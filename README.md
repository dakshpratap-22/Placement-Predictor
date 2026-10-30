# Placement Predictor

A college mini-project: a Flask web app with **user accounts** that uses a scikit-learn model to **estimate** a student's placement outcome, keeps a private **prediction history**, draws **analytics charts** and **side-by-side comparisons** from that history, checks **role-based skill readiness**, and offers a **What-If Simulator**.

> **Important - read first:** the bundled dataset (`sample_data.csv`) is **SYNTHETIC** (computer-generated), not real placement data. The model learns the rules written into the data generator, so its metrics say **nothing** about real-world accuracy. Every "Placed / Not Placed" shown is a **model estimate**, never a confirmed placement outcome, and the app does not record real outcomes. A change between two predictions does not prove that a student's real prospects changed.

## 1. Features

| Area | What it does |
|---|---|
| Accounts | Register, log in (by email), log out. Passwords hashed with Werkzeug. Signed Flask session cookies, protected pages, CSRF tokens on every form, login throttling, nav changes with login state. |
| Prediction | Logistic Regression pipeline -> Placed / Not Placed + probability (computed by the model, never hardcoded). |
| History | Your saved predictions only. Filter by date, sort, open any report, tick two records to compare, delete with a confirmation page. Records are labelled as historical and carry the model version that produced them. |
| Comparison report | Two records side by side: changed fields highlighted, probability difference, readiness for both, charts. Warns when the two used different model versions. |
| Analytics reports | Trend of estimated probability, outcome distribution, current vs previous, academic profile comparison, academic values over time, what-if comparison, role readiness. Date-range filter, CSV export, print / save as PDF. Charts use saved rows only; empty states when there is no data. |
| What-If Simulator | Same model scores original vs hypothetical profile. Saving is explicit and creates a separate record (plus a row in `simulations`); the original is never changed. |
| Role readiness | Checklist coverage per role. It is **not** a probability. |
| Branding | Original SVG logo, favicon set (SVG/ICO/PNG/Apple touch), consistent colours. |

## 2. Technology stack

Python, Flask (Jinja2), sqlite3, scikit-learn, NumPy, joblib, Werkzeug (password hashing), plain HTML/CSS/JavaScript. Charts are drawn by a small in-repo canvas library (`static/js/charts.js`), so there is no CDN, npm or Node.js dependency. No external APIs or keys.

### Adding more target job roles
Edit **`roles_config.py`** only: add one line to `ROLE_SKILLS` (`"Role Name": ["Skill", ...]`), optionally project ideas in `PROJECT_IDEAS`, then restart. Skills must exist in `SKILL_CATALOG` in `ml_utils.py`. No database change or retraining is needed. The role then appears in the prediction form, Role Readiness, Reports and the Admin dashboard.

### Admin dashboard
`admin.py` (+ `templates/admin_dashboard.html`, `templates/admin_delete_user.html`, `static/js/admin-charts.js`). Shows account totals, predictions per day, model-estimated outcomes, usage per role, model metadata and a user list with prediction counts (not individual profiles). Admins can delete a user account (confirmation page; cascades to that user's records; cannot delete yourself or another admin).

## 3. Project structure

```
app.py               Flask app factory, routes, validation, security headers, CSRF
auth_utils.py        Registration validation, password hashing helpers, login throttle, safe redirects
db.py                Schema, connection helper, idempotent migration (PRAGMA user_version)
reports.py           Pure functions that turn saved rows into chart / comparison data
ml_utils.py          Shared features, skill parsing, model loading / prediction
roles_config.py      Editable role checklists
generate_sample_data.py, train_model.py, sample_data.csv
models/              placement_model.joblib + metrics.json (created by train_model.py)
instance/            placement.db and .secret_key (created automatically, git-ignored)
templates/           base, index, about, login, register, dashboard, predict, result, history,
                     delete_confirm, compare, reports, role_readiness, simulator, error
static/              style.css, img/ (logo + favicons), js/ (app.js, charts.js, report-pages.js)
tests/               helpers.py, test_app.py, test_accounts_and_reports.py
```

## 4. Install and run

Python 3.10+ required.

**Windows (PowerShell)**
```powershell
python -m venv venv
venv\Scripts\activate
pip install -r requirements.txt
python train_model.py
python app.py
```

**macOS / Linux**
```bash
python3 -m venv venv && source venv/bin/activate
pip install -r requirements.txt
python train_model.py
python app.py
```
Open http://127.0.0.1:5000, click **Register**, then make a prediction. Stop with `Ctrl + C`.

## 5. Configuration (environment variables)

| Variable | Purpose |
|---|---|
| `SECRET_KEY` | Signs session cookies. **Set it in production.** If unset, a random key is generated once and saved to `instance/.secret_key` (git-ignored) so local sessions survive restarts. Never commit a key. |
| `SESSION_COOKIE_SECURE` | Set to `1` when served over HTTPS so the cookie is sent only over HTTPS (already set in `render.yaml`). |
| `ADMIN_EMAILS` | Comma-separated e-mails of admin users, e.g. `you@example.com`. Those accounts see the **Admin dashboard** (`/admin/`). Everyone else gets a 404. Register the admin account yourself first. |
| `FLASK_DEBUG` | `1` only while developing. Never in production. |

The login throttle (5 failures per 10 minutes per email + IP) is set by `LOGIN_MAX_ATTEMPTS` / `LOGIN_WINDOW_SECONDS` in `create_app()` in `app.py`; these are code settings, not environment variables.

PowerShell example: `$env:SECRET_KEY="a-long-random-string"; python app.py`

## 6. Database and migration

SQLite file `instance/placement.db`, created on first run. Tables:

- `users` (id PK, name, email UNIQUE case-insensitive, password_hash, created_at)
- `predictions` (the original columns, plus `user_id` FK -> users ON DELETE CASCADE and `model_version`)
- `simulations` (user_id, original_id, hypothetical_id, both classes and probabilities, model_version, created_at)

**Upgrading an existing database is automatic and non-destructive.** On start-up `db.migrate()` checks `PRAGMA user_version`; for an older database it first copies the file to `placement.db.bak-v1`, then only *adds* the new tables/columns. No rows are deleted or rewritten. Old rows have no owner (`user_id` NULL), so they are **not shown to any account**; they stay in the file and can be assigned manually with SQL if you want them back (see PROJECT_EXPLANATION.md).

## 7. Model training

`python train_model.py` trains on `sample_data.csv`, prints metrics and saves the pipeline plus `metrics.json`. Each prediction stores `model_version = "logreg-<training timestamp>"`; after retraining, old records keep their old version and comparisons across versions show a warning. To regenerate the synthetic data first: `python generate_sample_data.py`. Own CSV: keep columns `cgpa, tenth_pct, twelfth_pct, backlogs, projects, internships, skill_count, placed`, and update the "synthetic" wording if the data is real.

How the ML works: 7 features (CGPA, 10th %, 12th %, backlogs, projects, internships, recognised skill count) -> `StandardScaler` + `LogisticRegression` in one pipeline shared by training, prediction and what-if (so preprocessing is identical). 80/20 stratified split with seed 42 before fitting, scaler fitted on training data only, 5-fold CV. If the model file is missing or corrupt the app shows a setup message and saves nothing; it never fabricates a result.

Metrics from the build used for this README (synthetic data, 160-row test set): accuracy 0.706, F1 0.722, CV accuracy 0.728 +/- 0.024. Re-running training prints the current values; the About page shows them live.

## 8. Tests

```bash
python train_model.py            # the tests need a trained model
python -m unittest discover -s tests -t . -v
```
100 tests, all passing at the time of writing. They cover registration, login, wrong password, throttling, logout, CSRF, protected routes, user isolation (other users' result / readiness / simulator / delete / compare / history / CSV), saving with user and model version, duplicate-submit protection, history filters, comparison, deletion, chart data matching database values, empty states, CSV export, legacy-database migration, and missing / corrupt model.

## 9. Security notes

Hashed passwords; per-session CSRF token on every state-changing form; session id reset on login; HttpOnly + SameSite=Lax cookies (Secure via env); safe `next` redirects; parameterized SQL only; every record query is scoped by `user_id` (another user's id returns 404); Jinja auto-escaping; CSV export neutralises spreadsheet formulas; CSP, `X-Frame-Options`, `nosniff`, `no-store` on private pages; generic error pages (no stack traces) with details logged server-side.

## 10. Limitations and future work

- Synthetic data; few features; linear model; role checklists are illustrative.
- The app records model predictions only, **not** confirmed placement outcomes.
- Login throttling is in memory (per process) and resets on restart; with several gunicorn workers each keeps its own count. Use a shared store for production.
- "PDF export" uses the browser's Print -> Save as PDF.
- Old (pre-account) rows are kept but invisible until assigned to a user.
- No email verification or password reset.
- Future: real anonymised data, per-skill features, model comparison, recording real outcomes, password reset, admin tools.

## 11. Troubleshooting

| Problem | Fix |
|---|---|
| "Setup needed" / "Model not ready" | Run `python train_model.py`, restart the app. |
| `ModuleNotFoundError` | Activate the venv and `pip install -r requirements.txt`. |
| Logged out after every restart in production | Set a fixed `SECRET_KEY`. |
| "Too many attempts" at login | Wait 10 minutes or restart the server. |
| Model fails to load after upgrading scikit-learn | Re-run `python train_model.py`. |
| Port 5000 busy | Change `port=5000` at the bottom of `app.py`. |
