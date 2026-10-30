"""Shared helpers for the test-suite (account creation, login, CSRF tokens)."""
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

FAST_HASH = "pbkdf2:sha256:1000"      # fast hashing so tests run quickly
PASSWORD = "Passw0rdOK"

GOOD = {
    "student_name": "Asha Verma", "cgpa": "7.5", "tenth_pct": "82", "twelfth_pct": "78",
    "backlogs": "0", "projects": "2", "internships": "1",
    "skills": "Python, SQL", "target_role": "Python Developer",
}


def csrf_from(client, url):
    html = client.get(url).get_data(as_text=True)
    m = re.search(r'name="_csrf" value="([0-9a-f]+)"', html)
    return m.group(1) if m else ""


def register(client, name="Test User", email="test@example.com", password=PASSWORD, csrf=False):
    data = {"name": name, "email": email, "password": password, "confirm_password": password}
    if csrf:
        data["_csrf"] = csrf_from(client, "/register")
    return client.post("/register", data=data)


def login(client, email="test@example.com", password=PASSWORD, csrf=False, **extra):
    data = {"email": email, "password": password}
    data.update(extra)
    if csrf:
        data["_csrf"] = csrf_from(client, "/login")
    return client.post("/login", data=data)


def make_record(client, **overrides):
    resp = client.post("/predict", data=dict(GOOD, **overrides))
    assert resp.status_code == 302, resp.status_code
    return int(re.search(r"/result/(\d+)", resp.headers["Location"]).group(1))
