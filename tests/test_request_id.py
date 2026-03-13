import unittest

from fastapi.testclient import TestClient

import app


class RequestIdTests(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app.app)
        self._orig_generate = app.generate
        self._orig_list_models = app.list_models
        self._orig_health_check = app.health_check

    def tearDown(self):
        app.generate = self._orig_generate
        app.list_models = self._orig_list_models
        app.health_check = self._orig_health_check

    def test_chat_echoes_incoming_request_id(self):
        app.generate = lambda prompt, model: "ok"

        resp = self.client.post(
            "/chat",
            headers={"X-Request-Id": "bot-req-123"},
            json={"prompt": "hello"},
        )

        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.headers.get("X-Request-Id"), "bot-req-123")

    def test_chat_generates_fallback_request_id(self):
        app.generate = lambda prompt, model: "ok"

        resp = self.client.post("/chat", json={"prompt": "hello"})

        self.assertEqual(resp.status_code, 200)
        req_id = resp.headers.get("X-Request-Id")
        self.assertIsNotNone(req_id)
        self.assertEqual(len(req_id), 12)

    def test_health_live_sets_request_id_header(self):
        resp = self.client.get("/health/live", headers={"X-Request-Id": "health-1"})

        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.headers.get("X-Request-Id"), "health-1")


if __name__ == "__main__":
    unittest.main()
