"""Tests for SvmClassifier and KnnClassifier."""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

import pytest

from triagegate.classifier.svm import SvmClassifier
from triagegate.classifier.knn import KnnClassifier

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

_DATA_DIR = Path(__file__).resolve().parents[1] / "data"
TRAIN_CSV = str(_DATA_DIR / "tickets.csv")

# ---------------------------------------------------------------------------
# Clear-signal tickets per domain
# ---------------------------------------------------------------------------

CLEAR_TICKETS = {
    "api": (
        "REST endpoint returns 500 on POST /users",
        "The API route /api/v2/users returns an HTTP 500 status code "
        "when the request payload contains a null field. Curl reproduces it.",
    ),
    "database": (
        "Slow query causing deadlock in Postgres",
        "A database migration left a missing index on the transactions table. "
        "The connection pool is exhausted and we are seeing row lock contention "
        "in the SQL query logs.",
    ),
    "frontend": (
        "React component fails to render after CSS update",
        "The UI button in the modal is missing its style after a CSS change. "
        "The browser console shows an undefined variable in the DOM handler "
        "and the layout is broken on the page.",
    ),
    "auth": (
        "JWT token rejected – 401 Unauthorized after login",
        "After a successful login the session token is issued but every "
        "subsequent request returns 401. OAuth flow seems fine; the JWT "
        "credential is present. Possibly a permission / authorization issue.",
    ),
    "build": (
        "Docker image fails to compile in CI pipeline",
        "The build step in the CD pipeline errors out when webpack tries to "
        "bundle the npm package. The Gradle dependency cannot be resolved and "
        "the container artifact is never produced.",
    ),
}

# Ambiguous ticket that mixes api + database vocabulary
_AMBIGUOUS = (
    "API endpoint with slow database query",
    "The REST endpoint /api/orders sends a SQL query that scans the full "
    "table. The response is slow but the status code is 200. The database "
    "connection pool may also be involved.",
)

# Clear api ticket (high-confidence)
_CLEAR_API = CLEAR_TICKETS["api"]

VALID_DOMAINS = set(CLEAR_TICKETS.keys())


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def svm() -> SvmClassifier:
    clf = SvmClassifier()
    clf.fit(TRAIN_CSV)
    return clf


@pytest.fixture(scope="module")
def knn() -> KnnClassifier:
    clf = KnnClassifier()
    clf.fit(TRAIN_CSV)
    return clf


# ===========================================================================
# SvmClassifier tests
# ===========================================================================

class TestSvmTrain:
    def test_trains_without_error(self, svm: SvmClassifier) -> None:
        assert svm._pipeline is not None

    def test_classes_are_all_five_domains(self, svm: SvmClassifier) -> None:
        assert set(svm._classes) == VALID_DOMAINS


class TestSvmPredict:
    @pytest.mark.parametrize("domain", list(CLEAR_TICKETS))
    def test_predicts_correct_domain(self, svm: SvmClassifier, domain: str) -> None:
        title, desc = CLEAR_TICKETS[domain]
        pred = svm.predict(title, desc)
        assert pred == domain, f"Expected '{domain}', got '{pred}'"

    @pytest.mark.parametrize("domain", list(CLEAR_TICKETS))
    def test_predict_returns_valid_domain(self, svm: SvmClassifier, domain: str) -> None:
        title, desc = CLEAR_TICKETS[domain]
        assert svm.predict(title, desc) in VALID_DOMAINS


class TestSvmConfidence:
    def test_confidence_is_in_range(self, svm: SvmClassifier) -> None:
        title, desc = _CLEAR_API
        c = svm.confidence(title, desc)
        assert 0.0 <= c <= 1.0

    def test_clear_api_higher_confidence_than_ambiguous(self, svm: SvmClassifier) -> None:
        clear_conf = svm.confidence(*_CLEAR_API)
        ambiguous_conf = svm.confidence(*_AMBIGUOUS)
        assert clear_conf > ambiguous_conf, (
            f"Expected clear ({clear_conf:.4f}) > ambiguous ({ambiguous_conf:.4f})"
        )


class TestSvmSaveLoad:
    def test_save_load_roundtrip_preserves_predictions(self, svm: SvmClassifier) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            model_path = os.path.join(tmpdir, "svm_test.joblib")
            svm.save(model_path)

            loaded = SvmClassifier()
            loaded.load(model_path)

            for domain, (title, desc) in CLEAR_TICKETS.items():
                assert loaded.predict(title, desc) == svm.predict(title, desc), (
                    f"Prediction mismatch after load for domain '{domain}'"
                )

    def test_save_default_path(self, svm: SvmClassifier) -> None:
        # Just verify it saves without error; cleanup is handled by temp logic.
        from triagegate.classifier.svm import _DEFAULT_MODEL_PATH
        svm.save()
        assert _DEFAULT_MODEL_PATH.exists()


# ===========================================================================
# KnnClassifier tests
# ===========================================================================

class TestKnnTrain:
    def test_trains_without_error(self, knn: KnnClassifier) -> None:
        assert knn._knn is not None

    def test_train_labels_contain_all_domains(self, knn: KnnClassifier) -> None:
        assert set(knn._train_labels) == VALID_DOMAINS


class TestKnnPredict:
    @pytest.mark.parametrize("domain", list(CLEAR_TICKETS))
    def test_predicts_correct_domain(self, knn: KnnClassifier, domain: str) -> None:
        title, desc = CLEAR_TICKETS[domain]
        pred = knn.predict(title, desc)
        assert pred == domain, f"Expected '{domain}', got '{pred}'"

    @pytest.mark.parametrize("domain", list(CLEAR_TICKETS))
    def test_predict_returns_valid_domain(self, knn: KnnClassifier, domain: str) -> None:
        title, desc = CLEAR_TICKETS[domain]
        assert knn.predict(title, desc) in VALID_DOMAINS


class TestKnnConfidence:
    def test_confidence_is_fraction_of_five(self, knn: KnnClassifier) -> None:
        title, desc = _CLEAR_API
        c = knn.confidence(title, desc)
        # Must be one of 1/5, 2/5, 3/5, 4/5, 5/5
        assert c in {k / 5 for k in range(1, 6)}

    def test_confidence_in_range(self, knn: KnnClassifier) -> None:
        for title, desc in CLEAR_TICKETS.values():
            c = knn.confidence(title, desc)
            assert 0.0 < c <= 1.0


class TestKnnNeighbors:
    def test_returns_five_entries(self, knn: KnnClassifier) -> None:
        title, desc = _CLEAR_API
        nbrs = knn.neighbors(title, desc)
        assert len(nbrs) == 5

    def test_all_neighbor_domains_are_valid(self, knn: KnnClassifier) -> None:
        title, desc = _CLEAR_API
        nbrs = knn.neighbors(title, desc)
        for entry in nbrs:
            assert entry.domain in VALID_DOMAINS

    def test_neighbor_entries_have_titles(self, knn: KnnClassifier) -> None:
        title, desc = _CLEAR_API
        nbrs = knn.neighbors(title, desc)
        for entry in nbrs:
            assert isinstance(entry.title, str)
            assert len(entry.title) > 0

    @pytest.mark.parametrize("domain", list(CLEAR_TICKETS))
    def test_neighbors_predominantly_correct_domain(
        self, knn: KnnClassifier, domain: str
    ) -> None:
        title, desc = CLEAR_TICKETS[domain]
        nbrs = knn.neighbors(title, desc)
        domain_counts = {}
        for entry in nbrs:
            domain_counts[entry.domain] = domain_counts.get(entry.domain, 0) + 1
        top_domain = max(domain_counts, key=lambda d: domain_counts[d])
        assert top_domain == domain, (
            f"Top neighbor domain '{top_domain}' != expected '{domain}'"
        )
