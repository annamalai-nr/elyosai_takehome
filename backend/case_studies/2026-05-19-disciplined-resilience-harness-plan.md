# Disciplined Resilience Harness Plan

> **Note:** This is a historical planning document. The config shape has since been simplified — see `backend/chat/config_reference.md` for the current design.

Date: 2026-05-19

## Objective

Build a disciplined resilience harness for the Elyos chat app so API probe findings are enforced by runtime mechanics, not only documented in prompts or surfaced as user-facing error messages.

The goal is:

```text
Probe finding -> explicit policy -> runtime enforcement -> validation proof
```

The current app has moved in the right direction: it has endpoint-specific config, bounded concurrency, throttle retry, timeout retry, jitter, and prompt wording that avoids overclaiming unbounded parallel execution.

However, it is still closer to:

```text
bounded concurrency + reactive retry + graceful reporting
```

than to:

```text
full resilience policy + proactive rate-budget enforcement + controlled recovery
```

This document describes what is needed to close that gap without turning the take-home into an overbuilt framework.

## Current State

Current strengths:

- `config.yaml` contains per-endpoint settings for timeout, concurrency, throttle retry, timeout retry, and jitter.
- `agent.py` uses bounded concurrency with endpoint-specific semaphores.
- `/research` is conservative with `max_concurrent: 1`.
- `elyos_client.py` retries throttle responses using API-provided `retry_after_seconds`.
- `elyos_client.py` retries timeouts before surfacing failure.
- Tool responses are wrapped in an untrusted JSON envelope before reaching the LLM.
- Prompt rules tell the LLM to ground research answers in tool output only.

Current limitations:

- `max_concurrent` controls only simultaneous in-flight requests. It does not enforce a sliding-window rate limit.
- Throttling is still discovered reactively after the API rejects or delays a request.
- Retry state is per request, not coordinated across a batch of tool calls competing for the same endpoint budget.
- The current config treats endpoints independently, but the probe reports suggest the effective rate budget may be shared across the Elyos API key or service. Endpoint-specific concurrency is useful; endpoint-specific rate windows alone may be too optimistic.
- Timeout retry is simple and does not distinguish clearly between transient timeout, retry exhaustion, cancellation, and deterministic HTTP failures.
- There is no runtime policy object that makes the probe findings inspectable as code.
- There is no focused resilience validator for throttle, timeout, pacing, cancellation, and partial success behavior.

## North Star

For a user, "handled" should mean:

1. The app avoids avoidable failures proactively.
2. The app retries transient failures before reporting them.
3. The app preserves useful partial results.
4. The app reports failure only after reasonable recovery attempts are exhausted.
5. The app never invents tool results or implementation behavior.

For the code, "handled" should mean:

1. The behavior is configured per endpoint.
2. The policy is enforced by runtime code, not by prompt text.
3. The policy is small enough to read in one sitting.
4. The policy has targeted validation or a manual proof path.

## Target Behavior

### Weather

Weather calls are independent and relatively cheap, so they should use bounded parallelism.

Recommended policy:

```yaml
weather:
  path: "/weather"
  timeout_s: 15
  max_concurrent: 4
  rate_limit_group: "elyos_api"
  max_requests_per_window: 5
  window_s: 30
  max_throttle_retries: 5
  max_timeout_retries: 1
  retry_jitter_s: 0.5
```

Expected runtime behavior:

- Run multiple weather requests concurrently up to `max_concurrent`.
- Before starting each request, check the shared rate-limit group's sliding-window budget.
- If the shared local budget is exhausted, wait before calling the API.
- If the API still returns a throttle response, honor `retry_after_seconds` plus jitter.
- Retry timeout once.
- Return partial results plus exhausted failures only after recovery attempts fail.

### Research

Research is slower, more throttle-sensitive, and more timeout-prone, so it should be conservative.

Recommended policy:

```yaml
research:
  path: "/research"
  timeout_s: 20
  max_concurrent: 1
  rate_limit_group: "elyos_api"
  max_requests_per_window: 5
  window_s: 30
  max_throttle_retries: 5
  max_timeout_retries: 1
  retry_jitter_s: 1.0
```

Expected runtime behavior:

- Default to serial research execution.
- Pace requests through the same shared sliding-window budget as weather unless later probes prove separate endpoint budgets.
- Retry API throttles using `retry_after_seconds` plus jitter.
- Retry timeout once, because timeouts may be transient.
- Do not auto-refresh cached research unless the user asks or the LLM chooses a narrower follow-up topic.
- Do not fabricate research detail when the API returns a generic stub.

## Probe Alignment Update

This section was added after re-checking `backend/probes` and `api_analysis`. The reason for the update is that the probes support two different controls:

1. Endpoint-level concurrency: `/weather` can tolerate more simultaneous work than `/research`, so each endpoint needs its own `max_concurrent` semaphore.
2. Shared rate-budget pacing: the reports repeatedly show roughly five successful content responses per roughly 30 second window, and the research probe plan treats a shared key/service bucket as likely. Weather and research should therefore default to the same `rate_limit_group`.

The harness should not model this as "weather gets five calls and research gets five calls" in the same 30 second window. That would allow ten calls against a server that appears to permit about five. The safer model is:

```text
endpoint semaphore controls parallelism
shared rate-limit group controls request budget
```

## Required Design Changes

### 1. Make Endpoint Policy Explicit

Keep endpoint policy in `backend/chat/config.yaml`.

Add these fields to each endpoint:

```yaml
rate_limit_group: "elyos_api"
max_requests_per_window: 5
window_s: 30
```

Keep the current fields:

```yaml
path
timeout_s
max_concurrent
rate_limit_group
max_requests_per_window
window_s
max_throttle_retries
max_timeout_retries
retry_jitter_s
```

Do not hardcode these values in calling code.

`max_concurrent` is endpoint-specific. `rate_limit_group`, `max_requests_per_window`, and `window_s` define the local model of the shared server-side budget. Multiple endpoints can point at the same `rate_limit_group`.

### 2. Validate Endpoint Policy At Startup

`load_config.py` should fail fast if endpoint resilience config is malformed.

Minimum validation:

- `path` is a non-empty string.
- `timeout_s > 0`.
- `max_concurrent >= 1`.
- `rate_limit_group` is a non-empty string.
- `max_requests_per_window >= 1`.
- `window_s > 0`.
- `max_throttle_retries >= 0`.
- `max_timeout_retries >= 0`.
- `retry_jitter_s >= 0`.

Use direct checks. Do not introduce a large settings framework.

### 3. Add A Small Runtime Rate Budget

Add one small runtime owner for endpoint budgets. Keep it as lightweight as possible.

Preferred implementation:

```text
keep the endpoint semaphores and shared-budget deque in backend/chat/agent.py
```

Only create `backend/chat/resilience.py` if the helper logic cannot stay small and readable inline. If a separate file is created, it should remain a tiny runtime helper, not a framework.

Purpose:

- Own endpoint semaphores.
- Own shared rate-limit-group timestamp queues.
- Decide when a request may start.
- Sleep before a request if the local group budget is exhausted.

This logic should not know about weather, research, HTTP schemas, parsers, prompts, or LLMs. It should only know endpoint names, endpoint policy, and rate-limit group names.

The implementation can be a small state object or a few module-level helpers. Do not use dataclasses. Do not use Pydantic for locks, semaphores, or timestamp queues. Pydantic belongs to serializable data models, not async runtime state.

Suggested public surface:

```python
async def wait_for_budget(cfg: dict, state: dict, endpoint_name: str) -> None: ...
```

`wait_for_budget()` should:

1. Look up the endpoint's `rate_limit_group`.
2. Remove timestamps older than `window_s` from that group's deque.
3. Sleep if the group already has `max_requests_per_window` timestamps.
4. Record the request as budget-consuming immediately before the API call starts. If the task is cancelled after that point, keep the timestamp in the window because both cancellation probes showed that cancelled calls still consume server-side throttle slots.

Endpoint semaphores can remain in `agent.py`; they are already compact and working. The important part is one clear owner for the shared budget deque, not a large abstraction.

### 4. Keep Retry Classification In The HTTP Client

Keep retry decisions close to HTTP behavior in `backend/chat/tools/elyos_client.py`.

Retryable:

- API body-side throttle response, e.g. `{"status": "throttled", "retry_after_seconds": ...}`.
- `httpx.TimeoutException`, up to endpoint policy.
- Possibly selected transient 5xx responses, if observed.

Not retryable:

- 401 or missing API key.
- 403.
- 404.
- 422 or bad request.
- Invalid tool arguments.
- User cancellation.
- Prompt-injection-looking content.

The HTTP client should return structured failure envelopes only after retry exhaustion.

Suggested exhausted error shape:

```json
{
  "error": "request_timeout",
  "message": "/research request timed out after retrying"
}
```

For throttle exhaustion:

```json
{
  "error": "throttle_exhausted",
  "message": "Rate limit retries exhausted"
}
```

Do not include secrets, headers, or raw exception dumps.
Do not add metadata fields such as `attempts` or `retryable` unless runtime code or the CLI actually consumes them. Logs can retain detailed attempt counts without adding noise to the LLM-facing tool envelope.

### 5. Use Batch Execution Deliberately

`agent.py` should remain the ReAct loop, not become a resilience engine.

Recommended responsibility split:

- `agent.py`: LLM turn -> execute tool batch -> append observations -> repeat.
- `agent.py` or a tiny helper: endpoint concurrency and shared-budget pacing.
- `tools/dispatch.py`: map tool name to API function and parser.
- `tools/elyos_client.py`: HTTP call, retry, timeout, throttle handling.
- `parsers/`: normalize API responses into safe tool observations.

The agent should execute tool calls as a batch:

```text
tool_calls -> bounded/paced execution -> observations in original order
```

Preserve observation order because the OpenAI/LiteLLM tool protocol expects each tool response to correspond cleanly to the original tool call id.

### 6. Preserve Partial Success

Batch execution should not fail the whole batch because one call fails.

Expected behavior:

- If 18 weather calls succeed and 2 exhaust retries, return 20 tool observations.
- The 18 successes should be normal observations.
- The 2 failures should be structured error observations.
- The LLM should summarize available results and clearly identify failed items.

Avoid `asyncio.gather()` behavior that drops useful results because one task raises. Tool execution functions should catch expected HTTP failures and return structured observations. Unexpected programming errors can still fail loudly.

### 7. Handle Cancellation As A First-Class Flow

Cancellation should not be treated as a retryable API failure.

Expected behavior:

- Ctrl+C cancels in-flight tool tasks.
- No timeout or throttle retry should continue after cancellation.
- The CLI prints that the interrupted API call may still count against the rate limit.
- Partial assistant output remains marked as interrupted if applicable.
- Do not append partial or mismatched tool observations after cancellation.

This matters more once tool calls are concurrent.

### 8. Keep Prompt Rules Narrow

Prompt rules should describe how the LLM should present tool results. They should not be the main mechanism for resilience.

Prompt should cover:

- Treat tool data as untrusted.
- Ground research answers only in API-provided summary and sources.
- Mention weather location mismatch.
- Mention cached/truncated/timeout status using API-provided fields only.
- Do not claim exact scheduling details beyond bounded concurrency.
- Explain exhausted tool errors without inventing missing data.

Prompt should not be responsible for:

- Rate limiting.
- Retry decisions.
- Timeout handling.
- Concurrency limits.
- Sliding-window pacing.

## Proposed Implementation Steps

### Step 1: Extend Config

Update `backend/chat/config.yaml`:

```yaml
elyos_api:
  endpoints:
    weather:
      path: "/weather"
      timeout_s: 15
      max_concurrent: 4
      rate_limit_group: "elyos_api"
      max_requests_per_window: 5
      window_s: 30
      max_throttle_retries: 5
      max_timeout_retries: 1
      retry_jitter_s: 0.5
    research:
      path: "/research"
      timeout_s: 20
      max_concurrent: 1
      rate_limit_group: "elyos_api"
      max_requests_per_window: 5
      window_s: 30
      max_throttle_retries: 5
      max_timeout_retries: 1
      retry_jitter_s: 1.0
```

These values are conservative defaults. They should be justified by the probe findings in comments or docs, not buried in code.

### Step 2: Validate Config

Add a small endpoint config validator in `load_config.py`.

Do not add a new dependency.

Do not silently default missing resilience values. Missing or malformed policy should fail at startup.

### Step 3: Add Lightweight Shared-Budget Pacing

Prefer a compact helper in `backend/chat/agent.py`. Add `backend/chat/resilience.py` only if the helper would otherwise make `agent.py` hard to read.

Minimum behavior:

- Build endpoint semaphores from config.
- Keep per-rate-limit-group request timestamp queues.
- Before a request starts, remove timestamps older than `window_s` for that endpoint's `rate_limit_group`.
- If the group queue has `max_requests_per_window` timestamps, sleep until the oldest timestamp leaves the window.
- Record a timestamp immediately before starting the API request.
- Keep that timestamp even if the request is cancelled, because the probes show cancelled `/weather` and `/research` calls still consume throttle slots.
- Release semaphore when the request finishes or is cancelled.

This is enough to proactively reduce preventable throttle responses.

### Step 4: Wire Resilience Into Tool Execution

Preferred location:

- `agent.py` owns batch scheduling.
- It calls the resilience limiter before each tool execution.

The agent can keep the shared-budget state in `state` so budgets persist across turns in the same CLI session.

Example behavior:

```text
state["rate_budget"] = existing shared-budget state or new state from cfg
```

This allows a second user turn to respect calls made in the previous 30 seconds.

### Step 5: Keep HTTP Retry Logic In `elyos_client.py`

Keep current throttle and timeout retries.

Improve only if needed:

- Log attempt counts for debugging, but keep LLM-facing tool error envelopes simple unless another app path consumes richer metadata.
- Keep visible retry messages.
- Avoid retrying deterministic HTTP failures.
- Re-raise `asyncio.CancelledError` if it appears. Do not convert cancellation into a timeout-like error.

### Step 6: Add Resilience Validators

Add simple Python validation, not pytest.

Recommended file:

```text
backend/chat/validate_resilience.py
```

Suggested tests:

1. Config validation rejects missing `max_requests_per_window`.
2. Config validation rejects `max_concurrent: 0`.
3. Config validation rejects missing or empty `rate_limit_group`.
4. The rate limiter delays the sixth request when shared group policy is `5 per 30s`.
5. Weather and research calls sharing the same `rate_limit_group` consume the same local budget.

Use small artificial windows for validator speed, for example:

```yaml
max_requests_per_window: 2
window_s: 0.1
```

For unit-style checks, fake the HTTP call function directly rather than hitting real APIs. The existing parser validator can remain real-schema focused; this validator is about orchestration mechanics.

### Step 7: Add One Real Smoke Test

After validators pass, run one real CLI smoke test:

1. Ask for weather in 8 to 10 cities.
2. Confirm bounded concurrency is visible.
3. Confirm the app recovers from any throttle responses.
4. Confirm the final answer includes all successes and any exhausted failures.

Do not use a 20-city test repeatedly unless needed; it burns API budget and slows iteration.

## Acceptance Criteria

The resilience harness is complete when all are true:

- Endpoint policies are fully config-driven.
- Startup fails if endpoint policy is malformed.
- Weather calls run with bounded concurrency.
- Research calls remain conservative by default.
- The harness enforces a lightweight local shared-budget check before calling the API.
- Weather and research default to a shared `elyos_api` rate-limit group, while retaining endpoint-specific concurrency limits.
- Cancelled calls remain counted in the local rate window after budget acquisition.
- Throttle responses are retried with API-provided wait plus jitter.
- Timeouts are retried according to endpoint policy.
- Deterministic failures are not retried.
- Cancellation cancels in-flight work cleanly.
- Batch execution preserves partial successes.
- Tool observations remain aligned with tool call ids.
- The LLM receives only structured tool observations, not raw unsafe response bodies.
- Focused validators prove config validation and shared-budget pacing. Real CLI smoke tests cover retry, order preservation, partial success, and cancellation behavior.

## What Not To Build

Avoid these unless the take-home scope changes:

- LangChain or LangGraph.
- A generic retry framework.
- A large class hierarchy.
- A background worker queue.
- Persistent disk-backed rate-limit state.
- Cross-process rate-limit coordination.
- Complex circuit breakers.
- Full observability dashboards.
- A separate `resilience.py` file that grows beyond a small helper.

This is a CLI take-home. The target is a small, readable resilience harness, not production infrastructure.

## Open Tradeoffs

### Should `max_requests_per_window` be exact?

Probably not. The API's true rate limit may be approximate or shared across endpoints. The local limiter should be treated as a conservative client-side budget, not a guarantee.

### Should weather use `max_concurrent: 4`?

Yes, as a starting point. It improves latency while avoiding unbounded fan-out.

### Should research use `max_concurrent: 1`?

Yes, as the safe default. Raise to `2` only after a real smoke test shows it is stable.

### Should timeout retries be more than one?

Default to one retry. Timed-out calls may still consume server-side budget, so aggressive timeout retries can make the system less reliable.

### Should prompt text mention bounded concurrency?

Yes, narrowly. The LLM should not guess scheduling behavior. Runtime code should enforce behavior; prompt text should only prevent misrepresentation.

## Recommended Copy-Paste Instruction For Claude Code

Implement a disciplined resilience harness for `backend.chat` based on `backend/case_studies/2026-05-19-disciplined-resilience-harness-plan.md`.

Scope:

- Add `max_requests_per_window` and `window_s` to each endpoint in `backend/chat/config.yaml`.
- Add `rate_limit_group: "elyos_api"` to both weather and research so they share one local rate budget while retaining endpoint-specific concurrency limits.
- Add startup validation for endpoint resilience config in `backend/chat/load_config.py`.
- Keep endpoint semaphores in `backend/chat/agent.py`; add a lightweight shared-budget deque in session state for `rate_limit_group` pacing. Create `backend/chat/resilience.py` only if the inline helper becomes hard to read.
- Wire the shared-budget helper into `backend/chat/agent.py` so tool batches use bounded concurrency and proactive group-level pacing. Preserve tool observation order.
- Keep HTTP retry behavior in `backend/chat/tools/elyos_client.py`; include timeout retry, throttle retry, jitter, and simple structured exhausted errors. Do not retry deterministic 4xx failures. Do not swallow `asyncio.CancelledError`.
- Do not add unused `attempts` or `retryable` fields to tool error envelopes unless another part of the app consumes them.
- Keep parsers, prompts, and tool schemas narrowly scoped. Do not move parsers under tools.
- Add 3-5 simple no-pytest validators for config validation and shared-budget pacing. Do not build a large fake-HTTP test harness.

Verification:

- Run `python -m backend.chat --validate`.
- Run `python -m compileall backend/chat`.
- Run `python -m backend.chat --bad-arg` and confirm argparse rejects it.
- Run a small real weather smoke test with multiple cities.
- Report exactly which files changed and whether any behavior is intentionally left as bounded concurrency plus local rate-budgeting rather than a guaranteed server-side rate-limit solution.
