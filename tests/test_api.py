"""ChangeAgent API regression tests."""
from __future__ import annotations
import pytest
from fastapi.testclient import TestClient
from api import app

@pytest.fixture()
def client():
    with TestClient(app) as c:
        yield c

class TestHealth:
    def test_health_returns_200(self, client):
        assert client.get("/health").status_code == 200

    def test_health_body(self, client):
        b = client.get("/health").json()
        assert b["status"]  == "healthy"
        assert b["service"] == "ChangeAgent"

class TestAssess:
    def test_assess_happy_path(self, client):
        r = client.post("/api/v1/change/assess",
                        json={"intent": "database schema migration for payment service",
                              "workflow_id": "test-wf-001"})
        assert r.status_code == 200

    def test_assess_response_shape(self, client):
        b = client.post("/api/v1/change/assess",
                        json={"intent": "change authentication provider to Okta",
                              "workflow_id": "test-wf-002"}).json()
        assert "change_id"           in b
        assert "workflow_id"         in b
        assert "source"              in b
        assert "change_type"         in b
        assert "risk_level"          in b
        assert "affected_systems"    in b
        assert "rollback_steps"      in b
        assert "approval_required"   in b
        assert "change_window"       in b
        assert "summary"             in b
        assert "next_steps"          in b

    def test_change_type_is_valid(self, client):
        b = client.post("/api/v1/change/assess",
                        json={"intent": "emergency hotfix deployment"}).json()
        assert b["change_type"] in ("STANDARD", "NORMAL", "EMERGENCY")

    def test_risk_level_is_valid(self, client):
        b = client.post("/api/v1/change/assess",
                        json={"intent": "change rollback plan"}).json()
        assert b["risk_level"] in ("CRITICAL", "HIGH", "MEDIUM", "LOW")

    def test_approval_required_is_bool(self, client):
        b = client.post("/api/v1/change/assess",
                        json={"intent": "CAB submission preparation"}).json()
        assert isinstance(b["approval_required"], bool)

    def test_affected_systems_is_list(self, client):
        b = client.post("/api/v1/change/assess",
                        json={"intent": "change impact assessment"}).json()
        assert isinstance(b["affected_systems"], list)

    def test_rollback_steps_is_list(self, client):
        b = client.post("/api/v1/change/assess",
                        json={"intent": "change request assessment"}).json()
        assert isinstance(b["rollback_steps"], list)

    def test_change_id_deterministic(self, client):
        payload = {"intent": "deploy to prod", "workflow_id": "wf-det-001"}
        id1 = client.post("/api/v1/change/assess", json=payload).json()["change_id"]
        id2 = client.post("/api/v1/change/assess", json=payload).json()["change_id"]
        assert id1 == id2

class TestRequests:
    def test_requests_returns_list(self, client):
        b = client.get("/api/v1/change/requests").json()
        assert "requests" in b
        assert "count"    in b
        assert isinstance(b["requests"], list)
