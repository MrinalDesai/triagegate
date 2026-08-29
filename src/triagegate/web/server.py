from __future__ import annotations

import csv
import os
from collections import defaultdict
from pathlib import Path
from typing import Any, Dict, Optional, Set

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

try:
    from dotenv import load_dotenv  # type: ignore
    load_dotenv()
except ImportError:
    pass

from triagegate.escalation.bob_tier import EscalationReport, EscalationStore
from triagegate.escalation.dispatch import (
    dispatch_investigation,
    get_dispatch_status,
)
from triagegate.llm.client import GraniteClient
from triagegate.models.ticket import LadderResult, RoutingDecision, Ticket
from triagegate.pipeline.resolver import Resolver

_DATA_DIR = Path(__file__).resolve().parents[3] / "data"
_INCIDENT_HISTORY_CSV = _DATA_DIR / "incident_history.csv"

app = FastAPI(title="TriageGate")

# Resolve the web/ directory relative to the project root (two levels above
# this file: src/triagegate/web/server.py → project root).
_WEB_DIR = Path(__file__).resolve().parents[3] / "web"

# Mount the web/ directory under /web so individual files are accessible.
# Explicit top-level routes below allow the HTML pages to use simple relative
# paths (href="style.css") without a path prefix.
app.mount("/web", StaticFiles(directory=_WEB_DIR), name="web")

# Lazy-initialised singleton resolver (created on first request so tests that
# only hit /health don't pay the startup cost).
_resolver: Resolver | None = None

# Session-level counters: resolved-by rung → ticket count
_rung_counts: Dict[str, int] = defaultdict(int)

# Escalation store (single shared instance, default data/escalations/).
_escalation_store = EscalationStore()

# In-memory set of ticket_ids that have already been written to incident history.
# Prevents duplicate rows on concurrent or replayed requests.
_incident_history_written: Set[str] = set()

# In-memory set of ticket_ids whose routing result was "escalated".
# Populated by /api/route; used by /api/escalations/{id}/dispatch to gate
# dispatch requests without trusting any client-supplied field.
_escalated_ticket_ids: Set[str] = set()


def _make_llm_client():
    """Return a GraniteClient when all three WatsonX env vars are present, else None."""
    if (
        os.environ.get("WATSONX_API_KEY")
        and os.environ.get("WATSONX_PROJECT_ID")
        and os.environ.get("WATSONX_URL")
    ):
        return GraniteClient()
    return None


def _get_resolver() -> Resolver:
    global _resolver
    if _resolver is None:
        _resolver = Resolver(llm_client=_make_llm_client())
    return _resolver


@app.get("/index.html")
def index_html_redirect() -> RedirectResponse:
    """Redirect /index.html → / (permanent)."""
    return RedirectResponse(url="/", status_code=308)


@app.get("/")
def root() -> FileResponse:
    """Serve the Console tab (web/index.html)."""
    return FileResponse(_WEB_DIR / "index.html", media_type="text/html")


@app.get("/stats.html")
def stats_page() -> FileResponse:
    return FileResponse(_WEB_DIR / "stats.html", media_type="text/html")


@app.get("/about.html")
def about_page() -> FileResponse:
    return FileResponse(_WEB_DIR / "about.html", media_type="text/html")


@app.get("/style.css")
def style_css() -> FileResponse:
    return FileResponse(_WEB_DIR / "style.css", media_type="text/css")


@app.get("/app.js")
def app_js() -> FileResponse:
    return FileResponse(_WEB_DIR / "app.js", media_type="application/javascript")


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}


@app.get("/api/config")
def config() -> dict:
    """Return runtime configuration flags for the frontend."""
    granite_enabled = bool(
        os.environ.get("WATSONX_API_KEY")
        and os.environ.get("WATSONX_PROJECT_ID")
        and os.environ.get("WATSONX_URL")
    )
    return {"granite_enabled": granite_enabled}


@app.post("/api/route", response_model=LadderResult)
def route_ticket(ticket: Ticket) -> LadderResult:
    result = _get_resolver().resolve(ticket)
    _rung_counts[result.resolved_by] += 1
    if result.domain == "escalated":
        _escalated_ticket_ids.add(ticket.id)
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
    """Store an EscalationReport produced by the Bug Investigator mode.

    Enforces the state-machine transition matrix:
      [no report] → pending_approval  (HIGH risk, status must be pending_approval)
      [no report] → completed         (LOW risk, auto_applied=True)
      approved    → completed         (HIGH risk completing after approval)
      Everything else → 409
    Client-submitted approved/rejected are rejected (those come only via their
    dedicated endpoints).
    """
    if report.ticket_id != ticket_id:
        raise HTTPException(
            status_code=422,
            detail=f"ticket_id in URL ({ticket_id!r}) does not match body ({report.ticket_id!r})",
        )

    # Block client-submitted approved/rejected — dedicated endpoints only
    if report.status in ("approved", "rejected"):
        raise HTTPException(
            status_code=409,
            detail=f"status={report.status!r} can only be set via /approve or /reject endpoints",
        )

    existing = _escalation_store.load(ticket_id)

    if existing is None:
        # Fresh submission: only pending_approval (high) or completed (low) allowed
        if report.status == "pending_approval":
            # Risk must be high (model validator already enforces this, but belt+braces)
            if report.risk_level != "high":
                raise HTTPException(
                    status_code=409,
                    detail="pending_approval status requires risk_level='high'",
                )
        elif report.status == "completed":
            if report.risk_level != "low" or not report.auto_applied:
                raise HTTPException(
                    status_code=409,
                    detail="Fresh completed report requires risk_level='low' and auto_applied=True",
                )
        else:
            raise HTTPException(
                status_code=409,
                detail=f"Cannot create a fresh report with status={report.status!r}",
            )
    else:
        # Existing report: the only allowed transition is approved → completed (high risk)
        if existing.status == "completed":
            raise HTTPException(
                status_code=409,
                detail=f"Ticket {ticket_id!r} is already completed; no further transitions allowed",
            )
        if existing.status == "rejected":
            raise HTTPException(
                status_code=409,
                detail=f"Ticket {ticket_id!r} was rejected; no further transitions allowed",
            )
        if existing.status == "approved" and report.status == "completed":
            if report.risk_level != "high":
                raise HTTPException(
                    status_code=409,
                    detail="Completing an approved HIGH-risk ticket requires risk_level='high'",
                )
            # Valid transition — fall through to save
        else:
            raise HTTPException(
                status_code=409,
                detail=(
                    f"Invalid transition: stored status={existing.status!r} → "
                    f"requested status={report.status!r}"
                ),
            )

    _escalation_store.save(report)

    # Append incident history only for completed fix_verified, exactly once per ticket
    if report.status == "completed" and report.verdict == "fix_verified":
        _append_incident_history(report)

    return report


@app.get("/api/escalations/{ticket_id}", response_model=EscalationReport)
def get_escalation_report(ticket_id: str) -> EscalationReport:
    """Return the escalation report for *ticket_id*, or 404 if not found."""
    report = _escalation_store.load(ticket_id)
    if report is None:
        raise HTTPException(status_code=404, detail=f"No escalation report for ticket {ticket_id!r}")
    return report


@app.post("/api/escalations/{ticket_id}/approve", response_model=EscalationReport)
def approve_escalation(ticket_id: str) -> EscalationReport:
    """Approve a pending_approval escalation: pending_approval → approved.

    Only mutates the status field.  Does NOT write incident history.
    """
    report = _escalation_store.load(ticket_id)
    if report is None:
        raise HTTPException(status_code=404, detail=f"No escalation report for ticket {ticket_id!r}")
    if report.status != "pending_approval":
        raise HTTPException(
            status_code=409,
            detail=f"Cannot approve: report status is {report.status!r}, expected 'pending_approval'",
        )
    report = report.model_copy(update={"status": "approved"})
    _escalation_store.save(report)
    return report


@app.post("/api/escalations/{ticket_id}/reject", response_model=EscalationReport)
def reject_escalation(ticket_id: str) -> EscalationReport:
    """Reject a pending_approval escalation: pending_approval → rejected (TERMINAL)."""
    report = _escalation_store.load(ticket_id)
    if report is None:
        raise HTTPException(status_code=404, detail=f"No escalation report for ticket {ticket_id!r}")
    if report.status != "pending_approval":
        raise HTTPException(
            status_code=409,
            detail=f"Cannot reject: report status is {report.status!r}, expected 'pending_approval'",
        )
    report = report.model_copy(update={"status": "rejected"})
    _escalation_store.save(report)
    return report


# ---------------------------------------------------------------------------
# Dispatch endpoints
# ---------------------------------------------------------------------------

class DispatchRequest(BaseModel):
    title: str
    description: str


@app.post("/api/escalations/{ticket_id}/dispatch", status_code=202)
def dispatch_escalation(ticket_id: str, body: DispatchRequest) -> Dict[str, Any]:
    """Start a headless Bob investigation for an escalated ticket.

    Server-side escalation gate: the ticket_id must be in ``_escalated_ticket_ids``
    (populated by /api/route when domain == "escalated") OR have an existing
    escalation report on disk.  We NEVER trust a client-supplied "escalated"
    field — the check is performed entirely from server state.

    Returns:
        202 Accepted  — dispatch started (or reused).
        409 Conflict  — ticket was not escalated.
        503 Service Unavailable — BOB_API_KEY missing or CLI unavailable.
    """
    from triagegate.escalation.dispatch import _get_dispatch, _is_active, _public_record

    # ── Idempotency check ──────────────────────────────────────────────────
    existing = _get_dispatch(ticket_id)
    if existing is not None and _is_active(existing):
        record = _public_record(existing)
        record["reused"] = True
        return record

    # ── Server-side escalation gate ────────────────────────────────────────
    # A ticket is considered "escalated" when:
    #   (a) /api/route saw it and domain == "escalated"  (_escalated_ticket_ids), OR
    #   (b) an escalation report already exists on disk (i.e. Bob already filed one).
    # We never look at client-supplied body fields for this check.
    has_report = _escalation_store.load(ticket_id) is not None
    was_routed_as_escalated = ticket_id in _escalated_ticket_ids
    if not was_routed_as_escalated and not has_report:
        raise HTTPException(
            status_code=409,
            detail=(
                f"Ticket {ticket_id!r} was not escalated. "
                "Route the ticket via POST /api/route first and confirm the result is 'escalated'."
            ),
        )

    try:
        record = dispatch_investigation(ticket_id, body.title, body.description)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    except RuntimeError as exc:
        msg = str(exc)
        # Sanitize: never expose API key value or internal paths
        if "BOB_API_KEY" in msg or "api_key" in msg.lower():
            raise HTTPException(status_code=503, detail="BOB_API_KEY is not configured.")
        raise HTTPException(status_code=503, detail=f"Dispatch unavailable: {msg}")

    return record


@app.get("/api/escalations/{ticket_id}/dispatch/status")
def dispatch_status(ticket_id: str) -> Dict[str, Any]:
    """Return the current dispatch status for *ticket_id*.

    Uses ``process.poll()`` lazily — returns immediately without blocking.
    Never returns the API key, full environment, or raw exception details.
    """
    record = get_dispatch_status(ticket_id)
    if record is None:
        raise HTTPException(
            status_code=404,
            detail=f"No active dispatch found for ticket {ticket_id!r}",
        )
    return record


def _append_incident_history(report: EscalationReport) -> None:
    """Append one row to data/incident_history.csv for a completed fix_verified report.

    Uses EXACTLY the column schema generate_tickets.py writes:
      id, files_changed, risk_level, impact, tests_after, verdict

    files_changed is serialised as ", ".join(report.files_changed).
    Duplicate guard: each ticket_id is written at most once per process lifetime.
    """
    ticket_id = report.ticket_id
    if ticket_id in _incident_history_written:
        return

    csv_path = _INCIDENT_HISTORY_CSV
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    file_exists = csv_path.exists()
    fieldnames = ["id", "files_changed", "risk_level", "impact", "tests_after", "verdict"]

    files_changed_str = ", ".join(report.files_changed)
    impact_str = report.impact or ""

    row = {
        "id": ticket_id,
        "files_changed": files_changed_str,
        "risk_level": report.risk_level,
        "impact": impact_str,
        "tests_after": report.tests_after or "",
        "verdict": report.verdict,
    }

    with open(csv_path, "a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        if not file_exists:
            writer.writeheader()
        writer.writerow(row)

    _incident_history_written.add(ticket_id)
