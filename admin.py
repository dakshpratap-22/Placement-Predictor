"""
admin.py - read-mostly Admin dashboard (a Flask Blueprint).

Who is an admin?  Any registered user whose e-mail is listed in the
ADMIN_EMAILS environment variable (comma separated). There is no built-in
admin password and no database change. Everyone else gets a 404 for /admin/*,
so the page does not even reveal that it exists.

    PowerShell:  $env:ADMIN_EMAILS="you@example.com"; python app.py
    Linux/Mac:   ADMIN_EMAILS="you@example.com" python app.py

What it shows (all computed from the real database, nothing invented):
account totals, prediction counts, model-estimate distribution, daily
activity, usage per target role, the model's training metadata and a user
list with per-user prediction COUNTS. It deliberately does not display other
users' individual academic profiles.
The only write action is "delete a user account" (confirmation page, CSRF
protected, cannot delete yourself or another admin).

Hook-up (two lines in app.py, just before `return app`):
    import admin
    admin.init_app(app)
"""
import logging
import os
from datetime import datetime, timedelta
from functools import wraps

from flask import (Blueprint, abort, current_app, flash, g, redirect,
                   render_template, request, url_for)

import db as dbmod
import ml_utils
from roles_config import ROLE_SKILLS

bp = Blueprint("admin", __name__, url_prefix="/admin")
log = logging.getLogger("placement.admin")

USER_LIST_LIMIT = 200
DAYS_SHOWN = 30


# ---------------------------------------------------------------- helpers
def admin_emails(app=None):
    """Lower-case set of admin e-mails. A TESTING/config value wins over the env var."""
    app = app or current_app
    raw = app.config.get("ADMIN_EMAILS")
    if raw is None:
        raw = os.environ.get("ADMIN_EMAILS", "")
    if isinstance(raw, (list, tuple, set)):
        raw = ",".join(raw)
    return {e.strip().lower() for e in raw.split(",") if e.strip()}


def is_admin(user):
    return bool(user) and user["email"].lower() in admin_emails()


def _db():
    if "db" not in g:                      # app.py closes g.db after every request
        g.db = dbmod.connect(current_app.config["DATABASE"])
    return g.db


def admin_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if g.user is None:
            flash("Please log in to continue.", "info")
            target = request.full_path.rstrip("?") if request.method == "GET" else None
            return redirect(url_for("login", next=target) if target else url_for("login"))
        if not is_admin(g.user):
            abort(404)                     # do not reveal that an admin area exists
        return view(*args, **kwargs)
    return wrapped


def _one(sql, args=()):
    return _db().execute(sql, args).fetchone()[0]


# ---------------------------------------------------------------- dashboard data
def collect_stats():
    now = datetime.now()
    week_ago = (now - timedelta(days=7)).isoformat(timespec="seconds")

    total_users = _one("SELECT COUNT(*) FROM users")
    new_users_7d = _one("SELECT COUNT(*) FROM users WHERE created_at >= ?", (week_ago,))
    predictions = _one("SELECT COUNT(*) FROM predictions WHERE source = 'prediction' AND user_id IS NOT NULL")
    whatif_records = _one("SELECT COUNT(*) FROM predictions WHERE source != 'prediction' AND user_id IS NOT NULL")
    simulations = _one("SELECT COUNT(*) FROM simulations")
    legacy_rows = _one("SELECT COUNT(*) FROM predictions WHERE user_id IS NULL")
    preds_7d = _one("SELECT COUNT(*) FROM predictions WHERE source = 'prediction' AND created_at >= ?", (week_ago,))
    avg_prob = _db().execute(
        "SELECT AVG(probability_placed) FROM predictions "
        "WHERE source = 'prediction' AND probability_placed IS NOT NULL AND user_id IS NOT NULL").fetchone()[0]

    # outcome distribution (model labels, not real outcomes)
    dist = {r["predicted_class"]: r["n"] for r in _db().execute(
        "SELECT predicted_class, COUNT(*) AS n FROM predictions "
        "WHERE source = 'prediction' AND user_id IS NOT NULL GROUP BY predicted_class")}
    labels = [ml_utils.POSITIVE_LABEL, ml_utils.NEGATIVE_LABEL]
    distribution = {"labels": labels, "counts": [dist.get(k, 0) for k in labels]}

    # predictions per day for the last DAYS_SHOWN days (days with none are a real 0)
    start = (now - timedelta(days=DAYS_SHOWN - 1)).date()
    per_day = {r["d"]: r["n"] for r in _db().execute(
        "SELECT substr(created_at, 1, 10) AS d, COUNT(*) AS n FROM predictions "
        "WHERE source = 'prediction' AND user_id IS NOT NULL AND created_at >= ? GROUP BY d",
        (start.isoformat(),))}
    days = [(start + timedelta(days=i)).isoformat() for i in range(DAYS_SHOWN)]
    daily = {"labels": days, "counts": [per_day.get(d, 0) for d in days]}

    # usage per target role (every configured role is listed, even with 0)
    per_role = {r["target_role"]: r["n"] for r in _db().execute(
        "SELECT target_role, COUNT(*) AS n FROM predictions "
        "WHERE source = 'prediction' AND user_id IS NOT NULL GROUP BY target_role")}
    roles = [{"role": name, "skills": skills, "count": per_role.get(name, 0), "configured": True}
             for name, skills in ROLE_SKILLS.items()]
    for name, n in per_role.items():              # roles removed from roles_config.py later
        if name not in ROLE_SKILLS:
            roles.append({"role": name, "skills": [], "count": n, "configured": False})
    roles.sort(key=lambda r: (-r["count"], r["role"]))
    top = max([r["count"] for r in roles] + [1])
    for r in roles:
        r["share"] = round(100 * r["count"] / top)

    # model information
    model = None
    try:
        meta = ml_utils.load_model_bundle(current_app.config.get("MODEL_PATH", ml_utils.MODEL_PATH))["metadata"]
        model = {"name": meta.get("model_name"), "trained_at": meta.get("trained_at"),
                 "data_source": meta.get("data_source"), "metrics": meta.get("metrics") or {}}
    except ml_utils.ModelNotAvailableError:
        pass

    return {
        "cards": {"total_users": total_users, "new_users_7d": new_users_7d, "predictions": predictions,
                  "preds_7d": preds_7d, "whatif_records": whatif_records, "simulations": simulations,
                  "avg_prob": None if avg_prob is None else round(avg_prob * 100, 1),
                  "legacy_rows": legacy_rows},
        "distribution": distribution, "daily": daily, "roles": roles, "model": model,
    }


def collect_users(query):
    sql = ("SELECT u.id, u.name, u.email, u.created_at, "
           "COUNT(CASE WHEN p.source = 'prediction' THEN 1 END) AS predictions, "
           "MAX(p.created_at) AS last_activity "
           "FROM users u LEFT JOIN predictions p ON p.user_id = u.id ")
    args = []
    if query:
        like = "%" + query.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
        sql += "WHERE u.name LIKE ? ESCAPE '\\' OR u.email LIKE ? ESCAPE '\\' "
        args += [like, like]
    sql += "GROUP BY u.id ORDER BY u.created_at DESC, u.id DESC LIMIT ?"
    args.append(USER_LIST_LIMIT)
    admins = admin_emails()
    out = []
    for r in _db().execute(sql, args).fetchall():
        d = dict(r)
        d["is_admin"] = d["email"].lower() in admins
        out.append(d)
    return out


# ---------------------------------------------------------------- routes
@bp.route("/")
@admin_required
def dashboard():
    q = (request.args.get("q") or "").strip()[:80]
    stats = collect_stats()
    users = collect_users(q)
    total_users = stats["cards"]["total_users"]
    chart = {"daily": stats["daily"], "distribution": stats["distribution"]}
    return render_template("admin_dashboard.html", stats=stats, users=users, q=q, chart=chart,
                           total_users=total_users, shown_limit=USER_LIST_LIMIT, days=DAYS_SHOWN)


@bp.route("/users/<int:user_id>/delete", methods=["GET", "POST"])
@admin_required
def delete_user(user_id):
    row = _db().execute("SELECT id, name, email, created_at FROM users WHERE id = ?", (user_id,)).fetchone()
    if row is None:
        abort(404)
    if row["id"] == g.user["id"]:
        flash("You cannot delete your own account here.", "error")
        return redirect(url_for("admin.dashboard"))
    if row["email"].lower() in admin_emails():
        flash("Admin accounts cannot be deleted from the dashboard.", "error")
        return redirect(url_for("admin.dashboard"))
    count = _one("SELECT COUNT(*) FROM predictions WHERE user_id = ?", (user_id,))
    if request.method == "POST":
        db = _db()
        db.execute("DELETE FROM users WHERE id = ?", (user_id,))   # ON DELETE CASCADE removes their records
        db.commit()
        log.warning("Admin %s deleted user id=%s (%s records)", g.user["id"], user_id, count)
        flash(f"Account {row['email']} and its {count} saved record(s) were deleted.", "success")
        return redirect(url_for("admin.dashboard"))
    return render_template("admin_delete_user.html", u=row, count=count)


def init_app(app):
    """Register the blueprint and expose `is_admin` to every template."""
    app.register_blueprint(bp)

    @app.context_processor
    def _admin_flag():
        return {"is_admin": is_admin(getattr(g, "user", None))}
