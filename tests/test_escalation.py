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

MINIMAL_REPORT = {
    "ticket_id": "T-ESC-001",
    "root_cause": "Off-by-one in payment loop",
    "files_examined": ["app/payments.py", "app/orders.py"],
    "patch_summary": "Changed <= to < on line 42 of payments.py",
    "diff": "--- a/app/payments.py\n+++ b/app/payments.py\n@@ -42 +42 @@\n-    for i in range(0, n+1):\n+    for i in range(0, n):\n",
    "tests_before": "32 passed 1 failed",
    "tests_after": "33 passed",
    "verdict": "fix_verified",
}


def _make_report(**overrides) -> EscalationReport:
    data = {**MINIMAL_REPORT, **overrides}
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
        report = _make_report(verdict="fix_failed")
        assert report.verdict == "fix_failed"

    def test_verdict_needs_human(self):
        report = _make_report(verdict="needs_human")
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
        store.save(_make_report(verdict="fix_failed"))
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
    def _patch_store(self, tmp_path, monkeypatch):
        """Replace the module-level store with a fresh temp-backed one."""
        import triagegate.web.server as server_module
        fresh_store = EscalationStore(store_dir=tmp_path)
        monkeypatch.setattr(server_module, "_escalation_store", fresh_store)

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
# Risk-gated autonomy tests
# ---------------------------------------------------------------------------

class TestRiskLevel:
    """Validate risk_level / auto_applied model rules."""

    def test_low_risk_default(self):
        report = _make_report()
        assert report.risk_level == "low"
        assert report.auto_applied is False

    def test_high_risk_explicit(self):
        report = _make_report(risk_level="high")
        assert report.risk_level == "high"

    def test_low_risk_auto_applied_true_accepted(self):
        report = _make_report(risk_level="low", auto_applied=True)
        assert report.auto_applied is True
        assert report.risk_level == "low"

    def test_high_risk_auto_applied_true_rejected(self):
        with pytest.raises(ValidationError):
            _make_report(risk_level="high", auto_applied=True)

    def test_high_risk_auto_applied_false_accepted(self):
        report = _make_report(risk_level="high", auto_applied=False)
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
        report = _make_report(risk_level="high", auto_applied=False)
        restored = EscalationReport.model_validate_json(report.model_dump_json())
        assert restored.risk_level == "high"
        assert restored.auto_applied is False


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
        report = _make_report(risk_level="high", auto_applied=False)
        store.save(report)
        loaded = store.load("T-ESC-001")
        assert loaded.risk_level == "high"
        assert loaded.auto_applied is False


# ---------------------------------------------------------------------------
# Status / RCA / code_before / code_after model tests
# ---------------------------------------------------------------------------

class TestApprovalFields:
    """status, root_cause_analysis, code_before, code_after model fields."""

    def test_status_default_is_pending_approval(self):
        report = _make_report()
        assert report.status == "pending_approval"

    def test_status_approved(self):
        report = _make_report(status="approved")
        assert report.status == "approved"

    def test_status_rejected(self):
        report = _make_report(status="rejected")
        assert report.status == "rejected"

    def test_status_auto_applied(self):
        report = _make_report(status="auto_applied")
        assert report.status == "auto_applied"

    def test_status_invalid_raises(self):
        with pytest.raises(ValidationError):
            _make_report(status="unknown_state")

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
            status="approved",
            root_cause_analysis="RCA text",
            code_before="before",
            code_after="after",
        )
        data = json.loads(report.model_dump_json())
        assert data["status"] == "approved"
        assert data["root_cause_analysis"] == "RCA text"
        assert data["code_before"] == "before"
        assert data["code_after"] == "after"


class TestRiskLevelEndpoints:
    """Risk fields flow through POST/GET endpoints correctly."""

    @pytest.fixture(autouse=True)
    def _patch_store(self, tmp_path, monkeypatch):
        import triagegate.web.server as server_module
        fresh_store = EscalationStore(store_dir=tmp_path)
        monkeypatch.setattr(server_module, "_escalation_store", fresh_store)

    def test_post_low_risk_auto_applied_returns_201(self):
        payload = {**MINIMAL_REPORT, "risk_level": "low", "auto_applied": True}
        resp = client.post("/api/escalations/T-ESC-001/report", json=payload)
        assert resp.status_code == 201
        data = resp.json()
        assert data["risk_level"] == "low"
        assert data["auto_applied"] is True

    def test_post_high_risk_auto_applied_returns_422(self):
        payload = {**MINIMAL_REPORT, "risk_level": "high", "auto_applied": True}
        resp = client.post("/api/escalations/T-ESC-001/report", json=payload)
        assert resp.status_code == 422

    def test_post_high_risk_no_auto_returns_201(self):
        payload = {**MINIMAL_REPORT, "risk_level": "high", "auto_applied": False}
        resp = client.post("/api/escalations/T-ESC-001/report", json=payload)
        assert resp.status_code == 201
        data = resp.json()
        assert data["risk_level"] == "high"
        assert data["auto_applied"] is False

    def test_get_returns_risk_fields(self):
        payload = {**MINIMAL_REPORT, "risk_level": "low", "auto_applied": True}
        client.post("/api/escalations/T-ESC-001/report", json=payload)
        data = client.get("/api/escalations/T-ESC-001").json()
        assert data["risk_level"] == "low"
        assert data["auto_applied"] is True

    def test_risk_fields_default_in_response(self):
        resp = client.post("/api/escalations/T-ESC-001/report", json=MINIMAL_REPORT)
        assert resp.status_code == 201
        data = resp.json()
        assert "risk_level" in data
        assert "auto_applied" in data
        assert data["risk_level"] == "low"
        assert data["auto_applied"] is False


# ---------------------------------------------------------------------------
# Approve / reject endpoint tests
# ---------------------------------------------------------------------------

class TestApproveRejectEndpoints:
    """Approve and reject endpoints for escalation reports."""

    @pytest.fixture(autouse=True)
    def _patch_store(self, tmp_path, monkeypatch):
        import triagegate.web.server as server_module
        fresh_store = EscalationStore(store_dir=tmp_path)
        monkeypatch.setattr(server_module, "_escalation_store", fresh_store)

    def test_approve_missing_ticket_returns_404(self):
        resp = client.post("/api/escalations/NOEXIST-999/approve")
        assert resp.status_code == 404

    def test_reject_missing_ticket_returns_404(self):
        resp = client.post("/api/escalations/NOEXIST-999/reject")
        assert resp.status_code == 404

    def test_approve_pending_sets_status_approved(self):
        client.post("/api/escalations/T-ESC-001/report", json={**MINIMAL_REPORT, "risk_level": "high"})
        resp = client.post("/api/escalations/T-ESC-001/approve")
        assert resp.status_code == 200
        assert resp.json()["status"] == "approved"

    def test_reject_pending_sets_status_rejected(self):
        client.post("/api/escalations/T-ESC-001/report", json={**MINIMAL_REPORT, "risk_level": "high"})
        resp = client.post("/api/escalations/T-ESC-001/reject")
        assert resp.status_code == 200
        assert resp.json()["status"] == "rejected"

    def test_approve_twice_returns_409(self):
        client.post("/api/escalations/T-ESC-001/report", json={**MINIMAL_REPORT, "risk_level": "high"})
        client.post("/api/escalations/T-ESC-001/approve")
        resp = client.post("/api/escalations/T-ESC-001/approve")
        assert resp.status_code == 409

    def test_reject_after_approve_returns_409(self):
        client.post("/api/escalations/T-ESC-001/report", json={**MINIMAL_REPORT, "risk_level": "high"})
        client.post("/api/escalations/T-ESC-001/approve")
        resp = client.post("/api/escalations/T-ESC-001/reject")
        assert resp.status_code == 409

    def test_get_after_approve_reflects_approved_status(self):
        client.post("/api/escalations/T-ESC-001/report", json={**MINIMAL_REPORT, "risk_level": "high"})
        client.post("/api/escalations/T-ESC-001/approve")
        data = client.get("/api/escalations/T-ESC-001").json()
        assert data["status"] == "approved"

    def test_get_after_reject_reflects_rejected_status(self):
        client.post("/api/escalations/T-ESC-001/report", json={**MINIMAL_REPORT, "risk_level": "high"})
        client.post("/api/escalations/T-ESC-001/reject")
        data = client.get("/api/escalations/T-ESC-001").json()
        assert data["status"] == "rejected"

    def test_approve_response_contains_status_field(self):
        client.post("/api/escalations/T-ESC-001/report", json=MINIMAL_REPORT)
        resp = client.post("/api/escalations/T-ESC-001/approve")
        assert resp.status_code == 200
        assert "status" in resp.json()

    def test_new_fields_present_in_get_response(self):
        client.post("/api/escalations/T-ESC-001/report", json=MINIMAL_REPORT)
        data = client.get("/api/escalations/T-ESC-001").json()
        for field in ("status", "root_cause_analysis", "code_before", "code_after"):
            assert field in data, f"missing field: {field}"


# ---------------------------------------------------------------------------
# Incident history CSV tests
# ---------------------------------------------------------------------------

class TestIncidentHistoryCSV:
    """Approving a report appends a row to incident_history.csv."""

    @pytest.fixture(autouse=True)
    def _patch_store_and_csv(self, tmp_path, monkeypatch):
        import triagegate.web.server as server_module
        fresh_store = EscalationStore(store_dir=tmp_path)
        monkeypatch.setattr(server_module, "_escalation_store", fresh_store)
        # Redirect the history CSV to a temp file
        csv_path = tmp_path / "incident_history.csv"
        monkeypatch.setattr(server_module, "_INCIDENT_HISTORY_CSV", csv_path)
        self.csv_path = csv_path

    def test_approve_appends_row_to_csv(self):
        client.post("/api/escalations/T-ESC-001/report", json=MINIMAL_REPORT)
        client.post("/api/escalations/T-ESC-001/approve")
        assert self.csv_path.exists()
        import csv as csv_mod
        rows = list(csv_mod.DictReader(self.csv_path.read_text(encoding="utf-8").splitlines()))
        assert len(rows) == 1
        assert rows[0]["id"] == "T-ESC-001"
        assert rows[0]["verdict"] == "fix_verified"
        assert rows[0]["risk_level"] == "low"

    def test_reject_does_not_append_csv(self):
        client.post("/api/escalations/T-ESC-001/report", json=MINIMAL_REPORT)
        client.post("/api/escalations/T-ESC-001/reject")
        assert not self.csv_path.exists()

    def test_approve_with_rca_uses_first_line_as_impact(self):
        rca = "Primary root cause line.\n\nSecondary details."
        client.post("/api/escalations/T-ESC-001/report", json={**MINIMAL_REPORT, "root_cause_analysis": rca})
        client.post("/api/escalations/T-ESC-001/approve")
        import csv as csv_mod
        rows = list(csv_mod.DictReader(self.csv_path.read_text(encoding="utf-8").splitlines()))
        assert rows[0]["impact"] == "Primary root cause line."

    def test_approve_without_rca_uses_root_cause(self):
        client.post("/api/escalations/T-ESC-001/report", json=MINIMAL_REPORT)
        client.post("/api/escalations/T-ESC-001/approve")
        import csv as csv_mod
        rows = list(csv_mod.DictReader(self.csv_path.read_text(encoding="utf-8").splitlines()))
        assert rows[0]["impact"] == MINIMAL_REPORT["root_cause"]

    def test_csv_domain_is_escalated(self):
        client.post("/api/escalations/T-ESC-001/report", json=MINIMAL_REPORT)
        client.post("/api/escalations/T-ESC-001/approve")
        import csv as csv_mod
        rows = list(csv_mod.DictReader(self.csv_path.read_text(encoding="utf-8").splitlines()))
        assert rows[0]["domain"] == "escalated"
