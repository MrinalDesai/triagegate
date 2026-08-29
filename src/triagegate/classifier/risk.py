"""Binary risk classifier: predicts 'high' or 'low' risk from ticket text.

Training data
-------------
The classifier is trained on rows from ``data/incident_history.csv`` joined
to ticket text from ``data/tickets.csv`` (and optionally ``data/eval_tickets.csv``).
Each joined row provides:
    text       – ticket title + " " + ticket description
    risk_level – "high" | "low"  (label)

Model
-----
TF-IDF (1-2 gram, lowercase, English stop-words) → LinearSVC.
Confidence is derived from decision-function margins via softmax,
matching the convention used by :class:`~triagegate.classifier.svm.SvmClassifier`.

Persistence
-----------
``save`` / ``load`` use joblib; the default artifact path is
``data/risk_model.joblib``.
"""

from __future__ import annotations

import os
from pathlib import Path

import numpy as np
import pandas as pd
import joblib
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.svm import LinearSVC
from sklearn.pipeline import Pipeline

_DEFAULT_MODEL_PATH = Path(__file__).resolve().parents[3] / "data" / "risk_model.joblib"


def _softmax(x: np.ndarray) -> np.ndarray:
    e = np.exp(x - x.max())
    return e / e.sum()


class RiskClassifier:
    """TF-IDF + LinearSVC binary classifier that predicts ticket risk level.

    Labels: ``"high"`` | ``"low"``

    Usage::

        clf = RiskClassifier()
        clf.fit("data/tickets.csv", "data/incident_history.csv")
        label = clf.predict("Payment timeout", "Checkout endpoint crashes on POST /payments")
        conf  = clf.confidence("Payment timeout", "Checkout endpoint crashes on POST /payments")
        clf.save("data/risk_model.joblib")

        loaded = RiskClassifier()
        loaded.load("data/risk_model.joblib")
    """

    def __init__(self) -> None:
        self._pipeline: Pipeline | None = None
        self._classes: list[str] = []

    # ------------------------------------------------------------------
    # Training
    # ------------------------------------------------------------------

    def fit(
        self,
        tickets_csv: str | os.PathLike,
        history_csv: str | os.PathLike,
        extra_tickets_csv: str | os.PathLike | None = None,
    ) -> None:
        """Train on ticket text joined to incident-history risk labels.

        Parameters
        ----------
        tickets_csv:
            Path to the main ticket CSV (columns: id, title, description, domain).
        history_csv:
            Path to the incident-history CSV (columns: id, risk_level, …).
        extra_tickets_csv:
            Optional additional ticket CSV (e.g. eval_tickets.csv) whose rows are
            also included in training so all history ids are resolvable.
        """
        tickets_df = pd.read_csv(tickets_csv)
        if extra_tickets_csv is not None:
            extra_df = pd.read_csv(extra_tickets_csv)
            tickets_df = pd.concat([tickets_df, extra_df], ignore_index=True)

        history_df = pd.read_csv(history_csv)

        # Join on id to get (text, risk_level) pairs.
        merged = history_df.merge(tickets_df[["id", "title", "description"]], on="id", how="inner")

        texts = (merged["title"] + " " + merged["description"]).tolist()
        labels = merged["risk_level"].tolist()

        self._pipeline = Pipeline(
            [
                (
                    "tfidf",
                    TfidfVectorizer(
                        ngram_range=(1, 2),
                        lowercase=True,
                        stop_words="english",
                    ),
                ),
                ("svc", LinearSVC(max_iter=5000)),
            ]
        )
        self._pipeline.fit(texts, labels)
        self._classes = list(self._pipeline.named_steps["svc"].classes_)

    # ------------------------------------------------------------------
    # Inference
    # ------------------------------------------------------------------

    def predict(self, title: str, description: str) -> str:
        """Return ``'high'`` or ``'low'`` risk label."""
        if self._pipeline is None:
            raise RuntimeError("Model has not been trained. Call fit() first.")
        text = title + " " + description
        return str(self._pipeline.predict([text])[0])

    def confidence(self, title: str, description: str) -> float:
        """Return a 0-1 confidence score via softmax over decision-function margins."""
        if self._pipeline is None:
            raise RuntimeError("Model has not been trained. Call fit() first.")
        text = title + " " + description
        margins = self._pipeline.decision_function([text])[0]
        if np.ndim(margins) == 0:
            # Binary LinearSVC returns a scalar — convert to two-element array.
            margins = np.array([-float(margins), float(margins)])
        probs = _softmax(np.asarray(margins, dtype=float))
        return float(probs.max())

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def save(self, path: str | os.PathLike | None = None) -> None:
        """Persist the trained pipeline with joblib."""
        dest = Path(path) if path is not None else _DEFAULT_MODEL_PATH
        dest.parent.mkdir(parents=True, exist_ok=True)
        joblib.dump({"pipeline": self._pipeline, "classes": self._classes}, dest)

    def load(self, path: str | os.PathLike | None = None) -> None:
        """Restore a previously saved pipeline."""
        src = Path(path) if path is not None else _DEFAULT_MODEL_PATH
        data = joblib.load(src)
        self._pipeline = data["pipeline"]
        self._classes = data["classes"]
