from __future__ import annotations

from typing import List, Optional
from pydantic import BaseModel


class Ticket(BaseModel):
    id: str
    title: str
    description: str


class RoutingDecision(BaseModel):
    ticket_id: str
    domain: str
    method: str
    confidence: float
    explanation: Optional[str] = None


class ScorerResult(BaseModel):
    predicted_domain: str
    confidence: float
    evidence: List[str]
