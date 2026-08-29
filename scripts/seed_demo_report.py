"""
seed_demo_report.py — Load a previously recorded, real Bug Investigator result
into the escalation store so the Console can render the full escalation view
without a live Bob call.

This does NOT fabricate an investigation. It replays the actual result produced
by IBM Bob during a live Bug Investigator run on ticket A-0007 (the seeded
idempotency bug in demo_repo/app/payments.py): the real root-cause analysis,
the real before/after code, and the real 32->33 test transition captured from
that session.

Usage:
    python scripts/seed_demo_report.py            # write the completed report
    python scripts/seed_demo_report.py --clear    # remove it again

The Console's escalation panel will then show the recorded RCA, the red/green
code fix, the verdict badge, and the risk badge. Label it in any demo as a
replay of a recorded live investigation.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

# Make src importable when run from repo root
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from triagegate.escalation.bob_tier import EscalationReport, EscalationStore

TICKET_ID = "A-0007"

ROOT_CAUSE = (
    "idempotency_key stored but never checked before insert; retries create "
    "duplicate order rows"
)

RCA = (
    "The idempotency column existed, but was never consulted on write. The "
    "orders table carries an idempotency_key TEXT column (db.py:48), and "
    "charge() faithfully accepted and forwarded a caller-supplied key all the "
    "way to create_order(). However, create_order() in orders.py is a pure "
    "insert-and-return function \u2014 it executes INSERT INTO orders "
    "unconditionally on every call. Neither function ever checked whether a row "
    "with that key already existed before inserting. The key was written to the "
    "database as data, but never used as a guard.\n\n"
    "How the double-billing manifests: when a client retries a payment (network "
    "timeout, double-click, frontend retry logic), it supplies the same "
    "idempotency_key as the original attempt. The payment provider correctly "
    "deduplicates the external charge \u2014 so only one real monetary "
    "transaction occurs. But internally, charge() fires create_order() a second "
    "time, producing a second INSERT, a second row with a new id, and therefore "
    "a second entry in the customer's purchase history. The provider dashboard "
    "shows one charge; the app's own records show two \u2014 matching the "
    "reported symptom exactly.\n\n"
    "Notably, payments.py already contained get_charge_by_idempotency_key() "
    "\u2014 present as infrastructure but never called from charge(). The fix "
    "is simply to call it."
)

CODE_BEFORE = (
    "def charge(\n"
    "    customer_id: str,\n"
    "    item: str,\n"
    "    amount: float,\n"
    "    idempotency_key: Optional[str] = None,\n"
    ") -> dict:\n"
    "    return create_order(\n"
    "        customer_id=customer_id,\n"
    "        item=item,\n"
    "        amount=amount,\n"
    "        idempotency_key=idempotency_key,\n"
    "    )"
)

CODE_AFTER = (
    "def charge(\n"
    "    customer_id: str,\n"
    "    item: str,\n"
    "    amount: float,\n"
    "    idempotency_key: Optional[str] = None,\n"
    ") -> dict:\n"
    "    if idempotency_key is not None:\n"
    "        existing = get_charge_by_idempotency_key(idempotency_key)\n"
    "        if existing is not None:\n"
    "            return existing\n"
    "    return create_order(\n"
    "        customer_id=customer_id,\n"
    "        item=item,\n"
    "        amount=amount,\n"
    "        idempotency_key=idempotency_key,\n"
    "    )"
)

DIFF = (
    "--- a/app/payments.py\n"
    "+++ b/app/payments.py\n"
    "@@ def charge\n"
    "+    if idempotency_key is not None:\n"
    "+        existing = get_charge_by_idempotency_key(idempotency_key)\n"
    "+        if existing is not None:\n"
    "+            return existing\n"
    "     return create_order(...)"
)


def build_report() -> EscalationReport:
    """Construct the completed report from the recorded live-run data.

    Validated against the real EscalationReport model, so it cannot contain a
    state the schema would reject.
    """
    return EscalationReport(
        ticket_id=TICKET_ID,
        root_cause=ROOT_CAUSE,
        root_cause_analysis=RCA,
        files_examined=["app/payments.py", "app/orders.py", "app/db.py"],
        patch_summary=(
            "Add pre-insert idempotency check in charge(): return the existing "
            "order when a matching key is found. Four lines."
        ),
        diff=DIFF,
        code_before=CODE_BEFORE,
        code_after=CODE_AFTER,
        tests_before="32 passed, 1 failed",
        tests_after="33 passed",
        verdict="fix_verified",
        risk_level="high",
        auto_applied=False,
        status="completed",
        files_changed=["app/payments.py"],
        impact="Customers were billed once but recorded twice; retries created duplicate orders.",
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--clear",
        action="store_true",
        help="Remove the seeded report instead of writing it.",
    )
    parser.add_argument(
        "--store-dir",
        default="data/escalations",
        help="Escalation store directory (default: data/escalations).",
    )
    args = parser.parse_args()

    store = EscalationStore(store_dir=args.store_dir)
    path = store._path(TICKET_ID)  # noqa: SLF001 - intentional for the demo tool

    if args.clear:
        if path.exists():
            path.unlink()
            print(f"Removed seeded report: {path}")
        else:
            print(f"Nothing to clear (no report at {path}).")
        return 0

    report = build_report()  # validates against the real model
    store.save(report)
    print(f"Seeded recorded investigation for {TICKET_ID} -> {path}")
    print("Submit ticket A-0007 in the Console; the escalation panel will render")
    print("the recorded RCA, red/green code fix, and FIX VERIFIED / HIGH RISK badges.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
