# Case Study: Probe Findings to Chat-App Runtime Coverage

> **Note:** This is a historical audit. The config shape has since been simplified — see `backend/chat/config_reference.md` for the current design.

- **Original date:** 2026-05-18
- **Updated:** 2026-05-19
- **Reason for update:** The original audit was written before the ReAct refactor,
  bounded-concurrency resilience harness, shared-rate-limit proof, and test
  package cleanup. Several items previously marked open are now handled.
- **Status:** Mostly handled, with a small set of documentation and test-polish
  items still pending.

---

## TL;DR

The probe work is now substantially reflected in the chat app.

The current implementation handles the major correctness and trust risks:

- weather schema A/B normalization,
- weather fuzzy-match surfacing,
- HTTP-200 throttle envelopes,
- visible rate-limit waits and retry,
- research timeout handling,
- cached research without hardcoded date claims,
- truncated research with `processed_topic`,
- generic research-stub grounding,
- untrusted tool-result envelopes,
- valid ReAct tool-call protocol,
- bounded tool concurrency,
- shared Elyos rate-budget pacing,
- cancellation warning and cross-turn budget persistence.

The remaining gaps are no longer core agent-runtime failures. They are focused
cleanup items:

1. add or update a `DISCOVERIES.md` implementation matrix,
2. recursively truncate nested string fields in tool error bodies,
3. add a direct test for `rate_limit_safety_s`,
4. update stale README / CLI help references after the test-package rename,
5. optionally add a docstring to `backend/probes/__init__.py`.

---

## Source Material Reviewed

Primary probe scripts:

- `backend/probes/probe_weather.py`
- `backend/probes/probe_weather_cancellation.py`
- `backend/probes/probe_research.py`
- `backend/probes/probe_research_cancellation.py`

Generated probe reports:

- `api_analysis/_archive/weather_probe_report.html`
- `api_analysis/_archive/weather_cancellation_report.html`
- `api_analysis/_archive/research_probe_report.html`
- `api_analysis/_archive/research_cancellation_report.html`
- `api_analysis/_archive/shared_rate_limit_bucket_report.html`

Current chat-app implementation areas:

- `backend/chat/agent.py`
- `backend/chat/llm_client.py`
- `backend/chat/models.py`
- `backend/chat/parsers/`
- `backend/chat/tools/`
- `backend/chat/prompts.py`
- `backend/chat/interfaces/cli_chat.py`
- `backend/chat/tests/`
- `backend/chat/config.yaml`
- `backend/chat/load_config.py`

---

## North Star

The chat app should behave like a small resilient tool-using agent runtime:

- Treat API output as untrusted data.
- Normalize every known response shape before giving it to the LLM.
- Preserve API evidence fields instead of hardcoding probe-derived assumptions.
- Make slow, throttled, cancelled, cached, truncated, and mismatched states
  visible to the user.
- Ground research answers strictly in the tool result.
- Use bounded concurrency where useful, but respect the shared Elyos rate budget.
- Keep the implementation small and readable.

The goal is not to copy every probe detail into production code. The goal is to
encode every probe finding that changes runtime behavior, user trust, or failure
handling.

---

## Current Coverage Matrix

| Probe finding | Runtime handling | Status |
|---|---|---|
| `/weather` has flat and nested success schemas | `normalise_weather()` handles flat `temperature_c` and nested `conditions` shapes | Handled |
| Weather fuzzy match, e.g. `Mars` -> `Marseille` | Parser preserves `requested_location` and `returned_location`; prompt tells model to surface mismatch | Handled |
| Some impossible locations can still return plausible weather | Cannot be reliably detected from the API payload alone without an external location validator | Out of scope |
| Throttling can arrive as HTTP 200 body with `status="throttled"` | `elyos_client._call_api()` inspects JSON body, waits, and retries | Handled |
| Throttle waits can be long | CLI prints visible rate-limit retry waits | Handled |
| `/weather` and `/research` share effective rate budget | Confirmed by controlled probe; `config.yaml` uses shared `rate_limit_group: elyos_api` | Handled |
| Local rate window can be optimistic at boundary | `rate_limit_safety_s` extends client-side pacing window | Handled, needs direct test |
| Cancellation consumes server-side throttle budget | CLI warns on cancellation; session `rate_budgets` persist across turns | Handled |
| Concurrent calls can exhaust budget | Agent uses bounded concurrency plus shared-budget pacing | Handled |
| `/research` can return `{}` after timeout | `parse_research()` maps empty dict to `kind="timeout"` | Handled |
| HTTP timeout can be intermittent | `elyos_client._call_api()` retries timeout according to endpoint config | Handled |
| `/research` can return cached payloads | Parser preserves `generated_at`, `cache_age_seconds`, and human-readable `cache_age` | Handled |
| Cached research must not hardcode 2024 | Parser no longer injects stale-warning date; prompt forbids invented dates | Handled |
| `/research` can truncate long topics | Parser preserves `processed_topic` and `original_topic_length`; prompt tells model to show processed topic | Handled |
| `/research` often returns generic stubs | Prompt requires answers to use only `summary` and `sources`; generic summaries should be acknowledged as generic | Handled |
| Prompt-injection risk from API/tool data | Tool output is wrapped in an untrusted JSON envelope; prompt treats `data` as external information | Handled |
| Long user-controlled fields should not flood LLM context | Top-level `topic`, `summary`, and `message` are capped in `envelope()` | Partial |
| Nested error bodies can contain long strings | No recursive truncation yet | Pending |
| Tool-call protocol must be valid | `LLMTurn.assistant_message`, tool observations, and bounded ReAct rounds preserve protocol | Handled |
| Probe findings should be easy to explain in the Loom | Reports exist, but no current `DISCOVERIES.md` matrix | Pending |

---

## P0 Issues

P0 issues are correctness or safety failures. The current code handles the known
P0-class risks.

### P0.1 Research Hallucination From Generic Stub Responses - Handled

**Probe finding**

`/research` can return generic template summaries. If the LLM expands from its
own knowledge, the answer looks tool-grounded but is actually hallucinated.

**Required behavior**

- For `research_topic`, answer only from `summary` and `sources`.
- If the summary is generic, say it is generic.
- Do not add facts not present in the tool result.
- Treat a short honest response as correct.

**Current handling**

`backend/chat/prompts.py` frames the assistant as a router and formatter, not a
knowledge source. It explicitly restricts substantive research content to
`summary` and `sources`, and includes a GOOD/BAD example for generic research
output.

**Status**

Handled.

---

### P0.2 Tool Responses Must Stay Untrusted - Handled

**Probe finding**

Recon found prompt-injection risk in API-sourced content. User-controlled topic
text can also be echoed back by the API.

**Required behavior**

- Never pass raw API bodies into the LLM context.
- Always wrap tool results in a JSON envelope.
- Mark data as untrusted.
- Tell the LLM that API data is external information, not instructions.

**Current handling**

`backend/chat/parsers/__init__.py` wraps tool payloads as:

```json
{
  "source": "elyos_api",
  "tool": "...",
  "untrusted": true,
  "data": {}
}
```

`backend/chat/prompts.py` tells the model to treat the `data` field as external
information, not instructions.

**Status**

Handled.

**Remaining polish**

Nested string fields in error bodies are not recursively truncated. This is a P2
cleanup item, not a current P0 failure.

---

### P0.3 HTTP-200 Throttle Envelopes Must Not Be Treated as Success - Handled

**Probe finding**

Both endpoints can return throttling as HTTP 200:

```json
{
  "status": "throttled",
  "message": "Rate limit exceeded. Please wait.",
  "retry_after_seconds": 29,
  "data": null
}
```

**Required behavior**

- Parse every 200 response body.
- If `status == "throttled"`, sleep based on `retry_after_seconds`.
- Retry with a bounded retry count.
- If retries exhaust, return a clean tool error envelope.

**Current handling**

`backend/chat/tools/elyos_client.py` checks body-side throttle envelopes,
prints a visible retry message, waits with jitter, and retries up to the
endpoint-configured budget.

**Status**

Handled.

---

### P0.4 `/research` Empty `{}` Must Become Timeout, Not Content - Handled

**Probe finding**

`/research` can return literal `{}` after a slow server-side path.

**Required behavior**

- Detect empty dict.
- Convert to a structured timeout result.
- Tell the user research did not complete.
- Do not let the LLM answer from its own knowledge.

**Current handling**

`backend/chat/parsers/research.py` maps empty dict to
`ResearchResult(kind="timeout", ...)`. The prompt tells the LLM to report
timeouts and suggest retrying.

**Status**

Handled.

---

### P0.5 Weather Schema A/B Must Both Parse - Handled

**Probe finding**

`/weather` can return either:

- flat shape: `location`, `temperature_c`, `condition`, `humidity`
- nested shape: `location`, `conditions`, optional `note`

**Current handling**

`backend/chat/parsers/weather.py` normalizes both shapes into
`NormalisedWeather`.

**Status**

Handled.

---

### P0.6 Weather Fuzzy Match Must Be Visible - Handled

**Probe finding**

The API can silently fuzzy-match user input. Example: `Mars` can return
`Marseille`.

**Required behavior**

- Preserve user-requested location.
- Preserve API-returned location.
- Tell the user if they differ.

**Current handling**

`NormalisedWeather` stores both fields, and the prompt instructs the LLM to
surface mismatches.

**Limit**

Cases like `Atlantis` returning plausible weather cannot be detected from the
response alone. That would require a separate location-validity service, which
is out of scope for this take-home.

**Status**

Handled for detectable mismatches.

---

### P0.7 Tool-Call Protocol Must Stay Valid Across Rounds - Handled

**Required behavior**

- Assistant message includes `tool_calls`.
- Each tool result is returned with matching `tool_call_id`.
- Model is called again after tool results.
- Tool rounds are bounded.

**Current handling**

`backend/chat/llm_client.py` accumulates streamed tool calls into `ToolCall`
models. `backend/chat/agent.py` appends assistant messages and tool
observations, then repeats up to `MAX_TOOL_ROUNDS`.

**Status**

Handled.

---

## P1 Issues

P1 issues affect user trust, robustness, or faithful probe handling. Most are
now handled.

### P1.1 Cached Research Messaging Must Stay Evidence-Based - Handled

**Current handling**

The parser preserves `generated_at`, `cache_age_seconds`, and `cache_age`.
It does not manufacture a `stale_warning`. The prompt says cached results may be
outdated, but dates should only be mentioned if present in the tool payload.

**Status**

Handled.

---

### P1.2 Throttle Waits Should Be Visible to the User - Handled

**Current handling**

`backend/chat/tools/elyos_client.py` prints concise status during throttle
retry:

```text
Rate-limited, retrying in Ns...
```

**Status**

Handled.

---

### P1.3 Cancellation Should Preserve Budget Impact - Handled

**Current handling**

`backend/chat/interfaces/cli_chat.py` keeps a session-level state dictionary
across turns. That state includes `rate_budgets` and `rate_budget_locks`, so the
client-side budget is not reset after Ctrl+C. Cancellation also prints:

```text
Cancelled. The interrupted API call may still count against the rate limit.
```

**Status**

Handled.

**Note**

This is an approximate client-side model. The server remains authoritative, and
body-side `retry_after_seconds` retry remains the final recovery mechanism.

---

### P1.4 Truncation Should Surface the Actual Processed Topic - Handled

**Current handling**

`parse_research()` preserves `processed_topic` and `original_topic_length`.
The prompt tells the model to mention truncation and show `processed_topic`
when present.

**Status**

Handled.

---

### P1.5 Error Responses Should Be User-Friendly and Specific - Partially Handled

**Current handling**

The prompt has an `<error_rules>` section telling the model to explain tool
errors using only the provided `error` and `message` fields.

**Remaining gap**

`envelope()` only truncates top-level `topic`, `summary`, and `message` fields.
It does not recursively cap strings nested inside error bodies, such as a
FastAPI-style detail object or long echoed input.

**Recommended fix**

Add a tiny recursive truncation helper used by `envelope()`:

```python
def _truncate_value(value, max_len=200):
    if isinstance(value, str):
        return value if len(value) <= max_len else value[:max_len] + "..."
    if isinstance(value, list):
        return [_truncate_value(v, max_len) for v in value]
    if isinstance(value, dict):
        return {k: _truncate_value(v, max_len) for k, v in value.items()}
    return value
```

Add one parser test that verifies nested long strings are capped.

**Status**

Partial.

---

### P1.6 Research Retry Budget and Concurrency Should Be Deliberate - Handled

**Previous status**

Earlier versions serialized all tool calls. That was safe but slow.

**Current handling**

The current agent uses bounded concurrency and shared-budget pacing:

- `weather.max_concurrent: 4`
- `research.max_concurrent: 1`
- shared `rate_limit_group: elyos_api`
- `max_requests_per_window: 5`
- `window_s: 30`
- `rate_limit_safety_s: 2`

This is a better match for user expectations: independent calls can make
progress concurrently, while shared-budget pacing and server-side retry protect
against throttling.

**Status**

Handled.

**Remaining test polish**

Add one direct self-test proving `rate_limit_safety_s` extends the local pacing
window.

---

### P1.7 Do Not Auto-Refresh Research - Handled

**Required behavior**

- Do not silently call `/research` again just to improve a generic answer.
- If the result is too generic, ask the user for a narrower topic.

**Current handling**

The prompt treats generic summaries as valid tool output and asks the model not
to fill gaps from its own knowledge.

**Status**

Handled.

---

### P1.8 Tool Description Should Not Overstate `/research` - Handled

**Current handling**

`backend/chat/tools/schemas.py` describes research as a best-effort summary that
may be generic, cached, truncated, or timeout.

**Status**

Handled.

---

## P2 Issues

P2 issues improve maintainability, demonstration quality, and reviewer clarity.

### P2.1 Add or Update a `DISCOVERIES.md` Implementation Matrix - Pending

The probe reports are strong, but a reviewer still has to manually connect them
to runtime handling.

Recommended structure:

```text
Finding | Evidence | Runtime handling | File/function | Demo query | Status
```

Example rows:

- HTTP-200 throttle envelope -> weather/research reports -> `_call_api()`
- Shared rate bucket -> `shared_rate_limit_bucket_report.html` -> `tools/pacing.py:wait_for_budget()`
- Weather dual schema -> weather report -> `normalise_weather()`
- Mars -> Marseille mismatch -> requested/returned fields
- Research `{}` timeout -> research report -> `parse_research()`
- Cached/truncated research -> parser + prompt
- Cancellation consumes budget -> session-state budget persistence

**Status**

Pending.

---

### P2.2 README and CLI Help Should Match Test Package Rename - Pending

The code now uses:

- `backend/chat/tests/test_parsers.py`
- `backend/chat/tests/test_resilience.py`
- `backend/chat/tests/runner.py`

Stale live references should be updated:

- README architecture tree should no longer list `validate.py`.
- README command comment should say parser and resilience self-tests.
- `backend/chat/__main__.py` help should say parser and resilience self-tests.

Historical case studies may keep old wording if intentionally historical.

**Status**

Pending.

---

### P2.3 Add a Package Docstring to `backend/probes/__init__.py` - Pending

This file can stay functionally empty, but a docstring makes the package feel
intentional:

```python
"""Probe scripts for Elyos API discovery."""
```

**Status**

Pending.

---

### P2.4 Expand Self-Tests for Probe-Derived Cases - Partially Handled

Current self-tests cover:

- weather shape A,
- weather shape B,
- weather mismatch,
- fresh research,
- cached research with `generated_at`,
- no hardcoded `stale_warning`,
- truncated research with `processed_topic`,
- timeout research,
- error passthrough,
- untrusted envelope,
- config rejection,
- shared-budget pacing,
- cross-turn budget persistence,
- concurrent waiter serialization.

Recommended additions:

- nested long error strings are recursively capped,
- `rate_limit_safety_s` extends the pacing window,
- unknown weather schema returns `unknown_schema`.

**Status**

Partial.

---

### P2.5 Preserve `generated_at` in the Research Model - Handled

`ResearchResult` includes:

```python
generated_at: str | None = None
```

**Status**

Handled.

---

### P2.6 Use Topic-Neutral Prompt Examples - Optional

The current prompt example uses `climate change`. This is acceptable because the
test case used `solar energy`, but a synthetic topic would reduce model-prior
risk further.

**Status**

Optional polish.

---

## Recommended Implementation Order

1. Update live README and CLI help references to the new `tests/` package.
2. Add a direct `rate_limit_safety_s` self-test.
3. Add recursive envelope truncation for nested error bodies and one self-test.
4. Add or update `DISCOVERIES.md` with probe-to-runtime traceability.
5. Add a docstring to `backend/probes/__init__.py`.
6. Optionally switch prompt examples to a synthetic topic.

---

## Acceptance Criteria

The chat app can be considered aligned with the probe work when:

- `python -m backend.chat --validate` passes parser and resilience self-tests.
- A generic research result produces a generic, grounded answer with no invented
  facts.
- A cached research result says cached/may be outdated, and only mentions a date
  if the API result includes one.
- A long research topic tells the user the topic was truncated and shows the
  processed topic.
- `Mars` weather tells the user the API returned Marseille.
- A throttle envelope causes a visible wait message and retry.
- Ctrl+C cancels cleanly and the session-level rate budget survives the next
  turn.
- Shared weather/research rate-budget behavior is documented and enforced.
- `DISCOVERIES.md` maps every major probe finding to runtime handling or an
  explicit out-of-scope decision.

---

## Final Assessment

The current app now captures the important P0 and P1 runtime mechanics from the
probe work. It is no longer fair to describe the probe findings as only
partially reflected in the app in a major way.

The remaining work is targeted polish:

- make documentation match the current refactor,
- add two small self-tests,
- recursively cap nested error strings,
- document the discovery-to-implementation trail.

That is a much better end state for the take-home: the probes did not just
produce reports, they directly shaped the agent runtime.
