"""Tests for AREA 1-4:
- generate_tickets.py incident history generation
- RiskClassifier train/predict/confidence/save/load
- LadderResult fields: predicted_risk, predicted_risk_confidence, similar_incidents
- Existing behaviour unchanged when risk model / history absent
"""
from __future__ import annotations

import csv
import os
import sys
import tempfile
from pathlib import Path

import pytest

# Make the scripts directory importable without installation.
SCRIPTS_DIR = Path(__file__).parent.parent / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

from generate_tickets import (  # noqa: E402
    _compute_risk,
    _HIGH_RISK_KEYWORDS,
    generate,
    generate_incident_history,
    write_csv,
    write_incident_history_csv,
)

from triagegate.classifier.risk import RiskClassifier  # noqa: E402
from triagegate.models.ticket import IncidentSummary, LadderResult, Ticket  # noqa: E402
from triagegate.pipeline.resolver import Resolver  # noqa: E402

# ---------------------------------------------------------------------------
# Shared test data
# ---------------------------------------------------------------------------

_DATA_DIR = Path(__file__).resolve().parents[1] / "data"
TRAIN_CSV = _DATA_DIR / "tickets.csv"
EVAL_CSV = _DATA_DIR / "eval_tickets.csv"
HISTORY_CSV = _DATA_DIR / "incident_history.csv"

DOMAINS = ["api", "database", "frontend", "auth", "build"]

HISTORY_COLUMNS = {"id", "files_changed", "risk_level", "impact", "tests_after", "verdict"}

_TRAIN_ROWS = generate(n_per_domain=40, seed=42)
_EVAL_ROWS = generate(n_per_domain=10, seed=99)
_ALL_ROWS = _TRAIN_ROWS + _EVAL_ROWS


def _history_rows() -> list[dict]:
    return generate_incident_history(_ALL_ROWS, seed=7)


def _csv_rows(path: Path) -> list[dict]:
    with path.open(newline="", encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


# ===========================================================================
# AREA 1 — Incident history generation
# ===========================================================================

class TestIncidentHistoryInMemory:
    """generate_incident_history() in-memory correctness."""

    def test_same_count_as_tickets(self):
        history = _history_rows()
        assert len(history) == len(_ALL_ROWS)

    def test_ids_match_tickets(self):
        history = _history_rows()
        ticket_ids = {r["id"] for r in _ALL_ROWS}
        history_ids = {r["id"] for r in history}
        assert history_ids == ticket_ids

    def test_required_fields_present(self):
        history = _history_rows()
        for row in history:
            assert set(row.keys()) >= HISTORY_COLUMNS, f"Missing fields in {row}"

    def test_no_empty_fields(self):
        history = _history_rows()
        for row in history:
            for col in HISTORY_COLUMNS:
                assert row[col], f"Empty value for '{col}' in row {row}"

    def test_risk_level_valid_values(self):
        history = _history_rows()
        for row in history:
            assert row["risk_level"] in {"high", "low"}, f"Invalid risk_level: {row['risk_level']}"

    def test_tests_after_always_all_passed(self):
        history = _history_rows()
        for row in history:
            assert row["tests_after"] == "all passed"

    def test_verdict_always_fix_verified(self):
        history = _history_rows()
        for row in history:
            assert row["verdict"] == "fix_verified"

    def test_files_changed_non_empty(self):
        history = _history_rows()
        for row in history:
            assert row["files_changed"].strip(), f"Empty files_changed in {row}"

    def test_files_changed_plausible_paths(self):
        """Each entry in files_changed should look like a file path (contains '/')."""
        history = _history_rows()
        for row in history:
            for fpath in row["files_changed"].split(","):
                assert "/" in fpath.strip(), f"Not a plausible path: '{fpath}'"

    def test_deterministic_under_same_seed(self):
        h1 = generate_incident_history(_ALL_ROWS, seed=7)
        h2 = generate_incident_history(_ALL_ROWS, seed=7)
        assert h1 == h2

    def test_different_seeds_differ(self):
        h1 = generate_incident_history(_ALL_ROWS, seed=7)
        h2 = generate_incident_history(_ALL_ROWS, seed=99)
        assert h1 != h2

    def test_both_datasets_covered(self):
        """Incident history covers both train (seed=42) and eval (seed=99) tickets."""
        history = _history_rows()
        train_ids = {r["id"] for r in _TRAIN_ROWS}
        eval_ids = {r["id"] for r in _EVAL_ROWS}
        history_ids = {r["id"] for r in history}
        assert train_ids.issubset(history_ids)
        assert eval_ids.issubset(history_ids)


class TestRiskMapping:
    """_compute_risk() implements the documented keyword mapping."""

    def test_payment_path_is_high(self):
        assert _compute_risk(["app/payments.py"]) == "high"

    def test_auth_path_is_high(self):
        assert _compute_risk(["app/auth.py"]) == "high"

    def test_session_path_is_high(self):
        assert _compute_risk(["app/sessions.py"]) == "high"

    def test_login_path_is_high(self):
        assert _compute_risk(["app/views/login.py"]) == "high"

    def test_checkout_path_is_high(self):
        assert _compute_risk(["app/checkout.py"]) == "high"

    def test_billing_path_is_high(self):
        assert _compute_risk(["app/billing.py"]) == "high"

    def test_neutral_path_is_low(self):
        assert _compute_risk(["app/orders.py"]) == "low"

    def test_neutral_db_path_is_low(self):
        assert _compute_risk(["app/db.py"]) == "low"

    def test_pipeline_path_is_low(self):
        assert _compute_risk(["ci/pipeline.py"]) == "low"

    def test_two_low_paths_stay_low(self):
        assert _compute_risk(["app/db.py", "app/orders.py"]) == "low"

    def test_one_high_one_low_returns_high(self):
        assert _compute_risk(["app/orders.py", "app/payments.py"]) == "high"

    def test_high_keywords_set_is_documented(self):
        """The exported set of keywords must contain all six documented keywords."""
        expected = {"payment", "auth", "session", "login", "checkout", "billing"}
        assert expected == _HIGH_RISK_KEYWORDS

    def test_auth_domain_produces_high_risk(self):
        """Auth domain file candidates include high-risk paths — at least most rows are high."""
        # Use only the train set (seed=42) whose IDs are T-0001..T-0200, no overlap.
        train_rows = generate(n_per_domain=40, seed=42)
        auth_train_ids = {r["id"] for r in train_rows if r["domain"] == "auth"}
        history = generate_incident_history(train_rows, seed=7)
        auth_rows = [r for r in history if r["id"] in auth_train_ids]
        # Auth candidates include sessions.py, auth.py, login.py, auth_tokens.py (all high)
        # and permissions.py (low). At least some rows must be high.
        high_rows = [r for r in auth_rows if r["risk_level"] == "high"]
        assert len(high_rows) > 0, "Expected some high-risk auth rows"
        # The majority (>= 50%) should be high, because 4/5 candidates are high-risk.
        assert len(high_rows) / len(auth_rows) >= 0.5, (
            f"Expected majority high-risk auth rows, got {len(high_rows)}/{len(auth_rows)}"
        )

    def test_build_domain_produces_only_low_risk(self):
        """Build domain file candidates are all low-risk."""
        # Use only the train set to avoid ID collisions between train and eval.
        train_rows = generate(n_per_domain=40, seed=42)
        build_ids = {r["id"] for r in train_rows if r["domain"] == "build"}
        history = generate_incident_history(train_rows, seed=7)
        build_rows = [r for r in history if r["id"] in build_ids]
        for row in build_rows:
            assert row["risk_level"] == "low", f"Build ticket has unexpected risk: {row}"


class TestWriteIncidentHistoryCSV:
    def test_writes_correct_columns(self, tmp_path):
        rows = _history_rows()
        out = tmp_path / "incident_history.csv"
        write_incident_history_csv(rows, out)
        written = _csv_rows(out)
        assert set(written[0].keys()) == HISTORY_COLUMNS

    def test_writes_correct_row_count(self, tmp_path):
        rows = _history_rows()
        out = tmp_path / "incident_history.csv"
        write_incident_history_csv(rows, out)
        written = _csv_rows(out)
        assert len(written) == len(rows)

    def test_roundtrip_preserves_id(self, tmp_path):
        rows = _history_rows()
        out = tmp_path / "incident_history.csv"
        write_incident_history_csv(rows, out)
        written = _csv_rows(out)
        assert written[0]["id"] == rows[0]["id"]


# ===========================================================================
# AREA 2 — RiskClassifier
# ===========================================================================

@pytest.fixture(scope="module")
def risk_clf(tmp_path_factory) -> RiskClassifier:
    """RiskClassifier trained on data/tickets.csv + data/incident_history.csv."""
    clf = RiskClassifier()
    clf.fit(TRAIN_CSV, HISTORY_CSV, extra_tickets_csv=EVAL_CSV)
    return clf


@pytest.fixture(scope="module")
def risk_clf_tmp(tmp_path_factory):
    """RiskClassifier trained in tmp dir (for save/load roundtrip)."""
    tmp = tmp_path_factory.mktemp("risk")
    tickets = tmp / "tickets.csv"
    history = tmp / "history.csv"

    write_csv(_TRAIN_ROWS + _EVAL_ROWS, tickets)
    rows = generate_incident_history(_TRAIN_ROWS + _EVAL_ROWS, seed=7)
    write_incident_history_csv(rows, history)

    clf = RiskClassifier()
    clf.fit(tickets, history)
    return clf, tmp


class TestRiskClassifierTrain:
    def test_trains_without_error(self, risk_clf: RiskClassifier):
        assert risk_clf._pipeline is not None

    def test_classes_are_high_and_low(self, risk_clf: RiskClassifier):
        assert set(risk_clf._classes) == {"high", "low"}

    def test_pipeline_not_none_after_fit(self, risk_clf: RiskClassifier):
        assert risk_clf._pipeline is not None


class TestRiskClassifierPredict:
    def test_predict_returns_high_or_low(self, risk_clf: RiskClassifier):
        result = risk_clf.predict("Payment timeout", "POST /payments keeps failing")
        assert result in {"high", "low"}

    def test_payment_ticket_predicts_high(self, risk_clf: RiskClassifier):
        # Use a strongly payment-and-session-laden description to ensure high prediction.
        result = risk_clf.predict(
            "Session invalidated after payment checkout failure",
            "Users are logged out after attempting payment at checkout. "
            "The payment service billing endpoint triggers a session invalidation. "
            "Auth tokens are revoked unexpectedly on POST /payments after billing upgrade."
        )
        assert result == "high"

    def test_build_ticket_predicts_low(self, risk_clf: RiskClassifier):
        result = risk_clf.predict(
            "Docker build fails in CI pipeline",
            "The GitHub Actions workflow exits with code 137 during the npm build step."
        )
        assert result == "low"

    def test_auth_ticket_predicts_high(self, risk_clf: RiskClassifier):
        result = risk_clf.predict(
            "Session token expires on login",
            "After authenticating via SSO the session cookie is invalidated immediately."
        )
        assert result == "high"

    def test_predict_raises_before_fit(self):
        clf = RiskClassifier()
        with pytest.raises(RuntimeError, match="fit"):
            clf.predict("title", "description")


class TestRiskClassifierConfidence:
    def test_confidence_in_range(self, risk_clf: RiskClassifier):
        c = risk_clf.confidence("Payment fails on checkout", "POST /payments returns 500")
        assert 0.0 <= c <= 1.0

    def test_confidence_raises_before_fit(self):
        clf = RiskClassifier()
        with pytest.raises(RuntimeError, match="fit"):
            clf.confidence("title", "description")

    def test_confidence_is_float(self, risk_clf: RiskClassifier):
        c = risk_clf.confidence("Docker build crash", "CI pipeline OOM exit 137")
        assert isinstance(c, float)


class TestRiskClassifierSaveLoad:
    def test_save_load_roundtrip_preserves_prediction(self, tmp_path):
        clf = RiskClassifier()
        clf.fit(TRAIN_CSV, HISTORY_CSV, extra_tickets_csv=EVAL_CSV)
        model_path = tmp_path / "risk_test.joblib"
        clf.save(model_path)

        loaded = RiskClassifier()
        loaded.load(model_path)

        for title, desc in [
            ("Payment checkout fails", "POST /payments returns 500 in production"),
            ("Docker build OOM", "GitHub Actions exits with code 137 in npm step"),
        ]:
            assert clf.predict(title, desc) == loaded.predict(title, desc)

    def test_save_creates_file(self, tmp_path):
        clf = RiskClassifier()
        clf.fit(TRAIN_CSV, HISTORY_CSV, extra_tickets_csv=EVAL_CSV)
        model_path = tmp_path / "risk_save_test.joblib"
        clf.save(model_path)
        assert model_path.exists()

    def test_load_raises_on_missing_file(self, tmp_path):
        clf = RiskClassifier()
        with pytest.raises(Exception):
            clf.load(tmp_path / "nonexistent.joblib")


# ===========================================================================
# AREA 3 — LadderResult carries predicted_risk and similar_incidents
# ===========================================================================

@pytest.fixture(scope="module")
def resolver_with_risk() -> Resolver:
    """Resolver that has risk model + history loaded (using real data/artifacts)."""
    return Resolver()


@pytest.fixture(scope="module")
def resolver_no_risk(tmp_path_factory) -> Resolver:
    """Resolver with no risk model and no history (missing artifacts)."""
    tmp = tmp_path_factory.mktemp("no_risk")
    return Resolver(
        risk_model_path=str(tmp / "nonexistent_risk.joblib"),
        history_csv_path=str(tmp / "nonexistent_history.csv"),
    )


_CLEAR_API_TICKET = Ticket(
    id="T-test-api",
    title="POST /orders returns 503 only in production",
    description=(
        "The search-service endpoint POST /products started returning HTTP 502 "
        "since last release. Logs show an unhandled exception in the request "
        "handler. Rolling back the last deployment temporarily fixes it."
    ),
)

_CLEAR_AUTH_TICKET = Ticket(
    id="T-test-auth",
    title="SSO refresh token rotation broken on payment-service",
    description=(
        "Refresh token rotation in reporting-service issues a new token but also "
        "invalidates valid sessions on logout. Users are being signed out "
        "unexpectedly. Confirmed after last SSO library upgrade."
    ),
)


class TestLadderResultRiskFields:
    def test_predicted_risk_present_when_model_loaded(self, resolver_with_risk: Resolver):
        """When risk model is available, predicted_risk is 'high' or 'low'."""
        result = resolver_with_risk.resolve(_CLEAR_API_TICKET)
        assert result.predicted_risk in {"high", "low"}

    def test_predicted_risk_confidence_present_when_model_loaded(self, resolver_with_risk: Resolver):
        result = resolver_with_risk.resolve(_CLEAR_API_TICKET)
        assert result.predicted_risk_confidence is not None
        assert 0.0 <= result.predicted_risk_confidence <= 1.0

    def test_auth_ticket_risk_is_high(self, resolver_with_risk: Resolver):
        """Auth/session-related tickets should be predicted as high risk."""
        result = resolver_with_risk.resolve(_CLEAR_AUTH_TICKET)
        assert result.predicted_risk == "high"

    def test_predicted_risk_none_without_model(self, resolver_no_risk: Resolver):
        """When risk model file is absent, predicted_risk is None."""
        result = resolver_no_risk.resolve(_CLEAR_API_TICKET)
        assert result.predicted_risk is None

    def test_predicted_risk_confidence_none_without_model(self, resolver_no_risk: Resolver):
        result = resolver_no_risk.resolve(_CLEAR_API_TICKET)
        assert result.predicted_risk_confidence is None

    def test_predicted_risk_is_string_when_set(self, resolver_with_risk: Resolver):
        result = resolver_with_risk.resolve(_CLEAR_API_TICKET)
        if result.predicted_risk is not None:
            assert isinstance(result.predicted_risk, str)

    def test_ladder_result_is_pydantic(self, resolver_with_risk: Resolver):
        result = resolver_with_risk.resolve(_CLEAR_API_TICKET)
        assert isinstance(result, LadderResult)


class TestLadderResultSimilarIncidents:
    def test_similar_incidents_is_list(self, resolver_with_risk: Resolver):
        result = resolver_with_risk.resolve(_CLEAR_API_TICKET)
        assert isinstance(result.similar_incidents, list)

    def test_similar_incidents_max_five(self, resolver_with_risk: Resolver):
        result = resolver_with_risk.resolve(_CLEAR_API_TICKET)
        assert len(result.similar_incidents) <= 5

    def test_similar_incidents_have_required_fields(self, resolver_with_risk: Resolver):
        result = resolver_with_risk.resolve(_CLEAR_API_TICKET)
        for inc in result.similar_incidents:
            assert isinstance(inc, IncidentSummary)
            assert inc.id
            assert inc.title
            assert inc.domain
            assert inc.risk_level in {"high", "low"}
            assert inc.impact
            assert inc.verdict

    def test_similar_incidents_empty_without_history(self, resolver_no_risk: Resolver):
        result = resolver_no_risk.resolve(_CLEAR_API_TICKET)
        assert result.similar_incidents == []

    def test_similar_incidents_non_empty_with_history(self, resolver_with_risk: Resolver):
        result = resolver_with_risk.resolve(_CLEAR_API_TICKET)
        # With real history loaded there should be at least 1 similar incident
        assert len(result.similar_incidents) >= 1

    def test_similar_incidents_ids_are_valid_ticket_ids(self, resolver_with_risk: Resolver):
        """All returned incident ids should look like T-NNNN."""
        result = resolver_with_risk.resolve(_CLEAR_API_TICKET)
        for inc in result.similar_incidents:
            assert inc.id.startswith("T-"), f"Unexpected id format: {inc.id}"


# ===========================================================================
# AREA 4 — Existing behaviour unchanged when fields unused
# ===========================================================================

class TestExistingBehaviourPreserved:
    def test_domain_still_populated(self, resolver_with_risk: Resolver):
        result = resolver_with_risk.resolve(_CLEAR_API_TICKET)
        assert result.domain in {"api", "database", "frontend", "auth", "build", "escalated"}

    def test_voters_still_present(self, resolver_with_risk: Resolver):
        result = resolver_with_risk.resolve(_CLEAR_API_TICKET)
        voter_names = {v.voter for v in result.voters}
        assert {"svm", "knn", "scorer"}.issubset(voter_names)

    def test_elapsed_ms_still_present(self, resolver_with_risk: Resolver):
        result = resolver_with_risk.resolve(_CLEAR_API_TICKET)
        assert result.elapsed_ms >= 0

    def test_evidence_still_present(self, resolver_with_risk: Resolver):
        result = resolver_with_risk.resolve(_CLEAR_API_TICKET)
        assert isinstance(result.evidence, list)

    def test_ladder_result_serialises(self, resolver_with_risk: Resolver):
        """LadderResult.model_dump() succeeds even with new optional fields."""
        result = resolver_with_risk.resolve(_CLEAR_API_TICKET)
        d = result.model_dump()
        assert "predicted_risk" in d
        assert "predicted_risk_confidence" in d
        assert "similar_incidents" in d

    def test_no_risk_resolver_still_resolves_correctly(self, resolver_no_risk: Resolver):
        """Resolver without risk model still classifies domains correctly."""
        result = resolver_no_risk.resolve(_CLEAR_API_TICKET)
        assert result.domain in {"api", "database", "frontend", "auth", "build", "escalated"}
        assert result.resolved_by in {"svm_gate", "voter_agreement", "granite_tiebreak", "escalate"}

    def test_similar_incidents_field_is_always_list(self, resolver_no_risk: Resolver):
        """similar_incidents defaults to [] even when history is absent."""
        result = resolver_no_risk.resolve(_CLEAR_API_TICKET)
        assert isinstance(result.similar_incidents, list)
