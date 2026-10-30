"""
Automated tests for Placement Predictor.

Run from the project folder:   python -m unittest discover -s tests -v
(The model must be trained first:  python train_model.py)
"""
import os
import re
import sqlite3
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import create_app, validate_profile  # noqa: E402
from ml_utils import MODEL_PATH, parse_skills  # noqa: E402
from tests.helpers import FAST_HASH, register  # noqa: E402

GOOD = {
    "student_name": "Asha Verma", "cgpa": "7.5", "tenth_pct": "82", "twelfth_pct": "78",
    "backlogs": "0", "projects": "2", "internships": "1",
    "skills": "Python, SQL", "target_role": "Python Developer",
}


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = os.path.join(self.tmp.name, "test.db")
        self.app = create_app({"TESTING": True, "DATABASE": self.db, "CSRF_ENABLED": False,
                               "PASSWORD_HASH_METHOD": FAST_HASH})
        self.client = self.app.test_client()
        register(self.client)          # logs in: every route except the public ones needs it

    def tearDown(self):
        self.tmp.cleanup()

    def predict(self, **overrides):
        data = dict(GOOD, **overrides)
        return self.client.post("/predict", data=data)

    def make_record(self, **overrides):
        resp = self.predict(**overrides)
        self.assertEqual(resp.status_code, 302)
        return int(re.search(r"/result/(\d+)", resp.headers["Location"]).group(1))

    def rows(self):
        conn = sqlite3.connect(self.db)
        try:
            return conn.execute("SELECT * FROM predictions ORDER BY id").fetchall()
        finally:
            conn.close()


class TestPagesAndPrediction(Base):
    def test_model_artifact_exists(self):
        self.assertTrue(os.path.exists(MODEL_PATH), "Run python train_model.py first")

    def test_static_pages_load(self):
        for url in ("/", "/predict", "/about", "/history", "/dashboard", "/reports", "/login"):
            self.assertEqual(self.client.get(url, follow_redirects=True).status_code, 200, url)

    def test_css_loads(self):
        resp = self.client.get("/static/style.css")
        self.assertEqual(resp.status_code, 200)
        resp.close()

    def test_valid_prediction_and_result_page(self):
        rid = self.make_record()
        html = self.client.get(f"/result/{rid}").get_data(as_text=True)
        self.assertIn("Predicted outcome", html)
        self.assertTrue("Placed" in html or "Not Placed" in html)
        self.assertIn("Estimated probability", html)
        self.assertEqual(len(self.rows()), 1)

    def test_probability_is_between_0_and_1(self):
        self.make_record()
        p = self.rows()[0][11]
        self.assertGreaterEqual(p, 0.0)
        self.assertLessEqual(p, 1.0)

    def test_invalid_values_rejected(self):
        bad_cases = [
            {"cgpa": "11"}, {"cgpa": "-1"}, {"cgpa": "abc"}, {"cgpa": "nan"},
            {"tenth_pct": "101"}, {"twelfth_pct": "-5"},
            {"backlogs": "-1"}, {"backlogs": "1.5"}, {"projects": "x"},
            {"internships": "999"}, {"target_role": "Astronaut"},
            {"student_name": "<script>alert(1)</script>"},
        ]
        for case in bad_cases:
            resp = self.predict(**case)
            self.assertEqual(resp.status_code, 400, case)
        self.assertEqual(len(self.rows()), 0)

    def test_missing_fields_rejected(self):
        for key in GOOD:
            if key == "skills":
                continue  # optional
            data = dict(GOOD)
            del data[key]
            resp = self.client.post("/predict", data=data)
            self.assertEqual(resp.status_code, 400, key)
            self.assertIn("required", resp.get_data(as_text=True).lower() + "choose")
        self.assertEqual(len(self.rows()), 0)

    def test_valid_values_preserved_on_error(self):
        resp = self.predict(cgpa="15")
        html = resp.get_data(as_text=True)
        self.assertIn('value="Asha Verma"', html)
        self.assertIn("CGPA must be between", html)

    def test_unknown_record_404(self):
        for url in ("/result/9999", "/readiness/9999", "/simulator/9999"):
            self.assertEqual(self.client.get(url).status_code, 404, url)


class TestReadiness(Base):
    def test_partial_match(self):
        rid = self.make_record(skills="Python, Git", target_role="Python Developer")
        html = self.client.get(f"/readiness/{rid}").get_data(as_text=True)
        self.assertIn("50%", html)
        self.assertIn("SQL", html)
        self.assertIn("Problem Solving", html)
        self.assertIn("not placement probability", html)

    def test_full_match(self):
        rid = self.make_record(skills="HTML, CSS, JavaScript, Git", target_role="Web Developer")
        html = self.client.get(f"/readiness/{rid}").get_data(as_text=True)
        self.assertIn("100%", html)

    def test_zero_match(self):
        rid = self.make_record(skills="", target_role="Data Analyst")
        html = self.client.get(f"/readiness/{rid}").get_data(as_text=True)
        self.assertIn("0%", html)

    def test_aliases_parsed(self):
        skills, unknown = parse_skills("py, MySQL, github, power bi, quantum basketweaving")
        self.assertEqual(skills, ["Data Visualization", "Git", "Python", "SQL"])
        self.assertEqual(unknown, ["quantum basketweaving"])


class TestSimulator(Base):
    def sim(self, rid, **overrides):
        data = {"cgpa": "7.5", "tenth_pct": "82", "twelfth_pct": "78", "backlogs": "0",
                "projects": "2", "internships": "1", "skills": "Python, SQL"}
        data.update(overrides)
        return self.client.post(f"/simulator/{rid}", data=data)

    def test_get_shows_original_and_reset(self):
        rid = self.make_record()
        html = self.client.get(f"/simulator/{rid}").get_data(as_text=True)
        self.assertIn("Original profile", html)
        self.assertIn("Reset to original", html)

    def test_unchanged_inputs(self):
        rid = self.make_record()
        html = self.sim(rid).get_data(as_text=True)
        self.assertIn("No inputs were changed", html)
        self.assertIn("unchanged", html)

    def test_modified_inputs_recalculated_by_model(self):
        rid = self.make_record(cgpa="6.0", projects="0", internships="0", backlogs="3")
        orig_p = self.rows()[0][11]
        html = self.sim(rid, cgpa="9.0", projects="5", internships="2", backlogs="0",
                        skills="Python, SQL, Git, Excel, HTML").get_data(as_text=True)
        self.assertIn("What changed", html)
        self.assertIn("CGPA: 6 → 9", html)
        self.assertIn("percentage points", html)
        self.assertIn("Skills added", html)
        m = re.search(r"([+-]\d+\.\d) percentage points", html)
        self.assertIsNotNone(m)
        self.assertGreater(float(m.group(1)), 0)  # real model output improved
        self.assertIsNotNone(orig_p)

    def test_worse_profile_can_lower_probability(self):
        rid = self.make_record(cgpa="9", projects="5", internships="2")
        html = self.sim(rid, cgpa="5", projects="0", internships="0", backlogs="5").get_data(as_text=True)
        m = re.search(r"(-\d+\.\d) percentage points", html)
        self.assertIsNotNone(m)

    def test_original_not_overwritten_and_nothing_saved(self):
        rid = self.make_record()
        before = self.rows()
        self.sim(rid, cgpa="9.9", projects="9", internships="3", skills="Python")
        self.assertEqual(self.rows(), before)  # same rows, same values, no new rows

    def test_invalid_simulation_input(self):
        rid = self.make_record()
        self.assertEqual(self.sim(rid, cgpa="50").status_code, 400)
        self.assertEqual(self.sim(rid, projects="abc").status_code, 400)
        self.assertEqual(len(self.rows()), 1)

    def test_explicit_save_creates_separate_record(self):
        rid = self.make_record()
        before = self.rows()[0]
        resp = self.client.post(f"/simulator/{rid}/save", data={
            "cgpa": "9", "tenth_pct": "82", "twelfth_pct": "78", "backlogs": "0",
            "projects": "4", "internships": "2", "skills": "Python, SQL"})
        self.assertEqual(resp.status_code, 302)
        rows = self.rows()
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0], before)               # original untouched
        self.assertIn("(what-if)", rows[1][1])


class TestDatabaseHistoryAndSecurity(Base):
    def test_db_created_and_history_lists_record(self):
        self.assertTrue(os.path.exists(self.db))
        self.make_record(student_name="Ravi Kumar")
        html = self.client.get("/history").get_data(as_text=True)
        self.assertIn("Ravi Kumar", html)

    def test_sql_injection_like_name_rejected_and_table_intact(self):
        resp = self.predict(student_name="x'); DROP TABLE predictions;--")
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(self.rows(), [])  # table still exists (query would raise otherwise)

    def test_html_escaped_in_output(self):
        # Name regex blocks tags; skills with markup must be escaped/ignored
        rid = self.make_record(skills="<script>alert(1)</script>, Python")
        html = self.client.get(f"/result/{rid}").get_data(as_text=True)
        self.assertNotIn("<script>alert(1)</script>", html)

    def test_csrf_enforced_when_enabled(self):
        app = create_app({"TESTING": True, "DATABASE": self.db, "CSRF_ENABLED": True,
                          "PASSWORD_HASH_METHOD": FAST_HASH})
        c = app.test_client()
        register(c, email="csrf@example.com", csrf=True)
        self.assertEqual(c.post("/predict", data=GOOD).status_code, 400)
        page = c.get("/predict").get_data(as_text=True)
        token = re.search(r'name="_csrf" value="([0-9a-f]+)"', page).group(1)
        resp = c.post("/predict", data=dict(GOOD, _csrf=token))
        self.assertEqual(resp.status_code, 302)


class TestMissingModel(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.app = create_app({
            "TESTING": True, "CSRF_ENABLED": False,
            "DATABASE": os.path.join(self.tmp.name, "t.db"), "PASSWORD_HASH_METHOD": FAST_HASH,
            "MODEL_PATH": os.path.join(self.tmp.name, "does_not_exist.joblib")})
        self.client = self.app.test_client()
        register(self.client)

    def tearDown(self):
        self.tmp.cleanup()

    def test_prediction_shows_setup_error(self):
        resp = self.client.post("/predict", data=GOOD)
        self.assertEqual(resp.status_code, 503)
        html = resp.get_data(as_text=True)
        self.assertIn("python train_model.py", html)
        self.assertNotIn("Traceback", html)

    def test_pages_show_setup_banner(self):
        html = self.client.get("/").get_data(as_text=True)
        self.assertIn("Setup needed", html)

    def test_corrupt_model_file_handled(self):
        bad = os.path.join(self.tmp.name, "bad.joblib")
        with open(bad, "wb") as f:
            f.write(b"not a model")
        app = create_app({"TESTING": True, "CSRF_ENABLED": False, "MODEL_PATH": bad,
                          "DATABASE": os.path.join(self.tmp.name, "t2.db"),
                          "PASSWORD_HASH_METHOD": FAST_HASH})
        c = app.test_client()
        register(c)
        resp = c.post("/predict", data=GOOD)
        self.assertEqual(resp.status_code, 503)


class TestValidationUnit(unittest.TestCase):
    def test_validate_ok(self):
        clean, errors = validate_profile(GOOD)
        self.assertEqual(errors, {})
        self.assertEqual(clean["skills"], ["Python", "SQL"])


if __name__ == "__main__":
    unittest.main()
