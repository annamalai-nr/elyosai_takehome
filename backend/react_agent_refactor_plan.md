# ReAct Agent Refactor Plan

## Overall Objective

Refactor the current chat implementation into a cleaner ReAct-style agent while preserving the existing behavior of the take-home application.

The goal is not to introduce LangGraph, LangChain, or a large framework. The goal is to make the current hand-rolled tool-calling loop easier to read, review, and explain by separating the major responsibilities that currently live together in `backend/chat/agent.py`.

After the refactor, `backend/chat/agent.py` should read like the ReAct algorithm:

1. Ask the LLM for the next assistant turn.
2. If the LLM returns a final answer, append it and stop.
3. If the LLM requests tools, append the assistant tool-call message.
4. Execute the requested tools.
5. Append tool observations.
6. Repeat until the final answer or `MAX_TOOL_ROUNDS`.

In other words, `agent.py` should orchestrate the Thought/Action/Observation loop, not contain all implementation details for LLM streaming, HTTP calls, parser normalization, and tool dispatch.

## Why This Refactor Is Worth Doing

The current implementation works, but `backend/chat/agent.py` has too many responsibilities:

- LiteLLM streaming
- LLM parameter construction
- streamed tool-call delta accumulation
- ReAct loop orchestration
- Elyos API HTTP requests
- timeout handling
- throttle retry handling
- tool dispatch
- JSON argument parsing
- parser invocation
- envelope wrapping
- CLI progress printing
- LangSmith tracing decorators

That makes the code harder to explain during review. The important agent behavior is present, but it is buried under transport, parsing, and tool plumbing.

The refactor should make the architecture easier to reason about without adding unnecessary indirection. A split is useful only if the new module has a clear conceptual responsibility. Avoid creating one-function files that merely force a reader to jump around.

The design target is:

- simple enough for a take-home assignment;
- explicit enough to demonstrate agent control flow;
- faithful to the probe-driven quirks already discovered;
- easy to validate with the existing `--validate` path and CLI smoke tests.

## What To Retain From The Existing Codebase

Keep the existing modules that already have clear responsibility.

Do not move or rewrite these unless an import path must be updated:

- `backend/chat/prompts.py`
  - Keep the system prompt here.
  - Do not change the prompt text as part of this refactor.

- `backend/chat/parsers/`
  - Keep API response normalization in the existing parsers package.
  - Preserve the cleaner API-specific split, such as weather and research parser modules.
  - Keep the public parser imports available through `backend/chat/parsers/__init__.py`,
    for example `normalise_weather`, `parse_research`, and `envelope`.
  - Do not change parser semantics.

- `backend/chat/models.py`
  - Keep Pydantic models here.
  - Do not change field names or model behavior.

- `backend/chat/load_config.py`
  - Keep config loading and model/provider validation here.
  - Do not change config semantics.

- `backend/chat/paths.py`
  - Keep centralized package path constants here if this file is already restored.
  - `load_config.py` may continue importing from it.

- `backend/chat/interfaces/cli_chat.py`
  - Keep the interactive REPL and SIGINT handling here.
  - Do not change cancellation behavior unless required by imports.

- `backend/chat/validate.py`
  - Keep validator fixtures here.
  - Do not weaken or remove existing validations.

- `backend/chat/__main__.py`
  - Keep the argparse entrypoint here.
  - Preserve `--validate`.
  - Unknown arguments should continue to raise argparse errors.

- `backend/chat/tools/`
  - Keep `TOOLS` in `tools/schemas.py`.
  - Keep tool execution dispatch in `tools/dispatch.py`.
  - Keep raw Elyos HTTP client in `tools/elyos_client.py`.
  - `tools/__init__.py` re-exports `TOOLS` and `execute_tool_call`.
  - Keep the improved `research_topic` tool description:
    `"Look up a best-effort research summary. May return generic, cached, truncated, or timeout results."`

Also retain:

- LiteLLM as the LLM invocation layer.
- LangSmith tracing behavior as currently implemented.
- The OpenAI/LiteLLM tool-call protocol:
  - assistant message with `tool_calls`;
  - subsequent `role: "tool"` messages with matching `tool_call_id`.

## What To Change

### 1. Make `backend/chat/agent.py` orchestration-only

`agent.py` should own the ReAct loop and message sequencing.

It should keep:

- `MAX_TOOL_ROUNDS`
- `stream_turn(...)`
- the loop that decides whether to stop or execute tools
- appending assistant messages
- appending tool observation messages
- max-round logging

It should not own:

- raw LiteLLM streaming details
- streamed tool-call delta accumulation
- parser internals
- individual tool implementations

The final shape should be close to this:

```python
async def stream_turn(client, cfg, messages, state) -> None:
    for _ in range(MAX_TOOL_ROUNDS):
        turn = await stream_llm_turn(cfg, messages, state)
        messages.append(turn.assistant_message)

        if not turn.tool_calls:
            state["partial"] = ""
            return

        for tool_call in turn.tool_calls:
            observation = await execute_tool_call(client, cfg, tool_call)
            messages.append(observation)

    log.warning("Max tool rounds (%d) reached", MAX_TOOL_ROUNDS)
```

This makes the ReAct flow visible:

- LLM turn;
- optional action;
- tool observation;
- repeat.

### 2. Add `backend/chat/llm_client.py`

Purpose: LiteLLM streaming adapter.

Move the LLM-specific implementation details here.

This module should own:

- `litellm.acompletion(...)`
- LiteLLM logging suppression if still needed
- `_llm_kwargs(...)`
- streaming content chunks to stdout
- updating `state["partial"]`
- accumulating streamed tool-call deltas
- returning a structured representation of one LLM turn

Use small Pydantic models, not dataclasses. This project rule matters: do not introduce `@dataclass`.

The model classes can live in `backend/chat/models.py` if that keeps the package simpler.
If you prefer an LLM-specific module, keep it minimal and import from it intentionally.

```python
from pydantic import BaseModel

class ToolCall(BaseModel):
    id: str
    name: str
    arguments: str

class LLMTurn(BaseModel):
    content: str
    tool_calls: list[ToolCall]

    @property
    def assistant_message(self) -> dict:
        if not self.tool_calls:
            return {"role": "assistant", "content": self.content}

        return {
            "role": "assistant",
            "content": self.content or None,
            "tool_calls": [
                {
                    "id": call.id,
                    "type": "function",
                    "function": {
                        "name": call.name,
                        "arguments": call.arguments,
                    },
                }
                for call in self.tool_calls
            ],
        }
```

The function exported from this module should be something like:

```python
async def stream_llm_turn(cfg: dict, messages: list[dict], state: dict) -> LLMTurn:
    ...
```

`agent.py` should not need to know how streamed tool-call deltas are assembled.

### 3. Split `backend/chat/tools/` into schemas, dispatch, and client

The `tools/` package has three modules:

- `tools/schemas.py`: LLM tool JSON schemas only (`TOOLS`). No runtime imports.
- `tools/elyos_client.py`: raw Elyos HTTP client (`call_api`), throttle retry, timeout handling. No knowledge of tool-call protocol or parsers.
- `tools/dispatch.py`: tool execution dispatch (`execute_tool_call`). Parses tool-call arguments, calls `elyos_client.call_api`, normalizes with parsers, wraps in envelope, returns `{"role": "tool", ...}` messages.
- `tools/__init__.py`: re-exports `TOOLS` and `execute_tool_call`.

Recommended output shape from tool execution:

```python
async def execute_tool_call(client, cfg, call: ToolCall) -> dict:
    ...
    return {
        "role": "tool",
        "tool_call_id": call.id,
        "content": envelope(...),
    }
```

This keeps `agent.py` free from tool-specific details.

Keep these tracing decorators:

```python
@traceable(run_type="tool", name="execute_tool")      # dispatch.py
@traceable(run_type="tool", name="elyos_api_call")    # elyos_client.py
```

## Expected Final Module Responsibilities

After the refactor, the package should be easy to explain:

```text
backend/chat/
  __main__.py        argparse entrypoint
  config.yaml        package-specific runtime config
  paths.py           package path constants
  load_config.py     config loading and provider/env validation
  prompts.py         system prompt
  models.py          Pydantic models
  parsers/           weather/research normalization + untrusted envelope
  llm_client.py      LiteLLM streaming adapter
  tools.py           tool schemas + tool execution + Elyos API calls
  agent.py           ReAct loop orchestration
  validate.py        parser/envelope fixtures
  interfaces/
    cli_chat.py      REPL and SIGINT handling
```

This split is elegant because each file now answers one question:

- `agent.py`: What is the agent loop?
- `llm_client.py`: How do we stream from the model?
- `tools.py`: How do tool calls become Elyos API observations?
- `parsers/`: How do raw API quirks become normalized data?
- `paths.py`: Where are package-level paths defined?

## Behavioral Requirements

The refactor should preserve these behaviors:

- `python -m backend.chat` launches the chat.
- `python -m backend.chat --validate` runs validators.
- Unsupported CLI arguments are rejected by argparse.
- Weather requests call the weather endpoint.
- Research requests call the research endpoint.
- Tool output is wrapped in the untrusted JSON envelope.
- Weather single-observation and multi-observation schemas still parse.
- Weather requested/returned location mismatch remains available to the LLM.
- Research cached/truncated/timeout cases still normalize correctly.
- The app does not manufacture stale dates.
- Generic research summaries remain guarded by the existing prompt.
- Multi-tool turns continue to work.
- `MAX_TOOL_ROUNDS` still prevents infinite tool loops.
- Ctrl+C cancellation behavior remains owned by the CLI and should not regress.

## Validation Commands

Run:

```bash
/Users/annamalainarayanan/anaconda3/envs/elyosai/bin/python -m backend.chat --validate
```

Expected:

```text
All 9 validations passed.
```

Run:

```bash
/Users/annamalainarayanan/anaconda3/envs/elyosai/bin/python -m compileall backend/chat
```

Expected: clean compile.

Run:

```bash
/Users/annamalainarayanan/anaconda3/envs/elyosai/bin/python -m backend.chat --bad-arg
```

Expected: argparse rejects the argument and exits with code `2`.

Run a CLI weather smoke test:

```bash
printf "what's the weather in London?\nquit\n" | /Users/annamalainarayanan/anaconda3/envs/elyosai/bin/python -m backend.chat
```

Expected:

- chat starts;
- model calls the weather tool;
- CLI shows the weather pending message;
- assistant returns a weather answer;
- app exits on `quit`.

## Review Checklist

Before reporting the refactor as complete, confirm:

- `agent.py` contains the ReAct loop but not HTTP details.
- `llm_client.py` contains LiteLLM streaming details.
- `tools.py` contains `TOOLS`, tool execution dispatch, and raw Elyos API request/retry logic.
- The `parsers/` package, `models.py`, `prompts.py`, `load_config.py`, `paths.py`, `validate.py`, and `cli_chat.py` retain their current responsibilities.
- No imports remain from `backend.chat.core.*`.
- No imports remain from `backend.chat.interfaces.validate`.
- README architecture tree is updated if needed.
- New files are not left untracked by accident.

## Important Non-Goals

Do not:

- introduce LangGraph or LangChain;
- rewrite the system prompt;
- change parser behavior;
- change config behavior;
- remove LangSmith tracing;
- add a new UI;
- add voice functionality;
- rewrite validators into pytest;
- perform unrelated cleanup;
- commit or push.

This should be a focused architecture refactor that makes the current working app easier to explain as a ReAct-style agent while keeping the behavior equivalent.
