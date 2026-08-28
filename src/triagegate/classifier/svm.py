"""SVM-based ticket classifier using TF-IDF + LinearSVC."""

from __future__ import annotations

import os
from pathlib import Path

import numpy as np
import pandas as pd
import joblib
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.svm import LinearSVC
from sklearn.pipeline import Pipeline

_DEFAULT_MODEL_PATH = Path(__file__).resolve().parents[3] / "data" / "svm_model.joblib"


def _softmax(x: np.ndarray) -> np.ndarray:
    e = np.exp(x - x.max())
    return e / e.sum()


class SvmClassifier:
    """TF-IDF + LinearSVC classifier for ticket triage.

    Uses 1-2 gram TF-IDF (lowercase, English stop words) piped into LinearSVC.
    Confidence is derived from the decision function margins via softmax.
    """

    def __init__(self) -> None:
        self._pipeline: Pipeline | None = None
        self._classes: list[str] = []

    # ------------------------------------------------------------------
    # Training
    # ------------------------------------------------------------------

    def fit(self, csv_path: str | os.PathLike) -> None:
        """Train on *csv_path* (must have columns: title, description, domain)."""
        df = pd.read_csv(csv_path)
        texts = (df["title"] + " " + df["description"]).tolist()
        labels = df["domain"].tolist()

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
        """Return the most-likely domain label."""
        if self._pipeline is None:
            raise RuntimeError("Model has not been trained. Call fit() first.")
        text = title + " " + description
        return str(self._pipeline.predict([text])[0])

    def confidence(self, title: str, description: str) -> float:
        """Return a 0-1 confidence score via softmax over decision-function margins."""
        if self._pipeline is None:
            raise RuntimeError("Model has not been trained. Call fit() first.")
        text = title + " " + description
        margins = self._pipeline.decision_function([text])[0]  # shape (n_classes,)
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
