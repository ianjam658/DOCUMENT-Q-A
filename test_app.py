import os

os.environ.setdefault("GROQ_API_KEY", "test-key")
os.environ.setdefault("DATABASE_URL", "postgresql://test:test@localhost:5432/test")
os.environ.setdefault("API_SECRET_KEY", "test-secret")
os.environ["SKIP_DB_INIT"] = "1"  # no real DB available during unit tests

import pytest


@pytest.fixture
def client():
    from app import app as flask_app
    flask_app.config["TESTING"] = True
    with flask_app.test_client() as c:
        yield c


def test_health(client):
    res = client.get("/health")
    assert res.status_code == 200
    assert res.get_json()["status"] == "ok"


def test_ask_requires_auth(client):
    res = client.post("/ask", json={"question": "hi"})
    assert res.status_code == 401


def test_upload_requires_auth(client):
    res = client.post("/upload")
    assert res.status_code == 401


def test_ask_rejects_empty_question(client):
    res = client.post("/ask", json={"question": ""}, headers={"X-API-Key": "test-secret"})
    assert res.status_code == 400
