import os
import time

from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from logger import logger
from ollama_client import embedding, generate, generate_stream, list_models

load_dotenv()

DEFAULT_MODEL = os.environ.get("DEFAULT_MODEL", "deepseek-r1:8b")

app = FastAPI(title="AI Gateway")


class ChatRequest(BaseModel):
    prompt: str
    model: str | None = None


@app.get("/health")
def health():
    logger.info("health check")

    return {"status": "ok"}


@app.post("/chat")
def chat(req: ChatRequest):
    model = req.model or DEFAULT_MODEL

    response = generate(prompt=req.prompt, model=model)

    return {"model": model, "response": response}


@app.get("/models")
def models():
    return {"models": list_models()}


class GenerateRequest(BaseModel):
    prompt: str
    model: str | None = None


@app.post("/generate")
def generate_api(req: GenerateRequest):
    start = time.time()

    model = req.model or DEFAULT_MODEL

    logger.info(f"GENERATE request model={model}")

    response = generate(prompt=req.prompt, model=model)

    elapsed = round(time.time() - start, 2)

    logger.info(f"GENERATE response time={elapsed}s")

    return {"model": model, "response": response}


class EmbeddingRequest(BaseModel):
    text: str


@app.post("/embedding")
def embedding_api(req: EmbeddingRequest):
    vector = embedding(req.text)

    return {"embedding": vector}


@app.post("/generate_stream")
def generate_stream_api(req: GenerateRequest):
    model = req.model or DEFAULT_MODEL

    logger.info(f"STREAM request model={model}")

    generator = generate_stream(prompt=req.prompt, model=model)

    return StreamingResponse(generator, media_type="application/json")
