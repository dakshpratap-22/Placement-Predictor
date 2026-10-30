"""
reports.py - pure functions that turn a user's saved prediction rows into the
data behind the dashboard charts, the history filters and the comparison page.

DATA INTEGRITY: every number returned here is read from saved records. Nothing
is invented, smoothed or "improved". With no records the functions return empty
structures so the pages can show an honest empty state.

A "record" is the dict produced by app.row_to_profile():
  id, student_name, cgpa, tenth_pct, twelfth_pct, backlogs, projects,
  internships, skills(list), target_role, predicted_class, probability_placed,
  source, created_at(ISO text), model_version(or None)
"""

from datetime import date, datetime

from ml_utils import NEGATIVE_LABEL, POSITIVE_LABEL
from roles_config import LEARNING_TIPS, PROJECT_IDEAS, ROLE_SKILLS

SOURCE_PREDICTION = "prediction"

# (key, label, group) - the six academic/experience inputs shown in comparisons.
FEATURES = [
    ("cgpa", "CGPA", "cgpa"),
    ("tenth_pct", "10th %", "percent"),
    ("twelfth_pct", "12th %", "percent"),
    ("backlogs", "Backlogs", "count"),
    ("projects", "Projects", "count"),
    ("internships", "Internships", "count"),
]
GROUP_TITLES = {
    "cgpa": "CGPA (scale 0-10)",
    "percent": "School percentages (%)",
    "count": "Backlogs, projects, internships (counts)",
}


# --------------------------------------------------------------------------
# Shared helpers (moved here from app.py so reports can use them)
# --------------------------------------------------------------------------
def readiness_for(role, skills):
    """Checklist coverage for a role. NOT a placement probability."""
    required = ROLE_SKILLS[role]
    matched = [s for s in required if s in skills]
    missing = [s for s in required if s not in skills]
    pct = round(100 * len(matched) / len(required)) if required else 0
    return {
        "role": role, "required": required, "matched": matched, "missing": missing,
        "percent": pct,
        "tips": [(s, LEARNING_TIPS.get(s, "Search for a beginner tutorial and build a small practice project."))
                 for s in missing],
        "ideas": PROJECT_IDEAS.get(role, []),
    }


def describe_changes(orig, hypo):
    """Human-readable list of differences between two profiles."""
    changes = []
    for key, label, _g in FEATURES:
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
# Dates and filtering
# --------------------------------------------------------------------------
def parse_date(text):
    """'YYYY-MM-DD' -> date, or None when empty/invalid."""
    try:
        return datetime.strptime((text or "").strip(), "%Y-%m-%d").date()
    except ValueError:
        return None


def record_date(rec):
    return datetime.fromisoformat(rec["created_at"]).date()


def filter_records(records, d_from=None, d_to=None, include_whatif=False):
    out = []
    for r in records:
        if not include_whatif and r["source"] != SOURCE_PREDICTION:
            continue
        d = record_date(r)
        if d_from and d < d_from:
            continue
        if d_to and d > d_to:
            continue
        out.append(r)
    return out


def chronological(records):
    return sorted(records, key=lambda r: (r["created_at"], r["id"]))


def pct(prob):
    return None if prob is None else round(prob * 100, 1)


def label_for(rec):
    """Short axis label with the prediction identifier and date/time."""
    return f"#{rec['id']} · {rec['created_at'].replace('T', ' ')[:16]}"


def version_text(rec):
    return rec.get("model_version") or "unknown (saved before versioning)"


# --------------------------------------------------------------------------
# Chart data
# --------------------------------------------------------------------------
def trend_data(records):
    """Probability of 'Placed' for each saved record over time."""
    recs = chronological(records)
    return {
        "labels": [label_for(r) for r in recs],
        "ids": [r["id"] for r in recs],
        "probability": [pct(r["probability_placed"]) for r in recs],
        "classes": [r["predicted_class"] for r in recs],
        "versions": [version_text(r) for r in recs],
    }


def distribution(records):
    placed = sum(1 for r in records if r["predicted_class"] == POSITIVE_LABEL)
    not_placed = sum(1 for r in records if r["predicted_class"] == NEGATIVE_LABEL)
    return {"labels": [POSITIVE_LABEL, NEGATIVE_LABEL], "counts": [placed, not_placed]}


def feature_groups(a, b):
    """Grouped-bar data for two records, split by scale so axes stay honest."""
    groups = []
    for gkey in ("cgpa", "percent", "count"):
        feats = [(k, lab) for k, lab, g in FEATURES if g == gkey]
        groups.append({
            "title": GROUP_TITLES[gkey],
            "labels": [lab for _k, lab in feats],
            "a": [float(a[k]) for k, _l in feats],
            "b": [float(b[k]) for k, _l in feats],
        })
    return groups


def timeline_groups(records):
    """Line-chart data of the six academic inputs over time, split by scale."""
    recs = chronological(records)
    labels = [label_for(r) for r in recs]
    groups = []
    for gkey in ("cgpa", "percent", "count"):
        feats = [(k, lab) for k, lab, g in FEATURES if g == gkey]
        groups.append({
            "title": GROUP_TITLES[gkey],
            "labels": labels,
            "series": [{"name": lab, "data": [float(r[k]) for r in recs]} for k, lab in feats],
        })
    return groups


def pair_comparison(a, b):
    """Side-by-side comparison of two saved records.

    Returns the per-field table, the list of changed fields and the cautions
    that must be shown next to any 'change' (versions differ, hypothetical
    records, and the reminder that a changed prediction is not proof of a real
    change in placement prospects).
    """
    rows = []
    for key, label, _g in FEATURES:
        va, vb = a[key], b[key]
        rows.append({"label": label, "a": va, "b": vb, "changed": float(va) != float(vb),
                     "delta": round(float(vb) - float(va), 2)})
    skills_changed = sorted(a["skills"]) != sorted(b["skills"])
    rows.append({"label": "Recognised skills", "a": ", ".join(a["skills"]) or "None",
                 "b": ", ".join(b["skills"]) or "None", "changed": skills_changed, "delta": None})
    rows.append({"label": "Target role", "a": a["target_role"], "b": b["target_role"],
                 "changed": a["target_role"] != b["target_role"], "delta": None})

    prob_delta = None
    if a["probability_placed"] is not None and b["probability_placed"] is not None:
        prob_delta = round((b["probability_placed"] - a["probability_placed"]) * 100, 1)

    notes = []
    if a.get("model_version") != b.get("model_version") or a.get("model_version") is None:
        notes.append("These records were produced by different (or unknown) model versions, so "
                     "their predictions may not be directly comparable.")
    if a["source"] != SOURCE_PREDICTION or b["source"] != SOURCE_PREDICTION:
        notes.append("At least one record is a saved what-if (hypothetical) profile, not a student's "
                     "own entered profile.")
    notes.append("A change in the predicted output does not prove that a student's actual placement "
                 "prospects improved. Both values are model estimates, not confirmed placement outcomes.")
    return {
        "rows": rows,
        "changed_fields": [r["label"] for r in rows if r["changed"]],
        "prob_delta": prob_delta,
        "class_changed": a["predicted_class"] != b["predicted_class"],
        "readiness_a": readiness_for(a["target_role"], a["skills"]),
        "readiness_b": readiness_for(b["target_role"], b["skills"]),
        "notes": notes,
        "same_record": a["id"] == b["id"],
    }


def whatif_data(original, hypothetical, sim):
    """Original vs hypothetical bars for one saved simulation."""
    return {
        "id": sim["id"],
        "labels": ["Original", "Hypothetical"],
        "probability": [pct(sim["original_probability"]), pct(sim["hypothetical_probability"])],
        "classes": [sim["original_class"], sim["hypothetical_class"]],
        "changes": describe_changes(original, hypothetical),
        "created_at": sim["created_at"],
        "version": sim["model_version"] or "unknown (saved before versioning)",
    }


def readiness_chart(role, skills):
    r = readiness_for(role, skills)
    return {"role": role, "matched": r["matched"], "missing": r["missing"],
            "percent": r["percent"], "counts": [len(r["matched"]), len(r["missing"])]}


def summary_cards(all_records, in_range, sim_count):
    preds = [r for r in all_records if r["source"] == SOURCE_PREDICTION]
    latest = chronological(preds)[-1] if preds else None
    versions = {r.get("model_version") for r in preds if r.get("model_version")}
    return {
        "total_predictions": len(preds),
        "saved_whatif_records": len(all_records) - len(preds),
        "records_in_range": len(in_range),
        "saved_simulations": sim_count,
        "model_versions": len(versions),
        "latest": latest,
    }
