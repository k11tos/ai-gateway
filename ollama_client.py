import time
import requests
from logger import logger

from config import (
    OLLAMA_BASE_URL,
    REQUEST_TIMEOUT,
    RETRY_COUNT
)


def generate(prompt, model):
    
    logger.info(f"LLM call model={model}")
    payload = {
        "model": model,
        "prompt": prompt,
        "stream": False
    }

    r = requests.post(
        f"{OLLAMA_BASE_URL}/api/generate",
        json=payload,
        timeout=REQUEST_TIMEOUT
    )

    r.raise_for_status()

    return r.json()["response"]
            

def list_models():

    r = requests.get(
        f"{OLLAMA_BASE_URL}/api/tags",
        timeout=REQUEST_TIMEOUT
    )

    r.raise_for_status()

    data = r.json()

    return [m["name"] for m in data.get("models", [])]


def embedding(text, model="nomic-embed-text"):

    payload = {
        "model": model,
        "prompt": text
    }

    r = requests.post(
        f"{OLLAMA_BASE_URL}/api/embeddings",
        json=payload,
        timeout=REQUEST_TIMEOUT
    )

    if r.status_code != 200:
        raise Exception(f"Ollama embedding error: {r.text}")

    return r.json()["embedding"]


def generate_stream(prompt, model):

    payload = {
        "model": model,
        "prompt": prompt,
        "stream": True
    }

    r = requests.post(
        f"{OLLAMA_BASE_URL}/api/generate",
        json=payload,
        stream=True,
        timeout=REQUEST_TIMEOUT
    )

    r.raise_for_status()

    for line in r.iter_lines():

        if not line:
            continue

        data = line.decode("utf-8")

        yield data