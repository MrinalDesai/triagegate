"""Tests for the escalation tier: EscalationReport, EscalationStore, and endpoints."""
from __future__ import annotations

import json
import tempfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from triagegate.escalation.bob_tier import EscalationReport, EscalationStore
from triagegate.web.server import app

client = TestClient(app)

# ---------------------------------------------------------------------------
# Fixture helpers
# ---------------------------------------------------------------------------

# A minimal COMPLETED, LOW-risk report (the "normal" happy path for tests that
# just need a valid storable report).
MINIMAL_REPORT = {
    "ticket_id": "T-ESC-001",
    "root_cause": "Off-by-one in payment loop",
    "files_examined": ["app/payments.py", "app/orders.py"],
    "patch_summary": "Changed <= to < on line 42 of payments.py",
    "diff": "--- a/app/payments.py\n+++ b/app/payments.py\n@@ -42 +42 @@\n-    for i in range(0, n+1):\n+    for i in range(0, n):\n",
    "tests_before": "32 passed 1 failed",
    "tests_after": "33 passed",
    "verdict": "fix_verified",
    "status": "completed",
    "risk_level": "low",
    "auto_applied": True,
    "files_changed": ["app/orders.py"],
    "impact": "Off-by-one caused duplicate charges for ~100 users per day.",
}

# A pending_approval HIGH-risk proposal (no tests_after, no verdict)
PENDING_HIGH_REPORT = {
    "ticket_id": "T-ESC-001",
    "root_cause": "Off-by-one in payment loop",
    "files_examined": ["app/payments.py"],
    "patch_summary": "Risk: HIGH — modifies app/payments.py",
    "diff": "--- a/app/payments.py\n+++ b/app/payments.py\n@@ -42 +42 @@\n-    for i in range(0, n+1):\n+    for i in range(0, n):\n",
    "tests_before": "32 passed 1 failed",
    "status": "pending_approval",
    "risk_level": "high",
    "auto_applied": False,
}

# A completed HIGH-risk report (posted after approval)
COMPLETED_HIGH_REPORT = {
    "ticket_id": "T-ESC-001",
    "root_cause": "Off-by-one in payment loop",
    "files_examined": ["app/payments.py"],
    "patch_summary": "Risk: HIGH — modifies app/payments.py",
    "diff": "--- a/app/payments.py\n+++ b/app/payments.py\n@@ -42 +42 @@\n-    for i in range(0, n+1):\n+    for i in range(0, n):\n",
    "tests_before": "32 passed 1 failed",
    "tests_after": "33 passed",
    "verdict": "fix_verified",
    "status": "completed",
    "risk_level": "high",
    "auto_applied": False,
    "files_changed": ["app/payments.py"],
    "impact": "Off-by-one caused duplicate charges.",
}


def _make_report(**overrides) -> EscalationReport:
    data = {**MINIMAL_REPORT, **overrides}
    return EscalationReport(**data)


def _make_pending(**overrides) -> EscalationReport:
    data = {**PENDING_HIGH_REPORT, **overrides}
    return EscalationReport(**data)


# ---------------------------------------------------------------------------
# EscalationReport model tests
# ---------------------------------------------------------------------------

class TestEscalationReportModel:
    def test_valid_report_roundtrip(self):
        report = _make_report()
        assert report.ticket_id == "T-ESC-001"
        assert report.verdict == "fix_verified"

    def test_serialise_and_deserialise(self):
        report = _make_report()
        raw = report.model_dump_json()
        restored = EscalationReport.model_validate_json(raw)
        assert restored == report

    def test_verdict_fix_failed(self):
        report = _make_report(verdict="fix_failed", files_changed=[], impact=None)
        assert report.verdict == "fix_failed"

    def test_verdict_needs_human(self):
        report = _make_report(verdict="needs_human", files_changed=[], impact=None)
        assert report.verdict == "needs_human"

    def test_verdict_invalid_raises(self):
        with pytest.raises(ValidationError):
            _make_report(verdict="invalid_value")

    def test_verdict_empty_raises(self):
        with pytest.raises(ValidationError):
            _make_report(verdict="")

    def test_missing_ticket_id_raises(self):
        data = {k: v for k, v in MINIMAL_REPORT.items() if k != "ticket_id"}
        with pytest.raises(ValidationError):
            EscalationReport(**data)

    def test_files_examined_is_list(self):
        report = _make_report()
        assert isinstance(report.files_examined, list)

    def test_status_is_required(self):
        """status has no default — omitting it raises ValidationError."""
        data = {k: v for k, v in MINIMAL_REPORT.items() if k != "status"}
        with pytest.raises(ValidationError):
            EscalationReport(**data)


# ---------------------------------------------------------------------------
# EscalationStore tests
# ---------------------------------------------------------------------------

class TestEscalationStore:
    def test_save_and_load_roundtrip(self, tmp_path):
        store = EscalationStore(store_dir=tmp_path)
        report = _make_report()
        store.save(report)
        loaded = store.load("T-ESC-001")
        assert loaded == report

    def test_load_missing_returns_none(self, tmp_path):
        store = EscalationStore(store_dir=tmp_path)
        assert store.load("no-such-ticket") is None

    def test_exists_false_before_save(self, tmp_path):
        store = EscalationStore(store_dir=tmp_path)
        assert not store.exists("T-ESC-001")

    def test_exists_true_after_save(self, tmp_path):
        store = EscalationStore(store_dir=tmp_path)
        store.save(_make_report())
        assert store.exists("T-ESC-001")

    def test_overwrite_on_second_save(self, tmp_path):
        store = EscalationStore(store_dir=tmp_path)
        store.save(_make_report(verdict="fix_failed", files_changed=[], impact=None))
        store.save(_make_report(verdict="fix_verified"))
        assert store.load("T-ESC-001").verdict == "fix_verified"

    def test_store_dir_created_automatically(self, tmp_path):
        nested = tmp_path / "deep" / "nested" / "dir"
        store = EscalationStore(store_dir=nested)
        store.save(_make_report())
        assert nested.exists()

    def test_json_file_is_valid_json(self, tmp_path):
        store = EscalationStore(store_dir=tmp_path)
        store.save(_make_report())
        p = tmp_path / "T-ESC-001.json"
        data = json.loads(p.read_text())
        assert data["ticket_id"] == "T-ESC-001"


# ---------------------------------------------------------------------------
# API endpoint tests
# ---------------------------------------------------------------------------

class TestEscalationEndpoints:
    """Use a store backed by a temp directory so tests are fully isolated."""

    @pytest.fixture(autouse=True)
    def _patch_store_and_csv(self, tmp_path, monkeypatch):
        """Replace the module-level store with a fresh temp-backed one and redirect CSV."""
        import triagegate.web.server as server_module
        fresh_store = EscalationStore(store_dir=tmp_path)
        monkeypatch.setattr(server_module, "_escalation_store", fresh_store)
        csv_path = tmp_path / "incident_history.csv"
        monkeypatch.setattr(server_module, "_INCIDENT_HISTORY_CSV", csv_path)
        monkeypatch.setattr(server_module, "_incident_history_written", set())

    def test_get_missing_ticket_returns_404(self):
        response = client.get("/api/escalations/MISSING-999")
        assert response.status_code == 404

    def test_post_then_get_returns_200(self):
        response = client.post("/api/escalations/T-ESC-001/report", json=MINIMAL_REPORT)
        assert response.status_code == 201
        response = client.get("/api/escalations/T-ESC-001")
        assert response.status_code == 200

    def test_post_returns_saved_report(self):
        response = client.post("/api/escalations/T-ESC-001/report", json=MINIMAL_REPORT)
        assert response.status_code == 201
        data = response.json()
        assert data["ticket_id"] == "T-ESC-001"
        assert data["verdict"] == "fix_verified"

    def test_get_returns_correct_fields(self):
        client.post("/api/escalations/T-ESC-001/report", json=MINIMAL_REPORT)
        data = client.get("/api/escalations/T-ESC-001").json()
        for field in ("ticket_id", "root_cause", "files_examined", "patch_summary",
                      "diff", "tests_before", "tests_after", "verdict"):
            assert field in data, f"missing field: {field}"

    def test_ticket_id_mismatch_returns_422(self):
        payload = {**MINIMAL_REPORT, "ticket_id": "T-ESC-OTHER"}
        response = client.post("/api/escalations/T-ESC-001/report", json=payload)
        assert response.status_code == 422

    def test_invalid_verdict_returns_422(self):
        payload = {**MINIMAL_REPORT, "verdict": "totally_wrong"}
        response = client.post("/api/escalations/T-ESC-001/report", json=payload)
        assert response.status_code == 422

    def test_missing_field_returns_422(self):
        payload = {k: v for k, v in MINIMAL_REPORT.items() if k != "root_cause"}
        response = client.post("/api/escalations/T-ESC-001/report", json=payload)
        assert response.status_code == 422


# ---------------------------------------------------------------------------
# Risk-level model tests
# ---------------------------------------------------------------------------

class TestRiskLevel:
    """Validate risk_level / auto_applied / status model rules."""

    def test_low_risk_completed_auto_applied(self):
        report = _make_report()
        assert report.risk_level == "low"
        assert report.auto_applied is True
        assert report.status == "completed"

    def test_high_risk_pending_approval(self):
        report = _make_pending()
        assert report.risk_level == "high"
        assert report.auto_applied is False
        assert report.status == "pending_approval"

    def test_low_risk_auto_applied_true_accepted(self):
        report = _make_report(risk_level="low", auto_applied=True)
        assert report.auto_applied is True
        assert report.risk_level == "low"

    def test_high_risk_auto_applied_true_on_completed_rejected(self):
        """completed high-risk with auto_applied=True is invalid."""
        with pytest.raises(ValidationError):
            _make_report(risk_level="high", auto_applied=True, status="completed")

    def test_high_risk_auto_applied_false_completed_accepted(self):
        report = EscalationReport(**COMPLETED_HIGH_REPORT)
        assert report.risk_level == "high"
        assert report.auto_applied is False

    def test_invalid_risk_level_raises(self):
        with pytest.raises(ValidationError):
            _make_report(risk_level="medium")

    def test_risk_level_roundtrip_json_low(self):
        report = _make_report(risk_level="low", auto_applied=True)
        restored = EscalationReport.model_validate_json(report.model_dump_json())
        assert restored.risk_level == "low"
        assert restored.auto_applied is True

    def test_risk_level_roundtrip_json_high(self):
        report = EscalationReport(**COMPLETED_HIGH_REPORT)
        restored = EscalationReport.model_validate_json(report.model_dump_json())
        assert restored.risk_level == "high"
        assert restored.auto_applied is False

    def test_low_completed_without_auto_applied_rejected(self):
        """LOW completed without auto_applied=True must raise."""
        with pytest.raises(ValidationError):
            _make_report(risk_level="low", auto_applied=False, status="completed")

    def test_pending_low_risk_rejected_by_validator(self):
        """pending_approval with low risk must raise."""
        with pytest.raises(ValidationError):
            EscalationReport(
                ticket_id="T-X",
                root_cause="x",
                files_examined=[],
                patch_summary="x",
                diff="",
                tests_before="1 passed",
                status="pending_approval",
                risk_level="low",
                auto_applied=False,
            )

    def test_pending_with_verdict_rejected_by_validator(self):
        """pending_approval must not have verdict set."""
        with pytest.raises(ValidationError):
            EscalationReport(**{
                **PENDING_HIGH_REPORT,
                "verdict": "fix_verified",
            })

    def test_pending_with_tests_after_rejected_by_validator(self):
        """pending_approval must not have tests_after set."""
        with pytest.raises(ValidationError):
            EscalationReport(**{
                **PENDING_HIGH_REPORT,
                "tests_after": "33 passed",
            })

    def test_completed_fix_verified_without_files_changed_rejected(self):
        """completed fix_verified with empty files_changed must raise."""
        with pytest.raises(ValidationError):
            _make_report(files_changed=[], impact="some impact")

    def test_completed_fix_verified_without_impact_rejected(self):
        """completed fix_verified without impact must raise."""
        with pytest.raises(ValidationError):
            _make_report(impact=None)

    def test_completed_fix_failed_allows_empty_files_changed(self):
        """fix_failed does not require files_changed or impact."""
        report = _make_report(verdict="fix_failed", files_changed=[], impact=None)
        assert report.verdict == "fix_failed"


class TestRiskLevelStore:
    """risk_level and auto_applied survive store save/load roundtrip."""

    def test_low_auto_applied_roundtrip(self, tmp_path):
        store = EscalationStore(store_dir=tmp_path)
        report = _make_report(risk_level="low", auto_applied=True)
        store.save(report)
        loaded = store.load("T-ESC-001")
        assert loaded.risk_level == "low"
        assert loaded.auto_applied is True

    def test_high_no_auto_roundtrip(self, tmp_path):
        store = EscalationStore(store_dir=tmp_path)
        report = EscalationReport(**COMPLETED_HIGH_REPORT)
        store.save(report)
        loaded = store.load("T-ESC-001")
        assert loaded.risk_level == "high"
        assert loaded.auto_applied is False


# ---------------------------------------------------------------------------
# Status / RCA / code_before / code_after model tests
# ---------------------------------------------------------------------------

class TestApprovalFields:
    """status, root_cause_analysis, code_before, code_after, files_changed, impact."""

    def test_status_pending_approval_valid(self):
        report = _make_pending()
        assert report.status == "pending_approval"

    def test_status_approved_valid(self):
        # approved is an intermediate state — requires high risk, no verdict/tests_after
        report = _make_pending(status="approved")
        assert report.status == "approved"

    def test_status_rejected_valid(self):
        report = _make_pending(status="rejected")
        assert report.status == "rejected"

    def test_status_completed_valid(self):
        report = _make_report(status="completed")
        assert report.status == "completed"

    def test_status_invalid_raises(self):
        with pytest.raises(ValidationError):
            _make_report(status="unknown_state")

    def test_status_auto_applied_removed(self):
        """The old 'auto_applied' status literal no longer exists."""
        with pytest.raises(ValidationError):
            _make_report(status="auto_applied")

    def test_rca_default_empty(self):
        report = _make_report()
        assert report.root_cause_analysis == ""

    def test_rca_roundtrip(self):
        rca = "First paragraph.\n\nSecond paragraph."
        report = _make_report(root_cause_analysis=rca)
        restored = EscalationReport.model_validate_json(report.model_dump_json())
        assert restored.root_cause_analysis == rca

    def test_code_before_default_empty(self):
        report = _make_report()
        assert report.code_before == ""

    def test_code_after_default_empty(self):
        report = _make_report()
        assert report.code_after == ""

    def test_code_before_after_roundtrip(self):
        report = _make_report(code_before="def foo():\n    pass\n", code_after="def foo():\n    return 1\n")
        restored = EscalationReport.model_validate_json(report.model_dump_json())
        assert restored.code_before == "def foo():\n    pass\n"
        assert restored.code_after == "def foo():\n    return 1\n"

    def test_all_new_fields_in_json(self):
        report = _make_report(
            root_cause_analysis="RCA text",
            code_before="before",
            code_after="after",
            files_changed=["app/orders.py"],
            impact="Business impact sentence.",
        )
        data = json.loads(report.model_dump_json())
        assert data["status"] == "completed"
        assert data["root_cause_analysis"] == "RCA text"
        assert data["code_before"] == "before"
        assert data["code_after"] == "after"
        assert data["files_changed"] == ["app/orders.py"]
        assert data["impact"] == "Business impact sentence."

    def test_files_changed_default_empty_list(self):
        # For fix_failed/needs_human, files_changed can be empty
        report = _make_report(verdict="fix_failed", files_changed=[], impact=None)
        assert report.files_changed == []

    def test_impact_default_none(self):
        # fix_failed does not require impact
        report = _make_report(verdict="fix_failed", files_changed=[], impact=None)
        assert report.impact is None


# ---------------------------------------------------------------------------
# Risk-level endpoint tests
# ---------------------------------------------------------------------------

class TestRiskLevelEndpoints:
    """Risk fields flow through POST/GET endpoints correctly."""

    @pytest.fixture(autouse=True)
    def _patch_store_and_csv(self, tmp_path, monkeypatch):
        import triagegate.web.server as server_module
        fresh_store = EscalationStore(store_dir=tmp_path)
        monkeypatch.setattr(server_module, "_escalation_store", fresh_store)
        csv_path = tmp_path / "incident_history.csv"
        monkeypatch.setattr(server_module, "_INCIDENT_HISTORY_CSV", csv_path)
        monkeypatch.setattr(server_module, "_incident_history_written", set())

    def test_post_low_risk_completed_returns_201(self):
        payload = {**MINIMAL_REPORT, "risk_level": "low", "auto_applied": True, "status": "completed"}
        resp = client.post("/api/escalations/T-ESC-001/report", json=payload)
        assert resp.status_code == 201
        data = resp.json()
        assert data["risk_level"] == "low"
        assert data["auto_applied"] is True

    def test_post_high_risk_auto_applied_returns_422(self):
        payload = {**MINIMAL_REPORT, "risk_level": "high", "auto_applied": True, "status": "completed"}
        resp = client.post("/api/escalations/T-ESC-001/report", json=payload)
        assert resp.status_code == 422

    def test_post_high_risk_pending_approval_returns_201(self):
        payload = {**PENDING_HIGH_REPORT}
        resp = client.post("/api/escalations/T-ESC-001/report", json=payload)
        assert resp.status_code == 201
        data = resp.json()
        assert data["risk_level"] == "high"
        assert data["auto_applied"] is False
        assert data["status"] == "pending_approval"

    def test_get_returns_risk_fields(self):
        payload = {**MINIMAL_REPORT, "risk_level": "low", "auto_applied": True, "status": "completed"}
        client.post("/api/escalations/T-ESC-001/report", json=payload)
        data = client.get("/api/escalations/T-ESC-001").json()
        assert data["risk_level"] == "low"
        assert data["auto_applied"] is True

    def test_risk_fields_in_response(self):
        resp = client.post("/api/escalations/T-ESC-001/report", json=MINIMAL_REPORT)
        assert resp.status_code == 201
        data = resp.json()
        assert "risk_level" in data
        assert "auto_applied" in data
        assert data["risk_level"] == "low"
        assert data["auto_applied"] is True


# ---------------------------------------------------------------------------
# Approve / reject endpoint tests
# ---------------------------------------------------------------------------

class TestApproveRejectEndpoints:
    """Approve and reject endpoints for escalation reports."""

    @pytest.fixture(autouse=True)
    def _patch_store_and_csv(self, tmp_path, monkeypatch):
        import triagegate.web.server as server_module
        fresh_store = EscalationStore(store_dir=tmp_path)
        monkeypatch.setattr(server_module, "_escalation_store", fresh_store)
        csv_path = tmp_path / "incident_history.csv"
        monkeypatch.setattr(server_module, "_INCIDENT_HISTORY_CSV", csv_path)
        monkeypatch.setattr(server_module, "_incident_history_written", set())
        self.csv_path = csv_path

    def test_approve_missing_ticket_returns_404(self):
        resp = client.post("/api/escalations/NOEXIST-999/approve")
        assert resp.status_code == 404

    def test_reject_missing_ticket_returns_404(self):
        resp = client.post("/api/escalations/NOEXIST-999/reject")
        assert resp.status_code == 404

    def test_approve_pending_sets_status_approved(self):
        client.post("/api/escalations/T-ESC-001/report", json=PENDING_HIGH_REPORT)
        resp = client.post("/api/escalations/T-ESC-001/approve")
        assert resp.status_code == 200
        assert resp.json()["status"] == "approved"

    def test_reject_pending_sets_status_rejected(self):
        client.post("/api/escalations/T-ESC-001/report", json=PENDING_HIGH_REPORT)
        resp = client.post("/api/escalations/T-ESC-001/reject")
        assert resp.status_code == 200
        assert resp.json()["status"] == "rejected"

    def test_approve_twice_returns_409(self):
        client.post("/api/escalations/T-ESC-001/report", json=PENDING_HIGH_REPORT)
        client.post("/api/escalations/T-ESC-001/approve")
        resp = client.post("/api/escalations/T-ESC-001/approve")
        assert resp.status_code == 409

    def test_reject_after_approve_returns_409(self):
        client.post("/api/escalations/T-ESC-001/report", json=PENDING_HIGH_REPORT)
        client.post("/api/escalations/T-ESC-001/approve")
        resp = client.post("/api/escalations/T-ESC-001/reject")
        assert resp.status_code == 409

    def test_get_after_approve_reflects_approved_status(self):
        client.post("/api/escalations/T-ESC-001/report", json=PENDING_HIGH_REPORT)
        client.post("/api/escalations/T-ESC-001/approve")
        data = client.get("/api/escalations/T-ESC-001").json()
        assert data["status"] == "approved"

    def test_get_after_reject_reflects_rejected_status(self):
        client.post("/api/escalations/T-ESC-001/report", json=PENDING_HIGH_REPORT)
        client.post("/api/escalations/T-ESC-001/reject")
        data = client.get("/api/escalations/T-ESC-001").json()
        assert data["status"] == "rejected"

    def test_approve_response_contains_status_field(self):
        client.post("/api/escalations/T-ESC-001/report", json=PENDING_HIGH_REPORT)
        resp = client.post("/api/escalations/T-ESC-001/approve")
        assert resp.status_code == 200
        assert "status" in resp.json()

    def test_new_fields_present_in_get_response(self):
        client.post("/api/escalations/T-ESC-001/report", json=MINIMAL_REPORT)
        data = client.get("/api/escalations/T-ESC-001").json()
        for field in ("status", "root_cause_analysis", "code_before", "code_after"):
            assert field in data, f"missing field: {field}"

    def test_approve_writes_no_history(self):
        """approve MUST NOT write incident history."""
        client.post("/api/escalations/T-ESC-001/report", json=PENDING_HIGH_REPORT)
        client.post("/api/escalations/T-ESC-001/approve")
        assert not self.csv_path.exists(), "approve should not write incident history"


# ---------------------------------------------------------------------------
# Transition matrix tests
# ---------------------------------------------------------------------------

class TestTransitionMatrix:
    """Each allowed transition succeeds; each forbidden transition returns 409."""

    @pytest.fixture(autouse=True)
    def _patch_store_and_csv(self, tmp_path, monkeypatch):
        import triagegate.web.server as server_module
        fresh_store = EscalationStore(store_dir=tmp_path)
        monkeypatch.setattr(server_module, "_escalation_store", fresh_store)
        csv_path = tmp_path / "incident_history.csv"
        monkeypatch.setattr(server_module, "_INCIDENT_HISTORY_CSV", csv_path)
        monkeypatch.setattr(server_module, "_incident_history_written", set())
        self.csv_path = csv_path

    # --- Allowed transitions ---

    def test_fresh_pending_high_allowed(self):
        resp = client.post("/api/escalations/T-NEW/report", json={**PENDING_HIGH_REPORT, "ticket_id": "T-NEW"})
        assert resp.status_code == 201

    def test_fresh_completed_low_allowed(self):
        resp = client.post("/api/escalations/T-NEW/report", json={**MINIMAL_REPORT, "ticket_id": "T-NEW"})
        assert resp.status_code == 201

    def test_pending_to_approved_allowed(self):
        client.post("/api/escalations/T-NEW/report", json={**PENDING_HIGH_REPORT, "ticket_id": "T-NEW"})
        resp = client.post("/api/escalations/T-NEW/approve")
        assert resp.status_code == 200

    def test_pending_to_rejected_allowed(self):
        client.post("/api/escalations/T-NEW/report", json={**PENDING_HIGH_REPORT, "ticket_id": "T-NEW"})
        resp = client.post("/api/escalations/T-NEW/reject")
        assert resp.status_code == 200

    def test_approved_to_completed_high_allowed(self):
        client.post("/api/escalations/T-NEW/report", json={**PENDING_HIGH_REPORT, "ticket_id": "T-NEW"})
        client.post("/api/escalations/T-NEW/approve")
        resp = client.post("/api/escalations/T-NEW/report", json={**COMPLETED_HIGH_REPORT, "ticket_id": "T-NEW"})
        assert resp.status_code == 201

    # --- Forbidden transitions ---

    def test_client_submitted_approved_rejected_409(self):
        """Client cannot POST status=approved directly — must use /approve endpoint."""
        payload = {**PENDING_HIGH_REPORT, "ticket_id": "T-NEW", "status": "approved"}
        resp = client.post("/api/escalations/T-NEW/report", json=payload)
        assert resp.status_code == 409

    def test_client_submitted_rejected_409(self):
        payload = {**PENDING_HIGH_REPORT, "ticket_id": "T-NEW", "status": "rejected"}
        resp = client.post("/api/escalations/T-NEW/report", json=payload)
        assert resp.status_code == 409

    def test_completed_repost_returns_409(self):
        """Reposting to a completed ticket is forbidden."""
        client.post("/api/escalations/T-NEW/report", json={**MINIMAL_REPORT, "ticket_id": "T-NEW"})
        resp = client.post("/api/escalations/T-NEW/report", json={**MINIMAL_REPORT, "ticket_id": "T-NEW"})
        assert resp.status_code == 409

    def test_rejected_any_transition_returns_409(self):
        """After rejected, any further report post is 409."""
        client.post("/api/escalations/T-NEW/report", json={**PENDING_HIGH_REPORT, "ticket_id": "T-NEW"})
        client.post("/api/escalations/T-NEW/reject")
        resp = client.post("/api/escalations/T-NEW/report", json={**PENDING_HIGH_REPORT, "ticket_id": "T-NEW"})
        assert resp.status_code == 409

    def test_approve_completed_returns_409(self):
        """Cannot approve a completed ticket."""
        client.post("/api/escalations/T-NEW/report", json={**MINIMAL_REPORT, "ticket_id": "T-NEW"})
        resp = client.post("/api/escalations/T-NEW/approve")
        assert resp.status_code == 409

    def test_reject_completed_returns_409(self):
        """Cannot reject a completed ticket."""
        client.post("/api/escalations/T-NEW/report", json={**MINIMAL_REPORT, "ticket_id": "T-NEW"})
        resp = client.post("/api/escalations/T-NEW/reject")
        assert resp.status_code == 409

    def test_pending_approval_repost_returns_409(self):
        """Reposting a new pending_approval when one already exists is forbidden."""
        client.post("/api/escalations/T-NEW/report", json={**PENDING_HIGH_REPORT, "ticket_id": "T-NEW"})
        resp = client.post("/api/escalations/T-NEW/report", json={**PENDING_HIGH_REPORT, "ticket_id": "T-NEW"})
        assert resp.status_code == 409

    def test_fresh_completed_high_without_approval_rejected_409(self):
        """Fresh completed HIGH without going through pending_approval/approve is forbidden."""
        resp = client.post("/api/escalations/T-NEW/report", json={**COMPLETED_HIGH_REPORT, "ticket_id": "T-NEW"})
        assert resp.status_code == 409


# ---------------------------------------------------------------------------
# Incident history CSV tests
# ---------------------------------------------------------------------------

class TestIncidentHistoryCSV:
    """Incident history is written only when a completed fix_verified report is stored."""

    @pytest.fixture(autouse=True)
    def _patch_store_and_csv(self, tmp_path, monkeypatch):
        import triagegate.web.server as server_module
        fresh_store = EscalationStore(store_dir=tmp_path)
        monkeypatch.setattr(server_module, "_escalation_store", fresh_store)
        # Redirect the history CSV to a temp file
        csv_path = tmp_path / "incident_history.csv"
        monkeypatch.setattr(server_module, "_INCIDENT_HISTORY_CSV", csv_path)
        monkeypatch.setattr(server_module, "_incident_history_written", set())
        self.csv_path = csv_path

    def test_completed_fix_verified_writes_one_row(self):
        client.post("/api/escalations/T-ESC-001/report", json=MINIMAL_REPORT)
        assert self.csv_path.exists()
        import csv as csv_mod
        rows = list(csv_mod.DictReader(self.csv_path.read_text(encoding="utf-8").splitlines()))
        assert len(rows) == 1
        assert rows[0]["id"] == "T-ESC-001"
        assert rows[0]["verdict"] == "fix_verified"
        assert rows[0]["risk_level"] == "low"

    def test_completed_fix_verified_generator_schema(self):
        """Written row matches the exact generator schema columns."""
        import csv as csv_mod
        client.post("/api/escalations/T-ESC-001/report", json=MINIMAL_REPORT)
        rows = list(csv_mod.DictReader(self.csv_path.read_text(encoding="utf-8").splitlines()))
        expected_cols = {"id", "files_changed", "risk_level", "impact", "tests_after", "verdict"}
        assert set(rows[0].keys()) == expected_cols

    def test_files_changed_serialised_as_comma_joined(self):
        """files_changed list is stored as ', '.join(...) in CSV."""
        import csv as csv_mod
        payload = {**MINIMAL_REPORT, "files_changed": ["app/a.py", "app/b.py"]}
        client.post("/api/escalations/T-ESC-001/report", json=payload)
        rows = list(csv_mod.DictReader(self.csv_path.read_text(encoding="utf-8").splitlines()))
        assert rows[0]["files_changed"] == "app/a.py, app/b.py"

    def test_tests_after_stored_in_csv(self):
        import csv as csv_mod
        client.post("/api/escalations/T-ESC-001/report", json=MINIMAL_REPORT)
        rows = list(csv_mod.DictReader(self.csv_path.read_text(encoding="utf-8").splitlines()))
        assert rows[0]["tests_after"] == MINIMAL_REPORT["tests_after"]

    def test_reject_does_not_write_csv(self):
        client.post("/api/escalations/T-ESC-001/report", json=PENDING_HIGH_REPORT)
        client.post("/api/escalations/T-ESC-001/reject")
        assert not self.csv_path.exists()

    def test_approve_alone_does_not_write_csv(self):
        """approve transitions to 'approved' but does NOT write history."""
        client.post("/api/escalations/T-ESC-001/report", json=PENDING_HIGH_REPORT)
        client.post("/api/escalations/T-ESC-001/approve")
        assert not self.csv_path.exists()

    def test_duplicate_completion_409_no_second_row(self):
        """Second POST to a completed ticket returns 409; no duplicate row written."""
        import csv as csv_mod
        client.post("/api/escalations/T-ESC-001/report", json=MINIMAL_REPORT)
        resp2 = client.post("/api/escalations/T-ESC-001/report", json=MINIMAL_REPORT)
        assert resp2.status_code == 409
        rows = list(csv_mod.DictReader(self.csv_path.read_text(encoding="utf-8").splitlines()))
        assert len(rows) == 1, "Should have exactly one row, not two"

    def test_high_risk_full_flow_writes_csv_on_completed(self):
        """pending_approval → approved → completed(high) writes one row."""
        import csv as csv_mod
        client.post("/api/escalations/T-ESC-001/report", json=PENDING_HIGH_REPORT)
        # approve writes no history
        client.post("/api/escalations/T-ESC-001/approve")
        assert not self.csv_path.exists()
        # completed writes history
        client.post("/api/escalations/T-ESC-001/report", json=COMPLETED_HIGH_REPORT)
        assert self.csv_path.exists()
        rows = list(csv_mod.DictReader(self.csv_path.read_text(encoding="utf-8").splitlines()))
        assert len(rows) == 1
        assert rows[0]["id"] == "T-ESC-001"
        assert rows[0]["risk_level"] == "high"
        assert rows[0]["files_changed"] == "app/payments.py"

    def test_completed_fix_failed_does_not_write_csv(self):
        payload = {**MINIMAL_REPORT, "verdict": "fix_failed", "files_changed": [], "impact": None}
        client.post("/api/escalations/T-ESC-001/report", json=payload)
        assert not self.csv_path.exists()

    def test_impact_stored_from_report_field(self):
        import csv as csv_mod
        client.post("/api/escalations/T-ESC-001/report", json=MINIMAL_REPORT)
        rows = list(csv_mod.DictReader(self.csv_path.read_text(encoding="utf-8").splitlines()))
        assert rows[0]["impact"] == MINIMAL_REPORT["impact"]


# ---------------------------------------------------------------------------
# Wait-for-approval waiter tests (no real sleeps, no real HTTP)
# ---------------------------------------------------------------------------

class TestWaitForApproval:
    """Unit tests for scripts/wait_for_approval.py with stubbed responses."""

    @pytest.fixture(autouse=True)
    def _import_waiter(self, monkeypatch):
        import sys
        from pathlib import Path
        scripts_dir = Path(__file__).parent.parent / "scripts"
        sys.path.insert(0, str(scripts_dir))

    def _run_waiter(self, responses: list, monkeypatch, ticket_id="T-TEST",
                    timeout=30.0, interval=0.0):
        """Run wait_for_approval.main() with stubbed httpx.get and no real sleeps."""
        import wait_for_approval

        call_index = {"n": 0}

        class FakeResp:
            def __init__(self, status_code, body):
                self.status_code = status_code
                self._body = body

            def json(self):
                return self._body

        def fake_get(url, timeout=10):
            i = call_index["n"]
            call_index["n"] += 1
            sc, body = responses[min(i, len(responses) - 1)]
            return FakeResp(sc, body)

        monkeypatch.setattr("httpx.get", fake_get)
        monkeypatch.setattr("time.sleep", lambda _: None)

        import sys as _sys
        import argparse

        # Build args manually to avoid sys.argv parsing
        args = argparse.Namespace(
            ticket_id=ticket_id,
            url="http://localhost:8000",
            timeout=timeout,
            interval=interval,
        )

        # Capture SystemExit
        with pytest.raises(SystemExit) as exc_info:
            # Monkey-patch parse_args so main() uses our args
            monkeypatch.setattr(argparse.ArgumentParser, "parse_args", lambda self: args)
            wait_for_approval.main()

        return exc_info.value.code

    def test_approved_exits_0(self, monkeypatch):
        exit_code = self._run_waiter(
            [(200, {"status": "approved"})],
            monkeypatch,
        )
        assert exit_code == 0

    def test_rejected_exits_2(self, monkeypatch):
        exit_code = self._run_waiter(
            [(200, {"status": "rejected"})],
            monkeypatch,
        )
        assert exit_code == 2

    def test_pending_then_approved_exits_0(self, monkeypatch):
        responses = [
            (200, {"status": "pending_approval"}),
            (200, {"status": "pending_approval"}),
            (200, {"status": "approved"}),
        ]
        exit_code = self._run_waiter(responses, monkeypatch, timeout=300.0, interval=0.0)
        assert exit_code == 0

    def test_timeout_exits_1(self, monkeypatch):
        # With timeout=0 and a 404 response, it should time out immediately
        import time
        call_count = {"n": 0}

        class FakeResp:
            status_code = 404
            def json(self): return {}

        def fake_get(url, timeout=10):
            call_count["n"] += 1
            return FakeResp()

        monkeypatch.setattr("httpx.get", fake_get)

        real_monotonic = time.monotonic
        start = [None]

        def fake_sleep(s):
            pass

        monkeypatch.setattr("time.sleep", fake_sleep)

        import argparse
        import wait_for_approval

        args = argparse.Namespace(
            ticket_id="T-TIMEOUT",
            url="http://localhost:8000",
            timeout=0.0,  # immediate timeout
            interval=0.0,
        )
        monkeypatch.setattr(argparse.ArgumentParser, "parse_args", lambda self: args)

        with pytest.raises(SystemExit) as exc_info:
            wait_for_approval.main()

        assert exc_info.value.code == 1

    def test_404_then_approved_exits_0(self, monkeypatch):
        responses = [
            (404, {}),
            (404, {}),
            (200, {"status": "approved"}),
        ]
        exit_code = self._run_waiter(responses, monkeypatch, timeout=300.0, interval=0.0)
        assert exit_code == 0
