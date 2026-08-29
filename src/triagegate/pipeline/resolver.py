"""Resolver ladder: combines DeterministicScorer, SvmClassifier, and KnnClassifier."""

from __future__ import annotations

import time
from collections import Counter
from pathlib import Path

from triagegate.classifier.knn import KnnClassifier
from triagegate.classifier.scorer import DeterministicScorer
from triagegate.classifier.svm import SvmClassifier
from triagegate.models.ticket import LadderResult, Ticket, VoterResult

_DATA_DIR = Path(__file__).resolve().parents[3] / "data"
_DEFAULT_SVM_PATH = _DATA_DIR / "svm_model.joblib"
_DEFAULT_KNN_CSV = _DATA_DIR / "tickets.csv"


class Resolver:
    """Three-rung decision ladder for ticket triage.

    Rungs (tried in order):
    1. ``svm_gate``       — SVM confidence >= *svm_threshold* → resolve immediately.
    2. ``voter_agreement`` — majority vote across all three classifiers AND scorer
                             produced nonzero evidence.
    3. ``escalate``       — fallback when the above rungs fail.

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
    """

    def __init__(
        self,
        *,
        svm_threshold: float = 0.55,
        agreement_min_voters: int = 2,
        svm_model_path: str | Path | None = None,
        knn_csv_path: str | Path | None = None,
    ) -> None:
        self.svm_threshold = svm_threshold
        self.agreement_min_voters = agreement_min_voters

        # --- Scorer (no training needed) ---
        self._scorer = DeterministicScorer()

        # --- SVM: loaded from joblib ---
        self._svm = SvmClassifier()
        self._svm.load(svm_model_path or _DEFAULT_SVM_PATH)

        # --- kNN: trained at startup from CSV ---
        self._knn = KnnClassifier()
        self._knn.fit(knn_csv_path or _DEFAULT_KNN_CSV)

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
                # RUNG 3 — escalate
                # ----------------------------------------------------------------
                resolved_by = "escalate"
                domain = "escalated"

        elapsed_ms = (time.perf_counter() - t0) * 1000.0

        return LadderResult(
            ticket_id=ticket.id,
            title=title,
            description=description,
            domain=domain,
            resolved_by=resolved_by,
            voters=voters,
            evidence=evidence,
            elapsed_ms=round(elapsed_ms, 3),
        )
