import json
import os
import time
from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi import HTTPException
from fastapi import Request
from fastapi import Response
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from services.non_stream_request_flow import (
    prepare_non_stream_request_metadata,
    run_non_stream_generation,
)
from services.request_runtime import (
    OUTCOME_FAILURE,
    OUTCOME_INCOMPLETE,
    OUTCOME_SUCCESS,
    increment_request_metric as _increment_metric,
    latency_ms as _latency_ms,
    log_request_event as _log_request_event,
    request_id as _request_id,
    request_metrics_snapshot as _metrics_snapshot,
    reset_request_metrics as _reset_metrics,
    safe_version_summary as _safe_version_summary,
)
from services import presets as preset_service
from services.provider_adapter import CallableProviderAdapter, ProviderAdapter

from logger import logger
from routes.operational import (
    OperationalRouterDependencies,
    create_operational_router,
)
from routes.obsidian import create_obsidian_router
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


def _build_ollama_provider_adapter() -> ProviderAdapter:
    return CallableProviderAdapter(
        generate_fn=lambda *, prompt, model: generate(prompt=prompt, model=model),
        generate_stream_fn=lambda *, prompt, model: generate_stream(prompt=prompt, model=model),
        list_models_fn=lambda: list_models(),
        embedding_fn=lambda text: embedding(text),
    )


PROVIDER_ADAPTERS: dict[str, ProviderAdapter] = {
    DEFAULT_PROVIDER: _build_ollama_provider_adapter(),
}

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
    # Contract: clients send the original raw prompt plus preset metadata.
    # The gateway is responsible for applying preset prompt shaping.
    preset: str | None = None
    provider: str | None = None


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




def _provider_adapter_for_request(provider: str | None) -> tuple[str, ProviderAdapter]:
    resolved_provider = _resolve_provider_for_request(provider)
    provider_adapter = _adapter_for_provider(resolved_provider)
    return resolved_provider, provider_adapter


def _default_provider_adapter() -> ProviderAdapter:
    return _adapter_for_provider(DEFAULT_PROVIDER)


def _adapter_for_provider(provider: str) -> ProviderAdapter:
    try:
        return PROVIDER_ADAPTERS[provider]
    except KeyError as e:
        logger.error(f"provider_adapter_missing provider={provider}")
        raise HTTPException(
            status_code=500,
            detail=f"Provider adapter for '{provider}' is not configured.",
        ) from e


def _validate_non_blank_provider_response(
    response,
    *,
    endpoint: str,
    request_id: str | None,
    requested_model: str,
    resolved_model: str,
) -> str:
    if not isinstance(response, str) or not response.strip():
        logger.warning(
            "upstream_invalid_response "
            f"endpoint={endpoint} "
            f"request_id={request_id} "
            f"requested_model={requested_model} "
            f"resolved_model={resolved_model} "
            "reason=empty_response"
        )
        headers = {"X-Request-Id": request_id} if request_id else None
        raise HTTPException(
            status_code=502,
            detail="Invalid upstream response: empty response",
            headers=headers,
        )

    return response


def _generate_response(
    prompt: str,
    requested_model: str,
    resolved_model: str,
    provider: str,
    endpoint: str,
    provider_adapter: ProviderAdapter,
    request_id: str | None = None,
):

    try:
        response = provider_adapter.generate(prompt=prompt, model=resolved_model)
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

    response = _validate_non_blank_provider_response(
        response,
        endpoint=endpoint,
        request_id=request_id,
        requested_model=requested_model,
        resolved_model=resolved_model,
    )

    payload = {"provider": provider, "model": requested_model, "response": response}
    if requested_model != resolved_model:
        payload["resolved_model"] = resolved_model

    return payload


def _apply_gateway_prompt_preset(prompt: str, preset: str | None) -> str:
    """Apply preset shaping inside the gateway boundary.

    Downstream clients are expected to send raw `prompt` + optional `preset`
    structured data, and not pre-shaped prompt text.
    """

    return preset_service.apply_prompt_preset(prompt, preset)


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

operational_router_dependencies: OperationalRouterDependencies = AppOperationalRouterDependencies()
app.include_router(create_operational_router(operational_router_dependencies))
app.include_router(create_obsidian_router())


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
        resolved_provider, provider_adapter = _provider_adapter_for_request(req.provider)
        api_response = run_non_stream_generation(
            prompt=req.prompt,
            preset=req.preset,
            requested_model=metadata.requested_model,
            resolved_model=metadata.resolved_model,
            provider=resolved_provider,
            endpoint="/chat",
            request_id=request_id,
            apply_prompt_preset=_apply_gateway_prompt_preset,
            generate_response=_generate_response,
            provider_adapter=provider_adapter,
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
        api_response = {"models": _default_provider_adapter().list_models()}
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
    resolved_provider, provider_adapter = _provider_adapter_for_request(req.provider)

    _log_request_event(
        "start",
        "/generate",
        request_id,
        model=metadata.requested_model,
        preset=metadata.normalized_preset,
        provider=resolved_provider,
    )
    _increment_metric("requests_total")
    _increment_metric("chat_requests")
    _increment_metric("generate_requests")

    try:
        api_response = run_non_stream_generation(
            prompt=req.prompt,
            preset=req.preset,
            requested_model=metadata.requested_model,
            resolved_model=metadata.resolved_model,
            provider=resolved_provider,
            endpoint="/generate",
            request_id=request_id,
            apply_prompt_preset=_apply_gateway_prompt_preset,
            generate_response=_generate_response,
            provider_adapter=provider_adapter,
        )
    except HTTPException as e:
        _increment_metric("errors_total")
        _log_request_event(
            "complete",
            "/generate",
            request_id,
            model=metadata.requested_model,
            preset=metadata.normalized_preset,
            provider=resolved_provider,
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
        provider=resolved_provider,
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
        vector = _default_provider_adapter().embedding(text=req.text)
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
    _, provider_adapter = _provider_adapter_for_request(req.provider)
    shaped_prompt = _apply_gateway_prompt_preset(req.prompt, req.preset)
    return provider_adapter.generate_stream(prompt=shaped_prompt, model=resolved_model)


def _stream_with_completion_logging(
    upstream_generator,
    *,
    request_id: str,
    requested_model: str,
    resolved_model: str,
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
            requested_model=requested_model,
            resolved_model=resolved_model,
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
            resolved_model=stream_metadata["resolved_model"],
            normalized_preset=stream_metadata["normalized_preset"],
            observed_provider=stream_metadata["observed_provider"],
            start=start,
        ),
        media_type="application/x-ndjson",
    )
    response.headers["X-Request-Id"] = request_id

    return response


def _normalize_upstream_stream_events(
    upstream_generator,
    request_id: str | None = None,
    requested_model: str | None = None,
    resolved_model: str | None = None,
):
    done_emitted = False
    content_seen = False

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

        if isinstance(chunk, str):
            chunk_has_content = bool(chunk.strip())
            if chunk_has_content:
                content_seen = True

            should_emit = bool(chunk) and (chunk_has_content or content_seen)
            if should_emit:
                yield json.dumps({"response": chunk, "done": False}) + "\n"

        if event.get("done") is True:
            if not content_seen:
                logger.warning(
                    "stream_empty_response "
                    "endpoint=/generate_stream "
                    f"request_id={request_id} "
                    f"requested_model={requested_model} "
                    f"resolved_model={resolved_model} "
                    "reason=empty_response"
                )
            yield json.dumps({"done": True}) + "\n"
            done_emitted = True
            break

    if not done_emitted:
        logger.warning(
            "stream_done_missing request_id="
            f"{request_id} detail=upstream_ended_without_explicit_done"
        )

    return done_emitted
