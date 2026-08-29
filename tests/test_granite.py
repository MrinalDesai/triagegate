"""Tests for Granite tie-break integration (rung 2.5).

All tests use StubLLMClient — no network calls, no real credentials needed.
"""

from __future__ import annotations

from typing import Optional, Sequence, Tuple

import pytest

from triagegate.llm.client import StubLLMClient, _parse_llm_json
from triagegate.models.ticket import Ticket
from triagegate.pipeline.resolver import Resolver


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_stub(
    return_value: Optional[Tuple[str, float]],
) -> StubLLMClient:
    """Return a StubLLMClient that always returns *return_value*."""
    return StubLLMClient(handler=lambda title, desc, domains: return_value)


# This ticket has all-different voter predictions AND no scorer evidence, so
# it reliably falls through rung 1 (SVM confidence too low) and rung 2
# (voters all disagree and/or scorer has no evidence), landing at rung 2.5.
#
# Confirmed voter breakdown against the real models:
#   svm:    auth   (0.28)
#   knn:    build  (0.80)
#   scorer: api    (0.0, evidence=[])
_DISAGREEING_TITLE = "Service crashes randomly"
_DISAGREEING_DESC = "The server process exits unexpectedly without any clear error message."

# Voter domains emitted by the three classifiers for the ticket above.
# These are used to make the stub agree/disagree deterministically.
_VOTER_DOMAINS = {"auth", "build", "api"}  # svm, knn, scorer respectively


def _disagreeing_ticket() -> Ticket:
    return Ticket(id="T-disagree", title=_DISAGREEING_TITLE, description=_DISAGREEING_DESC)


def _resolver_with_stub(stub: StubLLMClient) -> Resolver:
    return Resolver(llm_client=stub)


# ---------------------------------------------------------------------------
# Sanity: verify the ticket actually reaches rung 2.5 without an LLM
# ---------------------------------------------------------------------------

class TestTiebreakPrecondition:
    def test_ticket_escalates_without_llm(self) -> None:
        """The disagreeing ticket must escalate when no LLM is configured."""
        r = Resolver().resolve(_disagreeing_ticket())
        assert r.resolved_by == "escalate", (
            f"Precondition failed: expected escalate, got {r.resolved_by!r}. "
            "Update _DISAGREEING_TITLE/_DESC to a ticket that escapes rung 2."
        )


# ---------------------------------------------------------------------------
# Tiebreak resolves: stub agrees with a voter above threshold
# ---------------------------------------------------------------------------

class TestGraniteTiebreakResolves:
    def test_resolved_by_granite_tiebreak(self) -> None:
        """Stub returns a domain that one voter also predicted, confidence >= 0.6."""
        # Pick any domain from the real voter set
        agreed_domain = "auth"  # SVM predicted this
        assert agreed_domain in _VOTER_DOMAINS

        stub = _make_stub((agreed_domain, 0.8))
        r = _resolver_with_stub(stub).resolve(_disagreeing_ticket())

        assert r.resolved_by == "granite_tiebreak"
        assert r.domain == agreed_domain

    def test_granite_voter_entry_present_on_tiebreak(self) -> None:
        """When granite resolves the tie, a 'granite' entry appears in voters."""
        agreed_domain = "build"  # kNN predicted this
        stub = _make_stub((agreed_domain, 0.75))
        r = _resolver_with_stub(stub).resolve(_disagreeing_ticket())

        voter_names = [v.voter for v in r.voters]
        assert "granite" in voter_names

    def test_granite_voter_confidence_matches_stub(self) -> None:
        """Granite voter entry records the confidence returned by the stub."""
        agreed_domain = "api"  # scorer predicted this
        stub = _make_stub((agreed_domain, 0.91))
        r = _resolver_with_stub(stub).resolve(_disagreeing_ticket())

        granite_entry = next(v for v in r.voters if v.voter == "granite")
        assert granite_entry.confidence == pytest.approx(0.91, abs=1e-4)

    def test_tiebreak_exactly_at_threshold(self) -> None:
        """Confidence exactly 0.6 must resolve (boundary condition)."""
        agreed_domain = "auth"
        stub = _make_stub((agreed_domain, 0.6))
        r = _resolver_with_stub(stub).resolve(_disagreeing_ticket())

        assert r.resolved_by == "granite_tiebreak"


# ---------------------------------------------------------------------------
# Tiebreak escalates: stub returns None
# ---------------------------------------------------------------------------

class TestGraniteEscalatesOnNone:
    def test_escalates_when_stub_returns_none(self) -> None:
        """When the stub returns None, the resolver must escalate."""
        stub = _make_stub(None)
        r = _resolver_with_stub(stub).resolve(_disagreeing_ticket())

        assert r.resolved_by == "escalate"
        assert r.domain == "escalated"

    def test_granite_voter_entry_present_on_none(self) -> None:
        """Even on None, a 'granite' entry is appended to voters."""
        stub = _make_stub(None)
        r = _resolver_with_stub(stub).resolve(_disagreeing_ticket())

        voter_names = [v.voter for v in r.voters]
        assert "granite" in voter_names

    def test_granite_voter_unknown_domain_on_none(self) -> None:
        """Granite voter domain is 'unknown' and confidence is 0 when stub returns None."""
        stub = _make_stub(None)
        r = _resolver_with_stub(stub).resolve(_disagreeing_ticket())

        granite_entry = next(v for v in r.voters if v.voter == "granite")
        assert granite_entry.domain == "unknown"
        assert granite_entry.confidence == 0.0


# ---------------------------------------------------------------------------
# Tiebreak escalates: stub disagrees with all voters
# ---------------------------------------------------------------------------

class TestGraniteEscalatesOnDisagreement:
    def test_escalates_when_stub_disagrees_with_all_voters(self) -> None:
        """Stub picks a valid domain that no voter chose → escalate."""
        # All domains that are NOT in the voter set
        all_domains = ["api", "database", "frontend", "auth", "build"]
        outsider = next(d for d in all_domains if d not in _VOTER_DOMAINS)

        stub = _make_stub((outsider, 0.9))
        r = _resolver_with_stub(stub).resolve(_disagreeing_ticket())

        assert r.resolved_by == "escalate"
        assert r.domain == "escalated"

    def test_escalates_when_stub_below_threshold(self) -> None:
        """Stub returns a voter-agreeable domain but below 0.6 confidence → escalate."""
        agreed_domain = "auth"
        stub = _make_stub((agreed_domain, 0.59))
        r = _resolver_with_stub(stub).resolve(_disagreeing_ticket())

        assert r.resolved_by == "escalate"
        assert r.domain == "escalated"

    def test_granite_voter_recorded_even_when_not_resolving(self) -> None:
        """Granite voter entry appears even when granite doesn't resolve the ticket."""
        outsider = next(
            d for d in ["api", "database", "frontend", "auth", "build"]
            if d not in _VOTER_DOMAINS
        )
        stub = _make_stub((outsider, 0.9))
        r = _resolver_with_stub(stub).resolve(_disagreeing_ticket())

        voter_names = [v.voter for v in r.voters]
        assert "granite" in voter_names


# ---------------------------------------------------------------------------
# llm_client=None behaves exactly as before (fully offline-safe)
# ---------------------------------------------------------------------------

class TestResolverWithoutLLM:
    @pytest.fixture(scope="module")
    def resolver(self) -> Resolver:
        return Resolver()  # llm_client=None by default

    def test_no_granite_voter_entry_on_disagreeing(self, resolver: Resolver) -> None:
        """Without an LLM client, 'granite' never appears in voters."""
        r = resolver.resolve(_disagreeing_ticket())
        voter_names = [v.voter for v in r.voters]
        assert "granite" not in voter_names

    def test_exactly_three_voters_on_rung1_ticket(self, resolver: Resolver) -> None:
        """Rung-1 tickets always produce exactly 3 voters (granite never reached)."""
        ticket = Ticket(
            id="T-api",
            title="POST /orders returns 503 only in production",
            description=(
                "The search-service endpoint POST /products started returning HTTP 502 "
                "since last release. Logs show an unhandled exception in the request "
                "handler. Rolling back the last deployment temporarily fixes it."
            ),
        )
        r = Resolver(svm_threshold=0.55).resolve(ticket)
        assert len(r.voters) == 3

    def test_voter_names_are_standard_on_rung1_ticket(self, resolver: Resolver) -> None:
        ticket = Ticket(
            id="T-api2",
            title="POST /orders returns 503 only in production",
            description=(
                "The search-service endpoint POST /products started returning HTTP 502 "
                "since last release. Logs show an unhandled exception in the request "
                "handler. Rolling back the last deployment temporarily fixes it."
            ),
        )
        r = Resolver(svm_threshold=0.55).resolve(ticket)
        assert {v.voter for v in r.voters} == {"svm", "knn", "scorer"}

    def test_escalates_as_before(self, resolver: Resolver) -> None:
        """The disagreeing ticket still escalates with llm_client=None."""
        r = resolver.resolve(_disagreeing_ticket())
        assert r.resolved_by == "escalate"
        assert r.domain == "escalated"

    def test_rung1_still_works(self, resolver: Resolver) -> None:
        """Clear API ticket still resolves via svm_gate with llm_client=None."""
        resolver_low = Resolver(svm_threshold=0.55)
        ticket = Ticket(
            id="T-api3",
            title="POST /orders returns 503 only in production",
            description=(
                "The search-service endpoint POST /products started returning HTTP 502 "
                "since last release. Logs show an unhandled exception in the request "
                "handler. Rolling back the last deployment temporarily fixes it."
            ),
        )
        r = resolver_low.resolve(ticket)
        assert r.resolved_by == "svm_gate"


# ---------------------------------------------------------------------------
# _parse_llm_json unit tests
# ---------------------------------------------------------------------------

class TestParseLlmJson:
    _DOMAINS = ["api", "database", "frontend", "auth", "build"]

    def test_clean_json(self) -> None:
        raw = '{"domain": "api", "confidence": 0.85}'
        result = _parse_llm_json(raw, self._DOMAINS)
        assert result == ("api", 0.85)

    def test_json_surrounded_by_prose(self) -> None:
        raw = 'Sure! Here is my answer: {"domain": "auth", "confidence": 0.7} Hope that helps.'
        result = _parse_llm_json(raw, self._DOMAINS)
        assert result == ("auth", 0.7)

    def test_unknown_domain_returns_none(self) -> None:
        raw = '{"domain": "networking", "confidence": 0.9}'
        result = _parse_llm_json(raw, self._DOMAINS)
        assert result is None

    def test_malformed_json_returns_none(self) -> None:
        raw = "not json at all"
        result = _parse_llm_json(raw, self._DOMAINS)
        assert result is None

    def test_empty_string_returns_none(self) -> None:
        result = _parse_llm_json("", self._DOMAINS)
        assert result is None

    def test_case_insensitive_domain(self) -> None:
        raw = '{"domain": "API", "confidence": 0.6}'
        result = _parse_llm_json(raw, self._DOMAINS)
        assert result == ("api", 0.6)
