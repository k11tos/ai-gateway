import app


def test_chat_echoes_incoming_request_id(client, monkeypatch):
    monkeypatch.setattr(app, "generate", lambda prompt, model: "ok")

    response = client.post(
        "/chat",
        headers={"X-Request-Id": "bot-req-123"},
        json={"prompt": "hello"},
    )

    assert response.status_code == 200
    assert response.headers["X-Request-Id"] == "bot-req-123"


def test_chat_generates_fallback_request_id(client, monkeypatch):
    monkeypatch.setattr(app, "generate", lambda prompt, model: "ok")

    response = client.post("/chat", json={"prompt": "hello"})

    assert response.status_code == 200
    request_id = response.headers.get("X-Request-Id")
    assert request_id is not None
    assert len(request_id) == 12


def test_health_live_sets_request_id_header(client):
    response = client.get("/health/live", headers={"X-Request-Id": "health-1"})

    assert response.status_code == 200
    assert response.headers["X-Request-Id"] == "health-1"
