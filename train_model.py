"""
train_model.py - trains the Placement Predictor model and saves it.

Run:  python train_model.py

What it does (in order):
 1. Loads sample_data.csv (creates it first if it does not exist).
 2. Checks the data is usable (enough rows, both classes present).
 3. Splits into train/test sets (80/20, stratified, fixed random seed).
 4. Builds ONE pipeline: StandardScaler + LogisticRegression.
    The scaler is fitted on the TRAINING split only (prevents data leakage).
 5. Evaluates on the held-out TEST split (accuracy, precision, recall, F1,
    confusion matrix) and runs 5-fold cross-validation on the training split.
 6. Saves the whole pipeline + metadata to models/placement_model.joblib.

No metric is hardcoded - everything printed/saved is computed here.
NOTE: the bundled dataset is SYNTHETIC, so these metrics describe how well the
model learned the synthetic rules, NOT real-world placement accuracy.
"""

import csv
import json
import os
import sys
from collections import Counter
from datetime import datetime

import joblib
import numpy as np
import sklearn
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import (accuracy_score, confusion_matrix, f1_score,
                             precision_score, recall_score)
from sklearn.model_selection import StratifiedKFold, cross_val_score, train_test_split
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler

from ml_utils import (DATA_PATH, FEATURE_COLUMNS, MODEL_PATH, NEGATIVE_LABEL,
                      POSITIVE_LABEL, TARGET_COLUMN)

RANDOM_SEED = 42
TEST_SIZE = 0.2
MIN_ROWS = 100          # below this, evaluation would be unreliable
MIN_CLASS_ROWS = 20     # each class needs at least this many rows


def load_data():
    """Read sample_data.csv with the csv module. Returns (X array, y array)."""
    if not os.path.exists(DATA_PATH):
        print("sample_data.csv not found - generating the synthetic dataset first...")
        from generate_sample_data import generate, write_csv
        write_csv(generate(), DATA_PATH)
    with open(DATA_PATH, newline="") as f:
        reader = csv.DictReader(f)
        header = reader.fieldnames or []
        missing = [c for c in FEATURE_COLUMNS + [TARGET_COLUMN] if c not in header]
        if missing:
            sys.exit(f"ERROR: sample_data.csv is missing columns: {missing}")
        X, y = [], []
        for row in reader:
            try:
                X.append([float(row[c]) for c in FEATURE_COLUMNS])
            except (TypeError, ValueError):
                continue  # skip rows with missing / non-numeric values
            y.append((row[TARGET_COLUMN] or "").strip())
    return np.array(X, dtype=float), np.array(y)


def main():
    X, y = load_data()
    counts = Counter(y.tolist())
    print(f"Loaded {len(y)} rows.  Class counts: {dict(counts)}\n")

    # --- Dataset suitability checks (report limitations honestly) ---------
    if len(y) < MIN_ROWS:
        sys.exit(f"ERROR: only {len(y)} rows; need at least {MIN_ROWS} for a "
                 "meaningful train/test evaluation. Training aborted.")
    if set(counts) != {POSITIVE_LABEL, NEGATIVE_LABEL} or min(counts.values()) < MIN_CLASS_ROWS:
        sys.exit("ERROR: both 'Placed' and 'Not Placed' need at least "
                 f"{MIN_CLASS_ROWS} rows. Training aborted.")

    # Split FIRST, so nothing about the test set leaks into training.
    X_train, X_test, y_train, y_test = train_test_split(
        X, y, test_size=TEST_SIZE, random_state=RANDOM_SEED, stratify=y)

    pipeline = Pipeline([
        ("preprocess", StandardScaler()),
        ("classifier", LogisticRegression(max_iter=1000, random_state=RANDOM_SEED)),
    ])

    # Cross-validation on the TRAINING data only (scaler refit inside each fold).
    cv = StratifiedKFold(n_splits=5, shuffle=True, random_state=RANDOM_SEED)
    cv_scores = cross_val_score(pipeline, X_train, y_train, cv=cv, scoring="accuracy")

    pipeline.fit(X_train, y_train)
    y_pred = pipeline.predict(X_test)

    labels = [NEGATIVE_LABEL, POSITIVE_LABEL]
    cm = confusion_matrix(y_test, y_pred, labels=labels)
    metrics = {
        "accuracy": float(accuracy_score(y_test, y_pred)),
        "precision_placed": float(precision_score(y_test, y_pred, pos_label=POSITIVE_LABEL, zero_division=0)),
        "recall_placed": float(recall_score(y_test, y_pred, pos_label=POSITIVE_LABEL, zero_division=0)),
        "f1_placed": float(f1_score(y_test, y_pred, pos_label=POSITIVE_LABEL, zero_division=0)),
        "cv_accuracy_mean": float(cv_scores.mean()),
        "cv_accuracy_std": float(cv_scores.std()),
        "confusion_matrix": cm.tolist(),
        "confusion_matrix_labels": labels,
        "n_train": int(len(X_train)),
        "n_test": int(len(X_test)),
    }

    metadata = {
        "trained_at": datetime.now().isoformat(timespec="seconds"),
        "model_name": "Logistic Regression (with StandardScaler)",
        "data_source": "SYNTHETIC demonstration dataset (not real student records)",
        "feature_columns": FEATURE_COLUMNS,
        "classes": [str(c) for c in pipeline.classes_],
        "random_seed": RANDOM_SEED,
        "sklearn_version": sklearn.__version__,
        "metrics": metrics,
    }

    os.makedirs(os.path.dirname(MODEL_PATH), exist_ok=True)
    joblib.dump({"pipeline": pipeline, "metadata": metadata}, MODEL_PATH)
    with open(os.path.join(os.path.dirname(MODEL_PATH), "metrics.json"), "w") as f:
        json.dump(metadata, f, indent=2)

    print("=== Evaluation on held-out test set ===")
    print(f"Accuracy : {metrics['accuracy']:.3f}")
    print(f"Precision: {metrics['precision_placed']:.3f}  (class: Placed)")
    print(f"Recall   : {metrics['recall_placed']:.3f}  (class: Placed)")
    print(f"F1-score : {metrics['f1_placed']:.3f}  (class: Placed)")
    print(f"5-fold CV accuracy (train data): {metrics['cv_accuracy_mean']:.3f} "
          f"+/- {metrics['cv_accuracy_std']:.3f}")
    print(f"Confusion matrix (rows=actual, cols=predicted) {labels}:\n{cm}")
    print(f"\nModel saved to: {MODEL_PATH}")
    print("\nREMINDER: the dataset is SYNTHETIC. These numbers do NOT show "
          "real-world placement accuracy.")


if __name__ == "__main__":
    main()
