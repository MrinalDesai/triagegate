"""
test_idempotency.py — regression test for the idempotency_key bug in payments.py

STATUS: EXPECTED TO FAIL until the bug described in KNOWN_BUG.md is fixed.

The bug:  charge() accepts an idempotency_key but never checks whether an
          order with that key already exists.  Retrying the same charge
          therefore inserts a duplicate order row.

The fix:  Before inserting, look up any existing order with the same
          idempotency_key and return it immediately if found.
"""

import pytest
from app.payments import charge
from app.orders import list_orders, get_orders_by_customer


def test_retry_charge_with_same_idempotency_key_creates_only_one_order():
    """
    Calling charge() twice with the same idempotency_key MUST result in
    exactly ONE order in the database.  The second call should return the
    original order rather than creating a duplicate.

    This test currently FAILS because payments.charge() does not check for an
    existing order before inserting (see KNOWN_BUG.md).
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
