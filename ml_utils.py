"""
ml_utils.py - Shared logic used by BOTH train_model.py and app.py.

Keeping feature names, feature order and skill parsing in one place guarantees
that training and prediction use identical inputs (no train/serve mismatch).
"""

import os
import re

import joblib
import numpy as np

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
MODEL_PATH = os.path.join(BASE_DIR, "models", "placement_model.joblib")
DATA_PATH = os.path.join(BASE_DIR, "sample_data.csv")

# The exact columns (and order) the model is trained on and predicts with.
FEATURE_COLUMNS = [
    "cgpa",
    "tenth_pct",
    "twelfth_pct",
    "backlogs",
    "projects",
    "internships",
    "skill_count",
]
TARGET_COLUMN = "placed"
POSITIVE_LABEL = "Placed"
NEGATIVE_LABEL = "Not Placed"

# ---------------------------------------------------------------------------
# Skill catalogue: canonical skill name -> accepted spellings (aliases).
# Only skills in this catalogue are recognised; this is project-defined and
# easy to extend.
# ---------------------------------------------------------------------------
SKILL_CATALOG = {
    "Python": ["python", "python3", "py"],
    "SQL": ["sql", "mysql", "sqlite", "postgresql", "postgres"],
    "Git": ["git", "github", "version control"],
    "Problem Solving": ["problem solving", "problem-solving", "dsa",
                        "data structures", "algorithms", "competitive programming"],
    "Excel": ["excel", "ms excel", "microsoft excel", "spreadsheets"],
    "Data Visualization": ["data visualization", "data visualisation",
                           "data viz", "matplotlib", "tableau", "power bi",
                           "powerbi", "seaborn"],
    "HTML": ["html", "html5"],
    "CSS": ["css", "css3"],
    "JavaScript": ["javascript", "js", "java script", "es6"],
    "Flask": ["flask"],
    "Machine Learning": ["machine learning", "ml", "scikit-learn", "sklearn"],
    "Communication": ["communication", "communication skills"],
    "Java": ["java"],
    "C/C++": ["c", "c++", "cpp", "c/c++"],
}


def parse_skills(raw_text):
    """Turn free text like 'python, SQL; git' into a sorted list of canonical
    catalogue skills. Unknown words are returned separately."""
    if not raw_text:
        return [], []
    tokens = [t.strip().lower() for t in re.split(r"[,;\n|/]+", raw_text) if t.strip()]
    # "c/c++" contains a slash; handle it before splitting would break it.
    if re.search(r"c\s*/\s*c\+\+", raw_text.lower()):
        tokens.append("c/c++")
    alias_lookup = {}
    for canonical, aliases in SKILL_CATALOG.items():
        alias_lookup[canonical.lower()] = canonical
        for a in aliases:
            alias_lookup[a] = canonical
    recognised, unknown = set(), []
    for tok in tokens:
        tok = re.sub(r"\s+", " ", tok)
        if tok in alias_lookup:
            recognised.add(alias_lookup[tok])
        elif tok not in ("c", "c++", "cpp", "c/c++") and tok not in unknown:
            unknown.append(tok)
    return sorted(recognised), unknown


def build_feature_frame(profile):
    """Build the 1 x 7 numeric array the model expects, from a validated
    profile dict (columns in FEATURE_COLUMNS order). `profile['skills']` is a
    list of canonical skills. (Name kept for historical reasons; no pandas.)"""
    row = {
        "cgpa": float(profile["cgpa"]),
        "tenth_pct": float(profile["tenth_pct"]),
        "twelfth_pct": float(profile["twelfth_pct"]),
        "backlogs": int(profile["backlogs"]),
        "projects": int(profile["projects"]),
        "internships": int(profile["internships"]),
        "skill_count": len(profile.get("skills", [])),
    }
    return np.array([[row[c] for c in FEATURE_COLUMNS]], dtype=float)


class ModelNotAvailableError(Exception):
    """Raised when the trained model artifact is missing or unreadable."""


def load_model_bundle(path=MODEL_PATH):
    """Load the saved bundle: {'pipeline', 'metadata'}."""
    if not os.path.exists(path):
        raise ModelNotAvailableError(
            "The trained model file was not found. Open a terminal in the "
            "project folder and run:  python train_model.py"
        )
    try:
        bundle = joblib.load(path)
    except Exception as exc:  # corrupted / incompatible file
        raise ModelNotAvailableError(
            "The model file could not be loaded (it may be corrupted or made "
            "with a different scikit-learn version). Re-run:  python train_model.py"
        ) from exc
    if not isinstance(bundle, dict) or "pipeline" not in bundle:
        raise ModelNotAvailableError(
            "The model file has an unexpected format. Re-run:  python train_model.py"
        )
    return bundle


def predict_profile(bundle, profile):
    """Run a profile through the saved pipeline.
    Returns dict(label, probability_placed, supports_probability)."""
    pipeline = bundle["pipeline"]
    X = build_feature_frame(profile)
    label = str(pipeline.predict(X)[0])
    result = {"label": label, "probability_placed": None, "supports_probability": False}
    if hasattr(pipeline, "predict_proba"):
        classes = list(pipeline.classes_)
        if POSITIVE_LABEL in classes:
            proba = pipeline.predict_proba(X)[0][classes.index(POSITIVE_LABEL)]
            result["probability_placed"] = float(proba)
            result["supports_probability"] = True
    return result
