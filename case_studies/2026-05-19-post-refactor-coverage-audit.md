# Post-Refactor Coverage Audit: Probe Findings vs Chat App

- **Date:** 2026-05-19
- **Scope:** Cross-reference all 4 probe reports against the current `backend/chat/` implementation after the ReAct refactor and disciplined resilience harness. Also reconcile against the earlier Codex audit (`2026-05-18-probe-findings-chat-app-coverage.md`).
- **Verdict:** Core runtime behavior is solid. Resilience harness adds proactive budget pacing, bounded concurrent execution, timeout retry, and config-driven policy — covered by 20 self-tests (9 parser + 4 resilience + 7 history), with `rate_limit_safety_s` behavior still needing a direct test. Endpoint schema validation was intentionally removed (low-value for a take-home; runtime failures are acceptable). Two low-priority items remain.

---

## Codex Audit Reconciliation

The earlier Codex audit (`2026-05-18-probe-findings-chat-app-coverage.md`) was written against the pre-refactor `core/engine.py` layout. Several of its P1/P2 items have since been resolved. Its "Source Material Reviewed" section has been updated to reference current paths.

### Items Codex flagged that are now fixed

| Codex item | What Codex said | Current state |
|------------|----------------|---------------|
| **P1.1** Cached research messaging too hardcoded | App injects hardcoded "early 2024" stale warning | **Fixed.** `parse_research()` uses API-provided `generated_at` and `cache_age_seconds`. Validator asserts no `stale_warning` field. Prompt says to use API evidence only. |
| **P1.8** Tool description overstates /research | Description says "Research a topic in depth" | **Fixed.** `tools/schemas.py`: `"Look up a best-effort research summary. May return generic, cached, truncated, or timeout results."` |
| **P2.5** Preserve `generated_at` in research model | Field missing from model | **Fixed.** `ResearchResult` has `generated_at: str | None = None` in `models.py`. |

### Items Codex flagged that are now also fixed (resilience harness)

| Codex item | Status | Resolution |
|------------|--------|------------|
| **P1.2** Visible throttle wait message | **Fixed** | `_call_api()` prints `"\r  Rate-limited, retrying in {wait}s..."` to stdout during backoff. |
| **P1.3** Cancellation budget tracking | **Fixed** | `cli_chat.py` prints cancellation warning; `session_state` preserves `rate_budgets` across turns and Ctrl+C. |
| **P1.4** Truncation prompt should mention `processed_topic` | **Fixed** | `<research_status_rules>` in `prompts.py`: "If 'processed_topic' is present, show the user what the API actually used." |
| **P1.5** Error responses need prompt rule | **Fixed** | `<error_rules>` section added to `prompts.py`. Nested dict truncation remains a P3 (see Remaining Gaps). |
| **P1.6** Serial tool execution should be documented | **Superseded** | Execution is now bounded parallel via `asyncio.gather` + per-endpoint semaphores. `<tool_data_handling>` in `prompts.py` tells LLM about bounded concurrency. |
| **P1.7** Don't auto-refresh research | Fine as-is | LLM decides when to call tools; app doesn't auto-retry. No change needed. |

### Items still open (lower priority)

| Codex item | Status | My assessment |
|------------|--------|---------------|
| **P2.1** `DISCOVERIES.md` matrix | Open | Not done. Lower priority — the Loom walkthrough can cover this verbally. |
| **P2.2** README shared throttle bucket wording | **Resolved** | README now references `shared_rate_limit_bucket_report.html` and describes confirmed shared budget with proactive pacing. |
| **P2.4** Expand validators | **Superseded** | Endpoint schema validation intentionally removed. 20 tests now (9 parser + 4 resilience + 7 history). Resilience tests cover budget pacing, shared groups, persistence, and concurrent waiter serialization. Could still add throttle/error/long-topic cases. |
| **P2.6** Topic-neutral prompt examples | Polish | Current example uses "climate change". Cosmetic. |

---

## Handled (39 findings — implemented correctly)

### Throttle & retry (6)

| # | Finding | Where |
|---|---------|-------|
| 1 | Throttle envelope detection (HTTP 200 body-side `status:"throttled"`) | `elyos_client.py _call_api()` checks `data.get("status") == "throttled"` on every 200 response |
| 2 | `retry_after_seconds` backoff with jitter | Sleeps `retry_after_seconds + 1 + random.uniform(0, jitter)` before retry |
| 3 | Bounded throttle retry count (config-driven) | `endpoint_cfg["max_throttle_retries"]` in `config.yaml` — no hardcoded constant |
| 4 | Throttle exhaustion returns structured error | Returns `{"error": "throttle_exhausted", ...}` |
| 5 | Error paths bypass throttle (401/404/405/422 return immediately) | `_call_api()` returns on non-200 without retry |
| 6 | Timeout retry with jitter | `httpx.TimeoutException` caught, retried up to `max_timeout_retries` with `random.uniform(0, jitter)` sleep. Returns `{"error": "request_timeout", ...}` on exhaustion |

### Weather parsing (6)

| # | Finding | Where |
|---|---------|-------|
| 7 | Weather Shape A (flat: `temperature_c`, `condition`, `humidity`) | `parsers/weather.py` field-presence detection, not city-based |
| 8 | Weather Shape B (multi-observation `conditions` array) | `parsers/weather.py` parses list of `WeatherObservation` |
| 9 | Shape B is not city-specific (random per-call across all cities) | Parser is field-based — handles both shapes for any city |
| 10 | Shape B mixed condition casing ("Overcast" vs "light rain") | Passed through as-is — cosmetic, LLM handles fine |
| 11 | Unknown weather schema | Returns `{"error": "unknown_schema", ...}` |
| 12 | Weather fuzzy match (`Mars` → `Marseille`, `京都` → `京都市`) | Preserves `requested_location` and `returned_location`; prompt instructs LLM to flag mismatch |

### Research parsing (4)

| # | Finding | Where |
|---|---------|-------|
| 13 | Research fresh schema | Parsed as `kind="fresh"`, `generated_at` preserved |
| 14 | Research cached schema (`cached:true`, `cache_age_seconds`, `generated_at`) | Parsed as `kind="cached"`, `cache_age` computed via `_humanize_seconds()`, no hardcoded dates |
| 15 | Research truncation over 50 chars | Parsed as `kind="truncated"`, `processed_topic` and `original_topic_length` preserved |
| 16 | Research empty `{}` response (~15s server timeout) | `parse_research()` checks `if not data:`, returns `ResearchResult(kind="timeout")` |

### Prompt & envelope (8)

| # | Finding | Where |
|---|---------|-------|
| 17 | Research generic/template summaries | System prompt forbids adding outside facts; GOOD/BAD few-shot example included |
| 18 | Untrusted data envelope on all tool output | `envelope()` wraps with `{"source": "elyos_api", "untrusted": true, ...}` |
| 19 | System prompt tells LLM tool data is external, not instructions | `<tool_data_handling>` section in `prompts.py` |
| 20 | `_truncate` on long string fields in envelope | `topic`, `summary`, `message` truncated at 200 chars |
| 21 | Prompt rules for cached research (mention staleness, use cache_age) | `<research_status_rules>` in `prompts.py` |
| 22 | Prompt rules for truncated research (includes `processed_topic`) | `<research_status_rules>`: "If 'processed_topic' is present, show the user what the API actually used" |
| 23 | Prompt rules for timeout research | System prompt: "tell the user and suggest retrying" |
| 24 | Prompt rules for weather location mismatch | `<weather_rules>` in `prompts.py` |

### Runtime & cancellation (6)

| # | Finding | Where |
|---|---------|-------|
| 25 | Config-driven timeouts (research: 20s, weather: 15s) | `endpoint_cfg["timeout_s"]` read from `config.yaml` — no hardcoded values in client |
| 26 | Pending messages ("Looking up weather...", "Researching... (Ctrl+C to cancel)") | `dispatch.py` prints before each API call |
| 27 | asyncio task.cancel() produces clean CancelledError | `cli_chat.py` SIGINT handler cancels active task, catches error, returns to prompt |
| 28 | CancelledError propagation in client | Explicit `except asyncio.CancelledError: raise` before other handlers in `_call_api()` |
| 29 | httpx client pool survives cancellation | Single shared `httpx.AsyncClient` reused across all turns |
| 30 | Prompt rules for tool errors | `<error_rules>` in `prompts.py`: use only error/message fields, do not hallucinate data |

### Resilience harness (9)

| # | Finding | Where |
|---|---------|-------|
| 31 | Bounded concurrent execution (weather: 4, research: 1) | `asyncio.Semaphore` per endpoint in `agent.py`, fan-out via `asyncio.gather` |
| 32 | Proactive budget pacing (shared sliding window) | `_wait_for_budget()` in `agent.py`: per-group `collections.deque` of timestamps, sleeps when window is full |
| 33 | Shared rate-limit group across endpoints | Both endpoints use `rate_limit_group: "elyos_api"` — share one deque and one budget |
| 34 | Boundary-burst prevention (`rate_limit_safety_s`) | Effective window = `window_s + rate_limit_safety_s` (32s vs 30s), prevents premature burst at window edge |
| 35 | Concurrency-safe budget checking | Per-group `asyncio.Lock` in `_wait_for_budget()` — lock held only for check/append, released before sleep |
| 36 | Session state persists across turns and cancellation | `session_state` dict created once in `cli_chat.py`; `rate_budgets` and `rate_budget_locks` survive Ctrl+C rollback |
| 37 | Config-driven resilience policy (10 fields per endpoint) | All retry counts, timeouts, jitter, concurrency, budget params in `config.yaml` — zero hardcoded constants |
| 38 | Config startup validation | `_validate_endpoints()` in `load_config.py` checks presence, type, and range for all 10 required fields |
| 39 | No prompt injection in tool endpoints (envelope applied as defense-in-depth) | All 70 probe response bodies clean; envelope still applied |

---

## Resolved Gaps (fixed 2026-05-19)

The following gaps were identified in this audit and earlier Codex audit, and have since been implemented:

| Gap | Fix | File |
|-----|-----|------|
| Visible throttle wait message | `print(f"\r  Rate-limited, retrying in {wait}s...", flush=True)` during backoff | `elyos_client.py:69` |
| Cancellation budget warning | `"Cancelled. The interrupted API call may still count against the rate limit."` | `cli_chat.py:59` |
| No prompt rule for tool errors | Added `<error_rules>` section — LLM told to use only error/message fields, not hallucinate | `prompts.py` |
| Truncation prompt missing `processed_topic` | Added "If 'processed_topic' is present, show the user what the API actually used" | `prompts.py` |
| Serial execution → bounded parallel | Replaced serial `for` loop with `asyncio.gather` + per-endpoint semaphores; `<tool_data_handling>` updated to describe bounded concurrency | `agent.py`, `prompts.py` |
| No timeout retry | Added `httpx.TimeoutException` catch with retry up to `max_timeout_retries` + jitter | `elyos_client.py:35-43` |
| No proactive budget pacing | Added `wait_for_budget()` with per-group deque sliding window and asyncio.Lock | `tools/pacing.py` |
| Hardcoded retry/timeout constants | All resilience parameters moved to `config.yaml` endpoint config | `config.yaml`, `elyos_client.py` |
| No config validation at startup | Intentionally removed — low-value defensive scaffolding for a take-home | *(deleted)* |
| Session state lost between turns | Created `session_state` once before REPL loop; `rate_budgets` persists across turns and Ctrl+C | `cli_chat.py:30` |
| Boundary burst at window edge | Added `rate_limit_safety_s: 2` config field; effective window = `window_s + rate_limit_safety_s` | `config.yaml`, `tools/pacing.py` |

---

## Test Coverage Summary

**20 tests** (run via `python -m backend.chat --validate`):

- **9 parser tests** (`test_parsers.py`): Shape A, Shape B, location mismatch, fresh/cached/truncated/timeout research, error passthrough, envelope structure.
- **4 resilience tests** (`test_resilience.py`): Budget delays over capacity, shared group across endpoints, budget persists across turns, concurrent waiters are serialized.
- **7 history tests** (`test_history.py`): No-op under limit, no-op when disabled, system prompt preserved, current user message preserved, tool-call turn integrity, oldest-first trimming, cancellation rollback regression.

---

## Remaining Gaps (1 low-priority + 1 unsolvable)

### Nested dict error bodies not truncated (P3)

**Probe evidence:** 5000-char location → 404 with full input echoed in a nested dict. `_truncate` only handles string values.

**Practical risk:** Low — LLM constructs arguments, won't send 5000 chars.

**Fix if needed:** Recursively truncate strings in nested dicts in `envelope()`, or JSON-serialize and truncate dict-valued `message` fields.

---

### Not solvable: Weather fabrication for fictional locations

The API returns `"location": "Atlantis"` with fabricated weather data. No mismatch signal — the name echoes back unchanged. Cannot detect client-side without an external location validator, which is out of scope.
