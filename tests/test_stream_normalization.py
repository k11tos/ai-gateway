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


def test_whitespace_chunk_between_content_chunks_is_preserved():
    upstream = iter([
        '{"response":"hello"}',
        '{"response":" "}',
        '{"response":"world"}',
        '{"done":true}',
    ])

    events = list(_normalize_upstream_stream_events(upstream))

    assert events == [
        '{"response": "hello", "done": false}\n',
        '{"response": " ", "done": false}\n',
        '{"response": "world", "done": false}\n',
        '{"done": true}\n',
    ]


def test_newline_and_indentation_chunks_after_content_are_preserved():
    upstream = iter([
        '{"response":"```python"}',
        '{"response":"\\n"}',
        '{"response":"    "}',
        '{"response":"print(1)"}',
        '{"done":true}',
    ])

    events = list(_normalize_upstream_stream_events(upstream))

    assert events == [
        '{"response": "```python", "done": false}\n',
        '{"response": "\\n", "done": false}\n',
        '{"response": "    ", "done": false}\n',
        '{"response": "print(1)", "done": false}\n',
        '{"done": true}\n',
    ]


def test_leading_whitespace_chunks_are_suppressed_until_content_arrives(caplog):
    caplog.set_level("WARNING", logger="ai_gateway")
    upstream = iter([
        '{"response":"   "}',
        '{"response":"\\n"}',
        '{"response":"hello"}',
        '{"response":" "}',
        '{"response":"world"}',
        '{"done":true}',
    ])

    events = list(
        _normalize_upstream_stream_events(
            upstream,
            request_id="stream-leading-blank-1",
        )
    )

    assert events == [
        '{"response": "hello", "done": false}\n',
        '{"response": " ", "done": false}\n',
        '{"response": "world", "done": false}\n',
        '{"done": true}\n',
    ]
    assert "stream_empty_response" not in caplog.text
