"""Tests for Task 25 — headless Bob investigation dispatch.

All subprocess calls are monkeypatched.  The real Bob CLI is never invoked.
"""
from __future__ import annotations

import json
import os
import threading
import types
from pathlib import Path
from typing import Any, Dict
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

# ---------------------------------------------------------------------------
# Helpers / fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def _clean_dispatch_registry(monkeypatch):
    """Reset the in-memory dispatch registry between tests."""
    import triagegate.escalation.dispatch as disp_mod
    monkeypatch.setattr(disp_mod, "_registry", {})
    yield
    monkeypatch.setattr(disp_mod, "_registry", {})


@pytest.fixture(autouse=True)
def _clean_server_state(monkeypatch):
    """Reset server-side escalated ticket set between tests."""
    import triagegate.web.server as srv
    monkeypatch.setattr(srv, "_escalated_ticket_ids", set())
    yield


def _make_mock_proc(poll_return=None):
    """Return a MagicMock that behaves like a Popen object."""
    proc = MagicMock()
    proc.poll.return_value = poll_return
    proc.pid = 12345
    return proc


def _fake_popen_factory(mock_proc):
    """Return a Popen constructor that always returns *mock_proc*."""
    def _fake_popen(argv, stdout, stderr, env, shell):
        assert shell is False, "shell=True must never be used"
        return mock_proc
    return _fake_popen


# ---------------------------------------------------------------------------
# AREA 1 — dispatch.py unit tests
# ---------------------------------------------------------------------------

class TestDispatchArgvSafety:
    """Verify argv is constructed safely, without shell=True or untrusted data."""

    def test_argv_does_not_contain_title(self, tmp_path, monkeypatch):
        monkeypatch.setenv("BOB_API_KEY", "test-key-xyz")
        monkeypatch.setenv("BOB_CLI", "bob")
        monkeypatch.setenv("BOB_MAX_COST", "1.0")

        captured_argv = []
        proc = _make_mock_proc(poll_return=None)

        def fake_popen(argv, stdout, stderr, env, shell):
            captured_argv.extend(argv)
            assert shell is False
            return proc

        import triagegate.escalation.dispatch as disp_mod
        monkeypatch.setattr(disp_mod.subprocess, "Popen", fake_popen)
        # Redirect payload/log dirs to tmp
        monkeypatch.setattr(disp_mod, "_DISPATCH_PAYLOADS_DIR", tmp_path / "payloads")
        monkeypatch.setattr(disp_mod, "_DISPATCH_LOGS_DIR", tmp_path / "logs")

        from triagegate.escalation.dispatch import dispatch_investigation
        dispatch_investigation("T-999", "Crash on login", "The app crashes when logging in")

        assert "Crash on login" not in captured_argv
        assert "The app crashes when logging in" not in captured_argv

    def test_argv_does_not_contain_description(self, tmp_path, monkeypatch):
        monkeypatch.setenv("BOB_API_KEY", "test-key-xyz")
        monkeypatch.setenv("BOB_CLI", "bob")
        monkeypatch.setenv("BOB_MAX_COST", "1.0")

        captured_argv = []
        proc = _make_mock_proc(poll_return=None)

        def fake_popen(argv, stdout, stderr, env, shell):
            captured_argv.extend(argv)
            return proc

        import triagegate.escalation.dispatch as disp_mod
        monkeypatch.setattr(disp_mod.subprocess, "Popen", fake_popen)
        monkeypatch.setattr(disp_mod, "_DISPATCH_PAYLOADS_DIR", tmp_path / "payloads")
        monkeypatch.setattr(disp_mod, "_DISPATCH_LOGS_DIR", tmp_path / "logs")

        from triagegate.escalation.dispatch import dispatch_investigation
        dispatch_investigation("T-998", "Memory leak", "RSS grows unbounded after 1 hour")

        for arg in captured_argv:
            assert "RSS grows unbounded" not in str(arg)

    def test_argv_contains_correct_bob_flags(self, tmp_path, monkeypatch):
        monkeypatch.setenv("BOB_API_KEY", "test-key-xyz")
        monkeypatch.setenv("BOB_CLI", "bob")
        monkeypatch.setenv("BOB_MAX_COST", "2.0")

        captured_argv = []
        proc = _make_mock_proc(poll_return=None)

        def fake_popen(argv, stdout, stderr, env, shell):
            captured_argv.extend(argv)
            return proc

        import triagegate.escalation.dispatch as disp_mod
        monkeypatch.setattr(disp_mod.subprocess, "Popen", fake_popen)
        monkeypatch.setattr(disp_mod, "_DISPATCH_PAYLOADS_DIR", tmp_path / "payloads")
        monkeypatch.setattr(disp_mod, "_DISPATCH_LOGS_DIR", tmp_path / "logs")

        from triagegate.escalation.dispatch import dispatch_investigation
        dispatch_investigation("T-001", "Bug title", "Bug description")

        assert "run" in captured_argv
        assert "--mode" in captured_argv
        assert "bug-investigator" in captured_argv
        assert "--format" in captured_argv
        assert "json" in captured_argv
        assert "--max-cost" in captured_argv
        assert "2.0" in captured_argv
        assert "--trust" in captured_argv
        assert "--accept-license" in captured_argv

    def test_shell_false_always_enforced(self, tmp_path, monkeypatch):
        monkeypatch.setenv("BOB_API_KEY", "test-key-xyz")
        monkeypatch.setenv("BOB_CLI", "bob")

        shell_values = []
        proc = _make_mock_proc()

        def fake_popen(argv, stdout, stderr, env, shell):
            shell_values.append(shell)
            return proc

        import triagegate.escalation.dispatch as disp_mod
        monkeypatch.setattr(disp_mod.subprocess, "Popen", fake_popen)
        monkeypatch.setattr(disp_mod, "_DISPATCH_PAYLOADS_DIR", tmp_path / "payloads")
        monkeypatch.setattr(disp_mod, "_DISPATCH_LOGS_DIR", tmp_path / "logs")

        from triagegate.escalation.dispatch import dispatch_investigation
        dispatch_investigation("T-002", "t", "d")
        assert shell_values == [False]

    def test_ticket_id_injection_cannot_modify_argv(self, tmp_path, monkeypatch):
        """Injection attempt in ticket_id must be rejected by validation."""
        monkeypatch.setenv("BOB_API_KEY", "test-key-xyz")
        monkeypatch.setenv("BOB_CLI", "bob")

        import triagegate.escalation.dispatch as disp_mod
        monkeypatch.setattr(disp_mod, "_DISPATCH_PAYLOADS_DIR", tmp_path / "payloads")
        monkeypatch.setattr(disp_mod, "_DISPATCH_LOGS_DIR", tmp_path / "logs")

        from triagegate.escalation.dispatch import dispatch_investigation
        with pytest.raises(ValueError, match="Invalid ticket_id"):
            dispatch_investigation("T-001; rm -rf /", "title", "desc")

    def test_ticket_id_with_path_traversal_rejected(self, tmp_path, monkeypatch):
        monkeypatch.setenv("BOB_API_KEY", "test-key-xyz")
        monkeypatch.setenv("BOB_CLI", "bob")

        import triagegate.escalation.dispatch as disp_mod
        monkeypatch.setattr(disp_mod, "_DISPATCH_PAYLOADS_DIR", tmp_path / "payloads")
        monkeypatch.setattr(disp_mod, "_DISPATCH_LOGS_DIR", tmp_path / "logs")

        from triagegate.escalation.dispatch import dispatch_investigation
        with pytest.raises(ValueError, match="Invalid ticket_id"):
            dispatch_investigation("../etc/passwd", "title", "desc")


class TestDispatchPayloadFile:
    """Verify payload JSON is written correctly and contains ticket data."""

    def test_payload_file_contains_ticket_data(self, tmp_path, monkeypatch):
        monkeypatch.setenv("BOB_API_KEY", "test-key-xyz")
        monkeypatch.setenv("BOB_CLI", "bob")

        proc = _make_mock_proc()

        import triagegate.escalation.dispatch as disp_mod
        monkeypatch.setattr(disp_mod.subprocess, "Popen", _fake_popen_factory(proc))
        payload_dir = tmp_path / "payloads"
        log_dir = tmp_path / "logs"
        monkeypatch.setattr(disp_mod, "_DISPATCH_PAYLOADS_DIR", payload_dir)
        monkeypatch.setattr(disp_mod, "_DISPATCH_LOGS_DIR", log_dir)

        from triagegate.escalation.dispatch import dispatch_investigation
        record = dispatch_investigation("T-100", "My Bug Title", "Long description here")

        # Find the payload file
        files = list(payload_dir.glob("*.json"))
        assert len(files) == 1
        data = json.loads(files[0].read_text(encoding="utf-8"))
        assert data["ticket_id"] == "T-100"
        assert data["title"] == "My Bug Title"
        assert data["description"] == "Long description here"
        assert "dispatch_id" in data

    def test_payload_does_not_contain_api_key(self, tmp_path, monkeypatch):
        monkeypatch.setenv("BOB_API_KEY", "SUPER-SECRET-KEY-ABCDEF")
        monkeypatch.setenv("BOB_CLI", "bob")

        proc = _make_mock_proc()

        import triagegate.escalation.dispatch as disp_mod
        monkeypatch.setattr(disp_mod.subprocess, "Popen", _fake_popen_factory(proc))
        payload_dir = tmp_path / "payloads"
        monkeypatch.setattr(disp_mod, "_DISPATCH_PAYLOADS_DIR", payload_dir)
        monkeypatch.setattr(disp_mod, "_DISPATCH_LOGS_DIR", tmp_path / "logs")

        from triagegate.escalation.dispatch import dispatch_investigation
        dispatch_investigation("T-101", "title", "desc")

        files = list(payload_dir.glob("*.json"))
        raw = files[0].read_text(encoding="utf-8")
        assert "SUPER-SECRET-KEY-ABCDEF" not in raw


class TestDispatchApiKeyHandling:
    """API key is passed in child env but never exposed."""

    def test_api_key_passed_to_child_env(self, tmp_path, monkeypatch):
        monkeypatch.setenv("BOB_API_KEY", "secret-key-for-env-test")
        monkeypatch.setenv("BOB_CLI", "bob")

        received_env = {}
        proc = _make_mock_proc()

        def capture_popen(argv, stdout, stderr, env, shell):
            received_env.update(env)
            return proc

        import triagegate.escalation.dispatch as disp_mod
        monkeypatch.setattr(disp_mod.subprocess, "Popen", capture_popen)
        monkeypatch.setattr(disp_mod, "_DISPATCH_PAYLOADS_DIR", tmp_path / "payloads")
        monkeypatch.setattr(disp_mod, "_DISPATCH_LOGS_DIR", tmp_path / "logs")

        from triagegate.escalation.dispatch import dispatch_investigation
        dispatch_investigation("T-200", "t", "d")

        assert received_env.get("BOB_API_KEY") == "secret-key-for-env-test"

    def test_api_key_not_in_argv(self, tmp_path, monkeypatch):
        monkeypatch.setenv("BOB_API_KEY", "NEVER-IN-ARGV-KEY-XYZ")
        monkeypatch.setenv("BOB_CLI", "bob")

        captured_argv = []
        proc = _make_mock_proc()

        def capture_popen(argv, stdout, stderr, env, shell):
            captured_argv.extend(argv)
            return proc

        import triagegate.escalation.dispatch as disp_mod
        monkeypatch.setattr(disp_mod.subprocess, "Popen", capture_popen)
        monkeypatch.setattr(disp_mod, "_DISPATCH_PAYLOADS_DIR", tmp_path / "payloads")
        monkeypatch.setattr(disp_mod, "_DISPATCH_LOGS_DIR", tmp_path / "logs")

        from triagegate.escalation.dispatch import dispatch_investigation
        dispatch_investigation("T-201", "t", "d")

        assert "NEVER-IN-ARGV-KEY-XYZ" not in captured_argv

    def test_api_key_not_in_return_value(self, tmp_path, monkeypatch):
        monkeypatch.setenv("BOB_API_KEY", "NEVER-RETURNED-KEY-987")
        monkeypatch.setenv("BOB_CLI", "bob")

        proc = _make_mock_proc()

        import triagegate.escalation.dispatch as disp_mod
        monkeypatch.setattr(disp_mod.subprocess, "Popen", _fake_popen_factory(proc))
        monkeypatch.setattr(disp_mod, "_DISPATCH_PAYLOADS_DIR", tmp_path / "payloads")
        monkeypatch.setattr(disp_mod, "_DISPATCH_LOGS_DIR", tmp_path / "logs")

        from triagegate.escalation.dispatch import dispatch_investigation
        record = dispatch_investigation("T-202", "t", "d")

        assert "NEVER-RETURNED-KEY-987" not in json.dumps(record)

    def test_missing_api_key_raises_runtime_error(self, tmp_path, monkeypatch):
        monkeypatch.delenv("BOB_API_KEY", raising=False)
        monkeypatch.setenv("BOB_CLI", "bob")

        import triagegate.escalation.dispatch as disp_mod
        monkeypatch.setattr(disp_mod, "_DISPATCH_PAYLOADS_DIR", tmp_path / "payloads")
        monkeypatch.setattr(disp_mod, "_DISPATCH_LOGS_DIR", tmp_path / "logs")

        from triagegate.escalation.dispatch import dispatch_investigation
        with pytest.raises(RuntimeError, match="BOB_API_KEY"):
            dispatch_investigation("T-300", "t", "d")


class TestDispatchNonBlocking:
    """dispatch_investigation must return without waiting for the child process."""

    def test_returns_immediately_without_waiting(self, tmp_path, monkeypatch):
        monkeypatch.setenv("BOB_API_KEY", "test-key-xyz")
        monkeypatch.setenv("BOB_CLI", "bob")

        import triagegate.escalation.dispatch as disp_mod

        # Popen that records whether wait() or communicate() were called
        proc = _make_mock_proc(poll_return=None)
        proc.wait = MagicMock(side_effect=AssertionError("wait() must not be called"))
        proc.communicate = MagicMock(side_effect=AssertionError("communicate() must not be called"))

        monkeypatch.setattr(disp_mod.subprocess, "Popen", _fake_popen_factory(proc))
        monkeypatch.setattr(disp_mod, "_DISPATCH_PAYLOADS_DIR", tmp_path / "payloads")
        monkeypatch.setattr(disp_mod, "_DISPATCH_LOGS_DIR", tmp_path / "logs")

        from triagegate.escalation.dispatch import dispatch_investigation
        record = dispatch_investigation("T-400", "t", "d")  # must not block

        # Verify record keys
        assert "dispatch_id" in record
        assert "ticket_id" in record
        assert "status" in record
        assert "started_at" in record

    def test_return_record_has_required_fields(self, tmp_path, monkeypatch):
        monkeypatch.setenv("BOB_API_KEY", "test-key-xyz")
        monkeypatch.setenv("BOB_CLI", "bob")
        proc = _make_mock_proc()

        import triagegate.escalation.dispatch as disp_mod
        monkeypatch.setattr(disp_mod.subprocess, "Popen", _fake_popen_factory(proc))
        monkeypatch.setattr(disp_mod, "_DISPATCH_PAYLOADS_DIR", tmp_path / "payloads")
        monkeypatch.setattr(disp_mod, "_DISPATCH_LOGS_DIR", tmp_path / "logs")

        from triagegate.escalation.dispatch import dispatch_investigation
        record = dispatch_investigation("T-401", "title", "desc")

        assert record["ticket_id"] == "T-401"
        assert record["status"] in ("starting", "running", "completed", "failed")
        assert "started_at" in record
        assert "dispatch_id" in record


class TestDispatchIdempotency:
    """Duplicate dispatch calls must not spawn a second subprocess."""

    def test_duplicate_dispatch_reuses_existing(self, tmp_path, monkeypatch):
        monkeypatch.setenv("BOB_API_KEY", "test-key-xyz")
        monkeypatch.setenv("BOB_CLI", "bob")

        popen_call_count = [0]
        proc = _make_mock_proc(poll_return=None)  # still running

        def counting_popen(argv, stdout, stderr, env, shell):
            popen_call_count[0] += 1
            return proc

        import triagegate.escalation.dispatch as disp_mod
        monkeypatch.setattr(disp_mod.subprocess, "Popen", counting_popen)
        monkeypatch.setattr(disp_mod, "_DISPATCH_PAYLOADS_DIR", tmp_path / "payloads")
        monkeypatch.setattr(disp_mod, "_DISPATCH_LOGS_DIR", tmp_path / "logs")

        from triagegate.escalation.dispatch import dispatch_investigation
        r1 = dispatch_investigation("T-500", "title", "desc")
        r2 = dispatch_investigation("T-500", "title", "desc")

        assert popen_call_count[0] == 1, "Popen must be called only once for duplicate dispatches"
        assert r1["dispatch_id"] == r2["dispatch_id"]


class TestCostValidation:
    """BOB_MAX_COST must be positive and never exceed 3.0."""

    def test_cost_above_ceiling_raises(self, monkeypatch):
        monkeypatch.setenv("BOB_API_KEY", "key")
        monkeypatch.setenv("BOB_MAX_COST", "5.0")

        from triagegate.escalation.dispatch import _get_max_cost
        with pytest.raises(ValueError, match="ceiling"):
            _get_max_cost()

    def test_cost_zero_raises(self, monkeypatch):
        monkeypatch.setenv("BOB_MAX_COST", "0.0")

        from triagegate.escalation.dispatch import _get_max_cost
        with pytest.raises(ValueError, match="positive"):
            _get_max_cost()

    def test_cost_negative_raises(self, monkeypatch):
        monkeypatch.setenv("BOB_MAX_COST", "-1.0")

        from triagegate.escalation.dispatch import _get_max_cost
        with pytest.raises(ValueError, match="positive"):
            _get_max_cost()

    def test_cost_defaults_to_3(self, monkeypatch):
        monkeypatch.delenv("BOB_MAX_COST", raising=False)

        from triagegate.escalation.dispatch import _get_max_cost
        assert _get_max_cost() == 3.0

    def test_cost_at_ceiling_accepted(self, monkeypatch):
        monkeypatch.setenv("BOB_MAX_COST", "3.0")

        from triagegate.escalation.dispatch import _get_max_cost
        assert _get_max_cost() == 3.0


class TestGetDispatchStatus:
    """get_dispatch_status uses poll() lazily."""

    def test_running_process_reports_running(self, tmp_path, monkeypatch):
        monkeypatch.setenv("BOB_API_KEY", "test-key-xyz")
        monkeypatch.setenv("BOB_CLI", "bob")

        proc = _make_mock_proc(poll_return=None)  # still running

        import triagegate.escalation.dispatch as disp_mod
        monkeypatch.setattr(disp_mod.subprocess, "Popen", _fake_popen_factory(proc))
        monkeypatch.setattr(disp_mod, "_DISPATCH_PAYLOADS_DIR", tmp_path / "payloads")
        monkeypatch.setattr(disp_mod, "_DISPATCH_LOGS_DIR", tmp_path / "logs")

        from triagegate.escalation.dispatch import dispatch_investigation, get_dispatch_status
        dispatch_investigation("T-600", "t", "d")
        status = get_dispatch_status("T-600")

        assert status is not None
        assert status["status"] == "running"
        assert "BOB_API_KEY" not in status
        assert "test-key-xyz" not in json.dumps(status)

    def test_successful_process_reports_completed(self, tmp_path, monkeypatch):
        monkeypatch.setenv("BOB_API_KEY", "test-key-xyz")
        monkeypatch.setenv("BOB_CLI", "bob")

        proc = _make_mock_proc(poll_return=0)  # exited successfully

        import triagegate.escalation.dispatch as disp_mod
        monkeypatch.setattr(disp_mod.subprocess, "Popen", _fake_popen_factory(proc))
        monkeypatch.setattr(disp_mod, "_DISPATCH_PAYLOADS_DIR", tmp_path / "payloads")
        monkeypatch.setattr(disp_mod, "_DISPATCH_LOGS_DIR", tmp_path / "logs")

        from triagegate.escalation.dispatch import dispatch_investigation, get_dispatch_status
        dispatch_investigation("T-601", "t", "d")
        status = get_dispatch_status("T-601")

        assert status["status"] == "completed"
        assert status.get("exit_code") == 0

    def test_failed_process_reports_failed(self, tmp_path, monkeypatch):
        monkeypatch.setenv("BOB_API_KEY", "test-key-xyz")
        monkeypatch.setenv("BOB_CLI", "bob")

        proc = _make_mock_proc(poll_return=1)  # exited with error

        import triagegate.escalation.dispatch as disp_mod
        monkeypatch.setattr(disp_mod.subprocess, "Popen", _fake_popen_factory(proc))
        monkeypatch.setattr(disp_mod, "_DISPATCH_PAYLOADS_DIR", tmp_path / "payloads")
        monkeypatch.setattr(disp_mod, "_DISPATCH_LOGS_DIR", tmp_path / "logs")

        from triagegate.escalation.dispatch import dispatch_investigation, get_dispatch_status
        dispatch_investigation("T-602", "t", "d")
        status = get_dispatch_status("T-602")

        assert status["status"] == "failed"
        assert status.get("exit_code") == 1
        assert "error_summary" in status

    def test_unknown_ticket_returns_none(self):
        from triagegate.escalation.dispatch import get_dispatch_status
        assert get_dispatch_status("NONEXISTENT-9999") is None


# ---------------------------------------------------------------------------
# AREA 2 — API endpoint tests
# ---------------------------------------------------------------------------

def _get_test_client():
    """Return a fresh TestClient, resetting server-level singletons."""
    from triagegate.web.server import app
    return TestClient(app)


def _make_running_popen(monkeypatch, tmp_path):
    """Patch Popen globally with a running (poll=None) mock."""
    import triagegate.escalation.dispatch as disp_mod
    proc = _make_mock_proc(poll_return=None)
    monkeypatch.setattr(disp_mod.subprocess, "Popen", _fake_popen_factory(proc))
    monkeypatch.setattr(disp_mod, "_DISPATCH_PAYLOADS_DIR", tmp_path / "payloads")
    monkeypatch.setattr(disp_mod, "_DISPATCH_LOGS_DIR", tmp_path / "logs")
    return proc


class TestDispatchEndpointPost:
    """POST /api/escalations/{ticket_id}/dispatch tests."""

    def _client(self):
        from triagegate.web.server import app
        return TestClient(app)

    def test_returns_202_for_escalated_ticket(self, tmp_path, monkeypatch):
        monkeypatch.setenv("BOB_API_KEY", "test-api-key")
        _make_running_popen(monkeypatch, tmp_path)

        # Register ticket as escalated via server state
        import triagegate.web.server as srv
        srv._escalated_ticket_ids.add("T-ESC-001")

        c = self._client()
        resp = c.post("/api/escalations/T-ESC-001/dispatch",
                      json={"title": "Bug", "description": "Details"})
        assert resp.status_code == 202, resp.text

    def test_202_response_contains_dispatch_record(self, tmp_path, monkeypatch):
        monkeypatch.setenv("BOB_API_KEY", "test-api-key")
        _make_running_popen(monkeypatch, tmp_path)

        import triagegate.web.server as srv
        srv._escalated_ticket_ids.add("T-ESC-002")

        c = self._client()
        resp = c.post("/api/escalations/T-ESC-002/dispatch",
                      json={"title": "Bug", "description": "Details"})
        data = resp.json()
        assert "dispatch_id" in data
        assert data["ticket_id"] == "T-ESC-002"
        assert "status" in data
        assert "started_at" in data

    def test_repeated_post_returns_reused_true(self, tmp_path, monkeypatch):
        monkeypatch.setenv("BOB_API_KEY", "test-api-key")
        _make_running_popen(monkeypatch, tmp_path)

        import triagegate.web.server as srv
        srv._escalated_ticket_ids.add("T-ESC-003")

        c = self._client()
        r1 = c.post("/api/escalations/T-ESC-003/dispatch",
                    json={"title": "Bug", "description": "Details"})
        r2 = c.post("/api/escalations/T-ESC-003/dispatch",
                    json={"title": "Bug", "description": "Details"})

        assert r1.status_code == 202
        assert r2.status_code == 202
        d2 = r2.json()
        assert d2.get("reused") is True
        assert d2["dispatch_id"] == r1.json()["dispatch_id"]

    def test_returns_503_when_api_key_missing(self, tmp_path, monkeypatch):
        monkeypatch.delenv("BOB_API_KEY", raising=False)

        import triagegate.web.server as srv
        srv._escalated_ticket_ids.add("T-ESC-004")

        c = self._client()
        resp = c.post("/api/escalations/T-ESC-004/dispatch",
                      json={"title": "Bug", "description": "Details"})
        assert resp.status_code == 503

    def test_503_does_not_expose_api_key(self, tmp_path, monkeypatch):
        monkeypatch.setenv("BOB_API_KEY", "EXPOSED-KEY-TEST")
        # Make CLI resolution fail
        import triagegate.escalation.dispatch as disp_mod

        def fail_popen(argv, stdout, stderr, env, shell):
            raise FileNotFoundError("bob not found")

        monkeypatch.setattr(disp_mod.subprocess, "Popen", fail_popen)
        monkeypatch.setattr(disp_mod, "_DISPATCH_PAYLOADS_DIR", tmp_path / "payloads")
        monkeypatch.setattr(disp_mod, "_DISPATCH_LOGS_DIR", tmp_path / "logs")

        import triagegate.web.server as srv
        srv._escalated_ticket_ids.add("T-ESC-005")

        c = self._client()
        resp = c.post("/api/escalations/T-ESC-005/dispatch",
                      json={"title": "Bug", "description": "Details"})
        # Should get 503; key must not be in response body
        assert "EXPOSED-KEY-TEST" not in resp.text

    def test_returns_409_when_ticket_not_escalated(self, tmp_path, monkeypatch):
        monkeypatch.setenv("BOB_API_KEY", "test-api-key")
        _make_running_popen(monkeypatch, tmp_path)
        # Do NOT add ticket to _escalated_ticket_ids

        c = self._client()
        resp = c.post("/api/escalations/T-NOT-ESC-001/dispatch",
                      json={"title": "Bug", "description": "Details"})
        assert resp.status_code == 409

    def test_non_escalated_ticket_still_rejected_even_with_escalated_body_field(
            self, tmp_path, monkeypatch):
        """Client cannot override the server-side escalation check."""
        monkeypatch.setenv("BOB_API_KEY", "test-api-key")
        _make_running_popen(monkeypatch, tmp_path)

        c = self._client()
        # Body contains an "escalated: true" field — must not be trusted
        resp = c.post("/api/escalations/T-NOT-ESC-002/dispatch",
                      json={"title": "Bug", "description": "Details", "escalated": True})
        assert resp.status_code == 409


class TestDispatchEndpointStatus:
    """GET /api/escalations/{ticket_id}/dispatch/status tests."""

    def _client(self):
        from triagegate.web.server import app
        return TestClient(app)

    def test_running_process_returns_running_status(self, tmp_path, monkeypatch):
        monkeypatch.setenv("BOB_API_KEY", "test-api-key")
        proc = _make_mock_proc(poll_return=None)

        import triagegate.escalation.dispatch as disp_mod
        monkeypatch.setattr(disp_mod.subprocess, "Popen", _fake_popen_factory(proc))
        monkeypatch.setattr(disp_mod, "_DISPATCH_PAYLOADS_DIR", tmp_path / "payloads")
        monkeypatch.setattr(disp_mod, "_DISPATCH_LOGS_DIR", tmp_path / "logs")

        import triagegate.web.server as srv
        srv._escalated_ticket_ids.add("T-STAT-001")

        c = self._client()
        c.post("/api/escalations/T-STAT-001/dispatch",
               json={"title": "t", "description": "d"})

        resp = c.get("/api/escalations/T-STAT-001/dispatch/status")
        assert resp.status_code == 200
        assert resp.json()["status"] == "running"

    def test_failed_process_returns_failed_status(self, tmp_path, monkeypatch):
        monkeypatch.setenv("BOB_API_KEY", "test-api-key")
        proc = _make_mock_proc(poll_return=2)

        import triagegate.escalation.dispatch as disp_mod
        monkeypatch.setattr(disp_mod.subprocess, "Popen", _fake_popen_factory(proc))
        monkeypatch.setattr(disp_mod, "_DISPATCH_PAYLOADS_DIR", tmp_path / "payloads")
        monkeypatch.setattr(disp_mod, "_DISPATCH_LOGS_DIR", tmp_path / "logs")

        import triagegate.web.server as srv
        srv._escalated_ticket_ids.add("T-STAT-002")

        c = self._client()
        c.post("/api/escalations/T-STAT-002/dispatch",
               json={"title": "t", "description": "d"})

        resp = c.get("/api/escalations/T-STAT-002/dispatch/status")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "failed"

    def test_completed_process_returns_completed_status(self, tmp_path, monkeypatch):
        monkeypatch.setenv("BOB_API_KEY", "test-api-key")
        proc = _make_mock_proc(poll_return=0)

        import triagegate.escalation.dispatch as disp_mod
        monkeypatch.setattr(disp_mod.subprocess, "Popen", _fake_popen_factory(proc))
        monkeypatch.setattr(disp_mod, "_DISPATCH_PAYLOADS_DIR", tmp_path / "payloads")
        monkeypatch.setattr(disp_mod, "_DISPATCH_LOGS_DIR", tmp_path / "logs")

        import triagegate.web.server as srv
        srv._escalated_ticket_ids.add("T-STAT-003")

        c = self._client()
        c.post("/api/escalations/T-STAT-003/dispatch",
               json={"title": "t", "description": "d"})

        resp = c.get("/api/escalations/T-STAT-003/dispatch/status")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "completed"

    def test_status_returns_404_for_unknown_ticket(self):
        c = self._client()
        resp = c.get("/api/escalations/T-UNKNOWN-9999/dispatch/status")
        assert resp.status_code == 404

    def test_status_does_not_expose_api_key(self, tmp_path, monkeypatch):
        monkeypatch.setenv("BOB_API_KEY", "STATUS-KEY-SHOULD-NOT-APPEAR")
        proc = _make_mock_proc(poll_return=None)

        import triagegate.escalation.dispatch as disp_mod
        monkeypatch.setattr(disp_mod.subprocess, "Popen", _fake_popen_factory(proc))
        monkeypatch.setattr(disp_mod, "_DISPATCH_PAYLOADS_DIR", tmp_path / "payloads")
        monkeypatch.setattr(disp_mod, "_DISPATCH_LOGS_DIR", tmp_path / "logs")

        import triagegate.web.server as srv
        srv._escalated_ticket_ids.add("T-STAT-KEY")

        c = self._client()
        c.post("/api/escalations/T-STAT-KEY/dispatch",
               json={"title": "t", "description": "d"})
        resp = c.get("/api/escalations/T-STAT-KEY/dispatch/status")
        assert "STATUS-KEY-SHOULD-NOT-APPEAR" not in resp.text


# ---------------------------------------------------------------------------
# AREA 3 — UI content tests
# ---------------------------------------------------------------------------

class TestDispatchUI:
    """Verify the dispatch button and messages are present in index.html."""

    def _client(self):
        from triagegate.web.server import app
        return TestClient(app)

    def test_index_contains_dispatch_button(self):
        resp = self._client().get("/")
        assert resp.status_code == 200
        assert "btn-dispatch" in resp.text

    def test_index_contains_dispatch_to_bob_text(self):
        resp = self._client().get("/")
        assert "Dispatch to Bob Investigator" in resp.text

    def test_index_contains_investigator_dispatched_working_message(self):
        resp = self._client().get("/")
        assert "Investigator dispatched" in resp.text

    def test_index_contains_automated_dispatch_unavailable_message(self):
        resp = self._client().get("/")
        assert "Automated dispatch unavailable" in resp.text

    def test_index_contains_dispatch_row(self):
        resp = self._client().get("/")
        assert "dispatch-row" in resp.text

    def test_index_contains_dispatch_status_msg(self):
        resp = self._client().get("/")
        assert "dispatch-status-msg" in resp.text

    def test_index_contains_dispatch_endpoint_call(self):
        resp = self._client().get("/")
        assert "/dispatch" in resp.text

    def test_style_contains_btn_dispatch(self):
        resp = self._client().get("/style.css")
        assert "btn-dispatch" in resp.text

    def test_style_contains_dispatch_row(self):
        resp = self._client().get("/style.css")
        assert "dispatch-row" in resp.text

    def test_style_contains_dispatch_status_msg(self):
        resp = self._client().get("/style.css")
        assert "dispatch-status-msg" in resp.text

    def test_existing_escalation_panel_preserved(self):
        """The manual investigation path must still be present."""
        resp = self._client().get("/")
        assert "awaiting Bug Investigator" in resp.text
        assert "Bob Investigator Report" in resp.text

    def test_manual_workflow_text_preserved(self):
        """Approval and reject buttons remain."""
        resp = self._client().get("/")
        assert "btn-approve" in resp.text
        assert "btn-reject" in resp.text
