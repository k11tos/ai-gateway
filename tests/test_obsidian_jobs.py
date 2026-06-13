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
    api.include_router(create_obsidian_router(ObsidianJobStore(str(tmp_path / "jobs.sqlite3"))))
    return TestClient(api)


def create_job(client, command="ask", payload=None):
    response = client.post(
        "/obsidian/jobs",
        headers=auth(TELEGRAM_TOKEN),
        json={"command": command, "payload": payload or {"question": "hello"}},
    )
    assert response.status_code == 200
    return response.json()["job_id"]


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

    claim_response = obsidian_client.get("/obsidian/jobs/next", headers=auth(WORKER_TOKEN))
    get_response = obsidian_client.get(f"/obsidian/jobs/{job_id}", headers=auth(TELEGRAM_TOKEN))

    assert claim_response.status_code == 200
    assert claim_response.json()["job"]["status"] == "running"
    assert get_response.status_code == 200
    assert get_response.json()["status"] == "running"
    assert get_response.json()["locked_at"] is not None


def test_result_update_stores_succeeded_result(obsidian_client):
    job_id = create_job(obsidian_client)

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


def test_result_update_stores_failed_error(obsidian_client):
    job_id = create_job(obsidian_client)

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
