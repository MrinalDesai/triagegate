from __future__ import annotations

from typing import Dict, List, Optional
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


class VoterResult(BaseModel):
    """Per-voter breakdown entry in a LadderResult."""

    voter: str
    domain: str
    confidence: float


class IncidentSummary(BaseModel):
    """A condensed incident-history record attached to a LadderResult."""

    id: str
    title: str
    domain: str
    risk_level: str
    impact: str
    verdict: str


class LadderResult(BaseModel):
    """Full result returned by the resolver ladder."""

    # Ticket fields
    ticket_id: str
    title: str
    description: str

    # Decision
    domain: str
    resolved_by: str  # "svm_gate" | "voter_agreement" | "granite_tiebreak" | "escalate"

    # Per-voter breakdown
    voters: List[VoterResult]

    # Evidence from the deterministic scorer
    evidence: List[str]

    # Timing
    elapsed_ms: float

    # Risk prediction (populated by Resolver when risk model is available)
    predicted_risk: Optional[str] = None
    predicted_risk_confidence: Optional[float] = None

    # Similar incidents from incident history (max 5, populated by Resolver)
    similar_incidents: List[IncidentSummary] = []
