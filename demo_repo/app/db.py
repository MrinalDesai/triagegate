"""
db.py — SQLite database helpers for Shopfast.

Uses the stdlib sqlite3 module with a file-based (or in-memory) database.
The module exposes get_connection() which callers use as a context manager,
plus init_db() to create the schema on first run.
"""

import sqlite3
import os

_DB_PATH = os.environ.get("SHOPFAST_DB", ":memory:")
_conn: sqlite3.Connection | None = None


def get_connection() -> sqlite3.Connection:
    """Return the shared SQLite connection, creating it if needed."""
    global _conn
    if _conn is None:
        _conn = sqlite3.connect(_DB_PATH, check_same_thread=False)
        _conn.row_factory = sqlite3.Row
        init_db(_conn)
    return _conn


def reset_connection(db_path: str = ":memory:") -> sqlite3.Connection:
    """Close any existing connection and open a fresh one (useful in tests)."""
    global _conn, _DB_PATH
    if _conn is not None:
        try:
            _conn.close()
        except Exception:
            pass
    _DB_PATH = db_path
    _conn = None
    return get_connection()


def init_db(conn: sqlite3.Connection) -> None:
    """Create tables if they do not already exist."""
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS orders (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            customer_id     TEXT    NOT NULL,
            item            TEXT    NOT NULL,
            amount          REAL    NOT NULL,
            idempotency_key TEXT,
            created_at      TEXT    DEFAULT (datetime('now'))
        );

        CREATE TABLE IF NOT EXISTS sessions (
            token       TEXT PRIMARY KEY,
            user_id     TEXT NOT NULL,
            expires_at  TEXT NOT NULL
        );
        """
    )
    conn.commit()
