"""Deterministic keyword-based scorer for bug report triage."""

from __future__ import annotations

import re

from triagegate.classifier.vocabulary import VOCABULARY
from triagegate.models.ticket import ScorerResult

DOMAINS = list(VOCABULARY.keys())


class DeterministicScorer:
    """Classifies a bug report into one of five domains using weighted term matching.

    Domains: api, database, frontend, auth, build.

    No LLM calls, no external dependencies. Pure string matching against a
    controlled vocabulary.
    """

    def score(self, title: str, description: str) -> ScorerResult:
        """Score a ticket and return a :class:`ScorerResult`.

        The combined title and description is lowercased and searched for each
        vocabulary term.  Per-domain scores are the sum of weights for each
        matching term.  Confidence is normalised so that a single-domain
        dominant signal yields values near 1.0 while scattered or absent hits
        yield values near 0.
        """
        text = (title + " " + description).lower()

        domain_scores: dict[str, float] = {}
        domain_evidence: dict[str, list[str]] = {}

        for domain, terms in VOCABULARY.items():
            total = 0.0
            matched: list[str] = []
            for term, weight in terms:
                # Use whole-word matching to avoid false positives (e.g. "ui"
                # inside "ipsum").  Multi-word terms (e.g. "connection pool")
                # are matched verbatim because the spaces already act as
                # natural boundaries.
                pattern = r"(?<![a-z0-9])" + re.escape(term) + r"(?![a-z0-9])"
                if re.search(pattern, text):
                    total += weight
                    matched.append(term)
            domain_scores[domain] = total
            domain_evidence[domain] = matched

        best_domain = max(domain_scores, key=lambda d: domain_scores[d])
        best_score = domain_scores[best_domain]
        total_score = sum(domain_scores.values())

        if total_score == 0.0:
            return ScorerResult(
                predicted_domain=best_domain,
                confidence=0.0,
                evidence=[],
            )

        # Confidence: fraction of total weight that belongs to the winning domain,
        # scaled so that full dominance (all weight in one domain) → 1.0.
        raw_fraction = best_score / total_score

        # raw_fraction is in [1/5, 1.0] when there are any hits.
        # Remap: 0.2 → 0, 1.0 → 1.0  via  (raw - 1/n) / (1 - 1/n)
        n = len(DOMAINS)
        confidence = (raw_fraction - 1.0 / n) / (1.0 - 1.0 / n)
        confidence = max(0.0, min(1.0, confidence))

        return ScorerResult(
            predicted_domain=best_domain,
            confidence=round(confidence, 4),
            evidence=domain_evidence[best_domain],
        )
