"""
conftest.py — shared pytest fixtures for Shopfast tests.

Each test module gets a fresh in-memory SQLite database so tests are fully
isolated from each other.
"""

import pytest

from app.db import reset_connection
from app.orders import _clear_orders
from app.sessions import _clear_sessions


@pytest.fixture(autouse=True)
def fresh_db():
    """Reset the SQLite connection and wipe the session store before every test."""
    reset_connection(":memory:")
    _clear_sessions()
    yield
    # nothing to tear down — :memory: DB is discarded automatically
