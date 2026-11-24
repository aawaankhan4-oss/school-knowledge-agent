"""Real per-person accounts, replacing the original single shared password.

Passwords are always hashed (werkzeug's salted hash) — never stored or
logged in plain text.
"""
from datetime import datetime, timezone

from werkzeug.security import check_password_hash, generate_password_hash


class UsernameTaken(Exception):
    pass


def create_user(conn, username, password, is_admin=False):
    username = username.strip()
    if not username:
        raise ValueError("Username is required.")
    if not password:
        raise ValueError("Password is required.")
    if conn.execute("SELECT id FROM users WHERE username = ?", (username,)).fetchone():
        raise UsernameTaken(f"'{username}' is already taken.")

    now = datetime.now(timezone.utc).isoformat()
    cur = conn.execute(
        "INSERT INTO users (username, password_hash, is_admin, created_at) VALUES (?, ?, ?, ?)",
        (username, generate_password_hash(password), 1 if is_admin else 0, now),
    )
    conn.commit()
    return cur.lastrowid


def verify_login(conn, username, password):
    """Returns {"id", "username", "is_admin"} on success, or None."""
    row = conn.execute(
        "SELECT id, username, password_hash, is_admin FROM users WHERE username = ?",
        (username.strip(),),
    ).fetchone()
    if not row or not check_password_hash(row[2], password):
        return None
    return {"id": row[0], "username": row[1], "is_admin": bool(row[3])}


def seed_admin_from_env(conn):
    """One-time migration: if no accounts exist yet but the old
    APP_PASSWORD_HASH env var is set, create a named 'admin' account that
    keeps working with that same password — so upgrading to real accounts
    doesn't lock out whoever already knew the shared password."""
    import os

    if conn.execute("SELECT COUNT(*) FROM users").fetchone()[0]:
        return
    legacy_hash = os.environ.get("APP_PASSWORD_HASH")
    if not legacy_hash:
        return

    now = datetime.now(timezone.utc).isoformat()
    conn.execute(
        "INSERT INTO users (username, password_hash, is_admin, created_at) VALUES (?, ?, 1, ?)",
        ("admin", legacy_hash, now),
    )
    conn.commit()
    print("[auth] Seeded an 'admin' account using the existing shared password.")
