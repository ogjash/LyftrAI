import os
import tempfile

from fastapi.testclient import TestClient

with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as database:
    os.environ["DATABASE_URL"] = f"sqlite:///{database.name}"
os.environ["LLM_API_KEYS"] = ""
os.environ["ENABLE_FAILURE_SIMULATION"] = "true"

from app.main import app


client = TestClient(app)


def test_health_and_validation():
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"

    response = client.post("/chat", json={"session_id": "test", "message": "   "})
    assert response.status_code == 422


def test_chat_cache_and_history():
    first = client.post(
        "/chat",
        json={"session_id": "cache-one", "message": "What is the capital of France?"},
    )
    assert first.status_code == 200
    assert first.json()["metadata"]["resolution_source"] == "LIVE_INFERENCE"

    second = client.post(
        "/chat",
        json={"session_id": "cache-two", "message": "What is the capital of France?"},
    )
    assert second.status_code == 200
    assert second.json()["metadata"]["resolution_source"] == "LLM_CACHE"
    assert second.json()["reply"] == first.json()["reply"]

    history = client.get("/sessions/cache-one/messages")
    assert history.status_code == 200
    assert len(history.json()["messages"]) == 2


def test_unknown_session_and_failed_simulation():
    unknown = client.get("/sessions/unknown/messages")
    assert unknown.status_code == 404

    failed = client.post(
        "/chat",
        json={"session_id": "failed", "message": "Say hello"},
        headers={"X-Simulate-Failure": "*=429"},
    )
    assert failed.status_code == 503
