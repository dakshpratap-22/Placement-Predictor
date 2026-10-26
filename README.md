# Placement Predictor

A college mini-project: a Flask web app that uses a scikit-learn model to **estimate** a student's placement outcome, checks **role-based skill readiness**, and offers a **What-If Placement Simulator**.

> **Important – read first:** the bundled dataset (`sample_data.csv`) is **SYNTHETIC** (computer-generated). It is **not** real student placement data. The model therefore learns the assumptions written into the data generator, and its accuracy numbers say **nothing** about real-world placement accuracy. Predictions are estimates, never guarantees of employment.

## 1. Features

- **Placement prediction** – Logistic Regression pipeline gives Placed / Not Placed and the probability of "Placed" (computed by the model, never hardcoded).
- **Role-Based Readiness** – compares your skills with an editable checklist for Python Developer, Data Analyst, Web Developer; shows matched/missing skills, learning tips and project ideas. The percentage is a simple checklist count, **not** placement probability and **not** a validated employability score.
- **What-If Simulator** – edit CGPA, projects, internships, backlogs or skills; the *same* model scores the original and hypothetical profile side by side. Nothing is saved unless you press the explicit "save" button, and your original record is never changed.
- **History** page of saved predictions (SQLite), **About** page with live training metrics.

## 2. Technology stack

Python, Flask (Jinja templates), HTML, CSS, scikit-learn, SQLite. NumPy and joblib for data handling and saving the model (no pandas needed). No Node.js, no external APIs, no API keys.

## 3. Project structure

```
placement_predictor/
├── app.py                  Flask app: routes, validation, database, simulator logic
├── ml_utils.py             Shared feature list, skill parsing, model loading/prediction
├── roles_config.py         Editable role skill checklists, tips and project ideas
├── generate_sample_data.py Creates the SYNTHETIC sample_data.csv
├── train_model.py          Trains + evaluates + saves the model
├── sample_data.csv         Synthetic demonstration dataset (800 rows)
├── requirements.txt
├── models/
│   ├── placement_model.joblib   (created by train_model.py)
│   └── metrics.json             (created by train_model.py)
├── instance/placement.db   SQLite DB (created automatically on first run)
├── templates/              base, index, predict, result, role_readiness,
│                           simulator, history, about, error
├── static/style.css
└── tests/test_app.py       Automated tests
```

## 4. Prerequisites

- Python 3.10 or newer (check with `python --version`). Install from python.org and tick **"Add Python to PATH"**.
- VS Code (with the Python extension is helpful).

## 5. Setup on Windows (PowerShell) – run in this order

1. Open VS Code → **File → Open Folder…** → choose the `placement_predictor` folder.
2. Open a terminal: **Terminal → New Terminal** (PowerShell).
3. Run these commands one by one:

```powershell
python -m venv venv
venv\Scripts\activate
pip install -r requirements.txt
python train_model.py
python app.py
```

| Command | What it does |
|---|---|
| `python -m venv venv` | Creates an isolated Python environment named `venv` (only once). |
| `venv\Scripts\activate` | Activates it. You will see `(venv)` in the prompt. Do this in every new terminal. |
| `pip install -r requirements.txt` | Installs Flask, scikit-learn, numpy, joblib. |
| `python train_model.py` | Trains the model on `sample_data.csv`, prints metrics, saves `models/placement_model.joblib`. |
| `python app.py` | Starts the website. |

4. Open **[http://127.0.0.1:5000](https://placement-predictor-rw05.onrender.com)** in your browser. Stop the server with `Ctrl + C`.

> If PowerShell says *"running scripts is disabled"* when activating, run once:
> `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned` and try again (or use Command Prompt: `venv\Scripts\activate.bat`).

## 6. Retraining the model

- Re-run `python train_model.py` any time. Restart the app afterwards (it also reloads automatically when the model file changes).
- To regenerate the synthetic data first: `python generate_sample_data.py`, then train again.
- To use your own CSV, keep the same columns: `cgpa, tenth_pct, twelfth_pct, backlogs, projects, internships, skill_count, placed` (`placed` = `Placed` / `Not Placed`). If your data is real, update the "synthetic" wording in the app and docs.

## 7. Running the tests

```powershell
python -m unittest discover -s tests -v
```
(Train the model first.)

## 8. How the ML part works

- **Features (7):** CGPA, 10th %, 12th %, backlogs, projects, internships, and `skill_count` (number of recognised catalogue skills).
- **Label:** `Placed` / `Not Placed`.
- **Pipeline:** `StandardScaler` → `LogisticRegression`, saved as one object so training and prediction always use identical features, order and scaling (`ml_utils.py` is shared by both).
- **No data leakage:** the data is split 80/20 (fixed seed 42, stratified) *before* fitting; the scaler is fitted on training data only; cross-validation re-fits it inside each fold.
- **Evaluation:** accuracy, precision, recall, F1 (for "Placed"), confusion matrix, 5-fold CV. Training refuses to run if there are too few rows or a class is missing.
- A student's submitted profile is **never** used for training.
- If the model file is missing or corrupt, the app shows a setup message – it does **not** fall back to some made-up formula.

## 9. How the What-If Simulator works

1. The original profile is loaded from the database (read-only).
2. You edit hypothetical values and press **Run simulation**.
3. Both profiles go through the same trained pipeline.
4. You see both predictions, the list of changed inputs, and the probability difference. If nothing changes, the result says so honestly. More projects or internships do **not** automatically raise the result – the model decides.
5. **Reset to original** reloads the saved values. Hypothetical profiles are saved only if you click the separate save button, and then as a *new* record.

## 10. How Role-Based Readiness works

Your skills text is matched (with aliases such as "py" → Python) against the role's checklist in `roles_config.py`. Percentage = matched ÷ required skills. The checklists are illustrative examples, not real hiring requirements; edit them freely.

## 11. Troubleshooting

| Problem | Fix |
|---|---|
| Yellow "Setup needed" banner / "Model not ready" | Run `python train_model.py`, then restart the app. |
| `ModuleNotFoundError: flask` (or sklearn…) | Activate the venv (`venv\Scripts\activate`) and run `pip install -r requirements.txt`. |
| `python` not recognised | Reinstall Python with "Add to PATH", or try `py` instead of `python`. |
| "Port 5000 already in use" | Close the other app, or change `port=5000` at the bottom of `app.py`. |
| Model fails to load after upgrading scikit-learn | Re-run `python train_model.py`. |
| Database error page | Delete `instance/placement.db` and restart; it is recreated. |
| Form says "session expired"/bad request | Reload the form page and submit again (CSRF token). |

Debug mode is **off** by default. To enable while developing: `$env:FLASK_DEBUG="1"; python app.py`. **Never enable it in production.** For any real deployment also set a secret key: `$env:SECRET_KEY="a-long-random-string"`.

## 12. Limitations and future improvements

**Limitations:** synthetic data; only 7 inputs; skills reduced to a count (which specific skill you have does not affect the model); simple linear model; no real-world validation; role checklists are illustrative; single-user local app without login.

**Future ideas:** train on real, consented, anonymised placement data; add per-skill features; compare more models (Random Forest) with cross-validation; add login so students only see their own history; export result as PDF; add charts.
