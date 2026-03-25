import json
import os
import time
import uuid
from typing import Literal
from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi import HTTPException
from fastapi import Request
from fastapi import Response
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from services.agent_brain_formatter import format_agent_brain_summary
from services.agent_brain_status_service import collect_local_server_status
from services.metrics_store import increment_metric, metrics_snapshot, reset_metrics
from services.non_stream_request_flow import (
    prepare_non_stream_request_metadata,
    run_non_stream_generation,
)
from services import presets as preset_service

from logger import logger
from routes.operational import (
    OperationalRouterDependencies,
    create_operational_router,
)
from ollama_client import (
    OLLAMA_BASE_URL,
    LEGACY_REQUEST_TIMEOUT,
    OLLAMA_CONNECT_TIMEOUT,
    OLLAMA_READ_TIMEOUT,
    OLLAMA_STREAM_READ_TIMEOUT,
    RETRY_COUNT,
    UpstreamServiceError,
    embedding,
    generate,
    generate_stream,
    health_check,
    list_models,
)

load_dotenv()

DEFAULT_MODEL = os.environ.get("DEFAULT_MODEL", "deepseek-r1:8b")
DEFAULT_PROVIDER = "ollama"
SUPPORTED_PROVIDERS = (DEFAULT_PROVIDER,)

OUTCOME_SUCCESS = "success"
OUTCOME_FAILURE = "failure"
OUTCOME_INCOMPLETE = "incomplete"
APP_VERSION_ENV_KEYS = ("APP_VERSION", "VERSION")
COMMIT_SHA_ENV_KEYS = ("COMMIT_SHA", "GIT_SHA", "GITHUB_SHA")
def _load_model_aliases() -> dict[str, str]:
    aliases = {
        "fast": os.environ.get("MODEL_ALIAS_FAST"),
        "smart": os.environ.get("MODEL_ALIAS_SMART"),
        "coding": os.environ.get("MODEL_ALIAS_CODING"),
    }
    configured_aliases = os.environ.get("MODEL_ALIASES")

    if configured_aliases:
        for raw_pair in configured_aliases.split(","):
            pair = raw_pair.strip()
            if not pair:
                continue

            alias, separator, model = pair.partition("=")
            if not separator:
                logger.warning(f"model_alias_config_invalid pair={pair}")
                continue

            normalized_alias = alias.strip()
            resolved_model = model.strip()

            if not normalized_alias:
                logger.warning(f"model_alias_config_invalid_empty_alias pair={pair}")
                continue
            if not resolved_model:
                logger.warning(f"model_alias_config_invalid_empty_model pair={pair}")
                continue

            aliases[normalized_alias] = resolved_model

    return {
        alias: model
        for alias, model in aliases.items()
        if isinstance(model, str) and model.strip()
    }


MODEL_ALIASES = _load_model_aliases()

app = FastAPI(title="AI Gateway")


class ChatRequest(BaseModel):
    prompt: str
    model: str | None = None
    preset: str | None = None
    provider: str | None = None


class AgentBrainSummary(BaseModel):
    gateway: str
    disk_percent: float | None = None
    memory_percent: float | None = None
    load_average: list[float] | None = None


class AgentBrainResponse(BaseModel):
    status: Literal["ok"] = "ok"
    overall_status: Literal["ok", "partial", "warning"]
    summary: AgentBrainSummary
    message_lines: list[str]


def _resolve_model_for_request(
    model: str | None,
    *,
    endpoint: str,
    request_id: str,
) -> tuple[str, str]:
    requested_model = model or DEFAULT_MODEL
    resolved_model = MODEL_ALIASES.get(requested_model, requested_model)

    if requested_model != resolved_model:
        logger.info(
            "model_alias_resolved "
            f"endpoint={endpoint} "
            f"request_id={request_id} "
            f"requested_model={requested_model} "
            f"resolved_model={resolved_model}"
        )

    return requested_model, resolved_model


def _resolve_provider_for_request(provider: str | None) -> str:
    if provider is None:
        return DEFAULT_PROVIDER

    resolved_provider = provider.strip().lower()

    if resolved_provider in SUPPORTED_PROVIDERS:
        return resolved_provider

    supported_providers = ", ".join(SUPPORTED_PROVIDERS)
    raise HTTPException(
        status_code=400,
        detail=(
            f"Unsupported provider '{provider}'. "
            f"Supported providers: {supported_providers}"
        ),
    )


def _generate_response(
    prompt: str,
    requested_model: str,
    resolved_model: str,
    provider: str,
    request_id: str | None = None,
):

    try:
        response = generate(prompt=prompt, model=resolved_model)
    except UpstreamServiceError as e:
        logger.error(
            "generate_upstream_error "
            f"request_id={request_id} "
            f"requested_model={requested_model} "
            f"resolved_model={resolved_model} "
            f"error={str(e)}"
        )
        headers = {"X-Request-Id": request_id} if request_id else None
        raise HTTPException(status_code=502, detail=str(e), headers=headers) from e

    payload = {"provider": provider, "model": requested_model, "response": response}
    if requested_model != resolved_model:
        payload["resolved_model"] = resolved_model

    return payload


def _request_id(request: Request) -> str:
    return request.headers.get("X-Request-Id") or uuid.uuid4().hex[:12]


def _latency_ms(start: float) -> int:
    return int((time.perf_counter() - start) * 1000)


def _first_non_empty_env(*keys: str) -> str | None:
    for key in keys:
        value = os.environ.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()

    return None


def _safe_version_summary() -> dict[str, str]:
    app_version = _first_non_empty_env(*APP_VERSION_ENV_KEYS)
    commit_sha = _first_non_empty_env(*COMMIT_SHA_ENV_KEYS)

    summary = {
        "app_version": app_version or "unavailable",
        "commit_sha": (commit_sha[:7] if commit_sha else "unavailable"),
    }
    if app_version or commit_sha:
        summary["status"] = "ok"
    else:
        summary["status"] = "unavailable"

    return summary


def _increment_metric(metric_key: str) -> None:
    increment_metric(metric_key)


def _metrics_snapshot() -> dict[str, int]:
    return metrics_snapshot()


def _reset_metrics() -> None:
    reset_metrics()



def _log_request_event(
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


class AppOperationalRouterDependencies:
    logger = logger

    def _request_id(self, request: Request) -> str:
        return _request_id(request)

    def _log_request_event(self, phase: str, endpoint: str, request_id: str, **kwargs) -> None:
        _log_request_event(phase, endpoint, request_id, **kwargs)

    def health_check(self) -> None:
        health_check()

    @property
    def UpstreamServiceError(self):
        return UpstreamServiceError

    @property
    def OUTCOME_FAILURE(self) -> str:
        return OUTCOME_FAILURE

    @property
    def OUTCOME_SUCCESS(self) -> str:
        return OUTCOME_SUCCESS

    def _latency_ms(self, start: float) -> int:
        return _latency_ms(start)

    def _safe_version_summary(self) -> dict[str, str]:
        return _safe_version_summary()

    def _metrics_snapshot(self) -> dict[str, int]:
        return _metrics_snapshot()

    @property
    def preset_service(self):
        return preset_service

    @property
    def DEFAULT_MODEL(self) -> str:
        return DEFAULT_MODEL

    @property
    def OLLAMA_BASE_URL(self) -> str | None:
        return OLLAMA_BASE_URL

    @property
    def LEGACY_REQUEST_TIMEOUT(self) -> float:
        return LEGACY_REQUEST_TIMEOUT

    @property
    def OLLAMA_CONNECT_TIMEOUT(self) -> float:
        return OLLAMA_CONNECT_TIMEOUT

    @property
    def OLLAMA_READ_TIMEOUT(self) -> float:
        return OLLAMA_READ_TIMEOUT

    @property
    def OLLAMA_STREAM_READ_TIMEOUT(self) -> float:
        return OLLAMA_STREAM_READ_TIMEOUT

    @property
    def RETRY_COUNT(self) -> int:
        return RETRY_COUNT

    @property
    def SUPPORTED_PROVIDERS(self) -> tuple[str, ...]:
        return SUPPORTED_PROVIDERS

    @property
    def DEFAULT_PROVIDER(self) -> str:
        return DEFAULT_PROVIDER

    @property
    def AgentBrainResponse(self):
        return AgentBrainResponse

    def collect_local_server_status(self) -> dict[str, object]:
        return collect_local_server_status()

    @property
    def AgentBrainSummary(self):
        return AgentBrainSummary

    def format_agent_brain_summary(self, summary: AgentBrainSummary) -> dict[str, object]:
        return format_agent_brain_summary(summary)


operational_router_dependencies: OperationalRouterDependencies = AppOperationalRouterDependencies()
app.include_router(create_operational_router(operational_router_dependencies))


@app.post("/chat")
def chat(req: ChatRequest, request: Request, response: Response):
    start = time.perf_counter()
    request_id = _request_id(request)
    metadata = prepare_non_stream_request_metadata(
        model=req.model,
        provider=req.provider,
        preset=req.preset,
        endpoint="/chat",
        request_id=request_id,
        default_provider=DEFAULT_PROVIDER,
        resolve_model=_resolve_model_for_request,
        normalize_preset_name=preset_service.normalize_preset_name,
    )

    _log_request_event(
        "start",
        "/chat",
        request_id,
        model=metadata.requested_model,
        preset=metadata.normalized_preset,
        provider=metadata.observed_provider,
    )
    _increment_metric("requests_total")
    _increment_metric("chat_requests")

    try:
        resolved_provider = _resolve_provider_for_request(req.provider)
        api_response = run_non_stream_generation(
            prompt=req.prompt,
            preset=req.preset,
            requested_model=metadata.requested_model,
            resolved_model=metadata.resolved_model,
            provider=resolved_provider,
            request_id=request_id,
            apply_prompt_preset=preset_service.apply_prompt_preset,
            generate_response=_generate_response,
        )
    except HTTPException as e:
        _increment_metric("errors_total")
        _log_request_event(
            "complete",
            "/chat",
            request_id,
            model=metadata.requested_model,
            preset=metadata.normalized_preset,
            provider=metadata.observed_provider,
            outcome=OUTCOME_FAILURE,
            latency_ms=_latency_ms(start),
            error=str(e.detail),
        )
        raise

    response.headers["X-Request-Id"] = request_id
    _log_request_event(
        "complete",
        "/chat",
        request_id,
        model=metadata.requested_model,
        preset=metadata.normalized_preset,
        provider=metadata.observed_provider,
        outcome="success",
        latency_ms=_latency_ms(start),
    )

    return api_response


@app.get("/models")
def models(request: Request, response: Response):
    start = time.perf_counter()
    request_id = _request_id(request)

    _log_request_event("start", "/models", request_id)
    _increment_metric("requests_total")

    try:
        api_response = {"models": list_models()}
    except UpstreamServiceError as e:
        _increment_metric("errors_total")
        _log_request_event(
            "complete",
            "/models",
            request_id,
            outcome=OUTCOME_FAILURE,
            latency_ms=_latency_ms(start),
            error=str(e),
        )
        raise HTTPException(
            status_code=502,
            detail=str(e),
            headers={"X-Request-Id": request_id},
        ) from e

    response.headers["X-Request-Id"] = request_id

    _log_request_event(
        "complete",
        "/models",
        request_id,
        outcome="success",
        latency_ms=_latency_ms(start),
    )

    return api_response


@app.post("/generate", deprecated=True)
def generate_api(req: ChatRequest, request: Request, response: Response):
    start = time.perf_counter()

    request_id = _request_id(request)
    metadata = prepare_non_stream_request_metadata(
        model=req.model,
        provider=req.provider,
        preset=req.preset,
        endpoint="/generate",
        request_id=request_id,
        default_provider=DEFAULT_PROVIDER,
        resolve_model=_resolve_model_for_request,
        normalize_preset_name=preset_service.normalize_preset_name,
    )

    _log_request_event(
        "start",
        "/generate",
        request_id,
        model=metadata.requested_model,
        preset=metadata.normalized_preset,
        provider=metadata.observed_provider,
    )
    _increment_metric("requests_total")
    _increment_metric("chat_requests")

    try:
        resolved_provider = _resolve_provider_for_request(req.provider)
        api_response = run_non_stream_generation(
            prompt=req.prompt,
            preset=req.preset,
            requested_model=metadata.requested_model,
            resolved_model=metadata.resolved_model,
            provider=resolved_provider,
            request_id=request_id,
            apply_prompt_preset=preset_service.apply_prompt_preset,
            generate_response=_generate_response,
        )
    except HTTPException as e:
        _increment_metric("errors_total")
        _log_request_event(
            "complete",
            "/generate",
            request_id,
            model=metadata.requested_model,
            preset=metadata.normalized_preset,
            provider=metadata.observed_provider,
            outcome=OUTCOME_FAILURE,
            latency_ms=_latency_ms(start),
            error=str(e.detail),
        )
        raise

    response.headers["X-Request-Id"] = request_id
    response.headers["Deprecation"] = "true"
    response.headers["Link"] = '</chat>; rel="successor-version"'

    _log_request_event(
        "complete",
        "/generate",
        request_id,
        model=metadata.requested_model,
        preset=metadata.normalized_preset,
        provider=metadata.observed_provider,
        outcome="success",
        latency_ms=_latency_ms(start),
    )

    return api_response



class EmbeddingRequest(BaseModel):
    text: str


@app.post("/embedding")
def embedding_api(req: EmbeddingRequest, request: Request, response: Response):
    start = time.perf_counter()
    request_id = _request_id(request)

    _log_request_event("start", "/embedding", request_id)
    _increment_metric("requests_total")
    _increment_metric("embedding_requests")

    try:
        vector = embedding(req.text)
    except UpstreamServiceError as e:
        _increment_metric("errors_total")
        _log_request_event(
            "complete",
            "/embedding",
            request_id,
            outcome=OUTCOME_FAILURE,
            latency_ms=_latency_ms(start),
            error=str(e),
        )
        raise HTTPException(
            status_code=502,
            detail=str(e),
            headers={"X-Request-Id": request_id},
        ) from e

    response.headers["X-Request-Id"] = request_id

    _log_request_event(
        "complete",
        "/embedding",
        request_id,
        outcome="success",
        latency_ms=_latency_ms(start),
    )

    return {"embedding": vector}


def _prepare_stream_request(req: ChatRequest, request_id: str) -> dict[str, str]:
    requested_model, resolved_model = _resolve_model_for_request(
        req.model,
        endpoint="/generate_stream",
        request_id=request_id,
    )
    normalized_preset = preset_service.normalize_preset_name(req.preset)
    observed_provider = (
        req.provider.strip().lower()
        if isinstance(req.provider, str)
        else DEFAULT_PROVIDER
    )
    return {
        "requested_model": requested_model,
        "resolved_model": resolved_model,
        "normalized_preset": normalized_preset,
        "observed_provider": observed_provider,
    }


def _create_upstream_stream(req: ChatRequest, resolved_model: str):
    _resolve_provider_for_request(req.provider)
    shaped_prompt = preset_service.apply_prompt_preset(req.prompt, req.preset)
    return generate_stream(prompt=shaped_prompt, model=resolved_model)


def _stream_with_completion_logging(
    upstream_generator,
    *,
    request_id: str,
    requested_model: str,
    normalized_preset: str | None,
    observed_provider: str,
    start: float,
):
    outcome = OUTCOME_SUCCESS
    error = None

    try:
        stream_completed = yield from _normalize_upstream_stream_events(
            upstream_generator,
            request_id=request_id,
        )
        if not stream_completed:
            outcome = OUTCOME_INCOMPLETE
    except Exception as e:
        outcome = OUTCOME_FAILURE
        error = str(e)
        raise
    except BaseException as e:
        outcome = OUTCOME_FAILURE
        error = type(e).__name__
        raise
    finally:
        if outcome == OUTCOME_FAILURE:
            _increment_metric("errors_total")
        _log_request_event(
            "complete",
            "/generate_stream",
            request_id,
            model=requested_model,
            preset=normalized_preset,
            provider=observed_provider,
            outcome=outcome,
            latency_ms=_latency_ms(start),
            error=error,
        )



@app.post("/generate_stream")
def generate_stream_api(req: ChatRequest, request: Request):
    start = time.perf_counter()
    request_id = _request_id(request)

    try:
        stream_metadata = _prepare_stream_request(req, request_id)
    except HTTPException as e:
        _increment_metric("errors_total")
        _log_request_event(
            "complete",
            "/generate_stream",
            request_id,
            outcome=OUTCOME_FAILURE,
            latency_ms=_latency_ms(start),
            error=str(e.detail),
        )
        raise

    _log_request_event(
        "start",
        "/generate_stream",
        request_id,
        model=stream_metadata["requested_model"],
        preset=stream_metadata["normalized_preset"],
        provider=stream_metadata["observed_provider"],
    )
    _increment_metric("requests_total")
    _increment_metric("stream_requests")

    try:
        upstream_generator = _create_upstream_stream(
            req,
            stream_metadata["resolved_model"],
        )
    except HTTPException as e:
        _increment_metric("errors_total")
        _log_request_event(
            "complete",
            "/generate_stream",
            request_id,
            model=stream_metadata["requested_model"],
            preset=stream_metadata["normalized_preset"],
            provider=stream_metadata["observed_provider"],
            outcome=OUTCOME_FAILURE,
            latency_ms=_latency_ms(start),
            error=str(e.detail),
        )
        raise
    except UpstreamServiceError as e:
        _increment_metric("errors_total")
        _log_request_event(
            "complete",
            "/generate_stream",
            request_id,
            model=stream_metadata["requested_model"],
            preset=stream_metadata["normalized_preset"],
            provider=stream_metadata["observed_provider"],
            outcome=OUTCOME_FAILURE,
            latency_ms=_latency_ms(start),
            error=str(e),
        )
        raise HTTPException(
            status_code=502,
            detail=str(e),
            headers={"X-Request-Id": request_id},
        ) from e

    response = StreamingResponse(
        _stream_with_completion_logging(
            upstream_generator,
            request_id=request_id,
            requested_model=stream_metadata["requested_model"],
            normalized_preset=stream_metadata["normalized_preset"],
            observed_provider=stream_metadata["observed_provider"],
            start=start,
        ),
        media_type="application/x-ndjson",
    )
    response.headers["X-Request-Id"] = request_id

    return response


def _normalize_upstream_stream_events(upstream_generator, request_id: str | None = None):
    done_emitted = False

    for raw_line in upstream_generator:
        line = raw_line.strip()

        if not line:
            continue

        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            logger.warning(
                f"stream_payload_invalid request_id={request_id} reason=invalid_json"
            )
            continue

        if not isinstance(event, dict):
            logger.warning(
                f"stream_payload_invalid request_id={request_id} reason=non_object"
            )
            continue

        chunk = event.get("response")

        if isinstance(chunk, str) and chunk:
            yield json.dumps({"response": chunk, "done": False}) + "\n"

        if event.get("done") is True:
            yield json.dumps({"done": True}) + "\n"
            done_emitted = True
            break

    if not done_emitted:
        logger.warning(
            "stream_done_missing request_id="
            f"{request_id} detail=upstream_ended_without_explicit_done"
        )

    return done_emitted
