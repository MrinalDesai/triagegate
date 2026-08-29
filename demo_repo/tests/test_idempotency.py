"""
test_idempotency.py — regression test for idempotency_key behaviour in payments.py

STATUS: EXPECTED TO FAIL.

Observed symptom: retrying a charge with the same idempotency_key does not
return the original order — it yields a new, different order id, resulting in
duplicate orders in the database for what should have been a single transaction.
"""

import pytest
from app.payments import charge
from app.orders import list_orders, get_orders_by_customer


def test_retry_charge_with_same_idempotency_key_creates_only_one_order():
    """
    Calling charge() twice with the same idempotency_key MUST result in
    exactly ONE order in the database.  The second call should return the
    original order rather than creating a duplicate.

    Currently FAILS: a retry yields a new order id instead of the original,
    producing two distinct orders for a single logical transaction.
    """
    key = "idem-test-key-001"

    first = charge("cust_retry", "Laptop", 999.0, idempotency_key=key)
    second = charge("cust_retry", "Laptop", 999.0, idempotency_key=key)

    # Both calls should return the same order (same id)
    assert first["id"] == second["id"], (
        "Retried charge returned a different order id — duplicate was created"
    )

    # Only one order should exist in the database
    all_orders = list_orders()
    customer_orders = get_orders_by_customer("cust_retry")

    assert len(all_orders) == 1, (
        f"Expected 1 order but found {len(all_orders)} — "
        "idempotency_key is not being enforced"
    )
    assert len(customer_orders) == 1, (
        f"Expected 1 order for customer but found {len(customer_orders)}"
    )
