import json
import os
import time
import uuid

from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi import HTTPException
from fastapi import Request
from fastapi import Response
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from logger import logger
from ollama_client import (
    UpstreamServiceError,
    embedding,
    generate,
    generate_stream,
    health_check,
    list_models,
)

load_dotenv()

DEFAULT_MODEL = os.environ.get("DEFAULT_MODEL", "deepseek-r1:8b")

app = FastAPI(title="AI Gateway")


class ChatRequest(BaseModel):
    prompt: str
    model: str | None = None


def _generate_response(req: ChatRequest, request_id: str | None = None):
    model = req.model or DEFAULT_MODEL

    try:
        response = generate(prompt=req.prompt, model=model)
    except UpstreamServiceError as e:
        logger.error(
            f"generate_upstream_error request_id={request_id} model={model} error={str(e)}"
        )
        headers = {"X-Request-Id": request_id} if request_id else None
        raise HTTPException(status_code=502, detail=str(e), headers=headers) from e

    return {"model": model, "response": response}


def _request_id(request: Request) -> str:
    return request.headers.get("X-Request-Id") or uuid.uuid4().hex[:12]


def _latency_ms(start: float) -> int:
    return int((time.perf_counter() - start) * 1000)


def _log_request_event(
    phase: str,
    endpoint: str,
    request_id: str,
    model: str | None = None,
    outcome: str | None = None,
    latency_ms: int | None = None,
    error: str | None = None,
):
    fields = [f"phase={phase}", f"endpoint={endpoint}", f"request_id={request_id}"]

    if model:
        fields.append(f"model={model}")
    if outcome:
        fields.append(f"outcome={outcome}")
    if latency_ms is not None:
        fields.append(f"latency_ms={latency_ms}")
    if error:
        fields.append(f"error={error}")

    message = " ".join(fields)

    if outcome == "failure":
        logger.error(message)
    else:
        logger.info(message)


@app.get("/health/live")
def health_live(request: Request, response: Response):
    request_id = _request_id(request)
    logger.info(f"liveness_check request_id={request_id}")
    response.headers["X-Request-Id"] = request_id

    return {"status": "ok"}


@app.get("/health/ready")
def health_ready(request: Request, response: Response):
    start = time.perf_counter()
    request_id = _request_id(request)
    _log_request_event("start", "/health/ready", request_id)

    try:
        health_check()
    except UpstreamServiceError as e:
        _log_request_event(
            "complete",
            "/health/ready",
            request_id,
            outcome="failure",
            latency_ms=_latency_ms(start),
            error=str(e),
        )
        raise HTTPException(
            status_code=503,
            detail=str(e),
            headers={"X-Request-Id": request_id},
        ) from e

    response.headers["X-Request-Id"] = request_id
    _log_request_event(
        "complete",
        "/health/ready",
        request_id,
        outcome="success",
        latency_ms=_latency_ms(start),
    )

    return {"status": "ok", "upstream": "ok"}


@app.get("/health")
def health(request: Request, response: Response):
    return health_ready(request, response)


@app.post("/chat")
def chat(req: ChatRequest, request: Request, response: Response):
    start = time.perf_counter()
    model = req.model or DEFAULT_MODEL
    request_id = _request_id(request)

    _log_request_event("start", "/chat", request_id, model=model)

    try:
        api_response = _generate_response(req, request_id=request_id)
    except HTTPException as e:
        _log_request_event(
            "complete",
            "/chat",
            request_id,
            model=model,
            outcome="failure",
            latency_ms=_latency_ms(start),
            error=str(e.detail),
        )
        raise

    response.headers["X-Request-Id"] = request_id
    _log_request_event(
        "complete",
        "/chat",
        request_id,
        model=model,
        outcome="success",
        latency_ms=_latency_ms(start),
    )

    return api_response


@app.get("/models")
def models(request: Request, response: Response):
    start = time.perf_counter()
    request_id = _request_id(request)

    _log_request_event("start", "/models", request_id)

    try:
        api_response = {"models": list_models()}
    except UpstreamServiceError as e:
        _log_request_event(
            "complete",
            "/models",
            request_id,
            outcome="failure",
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

    model = req.model or DEFAULT_MODEL
    request_id = _request_id(request)

    _log_request_event("start", "/generate", request_id, model=model)

    try:
        api_response = _generate_response(req, request_id=request_id)
    except HTTPException as e:
        _log_request_event(
            "complete",
            "/generate",
            request_id,
            model=model,
            outcome="failure",
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
        model=model,
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

    try:
        vector = embedding(req.text)
    except UpstreamServiceError as e:
        _log_request_event(
            "complete",
            "/embedding",
            request_id,
            outcome="failure",
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


@app.post("/generate_stream")
def generate_stream_api(req: ChatRequest, request: Request):
    start = time.perf_counter()
    model = req.model or DEFAULT_MODEL
    request_id = _request_id(request)

    _log_request_event("start", "/generate_stream", request_id, model=model)

    try:
        upstream_generator = generate_stream(prompt=req.prompt, model=model)
    except UpstreamServiceError as e:
        _log_request_event(
            "complete",
            "/generate_stream",
            request_id,
            model=model,
            outcome="failure",
            latency_ms=_latency_ms(start),
            error=str(e),
        )
        raise HTTPException(
            status_code=502,
            detail=str(e),
            headers={"X-Request-Id": request_id},
        ) from e

    def stream_with_completion_logging():
        outcome = "success"
        error = None

        try:
            yield from _normalize_upstream_stream_events(
                upstream_generator,
                request_id=request_id,
            )
        except Exception as e:
            outcome = "failure"
            error = str(e)
            raise
        except BaseException as e:
            outcome = "failure"
            error = type(e).__name__
            raise
        finally:
            _log_request_event(
                "complete",
                "/generate_stream",
                request_id,
                model=model,
                outcome=outcome,
                latency_ms=_latency_ms(start),
                error=error,
            )

    response = StreamingResponse(
        stream_with_completion_logging(),
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
