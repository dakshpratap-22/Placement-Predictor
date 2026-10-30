"""
app.py - Flask web application for the Placement Predictor.

Run:  python app.py
Then open http://127.0.0.1:5000 in your browser.

Layout of this project's logic:
  app.py          routes, validation, per-user data access
  db.py           schema + safe migration (users, predictions, simulations)
  auth_utils.py   registration validation, password hashing, login throttle
  reports.py      chart/comparison data built from SAVED records only
  ml_utils.py     feature list, skill parsing, model loading, prediction
"""

import csv
import io
import logging
import math
import os
import re
import secrets
import sqlite3
from datetime import datetime, timedelta
from functools import wraps

from flask import (Flask, Response, abort, flash, g, redirect, render_template,
                   request, send_from_directory, session, url_for)

import auth_utils
import db as dbmod
import reports
from ml_utils import (MODEL_PATH, NEGATIVE_LABEL, POSITIVE_LABEL,
                      FEATURE_COLUMNS, ModelNotAvailableError,
                      build_feature_frame, load_model_bundle, parse_skills,
                      predict_profile)
from reports import describe_changes, readiness_for  # noqa: F401  (re-exported)
from roles_config import ROLE_SKILLS

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

FEATURE_LABELS = {
    "cgpa": "CGPA",
    "tenth_pct": "10th %",
    "twelfth_pct": "12th %",
    "backlogs": "Backlogs",
    "projects": "Projects",
    "internships": "Internships",
    "skill_count": "Recognised skills",
}


# --------------------------------------------------------------------------
# Validation
# --------------------------------------------------------------------------
def _float_field(form, key, label, lo, hi, errors):
    raw = (form.get(key) or "").strip()
    if raw == "":
        errors[key] = f"{label} is required."
        return None
    try:
        val = float(raw)
    except ValueError:
        errors[key] = f"{label} must be a number."
        return None
    if math.isnan(val) or math.isinf(val):
        errors[key] = f"{label} must be a valid number."
        return None
    if not (lo <= val <= hi):
        errors[key] = f"{label} must be between {lo:g} and {hi:g}."
        return None
    return val


def _int_field(form, key, label, lo, hi, errors):
    raw = (form.get(key) or "").strip()
    if raw == "":
        errors[key] = f"{label} is required."
        return None
    if not re.fullmatch(r"\d+", raw):
        errors[key] = f"{label} must be a whole number (0 or more)."
        return None
    val = int(raw)
    if not (lo <= val <= hi):
        errors[key] = f"{label} must be between {lo} and {hi}."
        return None
    return val


def validate_profile(form, require_identity=True):
    """Validate a submitted form. Returns (clean_profile, errors).
    errors is a dict {field: message}; clean_profile is only complete when
    errors is empty."""
    errors = {}
    clean = {}

    if require_identity:
        name = re.sub(r"\s+", " ", (form.get("student_name") or "")).strip()
        if not name:
            errors["student_name"] = "Student name is required."
        elif len(name) > 60:
            errors["student_name"] = "Name must be 60 characters or fewer."
        elif not re.fullmatch(r"[A-Za-z][A-Za-z .'\-]*", name):
            errors["student_name"] = "Name may contain only letters, spaces, . ' and -."
        clean["student_name"] = name

        role = (form.get("target_role") or "").strip()
        if role not in ROLE_SKILLS:
            errors["target_role"] = "Please choose a target job role from the list."
        clean["target_role"] = role

    clean["cgpa"] = _float_field(form, "cgpa", "CGPA", 0, 10, errors)
    clean["tenth_pct"] = _float_field(form, "tenth_pct", "10th percentage", 0, 100, errors)
    clean["twelfth_pct"] = _float_field(form, "twelfth_pct", "12th percentage", 0, 100, errors)
    clean["backlogs"] = _int_field(form, "backlogs", "Backlogs", 0, 30, errors)
    clean["projects"] = _int_field(form, "projects", "Projects", 0, 30, errors)
    clean["internships"] = _int_field(form, "internships", "Internships", 0, 20, errors)

    skills_raw = (form.get("skills") or "").strip()
    unknown = []
    if len(skills_raw) > 300:
        errors["skills"] = "Skills text must be 300 characters or fewer."
        clean["skills"] = []
    else:
        clean["skills"], unknown = parse_skills(skills_raw)
    clean["unknown_skills"] = unknown
    return clean, errors


# --------------------------------------------------------------------------
# Explanations
# --------------------------------------------------------------------------
def explain_result(pred):
    label = pred["label"]
    if pred["supports_probability"]:
        p = pred["probability_placed"] * 100
        return (f"The model estimates a {p:.1f}% chance of '{POSITIVE_LABEL}' for this "
                f"profile and therefore predicts '{label}'. This estimate reflects patterns "
                "in a synthetic demonstration dataset only; it is not a guarantee.")
    return f"The model predicts '{label}'. This is an estimate, not a guarantee."


def top_factors(bundle, profile, n=3):
    """For a linear model, show which inputs pushed the estimate up/down
    (coefficient x standardised value). Returns [] if not available."""
    try:
        pipe = bundle["pipeline"]
        clf = pipe.named_steps["classifier"]
        scaled = pipe.named_steps["preprocess"].transform(build_feature_frame(profile))[0]
        classes = list(clf.classes_)
        sign = 1 if classes.index(POSITIVE_LABEL) == 1 else -1
        contrib = sign * clf.coef_[0] * scaled
        items = [(FEATURE_LABELS[f], float(c)) for f, c in zip(FEATURE_COLUMNS, contrib)]
        items.sort(key=lambda t: abs(t[1]), reverse=True)
        return [{"name": k, "direction": "raised" if v > 0 else "lowered"} for k, v in items[:n]]
    except Exception:
        return []


# --------------------------------------------------------------------------
# App factory
# --------------------------------------------------------------------------
SORTS = {
    "date_desc": lambda r: (r["created_at"], r["id"]),
    "date_asc": lambda r: (r["created_at"], r["id"]),
    "prob_desc": lambda r: (-1 if r["probability_placed"] is None else r["probability_placed"], r["id"]),
    "prob_asc": lambda r: (2 if r["probability_placed"] is None else r["probability_placed"], r["id"]),
}
SORT_LABELS = {
    "date_desc": "Newest first", "date_asc": "Oldest first",
    "prob_desc": "Highest probability first", "prob_asc": "Lowest probability first",
}


def _load_secret_key(instance_path):
    """SECRET_KEY comes from the environment. If it is not set (local development)
    a random key is generated once and kept in instance/.secret_key (git-ignored),
    so it is never hard-coded in source control."""
    key = os.environ.get("SECRET_KEY")
    if key:
        return key
    path = os.path.join(instance_path, ".secret_key")
    try:
        with open(path) as f:
            existing = f.read().strip()
        if existing:
            return existing
    except OSError:
        pass
    key = secrets.token_hex(32)
    try:
        with open(path, "w") as f:
            f.write(key)
    except OSError:
        pass  # read-only filesystem: fall back to a per-process key
    return key


def create_app(test_config=None):
    app = Flask(__name__, instance_relative_config=True)
    os.makedirs(app.instance_path, exist_ok=True)
    app.config.update(
        SECRET_KEY=_load_secret_key(app.instance_path),
        DATABASE=os.path.join(app.instance_path, "placement.db"),
        MODEL_PATH=MODEL_PATH,
        CSRF_ENABLED=True,
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE="Lax",
        SESSION_COOKIE_SECURE=os.environ.get("SESSION_COOKIE_SECURE", "0") == "1",
        PERMANENT_SESSION_LIFETIME=timedelta(hours=8),
        MAX_CONTENT_LENGTH=64 * 1024,
        PASSWORD_HASH_METHOD=None,        # None = Werkzeug default (scrypt)
        LOGIN_MAX_ATTEMPTS=5,
        LOGIN_WINDOW_SECONDS=600,
    )
    if test_config:
        app.config.update(test_config)
    app.logger.setLevel(logging.WARNING if app.testing else logging.INFO)

    dbmod.migrate(app.config["DATABASE"])
    throttle = auth_utils.LoginThrottle(app.config["LOGIN_MAX_ATTEMPTS"],
                                        app.config["LOGIN_WINDOW_SECONDS"])
    model_cache = {"key": None, "bundle": None}

    # ---------------- database helpers ----------------
    def get_db():
        if "db" not in g:
            g.db = dbmod.connect(app.config["DATABASE"])
        return g.db

    @app.teardown_appcontext
    def close_db(_exc):
        conn = g.pop("db", None)
        if conn is not None:
            conn.close()

    def row_to_profile(row):
        keys = row.keys()
        return {
            "id": row["id"],
            "student_name": row["student_name"],
            "cgpa": row["cgpa"], "tenth_pct": row["tenth_pct"], "twelfth_pct": row["twelfth_pct"],
            "backlogs": row["backlogs"], "projects": row["projects"], "internships": row["internships"],
            "skills": [s.strip() for s in row["skills"].split(",") if s.strip()],
            "target_role": row["target_role"],
            "predicted_class": row["predicted_class"],
            "probability_placed": row["probability_placed"],
            "created_at": row["created_at"],
            "source": row["source"],
            "model_version": row["model_version"] if "model_version" in keys else None,
        }

    def user_records(user_id):
        rows = get_db().execute(
            "SELECT * FROM predictions WHERE user_id = ? ORDER BY created_at, id", (user_id,)).fetchall()
        return [row_to_profile(r) for r in rows]

    def get_record_or_404(rec_id):
        """Only returns a record owned by the logged-in user. Another user's id
        gives the same 404 as a non-existent id (no information leak)."""
        row = get_db().execute("SELECT * FROM predictions WHERE id = ? AND user_id = ?",
                               (rec_id, g.user["id"])).fetchone()
        if row is None:
            abort(404)
        return row_to_profile(row)

    def save_prediction(profile, pred, version, source="prediction"):
        db = get_db()
        cur = db.execute(
            "INSERT INTO predictions (student_name, cgpa, tenth_pct, twelfth_pct, backlogs, "
            "projects, internships, skills, target_role, predicted_class, probability_placed, "
            "source, created_at, user_id, model_version) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (profile["student_name"], profile["cgpa"], profile["tenth_pct"], profile["twelfth_pct"],
             profile["backlogs"], profile["projects"], profile["internships"],
             ", ".join(profile["skills"]), profile["target_role"], pred["label"],
             pred["probability_placed"], source, datetime.now().isoformat(timespec="seconds"),
             g.user["id"], version))
        db.commit()
        return cur.lastrowid

    # ---------------- model helpers ----------------
    def get_bundle():
        path = app.config["MODEL_PATH"]
        mtime = os.path.getmtime(path) if os.path.exists(path) else None
        key = (path, mtime)
        if model_cache["key"] != key or model_cache["bundle"] is None:
            model_cache["bundle"] = load_model_bundle(path)
            model_cache["key"] = key
        return model_cache["bundle"]

    def model_ready():
        try:
            get_bundle()
            return True
        except ModelNotAvailableError:
            return False

    def model_version(bundle):
        """Identifier saved with every prediction: the training timestamp."""
        try:
            return "logreg-" + bundle["metadata"]["trained_at"]
        except (KeyError, TypeError):
            return None

    # ---------------- CSRF + one-time form tokens ----------------
    def csrf_token():
        if "_csrf" not in session:
            session["_csrf"] = secrets.token_hex(16)
        return session["_csrf"]

    def form_nonce():
        """One-time token for forms that create records, so a double click or a
        re-submitted form cannot store the same prediction twice."""
        nonce = secrets.token_hex(8)
        issued = session.get("nonces", [])
        issued.append(nonce)
        session["nonces"] = issued[-30:]
        return nonce

    def nonce_record(nonce):
        return session.get("used_nonces", {}).get(nonce) if nonce else None

    def mark_nonce(nonce, rec_id):
        if nonce:
            used = session.get("used_nonces", {})
            used[nonce] = rec_id
            session["used_nonces"] = dict(list(used.items())[-30:])

    @app.before_request
    def load_user():
        g.user = None
        uid = session.get("user_id")
        if uid is not None:
            row = get_db().execute("SELECT id, name, email FROM users WHERE id = ?", (uid,)).fetchone()
            if row is None:
                session.pop("user_id", None)
            else:
                g.user = row

    @app.before_request
    def check_csrf():
        if request.method == "POST" and app.config["CSRF_ENABLED"]:
            sent = request.form.get("_csrf", "")
            expected = session.get("_csrf", "")
            if not expected or not secrets.compare_digest(sent, expected):
                abort(400)

    @app.after_request
    def security_headers(resp):
        resp.headers.setdefault("X-Content-Type-Options", "nosniff")
        resp.headers.setdefault("X-Frame-Options", "DENY")
        resp.headers.setdefault("Referrer-Policy", "same-origin")
        resp.headers.setdefault(
            "Content-Security-Policy",
            "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; "
            "img-src 'self' data:; frame-ancestors 'none'; form-action 'self'")
        if request.endpoint in ("login", "register", "dashboard", "history", "reports"):
            resp.headers.setdefault("Cache-Control", "no-store")
        return resp

    @app.context_processor
    def inject_globals():
        return {"csrf_token": csrf_token, "form_nonce": form_nonce,
                "model_ready": model_ready(), "current_user": g.get("user"),
                "roles": list(ROLE_SKILLS.keys()), "year": datetime.now().year}

    def login_required(view):
        @wraps(view)
        def wrapped(*args, **kwargs):
            if g.user is None:
                flash("Please log in to continue.", "info")
                target = request.full_path.rstrip("?") if request.method == "GET" else None
                return redirect(url_for("login", next=target) if target else url_for("login"))
            return view(*args, **kwargs)
        return wrapped

    def setup_error_page(exc):
        return render_template("error.html", title="Model not ready",
                               message=str(exc), setup=True), 503

    # ---------------- authentication ----------------
    @app.route("/register", methods=["GET", "POST"])
    def register():
        if g.user:
            return redirect(url_for("dashboard"))
        if request.method == "GET":
            return render_template("register.html", values={}, errors={})
        clean, errors = auth_utils.validate_registration(request.form)
        values = {"name": clean["name"], "email": clean["email"]}
        if errors:
            return render_template("register.html", values=values, errors=errors), 400
        db = get_db()
        try:
            cur = db.execute(
                "INSERT INTO users (name, email, password_hash, created_at) VALUES (?,?,?,?)",
                (clean["name"], clean["email"],
                 auth_utils.hash_password(clean["password"], app.config["PASSWORD_HASH_METHOD"]),
                 datetime.now().isoformat(timespec="seconds")))
            db.commit()
        except sqlite3.IntegrityError:   # UNIQUE(email): duplicate (also covers a race)
            errors["email"] = "An account with this email already exists. Try logging in."
            return render_template("register.html", values=values, errors=errors), 409
        session.clear()
        session["user_id"] = cur.lastrowid
        session.permanent = True
        app.logger.info("New account created (user id %s)", cur.lastrowid)
        flash(f"Welcome, {clean['name']}! Your account has been created.", "success")
        return redirect(url_for("dashboard"))

    @app.route("/login", methods=["GET", "POST"])
    def login():
        if g.user:
            return redirect(url_for("dashboard"))
        nxt = request.values.get("next", "")
        if request.method == "GET":
            return render_template("login.html", values={}, errors={}, next=nxt)
        email = auth_utils.normalise_email(request.form.get("email"))
        password = request.form.get("password") or ""
        errors = {}
        if not email:
            errors["email"] = "Email is required."
        if not password:
            errors["password"] = "Password is required."
        if errors:
            return render_template("login.html", values={"email": email}, errors=errors, next=nxt), 400
        key = (email, request.remote_addr)
        if throttle.blocked(key):
            app.logger.warning("Login throttled for an account (too many failures)")
            flash("Too many failed attempts. Please wait a few minutes and try again.", "error")
            return render_template("login.html", values={"email": email}, errors={}, next=nxt), 429
        row = get_db().execute("SELECT id, name, password_hash FROM users WHERE email = ?",
                               (email,)).fetchone()
        if not auth_utils.verify_password(row["password_hash"] if row else None, password):
            throttle.record_failure(key)
            app.logger.info("Failed login attempt")
            flash("Invalid email or password.", "error")
            return render_template("login.html", values={"email": email}, errors={}, next=nxt), 401
        throttle.reset(key)
        session.clear()                       # new session on login (prevents fixation)
        session["user_id"] = row["id"]
        session.permanent = True
        flash(f"Welcome back, {row['name']}.", "success")
        return redirect(auth_utils.safe_next_url(nxt) or url_for("dashboard"))

    @app.route("/logout", methods=["POST"])
    def logout():
        session.clear()
        flash("You have been logged out.", "success")
        return redirect(url_for("index"))

    # ---------------- public pages ----------------
    @app.route("/")
    def index():
        return render_template("index.html")

    @app.route("/about")
    def about():
        meta = None
        try:
            meta = get_bundle()["metadata"]
        except ModelNotAvailableError:
            pass
        return render_template("about.html", meta=meta, role_skills=ROLE_SKILLS)

    @app.route("/favicon.ico")
    def favicon():
        return send_from_directory(os.path.join(app.root_path, "static", "img"),
                                   "favicon.ico", mimetype="image/x-icon")

    # ---------------- dashboard ----------------
    @app.route("/dashboard")
    @login_required
    def dashboard():
        records = user_records(g.user["id"])
        sim_count = get_db().execute("SELECT COUNT(*) FROM simulations WHERE user_id = ?",
                                     (g.user["id"],)).fetchone()[0]
        cards = reports.summary_cards(records, records, sim_count)
        recent = list(reversed(reports.chronological(records)))[:5]
        return render_template("dashboard.html", cards=cards, recent=recent, pos=POSITIVE_LABEL)

    @app.route("/latest/<kind>")
    @login_required
    def latest(kind):
        """Sidebar shortcuts: open the newest record's result/readiness/simulator."""
        targets = {"result": "result", "readiness": "readiness", "simulator": "simulator"}
        if kind not in targets:
            abort(404)
        preds = [r for r in user_records(g.user["id"]) if r["source"] == reports.SOURCE_PREDICTION]
        if not preds:
            flash("Make your first prediction to unlock this page.", "info")
            return redirect(url_for("predict"))
        return redirect(url_for(targets[kind], rec_id=reports.chronological(preds)[-1]["id"]))

    # ---------------- prediction ----------------
    @app.route("/predict", methods=["GET", "POST"])
    @login_required
    def predict():
        skill_names = sorted(set(s for v in ROLE_SKILLS.values() for s in v))
        if request.method == "GET":
            return render_template("predict.html", values={"student_name": g.user["name"]},
                                   errors={}, unknown=[], skill_names=skill_names)
        nonce = request.form.get("_nonce", "")
        done = nonce_record(nonce)
        if done is not None:               # form already submitted once: do not save again
            flash("This prediction was already saved.", "info")
            return redirect(url_for("result", rec_id=done))
        clean, errors = validate_profile(request.form)
        values = request.form.to_dict()
        if errors:
            return render_template("predict.html", values=values, errors=errors, unknown=[],
                                   skill_names=skill_names), 400
        try:
            bundle = get_bundle()
        except ModelNotAvailableError as exc:
            return setup_error_page(exc)
        pred = predict_profile(bundle, clean)
        rec_id = save_prediction(clean, pred, model_version(bundle))
        mark_nonce(nonce, rec_id)
        return redirect(url_for("result", rec_id=rec_id))

    @app.route("/result/<int:rec_id>")
    @login_required
    def result(rec_id):
        profile = get_record_or_404(rec_id)
        pred = {"label": profile["predicted_class"],
                "probability_placed": profile["probability_placed"],
                "supports_probability": profile["probability_placed"] is not None}
        factors, current_version = [], None
        try:
            bundle = get_bundle()
            factors = top_factors(bundle, profile)
            current_version = model_version(bundle)
        except ModelNotAvailableError:
            pass
        return render_template("result.html", p=profile, pred=pred,
                               explanation=explain_result(pred), factors=factors,
                               pos=POSITIVE_LABEL, version_text=reports.version_text(profile),
                               version_differs=current_version != profile["model_version"],
                               is_whatif=profile["source"] != reports.SOURCE_PREDICTION)

    @app.route("/readiness/<int:rec_id>")
    @login_required
    def readiness(rec_id):
        profile = get_record_or_404(rec_id)
        r = readiness_for(profile["target_role"], profile["skills"])
        return render_template("role_readiness.html", p=profile, r=r)

    # ---------------- what-if simulator ----------------
    @app.route("/simulator/<int:rec_id>", methods=["GET", "POST"])
    @login_required
    def simulator(rec_id):
        original = get_record_or_404(rec_id)  # never modified below
        base_values = {
            "cgpa": original["cgpa"], "tenth_pct": original["tenth_pct"],
            "twelfth_pct": original["twelfth_pct"], "backlogs": original["backlogs"],
            "projects": original["projects"], "internships": original["internships"],
            "skills": ", ".join(original["skills"]),
        }
        ctx = dict(p=original, values=base_values, errors={}, comparison=None, pos=POSITIVE_LABEL)
        try:
            bundle = get_bundle()
        except ModelNotAvailableError as exc:
            return setup_error_page(exc)
        orig_pred = predict_profile(bundle, original)  # recomputed with the same model
        if request.method == "POST":
            clean, errors = validate_profile(request.form, require_identity=False)
            ctx["values"] = request.form.to_dict()
            if errors:
                ctx["errors"] = errors
                return render_template("simulator.html", **ctx), 400
            hypo = dict(original)
            hypo.update({k: clean[k] for k in ("cgpa", "tenth_pct", "twelfth_pct",
                                               "backlogs", "projects", "internships", "skills")})
            hypo_pred = predict_profile(bundle, hypo)
            diff = None
            if orig_pred["supports_probability"] and hypo_pred["supports_probability"]:
                diff = (hypo_pred["probability_placed"] - orig_pred["probability_placed"]) * 100
            changes = describe_changes(original, hypo)
            ctx["comparison"] = {
                "orig": orig_pred, "hypo": hypo_pred, "diff": diff, "changes": changes,
                "class_changed": orig_pred["label"] != hypo_pred["label"],
                "hypo_profile": hypo, "unknown": clean["unknown_skills"],
            }
            ctx["chart"] = {
                "labels": ["Original", "Hypothetical"],
                "probability": [reports.pct(orig_pred["probability_placed"]),
                                reports.pct(hypo_pred["probability_placed"])],
            }
        return render_template("simulator.html", **ctx)

    @app.route("/simulator/<int:rec_id>/save", methods=["POST"])
    @login_required
    def simulator_save(rec_id):
        """Explicit user action: store the hypothetical profile as a NEW record and
        link it to the original in the `simulations` table. The original record is
        left untouched."""
        original = get_record_or_404(rec_id)
        nonce = request.form.get("_nonce", "")
        done = nonce_record(nonce)
        if done is not None:
            flash("This what-if scenario was already saved.", "info")
            return redirect(url_for("result", rec_id=done))
        clean, errors = validate_profile(request.form, require_identity=False)
        if errors:
            abort(400)
        try:
            bundle = get_bundle()
        except ModelNotAvailableError as exc:
            return setup_error_page(exc)
        version = model_version(bundle)
        hypo = dict(original)
        hypo.update({k: clean[k] for k in ("cgpa", "tenth_pct", "twelfth_pct",
                                           "backlogs", "projects", "internships", "skills")})
        hypo["student_name"] = (original["student_name"] + " (what-if)")[:80]
        orig_pred = predict_profile(bundle, original)
        hypo_pred = predict_profile(bundle, hypo)
        new_id = save_prediction(hypo, hypo_pred, version, source="what-if (saved by user)")
        db = get_db()
        db.execute(
            "INSERT INTO simulations (user_id, original_id, hypothetical_id, original_class, "
            "hypothetical_class, original_probability, hypothetical_probability, model_version, "
            "created_at) VALUES (?,?,?,?,?,?,?,?,?)",
            (g.user["id"], original["id"], new_id, orig_pred["label"], hypo_pred["label"],
             orig_pred["probability_placed"], hypo_pred["probability_placed"], version,
             datetime.now().isoformat(timespec="seconds")))
        db.commit()
        mark_nonce(nonce, new_id)
        flash("What-if scenario saved as a separate record.", "success")
        return redirect(url_for("result", rec_id=new_id))

    # ---------------- history, delete, compare ----------------
    @app.route("/history")
    @login_required
    def history():
        f_from = reports.parse_date(request.args.get("from"))
        f_to = reports.parse_date(request.args.get("to"))
        include_whatif = request.args.get("whatif") == "1"
        sort = request.args.get("sort", "date_desc")
        if sort not in SORTS:
            sort = "date_desc"
        records = user_records(g.user["id"])
        rows = reports.filter_records(records, f_from, f_to, include_whatif)
        rows.sort(key=SORTS[sort], reverse=sort.endswith("desc"))
        return render_template(
            "history.html", rows=rows[:200], total=len(rows), has_any=bool(records),
            f_from=request.args.get("from", ""), f_to=request.args.get("to", ""),
            include_whatif=include_whatif, sort=sort, sort_labels=SORT_LABELS,
            version_text=reports.version_text)

    @app.route("/history/<int:rec_id>/delete", methods=["GET", "POST"])
    @login_required
    def delete_record(rec_id):
        rec = get_record_or_404(rec_id)
        linked = get_db().execute(
            "SELECT COUNT(*) FROM simulations WHERE user_id = ? AND (original_id = ? OR hypothetical_id = ?)",
            (g.user["id"], rec_id, rec_id)).fetchone()[0]
        if request.method == "POST":
            db = get_db()
            db.execute("DELETE FROM predictions WHERE id = ? AND user_id = ?", (rec_id, g.user["id"]))
            db.commit()
            flash(f"Record #{rec_id} was deleted.", "success")
            return redirect(url_for("history"))
        return render_template("delete_confirm.html", p=rec, linked=linked)

    @app.route("/compare")
    @login_required
    def compare():
        ids = request.args.getlist("ids")
        a_raw, b_raw = request.args.get("a"), request.args.get("b")
        if ids and len(ids) != 2:
            flash("Please tick exactly two records to compare.", "error")
            return redirect(url_for("history"))
        if len(ids) == 2:
            a_raw, b_raw = ids
        records = user_records(g.user["id"])
        by_id = {r["id"]: r for r in records}
        if not a_raw and not b_raw:
            preds = reports.chronological([r for r in records if r["source"] == reports.SOURCE_PREDICTION])
            if len(preds) >= 2:
                a_raw, b_raw = str(preds[-2]["id"]), str(preds[-1]["id"])
        try:
            a_id, b_id = int(a_raw), int(b_raw)
        except (TypeError, ValueError):
            a_id = b_id = None
        if a_id is None or a_id not in by_id or b_id not in by_id:
            if len(records) < 2:
                flash("You need at least two saved records to compare. Make another prediction first.", "info")
            else:
                flash("Please pick two of your own saved records to compare.", "error")
            return redirect(url_for("history"))
        if a_id == b_id:
            flash("Please select two different records.", "error")
            return redirect(url_for("history"))
        a, b = by_id[a_id], by_id[b_id]
        if (a["created_at"], a["id"]) > (b["created_at"], b["id"]):
            a, b = b, a                           # always earlier -> later
        cmp = reports.pair_comparison(a, b)
        timeline = [r for r in records if r["source"] == reports.SOURCE_PREDICTION]
        chart = {
            "pair": {
                "a_label": reports.label_for(a), "b_label": reports.label_for(b),
                "groups": reports.feature_groups(a, b),
                "probability": [reports.pct(a["probability_placed"]), reports.pct(b["probability_placed"])],
                "classes": [a["predicted_class"], b["predicted_class"]],
            },
            "timeline": reports.timeline_groups(timeline) if len(timeline) >= 2 else [],
        }
        return render_template("compare.html", a=a, b=b, cmp=cmp, chart=chart,
                               version_text=reports.version_text, all_records=list(reversed(records)))

    # ---------------- graphical reports ----------------
    def _report_context():
        records = user_records(g.user["id"])
        by_id = {r["id"]: r for r in records}
        f_from = reports.parse_date(request.args.get("from"))
        f_to = reports.parse_date(request.args.get("to"))
        include_whatif = request.args.get("whatif") == "1"
        in_range = reports.filter_records(records, f_from, f_to, include_whatif)
        return records, by_id, f_from, f_to, include_whatif, in_range

    @app.route("/reports")
    @login_required
    def reports_page():
        records, by_id, f_from, f_to, include_whatif, in_range = _report_context()
        db = get_db()
        sims = [dict(r) for r in db.execute(
            "SELECT * FROM simulations WHERE user_id = ? ORDER BY created_at DESC, id DESC",
            (g.user["id"],)).fetchall()]
        cards = reports.summary_cards(records, in_range, len(sims))
        ctx = {"cards": cards, "f_from": request.args.get("from", ""), "f_to": request.args.get("to", ""),
               "include_whatif": include_whatif, "records": list(reversed(records)),
               "sims": sims, "has_data": bool(records), "version_text": reports.version_text}
        preds = reports.chronological([r for r in in_range if r["source"] == reports.SOURCE_PREDICTION]
                                      or in_range)
        chart = {"trend": reports.trend_data(in_range), "distribution": reports.distribution(in_range)}

        # Current vs previous (or two records chosen by the user)
        def pick(name):
            try:
                v = int(request.args.get(name, ""))
            except ValueError:
                return None
            return by_id.get(v)
        a, b = pick("a"), pick("b")
        if a is None or b is None:
            a = b = None
            if len(preds) >= 2:
                a, b = preds[-2], preds[-1]
        ctx["pair_a"], ctx["pair_b"] = a, b
        if a and b and a["id"] != b["id"]:
            if (a["created_at"], a["id"]) > (b["created_at"], b["id"]):
                a, b = b, a
            ctx["pair_a"], ctx["pair_b"] = a, b
            ctx["cmp"] = reports.pair_comparison(a, b)
            chart["pair"] = {
                "a_label": reports.label_for(a), "b_label": reports.label_for(b),
                "probability": [reports.pct(a["probability_placed"]), reports.pct(b["probability_placed"])],
                "classes": [a["predicted_class"], b["predicted_class"]],
                "groups": reports.feature_groups(a, b),
            }
        else:
            ctx["pair_a"] = ctx["pair_b"] = None
        if len(preds) >= 2:
            chart["timeline"] = reports.timeline_groups(preds)

        # What-if simulation comparison (saved simulations only)
        try:
            sim_id = int(request.args.get("sim", ""))
        except ValueError:
            sim_id = sims[0]["id"] if sims else None
        sim = next((s for s in sims if s["id"] == sim_id), sims[0] if sims else None)
        ctx["sim"] = sim
        if sim and sim["original_id"] in by_id and sim["hypothetical_id"] in by_id:
            chart["whatif"] = reports.whatif_data(by_id[sim["original_id"]], by_id[sim["hypothetical_id"]], sim)

        # Role-based readiness (checklist coverage, NOT placement probability)
        base = pick("rr") or (reports.chronological([r for r in records if r["source"] == reports.SOURCE_PREDICTION])[-1:] or [None])[0]
        role = request.args.get("role")
        if role not in ROLE_SKILLS:
            role = base["target_role"] if base else None
        ctx["readiness_base"], ctx["readiness_role"] = base, role
        if base and role:
            chart["readiness"] = reports.readiness_chart(role, base["skills"])
        ctx["chart"] = chart
        return render_template("reports.html", **ctx)

    @app.route("/reports/export.csv")
    @login_required
    def export_csv():
        _records, _by_id, _f, _t, _w, in_range = _report_context()

        def safe(v):  # neutralise spreadsheet formula injection
            s = "" if v is None else str(v)
            return "'" + s if s[:1] in ("=", "+", "-", "@") else s
        buf = io.StringIO()
        w = csv.writer(buf)
        w.writerow(["id", "saved_at", "record_type", "student_name", "target_role", "cgpa", "tenth_pct",
                    "twelfth_pct", "backlogs", "projects", "internships", "recognised_skills",
                    "model_prediction", "probability_placed_percent", "model_version"])
        for r in reports.chronological(in_range):
            w.writerow([r["id"], r["created_at"],
                        "model prediction" if r["source"] == reports.SOURCE_PREDICTION else "saved what-if (hypothetical)",
                        safe(r["student_name"]), safe(r["target_role"]), r["cgpa"], r["tenth_pct"],
                        r["twelfth_pct"], r["backlogs"], r["projects"], r["internships"],
                        safe("; ".join(r["skills"])), r["predicted_class"],
                        "" if r["probability_placed"] is None else round(r["probability_placed"] * 100, 1),
                        safe(r["model_version"] or "unknown")])
        return Response(buf.getvalue(), mimetype="text/csv", headers={
            "Content-Disposition": 'attachment; filename="placement_predictions.csv"'})

    # ---------------- error handlers ----------------
    @app.errorhandler(400)
    def bad_request(_e):
        return render_template("error.html", title="Bad request",
                               message="The request could not be processed. Please go back and "
                                       "try again (your session may have expired)."), 400

    @app.errorhandler(404)
    def not_found(_e):
        return render_template("error.html", title="Page not found",
                               message="That page or record does not exist."), 404

    @app.errorhandler(413)
    def too_large(_e):
        return render_template("error.html", title="Request too large",
                               message="The submitted data was too large."), 413

    @app.errorhandler(sqlite3.Error)
    def db_error(exc):
        app.logger.exception("Database error: %s", exc)
        return render_template("error.html", title="Database problem",
                               message="A database error occurred. Please try again. If it keeps "
                                       "happening, restart the app (the schema is upgraded "
                                       "automatically on start-up)."), 500

    @app.errorhandler(500)
    def server_error(_e):
        return render_template("error.html", title="Something went wrong",
                               message="An unexpected error occurred. Please try again."), 500

    import admin            # Admin dashboard (see admin.py)
    admin.init_app(app)

    return app


app = create_app()

if __name__ == "__main__":
    # Debug mode is OFF by default. Enable only while developing:
    #   PowerShell:  $env:FLASK_DEBUG="1"; python app.py
    # NEVER run with debug on in production - it exposes an interactive console.
    debug = os.environ.get("FLASK_DEBUG", "0") == "1"
    app.run(host="127.0.0.1", port=5000, debug=debug)
