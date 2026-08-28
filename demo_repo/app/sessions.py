"""
sessions.py — In-memory session store for Shopfast.

Provides:
  issue_token(user_id, ttl_seconds=3600) -> str   (returns the token)
  validate_token(token) -> str | None              (returns user_id or None)
  expire_token(token) -> bool                      (True if the token existed)
"""

from __future__ import annotations

import secrets
import time
from typing import Optional

# token -> {"user_id": str, "expires_at": float}
_store: dict[str, dict] = {}


def issue_token(user_id: str, ttl_seconds: int = 3600) -> str:
    """Create a new session token for *user_id* and store it in memory."""
    token = secrets.token_urlsafe(32)
    _store[token] = {
        "user_id": user_id,
        "expires_at": time.time() + ttl_seconds,
    }
    return token


def validate_token(token: str) -> Optional[str]:
    """
    Return the user_id bound to *token* if the token is valid and not expired,
    otherwise return None and clean up the stale entry.
    """
    entry = _store.get(token)
    if entry is None:
        return None
    if time.time() > entry["expires_at"]:
        del _store[token]
        return None
    return entry["user_id"]


def expire_token(token: str) -> bool:
    """
    Explicitly invalidate a token (logout).  Returns True if the token was
    present (whether or not it had already expired naturally).
    """
    return _store.pop(token, None) is not None


def _clear_sessions() -> None:
    """Remove all sessions — test helper only."""
    _store.clear()


def _session_count() -> int:
    """Return the number of live sessions — test helper only."""
    return len(_store)
