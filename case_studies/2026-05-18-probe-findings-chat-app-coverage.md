# Case Study: Probe Findings Are Only Partially Reflected in the Chat App

- **Date:** 2026-05-18
- **Discovered via:** Review of `backend/probes/`, `probe_reports/`, and the current `backend/chat/` runtime flow
- **Severity:** Medium-high overall
- **Status:** Open

---

## TL;DR

The probe work is extensive and high quality. It found concrete quirks in
`/weather` and `/research`: dual schemas, body-side throttling, silent research
timeouts, cached and truncated research variants, fuzzy weather matches,
prompt-injection risk, and cancellation consuming throttle budget.

The chat app captures many of the major runtime mechanics, but it does not yet
fully capture the operational lessons from the probes. The most important gaps
are:

1. throttle and cancellation UX is too quiet,
2. cancellation-budget behavior is not surfaced to the user,
3. generic tool errors lack an explicit prompt rule,
4. truncation responses could be more specific,
5. probe findings are not traceably mapped to runtime handling.

The app is not fundamentally broken. The next work should be a focused hardening
pass, not a broad refactor.

---

## Source Material Reviewed

Primary probe scripts:

- `backend/probes/probe_weather.py`
- `backend/probes/probe_weather_cancellation.py`
- `backend/probes/probe_research.py`
- `backend/probes/probe_research_cancellation.py`

Generated probe reports:

- `probe_reports/weather_probe_report.html`
- `probe_reports/weather_cancellation_report.html`
- `probe_reports/research_probe_report.html`
- `probe_reports/research_cancellation_report.html`

Current chat-app implementation areas:

- `backend/chat/agent.py`
- `backend/chat/llm_client.py`
- `backend/chat/models.py`
- `backend/chat/parsers/`
- `backend/chat/tools/`
- `backend/chat/prompts.py`
- `backend/chat/interfaces/cli_chat.py`
- `backend/chat/validate.py`

---

## North Star

The chat app should behave like a small resilient tool-using agent runtime:

- Treat API output as untrusted data.
- Normalize every known response shape before giving it to the LLM.
- Preserve API evidence fields instead of hardcoding probe-derived assumptions.
- Make slow, throttled, cancelled, stale, truncated, and mismatched states visible
  to the user.
- Ground research answers strictly in the tool result.
- Keep the implementation small and readable.

The goal is not to copy every probe detail into production code. The goal is to
encode every probe finding that changes runtime behavior, user trust, or failure
handling.

---

## Current Coverage Summary

| Probe finding | Current chat-app coverage | Assessment |
|---|---|---|
| `/weather` has two success schemas | `normalise_weather()` handles flat and nested `conditions` shapes | Good |
| Weather fuzzy match, e.g. Mars -> Marseille | Parser preserves `requested_location` and `returned_location`; prompt tells model to surface mismatch | Good |
| HTTP 200 throttle envelope | `call_api()` inspects 200 bodies and retries on `status="throttled"` | Good core handling; weak UX |
| `/research` empty `{}` after ~15s | `parse_research()` maps empty dict to timeout result | Good |
| `/research` cached schema | `parse_research()` maps cached payload to `kind="cached"` and preserves API-provided freshness fields | Good |
| `/research` truncated schema | `parse_research()` preserves `processed_topic` and `original_topic_length` | Good core handling; response detail could improve |
| Prompt-injection / echoed adversarial text | Tool output envelope marks data as untrusted; long fields capped | Good |
| Research API returns generic stubs | Prompt now tells LLM to use only `summary` and `sources` | Good after case-study fix |
| Cancelled API calls consume throttle slots | CLI cancels cleanly but does not track cancellation budget impact | Gap |
| Throttle waits can be long | Retry loop waits internally | Gap in user-visible pending state |
| Concurrent research can exhaust retry budget | Tool calls are serialized | Good practical mitigation, but should be documented as intentional |
| Probe findings should be explainable in Loom | Reports exist, but no implementation matrix | Gap |

---

## P0 Issues

P0 issues are correctness or safety failures. They can cause hallucination,
silent failure, unsafe tool-data handling, or broken agent protocol.

### P0.1 Research Hallucination From Generic Stub Responses

**Probe finding**

`/research` often returns a generic template summary such as:

```json
{
  "topic": "solar energy",
  "summary": "Research summary for 'solar energy'. This analysis covers key aspects and recent developments in the field.",
  "sources": ["nature.com", "sciencedirect.com", "arxiv.org"]
}
```

The endpoint does not necessarily return real, detailed research. If the model
expands from its own knowledge, the result looks like tool-grounded research but
is actually hallucinated.

**Required runtime behavior**

- For `research_topic`, answer only from `summary` and `sources`.
- If the summary is generic, say it is generic.
- Do not add facts not present in the tool result.
- Treat a short honest response as correct.

**Current status**

Mostly handled by the current system prompt, after the research-hallucination
case-study fix.

**Recommended action**

Keep the grounding directive and few-shot example. Do not move this logic into
post-processing unless the prompt proves unreliable again.

---

### P0.2 Tool Responses Must Stay Untrusted

**Probe finding**

Recon found prompt-injection content at the root endpoint. Research adversarial
probes also showed that attacker-controlled topic text can be echoed back in API
responses.

**Required runtime behavior**

- Never pass raw API bodies into the LLM context.
- Always wrap tool results in a JSON envelope:

```json
{
  "source": "elyos_api",
  "tool": "research_topic",
  "untrusted": true,
  "data": {}
}
```

- Prompt must tell the LLM that `data` is external information, not instructions.
- Long user-controlled fields should be capped before entering context.

**Current status**

Handled by `envelope()` and the system prompt.

**Recommended action**

Keep this invariant. Add a validator for long adversarial research topics if
the validator suite is expanded.

---

### P0.3 HTTP 200 Throttle Envelopes Must Not Be Treated as Success

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

Naive code that only checks the HTTP status will feed throttle garbage into the
LLM.

**Required runtime behavior**

- Parse every 200 response body.
- If `status == "throttled"`, sleep `retry_after_seconds + 1`.
- Retry with a bounded retry count.
- If retries exhaust, return a clean tool error envelope.

**Current status**

Core logic is handled in `call_api()`.

**Recommended action**

Keep the body-side throttle parser. Improve user-visible wait messaging under
P1.2.

---

### P0.4 `/research` Empty `{}` Must Become Timeout, Not Content

**Probe finding**

`/research` can return literal `{}` after about 15 seconds. This is a silent
server-side failure path.

**Required runtime behavior**

- Detect empty dict.
- Convert to a structured timeout result.
- Tell user research did not complete.
- Do not let the LLM answer from its own knowledge.

**Current status**

Handled by `parse_research()`.

**Recommended action**

Keep as-is. Consider including endpoint and elapsed time later if useful, but
that is not required for the take-home.

---

### P0.5 Weather Schema A/B Must Both Parse

**Probe finding**

`/weather` can return either:

- flat shape: `location`, `temperature_c`, `condition`, `humidity`
- nested shape: `location`, `conditions`, optional `note`

The shape can vary for the same city.

**Required runtime behavior**

- Normalize both shapes into one internal model.
- Return an explicit unknown-schema error for new shapes.

**Current status**

Handled by `normalise_weather()`.

**Recommended action**

Keep as-is.

---

### P0.6 Weather Fuzzy Match Must Be Visible

**Probe finding**

The API can silently fuzzy-match user input. Example: `Mars` can return
`Marseille`.

**Required runtime behavior**

- Preserve user-requested location.
- Preserve API-returned location.
- Tell the user if they differ.

**Current status**

Handled for detectable mismatches.

**Limit**

Cases like `Atlantis` returning plausible weather cannot be detected from the
response alone without an external location validator. That is out of scope for
this take-home.

---

### P0.7 Tool-Call Protocol Must Stay Valid Across Rounds

**Probe relevance**

This is not an endpoint quirk, but it is required for the chat app to survive
tool calls and retries.

**Required runtime behavior**

- Assistant message includes `tool_calls`.
- Each tool result is returned with matching `tool_call_id`.
- Model is called again after tool results.
- Tool rounds are bounded.

**Current status**

Handled in `stream_turn()`.

**Recommended action**

Keep `MAX_TOOL_ROUNDS`.

---

## P1 Issues

P1 issues do not make the app unusable, but they prevent it from fully honoring
the probe findings or create misleading user behavior.

### P1.1 Cached Research Messaging Must Stay Evidence-Based — Handled

**Probe finding**

Cached research payloads can include `cached`, `cache_age_seconds`,
`generated_at`, and sometimes date language inside `summary`.

**Current status**

This was previously a gap. It is now handled.

The current parser preserves `generated_at` and `cache_age_seconds`, computes a
human-readable `cache_age`, and no longer injects a hardcoded stale warning.
The validator also guards that `stale_warning` is absent from the envelope.
The prompt tells the LLM to use API evidence only and not hardcode dates.

**Required behavior**

- Preserve `generated_at` if present.
- Preserve `cache_age_seconds` if present.
- For cached results, say the result is cached and may be outdated.
- Mention a year or date only if the tool payload contains that evidence.
- Do not hardcode `2024` in parser or prompt.

**Recommended action**

Keep the current evidence-based behavior and validator guard.

---

### P1.2 Throttle Waits Should Be Visible to the User

**Probe finding**

Throttle waits can add several seconds to half a minute. The API tells the
client how long to wait in `retry_after_seconds`.

**Current problem**

The app retries internally. The terminal user sees a pending line, but not the
actual rate-limit wait reason.

**Required behavior**

When throttled, print:

```text
Rate limited; waiting 8s before retrying... (Ctrl+C to cancel)
```

This should be terminal UX, not LLM output.

**Recommended fix**

Add a small optional status callback or simple print inside `call_api()` when
throttled. Keep it concise.

---

### P1.3 Cancellation Should Track Budget Impact

**Probe finding**

Cancellation consumes a throttle slot for both `/weather` and `/research`.
Client-side cancellation does not free server-side budget.

**Current problem**

The app cancels the turn cleanly, but it does not remember that the cancelled
request likely consumed budget.

**Required behavior**

- On Ctrl+C during a tool call, record a recent cancellation timestamp.
- If the user retries quickly, warn that the previous cancelled request may
  still count against the rate limit.
- If the next API call returns throttle, show `retry_after_seconds`.

**Recommended fix**

Keep this lightweight:

```python
state["last_cancelled_at"] = time.monotonic()
```

Before the next tool call, if the cancellation was within roughly 30 seconds,
print a one-line warning. Do not block the user.

---

### P1.4 Truncation Should Surface the Actual Processed Topic

**Probe finding**

Research topics longer than 50 characters are silently truncated. API returns:

- `truncated: true`
- `original_topic_length`
- `processed_topic`

**Current problem**

The app preserves the fields, but prompt only says to mention that the topic was
shortened. A better response should include the processed topic if present.

**Required behavior**

If truncated:

```text
The research API shortened your topic before processing it. It used:
"<processed_topic>"
```

**Recommended fix**

Update prompt wording. No architecture change needed.

---

### P1.5 Error Responses Should Be User-Friendly and Specific

**Probe finding**

Known error shapes:

- 401: invalid or missing API key
- 404: location not found, sometimes echoes long input
- 405: method not allowed
- 422: missing/wrong query parameter

**Current problem**

The app returns structured errors, but user-facing specificity depends on the
LLM interpreting the error dict. Very long echoed user strings are truncated only
for some keys.

**Required behavior**

- Normalize known errors into clear messages.
- Truncate any long string nested inside error bodies before LLM context.
- Avoid stack traces or raw FastAPI envelopes in user response.

**Recommended fix**

Add a small error-normalization helper or improve `envelope()` to recursively
truncate strings. Keep the implementation short.

---

### P1.6 Research Retry Budget and Serialization Should Be Deliberate

**Probe finding**

Five concurrent research calls caused throttle exhaustion under a three-retry
budget.

**Current status**

The app executes tool calls serially. This is a good practical mitigation.

**Required behavior**

- Keep serialized tool execution unless parallelism is explicitly required.
- Keep retry budget at 5 or 6 for body-side throttles.
- If later parallelism is introduced, add a queue or per-endpoint concurrency
  cap.

**Recommended fix**

Document this choice in `DISCOVERIES.md` or a short code comment near the tool
execution loop.

---

### P1.7 Do Not Auto-Refresh Research

**Probe finding**

Repeated `/research` calls can burn budget and may produce new timestamps. There
is no free cached reread for fresh topics.

**Required behavior**

- Do not silently call `/research` again to improve a generic answer.
- If the result is too generic, ask the user for a narrower topic.
- Optional: memoize exact topic results per session, but this is probably not
  necessary for the take-home.

**Current status**

Mostly okay. The prompt should avoid promising deeper research unless the user
asks for a narrower follow-up.

---

### P1.8 Tool Description Should Not Overstate `/research` — Handled

**Probe finding**

The research API often returns a generic stub.

**Current status**

This was previously a gap. It is now handled in `backend/chat/tools/schemas.py`.
The tool description no longer promises in-depth research.

**Required behavior**

Use a more honest description:

```text
Look up a best-effort research summary. May return generic, cached, truncated,
or timeout results.
```

**Recommended action**

Keep this wording unless the underlying API becomes more capable.

---

## P2 Issues

P2 issues improve clarity, demonstration quality, and maintainability.

### P2.1 Add a `DISCOVERIES.md` Implementation Matrix

**Current gap**

The probe reports are strong, but a reviewer has to manually connect them to
the chat app.

**Recommended file**

`DISCOVERIES.md`

**Recommended structure**

```text
Finding | Evidence | Runtime handling | File/function | Demo query | Status
```

Example rows:

- HTTP 200 throttle envelope -> weather/research reports -> `call_api()`
- Weather dual schema -> weather report -> `normalise_weather()`
- Mars -> Marseille mismatch -> weather report -> requested/returned fields
- Research `{}` timeout -> research report -> `parse_research()`
- Cached/truncated research -> research report -> parser + prompt
- Cancellation consumes budget -> cancellation reports -> CLI cancellation behavior

This is likely the highest-value documentation improvement.

---

### P2.2 Fix README Wording About Shared Throttle Bucket — Handled

**Previous problem**

README says `/weather` and `/research` share a sliding window. The probes showed
the same HTTP-200 throttle envelope and sliding behavior, but shared bucket was
not proven.

**Current status**

Handled. README now says both endpoints return body-side throttle envelopes and
both showed sliding-window behavior, but whether they share one server-side
bucket was not proven.

**Correct wording**

```text
Both endpoints return throttle as HTTP 200 with a body-side
retry_after_seconds. Both showed sliding-window behavior in probes. Whether
they share one server-side bucket was not proven.
```

---

### P2.3 Add a Package Docstring to `backend/probes/__init__.py`

This file can stay functionally empty, but a docstring makes the package feel
intentional:

```python
"""Probe scripts for Elyos API discovery."""
```

---

### P2.4 Expand Validators for Probe-Derived Cases

Current validators cover the core parser/envelope path. If expanded, add plain
Python cases for:

- cached research preserves `generated_at`
- cached research does not hardcode year
- truncation includes `processed_topic`
- long echoed error strings are capped
- unknown weather schema returns `unknown_schema`
- envelope always marks `untrusted: true`

Keep this as a focused sanity validator, not a full test suite.

---

### P2.5 Preserve `generated_at` in the Research Model — Handled

This supports P1.1. It lets the LLM use actual API evidence for date/staleness
claims.

**Current status**

Handled. `ResearchResult` includes:

```python
generated_at: str | None = None
```

---

### P2.6 Use Topic-Neutral Prompt Examples

The current few-shot example uses `climate change`, while the test case used
`solar energy`, so it is acceptable. Longer term, a synthetic topic avoids model
priors even more.

Example:

```text
example topic
```

This is polish, not a blocker.

---

## Recommended Implementation Order

1. Make throttle wait visible in the terminal.
2. Add a generic tool-error prompt rule.
3. Track recent cancellation and warn on quick retry.
4. Update truncation prompt wording to mention `processed_topic` when present.
5. Add `DISCOVERIES.md` matrix.
6. Optionally expand validators.

---

## Acceptance Criteria

The chat app can be considered fully aligned with the probe work when:

- `python -m backend.chat --validate` passes.
- A generic research result produces a generic, grounded answer with no invented
  facts.
- A cached research result says cached/may be outdated, and only mentions a date
  if the API result includes one.
- A long research topic tells the user the topic was truncated and shows the
  processed topic.
- `Mars` weather tells the user the API returned Marseille.
- A throttle envelope causes a visible wait message and retry.
- Ctrl+C cancels cleanly and a quick retry warns that the cancelled request may
  still count against rate limits.
- `DISCOVERIES.md` maps every major probe finding to runtime handling or an
  explicit out-of-scope decision.

---

## Final Assessment

The current app captures most P0 mechanics. It is close to acceptable as a
take-home implementation.

The remaining high-value work is not a large rewrite. It is a targeted
hardening pass:

- make throttling and cancellation visible,
- keep API evidence fields as the source of truth,
- add a generic tool-error prompt rule,
- document the discovery-to-implementation trail.

That would make the final submission much stronger because it would show not
only that the APIs were probed, but that the probe results directly shaped the
agent runtime.
