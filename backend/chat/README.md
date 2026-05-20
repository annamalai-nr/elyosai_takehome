# Backend — Streaming Chat

ReAct-style streaming chat agent that calls two Elyos APIs (`/weather`, `/research`)
with tool calling, bounded concurrency, and throttle/timeout retry.

## Architecture

```
__main__.py          entry point (--validate, --serve, or interactive CLI)
config.yaml          model name, API base URL, endpoint settings
load_config.py       YAML loader + validation (uses paths.py for file paths)
models.py            Pydantic models: ToolCall, LLMTurn, WeatherObservation, etc.
prompts.py           system prompt (tool-data handling, hallucination guards)
llm_client.py        LiteLLM streaming adapter — one LLM turn at a time
agent.py             ReAct loop: LLM turn → tool execution → observation → repeat

parsers/
  __init__.py        envelope() — wraps tool results as untrusted JSON for the LLM
  weather.py         normalise_weather() — handles Shape A (flat) and Shape B (array)
  research.py        parse_research() — handles fresh, cached, truncated, timeout

tools/
  schemas.py         OpenAI-format tool schemas (get_weather, research_topic)
  dispatch.py        execute_tool_call() — routes tool calls to API functions
  elyos_client.py    HTTP client with throttle backoff + timeout retry

interfaces/
  cli_chat.py        interactive REPL with SIGINT cancellation + history trimming
  ws_server.py       WebSocket server for the web UI (ws://localhost:8765)

tests/
  runner.py          test runner (python -m backend.chat --validate)
  test_parsers.py    9 parser/envelope behavioral tests
  test_history.py    7 history trimming tests
```

## Key design decisions

- **Untrusted data envelope**: All API responses are wrapped with
  `{"source": "elyos_api", "untrusted": true, ...}` before entering LLM context.
  A prompt-injection payload was found at the API root endpoint.
- **Bounded concurrency**: Per-endpoint `asyncio.Semaphore` limits parallel requests
  (currently weather: 1, research: 1 — same-endpoint calls are serialized, cross-
  endpoint calls may overlap). Both endpoints share a single server-side rate budget.
- **Throttle retry**: The server returns `HTTP 200` with `{"status": "throttled",
  "retry_after_seconds": N}`. The client sleeps for `retry_after_seconds + 1` and
  retries up to `max_throttle_retries` (default 2).
- **LiteLLM**: All LLM calls go through the LiteLLM Python SDK (not the proxy),
  so the same streaming/tool-call loop works across OpenAI and Anthropic models.
- **emit callback**: An optional `emit` async callback threads through the entire
  pipeline. When `None` (CLI mode), functions print to stdout. When provided
  (WebSocket mode), they send JSON events to the frontend.

## Running

```bash
conda activate elyosai
python -m backend.chat              # interactive CLI chat
python -m backend.chat --serve      # WebSocket server for web UI
python -m backend.chat --validate   # run 16 self-tests
```
