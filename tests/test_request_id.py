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


def test_presets_logs_request_start_and_complete(client, caplog):
    caplog.set_level("INFO", logger="ai_gateway")

    response = client.get("/presets", headers={"X-Request-Id": "preset-log-1"})

    assert response.status_code == 200
    assert "phase=start endpoint=/presets request_id=preset-log-1" in caplog.text
    assert "phase=complete endpoint=/presets request_id=preset-log-1 outcome=success" in caplog.text


def test_presets_generates_fallback_request_id(client):
    response = client.get("/presets")

    assert response.status_code == 200
    request_id = response.headers.get("X-Request-Id")
    assert request_id is not None
    assert len(request_id) == 12


def test_config_echoes_incoming_request_id_and_logs(client, caplog):
    caplog.set_level("INFO", logger="ai_gateway")

    response = client.get("/config", headers={"X-Request-Id": "config-req-1"})

    assert response.status_code == 200
    assert response.headers["X-Request-Id"] == "config-req-1"
    assert "phase=start endpoint=/config request_id=config-req-1" in caplog.text
    assert "phase=complete endpoint=/config request_id=config-req-1 outcome=success" in caplog.text


def test_providers_echoes_incoming_request_id_and_logs(client, caplog):
    caplog.set_level("INFO", logger="ai_gateway")

    response = client.get("/providers", headers={"X-Request-Id": "providers-req-1"})

    assert response.status_code == 200
    assert response.headers["X-Request-Id"] == "providers-req-1"
    assert "phase=start endpoint=/providers request_id=providers-req-1" in caplog.text
    assert "phase=complete endpoint=/providers request_id=providers-req-1 outcome=success" in caplog.text


def test_providers_generates_fallback_request_id(client):
    response = client.get("/providers")

    assert response.status_code == 200
    request_id = response.headers.get("X-Request-Id")
    assert request_id is not None
    assert len(request_id) == 12


def test_chat_logs_normalized_preset_on_start_and_complete(client, monkeypatch, caplog):
    caplog.set_level("INFO", logger="ai_gateway")
    monkeypatch.setattr(app, "generate", lambda prompt, model: "ok")

    response = client.post(
        "/chat",
        headers={"X-Request-Id": "chat-log-1"},
        json={"prompt": "hello", "preset": " CODER "},
    )

    assert response.status_code == 200
    assert "phase=start endpoint=/chat request_id=chat-log-1 model=" in caplog.text
    assert "phase=complete endpoint=/chat request_id=chat-log-1 model=" in caplog.text
    assert "preset=coder" in caplog.text


def test_generate_logs_normalized_preset_on_start_and_complete(client, monkeypatch, caplog):
    caplog.set_level("INFO", logger="ai_gateway")
    monkeypatch.setattr(app, "generate", lambda prompt, model: "ok")

    response = client.post(
        "/generate",
        headers={"X-Request-Id": "generate-log-1"},
        json={"prompt": "hello", "preset": " ENGLISH "},
    )

    assert response.status_code == 200
    assert "phase=start endpoint=/generate request_id=generate-log-1 model=" in caplog.text
    assert "phase=complete endpoint=/generate request_id=generate-log-1 model=" in caplog.text
    assert "preset=english" in caplog.text


def test_generate_stream_logs_normalized_preset_on_start_and_complete(client, monkeypatch, caplog):
    caplog.set_level("INFO", logger="ai_gateway")
    monkeypatch.setattr(app, "generate_stream", lambda prompt, model: iter(['{"done":true}\n']))

    response = client.post(
        "/generate_stream",
        headers={"X-Request-Id": "stream-log-1"},
        json={"prompt": "hello", "preset": " QUANT "},
    )

    assert response.status_code == 200
    assert "phase=start endpoint=/generate_stream request_id=stream-log-1 model=" in caplog.text
    assert "phase=complete endpoint=/generate_stream request_id=stream-log-1 model=" in caplog.text
    assert "preset=quant" in caplog.text
