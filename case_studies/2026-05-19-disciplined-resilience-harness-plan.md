# Disciplined Resilience Harness Plan

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

> [CC] Agreed. These are solid and were validated in the post-refactor audit. No changes needed here.

Current limitations:

- `max_concurrent` controls only simultaneous in-flight requests. It does not enforce a sliding-window rate limit.
- Throttling is still discovered reactively after the API rejects or delays a request.
- Retry state is per request, not coordinated across a batch of tool calls competing for the same endpoint budget.
- The current config treats endpoints independently, but the probe reports suggest the effective rate budget may be shared across the Elyos API key or service. Endpoint-specific concurrency is useful; endpoint-specific rate windows alone may be too optimistic.
- Timeout retry is simple and does not distinguish clearly between transient timeout, retry exhaustion, cancellation, and deterministic HTTP failures.
- There is no runtime policy object that makes the probe findings inspectable as code.
- There is no focused resilience validator for throttle, timeout, pacing, cancellation, and partial success behavior.

> [CC] The shared-budget observation is the strongest insight here. The reactive retry already works — the question is whether a proactive sliding window earns its complexity. See my comments on Section 3 below.

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

> [CC] Strong framing. Point 3 ("small enough to read in one sitting") is the constraint I want to hold the implementation to. The rest of the plan should be measured against this.

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

This section was added after re-checking `backend/probes` and `probe_reports`. The reason for the update is that the probes support two different controls:

1. Endpoint-level concurrency: `/weather` can tolerate more simultaneous work than `/research`, so each endpoint needs its own `max_concurrent` semaphore.
2. Shared rate-budget pacing: the reports repeatedly show roughly five successful content responses per roughly 30 second window, and the research probe plan treats a shared key/service bucket as likely. Weather and research should therefore default to the same `rate_limit_group`.

The harness should not model this as "weather gets five calls and research gets five calls" in the same 30 second window. That would allow ten calls against a server that appears to permit about five. The safer model is:

```text
endpoint semaphore controls parallelism
shared rate-limit group controls request budget
```

> [CC] The two-layer model (endpoint semaphore + shared budget) is conceptually correct. My concern is implementation weight. The "~5 per ~30s" numbers are approximate — the probes couldn't pin them down precisely. Building a sliding-window timestamp queue around approximate numbers risks false precision. The reactive `retry_after_seconds` from the server is the authoritative signal. A simpler alternative: keep the semaphores, add a lightweight shared counter that tracks recent calls, and let the reactive retry handle the actual pacing. This gets 80% of the benefit at 20% of the code.

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

> [CC] Agree with adding `rate_limit_group` to config — it documents the shared-budget assumption explicitly, which is good engineering. The three new fields are reasonable. No objection here.

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

> [CC] Fully agree. High value, low cost. A single loop over endpoints with direct `assert` or `ValueError` checks — maybe 15 lines. Should have been there from the start.

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

> [CC] This is the section I push back on most. The design is sound in isolation, but the implementation cost is significant for a CLI take-home:
>
> - A `ResiliencePolicy` class with async context managers, timestamp queues, locks, semaphores, and cancellation-aware bookkeeping is likely 60-80 lines on its own.
> - The semaphores already exist in `agent.py` in ~10 lines and work correctly.
> - The sliding-window timestamp queue enforces an approximate budget (~5 per ~30s) that the probes couldn't pin down. Meanwhile, the server's `retry_after_seconds` is the authoritative pacing signal and is already honored.
>
> **Counter-proposal:** Keep the semaphores in `agent.py`. Add a lightweight shared call counter (a `collections.deque` of timestamps, ~15 lines) directly in `agent.py` or as a tiny helper. If the counter shows the window is near capacity, insert a brief pre-request delay. This documents the shared-budget assumption in code without a separate file, class, or async context manager protocol. The reactive retry remains the real pacing mechanism.
>
> If Codex feels strongly about the separate file, I can implement it — but it should be held to under 40 lines, not 60-80. The north star says "small enough to read in one sitting."

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

> [CC] Good classification. This already matches what `elyos_client.py` does — non-200 returns immediately, throttle and timeout retry, `httpx.HTTPError` returns immediately. The retryable/not-retryable distinction is already implemented correctly.

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

> [CC] The `attempts` and `retryable` fields are dead weight. Nothing downstream reads them — the LLM receives the error through the envelope and only sees `error` + `message`. The CLI doesn't branch on `retryable`. Adding fields nobody consumes adds noise to the response dicts and to the envelope. I'd skip these unless we add a consumer first.

### 5. Use Batch Execution Deliberately

`agent.py` should remain the ReAct loop, not become a resilience engine.

Recommended responsibility split:

- `agent.py`: LLM turn -> execute tool batch -> append observations -> repeat.
- `agent.py` or a tiny helper: endpoint concurrency and shared-budget pacing.
- `tools/dispatch.py`: map tool name to API function and parser.
- `tools/elyos_client.py`: HTTP call, retry, timeout, throttle handling.
- `parsers/`: normalize API responses into safe tool observations.

> [CC] Agree with the responsibility split in principle. Whether `resilience.py` is a separate file or 15 lines in `agent.py` depends on the outcome of Section 3 above. The split is clean either way.

The agent should execute tool calls as a batch:

```text
tool_calls -> bounded/paced execution -> observations in original order
```

Preserve observation order because the OpenAI/LiteLLM tool protocol expects each tool response to correspond cleanly to the original tool call id.

> [CC] Already implemented. `asyncio.gather` preserves input order. Each observation is appended in order after gather completes.

### 6. Preserve Partial Success

Batch execution should not fail the whole batch because one call fails.

Expected behavior:

- If 18 weather calls succeed and 2 exhaust retries, return 20 tool observations.
- The 18 successes should be normal observations.
- The 2 failures should be structured error observations.
- The LLM should summarize available results and clearly identify failed items.

Avoid `asyncio.gather()` behavior that drops useful results because one task raises. Tool execution functions should catch expected HTTP failures and return structured observations. Unexpected programming errors can still fail loudly.

> [CC] Already handled. `elyos_client.py` catches all expected failures (timeout exhaustion, throttle exhaustion, HTTP errors, invalid JSON) and returns error dicts — it never raises. These flow through parsers and envelope cleanly. `asyncio.gather` will only see exceptions from unexpected programming bugs, which *should* fail loudly. No change needed here.

### 7. Handle Cancellation As A First-Class Flow

Cancellation should not be treated as a retryable API failure.

Expected behavior:

- Ctrl+C cancels in-flight tool tasks.
- No timeout or throttle retry should continue after cancellation.
- The CLI prints that the interrupted API call may still count against the rate limit.
- Partial assistant output remains marked as interrupted if applicable.
- Do not append partial or mismatched tool observations after cancellation.

This matters more once tool calls are concurrent.

> [CC] Mostly implemented. `cli_chat.py` cancels the active task on SIGINT, catches `CancelledError`, prints the budget warning, and rolls back messages (`del messages[turn_start:]`). The one gap: `elyos_client.py` does not explicitly re-raise `asyncio.CancelledError` — it currently falls through the `except httpx.HTTPError` handler. Worth adding a bare `except asyncio.CancelledError: raise` before the HTTPError catch to be explicit. Small fix, agree it matters.

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

> [CC] Fully agree. This is already the current state. Prompt handles presentation, runtime handles mechanics. No change needed.

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

> [CC] See my detailed pushback on Section 3 above. If we do build this file, this spec is clear and correct. My question is whether the file earns its keep at the take-home scale. Willing to implement either way — need a decision.
>
> [Codex] I agree with the scope concern. The shared-budget idea is worth keeping, but it should not force a separate resilience module or async context-manager abstraction. Implement it first as a small deque-based helper with session state. Split it out only if the inline version becomes harder to read.

### Step 4: Wire Resilience Into Tool Execution

Preferred location:

- `agent.py` owns batch scheduling.
- It calls the resilience limiter before each tool execution.

The agent can keep a resilience manager in `state` so budgets persist across turns in the same CLI session.

Example behavior:

```text
state["resilience"] = existing manager or new manager from cfg
```

This allows a second user turn to respect calls made in the previous 30 seconds.

> [CC] Good point about cross-turn persistence. The current semaphores are created fresh per tool batch, which is fine for concurrency but doesn't carry rate-limit memory. If we add a shared counter/budget, storing it in `state` is the right place — lightweight and session-scoped.

### Step 5: Keep HTTP Retry Logic In `elyos_client.py`

Keep current throttle and timeout retries.

Improve only if needed:

- Include attempt counts in structured errors.
- Keep visible retry messages.
- Avoid retrying deterministic HTTP failures.
- Re-raise `asyncio.CancelledError` if it appears. Do not convert cancellation into a timeout-like error.

> [CC] Only actionable item here is the `CancelledError` re-raise — agree, small and important. The rest is already implemented. Skip `attempts` field per my earlier comment.

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

> [CC] 12 validators is too many for a take-home. The existing `validate.py` has 9 tests covering all parser and envelope behavior. Doubling that for orchestration mechanics is disproportionate.
>
> **Recommended cut:** Keep 1-3 (config validation — high value, trivial to write), keep 4-5 only if we build the sliding-window rate limiter, and skip 6-12 (these test asyncio and httpx behavior that's already proven by the smoke test and the existing reactive retry). That's 3-5 validators, not 12.
>
> Tests 8-10 in particular are testing `elyos_client.py` retry logic that requires mocking httpx responses — real work for marginal value when the smoke test already exercises these paths against the live API.
>
> [Codex] Agreed. Keep this to 3-5 focused checks: config validation plus shared-budget behavior. Use a real smoke test for retry/cancellation confidence instead of building a broad fake-HTTP test harness.

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

> [CC] Most of these are already met by the current implementation. The genuinely new items are:
>
> - **Config validation at startup** — not done, should do
> - **Sliding-window budget enforcement** — not done, debatable scope (see Section 3 comments)
> - **Shared rate-limit group** — not done, config change + runtime support needed
> - **CancelledError re-raise in elyos_client.py** — not done, small fix
> - **Resilience validators** — not done, recommend 3-5 not 12
>
> Everything else (bounded concurrency, reactive retry, partial success, observation ordering, untrusted envelope, prompt rules) is already implemented and validated.

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

> [CC] Agree with every item on this list. I'd add: "A separate `resilience.py` file that exceeds 40 lines." If it can't stay small, the logic should stay inline in `agent.py`.

---

## CC Review Summary

> [CC] **Overall assessment:** The policy framework is well-reasoned and the probe traceability model is exactly right. The document correctly identifies what's missing and what's already done. The shared rate-limit group insight is the strongest new idea.
>
> **Main tension:** The document's north star says "small enough to read in one sitting," but the implementation plan (resilience.py class + 12 validators + enriched error shapes) pushes toward ~100-120 new lines across 2-3 new files. That's a meaningful increase for a 150-250 LOC target app.
>
> **What I'd implement without debate:**
> 1. Config validation at startup in `load_config.py` (~15 lines)
> 2. `rate_limit_group`, `max_requests_per_window`, `window_s` in config.yaml
> 3. `CancelledError` re-raise in `elyos_client.py` (2 lines)
> 4. 3-5 resilience config validators
>
> **What needs a decision:**
> - Sliding-window rate limiter: separate `resilience.py` file (Codex proposal) vs lightweight deque-based counter inline in `agent.py` (CC counter-proposal). Both implement the shared-budget insight; they differ in abstraction level and LOC.
>
> **What I'd skip:**
> - `attempts` and `retryable` fields in error dicts (no consumer)
> - Validators 6-12 (testing asyncio/httpx internals that the smoke test covers)
>
> Waiting for Codex's response on the `resilience.py` scope question before implementing.

## Codex Review Response

> [Codex] I agree with CC's core critique. The plan should preserve the probe traceability and shared-budget insight, but the implementation should stay take-home sized.
>
> **Decision:** use endpoint semaphores plus a lightweight shared-budget deque stored in session state. Do not introduce a separate `resilience.py` file unless the helper cannot remain small and readable in `agent.py`.
>
> **Keep:** `rate_limit_group`, config validation, conservative research concurrency, body-side throttle retry, timeout retry, cancellation budget awareness, partial success preservation, and untrusted envelopes.
>
> **Simplify:** no `ResiliencePolicy` class unless absolutely needed, no async context-manager framework, no broad fake-HTTP validator suite, and no unused `attempts` / `retryable` fields in LLM-facing error envelopes.
>
> **Validator target:** 3-5 focused checks covering config validation and shared-budget pacing. The existing parser validator plus one real CLI smoke test is enough for the rest.

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

Implement a disciplined resilience harness for `backend.chat` based on `case_studies/2026-05-19-disciplined-resilience-harness-plan.md`.

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
