from app import _normalize_upstream_stream_events


def test_chunk_and_explicit_done():
    upstream = iter([
        '{"response":"hello"}',
        '{"done":true}',
    ])

    events = list(_normalize_upstream_stream_events(upstream))

    assert events == [
        '{"response": "hello", "done": false}\n',
        '{"done": true}\n',
    ]


def test_invalid_line_is_skipped():
    upstream = iter([
        "not-json",
        '{"response":"ok"}',
        '{"done":true}',
    ])

    events = list(_normalize_upstream_stream_events(upstream))

    assert events == [
        '{"response": "ok", "done": false}\n',
        '{"done": true}\n',
    ]


def test_premature_eof_without_done():
    upstream = iter([
        '{"response":"partial"}',
    ])

    events = list(_normalize_upstream_stream_events(upstream))

    assert events == ['{"response": "partial", "done": false}\n']


def test_empty_chunks_then_done_logs_empty_response_without_response_event(caplog):
    caplog.set_level("WARNING", logger="ai_gateway")
    upstream = iter([
        '{"response":""}',
        '{"response":"   "}',
        '{"done":true}',
    ])

    events = list(
        _normalize_upstream_stream_events(
            upstream,
            request_id="stream-empty-1",
            requested_model="fast",
            resolved_model="real-model",
        )
    )

    assert events == ['{"done": true}\n']
    assert "stream_empty_response endpoint=/generate_stream" in caplog.text
    assert "request_id=stream-empty-1" in caplog.text
    assert "requested_model=fast" in caplog.text
    assert "resolved_model=real-model" in caplog.text
    assert "reason=empty_response" in caplog.text
