from datetime import datetime, timezone

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from routes.obsidian import create_obsidian_router
from services.obsidian_jobs import ObsidianJobStore

TELEGRAM_TOKEN = "telegram-secret"
WORKER_TOKEN = "worker-secret"


def auth(token):
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def obsidian_client(tmp_path, monkeypatch):
    monkeypatch.setenv("OBSIDIAN_TELEGRAM_INTERNAL_TOKEN", TELEGRAM_TOKEN)
    monkeypatch.setenv("OBSIDIAN_WORKER_TOKEN", WORKER_TOKEN)
    api = FastAPI()
    api.include_router(
        create_obsidian_router(lambda: ObsidianJobStore(str(tmp_path / "jobs.sqlite3")))
    )
    return TestClient(api)


def create_job(client, command="ask", payload=None, telegram_chat_id=None):
    body = {"command": command, "payload": payload or {"question": "hello"}}
    if telegram_chat_id is not None:
        body["telegram_chat_id"] = telegram_chat_id
    response = client.post(
        "/obsidian/jobs",
        headers=auth(TELEGRAM_TOKEN),
        json=body,
    )
    assert response.status_code == 200
    return response.json()["job_id"]


def complete_job(
    client, job_id, status="succeeded", result_text="answer", error_text=None
):
    client.get("/obsidian/jobs/next", headers=auth(WORKER_TOKEN))
    payload = {"status": status}
    if result_text is not None:
        payload["result_text"] = result_text
    if error_text is not None:
        payload["error_text"] = error_text
    response = client.post(
        f"/obsidian/jobs/{job_id}/result",
        headers=auth(WORKER_TOKEN),
        json=payload,
    )
    assert response.status_code == 200
    return response.json()


def test_job_creation(obsidian_client):
    response = obsidian_client.post(
        "/obsidian/jobs",
        headers=auth(TELEGRAM_TOKEN),
        json={
            "command": "ask",
            "payload": {"question": "What changed today?"},
            "telegram_chat_id": 123,
            "telegram_message_id": 456,
            "requested_by": 789,
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["job_id"]
    assert body["status"] == "queued"


def test_invalid_command_rejected(obsidian_client):
    response = obsidian_client.post(
        "/obsidian/jobs",
        headers=auth(TELEGRAM_TOKEN),
        json={"command": "delete_vault", "payload": {}},
    )

    assert response.status_code == 422


def test_capture_command_rejected(obsidian_client):
    response = obsidian_client.post(
        "/obsidian/jobs",
        headers=auth(TELEGRAM_TOKEN),
        json={"command": "capture", "payload": {"text": "legacy note"}},
    )

    assert response.status_code == 422


def test_historical_capture_job_remains_readable(tmp_path, monkeypatch):
    monkeypatch.setenv("OBSIDIAN_TELEGRAM_INTERNAL_TOKEN", TELEGRAM_TOKEN)
    store = ObsidianJobStore(str(tmp_path / "jobs.sqlite3"))
    historical = store.create_job(
        command="capture",
        payload={"text": "legacy note"},
        telegram_chat_id=None,
        telegram_message_id=None,
        requested_by=None,
    )
    store.claim_next_job()
    store.complete_job(
        historical["job_id"],
        status="succeeded",
        result_text="legacy result",
        error_text=None,
    )
    client = TestClient(create_obsidian_router(lambda: store))

    response = client.get(
        f"/obsidian/jobs/{historical['job_id']}", headers=auth(TELEGRAM_TOKEN)
    )

    assert response.status_code == 200
    assert response.json()["command"] == "capture"
    assert response.json()["payload"] == {"text": "legacy note"}
    assert response.json()["status"] == "succeeded"
    assert response.json()["result_text"] == "legacy result"


def test_update_payload_survives_job_lifecycle_and_notification(obsidian_client):
    payload = {"instruction": "Rename the project note and keep its links."}
    create_response = obsidian_client.post(
        "/obsidian/jobs",
        headers=auth(TELEGRAM_TOKEN),
        json={"command": "update", "payload": payload, "telegram_chat_id": 12345},
    )
    assert create_response.status_code == 200
    job_id = create_response.json()["job_id"]

    queued_response = obsidian_client.get(
        f"/obsidian/jobs/{job_id}", headers=auth(TELEGRAM_TOKEN)
    )
    claim_response = obsidian_client.get(
        "/obsidian/jobs/next", headers=auth(WORKER_TOKEN)
    )

    assert queued_response.status_code == 200
    assert queued_response.json()["command"] == "update"
    assert queued_response.json()["payload"] == payload
    assert queued_response.json()["status"] == "queued"
    assert claim_response.status_code == 200
    assert claim_response.json()["job"]["command"] == "update"
    assert claim_response.json()["job"]["payload"] == payload
    assert claim_response.json()["job"]["status"] == "running"

    completion_response = obsidian_client.post(
        f"/obsidian/jobs/{job_id}/result",
        headers=auth(WORKER_TOKEN),
        json={"status": "succeeded", "result_text": "Project note updated."},
    )
    result_response = obsidian_client.get(
        f"/obsidian/jobs/{job_id}/result", headers=auth(TELEGRAM_TOKEN)
    )
    completed_response = obsidian_client.get(
        f"/obsidian/jobs/{job_id}", headers=auth(TELEGRAM_TOKEN)
    )
    notification_response = obsidian_client.get(
        "/obsidian/jobs/notifications/next", headers=auth(TELEGRAM_TOKEN)
    )

    assert completion_response.status_code == 200
    assert completion_response.json()["payload"] == payload
    assert result_response.status_code == 200
    assert result_response.json()["command"] == "update"
    assert result_response.json()["status"] == "succeeded"
    assert result_response.json()["result_text"] == "Project note updated."
    assert completed_response.status_code == 200
    assert completed_response.json()["payload"] == payload
    assert notification_response.status_code == 200
    assert notification_response.json()["job"]["job_id"] == job_id
    assert notification_response.json()["job"]["command"] == "update"
    assert notification_response.json()["job"]["result_text"] == (
        "Project note updated."
    )

    notified_response = obsidian_client.post(
        f"/obsidian/jobs/{job_id}/notified", headers=auth(TELEGRAM_TOKEN)
    )
    final_response = obsidian_client.get(
        f"/obsidian/jobs/{job_id}", headers=auth(TELEGRAM_TOKEN)
    )

    assert notified_response.status_code == 200
    assert notified_response.json()["result_notified_at"] is not None
    assert final_response.status_code == 200
    assert final_response.json()["payload"] == payload
    assert final_response.json()["result_notified_at"] is not None


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"instruction": "Check links and frontmatter without changing any files."},
    ],
    ids=["empty", "instructed"],
)
def test_lint_payload_survives_full_job_lifecycle_unchanged(obsidian_client, payload):
    create_response = obsidian_client.post(
        "/obsidian/jobs",
        headers=auth(TELEGRAM_TOKEN),
        json={"command": "lint", "payload": payload, "telegram_chat_id": 24680},
    )

    assert create_response.status_code == 200
    job_id = create_response.json()["job_id"]

    queued_response = obsidian_client.get(
        f"/obsidian/jobs/{job_id}", headers=auth(TELEGRAM_TOKEN)
    )
    claim_response = obsidian_client.get(
        "/obsidian/jobs/next", headers=auth(WORKER_TOKEN)
    )

    assert queued_response.status_code == 200
    assert queued_response.json()["command"] == "lint"
    assert queued_response.json()["payload"] == payload
    assert queued_response.json()["status"] == "queued"
    assert claim_response.status_code == 200
    assert claim_response.json()["job"]["job_id"] == job_id
    assert claim_response.json()["job"]["command"] == "lint"
    assert claim_response.json()["job"]["payload"] == payload
    assert claim_response.json()["job"]["status"] == "running"

    completion_response = obsidian_client.post(
        f"/obsidian/jobs/{job_id}/result",
        headers=auth(WORKER_TOKEN),
        json={"status": "succeeded", "result_text": "Lint completed."},
    )
    result_response = obsidian_client.get(
        f"/obsidian/jobs/{job_id}/result", headers=auth(TELEGRAM_TOKEN)
    )
    notification_response = obsidian_client.get(
        "/obsidian/jobs/notifications/next", headers=auth(TELEGRAM_TOKEN)
    )

    assert completion_response.status_code == 200
    assert completion_response.json()["payload"] == payload
    assert result_response.status_code == 200
    assert result_response.json()["command"] == "lint"
    assert result_response.json()["status"] == "succeeded"
    assert result_response.json()["result_text"] == "Lint completed."
    assert notification_response.status_code == 200
    assert notification_response.json()["job"]["job_id"] == job_id
    assert notification_response.json()["job"]["command"] == "lint"
    assert notification_response.json()["job"]["result_text"] == "Lint completed."

    notified_response = obsidian_client.post(
        f"/obsidian/jobs/{job_id}/notified", headers=auth(TELEGRAM_TOKEN)
    )
    final_response = obsidian_client.get(
        f"/obsidian/jobs/{job_id}", headers=auth(TELEGRAM_TOKEN)
    )

    assert notified_response.status_code == 200
    assert notified_response.json()["result_notified_at"] is not None
    assert final_response.status_code == 200
    assert final_response.json()["command"] == "lint"
    assert final_response.json()["payload"] == payload
    assert final_response.json()["status"] == "succeeded"
    assert final_response.json()["result_notified_at"] is not None


def test_missing_auth_rejected(obsidian_client):
    response = obsidian_client.post(
        "/obsidian/jobs",
        json={"command": "ask", "payload": {}},
    )

    assert response.status_code == 401


def test_worker_claims_oldest_queued_job(obsidian_client):
    first_job_id = create_job(obsidian_client, payload={"n": 1})
    second_job_id = create_job(obsidian_client, payload={"n": 2})

    response = obsidian_client.get("/obsidian/jobs/next", headers=auth(WORKER_TOKEN))

    assert response.status_code == 200
    claimed = response.json()["job"]
    assert claimed["job_id"] == first_job_id
    assert claimed["job_id"] != second_job_id


def test_claimed_job_becomes_running(obsidian_client):
    job_id = create_job(obsidian_client)

    claim_response = obsidian_client.get(
        "/obsidian/jobs/next", headers=auth(WORKER_TOKEN)
    )
    get_response = obsidian_client.get(
        f"/obsidian/jobs/{job_id}", headers=auth(TELEGRAM_TOKEN)
    )

    assert claim_response.status_code == 200
    assert claim_response.json()["job"]["status"] == "running"
    assert get_response.status_code == 200
    assert get_response.json()["status"] == "running"
    assert get_response.json()["locked_at"] is not None


def test_get_job_works_with_telegram_token(obsidian_client):
    job_id = create_job(obsidian_client, payload={"question": "status?"})

    response = obsidian_client.get(
        f"/obsidian/jobs/{job_id}", headers=auth(TELEGRAM_TOKEN)
    )

    assert response.status_code == 200
    body = response.json()
    assert body["job_id"] == job_id
    assert body["command"] == "ask"
    assert body["payload"] == {"question": "status?"}
    assert body["status"] == "queued"


def test_worker_can_lookup_completed_source_ask_with_original_data(obsidian_client):
    payload = {
        "question": "What did the gateway contract phase decide?",
        "options": {"scope": "unchanged"},
    }
    job_id = create_job(obsidian_client, command="ask", payload=payload)
    completed = complete_job(
        obsidian_client, job_id, result_text="Use explicit worker-side saving."
    )

    response = obsidian_client.get(
        f"/obsidian/worker/jobs/{job_id}", headers=auth(WORKER_TOKEN)
    )

    assert response.status_code == 200
    body = response.json()
    assert body["job_id"] == job_id
    assert body["command"] == "ask"
    assert body["payload"] == payload
    assert body["status"] == "succeeded"
    assert body["result_text"] == "Use explicit worker-side saving."
    assert body["error_text"] is None
    assert body["finished_at"] == completed["finished_at"]


@pytest.mark.parametrize(
    ("command", "expected_status", "result_text", "error_text"),
    [
        ("ask", "queued", None, None),
        ("update", "failed", None, "update failed"),
    ],
)
def test_worker_lookup_represents_data_for_source_validation(
    obsidian_client, command, expected_status, result_text, error_text
):
    job_id = create_job(obsidian_client, command=command, payload={"value": command})
    if expected_status == "failed":
        complete_job(
            obsidian_client,
            job_id,
            status="failed",
            result_text=result_text,
            error_text=error_text,
        )

    response = obsidian_client.get(
        f"/obsidian/worker/jobs/{job_id}", headers=auth(WORKER_TOKEN)
    )

    assert response.status_code == 200
    assert response.json()["command"] == command
    assert response.json()["status"] == expected_status
    assert response.json()["result_text"] == result_text
    assert response.json()["error_text"] == error_text


def test_worker_source_job_lookup_requires_worker_auth(obsidian_client):
    job_id = create_job(obsidian_client)

    missing = obsidian_client.get(f"/obsidian/worker/jobs/{job_id}")
    invalid = obsidian_client.get(
        f"/obsidian/worker/jobs/{job_id}", headers=auth("not-a-worker")
    )
    telegram = obsidian_client.get(
        f"/obsidian/worker/jobs/{job_id}", headers=auth(TELEGRAM_TOKEN)
    )

    assert missing.status_code == 401
    assert invalid.status_code == 401
    assert telegram.status_code == 401


def test_save_payload_survives_job_lifecycle_untouched(obsidian_client):
    source_job_id = create_job(obsidian_client, payload={"question": "Keep this?"})
    save_payload = {"source_job_id": source_job_id}

    job_id = create_job(obsidian_client, command="save", payload=save_payload)
    # The source ask is older, so claim and complete it before claiming the save job.
    source_claim = obsidian_client.get(
        "/obsidian/jobs/next", headers=auth(WORKER_TOKEN)
    )
    assert source_claim.json()["job"]["job_id"] == source_job_id
    complete_response = obsidian_client.post(
        f"/obsidian/jobs/{source_job_id}/result",
        headers=auth(WORKER_TOKEN),
        json={"status": "succeeded", "result_text": "Source answer"},
    )
    assert complete_response.status_code == 200

    claim_response = obsidian_client.get(
        "/obsidian/jobs/next", headers=auth(WORKER_TOKEN)
    )
    assert claim_response.status_code == 200
    assert claim_response.json()["job"]["job_id"] == job_id
    assert claim_response.json()["job"]["command"] == "save"
    assert claim_response.json()["job"]["payload"] == save_payload

    result_response = obsidian_client.post(
        f"/obsidian/jobs/{job_id}/result",
        headers=auth(WORKER_TOKEN),
        json={"status": "succeeded", "result_text": "Saved"},
    )
    lookup_response = obsidian_client.get(
        f"/obsidian/worker/jobs/{job_id}", headers=auth(WORKER_TOKEN)
    )

    assert result_response.status_code == 200
    assert result_response.json()["payload"] == save_payload
    assert lookup_response.status_code == 200
    assert lookup_response.json()["payload"] == save_payload
    assert lookup_response.json()["status"] == "succeeded"


def test_save_payload_shape_remains_worker_owned(obsidian_client):
    for payload in ({}, {"source_job_id": 123}, {"source_job_id": "ask-id", "x": 1}):
        response = obsidian_client.post(
            "/obsidian/jobs",
            headers=auth(TELEGRAM_TOKEN),
            json={"command": "save", "payload": payload},
        )

        assert response.status_code == 200


def test_result_update_stores_succeeded_result(obsidian_client):
    job_id = create_job(obsidian_client)
    obsidian_client.get("/obsidian/jobs/next", headers=auth(WORKER_TOKEN))

    response = obsidian_client.post(
        f"/obsidian/jobs/{job_id}/result",
        headers=auth(WORKER_TOKEN),
        json={"status": "succeeded", "result_text": "answer"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "succeeded"
    assert body["result_text"] == "answer"
    assert body["finished_at"] is not None


def test_get_result_alias_returns_succeeded_result_text(obsidian_client):
    job_id = create_job(obsidian_client)
    obsidian_client.get("/obsidian/jobs/next", headers=auth(WORKER_TOKEN))
    update_response = obsidian_client.post(
        f"/obsidian/jobs/{job_id}/result",
        headers=auth(WORKER_TOKEN),
        json={"status": "succeeded", "result_text": "answer"},
    )

    response = obsidian_client.get(
        f"/obsidian/jobs/{job_id}/result",
        headers=auth(TELEGRAM_TOKEN),
    )

    assert update_response.status_code == 200
    assert response.status_code == 200
    assert response.json() == {
        "job_id": job_id,
        "command": "ask",
        "status": "succeeded",
        "result_text": "answer",
        "error_text": None,
        "finished_at": update_response.json()["finished_at"],
    }


def test_get_result_alias_rejects_missing_auth(obsidian_client):
    job_id = create_job(obsidian_client)

    response = obsidian_client.get(f"/obsidian/jobs/{job_id}/result")

    assert response.status_code == 401


def test_get_result_alias_rejects_worker_token(obsidian_client):
    job_id = create_job(obsidian_client)

    response = obsidian_client.get(
        f"/obsidian/jobs/{job_id}/result", headers=auth(WORKER_TOKEN)
    )

    assert response.status_code == 401


def test_get_result_alias_returns_404_for_unknown_job(obsidian_client):
    response = obsidian_client.get(
        "/obsidian/jobs/unknown/result",
        headers=auth(TELEGRAM_TOKEN),
    )

    assert response.status_code == 404


def test_result_update_stores_failed_error(obsidian_client):
    job_id = create_job(obsidian_client)
    obsidian_client.get("/obsidian/jobs/next", headers=auth(WORKER_TOKEN))

    response = obsidian_client.post(
        f"/obsidian/jobs/{job_id}/result",
        headers=auth(WORKER_TOKEN),
        json={"status": "failed", "error_text": "vault unavailable"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "failed"
    assert body["error_text"] == "vault unavailable"
    assert body["finished_at"] is not None


def test_empty_queue_returns_clear_empty_response(obsidian_client):
    response = obsidian_client.get("/obsidian/jobs/next", headers=auth(WORKER_TOKEN))

    assert response.status_code == 200
    assert response.json() == {"job": None, "status": "empty"}


def test_second_result_call_does_not_overwrite_final_job(obsidian_client):
    job_id = create_job(obsidian_client)
    obsidian_client.get("/obsidian/jobs/next", headers=auth(WORKER_TOKEN))

    first_response = obsidian_client.post(
        f"/obsidian/jobs/{job_id}/result",
        headers=auth(WORKER_TOKEN),
        json={"status": "succeeded", "result_text": "original answer"},
    )
    second_response = obsidian_client.post(
        f"/obsidian/jobs/{job_id}/result",
        headers=auth(WORKER_TOKEN),
        json={"status": "failed", "error_text": "stale failure"},
    )
    get_response = obsidian_client.get(
        f"/obsidian/jobs/{job_id}", headers=auth(TELEGRAM_TOKEN)
    )

    assert first_response.status_code == 200
    assert second_response.status_code == 409
    assert get_response.status_code == 200
    body = get_response.json()
    assert body["status"] == "succeeded"
    assert body["result_text"] == "original answer"
    assert body["error_text"] is None


def test_oversized_result_text_is_truncated(tmp_path, monkeypatch):
    monkeypatch.setenv("OBSIDIAN_TELEGRAM_INTERNAL_TOKEN", TELEGRAM_TOKEN)
    monkeypatch.setenv("OBSIDIAN_WORKER_TOKEN", WORKER_TOKEN)
    monkeypatch.setenv("OBSIDIAN_JOB_MAX_RESULT_CHARS", "32")
    store = ObsidianJobStore(str(tmp_path / "jobs.sqlite3"))
    api = FastAPI()
    api.include_router(create_obsidian_router(lambda: store))
    client = TestClient(api)
    job_id = create_job(client)
    client.get("/obsidian/jobs/next", headers=auth(WORKER_TOKEN))

    response = client.post(
        f"/obsidian/jobs/{job_id}/result",
        headers=auth(WORKER_TOKEN),
        json={"status": "succeeded", "result_text": "x" * 100},
    )

    assert response.status_code == 200
    result_text = response.json()["result_text"]
    assert len(result_text) == 32
    assert result_text.endswith("...[truncated by ai-gateway]")


def test_oversized_error_text_is_truncated(tmp_path, monkeypatch):
    monkeypatch.setenv("OBSIDIAN_TELEGRAM_INTERNAL_TOKEN", TELEGRAM_TOKEN)
    monkeypatch.setenv("OBSIDIAN_WORKER_TOKEN", WORKER_TOKEN)
    monkeypatch.setenv("OBSIDIAN_JOB_MAX_ERROR_CHARS", "32")
    store = ObsidianJobStore(str(tmp_path / "jobs.sqlite3"))
    api = FastAPI()
    api.include_router(create_obsidian_router(lambda: store))
    client = TestClient(api)
    job_id = create_job(client)
    client.get("/obsidian/jobs/next", headers=auth(WORKER_TOKEN))

    response = client.post(
        f"/obsidian/jobs/{job_id}/result",
        headers=auth(WORKER_TOKEN),
        json={"status": "failed", "error_text": "x" * 100},
    )

    assert response.status_code == 200
    error_text = response.json()["error_text"]
    assert len(error_text) == 32
    assert error_text.endswith("...[truncated by ai-gateway]")


def test_cleanup_clears_old_succeeded_result_text(tmp_path, monkeypatch):
    monkeypatch.setenv("OBSIDIAN_JOB_RESULT_RETENTION_HOURS", "24")
    store = ObsidianJobStore(str(tmp_path / "jobs.sqlite3"))
    job = store.create_job(
        command="ask",
        payload={},
        telegram_chat_id=None,
        telegram_message_id=None,
        requested_by=None,
    )
    store.claim_next_job()
    store.complete_job(
        job["job_id"], status="succeeded", result_text="old answer", error_text=None
    )
    old_finished_at = "2026-06-14T00:00:00+00:00"
    with store._connect() as conn:
        conn.execute(
            "UPDATE obsidian_jobs SET finished_at = ? WHERE id = ?",
            (old_finished_at, job["job_id"]),
        )

    counts = store.cleanup_obsidian_job_payloads(
        now=datetime(2026, 6, 16, tzinfo=timezone.utc)
    )

    assert counts == {"result_text_cleared": 1, "error_text_cleared": 0}
    cleaned = store.get_job(job["job_id"])
    assert cleaned["status"] == "succeeded"
    assert cleaned["result_text"] is None


def test_cleanup_clears_old_failed_error_text(tmp_path, monkeypatch):
    monkeypatch.setenv("OBSIDIAN_JOB_ERROR_RETENTION_HOURS", "72")
    store = ObsidianJobStore(str(tmp_path / "jobs.sqlite3"))
    job = store.create_job(
        command="ask",
        payload={},
        telegram_chat_id=None,
        telegram_message_id=None,
        requested_by=None,
    )
    store.claim_next_job()
    store.complete_job(
        job["job_id"], status="failed", result_text=None, error_text="old error"
    )
    old_finished_at = "2026-06-12T00:00:00+00:00"
    with store._connect() as conn:
        conn.execute(
            "UPDATE obsidian_jobs SET finished_at = ? WHERE id = ?",
            (old_finished_at, job["job_id"]),
        )

    counts = store.cleanup_obsidian_job_payloads(
        now=datetime(2026, 6, 16, tzinfo=timezone.utc)
    )

    assert counts == {"result_text_cleared": 0, "error_text_cleared": 1}
    cleaned = store.get_job(job["job_id"])
    assert cleaned["status"] == "failed"
    assert cleaned["error_text"] is None


def test_cleanup_does_not_clear_recent_results(tmp_path, monkeypatch):
    monkeypatch.setenv("OBSIDIAN_JOB_RESULT_RETENTION_HOURS", "24")
    monkeypatch.setenv("OBSIDIAN_JOB_ERROR_RETENTION_HOURS", "72")
    store = ObsidianJobStore(str(tmp_path / "jobs.sqlite3"))
    job = store.create_job(
        command="ask",
        payload={},
        telegram_chat_id=None,
        telegram_message_id=None,
        requested_by=None,
    )
    store.claim_next_job()
    store.complete_job(
        job["job_id"], status="succeeded", result_text="recent answer", error_text=None
    )
    recent_finished_at = "2026-06-15T23:00:00+00:00"
    with store._connect() as conn:
        conn.execute(
            "UPDATE obsidian_jobs SET finished_at = ? WHERE id = ?",
            (recent_finished_at, job["job_id"]),
        )

    counts = store.cleanup_obsidian_job_payloads(
        now=datetime(2026, 6, 16, tzinfo=timezone.utc)
    )

    assert counts == {"result_text_cleared": 0, "error_text_cleared": 0}
    assert store.get_job(job["job_id"])["result_text"] == "recent answer"


def test_succeeded_job_with_chat_id_appears_in_notifications_next(obsidian_client):
    job_id = create_job(obsidian_client, telegram_chat_id=12345)
    finished = complete_job(obsidian_client, job_id, result_text="answer")

    response = obsidian_client.get(
        "/obsidian/jobs/notifications/next", headers=auth(TELEGRAM_TOKEN)
    )

    assert response.status_code == 200
    assert response.json() == {
        "job": {
            "job_id": job_id,
            "command": "ask",
            "status": "succeeded",
            "telegram_chat_id": 12345,
            "result_text": "answer",
            "error_text": None,
            "created_at": finished["created_at"],
            "finished_at": finished["finished_at"],
        }
    }


def test_failed_job_with_chat_id_appears_in_notifications_next(obsidian_client):
    job_id = create_job(obsidian_client, telegram_chat_id=12345)
    complete_job(
        obsidian_client,
        job_id,
        status="failed",
        result_text=None,
        error_text="vault unavailable",
    )

    response = obsidian_client.get(
        "/obsidian/jobs/notifications/next", headers=auth(TELEGRAM_TOKEN)
    )

    assert response.status_code == 200
    job = response.json()["job"]
    assert job["job_id"] == job_id
    assert job["status"] == "failed"
    assert job["telegram_chat_id"] == 12345
    assert job["error_text"] == "vault unavailable"


def test_queued_and_running_jobs_do_not_appear_in_notifications_next(obsidian_client):
    create_job(obsidian_client, telegram_chat_id=12345)
    running_job_id = create_job(obsidian_client, telegram_chat_id=12345)
    claimed = obsidian_client.get("/obsidian/jobs/next", headers=auth(WORKER_TOKEN))

    response = obsidian_client.get(
        "/obsidian/jobs/notifications/next", headers=auth(TELEGRAM_TOKEN)
    )

    assert claimed.status_code == 200
    assert claimed.json()["job"]["status"] == "running"
    assert claimed.json()["job"]["job_id"] != running_job_id
    assert response.status_code == 200
    assert response.json() == {"job": None, "status": "empty"}


def test_completed_job_without_chat_id_does_not_appear_in_notifications_next(
    obsidian_client,
):
    job_id = create_job(obsidian_client)
    complete_job(obsidian_client, job_id, result_text="answer")

    response = obsidian_client.get(
        "/obsidian/jobs/notifications/next", headers=auth(TELEGRAM_TOKEN)
    )

    assert response.status_code == 200
    assert response.json() == {"job": None, "status": "empty"}


def test_notification_next_leases_job_until_notified_or_expired(obsidian_client):
    job_id = create_job(obsidian_client, telegram_chat_id=12345)
    complete_job(obsidian_client, job_id, result_text="answer")

    first_response = obsidian_client.get(
        "/obsidian/jobs/notifications/next", headers=auth(TELEGRAM_TOKEN)
    )
    second_response = obsidian_client.get(
        "/obsidian/jobs/notifications/next", headers=auth(TELEGRAM_TOKEN)
    )

    assert first_response.status_code == 200
    assert first_response.json()["job"]["job_id"] == job_id
    assert second_response.status_code == 200
    assert second_response.json() == {"job": None, "status": "empty"}


def test_notification_next_returns_job_again_after_lease_expires(tmp_path, monkeypatch):
    monkeypatch.setenv("OBSIDIAN_TELEGRAM_INTERNAL_TOKEN", TELEGRAM_TOKEN)
    monkeypatch.setenv("OBSIDIAN_WORKER_TOKEN", WORKER_TOKEN)
    monkeypatch.setenv("OBSIDIAN_JOB_NOTIFICATION_LEASE_SECONDS", "300")
    store = ObsidianJobStore(str(tmp_path / "jobs.sqlite3"))
    api = FastAPI()
    api.include_router(create_obsidian_router(lambda: store))
    client = TestClient(api)
    job_id = create_job(client, telegram_chat_id=12345)
    complete_job(client, job_id, result_text="answer")
    first_response = client.get(
        "/obsidian/jobs/notifications/next", headers=auth(TELEGRAM_TOKEN)
    )
    with store._connect() as conn:
        conn.execute(
            """
            UPDATE obsidian_jobs
            SET result_notification_claimed_until = ?
            WHERE id = ?
            """,
            ("2026-06-15T00:00:00+00:00", job_id),
        )

    second_response = client.get(
        "/obsidian/jobs/notifications/next", headers=auth(TELEGRAM_TOKEN)
    )

    assert first_response.status_code == 200
    assert first_response.json()["job"]["job_id"] == job_id
    assert second_response.status_code == 200
    assert second_response.json()["job"]["job_id"] == job_id


def test_notified_job_does_not_appear_in_notifications_next(obsidian_client):
    job_id = create_job(obsidian_client, telegram_chat_id=12345)
    complete_job(obsidian_client, job_id, result_text="answer")
    mark_response = obsidian_client.post(
        f"/obsidian/jobs/{job_id}/notified", headers=auth(TELEGRAM_TOKEN)
    )

    response = obsidian_client.get(
        "/obsidian/jobs/notifications/next", headers=auth(TELEGRAM_TOKEN)
    )

    assert mark_response.status_code == 200
    assert response.status_code == 200
    assert response.json() == {"job": None, "status": "empty"}


def test_mark_notified_sets_result_notified_at_and_is_idempotent(obsidian_client):
    job_id = create_job(obsidian_client, telegram_chat_id=12345)
    complete_job(obsidian_client, job_id, result_text="answer")

    first_response = obsidian_client.post(
        f"/obsidian/jobs/{job_id}/notified", headers=auth(TELEGRAM_TOKEN)
    )
    second_response = obsidian_client.post(
        f"/obsidian/jobs/{job_id}/notified", headers=auth(TELEGRAM_TOKEN)
    )

    assert first_response.status_code == 200
    assert second_response.status_code == 200
    assert first_response.json()["result_notified_at"] is not None
    assert (
        second_response.json()["result_notified_at"]
        == first_response.json()["result_notified_at"]
    )


def test_mark_notified_rejects_queued_job_without_setting_timestamp(obsidian_client):
    job_id = create_job(obsidian_client, telegram_chat_id=12345)

    response = obsidian_client.post(
        f"/obsidian/jobs/{job_id}/notified", headers=auth(TELEGRAM_TOKEN)
    )
    get_response = obsidian_client.get(
        f"/obsidian/jobs/{job_id}", headers=auth(TELEGRAM_TOKEN)
    )

    assert response.status_code == 409
    assert get_response.status_code == 200
    assert get_response.json()["status"] == "queued"
    assert get_response.json()["result_notified_at"] is None


def test_mark_notified_rejects_running_job_without_setting_timestamp(obsidian_client):
    job_id = create_job(obsidian_client, telegram_chat_id=12345)
    claim_response = obsidian_client.get(
        "/obsidian/jobs/next", headers=auth(WORKER_TOKEN)
    )

    response = obsidian_client.post(
        f"/obsidian/jobs/{job_id}/notified", headers=auth(TELEGRAM_TOKEN)
    )
    get_response = obsidian_client.get(
        f"/obsidian/jobs/{job_id}", headers=auth(TELEGRAM_TOKEN)
    )

    assert claim_response.status_code == 200
    assert response.status_code == 409
    assert get_response.status_code == 200
    assert get_response.json()["status"] == "running"
    assert get_response.json()["result_notified_at"] is None


def test_mark_notified_rejects_completed_job_without_chat_id(obsidian_client):
    job_id = create_job(obsidian_client)
    complete_job(obsidian_client, job_id, result_text="answer")

    response = obsidian_client.post(
        f"/obsidian/jobs/{job_id}/notified", headers=auth(TELEGRAM_TOKEN)
    )
    get_response = obsidian_client.get(
        f"/obsidian/jobs/{job_id}", headers=auth(TELEGRAM_TOKEN)
    )

    assert response.status_code == 409
    assert get_response.status_code == 200
    assert get_response.json()["status"] == "succeeded"
    assert get_response.json()["result_notified_at"] is None


def test_notification_endpoints_reject_missing_wrong_and_worker_tokens(obsidian_client):
    job_id = create_job(obsidian_client, telegram_chat_id=12345)

    responses = [
        obsidian_client.get("/obsidian/jobs/notifications/next"),
        obsidian_client.get(
            "/obsidian/jobs/notifications/next", headers=auth("wrong-token")
        ),
        obsidian_client.get(
            "/obsidian/jobs/notifications/next", headers=auth(WORKER_TOKEN)
        ),
        obsidian_client.post(f"/obsidian/jobs/{job_id}/notified"),
        obsidian_client.post(
            f"/obsidian/jobs/{job_id}/notified", headers=auth("wrong-token")
        ),
        obsidian_client.post(
            f"/obsidian/jobs/{job_id}/notified", headers=auth(WORKER_TOKEN)
        ),
    ]

    assert [response.status_code for response in responses] == [
        401,
        401,
        401,
        401,
        401,
        401,
    ]


def test_get_job_rejects_worker_missing_and_invalid_tokens(obsidian_client):
    job_id = create_job(obsidian_client)

    responses = [
        obsidian_client.get(
            f"/obsidian/jobs/{job_id}", headers=auth(WORKER_TOKEN)
        ),
        obsidian_client.get(f"/obsidian/jobs/{job_id}"),
        obsidian_client.get(
            f"/obsidian/jobs/{job_id}", headers=auth("wrong-token")
        ),
    ]

    assert [response.status_code for response in responses] == [401, 401, 401]


def test_worker_endpoints_reject_telegram_token(obsidian_client):
    job_id = create_job(obsidian_client)

    next_response = obsidian_client.get(
        "/obsidian/jobs/next", headers=auth(TELEGRAM_TOKEN)
    )
    result_response = obsidian_client.post(
        f"/obsidian/jobs/{job_id}/result",
        headers=auth(TELEGRAM_TOKEN),
        json={"status": "succeeded", "result_text": "answer"},
    )

    assert next_response.status_code == 401
    assert result_response.status_code == 401
