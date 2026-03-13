import unittest

from app import _normalize_upstream_stream_events


class NormalizeUpstreamStreamEventsTests(unittest.TestCase):
    def test_chunk_and_explicit_done(self):
        upstream = iter([
            '{"response":"hello"}',
            '{"done":true}',
        ])

        events = list(_normalize_upstream_stream_events(upstream))

        self.assertEqual(
            events,
            [
                '{"response": "hello", "done": false}\n',
                '{"done": true}\n',
            ],
        )

    def test_invalid_line_is_skipped(self):
        upstream = iter([
            'not-json',
            '{"response":"ok"}',
            '{"done":true}',
        ])

        events = list(_normalize_upstream_stream_events(upstream))

        self.assertEqual(
            events,
            [
                '{"response": "ok", "done": false}\n',
                '{"done": true}\n',
            ],
        )

    def test_premature_eof_without_done(self):
        upstream = iter([
            '{"response":"partial"}',
        ])

        events = list(_normalize_upstream_stream_events(upstream))

        self.assertEqual(events, ['{"response": "partial", "done": false}\n'])


if __name__ == "__main__":
    unittest.main()
