"""
payments.py — Payment / charge simulation for Shopfast.
"""

from __future__ import annotations

from typing import Optional

from .db import get_connection
from .orders import create_order


def charge(
    customer_id: str,
    item: str,
    amount: float,
    idempotency_key: Optional[str] = None,
) -> dict:
    """
    Simulate charging a customer and record the resulting order.

    Parameters
    ----------
    customer_id:      identifier for the customer being charged
    item:             description of the purchased item
    amount:           charge amount in USD
    idempotency_key:  caller-supplied key for retry deduplication

    Returns
    -------
    dict with the created order record.
    """
    if idempotency_key is not None:
        existing = get_charge_by_idempotency_key(idempotency_key)
        if existing is not None:
            return existing
    return create_order(
        customer_id=customer_id,
        item=item,
        amount=amount,
        idempotency_key=idempotency_key,
    )


def get_charge_by_idempotency_key(idempotency_key: str) -> Optional[dict]:
    """Look up an existing order by its idempotency key (used by the fix)."""
    conn = get_connection()
    row = conn.execute(
        "SELECT * FROM orders WHERE idempotency_key = ? LIMIT 1",
        (idempotency_key,),
    ).fetchone()
    return dict(row) if row else None
