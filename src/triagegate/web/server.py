from __future__ import annotations

import csv
import os
from collections import defaultdict
from pathlib import Path
from typing import Dict

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

try:
    from dotenv import load_dotenv  # type: ignore
    load_dotenv()
except ImportError:
    pass

from triagegate.escalation.bob_tier import EscalationReport, EscalationStore
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


@app.post("/api/escalations/{ticket_id}/approve", response_model=EscalationReport)
def approve_escalation(ticket_id: str) -> EscalationReport:
    """Approve a pending escalation report; append incident to history CSV."""
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

    # Append to incident history CSV
    _append_incident_history(report)

    # Reload the resolver's history so future tickets see this incident
    if _resolver is not None:
        from triagegate.pipeline.resolver import _DEFAULT_HISTORY_CSV
        history_path = Path(_INCIDENT_HISTORY_CSV)
        if history_path.exists():
            from triagegate.pipeline.resolver import Resolver as _R
            _resolver._history = _R._load_history(history_path)

    return report


@app.post("/api/escalations/{ticket_id}/reject", response_model=EscalationReport)
def reject_escalation(ticket_id: str) -> EscalationReport:
    """Reject a pending escalation report."""
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


def _append_incident_history(report: EscalationReport) -> None:
    """Append one row to data/incident_history.csv for an approved report."""
    _INCIDENT_HISTORY_CSV.parent.mkdir(parents=True, exist_ok=True)
    file_exists = _INCIDENT_HISTORY_CSV.exists()
    fieldnames = ["id", "title", "domain", "risk_level", "impact", "verdict"]
    # title: use ticket_id as fallback; domain: from report if present else "escalated"
    title = report.ticket_id
    domain = "escalated"
    # impact: first non-empty line of root_cause_analysis, else root_cause
    rca = report.root_cause_analysis.strip()
    if rca:
        impact = rca.splitlines()[0].strip()
    else:
        impact = report.root_cause.splitlines()[0].strip()
    row = {
        "id": report.ticket_id,
        "title": title,
        "domain": domain,
        "risk_level": report.risk_level,
        "impact": impact,
        "verdict": report.verdict,
    }
    with open(_INCIDENT_HISTORY_CSV, "a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        if not file_exists:
            writer.writeheader()
        writer.writerow(row)
