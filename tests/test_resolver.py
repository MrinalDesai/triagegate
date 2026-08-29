"""Tests for Resolver ladder and /api/stats endpoint."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from triagegate.models.ticket import LadderResult, Ticket
from triagegate.pipeline.resolver import Resolver


# ---------------------------------------------------------------------------
# Module-level shared resolver — default thresholds (svm_threshold=0.55)
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def resolver() -> Resolver:
    return Resolver()


# ---------------------------------------------------------------------------
# Resolver with a lowered SVM threshold for rung-1 tests.
#
# The trained SVM (LinearSVC + softmax margins) tops out ~0.65 confidence.
# We use svm_threshold=0.55 so that unambiguous, domain-pure tickets reliably
# trigger rung 1, exercising that code path.
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def resolver_low_thresh() -> Resolver:
    return Resolver(svm_threshold=0.55)


# ---------------------------------------------------------------------------
# Tickets with clear, single-domain vocabulary that yield SVM conf > 0.55
# (confirmed against data/svm_model.joblib in development)
# ---------------------------------------------------------------------------
RUNG1_TICKETS: dict[str, tuple[str, str]] = {
    "api": (
        "POST /orders returns 503 only in production",
        "The search-service endpoint POST /products started returning HTTP 502 "
        "since last release. Logs show an unhandled exception in the request "
        "handler. Rolling back the last deployment temporarily fixes it.",
    ),
    "auth": (
        "SSO refresh token rotation broken on payment-service",
        "Refresh token rotation in reporting-service issues a new token but also "
        "invalidates valid sessions on logout. Users are being signed out "
        "unexpectedly. Confirmed after last SSO library upgrade.",
    ),
    "build": (
        "GitHub Actions stages run out of order – Gradle step skipped",
        "A misconfigured GitLab CI pipeline runs stages out of order so the "
        "Maven step is skipped after deploy. The artifact is never uploaded. "
        "Reverting the workflow YAML fixes it.",
    ),
    "database": (
        "Duplicate rows inserted into sessions due to missing constraint",
        "Concurrent INSERT operations on payments insert duplicate records since "
        "last release. There is no unique constraint on the composite key. A "
        "migration is needed to add the index.",
    ),
    "frontend": (
        "Tooltip on CartWidget flickers and disappears immediately",
        "The tooltip attached to NavBar appears for a split second then hides "
        "intermittently. Mouse-leave fires too early. The React component "
        "re-renders unexpectedly on hover. CSS transition is disrupted.",
    ),
}

# Mixed-vocabulary ticket: combines api + database, should fall past rung 1
# even at the low threshold.
_MIXED = (
    "API endpoint with slow database query",
    "The REST endpoint /api/orders sends a SQL query that scans the full "
    "table. The response is slow but the status code is 200. The database "
    "connection pool may also be involved.",
)

# Garbage ticket: no recognisable vocabulary → should escalate
_GARBAGE = (
    "asdfgh zxcvbn",
    "qwerty uiop 1234 !@#$",
)


# ===========================================================================
# Rung-1: clear tickets should resolve immediately via svm_gate
# (uses lowered threshold of 0.55 to match model capabilities)
# ===========================================================================

class TestRung1SvmGate:
    @pytest.mark.parametrize("domain", list(RUNG1_TICKETS))
    def test_clear_ticket_resolves_at_rung1(
        self, resolver_low_thresh: Resolver, domain: str
    ) -> None:
        title, desc = RUNG1_TICKETS[domain]
        ticket = Ticket(id=f"T-{domain}", title=title, description=desc)
        result = resolver_low_thresh.resolve(ticket)
        assert result.resolved_by == "svm_gate", (
            f"Expected svm_gate for domain '{domain}', got '{result.resolved_by}'"
        )

    @pytest.mark.parametrize("domain", list(RUNG1_TICKETS))
    def test_clear_ticket_correct_domain(
        self, resolver_low_thresh: Resolver, domain: str
    ) -> None:
        title, desc = RUNG1_TICKETS[domain]
        ticket = Ticket(id=f"T-{domain}", title=title, description=desc)
        result = resolver_low_thresh.resolve(ticket)
        assert result.domain == domain, (
            f"Expected domain '{domain}', got '{result.domain}'"
        )


# ===========================================================================
# Rung-2 / Rung-3: mixed and garbage tickets (default threshold)
# ===========================================================================

class TestRung2And3:
    def test_mixed_ticket_does_not_resolve_at_rung1(self, resolver: Resolver) -> None:
        """A mixed api+database ticket should not be caught by svm_gate (default thresh 0.55)."""
        ticket = Ticket(id="T-mixed", title=_MIXED[0], description=_MIXED[1])
        result = resolver.resolve(ticket)
        assert result.resolved_by != "svm_gate", (
            f"Mixed ticket unexpectedly resolved at rung 1 with domain '{result.domain}'"
        )

    def test_garbage_ticket_escalates(self, resolver: Resolver) -> None:
        """A ticket with no recognisable vocabulary should escalate."""
        ticket = Ticket(id="T-garbage", title=_GARBAGE[0], description=_GARBAGE[1])
        result = resolver.resolve(ticket)
        assert result.resolved_by == "escalate"
        assert result.domain == "escalated"


# ===========================================================================
# LadderResult structure
# ===========================================================================

class TestLadderResultStructure:
    def test_three_voter_entries_present(self, resolver: Resolver) -> None:
        title, desc = RUNG1_TICKETS["api"]
        ticket = Ticket(id="T-struct", title=title, description=desc)
        result = resolver.resolve(ticket)
        assert len(result.voters) == 3

    def test_voter_names(self, resolver: Resolver) -> None:
        title, desc = RUNG1_TICKETS["api"]
        ticket = Ticket(id="T-voters", title=title, description=desc)
        result = resolver.resolve(ticket)
        voter_names = {v.voter for v in result.voters}
        assert voter_names == {"svm", "knn", "scorer"}

    def test_elapsed_ms_present_and_fast(self, resolver: Resolver) -> None:
        title, desc = RUNG1_TICKETS["auth"]
        ticket = Ticket(id="T-timing", title=title, description=desc)
        result = resolver.resolve(ticket)
        assert hasattr(result, "elapsed_ms")
        assert result.elapsed_ms < 500, f"elapsed_ms={result.elapsed_ms} exceeds 500 ms"

    def test_ticket_fields_populated(self, resolver: Resolver) -> None:
        title, desc = RUNG1_TICKETS["build"]
        ticket = Ticket(id="T-fields", title=title, description=desc)
        result = resolver.resolve(ticket)
        assert result.ticket_id == "T-fields"
        assert result.title == title
        assert result.description == desc

    def test_evidence_is_list(self, resolver: Resolver) -> None:
        title, desc = RUNG1_TICKETS["database"]
        ticket = Ticket(id="T-evid", title=title, description=desc)
        result = resolver.resolve(ticket)
        assert isinstance(result.evidence, list)

    def test_ladder_result_is_pydantic_model(self, resolver: Resolver) -> None:
        title, desc = RUNG1_TICKETS["frontend"]
        ticket = Ticket(id="T-pydantic", title=title, description=desc)
        result = resolver.resolve(ticket)
        assert isinstance(result, LadderResult)


# ===========================================================================
# /api/stats endpoint
# ===========================================================================

class TestStatsEndpoint:
    """Tests for GET /api/stats."""

    def test_stats_returns_200(self) -> None:
        from triagegate.web.server import app
        client = TestClient(app)
        response = client.get("/api/stats")
        assert response.status_code == 200

    def test_stats_is_dict(self) -> None:
        from triagegate.web.server import app
        client = TestClient(app)
        response = client.get("/api/stats")
        assert isinstance(response.json(), dict)

    def test_stats_increments_after_route(self) -> None:
        from triagegate.web.server import app
        client = TestClient(app)

        before = client.get("/api/stats").json()
        before_total = sum(before.values())

        payload = {
            "id": "T-stat",
            "title": RUNG1_TICKETS["api"][0],
            "description": RUNG1_TICKETS["api"][1],
        }
        client.post("/api/route", json=payload)

        after = client.get("/api/stats").json()
        after_total = sum(after.values())

        assert after_total == before_total + 1

    def test_stats_rung_keys_are_valid(self) -> None:
        from triagegate.web.server import app
        client = TestClient(app)

        # Post a clear ticket to ensure at least one rung has been hit
        payload = {
            "id": "T-stat2",
            "title": RUNG1_TICKETS["database"][0],
            "description": RUNG1_TICKETS["database"][1],
        }
        client.post("/api/route", json=payload)

        data = client.get("/api/stats").json()
        valid_rungs = {"svm_gate", "voter_agreement", "escalate", "granite_tiebreak"}
        for key in data:
            assert key in valid_rungs, f"Unexpected rung key: '{key}'"
