# Placement Predictor – Project Explanation (for report and viva)

## 1. Abstract
Placement Predictor is a Flask web application that uses a Logistic Regression model (scikit-learn) to estimate whether a student profile is likely to be "Placed" or "Not Placed". It adds two features beyond a basic predictor: **Role-Based Readiness Analysis** (skill checklist coverage for a chosen job role) and a **What-If Placement Simulator** (comparing the current profile with a hypothetical one using the same model). The model is trained on a clearly labelled **synthetic** dataset, so the project demonstrates a machine-learning workflow, not real-world placement accuracy.

## 2. Problem statement
Students often do not know how their academic profile and skills relate to placement outcomes or which skills they are missing. This project provides an interactive tool to explore such relationships, while stating clearly that its output is a demonstration estimate.

## 3. Objectives
1. Predict a placement outcome (and probability) with an ML model.
2. Show which role-specific skills are present or missing, with learning suggestions.
3. Let users explore hypothetical changes to their profile.
4. Store predictions in a local database.
5. Communicate limitations honestly.

## 4. Existing-system limitations (cautious)
Simple placement calculators may use fixed formulas, may not explain how they were built, and may not show the uncertainty of their results. This project instead uses a trained, reproducible model, reports its evaluation, and states its limits. (We do not claim that other systems are inaccurate; only that transparency is a goal here.)

## 5. Proposed system
A local web app: form → server-side validation → ML prediction → result page → readiness analysis / what-if simulation → SQLite history.

## 6. System architecture
```
Browser (HTML/CSS)  <-->  Flask app (app.py)
                              |-- validation (validate_profile)
                              |-- ml_utils.py  --> models/placement_model.joblib (scikit-learn pipeline)
                              |-- roles_config.py (skill checklists)
                              '-- SQLite (instance/placement.db)

Offline: generate_sample_data.py -> sample_data.csv -> train_model.py -> placement_model.joblib
```

## 7. Workflow
1. User opens `/predict` and submits the form.
2. Server validates every field; errors are shown and valid values kept.
3. Skills text is parsed into catalogue skills; `skill_count` is computed.
4. The saved pipeline predicts the class and P(Placed).
5. The record is saved in SQLite and the user is redirected to `/result/<id>`.
6. From the result page: Role Readiness (`/readiness/<id>`) or Simulator (`/simulator/<id>`).

## 8. Modules
| File | Role |
|---|---|
| `app.py` | Routes, validation, DB access, simulator and readiness logic, error handlers, CSRF check |
| `ml_utils.py` | Feature names/order, skill catalogue and parsing, model loading, `predict_profile` |
| `roles_config.py` | Editable role checklists, learning tips, project ideas |
| `generate_sample_data.py` | Creates the synthetic CSV |
| `train_model.py` | Splits, trains, evaluates, saves model |
| `templates/`, `static/style.css` | User interface |
| `tests/test_app.py` | Automated tests |

## 9. Database schema
Table `predictions`: `id` (PK, auto), `student_name`, `cgpa`, `tenth_pct`, `twelfth_pct`, `backlogs`, `projects`, `internships`, `skills`, `target_role`, `predicted_class`, `probability_placed` (nullable), `source` ("prediction" or "what-if (saved by user)"), `created_at`. All queries use `?` placeholders (parameterized), which prevents SQL injection. No passwords are stored.

## 10. ML training and prediction
- **Data:** 800 synthetic rows, 7 features + label. Generated with a fixed seed; the rule linking features to label (plus random noise) is written in `generate_sample_data.py`.
- **Model:** Logistic Regression inside a Pipeline with StandardScaler. Chosen because it is simple, fast, outputs probabilities and is easy to explain.
- **Split:** 80% train / 20% test, stratified, `random_state=42`. Scaler fitted only on training data (prevents leakage).
- **Metrics from the last training run in this build** (computed by `train_model.py`, test set of 160 rows): accuracy 0.706, precision 0.735, recall 0.709, F1 0.722 (class Placed); 5-fold CV accuracy 0.728 ± 0.024; confusion matrix [[52, 22], [25, 61]] (rows actual Not Placed/Placed). Re-running training prints the current values; the About page shows them live.
- **Meaning:** these numbers show how well the model fits *synthetic* data with deliberate noise. They are not real-world accuracy.
- **Prediction:** the app builds a one-row table with the same columns/order and calls `predict` and `predict_proba` on the saved pipeline.

## 11. What-If Simulation
Load the saved record (read-only) → user edits values → both profiles are scored by the same pipeline → show both results, differences in inputs and probability. The simulator never updates the original record; saving a hypothetical profile requires a separate explicit button and creates a new row. If the model result does not change, that is displayed.

## 12. Role-Based Readiness
`matched = required ∩ user skills`; `percent = matched / required × 100`. This measures checklist coverage only. It is separate from the ML probability and is not a validated employability score. Checklists are examples defined in `roles_config.py`.

## 13. Test plan and results
Automated tests (`python -m unittest discover -s tests -v`) cover: all pages load, valid prediction, invalid and missing fields, readiness (partial/full/zero match, aliases), simulator (unchanged, improved, worsened, invalid input, original not overwritten, explicit save creates a separate record), database creation and history, SQL-injection-like and HTML input, CSRF, and missing/corrupt model. In this build, 28 tests ran and all passed. Not tested: real Windows/PowerShell execution (tested on Linux), visual rendering in different browsers.

## 14. Limitations
Synthetic data; few features; skills reduced to a count; linear model; role lists illustrative; no authentication; not validated on real placements.

## 15. Future scope
Real anonymised data, per-skill features, model comparison, login, charts, PDF export, more roles.

## 16. Likely viva questions
1. **Is the data real?** No, it is synthetic and labelled so. It shows the workflow only.
2. **Why Logistic Regression?** Simple, gives probabilities, easy to explain; suits a mini-project.
3. **What is a pipeline?** Chained steps (scaling then classifier) saved together so prediction uses the same steps as training.
4. **What is data leakage and how did you avoid it?** Test information influencing training. We split first and fit the scaler on training data only.
5. **What do accuracy, precision, recall and F1 mean?** Accuracy = fraction correct; precision = of predicted Placed, how many truly Placed; recall = of truly Placed, how many found; F1 = balance of both.
6. **What is a confusion matrix?** A table of actual vs predicted classes showing the types of errors.
7. **Why a fixed random seed?** So results are reproducible.
8. **How does the simulator work?** It scores the original and edited profile with the same model and compares them; it does not alter saved data.
9. **Will more projects always increase the probability?** Not necessarily; the model decides, and the app shows the actual result.
10. **Is skill-match % the same as placement probability?** No; it is a simple checklist count.
11. **How do you prevent SQL injection?** Parameterized queries (`?`) and input validation.
12. **What if the model file is missing?** The app shows a setup message telling you to run `train_model.py`; it never invents a result.
13. **Why `debug=False`?** Debug mode exposes an interactive console and stack traces; it must not be on in production.
14. **Can this guarantee a job?** No. It is an estimate from synthetic data.
