"""
db.py - database schema and safe, additive migration for Placement Predictor.

Schema versions (stored in SQLite's PRAGMA user_version):
  0/1  original project: a single `predictions` table, no users.
  2    adds `users`, `simulations`, and two columns on `predictions`
       (`user_id`, `model_version`).

The migration only ADDS tables/columns. It never drops or rewrites existing
rows. Before upgrading a database that already holds data, a copy of the file
is saved next to it (placement.db.bak-v1) so nothing can be lost.
"""

import os
import shutil
import sqlite3

SCHEMA_VERSION = 2

USERS_SQL = """
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    email TEXT NOT NULL UNIQUE,              -- stored lower-case
    password_hash TEXT NOT NULL,             -- werkzeug hash, never plain text
    created_at TEXT NOT NULL
);
"""

# Column order matters for the original 13 columns (existing code/tests index
# them); the two new columns are always LAST so ALTER TABLE gives the same shape.
PREDICTIONS_SQL = """
CREATE TABLE IF NOT EXISTS predictions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    student_name TEXT NOT NULL,
    cgpa REAL NOT NULL,
    tenth_pct REAL NOT NULL,
    twelfth_pct REAL NOT NULL,
    backlogs INTEGER NOT NULL,
    projects INTEGER NOT NULL,
    internships INTEGER NOT NULL,
    skills TEXT NOT NULL,
    target_role TEXT NOT NULL,
    predicted_class TEXT NOT NULL,
    probability_placed REAL,
    source TEXT NOT NULL DEFAULT 'prediction',
    created_at TEXT NOT NULL,
    user_id INTEGER REFERENCES users(id) ON DELETE CASCADE,
    model_version TEXT
);
"""

SIMULATIONS_SQL = """
CREATE TABLE IF NOT EXISTS simulations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    original_id INTEGER NOT NULL REFERENCES predictions(id) ON DELETE CASCADE,
    hypothetical_id INTEGER NOT NULL REFERENCES predictions(id) ON DELETE CASCADE,
    original_class TEXT NOT NULL,
    hypothetical_class TEXT NOT NULL,
    original_probability REAL,
    hypothetical_probability REAL,
    model_version TEXT,
    created_at TEXT NOT NULL
);
"""

INDEXES_SQL = """
CREATE INDEX IF NOT EXISTS idx_predictions_user_time ON predictions(user_id, created_at);
CREATE INDEX IF NOT EXISTS idx_simulations_user ON simulations(user_id, created_at);
"""


def connect(path):
    """Open a connection with row access by name and foreign keys enforced."""
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def _columns(conn, table):
    return {r[1] for r in conn.execute(f"PRAGMA table_info({table})")}


def _table_exists(conn, table):
    return conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
                        (table,)).fetchone() is not None


def migrate(path):
    """Create or upgrade the database at `path` to SCHEMA_VERSION. Idempotent."""
    conn = sqlite3.connect(path)
    try:
        version = conn.execute("PRAGMA user_version").fetchone()[0]
        had_predictions = _table_exists(conn, "predictions")

        # Safety copy before touching a database that already contains rows.
        if version < SCHEMA_VERSION and had_predictions and os.path.exists(path):
            has_rows = conn.execute("SELECT COUNT(*) FROM predictions").fetchone()[0] > 0
            backup = path + ".bak-v1"
            if has_rows and not os.path.exists(backup):
                shutil.copy2(path, backup)

        conn.execute(USERS_SQL)
        conn.execute(PREDICTIONS_SQL)           # no-op if the table already exists
        cols = _columns(conn, "predictions")
        if "user_id" not in cols:               # upgrade from the original schema
            conn.execute("ALTER TABLE predictions ADD COLUMN user_id INTEGER "
                         "REFERENCES users(id) ON DELETE CASCADE")
        if "model_version" not in cols:
            conn.execute("ALTER TABLE predictions ADD COLUMN model_version TEXT")
        conn.execute(SIMULATIONS_SQL)
        conn.executescript(INDEXES_SQL)
        conn.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
        conn.commit()
    finally:
        conn.close()
