import os
import time
import uuid

from fastapi import Request

from logger import logger
from services.metrics_store import increment_metric, metrics_snapshot, reset_metrics

OUTCOME_SUCCESS = "success"
OUTCOME_FAILURE = "failure"
OUTCOME_INCOMPLETE = "incomplete"
APP_VERSION_ENV_KEYS = ("APP_VERSION", "VERSION")
COMMIT_SHA_ENV_KEYS = ("COMMIT_SHA", "GIT_SHA", "GITHUB_SHA")


def request_id(request: Request) -> str:
    return request.headers.get("X-Request-Id") or uuid.uuid4().hex[:12]


def latency_ms(start: float) -> int:
    return int((time.perf_counter() - start) * 1000)


def first_non_empty_env(*keys: str) -> str | None:
    for key in keys:
        value = os.environ.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()

    return None


def safe_version_summary() -> dict[str, str]:
    app_version = first_non_empty_env(*APP_VERSION_ENV_KEYS)
    commit_sha = first_non_empty_env(*COMMIT_SHA_ENV_KEYS)

    summary = {
        "app_version": app_version or "unavailable",
        "commit_sha": (commit_sha[:7] if commit_sha else "unavailable"),
    }
    if app_version or commit_sha:
        summary["status"] = "ok"
    else:
        summary["status"] = "unavailable"

    return summary


def increment_request_metric(metric_key: str) -> None:
    increment_metric(metric_key)


def request_metrics_snapshot() -> dict[str, int]:
    return metrics_snapshot()


def reset_request_metrics() -> None:
    reset_metrics()


def log_request_event(
    phase: str,
    endpoint: str,
    request_id: str,
    model: str | None = None,
    preset: str | None = None,
    provider: str | None = None,
    outcome: str | None = None,
    latency_ms: int | None = None,
    error: str | None = None,
):
    fields = [f"phase={phase}", f"endpoint={endpoint}", f"request_id={request_id}"]

    if model:
        fields.append(f"model={model}")
    if preset:
        fields.append(f"preset={preset}")
    if provider:
        fields.append(f"provider={provider}")
    if outcome:
        fields.append(f"outcome={outcome}")
    if latency_ms is not None:
        fields.append(f"latency_ms={latency_ms}")
    if error:
        fields.append(f"error={error}")

    message = " ".join(fields)

    if outcome == OUTCOME_FAILURE:
        logger.error(message)
    else:
        logger.info(message)
