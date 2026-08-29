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

## Wiki job transport contract

The `/obsidian` API is limited to authenticated **auth, queue, job, result,
error, and notification transport**. The gateway persists job envelopes and
moves them through lifecycle states; it does not interpret instructions,
inspect files or vaults, execute wiki commands, perform LLM work, or deliver
notifications itself.

### Compatibility decision

`draft` remains accepted. It is part of the current command allowlist, so
removing it would reject requests that the gateway currently accepts. The
gateway assigns no special payload schema or processing behavior to it; its
payload remains an opaque object, like the other commands. New `capture` jobs
remain rejected. Rows containing the historical `capture` command can still be
claimed, completed, and read because persisted job commands are not revalidated
on those paths. This is historical-data compatibility, not a supported capture
workflow.

New jobs accept `ask`, `draft`, `ingest`, `lint`, `refactor`, `save`, `status`,
and `update`. Payloads are JSON objects and are serialized for persistence,
then returned as the same JSON value; the gateway does not validate or rewrite
worker-owned payload fields.

### Supported shared payloads

| Command | Supported payload sent by clients | Gateway behavior |
| --- | --- | --- |
| `update` | `{"instruction":"..."}` | Stores and forwards the object unchanged. |
| `save` | `{"source_job_id":"..."}` | Stores and forwards the object unchanged; it does not validate the referenced job. |
| `lint` | `{}` or `{"instruction":"..."}` | Stores and forwards either object unchanged. |
| `refactor` | `{"mode":"preview","instruction":"..."}` | Stores and forwards the object unchanged; it does not enforce mode or instruction semantics. |

All other allowed commands also carry opaque JSON-object payloads. The table
records the shared transport shapes for the implemented wiki operations; it
does not make the gateway the owner of their semantics.

### Authentication and lifecycle endpoints

| Endpoint | Credential | Transport behavior |
| --- | --- | --- |
| `POST /obsidian/jobs` | `OBSIDIAN_TELEGRAM_INTERNAL_TOKEN` | Validates the command allowlist, stores the envelope, and returns its ID and `queued` status. |
| `GET /obsidian/jobs/next` | `OBSIDIAN_WORKER_TOKEN` | Atomically claims the oldest queued job and returns it with `running` status, or returns an empty response. |
| `POST /obsidian/jobs/{job_id}/result` | `OBSIDIAN_WORKER_TOKEN` | Finalizes a running job as `succeeded` or `failed` and stores result/error text. |
| `GET /obsidian/worker/jobs/{job_id}` | `OBSIDIAN_WORKER_TOKEN` | Returns a job, including its original payload and result/error fields; this lets a worker resolve a save job's `source_job_id`. |
| `GET /obsidian/jobs/{job_id}` | `OBSIDIAN_TELEGRAM_INTERNAL_TOKEN` | Returns the complete persisted job envelope. |
| `GET /obsidian/jobs/{job_id}/result` | `OBSIDIAN_TELEGRAM_INTERNAL_TOKEN` | Returns command, status, result/error text, and completion time. |
| `GET /obsidian/jobs/notifications/next` | `OBSIDIAN_TELEGRAM_INTERNAL_TOKEN` | Leases the oldest completed, unnotified job that has a chat ID. |
| `POST /obsidian/jobs/{job_id}/notified` | `OBSIDIAN_TELEGRAM_INTERNAL_TOKEN` | Idempotently records notification acknowledgement for a deliverable completed job. |
| `GET /obsidian/status` | `OBSIDIAN_TELEGRAM_INTERNAL_TOKEN` | Returns queue counts, the latest completed-job summary, and retention cleanup counts. |

Notification polling returns `{ "job": null, "status": "empty" }` when no job
is deliverable. Jobs without `telegram_chat_id` remain retrievable but are not
returned for notification. A notification lease prevents overlapping pollers
from receiving the same job; after the lease expires, an unacknowledged job is
eligible again. Acknowledgement requires a completed job with a chat ID.

### Result retention

Configure temporary result/error retention and notification leases with:

```env
OBSIDIAN_JOB_RESULT_RETENTION_HOURS=24
OBSIDIAN_JOB_ERROR_RETENTION_HOURS=72
OBSIDIAN_JOB_MAX_RESULT_CHARS=20000
OBSIDIAN_JOB_MAX_ERROR_CHARS=4000
OBSIDIAN_JOB_NOTIFICATION_LEASE_SECONDS=300
```

Successful result text and failed error text are cleared after their respective
retention windows when cleanup runs. Oversized text is truncated at write time
with an ai-gateway marker. Cleanup does not delete job metadata or the original
command payload. Consequently, a notification can still identify a completed
job after its result/error text has expired. The default notification lease is
300 seconds.
