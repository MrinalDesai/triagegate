from __future__ import annotations

from collections import defaultdict
from typing import Dict

from fastapi import FastAPI

from triagegate.models.ticket import LadderResult, RoutingDecision, Ticket
from triagegate.pipeline.resolver import Resolver

app = FastAPI(title="TriageGate")

# Lazy-initialised singleton resolver (created on first request so tests that
# only hit /health don't pay the startup cost).
_resolver: Resolver | None = None

# Session-level counters: resolved-by rung → ticket count
_rung_counts: Dict[str, int] = defaultdict(int)


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
