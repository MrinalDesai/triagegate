import json

rca = """The idempotency column existed, but was never consulted on write. The orders table carries an idempotency_key TEXT column (db.py:48), and charge() faithfully accepted and forwarded a caller-supplied key all the way to create_order(). However, create_order() in orders.py is a pure insert-and-return function — it executes INSERT INTO orders unconditionally on every call. Neither function ever checked whether a row with that key already existed before inserting. The key was written to the database as data, but never used as a guard.

How the double-billing manifests: when a client retries a payment (network timeout, double-click, frontend retry logic), it supplies the same idempotency_key as the original attempt. The payment provider correctly deduplicates the external charge — so only one real monetary transaction occurs. But internally, charge() fires create_order() a second time, producing a second INSERT, a second row with a new id, and therefore a second entry in the customer's purchase history. The provider dashboard shows one charge; the app's own records show two — matching the reported symptom exactly.

Notably, payments.py already contained get_charge_by_idempotency_key() — present as infrastructure but never called from charge(). The fix is simply to call it."""

code_before = """def charge(
    customer_id: str,
    item: str,
    amount: float,
    idempotency_key: Optional[str] = None,
) -> dict:
    return create_order(
        customer_id=customer_id,
        item=item,
        amount=amount,
        idempotency_key=idempotency_key,
    )"""

code_after = """def charge(
    customer_id: str,
    item: str,
    amount: float,
    idempotency_key: Optional[str] = None,
) -> dict:
    if idempotency_key is not None:
        existing = get_charge_by_idempotency_key(idempotency_key)
        if existing is not None:
            return existing
    return create_order(
        customer_id=customer_id,
        item=item,
        amount=amount,
        idempotency_key=idempotency_key,
    )"""

report = {
    "ticket_id": "A-0007",
    "root_cause": "idempotency_key stored but never checked before insert; retries create duplicate order rows",
    "root_cause_analysis": rca,
    "files_examined": ["app/payments.py", "app/orders.py", "app/db.py"],
    "patch_summary": "Add pre-insert idempotency check in charge(): return the existing order when a matching key is found. Four lines.",
    "diff": "--- a/app/payments.py\n+++ b/app/payments.py\n@@ def charge\n+    if idempotency_key is not None:\n+        existing = get_charge_by_idempotency_key(idempotency_key)\n+        if existing is not None:\n+            return existing\n     return create_order(...)",
    "code_before": code_before,
    "code_after": code_after,
    "tests_before": "32 passed, 1 failed",
    "tests_after": "33 passed",
    "verdict": "fix_verified",
    "risk_level": "high",
    "auto_applied": False,
    "status": "pending_approval",
}

with open("real_report.json", "w") as f:
    json.dump(report, f, indent=2)
print("wrote real_report.json")