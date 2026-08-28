"""
test_orders.py — unit tests for app/orders.py
"""

import pytest
from app.orders import create_order, list_orders, get_orders_by_customer


def test_create_order_returns_dict():
    order = create_order("cust_1", "Widget", 9.99)
    assert isinstance(order, dict)


def test_create_order_has_expected_fields():
    order = create_order("cust_1", "Widget", 9.99)
    for field in ("id", "customer_id", "item", "amount"):
        assert field in order, f"missing field: {field}"


def test_create_order_stores_correct_values():
    order = create_order("cust_42", "Gadget", 49.99)
    assert order["customer_id"] == "cust_42"
    assert order["item"] == "Gadget"
    assert order["amount"] == pytest.approx(49.99)


def test_create_order_auto_increments_id():
    o1 = create_order("cust_1", "A", 1.0)
    o2 = create_order("cust_1", "B", 2.0)
    assert o2["id"] == o1["id"] + 1


def test_list_orders_empty_initially():
    assert list_orders() == []


def test_list_orders_returns_all():
    create_order("c1", "X", 1.0)
    create_order("c2", "Y", 2.0)
    assert len(list_orders()) == 2


def test_list_orders_newest_first():
    o1 = create_order("c1", "First", 1.0)
    o2 = create_order("c1", "Second", 2.0)
    orders = list_orders()
    assert orders[0]["id"] == o2["id"]
    assert orders[1]["id"] == o1["id"]


def test_get_orders_by_customer_returns_only_matching():
    create_order("alice", "Hat", 10.0)
    create_order("bob", "Bag", 20.0)
    create_order("alice", "Coat", 30.0)
    alice_orders = get_orders_by_customer("alice")
    assert len(alice_orders) == 2
    assert all(o["customer_id"] == "alice" for o in alice_orders)


def test_get_orders_by_customer_empty_for_unknown():
    create_order("alice", "Hat", 10.0)
    assert get_orders_by_customer("nobody") == []


def test_create_order_stores_idempotency_key():
    order = create_order("c1", "Item", 5.0, idempotency_key="key-abc")
    assert order["idempotency_key"] == "key-abc"
