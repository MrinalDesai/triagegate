"""
main.py — Shopfast FastAPI application.

Mounts the orders, payments, and sessions routers so the application can be
run with:

    uvicorn app.main:app --reload

from the demo_repo/ directory.
"""

from fastapi import FastAPI, HTTPException, Query
from pydantic import BaseModel
from typing import Optional

from .db import reset_connection
from . import orders as _orders
from . import payments as _payments
from . import sessions as _sessions

app = FastAPI(title="Shopfast", version="0.1.0")

# Ensure the DB schema is created on startup (in-memory by default).
reset_connection()


# ---------------------------------------------------------------------------
# Pydantic models
# ---------------------------------------------------------------------------


class OrderIn(BaseModel):
    customer_id: str
    item: str
    amount: float
    idempotency_key: Optional[str] = None


class ChargeIn(BaseModel):
    customer_id: str
    item: str
    amount: float
    idempotency_key: Optional[str] = None


class SessionIn(BaseModel):
    user_id: str
    ttl_seconds: int = 3600


# ---------------------------------------------------------------------------
# Orders
# ---------------------------------------------------------------------------


@app.post("/orders", status_code=201)
def create_order(body: OrderIn):
    return _orders.create_order(
        customer_id=body.customer_id,
        item=body.item,
        amount=body.amount,
        idempotency_key=body.idempotency_key,
    )


@app.get("/orders")
def list_orders():
    return _orders.list_orders()


@app.get("/orders/customer/{customer_id}")
def orders_by_customer(customer_id: str):
    return _orders.get_orders_by_customer(customer_id)


# ---------------------------------------------------------------------------
# Payments
# ---------------------------------------------------------------------------


@app.post("/charges", status_code=201)
def charge(body: ChargeIn):
    return _payments.charge(
        customer_id=body.customer_id,
        item=body.item,
        amount=body.amount,
        idempotency_key=body.idempotency_key,
    )


# ---------------------------------------------------------------------------
# Sessions
# ---------------------------------------------------------------------------


@app.post("/sessions", status_code=201)
def issue_session(body: SessionIn):
    token = _sessions.issue_token(body.user_id, body.ttl_seconds)
    return {"token": token}


@app.get("/sessions/validate")
def validate_session(token: str = Query(...)):
    user_id = _sessions.validate_token(token)
    if user_id is None:
        raise HTTPException(status_code=401, detail="Invalid or expired token")
    return {"user_id": user_id}


@app.delete("/sessions/{token}")
def expire_session(token: str):
    removed = _sessions.expire_token(token)
    if not removed:
        raise HTTPException(status_code=404, detail="Token not found")
    return {"detail": "session expired"}
