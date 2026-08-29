"""Resolver ladder: combines DeterministicScorer, SvmClassifier, and KnnClassifier."""

from __future__ import annotations

import time
from collections import Counter
from pathlib import Path
from typing import Optional

import pandas as pd

from triagegate.classifier.knn import KnnClassifier
from triagegate.classifier.risk import RiskClassifier
from triagegate.classifier.scorer import DeterministicScorer
from triagegate.classifier.svm import SvmClassifier
from triagegate.llm.client import LLMClient
from triagegate.models.ticket import IncidentSummary, LadderResult, Ticket, VoterResult

_DATA_DIR = Path(__file__).resolve().parents[3] / "data"
_DEFAULT_SVM_PATH = _DATA_DIR / "svm_model.joblib"
_DEFAULT_KNN_CSV = _DATA_DIR / "tickets.csv"
_DEFAULT_RISK_PATH = _DATA_DIR / "risk_model.joblib"
_DEFAULT_HISTORY_CSV = _DATA_DIR / "incident_history.csv"

_GRANITE_CONFIDENCE_THRESHOLD = 0.6

_MAX_SIMILAR_INCIDENTS = 5


class Resolver:
    """Three-rung decision ladder for ticket triage.

    Rungs (tried in order):
    1. ``svm_gate``         — SVM confidence >= *svm_threshold* → resolve immediately.
    2. ``voter_agreement``  — majority vote across all three classifiers AND scorer
                              produced nonzero evidence.
    2.5 ``granite_tiebreak``— optional LLM tie-break: only when voters disagree AND
                              an :class:`~triagegate.llm.client.LLMClient` is configured;
                              resolves when Granite picks a domain with confidence >= 0.6
                              that also matches at least one existing voter's prediction.
    3. ``escalate``         — fallback when the above rungs fail.

    Parameters
    ----------
    svm_threshold:
        Minimum SVM confidence required for rung-1 resolution (default 0.55).
    agreement_min_voters:
        Minimum number of voters that must agree for rung-2 resolution (default 2).
    svm_model_path:
        Path to the pre-trained SVM joblib file.  Defaults to ``data/svm_model.joblib``.
    knn_csv_path:
        Path to the CSV used to train the kNN at startup.  Defaults to ``data/tickets.csv``.
    llm_client:
        Optional :class:`~triagegate.llm.client.LLMClient` implementation used as a
        tie-break voter (rung 2.5).  When *None* the resolver is fully offline-safe.
    risk_model_path:
        Path to the pre-trained RiskClassifier joblib file.  Defaults to
        ``data/risk_model.joblib``.  When the file does not exist the risk fields
        are left as *None* and ``similar_incidents`` is empty.
    history_csv_path:
        Path to the incident-history CSV used to populate ``similar_incidents``.
        Defaults to ``data/incident_history.csv``.
    """

    def __init__(
        self,
        *,
        svm_threshold: float = 0.55,
        agreement_min_voters: int = 2,
        svm_model_path: str | Path | None = None,
        knn_csv_path: str | Path | None = None,
        llm_client: Optional[LLMClient] = None,
        risk_model_path: str | Path | None = None,
        history_csv_path: str | Path | None = None,
    ) -> None:
        self.svm_threshold = svm_threshold
        self.agreement_min_voters = agreement_min_voters
        self._llm_client = llm_client

        # --- Scorer (no training needed) ---
        self._scorer = DeterministicScorer()

        # --- SVM: loaded from joblib ---
        self._svm = SvmClassifier()
        self._svm.load(svm_model_path or _DEFAULT_SVM_PATH)

        # --- kNN: trained at startup from CSV ---
        self._knn = KnnClassifier()
        self._knn.fit(knn_csv_path or _DEFAULT_KNN_CSV)

        # --- RiskClassifier: loaded from joblib (optional) ---
        self._risk: RiskClassifier | None = None
        risk_path = Path(risk_model_path) if risk_model_path is not None else _DEFAULT_RISK_PATH
        if risk_path.exists():
            self._risk = RiskClassifier()
            self._risk.load(risk_path)

        # --- Incident history: keyed by ticket id (optional) ---
        self._history: dict[str, dict] = {}
        history_path = Path(history_csv_path) if history_csv_path is not None else _DEFAULT_HISTORY_CSV
        if history_path.exists():
            self._history = self._load_history(history_path)

        # --- Ticket title lookup (for similar_incidents join) ---
        self._ticket_titles: dict[str, str] = {}
        knn_csv = Path(knn_csv_path) if knn_csv_path is not None else Path(_DEFAULT_KNN_CSV)
        if knn_csv.exists():
            df = pd.read_csv(knn_csv)
            if "id" in df.columns and "title" in df.columns:
                self._ticket_titles = dict(zip(df["id"], df["title"]))

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def resolve(self, ticket: Ticket) -> LadderResult:
        """Run the ladder and return a :class:`LadderResult`."""
        t0 = time.perf_counter()

        title = ticket.title
        description = ticket.description

        # --- Ask every voter up front so we can always populate the breakdown ---
        svm_domain = self._svm.predict(title, description)
        svm_conf = self._svm.confidence(title, description)

        knn_domain = self._knn.predict(title, description)
        knn_conf = self._knn.confidence(title, description)

        scorer_result = self._scorer.score(title, description)
        scorer_domain = scorer_result.predicted_domain
        scorer_conf = scorer_result.confidence
        evidence = scorer_result.evidence

        voters = [
            VoterResult(voter="svm", domain=svm_domain, confidence=round(svm_conf, 4)),
            VoterResult(voter="knn", domain=knn_domain, confidence=round(knn_conf, 4)),
            VoterResult(voter="scorer", domain=scorer_domain, confidence=round(scorer_conf, 4)),
        ]

        # ----------------------------------------------------------------
        # RUNG 1 — svm_gate
        # ----------------------------------------------------------------
        if svm_conf >= self.svm_threshold:
            resolved_by = "svm_gate"
            domain = svm_domain
        else:
            # ----------------------------------------------------------------
            # RUNG 2 — voter_agreement
            # ----------------------------------------------------------------
            vote_counts: Counter[str] = Counter(
                [svm_domain, knn_domain, scorer_domain]
            )
            majority_domain, majority_count = vote_counts.most_common(1)[0]
            scorer_has_evidence = len(evidence) > 0

            if majority_count >= self.agreement_min_voters and scorer_has_evidence:
                resolved_by = "voter_agreement"
                domain = majority_domain
            else:
                # ----------------------------------------------------------------
                # RUNG 2.5 — granite_tiebreak (optional)
                # ----------------------------------------------------------------
                resolved_by, domain = self._try_granite_tiebreak(
                    title, description,
                    voter_domains={svm_domain, knn_domain, scorer_domain},
                    voters=voters,
                )

        elapsed_ms = (time.perf_counter() - t0) * 1000.0

        # --- Risk prediction ---
        predicted_risk: str | None = None
        predicted_risk_confidence: float | None = None
        if self._risk is not None:
            predicted_risk = self._risk.predict(title, description)
            predicted_risk_confidence = round(self._risk.confidence(title, description), 4)

        # --- Similar incidents (kNN neighbors joined to history) ---
        similar_incidents = self._get_similar_incidents(title, description)

        return LadderResult(
            ticket_id=ticket.id,
            title=title,
            description=description,
            domain=domain,
            resolved_by=resolved_by,
            voters=voters,
            evidence=evidence,
            elapsed_ms=round(elapsed_ms, 3),
            predicted_risk=predicted_risk,
            predicted_risk_confidence=predicted_risk_confidence,
            similar_incidents=similar_incidents,
        )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _load_history(path: Path) -> dict[str, dict]:
        """Load incident_history.csv into a dict keyed by ticket id."""
        df = pd.read_csv(path)
        return {str(row["id"]): row.to_dict() for _, row in df.iterrows()}

    def _get_similar_incidents(self, title: str, description: str) -> list[IncidentSummary]:
        """Return up to 5 IncidentSummary objects for the kNN neighbors."""
        if not self._history:
            return []
        neighbors = self._knn.neighbors(title, description)
        seen_ids: set[str] = set()
        results: list[IncidentSummary] = []
        for nbr in neighbors:
            tid = nbr.ticket_id
            if not tid or tid not in self._history:
                continue
            if tid in seen_ids:
                continue
            seen_ids.add(tid)
            hist = self._history[tid]
            nbr_title = self._ticket_titles.get(tid, nbr.title)
            results.append(
                IncidentSummary(
                    id=tid,
                    title=nbr_title,
                    domain=nbr.domain,
                    risk_level=str(hist.get("risk_level", "")),
                    impact=str(hist.get("impact", "")),
                    verdict=str(hist.get("verdict", "")),
                )
            )
            if len(results) >= _MAX_SIMILAR_INCIDENTS:
                break
        return results

    def _try_granite_tiebreak(
        self,
        title: str,
        description: str,
        voter_domains: set[str],
        voters: list[VoterResult],
    ) -> tuple[str, str]:
        """Attempt rung-2.5 resolution; return ``(resolved_by, domain)``."""
        if self._llm_client is None:
            return "escalate", "escalated"

        from triagegate.classifier.scorer import DOMAINS  # avoid circular at module level

        result = self._llm_client.classify(title, description, DOMAINS)

        if (
            result is not None
            and result[1] >= _GRANITE_CONFIDENCE_THRESHOLD
            and result[0] in voter_domains
        ):
            granite_domain, granite_conf = result
            voters.append(
                VoterResult(
                    voter="granite",
                    domain=granite_domain,
                    confidence=round(granite_conf, 4),
                )
            )
            return "granite_tiebreak", granite_domain

        # Record the granite attempt even when it doesn't resolve (if called)
        if result is not None:
            voters.append(
                VoterResult(
                    voter="granite",
                    domain=result[0],
                    confidence=round(result[1], 4),
                )
            )
        else:
            # None response — still record a granite entry so callers can see it was tried
            voters.append(
                VoterResult(voter="granite", domain="unknown", confidence=0.0)
            )

        return "escalate", "escalated"
