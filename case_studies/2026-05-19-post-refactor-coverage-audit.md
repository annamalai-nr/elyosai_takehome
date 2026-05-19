# Post-Refactor Coverage Audit: Probe Findings vs Chat App

- **Date:** 2026-05-19
- **Scope:** Cross-reference all 4 probe reports against the current `backend/chat/` implementation after the ReAct refactor. Also reconcile against the earlier Codex audit (`2026-05-18-probe-findings-chat-app-coverage.md`).
- **Verdict:** Core runtime behavior is solid. Three items Codex flagged as open are already fixed. Four genuinely open items remain — all are small, targeted changes.

---

## Codex Audit Reconciliation

The earlier Codex audit (`2026-05-18-probe-findings-chat-app-coverage.md`) was written against the pre-refactor `core/engine.py` layout. Several of its P1/P2 items have since been resolved. Its "Source Material Reviewed" section (lines 49-54) still references deleted paths (`core/engine.py`, `core/parsers.py`, `core/models.py`, `interfaces/validate.py`).

### Items Codex flagged that are now fixed

| Codex item | What Codex said | Current state |
|------------|----------------|---------------|
| **P1.1** Cached research messaging too hardcoded | App injects hardcoded "early 2024" stale warning | **Fixed.** `parse_research()` uses API-provided `generated_at` and `cache_age_seconds`. Validator asserts no `stale_warning` field. Prompt says to use API evidence only. |
| **P1.8** Tool description overstates /research | Description says "Research a topic in depth" | **Fixed.** `tools/schemas.py`: `"Look up a best-effort research summary. May return generic, cached, truncated, or timeout results."` |
| **P2.5** Preserve `generated_at` in research model | Field missing from model | **Fixed.** `ResearchResult` has `generated_at: str | None = None` in `models.py`. |

### Items Codex flagged that are still open

| Codex item | Status | My assessment |
|------------|--------|---------------|
| **P1.2** Visible throttle wait message | Open | Agree — `_call_api()` only `log.warning()` to stderr. See Gap 1 below. |
| **P1.3** Cancellation budget tracking | Open | Agree — no `last_cancelled_at`, no warning on quick retry. See Gap 2 below. |
| **P1.4** Truncation prompt should mention `processed_topic` | Open | Agree — prompt says "mention the topic was shortened" but doesn't tell LLM to show the actual processed text. Minor prompt wording fix. |
| **P1.5** Error responses need prompt rule + nested dict truncation | Open | Agree — no `<error_rules>` in prompt, nested dict error bodies not truncated. See Gap 3 and Gap 4 below. |
| **P1.6** Serial tool execution should be documented | Open | Agree — execution is serial but there's no comment explaining why. One-line fix. |
| **P1.7** Don't auto-refresh research | Fine as-is | LLM decides when to call tools; app doesn't auto-retry. No change needed. |
| **P2.1** `DISCOVERIES.md` matrix | Open | Not done. Lower priority — the Loom walkthrough can cover this verbally. |
| **P2.2** README shared throttle bucket wording | Open | README says "share a sliding window" which was not proven by probes. Minor wording fix. |
| **P2.4** Expand validators | Open | 9 validators cover core paths. Could add throttle/error/long-topic cases. |
| **P2.6** Topic-neutral prompt examples | Polish | Current example uses "climate change". Cosmetic. |

---

## Handled (30 findings — implemented correctly)

| # | Finding | Where |
|---|---------|-------|
| 1 | Throttle envelope detection (HTTP 200 body-side `status:"throttled"`) | `elyos_client.py _call_api()` checks `data.get("status") == "throttled"` on every 200 response |
| 2 | `retry_after_seconds` backoff (sliding window, never hardcoded) | Sleeps `retry_after_seconds + 1` before retry |
| 3 | Bounded retry count (`MAX_THROTTLE_RETRIES = 5`) | `elyos_client.py:9` |
| 4 | Throttle exhaustion returns structured error | Returns `{"error": "throttle_exhausted", ...}` |
| 5 | Error paths bypass throttle (401/404/405/422 return immediately) | `_call_api()` returns on non-200 without retry |
| 6 | Weather Shape A (flat: `temperature_c`, `condition`, `humidity`) | `parsers/weather.py` field-presence detection, not city-based |
| 7 | Weather Shape B (multi-observation `conditions` array) | `parsers/weather.py` parses list of `WeatherObservation` |
| 8 | Shape B is not city-specific (random per-call across all cities) | Parser is field-based — handles both shapes for any city |
| 9 | Shape B mixed condition casing ("Overcast" vs "light rain") | Passed through as-is — cosmetic, LLM handles fine |
| 10 | Unknown weather schema | Returns `{"error": "unknown_schema", ...}` |
| 11 | Weather fuzzy match (`Mars` → `Marseille`, `京都` → `京都市`) | Preserves `requested_location` and `returned_location`; prompt instructs LLM to flag mismatch |
| 12 | Research fresh schema | Parsed as `kind="fresh"`, `generated_at` preserved |
| 13 | Research cached schema (`cached:true`, `cache_age_seconds`, `generated_at`) | Parsed as `kind="cached"`, `cache_age` computed via `_humanize_seconds()`, no hardcoded dates |
| 14 | Research truncation over 50 chars | Parsed as `kind="truncated"`, `processed_topic` and `original_topic_length` preserved |
| 15 | Research empty `{}` response (~15s server timeout) | `parse_research()` checks `if not data:`, returns `ResearchResult(kind="timeout")` |
| 16 | Research generic/template summaries | System prompt forbids adding outside facts; GOOD/BAD few-shot example included |
| 17 | Untrusted data envelope on all tool output | `envelope()` wraps with `{"source": "elyos_api", "untrusted": true, ...}` |
| 18 | System prompt tells LLM tool data is external, not instructions | `<tool_data_handling>` section in `prompts.py` |
| 19 | `_truncate` on long string fields in envelope | `topic`, `summary`, `message` truncated at 200 chars |
| 20 | Prompt rules for cached research (mention staleness, use cache_age) | `<research_status_rules>` in `prompts.py` |
| 21 | Prompt rules for truncated research | System prompt: "mention the topic was shortened" |
| 22 | Prompt rules for timeout research | System prompt: "tell the user and suggest retrying" |
| 23 | Prompt rules for weather location mismatch | `<weather_rules>` in `prompts.py` |
| 24 | Client timeout 20s for /research, 15s for /weather | `elyos_client.py`: `get_weather()` 15.0, `research_topic()` 20.0 |
| 25 | Pending messages ("Looking up weather...", "Researching... (Ctrl+C to cancel)") | `dispatch.py` prints before each API call |
| 26 | asyncio task.cancel() produces clean CancelledError | `cli_chat.py` SIGINT handler cancels active task, catches error, returns to prompt |
| 27 | httpx client pool survives cancellation | Single shared `httpx.AsyncClient` reused across all turns |
| 28 | Sequential tool execution avoids concurrent throttle exhaustion | `agent.py`: `for tool_call in turn.tool_calls` — no parallel fan-out |
| 29 | No prompt injection in tool endpoints (envelope applied as defense-in-depth) | All 70 probe response bodies clean; envelope still applied |
| 30 | HTTP error passthrough (401/404/422/405) | Error dicts passed through parsers and enveloped |

---

## Resolved Gaps (fixed 2026-05-19)

The following gaps were identified in this audit and have since been implemented:

| Gap | Fix | File |
|-----|-----|------|
| Visible throttle wait message | `print(f"\r  Rate-limited, retrying in {wait}s...", flush=True)` during backoff | `elyos_client.py:52` |
| Cancellation budget warning | `"Cancelled. The interrupted API call may still count against the rate limit."` | `cli_chat.py:57` |
| No prompt rule for tool errors | Added `<error_rules>` section — LLM told to use only error/message fields, not hallucinate | `prompts.py` |
| Truncation prompt missing `processed_topic` | Added "If 'processed_topic' is present, show the user what the API actually used" | `prompts.py` |
| Serial tool execution undocumented | Added comment: "Serial: concurrent /research calls can exhaust retry budget under throttling (probe finding)" | `agent.py:30` |

---

## Remaining Gaps (1 low-priority + 1 unsolvable)

### Nested dict error bodies not truncated (P3)

**Probe evidence:** 5000-char location → 404 with full input echoed in a nested dict. `_truncate` only handles string values.

**Practical risk:** Low — LLM constructs arguments, won't send 5000 chars.

**Fix if needed:** Recursively truncate strings in nested dicts in `envelope()`, or JSON-serialize and truncate dict-valued `message` fields.

---

### Not solvable: Weather fabrication for fictional locations

The API returns `"location": "Atlantis"` with fabricated weather data. No mismatch signal — the name echoes back unchanged. Cannot detect client-side without an external location validator, which is out of scope.
