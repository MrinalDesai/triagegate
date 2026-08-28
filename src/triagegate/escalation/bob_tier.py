"""Bob escalation tier — EscalationReport model and EscalationStore."""
from __future__ import annotations

import json
from pathlib import Path
from typing import List, Literal, Optional

from pydantic import BaseModel, field_validator

# ---------------------------------------------------------------------------
# Verdict type
# ---------------------------------------------------------------------------

Verdict = Literal["fix_verified", "fix_failed", "needs_human"]

# ---------------------------------------------------------------------------
# Model
# ---------------------------------------------------------------------------

class EscalationReport(BaseModel):
    """Full report produced by the Bug Investigator mode for one ticket."""

    ticket_id: str
    root_cause: str
    files_examined: List[str]
    patch_summary: str
    diff: str
    tests_before: str  # e.g. "32 passed 1 failed"
    tests_after: str   # e.g. "33 passed"
    verdict: Verdict

    @field_validator("verdict")
    @classmethod
    def _valid_verdict(cls, v: str) -> str:
        allowed = {"fix_verified", "fix_failed", "needs_human"}
        if v not in allowed:
            raise ValueError(f"verdict must be one of {allowed!r}, got {v!r}")
        return v


# ---------------------------------------------------------------------------
# Store
# ---------------------------------------------------------------------------

_DEFAULT_STORE_DIR = Path("data/escalations")


class EscalationStore:
    """Persist and retrieve EscalationReport objects as JSON files."""

    def __init__(self, store_dir: Path | str = _DEFAULT_STORE_DIR) -> None:
        self.store_dir = Path(store_dir)
        self.store_dir.mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _path(self, ticket_id: str) -> Path:
        # Sanitise ticket_id so it is safe as a filename component.
        safe = ticket_id.replace("/", "_").replace("\\", "_")
        return self.store_dir / f"{safe}.json"

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def save(self, report: EscalationReport) -> None:
        """Write *report* to disk, overwriting any existing entry."""
        self._path(report.ticket_id).write_text(
            report.model_dump_json(indent=2), encoding="utf-8"
        )

    def load(self, ticket_id: str) -> Optional[EscalationReport]:
        """Return the report for *ticket_id*, or ``None`` if not found."""
        p = self._path(ticket_id)
        if not p.exists():
            return None
        return EscalationReport.model_validate_json(p.read_text(encoding="utf-8"))

    def exists(self, ticket_id: str) -> bool:
        return self._path(ticket_id).exists()
