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

## 6. Risk-gated protocol

### If risk is HIGH
1. **Diagnose and classify** — identify root cause, confirm HIGH classification.
2. **Write proposal JSON** with the following fields and post it via
   `scripts/save_escalation.py`:
   - `status`: `"pending_approval"`
   - `risk_level`: `"high"`
   - `auto_applied`: `false`
   - `root_cause`, `root_cause_analysis` — diagnosis narrative
   - `diff` — proposed unified diff (exact text to apply)
   - `code_before` / `code_after` — the specific lines before and after
   - `files_examined` — list of files read during investigation
   - `tests_before` — baseline suite summary
   - **No** `tests_after`, **No** `verdict` (omit or set to `null`)
3. **Run the waiter**:
   ```
   python scripts/wait_for_approval.py TICKET_ID
   ```
   - Exit 0 (approved) → proceed to step 4.
   - Exit 2 (rejected) → stop; do not apply the patch.
   - Exit 1 (timeout)  → stop; report timeout to operator.
4. **Apply the patch** and run the test suite:
   ```
   cd demo_repo && python -m pytest
   ```
5. **Post completed report** via `scripts/save_escalation.py`:
   - `status`: `"completed"`
   - `risk_level`: `"high"`, `auto_applied`: `false`
   - `tests_after`: suite summary string
   - `verdict`: one of `"fix_verified"` / `"fix_failed"` / `"needs_human"`
   - `files_changed`: list of files actually modified by the patch
   - `impact`: one sentence of business impact derived from the ticket symptom

The EscalationReport must include:
- `risk_level`: `"high"`
- `auto_applied`: `false`

### If risk is LOW
Apply the patch immediately; post **one** `completed` report with:
- `status`: `"completed"`
- `risk_level`: `"low"`, `auto_applied`: `true`
- `tests_after`, `verdict`, `files_changed`, `impact` — all required
- A one-sentence justification in `patch_summary` confirming why LOW risk was
  assigned (e.g. *"Risk: LOW — patch only modifies order-lookup logic in
  `app/orders.py`, no payment or auth code touched."*)

## 7. Always run the test suite after patching
After applying a patch (immediately for LOW risk; after approval for HIGH risk),
run:

```
cd demo_repo && python -m pytest
```

Capture the full output.  Record the last summary line as `tests_after`.

## 8. Report a structured verdict
Every completed investigation must post a `completed` EscalationReport.

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
6. **HIGH risk**: write + post `pending_approval` proposal; run
   `scripts/wait_for_approval.py`; wait for exit 0 before applying patch; then
   post `completed` report.
   **LOW risk**: apply patch immediately, post ONE `completed` report with
   `auto_applied=true` and all required completed fields.
7. Run `cd demo_repo && python -m pytest`; capture the after summary as `tests_after`.
8. Set verdict and populate all EscalationReport fields.
9. Post the completed report to the API or via the helper script.
