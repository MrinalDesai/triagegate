# Shopfast — Demo E-Commerce Backend

**Shopfast** is a minimal e-commerce backend built with FastAPI and SQLite.
It is the sample codebase used by the **Triagegate** triage system to
demonstrate automated bug investigation and ticket routing.

---

## Project Layout

```
demo_repo/
├── app/
│   ├── __init__.py
│   ├── db.py          # SQLite helpers (get_connection, init_db)
│   ├── orders.py      # Order CRUD
│   ├── payments.py    # Charge simulation (contains a seeded bug — see KNOWN_BUG.md)
│   ├── sessions.py    # In-memory session store
│   └── main.py        # FastAPI application
├── tests/
│   ├── conftest.py         # Shared fixtures (fresh DB per test)
│   ├── test_db.py          # DB layer tests
│   ├── test_orders.py      # Order module tests
│   ├── test_payments.py    # Payment module tests
│   ├── test_sessions.py    # Session module tests
│   └── test_idempotency.py # Regression test for the seeded bug (FAILS)
├── README.md
└── KNOWN_BUG.md
```

---

## Modules

### `app/db.py`
- `get_connection()` — returns a shared `sqlite3.Connection` (row factory enabled).
- `reset_connection(db_path)` — closes any existing connection and opens a fresh one (used by tests to get an isolated in-memory DB).
- `init_db(conn)` — creates the `orders` and `sessions` tables if they do not exist.

### `app/orders.py`
- `create_order(customer_id, item, amount, idempotency_key=None) -> dict`
- `list_orders() -> list[dict]` — all orders, newest first.
- `get_orders_by_customer(customer_id) -> list[dict]`

### `app/payments.py`
- `charge(customer_id, item, amount, idempotency_key=None) -> dict` — simulates charging a customer and records the resulting order.
  > ⚠️ **Contains a seeded bug** — see [KNOWN_BUG.md](KNOWN_BUG.md).
- `get_charge_by_idempotency_key(key) -> dict | None`

### `app/sessions.py`
In-memory session store backed by a plain Python dict.
- `issue_token(user_id, ttl_seconds=3600) -> str`
- `validate_token(token) -> str | None`
- `expire_token(token) -> bool`

### `app/main.py`
FastAPI application exposing:

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/orders` | Create order |
| `GET`  | `/orders` | List all orders |
| `GET`  | `/orders/customer/{id}` | Orders by customer |
| `POST` | `/charges` | Charge a customer |
| `POST` | `/sessions` | Issue session token |
| `GET`  | `/sessions/validate?token=…` | Validate token |
| `DELETE` | `/sessions/{token}` | Expire token |

---

## Running the App

```bash
cd demo_repo
pip install fastapi uvicorn
uvicorn app.main:app --reload
```

Interactive docs are available at <http://localhost:8000/docs>.

---

## Running Tests

```bash
cd demo_repo
pip install pytest httpx
python -m pytest
```

Expected result:
- **All tests pass** except `tests/test_idempotency.py::test_retry_charge_with_same_idempotency_key_creates_only_one_order` which **fails** intentionally.

To run only the passing suite:

```bash
python -m pytest --ignore=tests/test_idempotency.py
```

---

## Dependencies

| Package | Purpose |
|---------|---------|
| `fastapi` | HTTP framework |
| `uvicorn` | ASGI server |
| `pytest` | Test runner |
| `sqlite3` | Database (stdlib) |

No external database is required — Shopfast defaults to an in-memory SQLite database.
