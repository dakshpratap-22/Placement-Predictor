"""
roles_config.py - the configurable skill checklists for Role-Based Readiness.

>>> THIS IS THE FILE TO EDIT TO ADD MORE TARGET JOB ROLES. <<<

How to add a role (3 steps):
  1. Add one line to ROLE_SKILLS below:   "Role Name": ["Skill", "Skill", ...]
     The role then appears automatically in the "Target job role" dropdown,
     the Role Readiness page, the Reports page and the Admin dashboard.
  2. (Optional) Add 2-3 starter projects for it in PROJECT_IDEAS.
  3. (Optional) Add a learning tip for any NEW skill in LEARNING_TIPS.
Then restart the app. No database change and no model retraining is needed,
because the role is not an input of the ML model.

IMPORTANT: every skill name used in ROLE_SKILLS must exist as a key of
ml_utils.SKILL_CATALOG (currently: Python, SQL, Git, Problem Solving, Excel,
Data Visualization, HTML, CSS, JavaScript, Flask, Machine Learning,
Communication, Java, C/C++). A skill that is not in that catalogue can never
be matched from a student's skills text, so the role would always show 0%.
If you want a brand-new skill (e.g. "React"), add it to SKILL_CATALOG in
ml_utils.py first. Note: that increases the possible "skill count" the model
sees, and the model was trained on synthetic data with a smaller range, so
re-run `python generate_sample_data.py` and `python train_model.py` afterwards.

These checklists are ILLUSTRATIVE, project-defined examples. They are NOT
universal hiring requirements and have not been validated against real
employers.
"""

ROLE_SKILLS = {
    # --- original roles ---
    "Python Developer": ["Python", "SQL", "Git", "Problem Solving"],
    "Data Analyst": ["SQL", "Python", "Excel", "Data Visualization"],
    "Web Developer": ["HTML", "CSS", "JavaScript", "Git"],
    # --- added roles ---
    "Data Scientist": ["Python", "SQL", "Machine Learning", "Data Visualization"],
    "Machine Learning Engineer": ["Python", "Machine Learning", "Git", "Problem Solving"],
    "Backend Developer": ["Python", "SQL", "Flask", "Git"],
    "Frontend Developer": ["HTML", "CSS", "JavaScript", "Communication"],
    "Full Stack Developer": ["HTML", "CSS", "JavaScript", "Python", "SQL"],
    "Java Developer": ["Java", "SQL", "Git", "Problem Solving"],
    "Software Engineer": ["Problem Solving", "Git", "Python", "Communication"],
    "Business Analyst": ["Excel", "SQL", "Data Visualization", "Communication"],
    "QA Automation Engineer": ["Python", "SQL", "Problem Solving", "Communication"],
    "Embedded Systems Engineer": ["C/C++", "Problem Solving", "Git", "Python"],
}

LEARNING_TIPS = {
    "Python": "Work through Python basics (data types, functions, OOP) and solve small exercises daily.",
    "SQL": "Practise SELECT, JOIN, GROUP BY and subqueries on a small SQLite database.",
    "Git": "Learn init, add, commit, branch, merge and push; host a project on GitHub.",
    "Problem Solving": "Solve 2-3 easy/medium DSA problems a week (arrays, strings, recursion, sorting).",
    "Excel": "Learn formulas, VLOOKUP/XLOOKUP, pivot tables and basic charts.",
    "Data Visualization": "Practise charts with Matplotlib or a BI tool like Power BI/Tableau.",
    "HTML": "Build static pages using semantic tags, forms and tables.",
    "CSS": "Learn the box model, Flexbox, Grid and responsive media queries.",
    "JavaScript": "Learn variables, functions, the DOM and events; add interactivity to a page.",
    "Flask": "Build a small Flask app with routes, templates, forms and a SQLite database.",
    "Machine Learning": "Learn the train/test split, then fit simple scikit-learn models and compare their metrics.",
    "Communication": "Practise explaining a project in two minutes and write a short README for each project.",
    "Java": "Learn classes, collections, exceptions and write small console programs.",
    "C/C++": "Practise pointers, arrays, structs and memory handling with small programs.",
}

PROJECT_IDEAS = {
    "Python Developer": [
        "Command-line expense tracker using Python and SQLite",
        "Flask URL shortener with a small database",
        "Web scraper that saves results to CSV and summarises them",
    ],
    "Data Analyst": [
        "Sales dashboard from a public CSV dataset using SQL and charts",
        "Exploratory analysis of a public dataset with a written summary of insights",
        "Excel workbook with pivot tables analysing monthly spending",
    ],
    "Web Developer": [
        "Responsive personal portfolio website",
        "To-do list app with HTML, CSS and JavaScript",
        "Restaurant menu page with a contact form",
    ],
    "Data Scientist": [
        "Predict house prices from a public dataset and explain the model's errors",
        "Customer segmentation analysis with a written summary of findings",
        "Notebook comparing two classifiers on a public dataset",
    ],
    "Machine Learning Engineer": [
        "Train a classifier, save it with joblib and serve it from a Flask page",
        "Reproducible training script with a fixed seed and saved metrics",
        "Simple spam-message detector with a train/test evaluation",
    ],
    "Backend Developer": [
        "REST-style Flask API for a notes app with SQLite",
        "Login system with hashed passwords and protected pages",
        "Library book-lending tracker with a relational schema",
    ],
    "Frontend Developer": [
        "Responsive landing page using Flexbox and Grid",
        "Weather-style card UI that fetches sample JSON with JavaScript",
        "Accessible multi-step form with client-side validation",
    ],
    "Full Stack Developer": [
        "Blog app with Flask, SQLite and a responsive HTML/CSS front end",
        "Task manager with user accounts and a JavaScript-enhanced UI",
        "Event registration site with an admin view",
    ],
    "Java Developer": [
        "Console banking application using classes and collections",
        "Student record manager with file or database storage",
        "Simple inventory system with unit tests",
    ],
    "Software Engineer": [
        "Command-line project with tests and a clear README",
        "Implement common data structures and benchmark them",
        "Small open-source style project with Git branches and commits",
    ],
    "Business Analyst": [
        "Requirements document and process flow for a small business scenario",
        "Excel and SQL analysis of a public sales dataset with recommendations",
        "Dashboard of key metrics with a one-page summary for managers",
    ],
    "QA Automation Engineer": [
        "Write automated tests for a small Flask app with unittest",
        "Test plan and bug-report samples for a public website",
        "Script that checks a CSV file for data-quality problems",
    ],
    "Embedded Systems Engineer": [
        "Simulated traffic-light controller in C",
        "Temperature logger that reads sample sensor data and stores it",
        "Linked list and queue library written in C/C++",
    ],
}
