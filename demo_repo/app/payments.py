"""
payments.py — Payment / charge simulation for Shopfast.

BUG (seeded): charge() accepts an idempotency_key parameter but never checks
whether an order with that key already exists before inserting.  Retrying a
charge with the same idempotency_key therefore creates a duplicate order row
instead of returning the original one.  See KNOWN_BUG.md for details.
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
    idempotency_key:  caller-supplied key intended to make retries safe
                      (NOT currently enforced — see KNOWN_BUG.md)

    Returns
    -------
    dict with the created order record.
    """
    # ------------------------------------------------------------------ #
    # BUG: the idempotency_key should be looked up here and the existing  #
    # order returned if found.  The missing check is intentional for the  #
    # regression test in tests/test_idempotency.py.                       #
    # ------------------------------------------------------------------ #
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
