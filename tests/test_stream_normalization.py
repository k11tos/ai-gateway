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
