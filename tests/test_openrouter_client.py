import json
from unittest.mock import Mock

import pytest
import requests

import app
import ollama_client as upstream

MODEL = "google/gemma-4-26b-a4b-it:free"
SECRET = "test-key-not-for-output"


def response(data=None, status=200, lines=()):
    result = Mock(status_code=status)
    result.json.return_value = data
    result.iter_lines.return_value = iter(lines)
    return result


def sse(*events):
    for event in events:
        yield "data: " + (event if isinstance(event, str) else json.dumps(event))
        yield ""


def delta(content=None, finish=None):
    return {"choices": [{"delta": {"content": content}, "finish_reason": finish}]}


@pytest.fixture
def session(monkeypatch):
    fake = Mock()
    monkeypatch.setattr(upstream, "_get_session", lambda: fake)
    monkeypatch.setattr(upstream, "OPENROUTER_API_KEY", SECRET)
    monkeypatch.setattr(upstream, "RETRY_COUNT", 0)
    return fake


@pytest.mark.parametrize("endpoint", ["/chat", "/generate"])
def test_generation_contract(client, session, endpoint):
    reply = response({"choices": [{"message": {"content": "안녕하세요"}}]})
    session.post.return_value = reply
    result = client.post(endpoint, json={"prompt": "hello"})
    assert result.status_code == 200
    assert result.json() == {"provider": "openrouter", "model": app.DEFAULT_MODEL, "response": "안녕하세요"}
    args, kwargs = session.post.call_args
    assert args == (upstream.OPENROUTER_BASE_URL + "/chat/completions",)
    assert kwargs["json"]["messages"] == [{"role": "user", "content": "hello"}]
    assert kwargs["json"]["stream"] is False
    assert kwargs["json"]["provider"]["max_price"] == {"prompt": 0, "completion": 0}
    assert kwargs["headers"] == {"Authorization": f"Bearer {SECRET}"}
    assert kwargs["timeout"] == upstream.OPENROUTER_REQUEST_TIMEOUT
    assert kwargs["allow_redirects"] is False
    reply.close.assert_called_once()


def test_stream_contract(client, session):
    reply = response(lines=[": heartbeat", "", *sse(delta("안녕"), delta(" world"), delta(finish="stop"), "[DONE]")])
    session.post.return_value = reply
    result = client.post("/generate_stream", json={"prompt": "hi"})
    assert result.status_code == 200
    assert result.headers["content-type"].startswith("application/x-ndjson")
    assert [json.loads(line) for line in result.text.splitlines()] == [
        {"response": "안녕", "done": False}, {"response": " world", "done": False}, {"done": True}
    ]
    assert session.post.call_args.kwargs["timeout"] == upstream.OPENROUTER_STREAM_REQUEST_TIMEOUT
    reply.close.assert_called_once()


@pytest.mark.parametrize("tail", [[], list(sse(delta(finish="stop")))])
def test_eof_without_done_is_incomplete(session, tail):
    reply = response(lines=[*sse(delta("first")), *tail])
    session.post.return_value = reply
    assert [json.loads(x) for x in upstream.generate_stream("hi", MODEL)] == [{"response": "first", "done": False}]
    reply.close.assert_called_once()


@pytest.mark.parametrize("bad", [{"error": {"message": SECRET}}, delta(finish="error"), delta(finish="content_filter"), "not-json", "[DONE]"])
def test_stream_errors_never_emit_done(session, bad, caplog):
    reply = response(lines=sse(delta("first"), bad, "[DONE]"))
    session.post.return_value = reply
    chunks = []
    with pytest.raises(upstream.UpstreamServiceError) as error:
        for chunk in upstream.generate_stream("hi", MODEL):
            chunks.append(json.loads(chunk))
    assert chunks == [{"response": "first", "done": False}]
    assert SECRET not in str(error.value) + caplog.text
    reply.close.assert_called_once()


def test_stream_disconnect_is_safe(session):
    def broken(**kwargs):
        yield from sse(delta("first"))
        raise requests.ConnectionError(SECRET)
    reply = response()
    reply.iter_lines.side_effect = broken
    session.post.return_value = reply
    iterator = upstream.generate_stream("hi", MODEL)
    assert json.loads(next(iterator))["response"] == "first"
    with pytest.raises(upstream.UpstreamServiceError, match="connection interrupted") as error:
        next(iterator)
    assert SECRET not in str(error.value)
    reply.close.assert_called_once()


@pytest.mark.parametrize("endpoint", ["/chat", "/generate", "/generate_stream"])
@pytest.mark.parametrize("model", ["paid/model", "paid/model:free ", "openrouter/free", "fast"])
def test_only_free_models_allowed(client, session, monkeypatch, endpoint, model):
    monkeypatch.setattr(app, "MODEL_ALIASES", {"fast": "paid/model"})
    result = client.post(endpoint, json={"prompt": "hi", "model": model})
    assert result.status_code == 400
    assert ":free" in result.json()["detail"]
    session.post.assert_not_called()


def test_free_alias_allowed(client, session, monkeypatch):
    monkeypatch.setattr(app, "MODEL_ALIASES", {"fast": MODEL})
    session.post.return_value = response({"choices": [{"message": {"content": "ok"}}]})
    result = client.post("/chat", json={"prompt": "hi", "model": "fast"})
    assert result.json()["resolved_model"] == MODEL
    assert session.post.call_args.kwargs["json"]["model"] == MODEL


@pytest.mark.parametrize("status", [401, 403, 429, 500, 302])
@pytest.mark.parametrize("endpoint,method,expected", [("/chat", "post", 502), ("/generate_stream", "post", 502), ("/models", "get", 502), ("/health/ready", "get", 503)])
def test_http_errors_are_safe(client, session, caplog, status, endpoint, method, expected):
    reply = response({"error": SECRET}, status=status)
    getattr(session, method).return_value = reply
    result = client.post(endpoint, json={"prompt": "hi"}) if method == "post" else client.get(endpoint)
    assert result.status_code == expected
    assert SECRET not in result.text + caplog.text
    assert getattr(session, method).call_count == 1
    reply.close.assert_called_once()


@pytest.mark.parametrize("data", [None, [], {}, {"error": SECRET}, {"choices": []}, {"choices": [{"message": {"content": None}}]}])
def test_invalid_generation_response(session, data):
    session.post.return_value = response(data)
    with pytest.raises(upstream.UpstreamServiceError):
        upstream.generate("hi", MODEL)


def test_invalid_json(session):
    session.post.return_value = response()
    session.post.return_value.json.side_effect = ValueError(SECRET)
    with pytest.raises(upstream.UpstreamServiceError) as error:
        upstream.generate("hi", MODEL)
    assert SECRET not in str(error.value)


def test_models_filters_free_and_keeps_contract(client, session):
    session.get.return_value = response({"data": [{"id": MODEL}, {"id": "paid/model"}, {"id": "openrouter/free"}]})
    assert client.get("/models").json() == {"models": [MODEL]}


def test_ready_uses_authenticated_key_endpoint(client, session):
    session.get.return_value = response({"data": {"label": "key"}})
    assert client.get("/health/ready").status_code == 200
    assert session.get.call_args.args == (upstream.OPENROUTER_BASE_URL + "/key",)
    assert session.get.call_args.kwargs["headers"]["Authorization"] == f"Bearer {SECRET}"


def test_missing_key_is_not_ready(client, session, monkeypatch):
    monkeypatch.setattr(upstream, "OPENROUTER_API_KEY", "")
    assert client.get("/health/ready").status_code == 503
    session.get.assert_not_called()


def test_network_error_is_safe(client, session, caplog):
    session.post.side_effect = requests.ConnectionError(SECRET)
    result = client.post("/chat", json={"prompt": "hi"})
    assert result.status_code == 502
    assert SECRET not in result.text + caplog.text


def test_embedding_unsupported_without_network(client, session):
    result = client.post("/embedding", json={"text": "hi"})
    assert result.status_code == 501
    assert "unsupported" in result.json()["detail"]
    session.post.assert_not_called()


def test_config_never_exposes_key(client, monkeypatch):
    monkeypatch.setattr(app, "OPENROUTER_API_KEY", SECRET)
    result = client.get("/config")
    assert result.json()["openrouter_configured"] is True
    assert SECRET not in result.text


@pytest.mark.parametrize("endpoint", ["/chat", "/generate", "/generate_stream"])
def test_ollama_is_no_longer_supported(client, session, endpoint):
    assert client.post(endpoint, json={"prompt": "hi", "provider": "ollama"}).status_code == 400
    session.post.assert_not_called()


def test_stream_length_finish_and_usage_frame(session):
    session.post.return_value = response(lines=sse(
        delta("ok"), delta(finish="length"), {"choices": [], "usage": {}}, "[DONE]"
    ))
    assert [json.loads(x) for x in upstream.generate_stream("hi", MODEL)] == [
        {"response": "ok", "done": False}, {"done": True}
    ]


def test_sse_multiline_event(session):
    session.post.return_value = response(lines=[
        'data: {"choices":',
        'data: [{"delta":{"content":"ok"},"finish_reason":"stop"}]}',
        "", "data: [DONE]", "",
    ])
    assert json.loads(list(upstream.generate_stream("hi", MODEL))[-1]) == {"done": True}


def test_stream_consumer_close_releases_response(session):
    reply = response(lines=sse(delta("first"), delta("second")))
    session.post.return_value = reply
    iterator = upstream.generate_stream("hi", MODEL)
    next(iterator)
    iterator.close()
    reply.close.assert_called_once()


def test_connection_retry_uses_same_free_model(session, monkeypatch):
    monkeypatch.setattr(upstream, "RETRY_COUNT", 1)
    sleep = Mock()
    monkeypatch.setattr(upstream.time, "sleep", sleep)
    session.post.side_effect = [requests.Timeout(SECRET), response({"choices": [{"message": {"content": "ok"}}]})]
    assert upstream.generate("hi", MODEL) == "ok"
    assert session.post.call_count == 2
    assert all(call.kwargs["json"]["model"] == MODEL for call in session.post.call_args_list)
    sleep.assert_called_once_with(1)


@pytest.mark.parametrize("data", [None, {}, {"data": []}, {"error": SECRET}])
def test_readiness_rejects_invalid_payload(client, session, data):
    session.get.return_value = response(data)
    assert client.get("/health/ready").status_code == 503


@pytest.mark.parametrize("data", [None, {}, {"data": {}}, {"data": [{}]}])
def test_models_rejects_invalid_payload(client, session, data):
    session.get.return_value = response(data)
    assert client.get("/models").status_code == 502


def test_non_stream_failure_with_partial_content_is_rejected(session):
    session.post.return_value = response({"choices": [{"message": {"content": "partial"}, "finish_reason": "error"}]})
    with pytest.raises(upstream.UpstreamServiceError):
        upstream.generate("hi", MODEL)
