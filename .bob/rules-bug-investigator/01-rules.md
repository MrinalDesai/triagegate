# Bug Investigator — Operational Rules

## 1. Read before writing
Never modify any file without first reading its full contents.  Understand the
existing code before proposing any change.

## 2. Never modify tests
Files that live under a `tests/` directory (at any depth) or whose name starts
with `test_` are read-only.  Do not edit, delete, or rename them.

## 3. Keep patches minimal — single concern
Each patch must address exactly one root cause.  Do not refactor, reformat, or
improve unrelated code.  If multiple bugs exist, fix only the one described in
the ticket and note the rest in the verdict.

## 4. Always run the test suite after patching
After applying a patch, run:

```
cd demo_repo && python -m pytest
```

Capture the full output.  Record the last summary line (e.g. `3 passed, 1
failed`) as `tests_after` in the EscalationReport.

## 5. Report a structured verdict
Every investigation must end with an `EscalationReport` stored via the API
endpoint `POST /api/escalations/{ticket_id}/report` or the helper script
`scripts/save_escalation.py`.

The `verdict` field must be one of:
- `fix_verified` — patch applied and all tests pass
- `fix_failed`   — patch applied but tests still fail
- `needs_human`  — root cause identified but fix requires human judgement or
  touches multiple systems

## 6. Structured workflow
1. Read the ticket title and description.
2. Explore demo_repo/ — start with `README.md` then relevant source files.
3. Identify the root-cause file and line.
4. Apply a minimal patch (edit only production code, never tests).
5. Run `cd demo_repo && python -m pytest`; capture before/after summaries.
6. Set verdict and populate all EscalationReport fields.
7. Post the report to the API or via the helper script.
