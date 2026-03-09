import os
import time

import requests
from dotenv import load_dotenv

from logger import logger

load_dotenv()

OLLAMA_BASE_URL = os.environ.get("OLLAMA_BASE_URL", "http://desktop.home:11434")
REQUEST_TIMEOUT = int(os.environ.get("REQUEST_TIMEOUT", "90"))
RETRY_COUNT = int(os.environ.get("RETRY_COUNT", "2"))


def generate(prompt, model):
    logger.info(f"LLM call model={model}")
    payload = {"model": model, "prompt": prompt, "stream": False}

    for attempt in range(RETRY_COUNT + 1):
        try:
            r = requests.post(
                f"{OLLAMA_BASE_URL}/api/generate", json=payload, timeout=REQUEST_TIMEOUT
            )
            r.raise_for_status()
            return r.json()["response"]
        except requests.exceptions.RequestException as e:
            if attempt >= RETRY_COUNT:
                logger.error(f"Ollama generate failed after {RETRY_COUNT} retries: {e}")
                raise
            time.sleep(2**attempt)
            logger.warning(
                f"Ollama connection issue: {e}. "
                f"Retrying ({attempt + 1}/{RETRY_COUNT})..."
            )


def list_models():
    r = requests.get(f"{OLLAMA_BASE_URL}/api/tags", timeout=REQUEST_TIMEOUT)

    r.raise_for_status()

    data = r.json()

    return [m["name"] for m in data.get("models", [])]


def embedding(text, model="nomic-embed-text"):
    payload = {"model": model, "prompt": text}

    for attempt in range(RETRY_COUNT + 1):
        try:
            r = requests.post(
                f"{OLLAMA_BASE_URL}/api/embeddings",
                json=payload,
                timeout=REQUEST_TIMEOUT,
            )
            if r.status_code != 200:
                raise Exception(f"Ollama embedding error: {r.text}")
            return r.json()["embedding"]
        except Exception as e:
            if attempt >= RETRY_COUNT:
                logger.error(
                    f"Ollama embedding failed after {RETRY_COUNT} retries: {e}"
                )
                raise
            time.sleep(2**attempt)
            logger.warning(
                f"Ollama connection issue: {e}. "
                f"Retrying ({attempt + 1}/{RETRY_COUNT})..."
            )


def generate_stream(prompt, model):
    payload = {"model": model, "prompt": prompt, "stream": True}

    for attempt in range(RETRY_COUNT + 1):
        try:
            r = requests.post(
                f"{OLLAMA_BASE_URL}/api/generate",
                json=payload,
                stream=True,
                timeout=REQUEST_TIMEOUT,
            )
            r.raise_for_status()
            break
        except requests.exceptions.RequestException as e:
            if attempt >= RETRY_COUNT:
                logger.error(f"Ollama stream failed after {RETRY_COUNT} retries: {e}")
                raise
            time.sleep(2**attempt)
            logger.warning(
                f"Ollama connection issue: {e}. "
                f"Retrying ({attempt + 1}/{RETRY_COUNT})..."
            )

    for line in r.iter_lines():
        if not line:
            continue

        data = line.decode("utf-8")

        yield data
