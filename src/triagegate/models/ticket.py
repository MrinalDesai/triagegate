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


class LadderResult(BaseModel):
    """Full result returned by the resolver ladder."""

    # Ticket fields
    ticket_id: str
    title: str
    description: str

    # Decision
    domain: str
    resolved_by: str  # "svm_gate" | "voter_agreement" | "escalate"

    # Per-voter breakdown
    voters: List[VoterResult]

    # Evidence from the deterministic scorer
    evidence: List[str]

    # Timing
    elapsed_ms: float
