"""
app.py - Flask web application for the Placement Predictor.

Run:  python app.py
Then open http://127.0.0.1:5000 in your browser.
"""

import math
import os
import re
import secrets
import sqlite3
from datetime import datetime

from flask import (Flask, abort, g, redirect, render_template, request,
                   session, url_for)

from ml_utils import (MODEL_PATH, NEGATIVE_LABEL, POSITIVE_LABEL,
                      FEATURE_COLUMNS, ModelNotAvailableError,
                      build_feature_frame, load_model_bundle, parse_skills,
                      predict_profile)
from roles_config import LEARNING_TIPS, PROJECT_IDEAS, ROLE_SKILLS

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

SCHEMA = """
CREATE TABLE IF NOT EXISTS predictions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    student_name TEXT NOT NULL,
    cgpa REAL NOT NULL,
    tenth_pct REAL NOT NULL,
    twelfth_pct REAL NOT NULL,
    backlogs INTEGER NOT NULL,
    projects INTEGER NOT NULL,
    internships INTEGER NOT NULL,
    skills TEXT NOT NULL,
    target_role TEXT NOT NULL,
    predicted_class TEXT NOT NULL,
    probability_placed REAL,
    source TEXT NOT NULL DEFAULT 'prediction',
    created_at TEXT NOT NULL
);
"""

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


def readiness_for(role, skills):
    required = ROLE_SKILLS[role]
    matched = [s for s in required if s in skills]
    missing = [s for s in required if s not in skills]
    pct = round(100 * len(matched) / len(required)) if required else 0
    return {
        "role": role,
        "required": required,
        "matched": matched,
        "missing": missing,
        "percent": pct,
        "tips": [(s, LEARNING_TIPS.get(s, "Search for a beginner tutorial and build a small practice project.")) for s in missing],
        "ideas": PROJECT_IDEAS.get(role, []),
    }


def describe_changes(orig, hypo):
    """List of human-readable changes between two profiles."""
    changes = []
    for key, label in (("cgpa", "CGPA"), ("tenth_pct", "10th %"), ("twelfth_pct", "12th %"),
                       ("backlogs", "Backlogs"), ("projects", "Projects"),
                       ("internships", "Internships")):
        if float(orig[key]) != float(hypo[key]):
            changes.append(f"{label}: {orig[key]:g} → {hypo[key]:g}")
    added = [s for s in hypo["skills"] if s not in orig["skills"]]
    removed = [s for s in orig["skills"] if s not in hypo["skills"]]
    if added:
        changes.append("Skills added: " + ", ".join(added))
    if removed:
        changes.append("Skills removed: " + ", ".join(removed))
    return changes


# --------------------------------------------------------------------------
# App factory
# --------------------------------------------------------------------------
def create_app(test_config=None):
    app = Flask(__name__, instance_relative_config=True)
    app.config.update(
        SECRET_KEY=os.environ.get("SECRET_KEY", "dev-only-change-me"),
        DATABASE=os.path.join(app.instance_path, "placement.db"),
        MODEL_PATH=MODEL_PATH,
        CSRF_ENABLED=True,
    )
    if test_config:
        app.config.update(test_config)
    os.makedirs(app.instance_path, exist_ok=True)

    model_cache = {"key": None, "bundle": None}

    # ---------------- database helpers ----------------
    def get_db():
        if "db" not in g:
            g.db = sqlite3.connect(app.config["DATABASE"])
            g.db.row_factory = sqlite3.Row
        return g.db

    @app.teardown_appcontext
    def close_db(_exc):
        db = g.pop("db", None)
        if db is not None:
            db.close()

    def init_db():
        conn = sqlite3.connect(app.config["DATABASE"])
        try:
            conn.executescript(SCHEMA)
            conn.commit()
        finally:
            conn.close()

    init_db()

    def save_prediction(profile, pred, source="prediction"):
        db = get_db()
        cur = db.execute(
            "INSERT INTO predictions (student_name, cgpa, tenth_pct, twelfth_pct, backlogs, "
            "projects, internships, skills, target_role, predicted_class, probability_placed, "
            "source, created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (profile["student_name"], profile["cgpa"], profile["tenth_pct"], profile["twelfth_pct"],
             profile["backlogs"], profile["projects"], profile["internships"],
             ", ".join(profile["skills"]), profile["target_role"], pred["label"],
             pred["probability_placed"], source, datetime.now().isoformat(timespec="seconds")))
        db.commit()
        return cur.lastrowid

    def row_to_profile(row):
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
        }

    def get_record_or_404(rec_id):
        row = get_db().execute("SELECT * FROM predictions WHERE id = ?", (rec_id,)).fetchone()
        if row is None:
            abort(404)
        return row_to_profile(row)

    # ---------------- model helper ----------------
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

    # ---------------- CSRF ----------------
    def csrf_token():
        if "_csrf" not in session:
            session["_csrf"] = secrets.token_hex(16)
        return session["_csrf"]

    @app.before_request
    def check_csrf():
        if request.method == "POST" and app.config["CSRF_ENABLED"]:
            sent = request.form.get("_csrf", "")
            expected = session.get("_csrf", "")
            if not expected or not secrets.compare_digest(sent, expected):
                abort(400)

    @app.context_processor
    def inject_globals():
        return {"csrf_token": csrf_token, "model_ready": model_ready(),
                "roles": list(ROLE_SKILLS.keys()), "year": datetime.now().year}

    def setup_error_page(exc):
        return render_template("error.html", title="Model not ready",
                               message=str(exc), setup=True), 503

    # ---------------- routes ----------------
    @app.route("/")
    def index():
        return render_template("index.html")

    @app.route("/predict", methods=["GET", "POST"])
    def predict():
        if request.method == "GET":
            return render_template("predict.html", values={}, errors={}, unknown=[],
                                   skill_names=sorted(set(s for v in ROLE_SKILLS.values() for s in v)))
        clean, errors = validate_profile(request.form)
        values = request.form.to_dict()
        if errors:
            return render_template("predict.html", values=values, errors=errors, unknown=[],
                                   skill_names=[]), 400
        try:
            bundle = get_bundle()
        except ModelNotAvailableError as exc:
            return setup_error_page(exc)
        pred = predict_profile(bundle, clean)
        rec_id = save_prediction(clean, pred)
        return redirect(url_for("result", rec_id=rec_id))

    @app.route("/result/<int:rec_id>")
    def result(rec_id):
        profile = get_record_or_404(rec_id)
        pred = {"label": profile["predicted_class"],
                "probability_placed": profile["probability_placed"],
                "supports_probability": profile["probability_placed"] is not None}
        factors = []
        try:
            factors = top_factors(get_bundle(), profile)
        except ModelNotAvailableError:
            pass
        return render_template("result.html", p=profile, pred=pred,
                               explanation=explain_result(pred), factors=factors,
                               pos=POSITIVE_LABEL)

    @app.route("/readiness/<int:rec_id>")
    def readiness(rec_id):
        profile = get_record_or_404(rec_id)
        r = readiness_for(profile["target_role"], profile["skills"])
        return render_template("role_readiness.html", p=profile, r=r)

    @app.route("/simulator/<int:rec_id>", methods=["GET", "POST"])
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
        return render_template("simulator.html", **ctx)

    @app.route("/simulator/<int:rec_id>/save", methods=["POST"])
    def simulator_save(rec_id):
        """Explicit user action: store the hypothetical profile as a NEW record.
        The original record is left untouched."""
        original = get_record_or_404(rec_id)
        clean, errors = validate_profile(request.form, require_identity=False)
        if errors:
            abort(400)
        try:
            bundle = get_bundle()
        except ModelNotAvailableError as exc:
            return setup_error_page(exc)
        hypo = dict(original)
        hypo.update({k: clean[k] for k in ("cgpa", "tenth_pct", "twelfth_pct",
                                           "backlogs", "projects", "internships", "skills")})
        hypo["student_name"] = (original["student_name"] + " (what-if)")[:80]
        new_id = save_prediction(hypo, predict_profile(bundle, hypo), source="what-if (saved by user)")
        return redirect(url_for("result", rec_id=new_id))

    @app.route("/history")
    def history():
        rows = get_db().execute(
            "SELECT * FROM predictions ORDER BY id DESC LIMIT 50").fetchall()
        return render_template("history.html", rows=[row_to_profile(r) for r in rows])

    @app.route("/about")
    def about():
        meta = None
        try:
            meta = get_bundle()["metadata"]
        except ModelNotAvailableError:
            pass
        return render_template("about.html", meta=meta, role_skills=ROLE_SKILLS)

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

    @app.errorhandler(sqlite3.Error)
    def db_error(_e):
        return render_template("error.html", title="Database problem",
                               message="A database error occurred. Delete the file in the "
                                       "'instance' folder and restart the app to recreate it."), 500

    @app.errorhandler(500)
    def server_error(_e):
        return render_template("error.html", title="Something went wrong",
                               message="An unexpected error occurred. Please try again."), 500

    return app


app = create_app()

if __name__ == "__main__":
    # Debug mode is OFF by default. Enable only while developing:
    #   PowerShell:  $env:FLASK_DEBUG="1"; python app.py
    # NEVER run with debug on in production - it exposes an interactive console.
    debug = os.environ.get("FLASK_DEBUG", "0") == "1"
    app.run(host="127.0.0.1", port=5000, debug=debug)
