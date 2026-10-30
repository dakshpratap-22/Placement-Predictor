"""Tests for the Admin dashboard (admin.py) and the expanded role list."""
import json
import os
import re
import sqlite3
import tempfile
import unittest

from app import create_app
from ml_utils import SKILL_CATALOG
from roles_config import LEARNING_TIPS, PROJECT_IDEAS, ROLE_SKILLS
from tests.helpers import FAST_HASH, GOOD, PASSWORD, login, make_record, register

ADMIN = "boss@example.com"


def chart_json(html):
    m = re.search(r'<script type="application/json" id="chart-data">(.*?)</script>', html, re.S)
    return json.loads(m.group(1)) if m else None


class RoleConfigTests(unittest.TestCase):
    def test_original_roles_still_present(self):
        for r in ("Python Developer", "Data Analyst", "Web Developer"):
            self.assertIn(r, ROLE_SKILLS)

    def test_more_roles_than_before(self):
        self.assertGreaterEqual(len(ROLE_SKILLS), 12)

    def test_every_skill_is_in_the_catalogue(self):
        for role, skills in ROLE_SKILLS.items():
            self.assertTrue(skills, role)
            for s in skills:
                self.assertIn(s, SKILL_CATALOG, f"{role}: '{s}' is not in ml_utils.SKILL_CATALOG")

    def test_tips_and_ideas_refer_to_real_things(self):
        for s in LEARNING_TIPS:
            self.assertIn(s, SKILL_CATALOG)
        for r, ideas in PROJECT_IDEAS.items():
            self.assertIn(r, ROLE_SKILLS)
            self.assertGreaterEqual(len(ideas), 1)

    def test_no_duplicate_skills_within_a_role(self):
        for role, skills in ROLE_SKILLS.items():
            self.assertEqual(len(skills), len(set(skills)), role)


class AdminBase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = os.path.join(self.tmp.name, "t.db")
        self.app = create_app({"TESTING": True, "DATABASE": self.db, "CSRF_ENABLED": False,
                               "PASSWORD_HASH_METHOD": FAST_HASH, "ADMIN_EMAILS": ADMIN})
        self.admin = self.app.test_client()
        register(self.admin, name="Boss Person", email=ADMIN)

    def tearDown(self):
        self.tmp.cleanup()

    def user(self, email, name="Some Student"):
        c = self.app.test_client()
        register(c, name=name, email=email)
        return c

    def q(self, sql, args=()):
        conn = sqlite3.connect(self.db)
        try:
            return conn.execute(sql, args).fetchall()
        finally:
            conn.close()


class TestAdminAccess(AdminBase):
    def test_anonymous_redirected_to_login(self):
        r = self.app.test_client().get("/admin/")
        self.assertEqual(r.status_code, 302)
        self.assertIn("/login", r.headers["Location"])

    def test_normal_user_gets_404_and_no_link(self):
        c = self.user("stud@example.com")
        self.assertEqual(c.get("/admin/").status_code, 404)
        self.assertNotIn("Admin dashboard", c.get("/dashboard").get_data(as_text=True))
        uid = self.q("SELECT id FROM users WHERE email='stud@example.com'")[0][0]
        self.assertEqual(c.get(f"/admin/users/{uid}/delete").status_code, 404)
        self.assertEqual(c.post(f"/admin/users/{uid}/delete").status_code, 404)
        self.assertEqual(len(self.q("SELECT id FROM users")), 2)

    def test_admin_sees_dashboard_and_link(self):
        self.assertEqual(self.admin.get("/admin/").status_code, 200)
        self.assertIn("Admin dashboard", self.admin.get("/dashboard").get_data(as_text=True))

    def test_no_admins_configured_means_nobody_is_admin(self):
        app = create_app({"TESTING": True, "DATABASE": os.path.join(self.tmp.name, "n.db"),
                          "CSRF_ENABLED": False, "PASSWORD_HASH_METHOD": FAST_HASH, "ADMIN_EMAILS": ""})
        c = app.test_client(); register(c, email=ADMIN)
        self.assertEqual(c.get("/admin/").status_code, 404)

    def test_admin_email_match_is_case_insensitive(self):
        app = create_app({"TESTING": True, "DATABASE": os.path.join(self.tmp.name, "c.db"),
                          "CSRF_ENABLED": False, "PASSWORD_HASH_METHOD": FAST_HASH, "ADMIN_EMAILS": " Boss@Example.com , x@y.com"})
        c = app.test_client(); register(c, email=ADMIN)
        self.assertEqual(c.get("/admin/").status_code, 200)


class TestAdminData(AdminBase):
    def test_empty_state(self):
        html = self.admin.get("/admin/").get_data(as_text=True)
        self.assertIn("No predictions have been run yet", html)
        self.assertIn("Registered users", html)

    def test_numbers_match_the_database(self):
        a = self.user("a@example.com"); b = self.user("b@example.com")
        make_record(a); make_record(a, target_role="Data Scientist"); make_record(b, target_role="Data Scientist")
        html = self.admin.get("/admin/").get_data(as_text=True)
        data = chart_json(html)
        self.assertEqual(sum(data["distribution"]["counts"]), 3)
        self.assertEqual(sum(data["daily"]["counts"]), 3)
        placed = self.q("SELECT COUNT(*) FROM predictions WHERE predicted_class='Placed'")[0][0]
        self.assertEqual(data["distribution"]["counts"][0], placed)
        self.assertRegex(html, r"Registered users</div><div class=\"stat-value\">3<")
        self.assertRegex(html, r"Predictions run</div><div class=\"stat-value\">3<")
        self.assertRegex(html, r"Data Scientist</td>\s*<td class=\"small\">[^<]*</td>\s*<td>2</td>")

    def test_all_configured_roles_are_listed(self):
        html = self.admin.get("/admin/").get_data(as_text=True)
        for role in ROLE_SKILLS:
            self.assertIn(role, html)

    def test_user_list_counts_and_search(self):
        a = self.user("alice@example.com", name="Alice Wonder"); self.user("bob@example.com", name="Bob Builder")
        make_record(a); make_record(a)
        html = self.admin.get("/admin/").get_data(as_text=True)
        self.assertIn("alice@example.com", html); self.assertIn("bob@example.com", html)
        only = self.admin.get("/admin/?q=alice").get_data(as_text=True)
        self.assertIn("alice@example.com", only); self.assertNotIn("bob@example.com", only)
        self.assertEqual(self.admin.get("/admin/?q=%25").status_code, 200)       # wildcard is escaped, not matched
        self.assertNotIn("alice@example.com", self.admin.get("/admin/?q=%25").get_data(as_text=True))

    def test_other_users_profiles_are_not_shown(self):
        a = self.user("alice@example.com"); make_record(a, student_name="Secret Studentname")
        self.assertNotIn("Secret Studentname", self.admin.get("/admin/").get_data(as_text=True))

    def test_legacy_rows_not_counted_but_flagged(self):
        conn = sqlite3.connect(self.db)
        conn.execute("INSERT INTO predictions (student_name,cgpa,tenth_pct,twelfth_pct,backlogs,projects,internships,skills,"
                     "target_role,predicted_class,probability_placed,source,created_at) VALUES "
                     "('Old',7,80,75,0,1,0,'Python','Python Developer','Placed',0.6,'prediction','2026-01-01T10:00:00')")
        conn.commit(); conn.close()
        html = self.admin.get("/admin/").get_data(as_text=True)
        self.assertIn("no owner", html)
        self.assertEqual(sum(chart_json(html)["distribution"]["counts"]) if chart_json(html) else 0, 0)


class TestAdminDelete(AdminBase):
    def setUp(self):
        super().setUp()
        self.s = self.user("stud@example.com")
        make_record(self.s)
        self.uid = self.q("SELECT id FROM users WHERE email='stud@example.com'")[0][0]

    def test_confirmation_then_delete_cascades(self):
        html = self.admin.get(f"/admin/users/{self.uid}/delete").get_data(as_text=True)
        self.assertIn("cannot be undone", html)
        self.assertEqual(len(self.q("SELECT id FROM users")), 2)                  # GET deletes nothing
        self.assertEqual(self.admin.post(f"/admin/users/{self.uid}/delete").status_code, 302)
        self.assertEqual(self.q("SELECT id FROM users WHERE id=?", (self.uid,)), [])
        self.assertEqual(self.q("SELECT id FROM predictions"), [])
        self.assertEqual(self.s.get("/dashboard").status_code, 302)               # deleted user is logged out

    def test_cannot_delete_self_or_other_admin(self):
        my_id = self.q("SELECT id FROM users WHERE email=?", (ADMIN,))[0][0]
        self.assertEqual(self.admin.post(f"/admin/users/{my_id}/delete").status_code, 302)
        self.assertEqual(len(self.q("SELECT id FROM users WHERE id=?", (my_id,))), 1)

    def test_delete_unknown_user_is_404(self):
        self.assertEqual(self.admin.post("/admin/users/9999/delete").status_code, 404)

    def test_csrf_enforced_on_delete(self):
        app = create_app({"TESTING": True, "DATABASE": os.path.join(self.tmp.name, "csrf.db"),
                          "CSRF_ENABLED": True, "PASSWORD_HASH_METHOD": FAST_HASH, "ADMIN_EMAILS": ADMIN})
        c = app.test_client(); register(c, email=ADMIN, csrf=True)
        self.assertEqual(c.post("/admin/users/2/delete").status_code, 400)


class TestNewRolesWork(AdminBase):
    def test_every_role_can_be_predicted_and_has_a_readiness_page(self):
        c = self.user("stud@example.com")
        for role in ROLE_SKILLS:
            rid = make_record(c, target_role=role, skills="Python, SQL")
            self.assertEqual(c.get(f"/readiness/{rid}").status_code, 200, role)
            self.assertIn(role, c.get("/predict").get_data(as_text=True))


if __name__ == "__main__":
    unittest.main()
