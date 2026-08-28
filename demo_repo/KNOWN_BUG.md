# Known Bug — Idempotency Key Not Enforced in `payments.charge()`

> **Transparency note for judges:** this bug was seeded deliberately to give
> the Triagegate triage system a real defect to investigate and route.

---

## Summary

| Field | Value |
|-------|-------|
| **Module** | `app/payments.py` |
| **Function** | `charge()` |
| **Symptom** | Retrying a charge with the same `idempotency_key` creates a duplicate order row |
| **Severity** | High — customers can be double-charged |
| **Regression test** | `tests/test_idempotency.py::test_retry_charge_with_same_idempotency_key_creates_only_one_order` |
| **Test status** | ❌ FAILS (by design, until the bug is fixed) |

---

## Description

`charge()` accepts an optional `idempotency_key` parameter.  The intent is that
callers (e.g., a payment gateway client retrying after a network timeout) can
pass the same key on every attempt, and the function should recognise the key
and return the original order rather than inserting a new one.

**The check is missing.**  The current implementation passes the key straight
through to `create_order()` without first querying the database for an
existing order with that key.  Every call therefore inserts a new row,
regardless of whether an identical key was seen before.

### Buggy code (lines 42–48 of `app/payments.py`)

```python
# BUG: should check for an existing order with this idempotency_key first.
return create_order(
    customer_id=customer_id,
    item=item,
    amount=amount,
    idempotency_key=idempotency_key,
)
```

### Correct implementation

```python
if idempotency_key is not None:
    existing = get_charge_by_idempotency_key(idempotency_key)
    if existing:
        return existing          # ← return the original order, do NOT insert

return create_order(
    customer_id=customer_id,
    item=item,
    amount=amount,
    idempotency_key=idempotency_key,
)
```

---

## Reproducing the Bug

```python
from app.db import reset_connection
from app.payments import charge
from app.orders import list_orders

reset_connection(":memory:")

charge("cust_1", "Widget", 9.99, idempotency_key="retry-001")
charge("cust_1", "Widget", 9.99, idempotency_key="retry-001")  # retry

print(len(list_orders()))  # prints 2 — should print 1
```

---

## Regression Test

`tests/test_idempotency.py` contains a single test
(`test_retry_charge_with_same_idempotency_key_creates_only_one_order`) that:

1. Calls `charge()` twice with the same `idempotency_key`.
2. Asserts both calls returned the same order id.
3. Asserts only one order exists in the database.

**This test currently FAILS.**  All other tests in `demo_repo/tests/` pass.

```
FAILED tests/test_idempotency.py::test_retry_charge_with_same_idempotency_key_creates_only_one_order
```

Fix the bug (see correct implementation above) and the test will go green.
