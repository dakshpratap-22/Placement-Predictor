"""
generate_sample_data.py - creates sample_data.csv

IMPORTANT: THIS DATA IS SYNTHETIC (computer-generated). It is NOT a record of
real students or real placements. It exists only so the project can demonstrate
an end-to-end ML pipeline. The relationships in it (e.g. higher CGPA -> more
likely "Placed") were written by the author of this script, so a model trained
on it learns those assumptions - it does NOT prove anything about real-world
placement outcomes.

Run:  python generate_sample_data.py
"""

import csv

import numpy as np

SEED = 42
N_ROWS = 800


def generate(n=N_ROWS, seed=SEED):
    rng = np.random.default_rng(seed)

    cgpa = np.clip(rng.normal(7.2, 1.1, n), 4.5, 10.0).round(2)
    tenth = np.clip(rng.normal(78, 9, n), 45, 99).round(1)
    twelfth = np.clip(rng.normal(75, 10, n), 45, 99).round(1)
    backlogs = np.clip(rng.poisson(0.6, n), 0, 8)
    projects = np.clip(rng.poisson(2.0, n), 0, 8)
    internships = np.clip(rng.poisson(0.8, n), 0, 4)
    skill_count = np.clip(rng.poisson(4.0, n), 0, 12)

    # Assumed (author-defined) relationship between profile and placement.
    score = (
        1.1 * (cgpa - 7.0)
        + 0.02 * (tenth - 75)
        + 0.015 * (twelfth - 72)
        - 0.9 * backlogs
        + 0.35 * projects
        + 0.6 * internships
        + 0.25 * skill_count
        - 1.6
    )
    # Random noise so the data is not perfectly separable (real life is messy).
    score += rng.normal(0, 1.2, n)
    prob = 1 / (1 + np.exp(-score))
    placed = np.where(rng.random(n) < prob, "Placed", "Not Placed")

    cols = ["cgpa", "tenth_pct", "twelfth_pct", "backlogs", "projects",
            "internships", "skill_count", "placed"]
    data = [cgpa, tenth, twelfth, backlogs, projects, internships, skill_count, placed]
    return [dict(zip(cols, (v.item() if hasattr(v, "item") else v for v in row)))
            for row in zip(*data)]


def write_csv(rows, path="sample_data.csv"):
    with open(path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)


if __name__ == "__main__":
    rows = generate()
    write_csv(rows)
    print(f"Wrote sample_data.csv with {len(rows)} SYNTHETIC rows.")
    for label in ("Placed", "Not Placed"):
        print(label, sum(r["placed"] == label for r in rows))
