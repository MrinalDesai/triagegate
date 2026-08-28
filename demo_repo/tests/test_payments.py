"""
test_payments.py — unit tests for app/payments.py
"""

import pytest
from app.payments import charge, get_charge_by_idempotency_key
from app.orders import list_orders


def test_charge_returns_order_dict():
    result = charge("cust_1", "Book", 12.99)
    assert isinstance(result, dict)
    assert result["customer_id"] == "cust_1"


def test_charge_creates_order_row():
    charge("cust_2", "Pen", 1.99)
    orders = list_orders()
    assert len(orders) == 1
    assert orders[0]["item"] == "Pen"


def test_charge_stores_idempotency_key():
    result = charge("cust_3", "Desk", 199.0, idempotency_key="idem-xyz")
    assert result["idempotency_key"] == "idem-xyz"


def test_charge_without_idempotency_key():
    result = charge("cust_4", "Chair", 49.0)
    assert result["idempotency_key"] is None


def test_get_charge_by_idempotency_key_found():
    charge("cust_5", "Lamp", 29.0, idempotency_key="find-me")
    found = get_charge_by_idempotency_key("find-me")
    assert found is not None
    assert found["idempotency_key"] == "find-me"


def test_get_charge_by_idempotency_key_not_found():
    result = get_charge_by_idempotency_key("nonexistent-key")
    assert result is None
