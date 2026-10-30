"""
Tests for the v2 upgrade: accounts, per-user isolation, history, comparison,
chart data, empty states, schema migration and model-failure handling.

Run from the project folder:  python -m unittest discover -s tests -t . -v
(The model must be trained first:  python train_model.py)
"""
import json
import os
import re
import sqlite3
import tempfile
import unittest

from app import create_app
import reports
from tests.helpers import FAST_HASH, GOOD, PASSWORD, csrf_from, login, make_record, register


def chart_json(html):
    m = re.search(r'<script type="application/json" id="chart-data">(.*?)</script>', html, re.S)
    return json.loads(m.group(1)) if m else None


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = os.path.join(self.tmp.name, "t.db")
        self.cfg = {"TESTING": True, "DATABASE": self.db, "CSRF_ENABLED": False,
                    "PASSWORD_HASH_METHOD": FAST_HASH}
        self.app = create_app(self.cfg)
        self.client = self.app.test_client()

    def tearDown(self):
        self.tmp.cleanup()

    def new_client(self, email, name="Other Person"):
        c = self.app.test_client()
        self.assertEqual(register(c, name=name, email=email).status_code, 302)
        return c

    def q(self, sql, args=()):
        conn = sqlite3.connect(self.db)
        try:
            return conn.execute(sql, args).fetchall()
        finally:
            conn.close()


class TestRegistration(Base):
    def test_register_logs_in_and_redirects(self):
        r = register(self.client)
        self.assertEqual(r.status_code, 302)
        self.assertTrue(r.headers["Location"].endswith("/dashboard"))
        self.assertEqual(self.client.get("/dashboard").status_code, 200)

    def test_password_is_hashed_never_plain(self):
        register(self.client)
        stored = self.q("SELECT password_hash FROM users")[0][0]
        self.assertNotIn(PASSWORD, stored)
        self.assertTrue(stored.startswith(("pbkdf2:", "scrypt:")))

    def test_duplicate_email_rejected_case_insensitive(self):
        register(self.client, email="a@example.com")
        c2 = self.app.test_client()
        r = register(c2, email="A@Example.COM")
        self.assertEqual(r.status_code, 409)
        self.assertIn("already exists", r.get_data(as_text=True))
        self.assertEqual(len(self.q("SELECT id FROM users")), 1)

    def test_validation_errors(self):
        bad = [
            ({"name": ""}, "Name is required"),
            ({"email": ""}, "Email is required"),
            ({"email": "not-an-email"}, "valid email"),
            ({"password": "short1", "confirm_password": "short1"}, "at least 8"),
            ({"password": "onlyletters", "confirm_password": "onlyletters"}, "one letter and one number"),
            ({"confirm_password": "Different1"}, "do not match"),
            ({"name": "<b>x</b>"}, "only letters"),
        ]
        for override, text in bad:
            data = {"name": "Ok Name", "email": "ok@example.com", "password": PASSWORD,
                    "confirm_password": PASSWORD}
            data.update(override)
            r = self.app.test_client().post("/register", data=data)
            self.assertEqual(r.status_code, 400, override)
            self.assertIn(text, r.get_data(as_text=True), override)
        self.assertEqual(self.q("SELECT id FROM users"), [])


class TestLoginLogout(Base):
    def setUp(self):
        super().setUp()
        register(self.client, email="u@example.com")
        self.client.post("/logout")

    def test_login_success(self):
        r = login(self.client, email="u@example.com")
        self.assertEqual(r.status_code, 302)
        self.assertEqual(self.client.get("/dashboard").status_code, 200)

    def test_wrong_password_and_unknown_email_give_same_message(self):
        r1 = login(self.client, email="u@example.com", password="WrongPass1")
        r2 = login(self.client, email="nobody@example.com", password="WrongPass1")
        self.assertEqual((r1.status_code, r2.status_code), (401, 401))
        for r in (r1, r2):
            self.assertIn("Invalid email or password", r.get_data(as_text=True))
        self.assertEqual(self.client.get("/dashboard").status_code, 302)   # still logged out

    def test_empty_fields(self):
        r = login(self.client, email="", password="")
        self.assertEqual(r.status_code, 400)
        html = r.get_data(as_text=True)
        self.assertIn("Email is required", html)
        self.assertIn("Password is required", html)

    def test_logout_ends_session_and_requires_post(self):
        login(self.client, email="u@example.com")
        self.assertEqual(self.client.get("/logout").status_code, 405)
        self.assertEqual(self.client.post("/logout").status_code, 302)
        self.assertEqual(self.client.get("/dashboard").status_code, 302)

    def test_open_redirect_blocked(self):
        r = login(self.client, email="u@example.com", next="//evil.example.com")
        self.assertTrue(r.headers["Location"].endswith("/dashboard"))
        self.client.post("/logout")
        r = login(self.client, email="u@example.com", next="/history")
        self.assertTrue(r.headers["Location"].endswith("/history"))

    def test_login_throttle(self):
        for _ in range(5):
            login(self.client, email="u@example.com", password="WrongPass1")
        r = login(self.client, email="u@example.com", password=PASSWORD)   # correct, but blocked
        self.assertEqual(r.status_code, 429)

    def test_cookie_and_security_headers(self):
        r = login(self.client, email="u@example.com")
        cookie = r.headers.get("Set-Cookie", "")
        self.assertIn("HttpOnly", cookie)
        self.assertIn("SameSite=Lax", cookie)
        h = self.client.get("/").headers
        self.assertEqual(h["X-Content-Type-Options"], "nosniff")
        self.assertIn("script-src 'self'", h["Content-Security-Policy"])

    def test_csrf_required_on_auth_forms(self):
        app = create_app(dict(self.cfg, CSRF_ENABLED=True, DATABASE=os.path.join(self.tmp.name, "c.db")))
        c = app.test_client()
        self.assertEqual(c.post("/register", data={"name": "A B", "email": "x@example.com",
                                                   "password": PASSWORD, "confirm_password": PASSWORD}).status_code, 400)
        self.assertEqual(register(c, email="x@example.com", csrf=True).status_code, 302)
        self.assertEqual(c.post("/logout").status_code, 400)               # no token
        self.assertEqual(c.post("/logout", data={"_csrf": csrf_from(c, "/dashboard")}).status_code, 302)

    def test_navbar_changes_with_login_state(self):
        self.assertIn("Log in", self.client.get("/").get_data(as_text=True))
        login(self.client, email="u@example.com")
        html = self.client.get("/").get_data(as_text=True)
        self.assertIn("Log out", html)
        self.assertIn("Analytics reports", html)


class TestProtectedRoutes(Base):
    def test_anonymous_redirected_to_login(self):
        for url in ("/dashboard", "/predict", "/history", "/reports", "/compare", "/result/1",
                    "/readiness/1", "/simulator/1", "/history/1/delete", "/reports/export.csv",
                    "/latest/result"):
            r = self.client.get(url)
            self.assertEqual(r.status_code, 302, url)
            self.assertIn("/login", r.headers["Location"], url)

    def test_anonymous_post_cannot_create_records(self):
        r = self.client.post("/predict", data=GOOD)
        self.assertEqual(r.status_code, 302)
        self.assertEqual(self.q("SELECT id FROM predictions"), [])

    def test_public_pages_open(self):
        for url in ("/", "/about", "/login", "/register"):
            self.assertEqual(self.client.get(url).status_code, 200, url)


class TestUserIsolation(Base):
    def setUp(self):
        super().setUp()
        register(self.client, email="a@example.com")
        self.rec_a = make_record(self.client, student_name="Alice Only")
        self.other = self.new_client("b@example.com")

    def test_other_user_cannot_open_records(self):
        for url in (f"/result/{self.rec_a}", f"/readiness/{self.rec_a}", f"/simulator/{self.rec_a}",
                    f"/history/{self.rec_a}/delete"):
            self.assertEqual(self.other.get(url).status_code, 404, url)

    def test_other_user_cannot_modify_or_delete(self):
        r = self.other.post(f"/history/{self.rec_a}/delete")
        self.assertEqual(r.status_code, 404)
        r = self.other.post(f"/simulator/{self.rec_a}/save", data={
            "cgpa": "9", "tenth_pct": "80", "twelfth_pct": "80", "backlogs": "0", "projects": "3",
            "internships": "1", "skills": "Python"})
        self.assertEqual(r.status_code, 404)
        self.assertEqual(len(self.q("SELECT id FROM predictions")), 1)

    def test_history_reports_export_are_private(self):
        self.assertNotIn("Alice Only", self.other.get("/history").get_data(as_text=True))
        csv_text = self.other.get("/reports/export.csv").get_data(as_text=True)
        self.assertNotIn("Alice Only", csv_text)
        self.assertEqual(csv_text.strip().count("\n"), 0)                # header only
        data = chart_json(self.other.get("/reports").get_data(as_text=True))
        self.assertIsNone(data)                                          # user B has no data

    def test_compare_with_foreign_id_does_not_leak(self):
        mine = make_record(self.other)
        r = self.other.get(f"/compare?a={self.rec_a}&b={mine}", follow_redirects=True)
        self.assertNotIn("Alice Only", r.get_data(as_text=True))
        self.assertNotIn("Historical Comparison Report", r.get_data(as_text=True))

    def test_records_belong_to_the_creating_user(self):
        mine = make_record(self.other)
        rows = dict(self.q("SELECT id, user_id FROM predictions"))
        self.assertNotEqual(rows[self.rec_a], rows[mine])


class TestPredictionSaving(Base):
    def setUp(self):
        super().setUp()
        register(self.client)

    def test_saved_with_user_and_model_version(self):
        rid = make_record(self.client)
        uid, version, prob = self.q("SELECT user_id, model_version, probability_placed FROM predictions WHERE id=?", (rid,))[0]
        self.assertIsNotNone(uid)
        self.assertTrue(version.startswith("logreg-"))
        self.assertTrue(0 <= prob <= 1)

    def test_resubmitting_same_form_does_not_duplicate(self):
        html = self.client.get("/predict").get_data(as_text=True)
        nonce = re.search(r'name="_nonce" value="([0-9a-f]+)"', html).group(1)
        r1 = self.client.post("/predict", data=dict(GOOD, _nonce=nonce))
        r2 = self.client.post("/predict", data=dict(GOOD, _nonce=nonce))
        self.assertEqual(r1.headers["Location"], r2.headers["Location"])
        self.assertEqual(len(self.q("SELECT id FROM predictions")), 1)

    def test_new_prediction_preserves_history(self):
        a = make_record(self.client, cgpa="6.0")
        before = self.q("SELECT * FROM predictions WHERE id=?", (a,))
        make_record(self.client, cgpa="8.5")
        self.assertEqual(self.q("SELECT * FROM predictions WHERE id=?", (a,)), before)
        self.assertEqual(len(self.q("SELECT id FROM predictions")), 2)

    def test_prediction_comes_from_model_not_hardcoded(self):
        low = make_record(self.client, cgpa="4.5", projects="0", internships="0", backlogs="6", skills="")
        high = make_record(self.client, cgpa="9.5", projects="6", internships="3", backlogs="0",
                           skills="Python, SQL, Git, Excel, HTML, CSS")
        p = dict(self.q("SELECT id, probability_placed FROM predictions"))
        self.assertLess(p[low], p[high])


class TestHistoryAndCompare(Base):
    def setUp(self):
        super().setUp()
        register(self.client)
        self.a = make_record(self.client, cgpa="6.0", projects="0")
        self.b = make_record(self.client, cgpa="8.5", projects="4", skills="Python, SQL, Git")
        # give the two records distinct, known dates for the filter tests
        conn = sqlite3.connect(self.db)
        conn.execute("UPDATE predictions SET created_at='2026-01-10T10:00:00' WHERE id=?", (self.a,))
        conn.execute("UPDATE predictions SET created_at='2026-03-05T09:30:00' WHERE id=?", (self.b,))
        conn.commit(); conn.close()

    def ids_in(self, html):
        return [int(i) for i in re.findall(r'name="ids" value="(\d+)"', html)]

    def test_history_lists_own_records_labelled_historical(self):
        html = self.client.get("/history").get_data(as_text=True)
        self.assertEqual(sorted(self.ids_in(html)), sorted([self.a, self.b]))
        self.assertIn("historical model predictions", html)

    def test_date_filter_and_sort(self):
        html = self.client.get("/history?from=2026-02-01").get_data(as_text=True)
        self.assertEqual(self.ids_in(html), [self.b])
        html = self.client.get("/history?to=2026-02-01").get_data(as_text=True)
        self.assertEqual(self.ids_in(html), [self.a])
        asc = self.ids_in(self.client.get("/history?sort=date_asc").get_data(as_text=True))
        desc = self.ids_in(self.client.get("/history?sort=date_desc").get_data(as_text=True))
        self.assertEqual(asc, [self.a, self.b]); self.assertEqual(desc, [self.b, self.a])
        self.assertEqual(self.client.get("/history?sort=bogus&from=garbage").status_code, 200)

    def test_compare_two_records_shows_changes_and_cautions(self):
        html = self.client.get(f"/compare?a={self.a}&b={self.b}").get_data(as_text=True)
        self.assertIn("Historical Comparison Report", html)
        for field in ("CGPA", "Projects"):
            self.assertRegex(html, rf'row-changed[^>]*>\s*<th scope="row">{field}')
        self.assertNotRegex(html, r'row-changed[^>]*>\s*<th scope="row">Backlogs')
        self.assertIn("does not prove", html)
        self.assertIn("checklist coverage", html.lower())

    def test_compare_via_checkbox_ids_and_order(self):
        html = self.client.get(f"/compare?ids={self.b}&ids={self.a}").get_data(as_text=True)
        self.assertIn(f"Record #{self.a} (earlier) vs record #{self.b} (later)", html)   # sorted by date

    def test_compare_invalid_selections_redirect(self):
        for qs in (f"a={self.a}&b={self.a}", "a=999&b=998", "a=x&b=y", f"ids={self.a}"):
            r = self.client.get("/compare?" + qs)
            self.assertEqual(r.status_code, 302, qs)
            self.assertIn("/history", r.headers["Location"])

    def test_compare_with_fewer_than_two_records(self):
        c = self.new_client("solo@example.com")
        make_record(c)
        r = c.get("/compare", follow_redirects=True)
        self.assertIn("at least two", r.get_data(as_text=True))

    def test_version_warning_when_models_differ(self):
        conn = sqlite3.connect(self.db)
        conn.execute("UPDATE predictions SET model_version='logreg-OLD' WHERE id=?", (self.a,))
        conn.commit(); conn.close()
        html = self.client.get(f"/compare?a={self.a}&b={self.b}").get_data(as_text=True)
        self.assertIn("may not be directly comparable", html)

    def test_delete_needs_confirmation(self):
        self.assertIn("cannot be undone", self.client.get(f"/history/{self.a}/delete").get_data(as_text=True))
        self.assertEqual(len(self.q("SELECT id FROM predictions")), 2)            # GET deletes nothing
        r = self.client.post(f"/history/{self.a}/delete")
        self.assertEqual(r.status_code, 302)
        self.assertEqual([r[0] for r in self.q("SELECT id FROM predictions")], [self.b])

    def test_deleting_original_removes_linked_simulation_only(self):
        self.client.post(f"/simulator/{self.a}/save", data={
            "cgpa": "9", "tenth_pct": "82", "twelfth_pct": "78", "backlogs": "0", "projects": "5",
            "internships": "2", "skills": "Python"})
        self.assertEqual(len(self.q("SELECT id FROM simulations")), 1)
        self.client.post(f"/history/{self.a}/delete")
        self.assertEqual(self.q("SELECT id FROM simulations"), [])
        self.assertEqual(len(self.q("SELECT id FROM predictions")), 2)            # b + what-if copy


class TestChartDataAndEmptyStates(Base):
    def setUp(self):
        super().setUp()
        register(self.client)

    def test_empty_states(self):
        html = self.client.get("/reports").get_data(as_text=True)
        self.assertIn("No data to chart yet", html)
        self.assertIn("generate the first one", html)
        self.assertIsNone(chart_json(html))
        self.assertIn("No predictions yet", self.client.get("/dashboard").get_data(as_text=True))
        self.assertIn("No predictions saved yet", self.client.get("/history").get_data(as_text=True))

    def test_trend_comes_from_saved_rows_only(self):
        ids = [make_record(self.client, cgpa=c) for c in ("5.0", "7.0", "9.0")]
        data = chart_json(self.client.get("/reports").get_data(as_text=True))
        saved = {r[0]: r[1] for r in self.q("SELECT id, probability_placed FROM predictions")}
        self.assertEqual(data["trend"]["ids"], ids)
        self.assertEqual(data["trend"]["probability"], [round(saved[i] * 100, 1) for i in ids])
        self.assertEqual(sum(data["distribution"]["counts"]), 3)
        self.assertLessEqual(len(data["trend"]["probability"]), 3)               # nothing invented

    def test_single_record_has_no_pair_or_timeline(self):
        make_record(self.client)
        html = self.client.get("/reports").get_data(as_text=True)
        data = chart_json(html)
        self.assertNotIn("pair", data); self.assertNotIn("timeline", data)
        self.assertIn("at least two saved predictions", html)

    def test_pair_defaults_to_latest_vs_previous(self):
        a = make_record(self.client, cgpa="5.0"); b = make_record(self.client, cgpa="9.0")
        data = chart_json(self.client.get("/reports").get_data(as_text=True))
        saved = {r[0]: r[1] for r in self.q("SELECT id, probability_placed FROM predictions")}
        self.assertEqual(data["pair"]["probability"], [round(saved[a] * 100, 1), round(saved[b] * 100, 1)])
        cgpa = data["pair"]["groups"][0]
        self.assertEqual((cgpa["a"], cgpa["b"]), ([5.0], [9.0]))

    def test_whatif_chart_uses_saved_simulation(self):
        rid = make_record(self.client, cgpa="6.0", projects="0")
        self.client.post(f"/simulator/{rid}/save", data={
            "cgpa": "9", "tenth_pct": "82", "twelfth_pct": "78", "backlogs": "0", "projects": "5",
            "internships": "2", "skills": "Python, SQL"})
        sim = self.q("SELECT original_probability, hypothetical_probability FROM simulations")[0]
        data = chart_json(self.client.get("/reports").get_data(as_text=True))
        self.assertEqual(data["whatif"]["probability"], [round(sim[0] * 100, 1), round(sim[1] * 100, 1)])
        self.assertTrue(any("CGPA" in c for c in data["whatif"]["changes"]))
        # saved what-if records are excluded from the trend by default (they are hypothetical)
        self.assertEqual(data["trend"]["ids"], [rid])
        incl = chart_json(self.client.get("/reports?whatif=1").get_data(as_text=True))
        self.assertEqual(len(incl["trend"]["ids"]), 2)

    def test_whatif_empty_state(self):
        make_record(self.client)
        self.assertIn("No saved what-if comparison yet", self.client.get("/reports").get_data(as_text=True))

    def test_readiness_chart_counts(self):
        make_record(self.client, skills="Python, Git", target_role="Python Developer")
        data = chart_json(self.client.get("/reports").get_data(as_text=True))
        self.assertEqual(data["readiness"]["counts"], [2, 2])
        self.assertEqual(data["readiness"]["percent"], 50)
        other = chart_json(self.client.get("/reports?role=Web+Developer").get_data(as_text=True))
        self.assertEqual(other["readiness"]["role"], "Web Developer")
        self.assertEqual(other["readiness"]["counts"], [1, 3])

    def test_date_range_filters_chart(self):
        a = make_record(self.client); b = make_record(self.client)
        conn = sqlite3.connect(self.db)
        conn.execute("UPDATE predictions SET created_at='2026-01-01T08:00:00' WHERE id=?", (a,))
        conn.commit(); conn.close()
        data = chart_json(self.client.get("/reports?from=2026-06-01").get_data(as_text=True))
        self.assertEqual(data["trend"]["ids"], [b])

    def test_csv_export(self):
        make_record(self.client)
        r = self.client.get("/reports/export.csv")
        self.assertEqual(r.mimetype, "text/csv")
        lines = r.get_data(as_text=True).strip().splitlines()
        self.assertEqual(len(lines), 2)
        self.assertIn("model_prediction", lines[0])
        self.assertIn("attachment", r.headers["Content-Disposition"])

    def test_labels_distinguish_prediction_from_outcome(self):
        make_record(self.client)
        html = self.client.get("/reports").get_data(as_text=True)
        self.assertIn("not a confirmed placement outcome", html)
        self.assertIn("not</strong> placement probability", html)

    def test_simulator_page_chart_data_is_live_model_output(self):
        rid = make_record(self.client, cgpa="6.0")
        html = self.client.post(f"/simulator/{rid}", data={
            "cgpa": "9", "tenth_pct": "82", "twelfth_pct": "78", "backlogs": "0", "projects": "2",
            "internships": "1", "skills": "Python, SQL"}).get_data(as_text=True)
        w = chart_json(html)["whatif"]
        self.assertEqual(w["labels"], ["Original", "Hypothetical"])
        self.assertGreater(w["probability"][1], w["probability"][0])


class TestReportsUnit(unittest.TestCase):
    def rec(self, i, prob, cls, created, source="prediction", version="v1", **kw):
        base = dict(id=i, student_name="X", cgpa=7, tenth_pct=80, twelfth_pct=80, backlogs=0, projects=1,
                    internships=0, skills=["Python"], target_role="Python Developer",
                    predicted_class=cls, probability_placed=prob, created_at=created, source=source,
                    model_version=version)
        base.update(kw)
        return base

    def test_trend_is_chronological_and_exact(self):
        recs = [self.rec(2, 0.8, "Placed", "2026-02-01T10:00:00"), self.rec(1, 0.3, "Not Placed", "2026-01-01T10:00:00")]
        t = reports.trend_data(recs)
        self.assertEqual(t["ids"], [1, 2]); self.assertEqual(t["probability"], [30.0, 80.0])

    def test_empty_inputs(self):
        self.assertEqual(reports.trend_data([])["labels"], [])
        self.assertEqual(reports.distribution([])["counts"], [0, 0])
        self.assertEqual(reports.summary_cards([], [], 0)["total_predictions"], 0)

    def test_no_probability_is_not_invented(self):
        t = reports.trend_data([self.rec(1, None, "Placed", "2026-01-01T10:00:00")])
        self.assertEqual(t["probability"], [None])

    def test_pair_comparison_flags_changes(self):
        a = self.rec(1, 0.4, "Not Placed", "2026-01-01T10:00:00")
        b = self.rec(2, 0.6, "Placed", "2026-02-01T10:00:00", cgpa=8, skills=["Python", "SQL"], version="v2")
        c = reports.pair_comparison(a, b)
        self.assertEqual(set(c["changed_fields"]), {"CGPA", "Recognised skills"})
        self.assertEqual(c["prob_delta"], 20.0); self.assertTrue(c["class_changed"])
        self.assertTrue(any("different" in n for n in c["notes"]))


class TestMigration(unittest.TestCase):
    def make_v1_db(self, path):
        conn = sqlite3.connect(path)
        conn.executescript("""
        CREATE TABLE predictions (id INTEGER PRIMARY KEY AUTOINCREMENT, student_name TEXT NOT NULL,
          cgpa REAL NOT NULL, tenth_pct REAL NOT NULL, twelfth_pct REAL NOT NULL, backlogs INTEGER NOT NULL,
          projects INTEGER NOT NULL, internships INTEGER NOT NULL, skills TEXT NOT NULL, target_role TEXT NOT NULL,
          predicted_class TEXT NOT NULL, probability_placed REAL, source TEXT NOT NULL DEFAULT 'prediction',
          created_at TEXT NOT NULL);
        INSERT INTO predictions (student_name,cgpa,tenth_pct,twelfth_pct,backlogs,projects,internships,skills,
          target_role,predicted_class,probability_placed,source,created_at)
          VALUES ('Legacy Student',7.1,80,75,0,2,1,'Python','Python Developer','Placed',0.66,'prediction','2026-01-01T10:00:00');
        """)
        conn.commit(); conn.close()

    def test_old_database_is_upgraded_without_losing_data(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "old.db")
            self.make_v1_db(path)
            app = create_app({"TESTING": True, "DATABASE": path, "CSRF_ENABLED": False, "PASSWORD_HASH_METHOD": FAST_HASH})
            conn = sqlite3.connect(path)
            cols = {r[1] for r in conn.execute("PRAGMA table_info(predictions)")}
            self.assertTrue({"user_id", "model_version"} <= cols)
            row = conn.execute("SELECT student_name, cgpa, probability_placed, user_id FROM predictions").fetchone()
            self.assertEqual(row, ("Legacy Student", 7.1, 0.66, None))             # preserved
            self.assertEqual(conn.execute("PRAGMA user_version").fetchone()[0], 2)
            conn.close()
            self.assertTrue(os.path.exists(path + ".bak-v1"))                      # safety copy
            create_app({"TESTING": True, "DATABASE": path})                         # idempotent
            # a newly registered user must NOT see the legacy (ownerless) row
            c = app.test_client()
            register(c)
            self.assertNotIn("Legacy Student", c.get("/history").get_data(as_text=True))
            self.assertEqual(c.get("/result/1").status_code, 404)
            self.assertEqual(login(c).status_code, 302)


class TestModelFailure(Base):
    def test_missing_and_corrupt_model_do_not_crash_or_save(self):
        bad = os.path.join(self.tmp.name, "bad.joblib")
        with open(bad, "wb") as fh:
            fh.write(b"junk")
        for path in (os.path.join(self.tmp.name, "nope.joblib"), bad):
            app = create_app(dict(self.cfg, MODEL_PATH=path, DATABASE=os.path.join(self.tmp.name, os.path.basename(path) + ".db")))
            c = app.test_client(); register(c)
            r = c.post("/predict", data=GOOD)
            self.assertEqual(r.status_code, 503)
            html = r.get_data(as_text=True)
            self.assertIn("train_model.py", html); self.assertNotIn("Traceback", html)
            self.assertEqual(c.get("/reports").status_code, 200)
            self.assertEqual(c.get("/dashboard").status_code, 200)


if __name__ == "__main__":
    unittest.main()
