import app


class FakeProviderAdapter:
    def __init__(self):
        self.calls = []

    def generate(self, *, prompt: str, model: str) -> str:
        self.calls.append(("generate", prompt, model))
        return "fake-generated"

    def generate_stream(self, *, prompt: str, model: str):
        self.calls.append(("generate_stream", prompt, model))
        return iter(['{"done":true}\n'])

    def list_models(self) -> list[str]:
        self.calls.append(("list_models",))
        return ["fake-a", "fake-b"]

    def embedding(self, *, text: str) -> list[float]:
        self.calls.append(("embedding", text))
        return [0.5]


def test_non_stream_generation_routes_through_provider_adapter_after_preset_shaping(client, monkeypatch):
    fake_adapter = FakeProviderAdapter()
    monkeypatch.setattr(app, "PROVIDER_ADAPTERS", {app.DEFAULT_PROVIDER: fake_adapter})

    response = client.post("/chat", json={"prompt": "hello", "preset": "coder"})

    assert response.status_code == 200
    assert response.json() == {
        "provider": app.DEFAULT_PROVIDER,
        "model": app.DEFAULT_MODEL,
        "response": "fake-generated",
    }
    assert fake_adapter.calls == [
        (
            "generate",
            app.preset_service.PRESET_BY_NAME["coder"]["prompt_prefix"] + "hello",
            app.DEFAULT_MODEL,
        )
    ]


def test_models_embedding_and_stream_use_provider_adapter(client, monkeypatch):
    fake_adapter = FakeProviderAdapter()
    monkeypatch.setattr(app, "PROVIDER_ADAPTERS", {app.DEFAULT_PROVIDER: fake_adapter})

    models_response = client.get("/models")
    embedding_response = client.post("/embedding", json={"text": "embed-me"})
    stream_response = client.post("/generate_stream", json={"prompt": "stream-me"})

    assert models_response.status_code == 200
    assert models_response.json() == {"models": ["fake-a", "fake-b"]}

    assert embedding_response.status_code == 200
    assert embedding_response.json() == {"embedding": [0.5]}

    assert stream_response.status_code == 200
    assert fake_adapter.calls == [
        ("list_models",),
        ("embedding", "embed-me"),
        ("generate_stream", "stream-me", app.DEFAULT_MODEL),
    ]
