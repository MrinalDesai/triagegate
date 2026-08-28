"""
test_db.py — unit tests for app/db.py
"""

import pytest
from app.db import get_connection, reset_connection, init_db


def test_get_connection_returns_connection():
    conn = get_connection()
    assert conn is not None


def test_get_connection_is_singleton():
    conn1 = get_connection()
    conn2 = get_connection()
    assert conn1 is conn2


def test_reset_connection_creates_new_connection():
    conn1 = get_connection()
    conn2 = reset_connection(":memory:")
    # After reset a new object is returned
    assert conn2 is not conn1


def test_orders_table_exists():
    conn = get_connection()
    result = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='orders'"
    ).fetchone()
    assert result is not None


def test_sessions_table_exists():
    conn = get_connection()
    result = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='sessions'"
    ).fetchone()
    assert result is not None


def test_orders_table_has_idempotency_key_column():
    conn = get_connection()
    cols = [
        row[1]
        for row in conn.execute("PRAGMA table_info(orders)").fetchall()
    ]
    assert "idempotency_key" in cols
