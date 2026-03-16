import app
from ollama_client import UpstreamServiceError


def _metrics(client):
    response = client.get('/metrics')
    assert response.status_code == 200
    return response.json()


def test_metrics_start_at_zero_in_isolated_setup(client):
    app._reset_metrics()

    assert _metrics(client) == {
        'requests_total': 0,
        'chat_requests': 0,
        'stream_requests': 0,
        'embedding_requests': 0,
        'errors_total': 0,
    }


def test_chat_increments_metrics(client, monkeypatch):
    app._reset_metrics()
    monkeypatch.setattr(app, 'generate', lambda prompt, model: 'ok')

    response = client.post('/chat', json={'prompt': 'hello'})

    assert response.status_code == 200
    assert _metrics(client) == {
        'requests_total': 1,
        'chat_requests': 1,
        'stream_requests': 0,
        'embedding_requests': 0,
        'errors_total': 0,
    }


def test_generate_stream_increments_metrics(client, monkeypatch):
    app._reset_metrics()
    monkeypatch.setattr(app, 'generate_stream', lambda prompt, model: iter(['{"done":true}\n']))

    response = client.post('/generate_stream', json={'prompt': 'hello'})

    assert response.status_code == 200
    assert _metrics(client) == {
        'requests_total': 1,
        'chat_requests': 0,
        'stream_requests': 1,
        'embedding_requests': 0,
        'errors_total': 0,
    }


def test_embedding_increments_metrics(client, monkeypatch):
    app._reset_metrics()
    monkeypatch.setattr(app, 'embedding', lambda text: [0.1])

    response = client.post('/embedding', json={'text': 'hello'})

    assert response.status_code == 200
    assert _metrics(client) == {
        'requests_total': 1,
        'chat_requests': 0,
        'stream_requests': 0,
        'embedding_requests': 1,
        'errors_total': 0,
    }


def test_error_paths_increment_errors_total(client):
    app._reset_metrics()

    response = client.post('/chat', json={'prompt': 'hello', 'preset': 'unknown'})

    assert response.status_code == 400
    assert _metrics(client) == {
        'requests_total': 1,
        'chat_requests': 1,
        'stream_requests': 0,
        'embedding_requests': 0,
        'errors_total': 1,
    }


def test_upstream_failure_increments_errors_total(client, monkeypatch):
    app._reset_metrics()

    def fail(_text):
        raise UpstreamServiceError('embedding failed')

    monkeypatch.setattr(app, 'embedding', fail)

    response = client.post('/embedding', json={'text': 'hello'})

    assert response.status_code == 502
    assert _metrics(client) == {
        'requests_total': 1,
        'chat_requests': 0,
        'stream_requests': 0,
        'embedding_requests': 1,
        'errors_total': 1,
    }


def test_chat_invalid_provider_increments_metrics_and_errors(client):
    app._reset_metrics()

    response = client.post('/chat', json={'prompt': 'hello', 'provider': 'openai'})

    assert response.status_code == 400
    assert response.json() == {
        'detail': "Unsupported provider 'openai'. Supported providers: ollama"
    }
    assert _metrics(client) == {
        'requests_total': 1,
        'chat_requests': 1,
        'stream_requests': 0,
        'embedding_requests': 0,
        'errors_total': 1,
    }


def test_generate_stream_invalid_provider_increments_metrics_and_errors(client):
    app._reset_metrics()

    response = client.post('/generate_stream', json={'prompt': 'hello', 'provider': 'gemini'})

    assert response.status_code == 400
    assert response.json() == {
        'detail': "Unsupported provider 'gemini'. Supported providers: ollama"
    }
    assert _metrics(client) == {
        'requests_total': 1,
        'chat_requests': 0,
        'stream_requests': 1,
        'embedding_requests': 0,
        'errors_total': 1,
    }
