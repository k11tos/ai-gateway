import pytest

import app
from ollama_client import UpstreamServiceError


class ExplodingStream:
    def __iter__(self):
        yield '{"response":"first"}'
        raise RuntimeError("stream exploded")


def test_normalize_stream_skips_empty_response_chunks_and_preserves_order():
    upstream = iter(
        [
            '\n',
            '{"response":""}',
            '{"response":"first"}',
            '{"response":"second"}',
            '{"done":true}',
            '{"response":"ignored-after-done"}',
        ]
    )

    events = list(app._normalize_upstream_stream_events(upstream, request_id="r1"))

    assert events == [
        '{"response": "first", "done": false}\n',
        '{"response": "second", "done": false}\n',
        '{"done": true}\n',
    ]


def test_normalize_stream_propagates_generator_errors_after_yielding_existing_chunks():
    events = []

    with pytest.raises(RuntimeError, match="stream exploded"):
        for event in app._normalize_upstream_stream_events(ExplodingStream(), request_id="r2"):
            events.append(event)

    assert events == ['{"response": "first", "done": false}\n']


@pytest.mark.parametrize(
    ("endpoint", "payload", "missing_field"),
    [
        ("/chat", {}, "prompt"),
        ("/generate", {}, "prompt"),
        ("/generate_stream", {}, "prompt"),
        ("/embedding", {}, "text"),
    ],
)
def test_required_fields_return_validation_error(client, endpoint, payload, missing_field):
    response = client.post(endpoint, json=payload)

    assert response.status_code == 422
    body = response.json()
    assert body["detail"][0]["loc"][-1] == missing_field
    assert body["detail"][0]["type"] == "missing"


@pytest.mark.parametrize(
    ("endpoint", "payload", "bad_field"),
    [
        ("/chat", {"prompt": 123}, "prompt"),
        ("/generate", {"prompt": 123}, "prompt"),
        ("/generate_stream", {"prompt": 123}, "prompt"),
        ("/embedding", {"text": ["not", "a", "string"]}, "text"),
    ],
)
def test_invalid_field_types_return_validation_error(client, endpoint, payload, bad_field):
    response = client.post(endpoint, json=payload)

    assert response.status_code == 422
    body = response.json()
    assert body["detail"][0]["loc"][-1] == bad_field


@pytest.mark.parametrize("endpoint", ["/chat", "/generate", "/generate_stream", "/embedding"])
def test_malformed_json_body_returns_validation_error(client, endpoint):
    response = client.post(
        endpoint,
        content='{"prompt": "hello"',
        headers={"content-type": "application/json"},
    )

    assert response.status_code == 422
    assert response.json()["detail"][0]["type"] == "json_invalid"


def test_chat_uses_runtime_default_model_value(client, monkeypatch):
    monkeypatch.setattr(app, "DEFAULT_MODEL", "new-default-model")
    monkeypatch.setattr(app, "generate", lambda prompt, model: f"{prompt}:{model}")

    response = client.post("/chat", json={"prompt": "hello"})

    assert response.status_code == 200
    assert response.json() == {
        "provider": app.DEFAULT_PROVIDER,
        "model": "new-default-model",
        "response": "hello:new-default-model",
    }


def test_chat_explicit_model_overrides_runtime_default(client, monkeypatch):
    monkeypatch.setattr(app, "DEFAULT_MODEL", "new-default-model")
    monkeypatch.setattr(app, "generate", lambda prompt, model: model)

    response = client.post("/chat", json={"prompt": "hello", "model": "custom-model"})

    assert response.status_code == 200
    assert response.json() == {
        "provider": app.DEFAULT_PROVIDER,
        "model": "custom-model",
        "response": "custom-model",
    }


def test_chat_returns_502_when_generate_dependency_fails(client, monkeypatch):
    def fail(prompt, model):
        raise UpstreamServiceError("chat upstream failed")

    monkeypatch.setattr(app, "generate", fail)

    response = client.post("/chat", json={"prompt": "hello"})

    assert response.status_code == 502
    assert response.json() == {"detail": "chat upstream failed"}


def test_embedding_endpoint_returns_vector(client, monkeypatch):
    monkeypatch.setattr(app, "embedding", lambda text: [0.1, 0.2, 0.3])

    response = client.post("/embedding", json={"text": "hello"})

    assert response.status_code == 200
    assert response.json() == {"embedding": [0.1, 0.2, 0.3]}


def test_embedding_endpoint_returns_502_on_upstream_error(client, monkeypatch):
    def fail(text):
        raise UpstreamServiceError("embedding upstream failed")

    monkeypatch.setattr(app, "embedding", fail)

    response = client.post("/embedding", json={"text": "hello"})

    assert response.status_code == 502
    assert response.json() == {"detail": "embedding upstream failed"}


def test_health_ready_returns_503_on_upstream_failure(client, monkeypatch):
    def fail():
        raise UpstreamServiceError("ready check failed")

    monkeypatch.setattr(app, "health_check", fail)

    response = client.get("/health/ready")

    assert response.status_code == 503
    assert response.json() == {"detail": "ready check failed"}
