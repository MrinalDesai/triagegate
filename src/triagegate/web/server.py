from fastapi import FastAPI

from triagegate.models.ticket import RoutingDecision, Ticket

app = FastAPI(title="TriageGate")


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}


@app.post("/api/route", response_model=RoutingDecision)
def route_ticket(ticket: Ticket) -> RoutingDecision:
    return RoutingDecision(
        ticket_id=ticket.id,
        domain="unclassified",
        method="stub",
        confidence=0.0,
        explanation="Stub routing — no classifier loaded.",
    )
