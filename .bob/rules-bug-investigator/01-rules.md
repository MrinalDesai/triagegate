# Bug Investigator — Operational Rules

## 1. Run the full test suite first — before reading any code
The **very first action** of every investigation must be to run the test suite
and record the baseline result:

```
cd demo_repo && python -m pytest
```

Capture the full output.  Record the last summary line (e.g. `3 passed, 1
failed`) as `tests_before` in the EscalationReport.  Do **not** read source
files or form any hypothesis until this baseline is in hand.

## 2. Read before writing
Never modify any file without first reading its full contents.  Understand the
existing code before proposing any change.

## 3. Never modify tests
Files that live under a `tests/` directory (at any depth) or whose name starts
with `test_` are read-only.  Do not edit, delete, or rename them.

## 4. Keep patches minimal — single concern
Each patch must address exactly one root cause.  Do not refactor, reformat, or
improve unrelated code.  If multiple bugs exist, fix only the one described in
the ticket and note the rest in the verdict.

## 5. Classify fix risk before touching any file
After identifying the root cause but **before modifying any file**, classify
the risk level of the proposed fix:

- **HIGH** if the patch touches any of the following high-sensitivity paths in
  `demo_repo`:
  - `app/payments.py` — payment processing code
  - `app/sessions.py` — authentication / session management code
  - Destructive database operations in `app/db.py` (e.g. `DELETE`, `DROP`,
    `TRUNCATE`, or any function whose name contains `delete`, `purge`, `wipe`,
    or `destroy`)
- **LOW** for all other changes: pure logic fixes, formatting, read-only paths,
  e.g. `app/orders.py` lookup functions.

## 6. Risk-gated stop: HIGH risk requires human approval before any edit

### If risk is HIGH
The investigator **MUST NOT** modify any file yet.  Instead it must:

1. Present the proposed fix as a **unified diff** (the exact text that would be
   applied, formatted as a standard `diff -u` patch).
2. State the risk justification: name the sensitive file(s) the patch touches
   and why that qualifies as HIGH risk.
3. **Explicitly ask the human operator for approval** to apply the patch, e.g.:
   > "This patch modifies `app/payments.py` (HIGH risk — payment processing
   > code). Please confirm: should I apply this patch and run the test suite?"
4. Wait for the human operator to respond **in this session** with explicit
   approval (e.g. "yes", "apply", "approved").
5. Only after receiving that approval: apply the patch and proceed to step 8.

The EscalationReport must include:
- `risk_level`: `"high"`
- `auto_applied`: `false`
- A one-sentence justification in `patch_summary` stating why HIGH risk was
  assigned.

### If risk is LOW
The investigator may apply the patch immediately without stopping.  Note in the
report that `auto_applied` is eligible.

The EscalationReport must include:
- `risk_level`: `"low"`
- `auto_applied`: `true`
- A one-sentence justification in `patch_summary` confirming why LOW risk was
  assigned (e.g. *"Risk: LOW — patch only modifies order-lookup logic in
  app/orders.py, no payment or auth code touched."*)

## 7. Always run the test suite after patching
After applying a patch (immediately for LOW risk; after human approval for HIGH
risk), run:

```
cd demo_repo && python -m pytest
```

Capture the full output.  Record the last summary line (e.g. `3 passed, 1
failed`) as `tests_after` in the EscalationReport.

## 8. Report a structured verdict
Every investigation must end with an `EscalationReport` stored via the API
endpoint `POST /api/escalations/{ticket_id}/report` or the helper script
`scripts/save_escalation.py`.

The `verdict` field must be one of:
- `fix_verified` — patch applied and all tests pass
- `fix_failed`   — patch applied but tests still fail
- `needs_human`  — root cause identified but fix requires human judgement or
  touches multiple systems

## 9. Structured workflow
1. Run `cd demo_repo && python -m pytest`; record the baseline as `tests_before`.
2. Read the ticket title and description.
3. Explore demo_repo/ — start with `README.md` then relevant source files.
4. Identify the root-cause file and line.
5. Classify fix risk (Rule 5).
6. **HIGH risk**: present unified diff + justification + ask for human approval;
   wait for approval before proceeding.
   **LOW risk**: apply patch immediately.
7. Run `cd demo_repo && python -m pytest`; capture the after summary as `tests_after`.
8. Set verdict and populate all EscalationReport fields (`risk_level`,
   `auto_applied`, `patch_summary` justification).
9. Post the report to the API or via the helper script.
