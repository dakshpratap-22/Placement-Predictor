"""
auth_utils.py - small, dependency-free helpers for registration and login.

Passwords are hashed with Werkzeug (salted, slow hash). Plain-text passwords
are never stored or logged.
"""

import re
import time
from collections import defaultdict, deque

from werkzeug.security import check_password_hash, generate_password_hash

EMAIL_RE = re.compile(r"^[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}$")
NAME_RE = re.compile(r"[A-Za-z][A-Za-z .'\-]*")
MIN_PASSWORD = 8
MAX_PASSWORD = 128

# A valid hash of a random string; used so a login attempt for an unknown email
# costs about the same time as one for a real account (reduces user enumeration).
_DUMMY_HASH = generate_password_hash("not-a-real-password")


def normalise_email(raw):
    return (raw or "").strip().lower()


def validate_registration(form):
    """Return (clean, errors). `clean` has name, email, password."""
    errors, clean = {}, {}

    name = re.sub(r"\s+", " ", (form.get("name") or "")).strip()
    if not name:
        errors["name"] = "Name is required."
    elif len(name) > 60:
        errors["name"] = "Name must be 60 characters or fewer."
    elif not NAME_RE.fullmatch(name):
        errors["name"] = "Name may contain only letters, spaces, . ' and -."
    clean["name"] = name

    email = normalise_email(form.get("email"))
    if not email:
        errors["email"] = "Email is required."
    elif len(email) > 120 or not EMAIL_RE.fullmatch(email):
        errors["email"] = "Please enter a valid email address."
    clean["email"] = email

    password = form.get("password") or ""
    confirm = form.get("confirm_password") or ""
    if not password:
        errors["password"] = "Password is required."
    elif len(password) < MIN_PASSWORD:
        errors["password"] = f"Password must be at least {MIN_PASSWORD} characters."
    elif len(password) > MAX_PASSWORD:
        errors["password"] = f"Password must be at most {MAX_PASSWORD} characters."
    elif not (re.search(r"[A-Za-z]", password) and re.search(r"\d", password)):
        errors["password"] = "Password must contain at least one letter and one number."
    if "password" not in errors:
        if not confirm:
            errors["confirm_password"] = "Please confirm your password."
        elif confirm != password:
            errors["confirm_password"] = "The two passwords do not match."
    clean["password"] = password
    return clean, errors


def hash_password(password, method=None):
    return generate_password_hash(password, method=method) if method else generate_password_hash(password)


def verify_password(stored_hash, password):
    """Constant-effort check; pass stored_hash=None for an unknown account."""
    if stored_hash is None:
        check_password_hash(_DUMMY_HASH, password or "")
        return False
    return check_password_hash(stored_hash, password or "")


def safe_next_url(target):
    """Only allow redirects to a local path (blocks open redirects)."""
    if target and target.startswith("/") and not target.startswith("//") and "\\" not in target:
        return target
    return None


class LoginThrottle:
    """In-memory limiter: at most `limit` failed logins per `window` seconds per
    (email, ip). Per-process only - fine for a student project; use a shared
    store (e.g. Redis) behind several servers."""

    def __init__(self, limit=5, window=600):
        self.limit, self.window = limit, window
        self._fails = defaultdict(deque)

    def _prune(self, key, now):
        q = self._fails[key]
        while q and now - q[0] > self.window:
            q.popleft()
        return q

    def blocked(self, key, now=None):
        now = time.time() if now is None else now
        return len(self._prune(key, now)) >= self.limit

    def record_failure(self, key, now=None):
        now = time.time() if now is None else now
        self._prune(key, now).append(now)

    def reset(self, key):
        self._fails.pop(key, None)
