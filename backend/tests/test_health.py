from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_health_endpoint() -> None:
    response = client.get("/api/v1/health")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["service"] == "cybermind-api"
    assert "timestamp" in body
    assert body["neo4j"]["status"] in {
        "connected",
        "unreachable",
        "authentication_failure",
        "invalid_configuration",
    }
