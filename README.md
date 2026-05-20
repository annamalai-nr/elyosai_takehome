# Elyos AI Take-Home

Candidate take-home for the Elyos AI Founding Software Engineer role.
Builds a CLI streaming chat application that calls two real-world APIs
(`/weather`, `/research`) with deliberately planted quirks.

## Repository layout

```
.
├── README.md                          this file
├── north_stars.md                     engineering conventions
├── project_context.md                 assignment shape, sources, scope
├── AGENTS.md                          repo-wide AI-agent instructions
├── CLAUDE.md                          Claude Code specifics
├── pyproject.toml                     Hatch packaging + dependencies
├── requirements.txt                   pip dependencies (also covered by pyproject)
├── .env                               ELYOS_API_KEY (gitignored)
├── .vscode/settings.json              Python interpreter + analysis settings
├── .claude/                           Claude Code permissions
├── Elyos Interview 2.0.pdf            the take-home PDF (source of truth)
│
├── initial_research_reports/          pre-probing strategy artifacts
│   ├── Elyos AI — Research Report.html       broad company research
│   ├── elyos_api_recon_findings.html          unauthenticated host recon
│   ├── api_quirks_research_v2.html            quirk hypotheses (v2)
│   └── api_quirks_research_v3.html            quirk hypotheses (v3, final)
│
├── initial_api_invocations/           early sanity probe + recon outputs
│   ├── probe_injection.py                     2-call injection-content check
│   ├── fetch.sh                               unauthenticated recon shell script
│   ├── weather_<ts>.raw                       sanity-probe raw responses
│   └── research_<ts>.raw
│
├── probe_reports/                     consolidated probe reports
│   ├── weather_report.html                    /weather findings (all quirks + cancellation)
│   ├── research_report.html                   /research findings (all quirks + cancellation)
│   └── _archive/                              raw per-probe reports (superseded)
│       ├── weather_probe_report.html          /weather main probe (32 calls)
│       ├── weather_cancellation_report.html   /weather cancellation sidecar
│       ├── research_probe_report.html         /research main probe (27 calls)
│       ├── research_cancellation_report.html  /research cancellation sidecar
│       ├── shared_rate_limit_bucket_report.html  shared rate budget proof
│       └── probe_plans/research_probe_plan.html  /research pre-execution plan
│
├── case_studies/                      trace-driven debugging write-ups
│   ├── 2026-05-18-research-api-hallucination.md       root cause + diagnosis
│   ├── 2026-05-18-probe-findings-chat-app-coverage.md probe → runtime coverage audit
│   ├── 2026-05-19-disciplined-resilience-harness-plan.md resilience policy + implementation plan
│   ├── 2026-05-19-post-refactor-coverage-audit.md     post-harness coverage reconciliation
│   └── fix-round-*                                    iterative hallucination fix attempts
│
├── backend/
│   ├── __init__.py
│   ├── chat/                          streaming CLI chat package
│   │   ├── __init__.py
│   │   ├── __main__.py                python -m backend.chat (argparse)
│   │   ├── config.yaml                model selection + Elyos API config
│   │   ├── paths.py                   package path constants
│   │   ├── load_config.py             config loader + validation
│   │   ├── models.py                  Pydantic models (domain + LLM turn)
│   │   ├── parsers/                   response parsers + JSON envelope
│   │   │   ├── weather.py             /weather response normalization
│   │   │   └── research.py            /research response normalization
│   │   ├── prompts.py                 system prompt
│   │   ├── tools/                      tool schemas + execution + Elyos API
│   │   │   ├── schemas.py             LLM tool schemas
│   │   │   ├── dispatch.py            tool execution dispatch
│   │   │   ├── pacing.py              proactive rate-limit pacing + bounded execution
│   │   │   └── elyos_client.py        raw Elyos HTTP/retry client
│   │   ├── llm_client.py              LiteLLM streaming adapter
│   │   ├── agent.py                   ReAct loop + bounded concurrency + budget pacing
│   │   ├── tests/                     self-tests (--validate)
│   │   │   ├── runner.py              test runner entry point
│   │   │   ├── test_history.py         7 history trimming tests
│   │   │   ├── test_parsers.py        9 parser/envelope behavioral tests
│   │   │   └── test_resilience.py     4 budget + concurrency tests
│   │   └── interfaces/
│   │       └── cli_chat.py            interactive REPL + SIGINT handling
│   ├── llm_utils/                     ported LiteLLM kwargs helpers
│   │   └── litellm_kwargs.py
│   ├── reference_docs/                allowed model names + LLM rules
│   │   ├── allowed_models.csv
│   │   ├── llm_rules.md
│   │   └── llm_prompting_guide.md
│   ├── probes/                        the structured probe scripts
│   │   ├── __init__.py
│   │   ├── probe_weather.py
│   │   ├── probe_weather_cancellation.py
│   │   ├── probe_research.py
│   │   └── probe_research_cancellation.py
│   └── outputs/probes/                per-call raw responses + JSONL logs
│       ├── weather/
│       └── research/
│
└── frontend/
    └── index.html                     standalone web UI (open in browser)
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
python -m backend.chat              # interactive streaming chat
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

Open `frontend/index.html` directly in a browser — no build step or server
required. It is a self-contained HTML/CSS/JS file with a demo simulation of
the chat interface (weather cards, research cards, rate-limit indicators,
cancellation handling). To serve it locally:

```bash
# Option 1: open the file directly
open frontend/index.html

# Option 2: serve via Python's built-in HTTP server
python -m http.server 8000 --directory frontend
# then visit http://localhost:8000
```

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

## Running the probes

All probe scripts read `ELYOS_API_KEY` automatically from `.env` (at the
project root) via python-dotenv. You can also pass the key explicitly as
the first CLI argument.

### Initial sanity probe (2 calls — already executed)

The earliest probe: a 2-call check for prompt-injection content in
`/weather` and `/research`. Outputs land alongside the script in
`initial_api_invocations/`.

```bash
python initial_api_invocations/probe_injection.py
```

### Structured /weather probe (32 calls + 8 cancellation calls)

```bash
python backend/probes/probe_weather.py
python backend/probes/probe_weather_cancellation.py
```

Outputs: `backend/outputs/probes/weather/` (`.raw` files + `weather_probe_log.jsonl` + `weather_cancel_log.jsonl`).

### Structured /research probe (27 calls + 10 cancellation calls)

```bash
python backend/probes/probe_research.py
python backend/probes/probe_research_cancellation.py
```

Outputs: `backend/outputs/probes/research/` (`.raw` files + `research_probe_log.jsonl` + `research_cancel_log.jsonl`).

## Where to find findings

Read the consolidated HTML reports in `probe_reports/` — one per API
endpoint, covering all quirks and cancellation behaviour. The raw
per-probe source reports are preserved in `probe_reports/_archive/`.

## Case studies

The `case_studies/` folder contains trace-driven debugging write-ups and
coverage audits:

- **Research hallucination** (`2026-05-18-research-api-hallucination.md` +
  `fix-round-*.md`): `/research` returns a generic template, LLM expands with
  its own knowledge. Fixed with grounding directive, refusal-as-valid-output,
  and GOOD/BAD few-shot example.
- **Probe-to-runtime coverage** (`2026-05-18-probe-findings-chat-app-coverage.md`):
  Cross-references all probe findings against the chat app implementation.
- **Resilience harness** (`2026-05-19-disciplined-resilience-harness-plan.md`):
  Policy document for bounded concurrency, proactive budget pacing, timeout
  retry, and config-driven resilience.
- **Post-harness reconciliation** (`2026-05-19-post-refactor-coverage-audit.md`):
  Final coverage audit after the resilience harness was implemented.

## Take-home phases

| Phase | What | Status | Where to read |
|---|---|---|---|
| 0. Setup | conda env, `.env`, `pip install -e .` | Done | this README |
| 1. Investigation | probe `/weather` + `/research`, document findings | Done | `probe_reports/*.html` |
| 2. Build | CLI streaming chat with tool calling | Done | `backend/chat/` |
| 3. Harden | add handling for confirmed quirks + fix research hallucination | Done | `backend/chat/parsers/`, `case_studies/` |
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
  A controlled probe confirmed they share a single server-side rate budget
  (see `probe_reports/shared_rate_limit_bucket_report.html`). The chat app
  uses one API-level `rate_limit` block with proactive budget pacing and
  bounded concurrency to stay within limits. **Cancelled calls still consume a slot.**
