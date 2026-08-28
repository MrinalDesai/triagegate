"""
orders.py — Order management for Shopfast.

Provides:
  create_order(customer_id, item, amount, idempotency_key=None) -> dict
  list_orders() -> list[dict]
  get_orders_by_customer(customer_id) -> list[dict]
"""

from __future__ import annotations

from typing import Optional

from .db import get_connection


def create_order(
    customer_id: str,
    item: str,
    amount: float,
    idempotency_key: Optional[str] = None,
) -> dict:
    """Insert a new order row and return the created order as a dict."""
    conn = get_connection()
    cur = conn.execute(
        """
        INSERT INTO orders (customer_id, item, amount, idempotency_key)
        VALUES (?, ?, ?, ?)
        """,
        (customer_id, item, amount, idempotency_key),
    )
    conn.commit()
    row = conn.execute(
        "SELECT * FROM orders WHERE id = ?", (cur.lastrowid,)
    ).fetchone()
    return dict(row)


def list_orders() -> list[dict]:
    """Return all orders, newest first."""
    conn = get_connection()
    rows = conn.execute(
        "SELECT * FROM orders ORDER BY id DESC"
    ).fetchall()
    return [dict(r) for r in rows]


def get_orders_by_customer(customer_id: str) -> list[dict]:
    """Return all orders for a specific customer, newest first."""
    conn = get_connection()
    rows = conn.execute(
        "SELECT * FROM orders WHERE customer_id = ? ORDER BY id DESC",
        (customer_id,),
    ).fetchall()
    return [dict(r) for r in rows]


def _clear_orders(conn=None) -> None:
    """Delete all orders — test helper only."""
    c = conn or get_connection()
    c.execute("DELETE FROM orders")
    c.commit()
