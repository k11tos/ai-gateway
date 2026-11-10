"""OpenRouter client; module name retained for existing imports."""

import json
import math
import os
import time
from threading import local

import requests
from dotenv import load_dotenv

from logger import logger

load_dotenv()

OPENROUTER_BASE_URL = os.environ.get(
    "OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1"
).rstrip("/")
OPENROUTER_API_KEY = os.environ.get("OPENROUTER_API_KEY", "")


def _get_timeout_env(name, default):
    try:
        value = float(os.environ.get(name, default))
        if not math.isfinite(value) or value <= 0:
            raise ValueError
        return value
    except ValueError:
        logger.warning(f"Invalid {name}; using fallback timeout of {default}s")
        return default


LEGACY_REQUEST_TIMEOUT = _get_timeout_env("REQUEST_TIMEOUT", 90.0)
OPENROUTER_CONNECT_TIMEOUT = _get_timeout_env(
    "OPENROUTER_CONNECT_TIMEOUT", LEGACY_REQUEST_TIMEOUT
)
OPENROUTER_READ_TIMEOUT = _get_timeout_env(
    "OPENROUTER_READ_TIMEOUT", LEGACY_REQUEST_TIMEOUT
)
OPENROUTER_STREAM_READ_TIMEOUT = _get_timeout_env(
    "OPENROUTER_STREAM_READ_TIMEOUT", OPENROUTER_READ_TIMEOUT
)
OPENROUTER_REQUEST_TIMEOUT = (OPENROUTER_CONNECT_TIMEOUT, OPENROUTER_READ_TIMEOUT)
OPENROUTER_STREAM_REQUEST_TIMEOUT = (
    OPENROUTER_CONNECT_TIMEOUT, OPENROUTER_STREAM_READ_TIMEOUT
)
RETRY_COUNT = int(os.environ.get("RETRY_COUNT", "2"))
_thread_local = local()


class UpstreamServiceError(Exception):
    """Safe, public error message without upstream bodies or credentials."""

    status_code = 502


class FreeModelRequiredError(UpstreamServiceError):
    status_code = 400


class EmbeddingUnsupportedError(UpstreamServiceError):
    status_code = 501


def _get_session():
    session = getattr(_thread_local, "session", None)
    if session is None:
        session = requests.Session()
        _thread_local.session = session
    return session


def _headers():
    if not OPENROUTER_API_KEY.strip():
        raise UpstreamServiceError("OpenRouter API key is not configured")
    return {"Authorization": f"Bearer {OPENROUTER_API_KEY}"}


def _payload(prompt, model, stream):
    if not isinstance(model, str) or not model.endswith(":free"):
        raise FreeModelRequiredError("Only model IDs ending in :free are supported")
    return {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "stream": stream,
        # Defense in depth: never route to a provider that charges for tokens.
        "provider": {"max_price": {"prompt": 0, "completion": 0}},
    }


def _request(method, endpoint, *, payload=None, stream=False):
    headers = _headers()
    for attempt in range(RETRY_COUNT + 1):
        response = None
        try:
            kwargs = {
                "headers": headers,
                "timeout": (OPENROUTER_STREAM_REQUEST_TIMEOUT if stream
                            else OPENROUTER_REQUEST_TIMEOUT),
                "allow_redirects": False,
            }
            if method == "post":
                kwargs.update(json=payload, stream=stream)
            response = getattr(_get_session(), method)(
                f"{OPENROUTER_BASE_URL}{endpoint}", **kwargs
            )
            if response.status_code != 200:
                status = response.status_code
                response.close()
                if status in (401, 403):
                    raise UpstreamServiceError("OpenRouter authentication failed")
                raise UpstreamServiceError(f"OpenRouter request failed (HTTP {status})")
            return response
        except requests.exceptions.RequestException:
            if response is not None:
                response.close()
            if attempt >= RETRY_COUNT:
                raise UpstreamServiceError("OpenRouter connection failed") from None
            time.sleep(2**attempt)


def _parse_json_object(response):
    try:
        data = response.json()
        if not isinstance(data, dict) or "error" in data:
            raise ValueError
        return data
    except ValueError:
        raise UpstreamServiceError("OpenRouter response invalid") from None


def generate(prompt, model):
    response = _request("post", "/chat/completions", payload=_payload(prompt, model, False))
    try:
        data = _parse_json_object(response)
        try:
            choice = data["choices"][0]
            if choice.get("finish_reason") not in (None, "stop", "length"):
                raise ValueError
            content = choice["message"]["content"]
            if not isinstance(content, str) or not content.strip():
                raise ValueError
            return content
        except (KeyError, IndexError, TypeError, ValueError):
            raise UpstreamServiceError("OpenRouter response invalid") from None
    finally:
        response.close()


def list_models():
    response = _request("get", "/models")
    try:
        models = _parse_json_object(response).get("data")
        if not isinstance(models, list) or any(
            not isinstance(m, dict) or not isinstance(m.get("id"), str) for m in models
        ):
            raise UpstreamServiceError("OpenRouter model list invalid")
        return [m["id"] for m in models if m["id"].endswith(":free")]
    finally:
        response.close()


def health_check():
    # /models is public and cannot establish whether the API key is valid.
    response = _request("get", "/key")
    try:
        if not isinstance(_parse_json_object(response).get("data"), dict):
            raise UpstreamServiceError("OpenRouter health response invalid")
    finally:
        response.close()


def embedding(text, model=None):
    raise EmbeddingUnsupportedError("Embedding is unsupported: no free model configured")


def generate_stream(prompt, model):
    response = _request(
        "post", "/chat/completions", payload=_payload(prompt, model, True), stream=True
    )
    return _iter_stream_lines(response)


def _sse_data(response):
    """Collect SSE data fields, ignoring comments/keepalives and other fields."""
    fields = []
    for line in response.iter_lines(decode_unicode=False):
        if isinstance(line, bytes):
            line = line.decode("utf-8", errors="strict")
        if not line:
            if fields:
                yield "\n".join(fields)
                fields = []
        elif line.startswith("data:"):
            fields.append(line[5:].removeprefix(" "))
    if fields:
        yield "\n".join(fields)


def _iter_stream_lines(response):
    finished = False
    try:
        for raw_data in _sse_data(response):
            if raw_data == "[DONE]":
                if not finished:
                    raise UpstreamServiceError("OpenRouter stream ended without successful finish")
                yield json.dumps({"done": True}) + "\n"
                return
            try:
                event = json.loads(raw_data)
                if not isinstance(event, dict) or "error" in event:
                    raise ValueError
                choices = event.get("choices")
                if not isinstance(choices, list):
                    raise ValueError
                if not choices:  # usage-only frame
                    continue
                choice = choices[0]
                reason = choice.get("finish_reason")
                if reason is not None:
                    if reason not in ("stop", "length"):
                        raise ValueError
                    finished = True
                content = choice.get("delta", {}).get("content")
                if content is not None and not isinstance(content, str):
                    raise ValueError
            except (ValueError, KeyError, IndexError, TypeError, AttributeError):
                raise UpstreamServiceError("OpenRouter stream response invalid or failed") from None
            if content:
                yield json.dumps({"response": content, "done": False}) + "\n"
        # Clean EOF without [DONE] is incomplete; gateway records this separately.
    except requests.exceptions.RequestException:
        raise UpstreamServiceError("OpenRouter stream connection interrupted") from None
    except UnicodeError:
        raise UpstreamServiceError("OpenRouter stream response invalid") from None
    finally:
        response.close()
