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


def _generate_response(req: ChatRequest):
    model = req.model or DEFAULT_MODEL

    try:
        response = generate(prompt=req.prompt, model=model)
    except UpstreamServiceError as e:
        raise HTTPException(status_code=502, detail=str(e)) from e

    return {"model": model, "response": response}


def _request_id(request: Request) -> str:
    return request.headers.get("X-Request-Id") or uuid.uuid4().hex[:12]


@app.get("/health/live")
def health_live():
    logger.info("liveness check")

    return {"status": "ok"}


@app.get("/health/ready")
def health_ready():
    logger.info("readiness check")

    try:
        health_check()
    except UpstreamServiceError as e:
        raise HTTPException(status_code=503, detail=str(e)) from e

    return {"status": "ok", "upstream": "ok"}


@app.get("/health")
def health():
    return health_ready()


@app.post("/chat")
def chat(req: ChatRequest, request: Request, response: Response):
    start = time.time()
    model = req.model or DEFAULT_MODEL
    request_id = _request_id(request)

    logger.info(f"chat_request request_id={request_id} model={model}")

    api_response = _generate_response(req)
    response.headers["X-Request-Id"] = request_id

    elapsed = round(time.time() - start, 2)
    logger.info(
        f"chat_complete request_id={request_id} model={model} latency={elapsed}s"
    )

    return api_response


@app.get("/models")
def models(request: Request, response: Response):
    start = time.time()
    request_id = _request_id(request)

    logger.info(f"models_request request_id={request_id}")

    try:
        api_response = {"models": list_models()}
    except UpstreamServiceError as e:
        raise HTTPException(status_code=502, detail=str(e)) from e

    response.headers["X-Request-Id"] = request_id

    elapsed = round(time.time() - start, 2)
    logger.info(f"models_complete request_id={request_id} latency={elapsed}s")

    return api_response


@app.post("/generate", deprecated=True)
def generate_api(req: ChatRequest, request: Request, response: Response):
    start = time.time()

    model = req.model or DEFAULT_MODEL
    request_id = _request_id(request)

    logger.info(f"generate_request request_id={request_id} model={model}")

    api_response = _generate_response(req)

    response.headers["X-Request-Id"] = request_id
    response.headers["Deprecation"] = "true"
    response.headers["Link"] = '</chat>; rel="successor-version"'

    elapsed = round(time.time() - start, 2)

    logger.info(
        f"generate_complete request_id={request_id} model={model} latency={elapsed}s"
    )

    return api_response


class EmbeddingRequest(BaseModel):
    text: str


@app.post("/embedding")
def embedding_api(req: EmbeddingRequest, request: Request, response: Response):
    start = time.time()
    request_id = _request_id(request)

    logger.info(f"embedding_request request_id={request_id}")

    try:
        vector = embedding(req.text)
    except UpstreamServiceError as e:
        raise HTTPException(status_code=502, detail=str(e)) from e

    response.headers["X-Request-Id"] = request_id

    elapsed = round(time.time() - start, 2)
    logger.info(f"embedding_complete request_id={request_id} latency={elapsed}s")

    return {"embedding": vector}


@app.post("/generate_stream")
def generate_stream_api(req: ChatRequest, request: Request):
    start = time.time()
    model = req.model or DEFAULT_MODEL
    request_id = _request_id(request)

    logger.info(f"generate_stream_request request_id={request_id} model={model}")

    try:
        upstream_generator = generate_stream(prompt=req.prompt, model=model)
    except UpstreamServiceError as e:
        raise HTTPException(status_code=502, detail=str(e)) from e

    generator = _normalize_upstream_stream_events(upstream_generator)
    response = StreamingResponse(generator, media_type="application/x-ndjson")
    response.headers["X-Request-Id"] = request_id

    elapsed = round(time.time() - start, 2)
    logger.info(
        f"generate_stream_complete request_id={request_id} model={model} latency={elapsed}s"
    )

    return response


def _normalize_upstream_stream_events(upstream_generator):
    done_emitted = False

    for raw_line in upstream_generator:
        line = raw_line.strip()

        if not line:
            continue

        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            logger.warning("Skipping invalid upstream stream payload")
            continue

        if not isinstance(event, dict):
            logger.warning("Skipping non-object upstream stream payload")
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
            "Upstream stream ended without explicit done event; closing without synthetic completion"
        )
