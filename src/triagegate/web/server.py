from __future__ import annotations

from collections import defaultdict
from typing import Dict

from fastapi import FastAPI, HTTPException

from triagegate.escalation.bob_tier import EscalationReport, EscalationStore
from triagegate.models.ticket import LadderResult, RoutingDecision, Ticket
from triagegate.pipeline.resolver import Resolver

app = FastAPI(title="TriageGate")

# Lazy-initialised singleton resolver (created on first request so tests that
# only hit /health don't pay the startup cost).
_resolver: Resolver | None = None

# Session-level counters: resolved-by rung → ticket count
_rung_counts: Dict[str, int] = defaultdict(int)

# Escalation store (single shared instance, default data/escalations/).
_escalation_store = EscalationStore()


def _get_resolver() -> Resolver:
    global _resolver
    if _resolver is None:
        _resolver = Resolver()
    return _resolver


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}


@app.post("/api/route", response_model=LadderResult)
def route_ticket(ticket: Ticket) -> LadderResult:
    result = _get_resolver().resolve(ticket)
    _rung_counts[result.resolved_by] += 1
    return result


@app.get("/api/stats")
def stats() -> Dict[str, int]:
    """Return counts of tickets resolved per rung this session."""
    return dict(_rung_counts)


# ---------------------------------------------------------------------------
# Escalation endpoints
# ---------------------------------------------------------------------------

@app.post("/api/escalations/{ticket_id}/report", response_model=EscalationReport, status_code=201)
def save_escalation_report(ticket_id: str, report: EscalationReport) -> EscalationReport:
    """Store an EscalationReport produced by the Bug Investigator mode."""
    if report.ticket_id != ticket_id:
        raise HTTPException(
            status_code=422,
            detail=f"ticket_id in URL ({ticket_id!r}) does not match body ({report.ticket_id!r})",
        )
    _escalation_store.save(report)
    return report


@app.get("/api/escalations/{ticket_id}", response_model=EscalationReport)
def get_escalation_report(ticket_id: str) -> EscalationReport:
    """Return the escalation report for *ticket_id*, or 404 if not found."""
    report = _escalation_store.load(ticket_id)
    if report is None:
        raise HTTPException(status_code=404, detail=f"No escalation report for ticket {ticket_id!r}")
    return report
