import pytest
from pydantic import ValidationError

from triagegate.models.ticket import RoutingDecision, Ticket


class TestTicket:
    def test_valid_ticket(self):
        ticket = Ticket(id="T-001", title="Login fails", description="Cannot log in after password reset.")
        assert ticket.id == "T-001"
        assert ticket.title == "Login fails"
        assert ticket.description == "Cannot log in after password reset."

    def test_missing_field_raises(self):
        with pytest.raises(ValidationError):
            Ticket(id="T-002", title="Missing desc")  # description is required

    def test_ticket_serialises(self):
        ticket = Ticket(id="T-003", title="Slow query", description="DB query takes 30 s.")
        data = ticket.model_dump()
        assert data == {"id": "T-003", "title": "Slow query", "description": "DB query takes 30 s."}


class TestRoutingDecision:
    def test_valid_decision(self):
        decision = RoutingDecision(
            ticket_id="T-001",
            domain="database",
            method="stub",
            confidence=0.95,
            explanation="High keyword overlap.",
        )
        assert decision.ticket_id == "T-001"
        assert decision.domain == "database"
        assert decision.method == "stub"
        assert decision.confidence == 0.95
        assert decision.explanation == "High keyword overlap."

    def test_explanation_optional(self):
        decision = RoutingDecision(
            ticket_id="T-002",
            domain="networking",
            method="rule",
            confidence=1.0,
        )
        assert decision.explanation is None

    def test_missing_required_field_raises(self):
        with pytest.raises(ValidationError):
            RoutingDecision(ticket_id="T-003", domain="auth", confidence=0.5)  # method missing
