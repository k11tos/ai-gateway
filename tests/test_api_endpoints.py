import app
from ollama_client import UpstreamServiceError


def test_health_endpoint_returns_ready_payload(client, monkeypatch):
    monkeypatch.setattr(app, "health_check", lambda: None)

    response = client.get("/health", headers={"X-Request-Id": "health-id"})

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "upstream": "ok"}
    assert response.headers["X-Request-Id"] == "health-id"


def test_models_endpoint_returns_model_list(client, monkeypatch):
    monkeypatch.setattr(app, "list_models", lambda: ["a", "b"])

    response = client.get("/models")

    assert response.status_code == 200
    assert response.json() == {"models": ["a", "b"]}


def test_models_endpoint_returns_502_on_upstream_error(client, monkeypatch):
    def fail():
        raise UpstreamServiceError("boom")

    monkeypatch.setattr(app, "list_models", fail)

    response = client.get("/models")

    assert response.status_code == 502
    assert response.json() == {"detail": "boom"}


def test_chat_uses_default_model_when_omitted(client, monkeypatch):
    calls = {}

    def fake_generate(prompt, model):
        calls["prompt"] = prompt
        calls["model"] = model
        return "generated"

    monkeypatch.setattr(app, "generate", fake_generate)

    response = client.post("/chat", json={"prompt": "hello"})

    assert response.status_code == 200
    assert calls == {"prompt": "hello", "model": app.DEFAULT_MODEL}
    assert response.json() == {"model": app.DEFAULT_MODEL, "response": "generated"}


def test_chat_uses_explicit_model_when_provided(client, monkeypatch):
    calls = {}

    def fake_generate(prompt, model):
        calls["prompt"] = prompt
        calls["model"] = model
        return "generated"

    monkeypatch.setattr(app, "generate", fake_generate)

    response = client.post("/chat", json={"prompt": "hello", "model": "custom"})

    assert response.status_code == 200
    assert calls == {"prompt": "hello", "model": "custom"}
    assert response.json() == {"model": "custom", "response": "generated"}


def test_generate_endpoint_returns_502_on_upstream_error(client, monkeypatch):
    def fail(prompt, model):
        raise UpstreamServiceError("generate failed")

    monkeypatch.setattr(app, "generate", fail)

    response = client.post("/generate", json={"prompt": "hello"})

    assert response.status_code == 502
    assert response.json() == {"detail": "generate failed"}


def test_generate_stream_returns_normalized_chunks(client, monkeypatch):
    seen = {}

    def fake_stream(prompt, model):
        seen["prompt"] = prompt
        seen["model"] = model
        return iter([
            '{"response":"hello"}\n',
            '{"response":" world"}\n',
            '{"done":true}\n',
        ])

    monkeypatch.setattr(app, "generate_stream", fake_stream)

    with client.stream("POST", "/generate_stream", json={"prompt": "hi"}) as response:
        chunks = list(response.iter_lines())

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("application/x-ndjson")
    assert seen == {"prompt": "hi", "model": app.DEFAULT_MODEL}
    assert chunks == [
        '{"response": "hello", "done": false}',
        '{"response": " world", "done": false}',
        '{"done": true}',
    ]


def test_generate_stream_returns_502_when_dependency_fails(client, monkeypatch):
    def fail(prompt, model):
        raise UpstreamServiceError("stream failed")

    monkeypatch.setattr(app, "generate_stream", fail)

    response = client.post("/generate_stream", json={"prompt": "hi"})

    assert response.status_code == 502
    assert response.json() == {"detail": "stream failed"}


def test_presets_endpoint_returns_static_presets(client):
    response = client.get("/presets", headers={"X-Request-Id": "preset-req-1"})

    assert response.status_code == 200
    assert response.headers["X-Request-Id"] == "preset-req-1"
    assert response.json() == {"presets": list(app.PRESETS_API_CONTRACT)}


def test_presets_response_contract_shape_and_order(client):
    response = client.get("/presets")

    assert response.status_code == 200

    payload = response.json()
    assert set(payload.keys()) == {"presets"}
    assert isinstance(payload["presets"], list)

    expected_names_in_order = ["normal", "coder", "english", "quant"]
    preset_names = [preset["name"] for preset in payload["presets"]]
    assert preset_names == expected_names_in_order

    for preset in payload["presets"]:
        assert set(preset.keys()) == {"name", "description"}
        assert isinstance(preset["name"], str)
        assert isinstance(preset["description"], str)


def test_presets_names_are_unique(client):
    response = client.get("/presets")

    assert response.status_code == 200

    preset_names = [preset["name"] for preset in response.json()["presets"]]
    assert len(preset_names) == len(set(preset_names))
