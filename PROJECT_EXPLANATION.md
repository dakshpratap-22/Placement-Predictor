# Project Explanation - Placement Predictor (v2: accounts, history, analytics)

> The dataset is **synthetic**. All "Placed / Not Placed" values are model estimates, not confirmed outcomes. Nothing in this project guarantees a job.

## 1. Overview
A Flask web app where a logged-in student enters an academic profile, receives a machine-learning estimate of placement, and builds a private history of predictions. From that history the app draws charts and compares any two records. It also offers a what-if simulator and a skill-readiness checklist.

## 2. Architecture
```
Browser --HTTP--> Flask (app.py)
                    |-- auth_utils.py   validation, password hashing, throttle, safe redirects
                    |-- ml_utils.py     load pipeline, build feature row, predict
                    |-- reports.py      saved rows -> chart / comparison data (pure functions)
                    |-- db.py           schema + migration
                    '-- SQLite (instance/placement.db)    models/placement_model.joblib
Templates (Jinja2) render HTML; static/js draws charts on <canvas> from JSON embedded in the page.
```
Request flow: `before_request` loads the user from the session, then checks the CSRF token on POST; a route decorated `login_required` redirects anonymous users to `/login`; every database read of a record includes `AND user_id = ?`; `after_request` adds security headers.

## 3. Database design
- **users**: `id` PK, `name`, `email` (UNIQUE, stored lower-case), `password_hash`, `created_at`.
- **predictions**: original columns (`student_name, cgpa, tenth_pct, twelfth_pct, backlogs, projects, internships, skills, target_role, predicted_class, probability_placed, source, created_at`) + `user_id` (FK -> users, ON DELETE CASCADE) + `model_version`.
- **simulations**: `user_id`, `original_id`, `hypothetical_id` (FKs to predictions, cascade), original/hypothetical class and probability, `model_version`, `created_at`.
- Foreign keys are enforced with `PRAGMA foreign_keys=ON`. Queries use `?` placeholders.
- **Migration** (`db.migrate`): idempotent, keyed on `PRAGMA user_version` (now 2). For a v1 database that contains rows it first copies the file to `placement.db.bak-v1`, then only adds. Legacy rows keep `user_id = NULL`, so no user can see them. To adopt them manually: `UPDATE predictions SET user_id = <your user id> WHERE user_id IS NULL;`.
- **No duplicate on refresh**: the predict and simulator-save forms carry a one-time `_nonce`; re-posting the same form redirects to the already-saved record instead of inserting again.

## 4. Login workflow
1. **Register**: validate name, email format, password (8-128 chars, at least one letter and one number, confirmation matches); reject duplicate email (case-insensitive); store a Werkzeug hash (`scrypt` by default); log in.
2. **Login**: look up by email; compare with `check_password_hash`. Unknown email and wrong password give the same message and cost similar time (a dummy hash is checked). 5 failures in 10 minutes per (email, IP) gives HTTP 429. On success `session.clear()` first (prevents session fixation), then store `user_id`.
3. **Protected pages** redirect to `/login?next=...`; `next` is only honoured if it is a local path.
4. **Logout** is POST-only (with CSRF) and clears the session.
5. **CSRF**: a random token lives in the session and is a hidden `_csrf` field in every form; POSTs without it get HTTP 400.
6. **Secret key**: from `SECRET_KEY`, else generated once into `instance/.secret_key` (git-ignored).

## 5. ML workflow
`generate_sample_data.py` -> `sample_data.csv` (800 synthetic rows) -> `train_model.py` (80/20 stratified split, seed 42; `StandardScaler` + `LogisticRegression` pipeline; metrics; 5-fold CV) -> `models/placement_model.joblib` + `metrics.json`. At prediction time `ml_utils` builds a one-row feature array in the training column order and calls `predict` / `predict_proba`. The simulator uses the **same function**, so preprocessing is identical. The model version string `logreg-<trained_at>` is saved with every record. Build metrics (synthetic data): accuracy 0.706, precision 0.735, recall 0.709, F1 0.722, CV 0.728 +/- 0.024 - these describe fit to synthetic data only. If the model cannot be loaded the app shows a setup message (HTTP 503 on predict) and saves nothing.

Readiness % = matched checklist skills / required skills. It is **not** the model probability.

## 6. Graph workflow
`reports.py` converts the user's saved rows into plain dictionaries (trend, distribution, pair, timeline, what-if, readiness). The route embeds the dictionary as `<script type="application/json" id="chart-data">`. `report-pages.js` reads it and calls `charts.js` (`line`, `bar`, `doughnut`) to draw on `<canvas>`, with hover tooltips, HTML legends and a "view chart data as a table" fallback. Because the JSON is built only from database rows, no value is invented; with no rows the page shows an empty state instead of a chart. Saved what-if records are excluded from the trend/distribution unless the user ticks "include what-if", because they are hypothetical. I wrote the chart code myself (no Chart.js) because this build environment could not download packages; swapping in Chart.js later only means replacing `report-pages.js`, since the JSON contract stays the same.

## 7. Comparison workflow
History page: tick two records -> `GET /compare?ids=A&ids=B` (exactly two required). The route fetches both **scoped to the logged-in user** (foreign ids behave as "not found"), orders them by date, then `reports.pair_comparison` builds: changed fields, probability difference (percentage points), class change, readiness for both, and cautions (different model versions, what-if record involved, "a changed prediction does not prove real improvement"). The Reports page can also pick any two records, or defaults to latest vs previous.

## 8. Technologies and why
- **Flask** - small, easy to explain; app-factory pattern makes testing easy.
- **sqlite3** - no server to install; adequate for a single-machine mini-project.
- **scikit-learn Logistic Regression** - simple, outputs probabilities, explainable.
- **Werkzeug hashing** - salted, slow hashes; plain passwords are never stored.
- **Canvas charts** - no external dependency; data comes from the server as JSON.
- **unittest** - standard library test runner.

## 9. Demo steps
1. Run `python train_model.py`, then `python app.py`; open http://127.0.0.1:5000.
2. Register an account; note the logged-in sidebar.
3. Make a prediction with weak values (e.g. CGPA 5.8, 0 projects). Open the result.
4. Make a second prediction with stronger values.
5. Open **Prediction history**, tick both, press **Compare selected**; show changed fields and the caution banners.
6. Open **Analytics reports**: trend, distribution, current vs previous, academic charts, role readiness; use the date filter; export CSV; Print / save as PDF.
7. Open the **What-if simulator**, change values, run, save as a separate record; show it under "What-if simulation comparison".
8. Log out, register a second user, show their history is empty (isolation); try `/result/1` -> 404.
9. Delete a record (confirmation page).

## 9b. Admin dashboard and roles
`admin.py` is a Flask Blueprint. Admin = e-mail listed in the `ADMIN_EMAILS` environment variable (no default admin password, no schema change); non-admins get 404 so the area is not advertised. All figures are SQL aggregates over real rows. Account deletion relies on `ON DELETE CASCADE`. Target roles live only in `roles_config.py`; the role is not a model feature, so adding roles needs no retraining.

## 10. Testing
`python -m unittest discover -s tests -t . -v` - 100 tests, all passing when this document was written (covers auth, CSRF, isolation, history, comparison, chart data, empty states, migration, model failure, validation, plus the original feature tests). Charts were additionally opened in headless Chromium: all chart canvases painted with real data, no console errors, no horizontal scroll at 390 px width. **Not tested**: Windows/PowerShell run, Safari/Firefox, screen-reader behaviour, behaviour behind several gunicorn workers.

## 11. Limitations and future scope
Synthetic data; few features; linear model; illustrative role lists; no real-outcome recording; in-memory login throttle; no password reset / email verification; PDF export via browser print. Future: real anonymised data, outcome tracking, per-skill features, model comparison, password reset.

## 12. Likely viva questions
1. **Is the data real?** No, it is synthetic and labelled so; it demonstrates the workflow.
2. **Why Logistic Regression?** Simple, gives probabilities, easy to explain.
3. **What is a pipeline?** Scaling + classifier saved as one object so prediction repeats training steps exactly.
4. **How did you avoid data leakage?** Split first; scaler fitted on training data only; CV refits inside each fold.
5. **Accuracy vs precision vs recall vs F1?** Fraction correct; of predicted Placed how many truly were; of true Placed how many found; balance of the last two.
6. **How are passwords stored?** As salted Werkzeug hashes (scrypt); never in plain text.
7. **What is CSRF and how do you stop it?** A forged cross-site form submission using the user's cookie; every form carries a secret per-session token the server checks.
8. **How do you stop one user seeing another's records?** Every query filters by `user_id`; other users' ids return 404; tests cover it.
9. **Why store `model_version`?** After retraining, old and new predictions may not be comparable; the app warns.
10. **Does a higher probability on a later record mean the student improved?** No; it means the model's estimate for the new inputs differs. The app says so.
11. **Is readiness % the same as probability?** No; it is checklist coverage.
12. **How do you prevent SQL injection?** Parameterized queries and validation.
13. **What happens on page refresh after predicting?** The redirect-after-POST pattern plus a one-time nonce prevents duplicate rows.
14. **How did you upgrade the old database safely?** Additive migration, backup copy first, nothing deleted.
15. **Why `debug=False`?** Debug mode exposes an interactive console.
16. **Can this guarantee a job?** No; it is an estimate from synthetic data.
