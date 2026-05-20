# Config Reference — `config.yaml`

## API-level settings (`elyos_api`)

| Field | Type | Example | Purpose |
|-------|------|---------|---------|
| `base_url` | string | `"https://..."` | Elyos API base URL. |
| `api_key_env` | string | `"ELYOS_API_KEY"` | Name of the env var holding the API key. |
| `max_throttle_retries` | int | `2` | How many times to retry after a server throttle response (`{"status": "throttled"}`). |

**How throttle retry works:** When the server returns a throttle response,
`elyos_client.py` reads the authoritative `retry_after_seconds` from the
response body, sleeps `retry_after + 1` s, and retries up to
`max_throttle_retries` times. There is no client-side proactive pacing —
the server's `retry_after_seconds` is the sole backoff signal.

**Bounded concurrency:** Per-endpoint `max_concurrent` semaphores in
`agent.py` limit how many HTTP calls can be in-flight simultaneously.
This is the only client-side rate protection beyond reactive throttle retry.

---

## Per-endpoint config (`elyos_api.endpoints.<name>`)

| Field | Type | Example | Purpose |
|-------|------|---------|---------|
| `path` | string | `"/weather"` | URL path appended to `base_url`. |
| `timeout_s` | number | `15` (weather), `20` (research) | HTTP response timeout. |
| `max_concurrent` | int | `1` (weather), `1` (research) | Max simultaneous in-flight HTTP calls, enforced by an `asyncio.Semaphore`. Both endpoints are currently serialized; cross-endpoint calls may still overlap. |
| `max_timeout_retries` | int | `0` (default), `1` (research) | How many times to retry after a timeout. Optional — defaults to 0 if absent. |

---

## Session (`cli_chat`)

| Field | Type | Default | Purpose |
|-------|------|---------|---------|
| `max_history_messages` | int | `0` (no limit) | Maximum number of messages in the conversation history sent to the LLM. When exceeded, the oldest complete turns are trimmed while preserving the system prompt and the current user message. Trimming happens at user-message boundaries to avoid orphaning tool-call/tool-result pairs. |
