"""kNN-based ticket classifier using TF-IDF + cosine similarity."""

from __future__ import annotations

import os
from pathlib import Path
from typing import NamedTuple

import numpy as np
import pandas as pd
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.neighbors import NearestNeighbors
from collections import Counter


class NeighborEntry(NamedTuple):
    title: str
    domain: str


class KnnClassifier:
    """TF-IDF + cosine k-NN classifier (k=5) for ticket triage.

    * ``predict``  – majority-vote domain among 5 nearest neighbours.
    * ``confidence`` – fraction of the 5 votes belonging to the winner (e.g. 4/5 → 0.8).
    * ``neighbors`` – returns the 5 nearest ticket titles with their domains.
    """

    K = 5

    def __init__(self) -> None:
        self._vectorizer: TfidfVectorizer | None = None
        self._knn: NearestNeighbors | None = None
        self._train_titles: list[str] = []
        self._train_labels: list[str] = []
        self._X_train: np.ndarray | None = None  # sparse or dense TF-IDF matrix

    # ------------------------------------------------------------------
    # Training
    # ------------------------------------------------------------------

    def fit(self, csv_path: str | os.PathLike) -> None:
        """Train on *csv_path* (must have columns: title, description, domain)."""
        df = pd.read_csv(csv_path)
        texts = (df["title"] + " " + df["description"]).tolist()
        self._train_titles = df["title"].tolist()
        self._train_labels = df["domain"].tolist()

        self._vectorizer = TfidfVectorizer(
            ngram_range=(1, 2),
            lowercase=True,
            stop_words="english",
        )
        self._X_train = self._vectorizer.fit_transform(texts)

        self._knn = NearestNeighbors(
            n_neighbors=self.K,
            metric="cosine",
            algorithm="brute",
        )
        self._knn.fit(self._X_train)

    # ------------------------------------------------------------------
    # Internal helper
    # ------------------------------------------------------------------

    def _query(self, title: str, description: str) -> list[int]:
        """Return indices of K nearest training samples."""
        if self._vectorizer is None or self._knn is None:
            raise RuntimeError("Model has not been trained. Call fit() first.")
        text = title + " " + description
        vec = self._vectorizer.transform([text])
        _, indices = self._knn.kneighbors(vec, n_neighbors=self.K)
        return list(indices[0])

    # ------------------------------------------------------------------
    # Inference
    # ------------------------------------------------------------------

    def predict(self, title: str, description: str) -> str:
        """Return the majority-vote domain among 5 nearest neighbours."""
        indices = self._query(title, description)
        votes = [self._train_labels[i] for i in indices]
        return Counter(votes).most_common(1)[0][0]

    def confidence(self, title: str, description: str) -> float:
        """Return the winning fraction of the vote (e.g. 4/5 agree → 0.8)."""
        indices = self._query(title, description)
        votes = [self._train_labels[i] for i in indices]
        winner_count = Counter(votes).most_common(1)[0][1]
        return winner_count / self.K

    def neighbors(self, title: str, description: str) -> list[NeighborEntry]:
        """Return the 5 nearest ticket titles with their domains."""
        indices = self._query(title, description)
        return [
            NeighborEntry(title=self._train_titles[i], domain=self._train_labels[i])
            for i in indices
        ]
