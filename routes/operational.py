import time
from typing import Any, Protocol

from fastapi import APIRouter, HTTPException, Request, Response


class OperationalRouterDependencies(Protocol):
    def _request_id(self, request: Request) -> str: ...
    logger: Any
    def _log_request_event(self, phase: str, endpoint: str, request_id: str, **kwargs: Any) -> None: ...
    def health_check(self) -> None: ...
    UpstreamServiceError: type[Exception]
    OUTCOME_FAILURE: str
    OUTCOME_SUCCESS: str
    def _latency_ms(self, start: float) -> int: ...
    def _safe_version_summary(self) -> dict[str, Any]: ...
    def _metrics_snapshot(self) -> dict[str, int]: ...
    preset_service: Any
    DEFAULT_MODEL: str
    OLLAMA_BASE_URL: str | None
    LEGACY_REQUEST_TIMEOUT: float
    OLLAMA_CONNECT_TIMEOUT: float
    OLLAMA_READ_TIMEOUT: float
    OLLAMA_STREAM_READ_TIMEOUT: float
    RETRY_COUNT: int
    SUPPORTED_PROVIDERS: tuple[str, ...]
    DEFAULT_PROVIDER: str
    AgentBrainResponse: Any
    def collect_local_server_status(self) -> dict[str, Any]: ...
    AgentBrainSummary: Any
    def format_agent_brain_summary(self, summary: Any, changes: Any | None = None) -> dict[str, Any]: ...
    def detect_agent_brain_changes(self, previous_snapshot: Any, current_snapshot: Any) -> Any: ...
    def format_agent_brain_changes(self, change_set: Any) -> dict[str, Any]: ...
    def get_previous_agent_brain_snapshot(self) -> Any: ...
    def set_latest_agent_brain_snapshot(self, snapshot: Any) -> None: ...


def create_operational_router(deps: OperationalRouterDependencies) -> APIRouter:
    router = APIRouter()

    @router.get("/health/live")
    def health_live(request: Request, response: Response):
        request_id = deps._request_id(request)
        deps.logger.info(f"liveness_check request_id={request_id}")
        response.headers["X-Request-Id"] = request_id

        return {"status": "ok"}

    @router.get("/health/ready")
    def health_ready(request: Request, response: Response):
        start = time.perf_counter()
        request_id = deps._request_id(request)
        deps._log_request_event("start", "/health/ready", request_id)

        try:
            deps.health_check()
        except deps.UpstreamServiceError as e:
            deps._log_request_event(
                "complete",
                "/health/ready",
                request_id,
                outcome=deps.OUTCOME_FAILURE,
                latency_ms=deps._latency_ms(start),
                error=str(e),
            )
            raise HTTPException(
                status_code=503,
                detail=str(e),
                headers={"X-Request-Id": request_id},
            ) from e

        response.headers["X-Request-Id"] = request_id
        deps._log_request_event(
            "complete",
            "/health/ready",
            request_id,
            outcome=deps.OUTCOME_SUCCESS,
            latency_ms=deps._latency_ms(start),
        )

        return {"status": "ok", "upstream": "ok"}

    @router.get("/health")
    def health(request: Request, response: Response):
        return health_ready(request, response)

    @router.get("/version")
    def version(request: Request, response: Response):
        start = time.perf_counter()
        request_id = deps._request_id(request)

        deps._log_request_event("start", "/version", request_id)

        response.headers["X-Request-Id"] = request_id

        deps._log_request_event(
            "complete",
            "/version",
            request_id,
            outcome=deps.OUTCOME_SUCCESS,
            latency_ms=deps._latency_ms(start),
        )

        return deps._safe_version_summary()

    @router.get("/metrics")
    def metrics():
        return deps._metrics_snapshot()

    @router.get("/presets")
    def presets(request: Request, response: Response):
        start = time.perf_counter()
        request_id = deps._request_id(request)

        deps._log_request_event("start", "/presets", request_id)

        response.headers["X-Request-Id"] = request_id

        deps._log_request_event(
            "complete",
            "/presets",
            request_id,
            outcome=deps.OUTCOME_SUCCESS,
            latency_ms=deps._latency_ms(start),
        )

        return {"presets": deps.preset_service.list_presets()}

    @router.get("/config")
    def config(request: Request, response: Response):
        start = time.perf_counter()
        request_id = deps._request_id(request)

        deps._log_request_event("start", "/config", request_id)

        response.headers["X-Request-Id"] = request_id

        deps._log_request_event(
            "complete",
            "/config",
            request_id,
            outcome=deps.OUTCOME_SUCCESS,
            latency_ms=deps._latency_ms(start),
        )

        return {
            "default_model": deps.DEFAULT_MODEL,
            "ollama_configured": bool(deps.OLLAMA_BASE_URL),
            "request_timeout_s": deps.LEGACY_REQUEST_TIMEOUT,
            "ollama_connect_timeout_s": deps.OLLAMA_CONNECT_TIMEOUT,
            "ollama_read_timeout_s": deps.OLLAMA_READ_TIMEOUT,
            "ollama_stream_read_timeout_s": deps.OLLAMA_STREAM_READ_TIMEOUT,
            "retry_count": deps.RETRY_COUNT,
        }

    @router.get("/providers")
    def providers(request: Request, response: Response):
        start = time.perf_counter()
        request_id = deps._request_id(request)

        deps._log_request_event("start", "/providers", request_id)

        response.headers["X-Request-Id"] = request_id

        deps._log_request_event(
            "complete",
            "/providers",
            request_id,
            outcome=deps.OUTCOME_SUCCESS,
            latency_ms=deps._latency_ms(start),
        )

        return {
            "supported_providers": list(deps.SUPPORTED_PROVIDERS),
            "default_provider": deps.DEFAULT_PROVIDER,
        }

    @router.post("/agent/brain", response_model=deps.AgentBrainResponse)
    def agent_brain(request: Request, response: Response):
        start = time.perf_counter()
        request_id = deps._request_id(request)

        deps._log_request_event("start", "/agent/brain", request_id)

        raw_status = deps.collect_local_server_status()
        summary = deps.AgentBrainSummary(
            gateway=raw_status["gateway"],
            disk_percent=raw_status["disk_percent"],
            memory_percent=raw_status["memory_percent"],
            load_average=raw_status["load_average"],
            uptime_seconds=raw_status["uptime_seconds"],
            service_states=raw_status["service_states"],
            docker_summary=raw_status["docker_summary"],
        )
        previous_snapshot = deps.get_previous_agent_brain_snapshot()
        current_snapshot = summary
        change_set = deps.detect_agent_brain_changes(previous_snapshot, current_snapshot)
        change_presentation = deps.format_agent_brain_changes(change_set)
        deps.set_latest_agent_brain_snapshot(current_snapshot)
        presentation = deps.format_agent_brain_summary(summary, change_presentation)

        response.headers["X-Request-Id"] = request_id
        deps._log_request_event(
            "complete",
            "/agent/brain",
            request_id,
            outcome=deps.OUTCOME_SUCCESS,
            latency_ms=deps._latency_ms(start),
        )

        return deps.AgentBrainResponse(
            overall_status=presentation["overall_status"],
            summary=summary,
            message_lines=presentation["message_lines"],
            has_notable_changes=change_presentation["has_notable_changes"],
            changes=change_presentation["changes"],
        )

    return router
