# Config Reference — `config.yaml` Endpoint Fields

Each endpoint under `elyos_api.endpoints` has 10 resilience fields.
They fall into three groups: pacing, concurrency, and retry.

---

## Pacing (proactive rate-limit avoidance)

These three fields define the client-side sliding window that mirrors the
server's rate limit. The goal is to voluntarily pace requests so the server
rarely needs to throttle us.

| Field | Type | Example | Purpose |
|-------|------|---------|---------|
| `max_requests_per_window` | int | `5` | How many calls the server allows per window. Discovered empirically — the 6th call within ~30s gets throttled. |
| `window_s` | number | `30` | The server's rate-limit sliding window in seconds. Also discovered empirically from probe `retry_after_seconds` values. |
| `rate_limit_safety_s` | number | `2` | Added to `window_s` on the client side (effective window = 32s). Without it, 5 timestamps expire at exactly T=30 and we immediately fire 5 more, but the server's clock might disagree by 1-2 seconds, causing throttling. |

**How they work together:** The proactive pacer in `agent._wait_for_budget()`
tracks timestamps of recent calls in a per-group deque. When
`len(deque) >= max_requests_per_window`, it sleeps until the oldest timestamp
is older than `window_s + rate_limit_safety_s`. This keeps us just under the
server's limit without wasting calls on throttle responses.

---

## Concurrency

| Field | Type | Example | Purpose |
|-------|------|---------|---------|
| `max_concurrent` | int | `4` (weather), `1` (research) | Max simultaneous in-flight HTTP calls, enforced by an `asyncio.Semaphore`. |
| `rate_limit_group` | string | `"elyos_api"` | Groups endpoints that share a server-side rate budget. Both weather and research use the same group, confirmed by a controlled probe (`shared_rate_limit_bucket_report.html`). |

**Why weather is 4, not 5:** Setting concurrency one below the budget
(`4 < 5`) prevents all budget slots from being consumed in a single burst.
With 4 concurrent, there is always headroom for smoother pacing across
the window.

**Why research is 1:** Research calls are slow (3-8s) and share the same
rate budget. Parallel research calls would tie up budget slots for seconds
each, starving weather calls and exhausting the shared budget quickly.

---

## Retry (reactive recovery)

These fields control what happens when a request fails despite proactive
pacing. There are two failure modes: server throttle and network timeout.

| Field | Type | Example | Purpose |
|-------|------|---------|---------|
| `max_throttle_retries` | int | `5` | How many times to retry after a server throttle response (`{"status": "throttled"}`). 5 is generous — in practice, proactive pacing means we rarely see more than 1-2 throttles per request. |
| `max_timeout_retries` | int | `1` | How many times to retry after an `httpx.TimeoutException`. Only 1 because timeouts usually mean the server is genuinely overloaded — aggressive retry would make it worse. |
| `retry_jitter_s` | number | `0.5` (weather), `1.0` (research) | Random delay (`uniform(0, jitter)`) added on top of the server's `retry_after_seconds` for throttle retries, or used alone for timeout retries. Prevents multiple retries from hitting the server at the same instant. Research gets a higher jitter because its calls are heavier. |

**Throttle retry wait formula:** `retry_after_seconds + 1 + uniform(0, jitter)`

The `retry_after_seconds` value comes from the server and ranges from ~0
to ~30 seconds depending on how far into the server's rate window the
request landed. Thanks to proactive pacing, throttles that do occur are
typically near the window boundary, so `retry_after_seconds` is usually
only 1-3 seconds.

---

## Other endpoint fields

| Field | Type | Example | Purpose |
|-------|------|---------|---------|
| `path` | string | `"/weather"` | URL path appended to `base_url`. |
| `timeout_s` | number | `15` (weather), `20` (research) | HTTP response timeout. Weather is fast (~200ms) so 15s is generous. Research is slow (3-8s) so 20s gives it room. |

---

## Session (`cli_chat`)

| Field | Type | Default | Purpose |
|-------|------|---------|---------|
| `max_history_messages` | int | `0` (no limit) | Maximum number of messages in the conversation history sent to the LLM. When exceeded, the oldest complete turns are trimmed while preserving the system prompt and the current user message. Trimming happens at user-message boundaries to avoid orphaning tool-call/tool-result pairs. |
