from fastapi.testclient import TestClient


def test_app_import_startup_succeeds_with_obsidian_env_unset(monkeypatch):
    monkeypatch.delenv("OBSIDIAN_JOBS_DB_PATH", raising=False)
    monkeypatch.delenv("OBSIDIAN_TELEGRAM_INTERNAL_TOKEN", raising=False)
    monkeypatch.delenv("OBSIDIAN_WORKER_TOKEN", raising=False)

    import app

    assert hasattr(app, "app")


def test_health_live_returns_200_with_obsidian_env_unset(monkeypatch):
    monkeypatch.delenv("OBSIDIAN_JOBS_DB_PATH", raising=False)
    monkeypatch.delenv("OBSIDIAN_TELEGRAM_INTERNAL_TOKEN", raising=False)
    monkeypatch.delenv("OBSIDIAN_WORKER_TOKEN", raising=False)

    from app import app

    response = TestClient(app).get("/health/live")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_obsidian_endpoint_returns_503_when_config_missing(monkeypatch):
    monkeypatch.delenv("OBSIDIAN_JOBS_DB_PATH", raising=False)
    monkeypatch.delenv("OBSIDIAN_TELEGRAM_INTERNAL_TOKEN", raising=False)
    monkeypatch.delenv("OBSIDIAN_WORKER_TOKEN", raising=False)

    from app import app

    response = TestClient(app).post(
        "/obsidian/jobs",
        json={"command": "ask", "payload": {}},
    )

    assert response.status_code == 503
    assert response.json() == {"detail": "Obsidian queue auth is not configured"}


def test_obsidian_endpoint_returns_503_when_database_config_missing(monkeypatch):
    monkeypatch.delenv("OBSIDIAN_JOBS_DB_PATH", raising=False)
    monkeypatch.setenv("OBSIDIAN_TELEGRAM_INTERNAL_TOKEN", "telegram-secret")

    from app import app

    response = TestClient(app).post(
        "/obsidian/jobs",
        headers={"Authorization": "Bearer telegram-secret"},
        json={"command": "ask", "payload": {}},
    )

    assert response.status_code == 503
    assert response.json() == {"detail": "Obsidian queue database is not configured"}
