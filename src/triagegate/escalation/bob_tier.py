"""Bob escalation tier — EscalationReport model and EscalationStore."""
from __future__ import annotations

import json
from pathlib import Path
from typing import List, Literal, Optional

from pydantic import BaseModel, Field, field_validator, model_validator

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
    # Optional until completed
    tests_after: Optional[str] = None
    verdict: Optional[Verdict] = None
    risk_level: Literal["high", "low"] = "low"
    auto_applied: bool = False
    # Status is REQUIRED — no default
    status: Literal["pending_approval", "approved", "rejected", "completed"]
    root_cause_analysis: str = ""
    code_before: str = ""
    code_after: str = ""
    # New fields
    files_changed: List[str] = Field(default_factory=list)
    impact: Optional[str] = None

    # ------------------------------------------------------------------
    # Field-level validators
    # ------------------------------------------------------------------

    @field_validator("verdict")
    @classmethod
    def _valid_verdict(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return v
        allowed = {"fix_verified", "fix_failed", "needs_human"}
        if v not in allowed:
            raise ValueError(f"verdict must be one of {allowed!r}, got {v!r}")
        return v

    # ------------------------------------------------------------------
    # Cross-field validators per status
    # ------------------------------------------------------------------

    @model_validator(mode="after")
    def _enforce_state_machine(self) -> "EscalationReport":
        status = self.status
        risk = self.risk_level
        auto = self.auto_applied
        ta = self.tests_after
        v = self.verdict

        if status in ("pending_approval", "approved", "rejected"):
            # All three intermediate states require high risk
            if risk != "high":
                raise ValueError(
                    f"status={status!r} requires risk_level='high', got {risk!r}"
                )
            if ta is not None:
                raise ValueError(
                    f"status={status!r} must not have tests_after set"
                )
            if v is not None:
                raise ValueError(
                    f"status={status!r} must not have verdict set"
                )
            if auto:
                raise ValueError(
                    f"status={status!r} requires auto_applied=False"
                )

        elif status == "completed":
            # completed requires tests_after and verdict
            if not ta:
                raise ValueError(
                    "status='completed' requires a non-empty tests_after"
                )
            if v is None:
                raise ValueError(
                    "status='completed' requires verdict to be set"
                )
            # risk-specific auto_applied rules
            if risk == "high" and auto:
                raise ValueError(
                    "status='completed' with risk_level='high' requires auto_applied=False"
                )
            if risk == "low" and not auto:
                raise ValueError(
                    "status='completed' with risk_level='low' requires auto_applied=True"
                )
            # fix_verified additionally requires files_changed and impact
            if v == "fix_verified":
                if not self.files_changed:
                    raise ValueError(
                        "status='completed' with verdict='fix_verified' requires non-empty files_changed"
                    )
                if not self.impact:
                    raise ValueError(
                        "status='completed' with verdict='fix_verified' requires impact to be set"
                    )

        return self


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
