import os
from functools import lru_cache
from typing import Any, Callable, Literal

from fastapi import APIRouter, Header, HTTPException, Request, Response
from pydantic import BaseModel, Field, field_validator

from logger import logger
from services.obsidian_jobs import (
    ALLOWED_COMMANDS,
    FINAL_STATUSES,
    JobTransitionConflict,
    ObsidianJobStore,
)


class ObsidianJobCreateRequest(BaseModel):
    command: str
    payload: dict[str, Any] = Field(default_factory=dict)
    telegram_chat_id: int | None = None
    telegram_message_id: int | None = None
    requested_by: int | None = None

    @field_validator("command")
    @classmethod
    def command_must_be_allowed(cls, value: str) -> str:
        if value not in ALLOWED_COMMANDS:
            allowed = ", ".join(sorted(ALLOWED_COMMANDS))
            raise ValueError(f"command must be one of: {allowed}")
        return value


class ObsidianJobResultRequest(BaseModel):
    status: Literal["succeeded", "failed"]
    result_text: str | None = None
    error_text: str | None = None


def _bearer_token(authorization: str | None) -> str | None:
    if not authorization:
        return None
    scheme, separator, token = authorization.partition(" ")
    if not separator or scheme.lower() != "bearer" or not token.strip():
        return None
    return token.strip()


def _require_token(authorization: str | None, expected: str | None) -> None:
    if not expected:
        raise HTTPException(status_code=503, detail="Obsidian queue auth is not configured")
    if _bearer_token(authorization) != expected:
        raise HTTPException(status_code=401, detail="Unauthorized")


def _configured_db_path() -> str:
    db_path = os.environ.get("OBSIDIAN_JOBS_DB_PATH")
    if not db_path:
        raise HTTPException(status_code=503, detail="Obsidian queue database is not configured")
    return db_path


@lru_cache(maxsize=8)
def _cached_store(db_path: str) -> ObsidianJobStore:
    return ObsidianJobStore(db_path)


def default_obsidian_job_store_provider() -> ObsidianJobStore:
    return _cached_store(_configured_db_path())


def _request_id(request: Request) -> str | None:
    return request.headers.get("X-Request-Id")


def _log_job_event(event: str, *, request_id: str | None, job: dict[str, Any]) -> None:
    logger.info(
        f"obsidian_job_{event} request_id={request_id} "
        f"job_id={job.get('job_id')} command={job.get('command')} status={job.get('status')}"
    )


def _get_job_or_404(store: ObsidianJobStore, job_id: str) -> dict[str, Any]:
    job = store.get_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")
    return job


def _job_result_response(job: dict[str, Any]) -> dict[str, Any]:
    return {
        "job_id": job["job_id"],
        "command": job["command"],
        "status": job["status"],
        "result_text": job["result_text"],
        "error_text": job["error_text"],
        "finished_at": job["finished_at"],
    }


def create_obsidian_router(
    store_provider: Callable[[], ObsidianJobStore] = default_obsidian_job_store_provider,
) -> APIRouter:
    router = APIRouter(prefix="/obsidian", tags=["obsidian"])

    @router.post("/jobs")
    def create_job(
        req: ObsidianJobCreateRequest,
        request: Request,
        response: Response,
        authorization: str | None = Header(default=None),
    ):
        _require_token(authorization, os.environ.get("OBSIDIAN_TELEGRAM_INTERNAL_TOKEN"))
        store = store_provider()
        job = store.create_job(
            command=req.command,
            payload=req.payload,
            telegram_chat_id=req.telegram_chat_id,
            telegram_message_id=req.telegram_message_id,
            requested_by=req.requested_by,
        )
        request_id = _request_id(request)
        if request_id:
            response.headers["X-Request-Id"] = request_id
        _log_job_event("created", request_id=request_id, job={**job, "command": req.command})
        return job

    @router.get("/jobs/next")
    def claim_next_job(
        request: Request,
        authorization: str | None = Header(default=None),
    ):
        _require_token(authorization, os.environ.get("OBSIDIAN_WORKER_TOKEN"))
        job = store_provider().claim_next_job()
        if job is None:
            return {"job": None, "status": "empty"}
        _log_job_event("claimed", request_id=_request_id(request), job=job)
        return {"job": job}

    @router.post("/jobs/{job_id}/result")
    def store_result(
        job_id: str,
        req: ObsidianJobResultRequest,
        request: Request,
        authorization: str | None = Header(default=None),
    ):
        _require_token(authorization, os.environ.get("OBSIDIAN_WORKER_TOKEN"))
        if req.status not in FINAL_STATUSES:
            raise HTTPException(status_code=400, detail="Invalid final status")
        try:
            job = store_provider().complete_job(
                job_id,
                status=req.status,
                result_text=req.result_text,
                error_text=req.error_text,
            )
        except JobTransitionConflict as e:
            raise HTTPException(status_code=409, detail="Job is not running") from e
        if job is None:
            raise HTTPException(status_code=404, detail="Job not found")
        _log_job_event("finished", request_id=_request_id(request), job=job)
        return job

    @router.get("/jobs/{job_id}")
    def get_job(job_id: str, authorization: str | None = Header(default=None)):
        _require_token(authorization, os.environ.get("OBSIDIAN_TELEGRAM_INTERNAL_TOKEN"))
        return _get_job_or_404(store_provider(), job_id)

    @router.get("/jobs/{job_id}/result")
    def get_job_result(job_id: str, authorization: str | None = Header(default=None)):
        _require_token(authorization, os.environ.get("OBSIDIAN_TELEGRAM_INTERNAL_TOKEN"))
        return _job_result_response(_get_job_or_404(store_provider(), job_id))

    @router.get("/status")
    def status(authorization: str | None = Header(default=None)):
        _require_token(authorization, os.environ.get("OBSIDIAN_TELEGRAM_INTERNAL_TOKEN"))
        return store_provider().status_summary()

    return router
