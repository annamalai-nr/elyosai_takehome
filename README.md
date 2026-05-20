# Elyos AI Take-Home

Candidate take-home for the Elyos AI Founding Software Engineer role.
Builds a CLI streaming chat application that calls two real-world APIs
(`/weather`, `/research`) with deliberately planted quirks.

## Repository layout

```
.
├── probe_reports/                     consolidated probe reports
│   ├── weather_report.html                    /weather findings (all quirks + cancellation)
│   ├── research_report.html                   /research findings (all quirks + cancellation)
│   └── _archive/                              raw per-probe reports (superseded)
│
├── backend/chat/                      streaming CLI chat package
│   ├── __main__.py                    python -m backend.chat (argparse)
│   ├── config.yaml                    model selection + Elyos API config
│   ├── config_reference.md            config.yaml field reference
│   ├── paths.py                       package path constants
│   ├── load_config.py                 config loader + validation
│   ├── models.py                      Pydantic models (domain + LLM turn)
│   ├── prompts.py                     system prompt
│   ├── llm_client.py                  LiteLLM streaming adapter
│   ├── agent.py                       ReAct loop + bounded concurrency + budget pacing
│   ├── parsers/                       response parsers + JSON envelope
│   │   ├── __init__.py                envelope() — untrusted data wrapper
│   │   ├── weather.py                 /weather response normalization
│   │   └── research.py                /research response normalization
│   ├── tools/                         tool schemas + execution + Elyos API
│   │   ├── schemas.py                 LLM tool schemas
│   │   ├── dispatch.py                tool execution dispatch
│   │   ├── pacing.py                  proactive rate-limit pacing + bounded execution
│   │   └── elyos_client.py            Elyos HTTP client with throttle/timeout retry
│   ├── tests/                         self-tests (--validate)
│   │   ├── runner.py                  test runner entry point
│   │   ├── test_history.py            7 history trimming tests
│   │   ├── test_parsers.py            9 parser/envelope behavioral tests
│   │   └── test_resilience.py         4 budget + concurrency tests
│   └── interfaces/
│       ├── cli_chat.py                interactive REPL + SIGINT handling
│       └── ws_server.py               WebSocket server for the web UI
│
└── frontend/
    └── index.html                     web UI (connects to backend via WebSocket)
```

## Setup

### One-time

```bash
# 1. Create the conda environment (Python 3.12)
conda create -n elyosai python=3.12 -y
conda activate elyosai

# 2. Install the project in editable mode (uses pyproject.toml + Hatch)
cd /Users/annamalainarayanan/Desktop/personal/interview_prep/elyosai
pip install -e .

# 3. Confirm the .env is present (already populated with the API key)
cat .env   # should show ELYOS_API_KEY=<your-key>
```

### Every session

```bash
conda activate elyosai
cd /Users/annamalainarayanan/Desktop/personal/interview_prep/elyosai
```

## Running the chat app

### CLI

```bash
conda activate elyosai
python -m backend.chat              # interactive streaming chat (CLI)
python -m backend.chat --serve      # start WebSocket server for the web UI
python -m backend.chat --validate   # run 20 parser + resilience + history self-tests
```

Config lives at `backend/chat/config.yaml`. Model name, API base URL, and
other settings are there. The `.env` at the project root supplies API keys.

LLM calls go through [LiteLLM](https://docs.litellm.ai/) (Python SDK, not
proxy). OpenAI and Anthropic text models from `allowed_models.csv` are
supported — set `llm.model_name` in the config to switch providers.

Operational logs go to stderr at INFO level (config load, throttle retries,
API errors). Set `LOG_LEVEL=DEBUG` in `.env` for per-request tracing.

### Web UI

The web frontend connects to the backend via WebSocket. Start the server
first, then open the HTML file:

```bash
# 1. Start the WebSocket server (ws://localhost:8765)
python -m backend.chat --serve

# 2. In another terminal, serve the frontend
python -m http.server 8000 --directory frontend
# then visit http://localhost:8000
```

The frontend streams LLM text, renders tool-call cards (weather, research),
and shows connection/rate-limit status — all driven by real backend data.

### LangSmith tracing

Every LLM call and tool execution is forwarded to
[LangSmith](https://docs.smith.langchain.com/) via LiteLLM's built-in
callback. Add these env vars to `.env`:

```
LANGSMITH_TRACING=true
LANGSMITH_API_KEY=<your-key>
LANGSMITH_PROJECT=<project-name>
```

Tracing is automatic — no code changes needed. If `LANGSMITH_TRACING` is
unset or false, the callback is a no-op.

## Take-home phases

| Phase | What | Status | Where to read |
|---|---|---|---|
| 0. Setup | conda env, `.env`, `pip install -e .` | Done | this README |
| 1. Investigation | probe `/weather` + `/research`, document findings | Done | `probe_reports/*.html` |
| 2. Build | CLI streaming chat with tool calling | Done | `backend/chat/` |
| 3. Harden | add handling for confirmed quirks + fix research hallucination | Done | `backend/chat/parsers/`, `backend/chat/prompts.py` |
| 4. Loom | 10–15 min walkthrough | | take-home PDF §Part 2 |
| 5. Submit | code + Loom + AI session transcript | | take-home PDF §Logistics |

## Conventions

- **Conda only.** Run all Python code in the `elyosai` env.
- The take-home originally recommends provider official SDKs. This
  implementation deliberately uses the **LiteLLM Python SDK** (not the
  LiteLLM proxy) so the same streaming/tool-call loop can switch between
  OpenAI and Anthropic text models via `backend/chat/config.yaml`.
- **Target 150–250 LOC** in the chat app. Past 400 is over-engineering.
- **Treat API responses as untrusted data** — a prompt-injection payload has
  already been found at `/` (the root endpoint).
- **Mind the throttle.** Both `/weather` and `/research` return throttling as
  HTTP 200 with a `{"status":"throttled","retry_after_seconds":N,...}` body.
  A controlled probe confirmed they share a single server-side rate budget. The chat app
  uses one API-level `rate_limit` block with proactive budget pacing and
  bounded concurrency to stay within limits. **Cancelled calls still consume a slot.**
