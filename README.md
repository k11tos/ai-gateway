# AI Gateway

## Role

ai-gateway has two separate responsibilities:

1. **AI assistant API**: the existing chat, generation, streaming, embedding, preset, provider, model, metrics, version, and health endpoints remain supported for non-wiki assistant clients. These features call the configured upstream AI provider as documented below and are independent of the Obsidian wiki workflow.
2. **Obsidian wiki job transport**: the `/obsidian/jobs` endpoints are the queue, result, and notification state transport for wiki jobs shared by `telegram-ai-bot` and `obsidian-mobile-worker`. ai-gateway stores job metadata, payloads, queue state, worker result/error text, notification leases, and notification acknowledgements. It does **not** run wiki LLM logic, execute opencode, read the Obsidian vault, or perform vault-side file changes.

Final wiki direction:

- `telegram-ai-bot` submits wiki jobs to ai-gateway and later polls notification state to deliver completed results to Telegram chats.
- ai-gateway durably stores queued jobs, running/completed status, result/error payloads, and notification delivery state.
- The MacBook-side `obsidian-mobile-worker`, together with opencode, claims jobs from ai-gateway and performs all vault-side work against the local Obsidian vault.
- `/wiki capture` is removed from the workflow; wiki requests should use the remaining job commands supported by `telegram-ai-bot` and `obsidian-mobile-worker`.

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

## Obsidian wiki job transport

The Obsidian endpoints are a job queue, result, and notification state transport layer only. Wiki LLM reasoning, opencode execution, and Obsidian vault reads/writes happen outside ai-gateway on the MacBook-side `obsidian-mobile-worker`; the gateway stores command metadata, payloads, status, final result/error text, notification lease/acknowledgement state, and timestamps.

This is intentionally separate from the non-wiki AI assistant API described above. Assistant endpoints such as `POST /chat`, `POST /generate_stream`, and `POST /embedding` remain supported, but they are not part of the Obsidian wiki job execution path.

### Workflow boundaries

- **Telegram submitter**: `telegram-ai-bot` accepts `/wiki` requests and creates `/obsidian/jobs` records in ai-gateway. `/wiki capture` is no longer part of the supported workflow.
- **Transport store**: ai-gateway persists queue state (`queued`, `running`, `succeeded`, `failed`), job payloads, worker result/error text, notification leases, and `result_notified_at` acknowledgements.
- **Vault worker**: `obsidian-mobile-worker` runs on the MacBook, claims jobs from ai-gateway, invokes opencode for wiki work, reads/writes the local Obsidian vault as needed, and posts the final job result back to ai-gateway.
- **Telegram delivery**: `telegram-ai-bot` polls ai-gateway for completed unnotified jobs and sends result notifications to the original Telegram chat. ai-gateway does not send Telegram messages.

### Obsidian job result retention

Configure temporary payload retention with:

```env
OBSIDIAN_JOB_RESULT_RETENTION_HOURS=24
OBSIDIAN_JOB_ERROR_RETENTION_HOURS=72
OBSIDIAN_JOB_MAX_RESULT_CHARS=20000
OBSIDIAN_JOB_MAX_ERROR_CHARS=4000
OBSIDIAN_JOB_NOTIFICATION_LEASE_SECONDS=300
```

Obsidian job results may contain LLM-generated summaries derived from private notes. ai-gateway stores final results temporarily and clears old payloads according to retention settings. Oversized worker result and error text is truncated at write time with an ai-gateway truncation marker.

### Obsidian job notification delivery

`telegram-ai-bot` can durably poll completed worker jobs for automatic delivery back to the original Telegram chat. ai-gateway only tracks queue/result state; it does not send Telegram messages, read the Obsidian vault, or call an LLM.

Authenticated with `Authorization: Bearer <OBSIDIAN_TELEGRAM_INTERNAL_TOKEN>`:

- `GET /obsidian/jobs/notifications/next` atomically leases and returns the oldest completed (`succeeded` or `failed`) job whose `result_notified_at` is still `null`, whose `telegram_chat_id` is present, and whose notification lease is absent or expired. It returns `{ "job": null, "status": "empty" }` when there is nothing to deliver. Jobs without `telegram_chat_id` are still stored but are skipped by notification polling.
- `POST /obsidian/jobs/{job_id}/notified` idempotently sets `result_notified_at` after `telegram-ai-bot` sends or intentionally acknowledges the result. Worker credentials cannot use this endpoint, and queued/running jobs or completed jobs without `telegram_chat_id` return `409 Conflict` instead of being acknowledged.

`OBSIDIAN_JOB_NOTIFICATION_LEASE_SECONDS` controls how long a claimed notification remains hidden from other pollers before it can be returned again. The default is 300 seconds, so overlapping pollers do not receive the same job while crashed bots still recover pending deliveries after the lease expires.

If result retention has already cleared `result_text` or `error_text`, notification polling may still return the completed job so the bot can display a helpful expired-result message. Failed jobs are returned even when `error_text` is empty. Existing direct lookup endpoints such as `GET /obsidian/jobs/{job_id}` and `GET /obsidian/jobs/{job_id}/result` continue to support manual `/wiki result <job_id>` flows. `/wiki capture` should not be documented or reintroduced as a client workflow.
