# Config Reference — `config.yaml`

## API-level rate limit (`elyos_api.rate_limit`)

One shared budget for the whole Elyos API — both weather and research
draw from the same pool (confirmed by controlled probe).

| Field | Type | Example | Purpose |
|-------|------|---------|---------|
| `max_requests_per_window` | int | `5` | How many calls the server allows per window. The 6th call within ~30s gets throttled. |
| `window_s` | number | `30` | The server's rate-limit sliding window in seconds. |
| `max_throttle_retries` | int | `2` | How many times to retry after a server throttle response (`{"status": "throttled"}`). |

**How they work together:** The proactive pacer in `tools.pacing.wait_for_budget()`
tracks timestamps of recent calls in a deque. When
`len(deque) >= max_requests_per_window`, it sleeps until the oldest timestamp
is older than `window_s`. On throttle, the client sleeps
`retry_after_seconds + 1` (no jitter — single-user CLI).

---

## Per-endpoint config (`elyos_api.endpoints.<name>`)

| Field | Type | Example | Purpose |
|-------|------|---------|---------|
| `path` | string | `"/weather"` | URL path appended to `base_url`. |
| `timeout_s` | number | `15` (weather), `20` (research) | HTTP response timeout. |
| `max_concurrent` | int | `4` (weather), `1` (research) | Max simultaneous in-flight HTTP calls, enforced by an `asyncio.Semaphore`. |
| `max_timeout_retries` | int | `0` (default), `1` (research) | How many times to retry after a timeout. Optional — defaults to 0 if absent. |

---

## Session (`cli_chat`)

| Field | Type | Default | Purpose |
|-------|------|---------|---------|
| `max_history_messages` | int | `0` (no limit) | Maximum number of messages in the conversation history sent to the LLM. When exceeded, the oldest complete turns are trimmed while preserving the system prompt and the current user message. Trimming happens at user-message boundaries to avoid orphaning tool-call/tool-result pairs. |
