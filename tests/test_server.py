import pytest
from fastapi.testclient import TestClient

from triagegate.web.server import app

client = TestClient(app)


class TestHealth:
    def test_health_returns_200(self):
        response = client.get("/health")
        assert response.status_code == 200

    def test_health_body(self):
        response = client.get("/health")
        assert response.json() == {"status": "ok"}


class TestRouteEndpoint:
    def test_route_returns_200(self):
        payload = {"id": "T-100", "title": "Network timeout", "description": "Connection drops every 5 min."}
        response = client.post("/api/route", json=payload)
        assert response.status_code == 200

    def test_route_ticket_id_matches(self):
        payload = {"id": "T-102", "title": "Disk full", "description": "Root partition at 100%."}
        response = client.post("/api/route", json=payload)
        data = response.json()
        assert data["ticket_id"] == "T-102"

    def test_route_response_schema(self):
        payload = {"id": "T-103", "title": "Memory leak", "description": "RSS grows unbounded."}
        response = client.post("/api/route", json=payload)
        data = response.json()
        assert "ticket_id" in data
        assert "domain" in data
        assert "resolved_by" in data
        assert "voters" in data
        assert "evidence" in data
        assert "elapsed_ms" in data

    def test_route_missing_field_returns_422(self):
        # description is required — omitting it should yield 422 Unprocessable Entity
        payload = {"id": "T-104", "title": "No description"}
        response = client.post("/api/route", json=payload)
        assert response.status_code == 422
