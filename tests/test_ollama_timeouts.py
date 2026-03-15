import importlib
import sys

import pytest


@pytest.fixture
def ollama_module(monkeypatch):
    keys = [
        "REQUEST_TIMEOUT",
        "OLLAMA_CONNECT_TIMEOUT",
        "OLLAMA_READ_TIMEOUT",
        "OLLAMA_STREAM_READ_TIMEOUT",
    ]
    for key in keys:
        monkeypatch.delenv(key, raising=False)

    sys.modules.pop("ollama_client", None)
    import ollama_client

    module = importlib.reload(ollama_client)
    yield module


@pytest.fixture
def reloaded_ollama(monkeypatch):
    def _reload(**env):
        keys = [
            "REQUEST_TIMEOUT",
            "OLLAMA_CONNECT_TIMEOUT",
            "OLLAMA_READ_TIMEOUT",
            "OLLAMA_STREAM_READ_TIMEOUT",
        ]
        for key in keys:
            monkeypatch.delenv(key, raising=False)

        for key, value in env.items():
            monkeypatch.setenv(key, value)

        sys.modules.pop("ollama_client", None)
        import ollama_client

        return importlib.reload(ollama_client)

    return _reload


def test_timeout_env_parsing_accepts_valid_float_values(reloaded_ollama):
    module = reloaded_ollama(
        REQUEST_TIMEOUT="90",
        OLLAMA_CONNECT_TIMEOUT="1.5",
        OLLAMA_READ_TIMEOUT="12.25",
        OLLAMA_STREAM_READ_TIMEOUT="35.75",
    )

    assert module.OLLAMA_CONNECT_TIMEOUT == 1.5
    assert module.OLLAMA_READ_TIMEOUT == 12.25
    assert module.OLLAMA_STREAM_READ_TIMEOUT == 35.75


def test_timeout_env_parsing_invalid_value_falls_back_and_warns(reloaded_ollama, caplog):
    module = reloaded_ollama(REQUEST_TIMEOUT="7", OLLAMA_READ_TIMEOUT="oops")

    assert module.OLLAMA_READ_TIMEOUT == 7.0
    assert "Invalid OLLAMA_READ_TIMEOUT='oops'" in caplog.text


def test_timeout_env_parsing_non_positive_value_falls_back(reloaded_ollama):
    module = reloaded_ollama(REQUEST_TIMEOUT="11", OLLAMA_CONNECT_TIMEOUT="0")

    assert module.OLLAMA_CONNECT_TIMEOUT == 11.0


def test_generate_stream_uses_stream_timeout_tuple(ollama_module, monkeypatch):
    captured = {}

    class FakeResponse:
        def raise_for_status(self):
            return None

        def iter_lines(self, decode_unicode=True):
            yield '{"done":true}'

        def close(self):
            return None

    class FakeSession:
        def post(self, url, json, stream, timeout):
            captured["timeout"] = timeout
            return FakeResponse()

    monkeypatch.setattr(ollama_module, "_get_session", lambda: FakeSession())

    list(ollama_module.generate_stream("hello", "model"))

    assert captured["timeout"] == ollama_module.OLLAMA_STREAM_REQUEST_TIMEOUT


@pytest.mark.parametrize("method,args", [("generate", ("hello", "model")), ("embedding", ("hello",))])
def test_non_stream_calls_use_normal_timeout_tuple(
    ollama_module, monkeypatch, method, args
):
    captured = {}

    class FakeResponse:
        def raise_for_status(self):
            return None

        def json(self):
            if method == "generate":
                return {"response": "ok"}
            return {"embedding": [0.1, 0.2]}

    class FakeSession:
        def post(self, url, json, timeout):
            captured["timeout"] = timeout
            return FakeResponse()

    monkeypatch.setattr(ollama_module, "_get_session", lambda: FakeSession())

    getattr(ollama_module, method)(*args)

    assert captured["timeout"] == ollama_module.OLLAMA_REQUEST_TIMEOUT


def test_non_stream_get_calls_use_normal_timeout_tuple(ollama_module, monkeypatch):
    captured = {"timeouts": []}

    class FakeResponse:
        def raise_for_status(self):
            return None

        def json(self):
            return {"models": [{"name": "m1"}]}

    class FakeSession:
        def get(self, url, timeout):
            captured["timeouts"].append(timeout)
            return FakeResponse()

    monkeypatch.setattr(ollama_module, "_get_session", lambda: FakeSession())

    assert ollama_module.list_models() == ["m1"]
    ollama_module.health_check()

    assert captured["timeouts"] == [
        ollama_module.OLLAMA_REQUEST_TIMEOUT,
        ollama_module.OLLAMA_REQUEST_TIMEOUT,
    ]


def test_timeout_fallback_uses_legacy_request_timeout(reloaded_ollama):
    module = reloaded_ollama(REQUEST_TIMEOUT="13")

    assert module.LEGACY_REQUEST_TIMEOUT == 13.0
    assert module.OLLAMA_CONNECT_TIMEOUT == 13.0
    assert module.OLLAMA_READ_TIMEOUT == 13.0
    assert module.OLLAMA_STREAM_READ_TIMEOUT == 13.0
