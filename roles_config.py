"""
roles_config.py - the configurable skill checklists for Role-Based Readiness.

These checklists are ILLUSTRATIVE, project-defined examples. They are NOT
universal hiring requirements and have not been validated against real
employers. To add or change a role, just edit the dictionaries below.
Skill names must match names in ml_utils.SKILL_CATALOG.
"""

ROLE_SKILLS = {
    "Python Developer": ["Python", "SQL", "Git", "Problem Solving"],
    "Data Analyst": ["SQL", "Python", "Excel", "Data Visualization"],
    "Web Developer": ["HTML", "CSS", "JavaScript", "Git"],
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
}
