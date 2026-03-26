import app
from services import presets
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


def test_version_endpoint_returns_safe_fallbacks_when_env_missing(client, monkeypatch):
    monkeypatch.delenv("APP_VERSION", raising=False)
    monkeypatch.delenv("VERSION", raising=False)
    monkeypatch.delenv("COMMIT_SHA", raising=False)
    monkeypatch.delenv("GIT_SHA", raising=False)
    monkeypatch.delenv("GITHUB_SHA", raising=False)

    response = client.get("/version")

    assert response.status_code == 200
    assert response.json() == {
        "app_version": "unavailable",
        "commit_sha": "unavailable",
        "status": "unavailable",
    }




def test_version_endpoint_truncates_full_commit_sha(client, monkeypatch):
    monkeypatch.setenv("APP_VERSION", "1.2.3")
    monkeypatch.setenv("COMMIT_SHA", "abc1234def5678")

    response = client.get("/version")

    assert response.status_code == 200
    assert response.json() == {
        "app_version": "1.2.3",
        "commit_sha": "abc1234",
        "status": "ok",
    }

def test_version_endpoint_returns_env_values_when_present(client, monkeypatch):
    monkeypatch.setenv("APP_VERSION", "1.2.3")
    monkeypatch.setenv("COMMIT_SHA", "abc1234")

    response = client.get("/version")

    assert response.status_code == 200
    assert response.json() == {
        "app_version": "1.2.3",
        "commit_sha": "abc1234",
        "status": "ok",
    }


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
    assert response.json() == {
        "provider": app.DEFAULT_PROVIDER,
        "model": app.DEFAULT_MODEL,
        "response": "generated",
    }


def test_chat_accepts_ollama_provider(client, monkeypatch):
    calls = {}

    def fake_generate(prompt, model):
        calls["prompt"] = prompt
        calls["model"] = model
        return "generated"

    monkeypatch.setattr(app, "generate", fake_generate)

    response = client.post(
        "/chat", json={"prompt": "hello", "provider": "ollama"}
    )

    assert response.status_code == 200
    assert calls == {"prompt": "hello", "model": app.DEFAULT_MODEL}
    assert response.json()["provider"] == app.DEFAULT_PROVIDER


def test_chat_accepts_normalized_ollama_provider(client, monkeypatch):
    calls = {}

    def fake_generate(prompt, model):
        calls["prompt"] = prompt
        calls["model"] = model
        return "generated"

    monkeypatch.setattr(app, "generate", fake_generate)

    response = client.post(
        "/chat", json={"prompt": "hello", "provider": " OLLAMA "}
    )

    assert response.status_code == 200
    assert calls == {"prompt": "hello", "model": app.DEFAULT_MODEL}


def test_chat_rejects_unsupported_provider(client):
    response = client.post(
        "/chat", json={"prompt": "hello", "provider": "openai"}
    )

    assert response.status_code == 400
    assert response.json() == {
        "detail": "Unsupported provider 'openai'. Supported providers: ollama"
    }


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
    assert response.json() == {
        "provider": app.DEFAULT_PROVIDER,
        "model": "custom",
        "response": "generated",
    }


def test_chat_applies_coder_preset(client, monkeypatch):
    calls = {}

    def fake_generate(prompt, model):
        calls["prompt"] = prompt
        calls["model"] = model
        return "generated"

    monkeypatch.setattr(app, "generate", fake_generate)

    response = client.post("/chat", json={"prompt": "hello", "preset": "coder"})

    assert response.status_code == 200
    assert calls == {
        "prompt": presets.PRESET_BY_NAME["coder"]["prompt_prefix"] + "hello",
        "model": app.DEFAULT_MODEL,
    }


def test_chat_accepts_normalized_preset_input(client, monkeypatch):
    calls = {}

    def fake_generate(prompt, model):
        calls["prompt"] = prompt
        calls["model"] = model
        return "generated"

    monkeypatch.setattr(app, "generate", fake_generate)

    response = client.post("/chat", json={"prompt": "hello", "preset": " CODER "})

    assert response.status_code == 200
    assert calls == {
        "prompt": presets.PRESET_BY_NAME["coder"]["prompt_prefix"] + "hello",
        "model": app.DEFAULT_MODEL,
    }


def test_chat_applies_preset_inside_gateway_boundary(client, monkeypatch):
    seen = {}

    def fake_apply(prompt, preset):
        seen["apply_input"] = (prompt, preset)
        return f"gateway-shaped::{prompt}"

    def fake_generate(prompt, model):
        seen["upstream_input"] = (prompt, model)
        return "generated"

    monkeypatch.setattr(app, "_apply_gateway_prompt_preset", fake_apply)
    monkeypatch.setattr(app, "generate", fake_generate)

    response = client.post("/chat", json={"prompt": "raw-input", "preset": "coder"})

    assert response.status_code == 200
    assert seen["apply_input"] == ("raw-input", "coder")
    assert seen["upstream_input"] == ("gateway-shaped::raw-input", app.DEFAULT_MODEL)


def test_apply_prompt_preset_uses_same_source_as_presets_endpoint(client):
    response = client.get("/presets")

    assert response.status_code == 200

    endpoint_names = [preset["name"] for preset in response.json()["presets"]]
    shared_names = [preset["name"] for preset in presets.PRESET_DEFINITIONS]

    assert endpoint_names == shared_names

    for preset_name in endpoint_names:
        expected = presets.PRESET_BY_NAME[preset_name]["prompt_prefix"] + "probe"
        assert presets.apply_prompt_preset("probe", preset_name) == expected


def test_chat_rejects_unknown_preset(client):
    response = client.post("/chat", json={"prompt": "hello", "preset": "unknown"})

    assert response.status_code == 400
    assert response.json()["detail"] == (
        "Unknown preset 'unknown'. Valid presets: normal, coder, english, quant"
    )


def test_chat_resolves_model_alias_when_configured(client, monkeypatch):
    monkeypatch.setattr(app, "MODEL_ALIASES", {"fast": "llama3.2:3b"})
    calls = {}

    def fake_generate(prompt, model):
        calls["prompt"] = prompt
        calls["model"] = model
        return "generated"

    monkeypatch.setattr(app, "generate", fake_generate)

    response = client.post("/chat", json={"prompt": "hello", "model": "fast"})

    assert response.status_code == 200
    assert calls == {"prompt": "hello", "model": "llama3.2:3b"}
    assert response.json() == {
        "provider": app.DEFAULT_PROVIDER,
        "model": "fast",
        "resolved_model": "llama3.2:3b",
        "response": "generated",
    }


def test_generate_endpoint_returns_502_on_upstream_error(client, monkeypatch):
    def fail(prompt, model):
        raise UpstreamServiceError("generate failed")

    monkeypatch.setattr(app, "generate", fail)

    response = client.post("/generate", json={"prompt": "hello"})

    assert response.status_code == 502
    assert response.json() == {"detail": "generate failed"}


def test_generate_returns_requested_and_resolved_model_when_alias_matches(client, monkeypatch):
    monkeypatch.setattr(app, "MODEL_ALIASES", {"smart": "llama3.1:8b"})
    calls = {}

    def fake_generate(prompt, model):
        calls["prompt"] = prompt
        calls["model"] = model
        return "generated"

    monkeypatch.setattr(app, "generate", fake_generate)

    response = client.post("/generate", json={"prompt": "hello", "model": "smart"})

    assert response.status_code == 200
    assert calls == {"prompt": "hello", "model": "llama3.1:8b"}
    assert response.json() == {
        "provider": app.DEFAULT_PROVIDER,
        "model": "smart",
        "resolved_model": "llama3.1:8b",
        "response": "generated",
    }


def test_generate_applies_english_preset(client, monkeypatch):
    calls = {}

    def fake_generate(prompt, model):
        calls["prompt"] = prompt
        calls["model"] = model
        return "generated"

    monkeypatch.setattr(app, "generate", fake_generate)

    response = client.post("/generate", json={"prompt": "hi", "preset": "english"})

    assert response.status_code == 200
    assert calls == {
        "prompt": presets.PRESET_BY_NAME["english"]["prompt_prefix"] + "hi",
        "model": app.DEFAULT_MODEL,
    }


def test_generate_applies_preset_inside_gateway_boundary(client, monkeypatch):
    seen = {}

    def fake_apply(prompt, preset):
        seen["apply_input"] = (prompt, preset)
        return f"gateway-shaped::{prompt}"

    def fake_generate(prompt, model):
        seen["upstream_input"] = (prompt, model)
        return "generated"

    monkeypatch.setattr(app, "_apply_gateway_prompt_preset", fake_apply)
    monkeypatch.setattr(app, "generate", fake_generate)

    response = client.post("/generate", json={"prompt": "raw-input", "preset": "english"})

    assert response.status_code == 200
    assert seen["apply_input"] == ("raw-input", "english")
    assert seen["upstream_input"] == ("gateway-shaped::raw-input", app.DEFAULT_MODEL)


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


def test_generate_rejects_unsupported_provider(client):
    response = client.post(
        "/generate", json={"prompt": "hello", "provider": "anthropic"}
    )

    assert response.status_code == 400
    assert response.json() == {
        "detail": "Unsupported provider 'anthropic'. Supported providers: ollama"
    }


def test_generate_stream_rejects_unsupported_provider(client):
    response = client.post(
        "/generate_stream", json={"prompt": "hello", "provider": "gemini"}
    )

    assert response.status_code == 400
    assert response.json() == {
        "detail": "Unsupported provider 'gemini'. Supported providers: ollama"
    }


def test_generate_stream_resolves_model_alias(client, monkeypatch):
    monkeypatch.setattr(app, "MODEL_ALIASES", {"coding": "qwen2.5-coder:7b"})
    seen = {}

    def fake_stream(prompt, model):
        seen["prompt"] = prompt
        seen["model"] = model
        return iter(['{"done":true}\n'])

    monkeypatch.setattr(app, "generate_stream", fake_stream)

    response = client.post(
        "/generate_stream", json={"prompt": "build", "model": "coding"}
    )

    assert response.status_code == 200
    assert seen == {"prompt": "build", "model": "qwen2.5-coder:7b"}


def test_generate_stream_applies_quant_preset(client, monkeypatch):
    seen = {}

    def fake_stream(prompt, model):
        seen["prompt"] = prompt
        seen["model"] = model
        return iter(['{"done":true}\n'])

    monkeypatch.setattr(app, "generate_stream", fake_stream)

    response = client.post(
        "/generate_stream", json={"prompt": "solve", "preset": "quant"}
    )

    assert response.status_code == 200
    assert seen == {
        "prompt": presets.PRESET_BY_NAME["quant"]["prompt_prefix"] + "solve",
        "model": app.DEFAULT_MODEL,
    }


def test_generate_stream_applies_preset_inside_gateway_boundary(client, monkeypatch):
    seen = {}

    def fake_apply(prompt, preset):
        seen["apply_input"] = (prompt, preset)
        return f"gateway-shaped::{prompt}"

    def fake_stream(prompt, model):
        seen["upstream_input"] = (prompt, model)
        return iter(['{"done":true}\n'])

    monkeypatch.setattr(app, "_apply_gateway_prompt_preset", fake_apply)
    monkeypatch.setattr(app, "generate_stream", fake_stream)

    response = client.post(
        "/generate_stream", json={"prompt": "raw-input", "preset": "quant"}
    )

    assert response.status_code == 200
    assert seen["apply_input"] == ("raw-input", "quant")
    assert seen["upstream_input"] == ("gateway-shaped::raw-input", app.DEFAULT_MODEL)


def test_generate_stream_rejects_unknown_preset(client):
    response = client.post(
        "/generate_stream", json={"prompt": "hello", "preset": "unknown"}
    )

    assert response.status_code == 400
    assert response.json()["detail"] == (
        "Unknown preset 'unknown'. Valid presets: normal, coder, english, quant"
    )


def test_generate_rejects_unknown_preset(client):
    response = client.post("/generate", json={"prompt": "hello", "preset": "unknown"})

    assert response.status_code == 400
    assert response.json()["detail"] == (
        "Unknown preset 'unknown'. Valid presets: normal, coder, english, quant"
    )


def test_chat_invalid_provider_does_not_call_generate(client, monkeypatch):
    called = {"generate": False}

    def fake_generate(prompt, model):
        called["generate"] = True
        return "generated"

    monkeypatch.setattr(app, "generate", fake_generate)

    response = client.post("/chat", json={"prompt": "hello", "provider": "openai"})

    assert response.status_code == 400
    assert called["generate"] is False


def test_generate_stream_invalid_provider_does_not_call_generate_stream(client, monkeypatch):
    called = {"generate_stream": False}

    def fake_stream(prompt, model):
        called["generate_stream"] = True
        return iter(['{"done":true}\n'])

    monkeypatch.setattr(app, "generate_stream", fake_stream)

    response = client.post(
        "/generate_stream", json={"prompt": "hello", "provider": "gemini"}
    )

    assert response.status_code == 400
    assert called["generate_stream"] is False


def test_generate_keeps_original_model_when_alias_not_found(client, monkeypatch):
    monkeypatch.setattr(app, "MODEL_ALIASES", {"smart": "mistral:7b"})
    calls = {}

    def fake_generate(prompt, model):
        calls["prompt"] = prompt
        calls["model"] = model
        return "generated"

    monkeypatch.setattr(app, "generate", fake_generate)

    response = client.post("/generate", json={"prompt": "hello", "model": "exact:1"})

    assert response.status_code == 200
    assert calls == {"prompt": "hello", "model": "exact:1"}
    assert response.json() == {
        "provider": app.DEFAULT_PROVIDER,
        "model": "exact:1",
        "response": "generated",
    }


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
    assert response.json() == {
        "presets": [
            {"name": p["name"], "description": p["description"], "prompt_prefix": p["prompt_prefix"]}
            for p in presets.PRESET_DEFINITIONS
        ]
    }


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
        assert set(preset.keys()) == {"name", "description", "prompt_prefix"}
        assert isinstance(preset["name"], str)
        assert isinstance(preset["description"], str)
        assert isinstance(preset["prompt_prefix"], str)


def test_presets_names_are_unique(client):
    response = client.get("/presets")

    assert response.status_code == 200

    preset_names = [preset["name"] for preset in response.json()["presets"]]
    assert len(preset_names) == len(set(preset_names))


def test_config_endpoint_returns_safe_runtime_summary(client, monkeypatch):
    monkeypatch.setattr(app, "DEFAULT_MODEL", "deepseek-r1:8b")
    monkeypatch.setattr(app, "OLLAMA_BASE_URL", "http://ollama.local:11434")
    monkeypatch.setattr(app, "LEGACY_REQUEST_TIMEOUT", 42.0)
    monkeypatch.setattr(app, "OLLAMA_CONNECT_TIMEOUT", 3.0)
    monkeypatch.setattr(app, "OLLAMA_READ_TIMEOUT", 45.0)
    monkeypatch.setattr(app, "OLLAMA_STREAM_READ_TIMEOUT", 120.0)
    monkeypatch.setattr(app, "RETRY_COUNT", 5)

    response = client.get("/config")

    assert response.status_code == 200
    assert response.json() == {
        "default_model": "deepseek-r1:8b",
        "ollama_configured": True,
        "request_timeout_s": 42.0,
        "ollama_connect_timeout_s": 3.0,
        "ollama_read_timeout_s": 45.0,
        "ollama_stream_read_timeout_s": 120.0,
        "retry_count": 5,
    }


def test_providers_endpoint_returns_discovery_payload(client):
    response = client.get("/providers")

    assert response.status_code == 200
    assert response.json() == {
        "supported_providers": ["ollama"],
        "default_provider": "ollama",
    }


def test_provider_validation_uses_supported_providers_source_of_truth(client, monkeypatch):
    monkeypatch.setattr(app, "SUPPORTED_PROVIDERS", ("ollama", "openai"))
    monkeypatch.setattr(app, "DEFAULT_PROVIDER", "openai")
    monkeypatch.setattr(
        app,
        "PROVIDER_ADAPTERS",
        {
            "ollama": app.PROVIDER_ADAPTERS["ollama"],
            "openai": app.PROVIDER_ADAPTERS["ollama"],
        },
    )

    response = client.get("/providers")

    assert response.status_code == 200
    assert response.json() == {
        "supported_providers": ["ollama", "openai"],
        "default_provider": "openai",
    }

    calls = {}

    def fake_generate(prompt, model):
        calls["prompt"] = prompt
        calls["model"] = model
        return "generated"

    monkeypatch.setattr(app, "generate", fake_generate)

    accepted = client.post("/chat", json={"prompt": "hello", "provider": "OPENAI"})

    assert accepted.status_code == 200
    assert accepted.json()["provider"] == "openai"

    rejected = client.post("/chat", json={"prompt": "hello", "provider": "anthropic"})

    assert rejected.status_code == 400
    assert rejected.json() == {
        "detail": "Unsupported provider 'anthropic'. Supported providers: ollama, openai"
    }


def test_provider_adapter_resolution_fails_when_supported_provider_has_no_adapter(client, monkeypatch):
    monkeypatch.setattr(app, "SUPPORTED_PROVIDERS", ("ollama", "openai"))
    monkeypatch.setattr(app, "PROVIDER_ADAPTERS", {"ollama": app.PROVIDER_ADAPTERS["ollama"]})

    response = client.post("/chat", json={"prompt": "hello", "provider": "openai"})

    assert response.status_code == 500
    assert response.json() == {
        "detail": "Provider adapter for 'openai' is not configured."
    }


def test_load_model_aliases_ignores_malformed_and_empty_csv_entries(monkeypatch, caplog):
    monkeypatch.setenv("MODEL_ALIAS_FAST", "base-fast")
    monkeypatch.setenv(
        "MODEL_ALIASES",
        "broken,no-model=,=missing-alias, smart = llama3.1:8b ,coding=qwen2.5-coder:7b",
    )

    with caplog.at_level("WARNING"):
        aliases = app._load_model_aliases()

    assert aliases["fast"] == "base-fast"
    assert aliases["smart"] == "llama3.1:8b"
    assert aliases["coding"] == "qwen2.5-coder:7b"
    assert "no-model" not in aliases
    assert "" not in aliases

    messages = [record.message for record in caplog.records]
    assert any("model_alias_config_invalid pair=broken" in message for message in messages)
    assert any(
        "model_alias_config_invalid_empty_model pair=no-model=" in message
        for message in messages
    )
    assert any(
        "model_alias_config_invalid_empty_alias pair==missing-alias" in message
        for message in messages
    )


def _mock_agent_brain_metrics(monkeypatch, status):
    monkeypatch.setattr(app, "collect_local_server_status", lambda: status)


def _assert_agent_brain_response(response, *, expected_status, expected_summary, expected_lines):
    assert response.status_code == 200

    payload = response.json()

    assert set(payload) == {"status", "overall_status", "summary", "message_lines"}
    assert payload["status"] == "ok"
    assert payload["overall_status"] == expected_status
    assert payload["summary"] == expected_summary
    assert isinstance(payload["message_lines"], list)
    assert payload["message_lines"]
    assert payload["message_lines"] == expected_lines


def test_agent_brain_returns_ok_when_all_metrics_are_present(client, monkeypatch):
    _mock_agent_brain_metrics(
        monkeypatch,
        {
            "gateway": "ok",
            "disk_percent": 71.2,
            "memory_percent": 53.4,
            "load_average": [0.12, 0.20, 0.18],
            "uptime_seconds": 3723.0,
            "service_states": {"ai-gateway": "active", "telegram-bot": "active"},
            "docker_summary": {"running": 2, "stopped": 1},
        },
    )

    response = client.post("/agent/brain")

    _assert_agent_brain_response(
        response,
        expected_status="ok",
        expected_summary={
            "gateway": "ok",
            "disk_percent": 71.2,
            "memory_percent": 53.4,
            "load_average": [0.12, 0.2, 0.18],
            "uptime_seconds": 3723.0,
            "service_states": {"ai-gateway": "active", "telegram-bot": "active"},
            "docker_summary": {"running": 2, "stopped": 1},
        },
        expected_lines=[
            "ai-gateway 정상",
            "디스크 사용률 71.2%입니다.",
            "메모리 사용률 53.4%입니다.",
            "로드 평균 0.12, 0.20, 0.18입니다.",
            "가동 시간 1시간 2분입니다.",
            "서비스 상태 ai-gateway=active, telegram-bot=active.",
            "Docker 컨테이너 실행 2개, 중지 1개입니다.",
            "현재 즉시 대응이 필요한 징후는 없습니다.",
        ],
    )


def test_agent_brain_returns_partial_when_one_metric_is_missing(client, monkeypatch):
    _mock_agent_brain_metrics(
        monkeypatch,
        {
            "gateway": "ok",
            "disk_percent": None,
            "memory_percent": 53.4,
            "load_average": [0.12, 0.20, 0.18],
            "uptime_seconds": None,
            "service_states": {"ai-gateway": "active", "telegram-bot": "active"},
            "docker_summary": None,
        },
    )

    response = client.post("/agent/brain")

    _assert_agent_brain_response(
        response,
        expected_status="partial",
        expected_summary={
            "gateway": "ok",
            "disk_percent": None,
            "memory_percent": 53.4,
            "load_average": [0.12, 0.2, 0.18],
            "uptime_seconds": None,
            "service_states": {"ai-gateway": "active", "telegram-bot": "active"},
            "docker_summary": None,
        },
        expected_lines=[
            "ai-gateway 일부 지표 확인 필요",
            "디스크 사용률을 확인할 수 없습니다.",
            "메모리 사용률 53.4%입니다.",
            "로드 평균 0.12, 0.20, 0.18입니다.",
            "가동 시간을 확인할 수 없습니다.",
            "서비스 상태 ai-gateway=active, telegram-bot=active.",
            "Docker 상태를 확인할 수 없습니다.",
            "일부 지표가 없어 추가 확인이 필요합니다.",
        ],
    )


def test_agent_brain_returns_warning_when_memory_percent_is_high(client, monkeypatch):
    _mock_agent_brain_metrics(
        monkeypatch,
        {
            "gateway": "ok",
            "disk_percent": 71.2,
            "memory_percent": 90.0,
            "load_average": [0.12, 0.20, 0.18],
            "uptime_seconds": 3600.0,
            "service_states": {"ai-gateway": "active", "telegram-bot": "active"},
            "docker_summary": {"running": 1, "stopped": 0},
        },
    )

    response = client.post("/agent/brain")

    _assert_agent_brain_response(
        response,
        expected_status="warning",
        expected_summary={
            "gateway": "ok",
            "disk_percent": 71.2,
            "memory_percent": 90.0,
            "load_average": [0.12, 0.2, 0.18],
            "uptime_seconds": 3600.0,
            "service_states": {"ai-gateway": "active", "telegram-bot": "active"},
            "docker_summary": {"running": 1, "stopped": 0},
        },
        expected_lines=[
            "ai-gateway 주의",
            "디스크 사용률 71.2%입니다.",
            "메모리 사용률 90.0%로 높습니다.",
            "로드 평균 0.12, 0.20, 0.18입니다.",
            "가동 시간 1시간 0분입니다.",
            "서비스 상태 ai-gateway=active, telegram-bot=active.",
            "Docker 컨테이너 실행 1개, 중지 0개입니다.",
            "자원 사용률이 높아 즉시 점검이 필요합니다.",
        ],
    )


def test_agent_brain_returns_warning_when_service_is_down(client, monkeypatch):
    _mock_agent_brain_metrics(
        monkeypatch,
        {
            "gateway": "ok",
            "disk_percent": 71.2,
            "memory_percent": 53.4,
            "load_average": [0.12, 0.20, 0.18],
            "uptime_seconds": 3600.0,
            "service_states": {"ai-gateway": "failed", "telegram-bot": "active"},
            "docker_summary": {"running": 1, "stopped": 0},
        },
    )

    response = client.post("/agent/brain")

    _assert_agent_brain_response(
        response,
        expected_status="warning",
        expected_summary={
            "gateway": "ok",
            "disk_percent": 71.2,
            "memory_percent": 53.4,
            "load_average": [0.12, 0.2, 0.18],
            "uptime_seconds": 3600.0,
            "service_states": {"ai-gateway": "failed", "telegram-bot": "active"},
            "docker_summary": {"running": 1, "stopped": 0},
        },
        expected_lines=[
            "ai-gateway 주의",
            "디스크 사용률 71.2%입니다.",
            "메모리 사용률 53.4%입니다.",
            "로드 평균 0.12, 0.20, 0.18입니다.",
            "가동 시간 1시간 0분입니다.",
            "서비스 상태 ai-gateway=failed, telegram-bot=active.",
            "Docker 컨테이너 실행 1개, 중지 0개입니다.",
            "서비스 상태 경고가 감지되어 즉시 점검이 필요합니다.",
        ],
    )
