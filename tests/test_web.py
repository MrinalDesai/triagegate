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
