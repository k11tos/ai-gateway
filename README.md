# AI Gateway

## Install

Runtime dependencies are intentionally minimized in `requirements.txt`.

```bash
pip install -r requirements.txt
```


## API

- `GET /health/live`: 프로세스 liveness 전용 체크 (`200` 고정)
- `GET /health/ready`: Ollama upstream readiness 체크, upstream 장애 시 `503` 반환
- `GET /health`: 기존 호환용 endpoint로 `GET /health/ready`와 동일 동작
- `POST /chat`: 기본 텍스트 생성 엔드포인트
- `POST /generate`: `POST /chat`와 동일 동작(하위 호환용, deprecated)
- `GET /presets`: preset catalog endpoint for clients that want to discover supported preset metadata
- `GET /providers`: provider discovery endpoint (`supported_providers`, `default_provider`)
- `GET /metrics`: in-memory request counters for lightweight operational visibility
- `GET /version`: build/version metadata summary
- `GET /models`: model discovery endpoint
- `POST /generate_stream`: streaming generation endpoint
- `POST /embedding`: embedding endpoint

신규 클라이언트는 `POST /chat` 사용을 권장합니다.

### `GET /metrics` semantics

The `/metrics` payload remains a simple in-memory counter snapshot:

- `requests_total`: total counted API requests across instrumented endpoints.
- `chat_requests`: non-stream text generation requests (`POST /chat` and `POST /generate`).
- `generate_requests`: requests that specifically hit the deprecated `POST /generate` endpoint.
- `stream_requests`: streaming text generation requests (`POST /generate_stream`).
- `embedding_requests`: embedding requests (`POST /embedding`).
- `errors_total`: counted request failures across instrumented endpoints.

Notes:

- `chat_requests` keeps its legacy aggregate behavior for backward compatibility.
- `generate_requests` is additive and exists to disambiguate deprecated `/generate` traffic from `/chat`.

### Provider behavior (current)

- Current support: the gateway currently supports only `ollama`.
- Request field relationship: the `provider` field in `POST /chat`, `POST /generate`, and `POST /generate_stream` is validated against supported providers. If omitted, the gateway uses the `default_provider` (`ollama`).
- Unsupported handling: if `provider` is present but not supported, the request is rejected with `400 Bad Request` and an error message listing supported providers.
- Practical guidance: clients should treat `provider` as a validated selector (not a free-form hint) and can call `GET /providers` to discover the current supported/default values.

### `GET /presets` contract

`GET /presets` exposes the preset catalog derived from `PRESET_DEFINITIONS`. Use it when a client needs to list available presets and attach preset metadata to UI or request-building flows.

Preset application contract for chat/generate requests:

- Clients should send the original raw `prompt` plus optional `preset` name as structured request fields.
- The gateway owns preset shaping and prepends the preset's `prompt_prefix` before calling upstream generation APIs.
- Clients should **not** pre-apply preset prefixes themselves.

Response shape:

```json
{
  "presets": [
    {
      "name": "string",
      "description": "string",
      "prompt_prefix": "string"
    }
  ]
}
```

Field meanings:

- `name`: stable preset identifier for display and selection.
- `description`: short human-readable summary of the preset's intended behavior.
- `prompt_prefix`: text prepended by the gateway when that preset is applied.

Stability expectations:

- Downstream clients may treat the `/presets` response shape as a stable contract.
- The top-level `presets` array and each preset object's `name`, `description`, and `prompt_prefix` fields should be preserved for compatibility.
- The top-level `presets` array order is also intended to remain stable, and clients may depend on the server-defined preset ordering.
- Additive changes should be preferred over renaming, reordering, or removing these fields.


> Note: server health monitoring, diagnostics collection, LLM triage, and Telegram alerting are now owned by `home_service`.


## Tests

Run the full test suite with:

```bash
pytest
```

## Model aliases

You can request friendly model aliases in `POST /chat`, `POST /generate`, and `POST /generate_stream`.

Configure aliases with either dedicated environment variables:

- `MODEL_ALIAS_FAST`
- `MODEL_ALIAS_SMART`
- `MODEL_ALIAS_CODING`

Or provide a comma-separated mapping with `MODEL_ALIASES`, for example:

```bash
MODEL_ALIASES="fast=llama3.2:3b,smart=llama3.1:8b,coding=qwen2.5-coder:7b"
```

Resolution rules:

1. The requested model is looked up in the alias table.
2. If an alias exists, the mapped model is sent to Ollama.
3. If no alias exists, the requested model is used unchanged.
4. If no model is requested, `DEFAULT_MODEL` is used.

Response behavior for `POST /chat` and `POST /generate`:
- `model` always returns the client-requested model name (or `DEFAULT_MODEL` when omitted).
- `resolved_model` is included only when alias resolution changed the upstream target model.

If both `MODEL_ALIAS_*` and `MODEL_ALIASES` define the same alias key, `MODEL_ALIASES` wins for that key.

## Obsidian job result retention

The Obsidian endpoints are a job queue and result transport layer only. LLM-backed `ingest`, `ask`, and `draft` work and Obsidian vault access are performed by the external `obsidian-mobile-worker`; the gateway stores command metadata, payloads, status, final result/error text, and timestamps.

Configure temporary payload retention with:

```env
OBSIDIAN_JOB_RESULT_RETENTION_HOURS=24
OBSIDIAN_JOB_ERROR_RETENTION_HOURS=72
OBSIDIAN_JOB_MAX_RESULT_CHARS=20000
OBSIDIAN_JOB_MAX_ERROR_CHARS=4000
```

Obsidian job results may contain LLM-generated summaries derived from private notes. ai-gateway stores final results temporarily and clears old payloads according to retention settings. Oversized worker result and error text is truncated at write time with an ai-gateway truncation marker.
