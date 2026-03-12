import os
import time
from threading import local

import requests
from dotenv import load_dotenv

from logger import logger

load_dotenv()

OLLAMA_BASE_URL = os.environ.get("OLLAMA_BASE_URL", "http://desktop.home:11434")
REQUEST_TIMEOUT = int(os.environ.get("REQUEST_TIMEOUT", "90"))
RETRY_COUNT = int(os.environ.get("RETRY_COUNT", "2"))
_thread_local = local()


class UpstreamServiceError(Exception):
    """Raised when Ollama cannot be reached or returns an invalid response."""


def _get_session():
    session = getattr(_thread_local, "session", None)

    if session is None:
        session = requests.Session()
        _thread_local.session = session

    return session


def _parse_json_object(response, endpoint):
    try:
        data = response.json()
    except ValueError as e:
        logger.error(f"Invalid Ollama {endpoint} JSON payload: {e}")
        raise UpstreamServiceError(f"Ollama {endpoint} response invalid") from e

    if not isinstance(data, dict):
        logger.error(
            f"Invalid Ollama {endpoint} payload type: "
            f"expected object, got {type(data).__name__}"
        )
        raise UpstreamServiceError(f"Ollama {endpoint} response invalid")

    return data


def generate(prompt, model):
    logger.info(f"LLM call model={model}")
    payload = {"model": model, "prompt": prompt, "stream": False}

    for attempt in range(RETRY_COUNT + 1):
        try:
            r = _get_session().post(
                f"{OLLAMA_BASE_URL}/api/generate", json=payload, timeout=REQUEST_TIMEOUT
            )
            r.raise_for_status()
            data = _parse_json_object(r, "generate")
            return data["response"]
        except requests.exceptions.RequestException as e:
            if attempt >= RETRY_COUNT:
                logger.error(f"Ollama generate failed after {RETRY_COUNT} retries: {e}")
                raise UpstreamServiceError("Ollama generate request failed") from e
            time.sleep(2**attempt)
            logger.warning(
                f"Ollama connection issue: {e}. "
                f"Retrying ({attempt + 1}/{RETRY_COUNT})..."
            )
        except (KeyError, TypeError) as e:
            logger.error(f"Invalid Ollama generate response payload: {e}")
            raise UpstreamServiceError("Ollama generate response invalid") from e


def list_models():
    try:
        r = _get_session().get(f"{OLLAMA_BASE_URL}/api/tags", timeout=REQUEST_TIMEOUT)
        r.raise_for_status()
        data = _parse_json_object(r, "list models")
        return [m["name"] for m in data.get("models", [])]
    except requests.exceptions.RequestException as e:
        logger.error(f"Ollama list models failed: {e}")
        raise UpstreamServiceError("Ollama list models request failed") from e
    except (KeyError, TypeError) as e:
        logger.error(f"Invalid Ollama list models response payload: {e}")
        raise UpstreamServiceError("Ollama list models response invalid") from e


def health_check():
    try:
        r = _get_session().get(f"{OLLAMA_BASE_URL}/api/tags", timeout=REQUEST_TIMEOUT)
        r.raise_for_status()
        _parse_json_object(r, "health check")
    except requests.exceptions.RequestException as e:
        logger.error(f"Ollama health check failed: {e}")
        raise UpstreamServiceError("Ollama health check request failed") from e


def embedding(text, model="nomic-embed-text"):
    payload = {"model": model, "prompt": text}

    for attempt in range(RETRY_COUNT + 1):
        try:
            r = _get_session().post(
                f"{OLLAMA_BASE_URL}/api/embeddings",
                json=payload,
                timeout=REQUEST_TIMEOUT,
            )
            r.raise_for_status()
            data = _parse_json_object(r, "embedding")
            return data["embedding"]
        except requests.exceptions.RequestException as e:
            if attempt >= RETRY_COUNT:
                logger.error(
                    f"Ollama embedding failed after {RETRY_COUNT} retries: {e}"
                )
                raise UpstreamServiceError("Ollama embedding request failed") from e
            time.sleep(2**attempt)
            logger.warning(
                f"Ollama connection issue: {e}. "
                f"Retrying ({attempt + 1}/{RETRY_COUNT})..."
            )
        except (KeyError, TypeError) as e:
            logger.error(f"Invalid Ollama embedding response payload: {e}")
            raise UpstreamServiceError("Ollama embedding response invalid") from e


def generate_stream(prompt, model):
    payload = {"model": model, "prompt": prompt, "stream": True}

    for attempt in range(RETRY_COUNT + 1):
        try:
            r = _get_session().post(
                f"{OLLAMA_BASE_URL}/api/generate",
                json=payload,
                stream=True,
                timeout=REQUEST_TIMEOUT,
            )
            r.raise_for_status()
            return _iter_stream_lines(r)
        except requests.exceptions.RequestException as e:
            if attempt >= RETRY_COUNT:
                logger.error(f"Ollama stream failed after {RETRY_COUNT} retries: {e}")
                raise UpstreamServiceError("Ollama stream request failed") from e
            time.sleep(2**attempt)
            logger.warning(
                f"Ollama connection issue: {e}. "
                f"Retrying ({attempt + 1}/{RETRY_COUNT})..."
            )


def _iter_stream_lines(response):
    try:
        for line in response.iter_lines(decode_unicode=True):
            if not line:
                continue

            yield f"{line}\n"

    finally:
        response.close()
