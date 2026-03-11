import os
import time

from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi import HTTPException
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


@app.get("/health")
def health():
    logger.info("health check")

    try:
        health_check()
    except UpstreamServiceError as e:
        raise HTTPException(status_code=503, detail=str(e)) from e

    return {"status": "ok", "upstream": "ok"}


@app.post("/chat")
def chat(req: ChatRequest):
    return _generate_response(req)


@app.get("/models")
def models():
    try:
        return {"models": list_models()}
    except UpstreamServiceError as e:
        raise HTTPException(status_code=502, detail=str(e)) from e


@app.post("/generate", deprecated=True)
def generate_api(req: ChatRequest, response: Response):
    start = time.time()

    model = req.model or DEFAULT_MODEL

    logger.info(f"GENERATE request model={model}")

    api_response = _generate_response(req)

    response.headers["Deprecation"] = "true"
    response.headers["Link"] = '</chat>; rel="successor-version"'

    elapsed = round(time.time() - start, 2)

    logger.info(f"GENERATE response time={elapsed}s")

    return api_response


class EmbeddingRequest(BaseModel):
    text: str


@app.post("/embedding")
def embedding_api(req: EmbeddingRequest):
    try:
        vector = embedding(req.text)
    except UpstreamServiceError as e:
        raise HTTPException(status_code=502, detail=str(e)) from e

    return {"embedding": vector}


@app.post("/generate_stream")
def generate_stream_api(req: ChatRequest):
    model = req.model or DEFAULT_MODEL

    logger.info(f"STREAM request model={model}")

    try:
        generator = generate_stream(prompt=req.prompt, model=model)
    except UpstreamServiceError as e:
        raise HTTPException(status_code=502, detail=str(e)) from e

    return StreamingResponse(generator, media_type="application/x-ndjson")
