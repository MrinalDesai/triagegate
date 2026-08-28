"""Tests for DeterministicScorer."""

from __future__ import annotations

import pytest

from triagegate.classifier.scorer import DeterministicScorer
from triagegate.models.ticket import ScorerResult

scorer = DeterministicScorer()


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------

def _score(title: str, description: str) -> ScorerResult:
    return scorer.score(title, description)


# ---------------------------------------------------------------------------
# One clearly-worded ticket per domain – confidence must be > 0.7
# ---------------------------------------------------------------------------

class TestDomainClassification:
    def test_api_ticket(self):
        result = _score(
            title="REST endpoint returns 500 on POST /users",
            description=(
                "The API route /api/v2/users returns an HTTP 500 status code "
                "when the request payload contains a null field. Curl reproduces it."
            ),
        )
        assert result.predicted_domain == "api"
        assert result.confidence > 0.7

    def test_database_ticket(self):
        result = _score(
            title="Slow query causing deadlock in Postgres",
            description=(
                "A database migration left a missing index on the transactions table. "
                "The connection pool is exhausted and we are seeing row lock contention "
                "in the SQL query logs."
            ),
        )
        assert result.predicted_domain == "database"
        assert result.confidence > 0.7

    def test_frontend_ticket(self):
        result = _score(
            title="React component fails to render after CSS update",
            description=(
                "The UI button in the modal is missing its style after a CSS change. "
                "The browser console shows an undefined variable in the DOM handler "
                "and the layout is broken on the page."
            ),
        )
        assert result.predicted_domain == "frontend"
        assert result.confidence > 0.7

    def test_auth_ticket(self):
        result = _score(
            title="JWT token rejected – 401 Unauthorized after login",
            description=(
                "After a successful login the session token is issued but every "
                "subsequent request returns 401. OAuth flow seems fine; the JWT "
                "credential is present. Possibly a permission / authorization issue."
            ),
        )
        assert result.predicted_domain == "auth"
        assert result.confidence > 0.7

    def test_build_ticket(self):
        result = _score(
            title="Docker image fails to compile in CI pipeline",
            description=(
                "The build step in the CD pipeline errors out when webpack tries to "
                "bundle the npm package. The Gradle dependency cannot be resolved and "
                "the container artifact is never produced."
            ),
        )
        assert result.predicted_domain == "build"
        assert result.confidence > 0.7


# ---------------------------------------------------------------------------
# Ambiguous ticket mixing api + database – confidence must be < 0.5
# ---------------------------------------------------------------------------

class TestAmbiguousTicket:
    def test_api_database_mixed_low_confidence(self):
        result = _score(
            title="API endpoint with slow database query",
            description=(
                "The REST endpoint /api/orders sends a SQL query that scans the full "
                "table. The response is slow but the status code is 200. The database "
                "connection pool may also be involved."
            ),
        )
        # Hits are spread across api AND database → confidence should be low
        assert result.confidence < 0.5


# ---------------------------------------------------------------------------
# Empty / garbage input – confidence near 0
# ---------------------------------------------------------------------------

class TestEdgeCases:
    def test_empty_ticket_confidence_is_zero(self):
        result = _score(title="", description="")
        assert result.confidence == 0.0

    def test_garbage_ticket_low_confidence(self):
        result = _score(
            title="asdfgh zxcvbn",
            description="qwerty uiop 1234 !@#$ lorem ipsum dolor sit amet",
        )
        assert result.confidence < 0.1


# ---------------------------------------------------------------------------
# Evidence list contains actual matched terms
# ---------------------------------------------------------------------------

class TestEvidence:
    def test_evidence_contains_matched_terms(self):
        result = _score(
            title="OAuth SSO login broken",
            description="Cannot complete authentication. The 2fa step returns 401.",
        )
        assert result.predicted_domain == "auth"
        # All reported evidence terms must genuinely appear in the text
        combined_text = "oauth sso login broken cannot complete authentication. the 2fa step returns 401."
        for term in result.evidence:
            assert term in combined_text, f"Evidence term '{term}' not found in text"
        # At least some terms should be found
        assert len(result.evidence) >= 1

    def test_evidence_is_empty_when_no_hits(self):
        result = _score(title="", description="")
        assert result.evidence == []
