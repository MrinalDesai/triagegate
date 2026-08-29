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

## 5. Always run the test suite after patching
After applying a patch, run:

```
cd demo_repo && python -m pytest
```

Capture the full output.  Record the last summary line (e.g. `3 passed, 1
failed`) as `tests_after` in the EscalationReport.

## 6. Report a structured verdict
Every investigation must end with an `EscalationReport` stored via the API
endpoint `POST /api/escalations/{ticket_id}/report` or the helper script
`scripts/save_escalation.py`.

The `verdict` field must be one of:
- `fix_verified` — patch applied and all tests pass
- `fix_failed`   — patch applied but tests still fail
- `needs_human`  — root cause identified but fix requires human judgement or
  touches multiple systems

## 7. Classify fix risk before patching
After identifying the root cause (step 4 below) but **before applying any
patch**, classify the risk level of the proposed fix:

- **HIGH** if the patch touches any of the following high-sensitivity paths in
  `demo_repo`:
  - `app/payments.py` — payment processing code
  - `app/sessions.py` — authentication / session management code
  - Destructive database operations in `app/db.py` (e.g. `DELETE`, `DROP`,
    `TRUNCATE`, or any function whose name contains `delete`, `purge`, `wipe`,
    or `destroy`)
- **LOW** for all other changes: pure logic fixes, formatting, read-only paths,
  e.g. `app/orders.py` lookup functions.

The EscalationReport **must** include:
- `risk_level`: `"high"` or `"low"`
- A one-sentence justification in `patch_summary` stating why that level was
  assigned (e.g. *"Risk: LOW — patch only modifies order-lookup logic in
  app/orders.py, no payment or auth code touched."*)
- `auto_applied`: `true` only when `risk_level == "low"` (set `false` for HIGH
  risk; the model will reject `auto_applied=true` with HIGH risk).

## 8. Structured workflow
1. Run `cd demo_repo && python -m pytest`; record the baseline as `tests_before`.
2. Read the ticket title and description.
3. Explore demo_repo/ — start with `README.md` then relevant source files.
4. Identify the root-cause file and line.
5. Classify fix risk (Rule 7) and record `risk_level` + justification.
6. Apply a minimal patch (edit only production code, never tests).
7. Run `cd demo_repo && python -m pytest`; capture the after summary as `tests_after`.
8. Set verdict and populate all EscalationReport fields (including `risk_level`
   and `auto_applied`).
9. Post the report to the API or via the helper script.
