"""Tests for the web console static-file serving."""
import pytest
from fastapi.testclient import TestClient

from triagegate.web.server import app

client = TestClient(app)


class TestRootRoute:
    def test_get_root_returns_200(self):
        """GET / must return HTTP 200."""
        response = client.get("/")
        assert response.status_code == 200

    def test_get_root_content_type_is_html(self):
        """GET / must return text/html."""
        response = client.get("/")
        assert "text/html" in response.headers["content-type"]

    def test_get_root_contains_triagegate(self):
        """The served HTML must include the product name."""
        response = client.get("/")
        assert "TriageGate" in response.text


class TestStaticFiles:
    def test_style_css_returns_200(self):
        """style.css must be served."""
        response = client.get("/style.css")
        assert response.status_code == 200

    def test_style_css_content_type(self):
        """style.css must have text/css content-type."""
        response = client.get("/style.css")
        assert "text/css" in response.headers["content-type"]

    def test_app_js_returns_200(self):
        """app.js must be served."""
        response = client.get("/app.js")
        assert response.status_code == 200

    def test_app_js_content_type(self):
        """app.js must have a javascript content-type."""
        response = client.get("/app.js")
        ct = response.headers["content-type"]
        assert "javascript" in ct

    def test_stats_html_returns_200(self):
        """stats.html must be served."""
        response = client.get("/stats.html")
        assert response.status_code == 200

    def test_stats_html_content_type(self):
        response = client.get("/stats.html")
        assert "text/html" in response.headers["content-type"]

    def test_about_html_returns_200(self):
        """about.html must be served."""
        response = client.get("/about.html")
        assert response.status_code == 200

    def test_about_html_content_type(self):
        response = client.get("/about.html")
        assert "text/html" in response.headers["content-type"]


class TestNewStaticContent:
    """Verify the new surface areas are present in the served static files."""

    def test_index_contains_similar_incidents_card(self):
        """index.html must include the Similar Past Incidents card."""
        response = client.get("/")
        assert "Similar Past Incidents" in response.text

    def test_index_contains_predicted_risk_row(self):
        """index.html must include the predicted-risk-row element."""
        response = client.get("/")
        assert "predicted-risk-row" in response.text

    def test_index_contains_rationale_row(self):
        """index.html must include the rationale-row element."""
        response = client.get("/")
        assert "rationale-row" in response.text

    def test_index_contains_human_approval_node(self):
        """index.html must include the Human approval pipeline node."""
        response = client.get("/")
        assert "Human approval" in response.text

    def test_index_contains_escalated_waiting_copy(self):
        """index.html must include the updated escalation waiting copy."""
        response = client.get("/")
        assert "awaiting Bug Investigator" in response.text

    def test_style_contains_human_pending(self):
        """style.css must define the pp-human-pending class."""
        response = client.get("/style.css")
        assert "pp-human-pending" in response.text

    def test_style_contains_predicted_risk_badge(self):
        """style.css must define the predicted-risk-badge class."""
        response = client.get("/style.css")
        assert "predicted-risk-badge" in response.text

    def test_style_contains_rationale_row(self):
        """style.css must define the rationale-row class."""
        response = client.get("/style.css")
        assert "rationale-row" in response.text

    def test_style_contains_chip_risk_high(self):
        """style.css must define chip-risk-high for similar incidents."""
        response = client.get("/style.css")
        assert "chip-risk-high" in response.text

    def test_style_contains_code_fix_wrap(self):
        """style.css must define code-fix-wrap for code diff blocks."""
        response = client.get("/style.css")
        assert "code-fix-wrap" in response.text

    def test_style_contains_code_before(self):
        """style.css must define code-before class."""
        response = client.get("/style.css")
        assert "code-before" in response.text

    def test_style_contains_code_after(self):
        """style.css must define code-after class."""
        response = client.get("/style.css")
        assert "code-after" in response.text

    def test_style_contains_btn_approve(self):
        """style.css must define btn-approve class."""
        response = client.get("/style.css")
        assert "btn-approve" in response.text

    def test_style_contains_btn_reject(self):
        """style.css must define btn-reject class."""
        response = client.get("/style.css")
        assert "btn-reject" in response.text

    def test_style_contains_approval_badge(self):
        """style.css must define approval-badge class."""
        response = client.get("/style.css")
        assert "approval-badge" in response.text

    def test_style_contains_approval_row(self):
        """style.css must define approval-row class."""
        response = client.get("/style.css")
        assert "approval-row" in response.text

    def test_style_contains_pp_human_approved(self):
        """style.css must define pp-human-approved pipeline node class."""
        response = client.get("/style.css")
        assert "pp-human-approved" in response.text

    def test_index_contains_root_cause_analysis(self):
        """index.html must reference Root Cause Analysis section."""
        response = client.get("/")
        assert "Root Cause Analysis" in response.text

    def test_index_contains_code_fix_block(self):
        """index.html JS must reference code-fix-block for diff rendering."""
        response = client.get("/")
        assert "code-fix-block" in response.text

    def test_index_contains_btn_approve(self):
        """index.html JS must include the approve button class."""
        response = client.get("/")
        assert "btn-approve" in response.text

    def test_index_contains_btn_reject(self):
        """index.html JS must include the reject button class."""
        response = client.get("/")
        assert "btn-reject" in response.text


class TestIndexHtmlRedirect:
    def test_index_html_redirects(self):
        """/index.html must issue a 307 or 308 redirect."""
        response = client.get("/index.html", follow_redirects=False)
        assert response.status_code in (307, 308)

    def test_index_html_redirect_lands_on_200_html(self):
        """/index.html followed to completion must return 200 text/html."""
        response = client.get("/index.html", follow_redirects=True)
        assert response.status_code == 200
        assert "text/html" in response.headers["content-type"]


class TestServerConstruction:
    """Server wiring: _make_llm_client returns None when credentials are absent."""

    def test_llm_client_none_when_no_env_vars(self, monkeypatch):
        """When all three WatsonX vars are absent, _make_llm_client returns None."""
        monkeypatch.delenv("WATSONX_API_KEY", raising=False)
        monkeypatch.delenv("WATSONX_PROJECT_ID", raising=False)
        monkeypatch.delenv("WATSONX_URL", raising=False)
        from triagegate.web.server import _make_llm_client
        assert _make_llm_client() is None

    def test_llm_client_none_when_partial_env_vars(self, monkeypatch):
        """When only some WatsonX vars are set, _make_llm_client returns None."""
        monkeypatch.setenv("WATSONX_API_KEY", "key123")
        monkeypatch.delenv("WATSONX_PROJECT_ID", raising=False)
        monkeypatch.delenv("WATSONX_URL", raising=False)
        from triagegate.web.server import _make_llm_client
        assert _make_llm_client() is None

    def test_llm_client_returned_when_all_env_vars_present(self, monkeypatch):
        """When all three WatsonX vars are present, _make_llm_client returns a client."""
        monkeypatch.setenv("WATSONX_API_KEY", "key123")
        monkeypatch.setenv("WATSONX_PROJECT_ID", "proj456")
        monkeypatch.setenv("WATSONX_URL", "https://us-south.ml.cloud.ibm.com")
        from triagegate.web.server import _make_llm_client
        client_obj = _make_llm_client()
        assert client_obj is not None

    def test_resolver_still_works_without_llm(self, monkeypatch):
        """Resolver created with llm_client=None (no WatsonX creds) still handles requests."""
        monkeypatch.delenv("WATSONX_API_KEY", raising=False)
        monkeypatch.delenv("WATSONX_PROJECT_ID", raising=False)
        monkeypatch.delenv("WATSONX_URL", raising=False)
        # Reset cached resolver so _make_llm_client is called fresh
        import triagegate.web.server as server_module
        monkeypatch.setattr(server_module, "_resolver", None)
        response = client.get("/health")
        assert response.status_code == 200
