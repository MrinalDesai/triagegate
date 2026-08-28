"""
test_sessions.py — unit tests for app/sessions.py
"""

import time
import pytest
from app.sessions import issue_token, validate_token, expire_token, _session_count


def test_issue_token_returns_string():
    token = issue_token("user_1")
    assert isinstance(token, str) and len(token) > 10


def test_issued_tokens_are_unique():
    t1 = issue_token("user_1")
    t2 = issue_token("user_1")
    assert t1 != t2


def test_validate_token_returns_user_id():
    token = issue_token("alice")
    assert validate_token(token) == "alice"


def test_validate_token_unknown_returns_none():
    assert validate_token("bogus-token-xyz") is None


def test_validate_token_expired_returns_none():
    token = issue_token("bob", ttl_seconds=0)
    # TTL of 0 means it is already expired
    time.sleep(0.01)
    assert validate_token(token) is None


def test_expire_token_returns_true_for_valid():
    token = issue_token("charlie")
    assert expire_token(token) is True


def test_expire_token_invalidates_session():
    token = issue_token("dave")
    expire_token(token)
    assert validate_token(token) is None


def test_expire_token_returns_false_for_unknown():
    assert expire_token("no-such-token") is False


def test_session_count_increments():
    before = _session_count()
    issue_token("eve")
    assert _session_count() == before + 1


def test_session_count_decrements_after_expire():
    token = issue_token("frank")
    before = _session_count()
    expire_token(token)
    assert _session_count() == before - 1
