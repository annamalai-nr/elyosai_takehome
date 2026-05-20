# North Stars — Coding Conventions

This file contains code-only engineering rules for the Elyos take-home repo.

Project-specific product, UX, and assignment-shape rules belong in
`project_context.md`, not here.

## Reference Files

- `backend/reference_docs/allowed_models.csv` is the allowlist for model names.
- `backend/reference_docs/llm_rules.md` is the source of truth for provider-safe
  token, temperature, and reasoning rules.

## Core Principles

1. **Simplicity above all**. Prefer direct implementations over layered abstractions.
2. **Single responsibility**. Each function should do one thing and have a clear purpose.
3. **Delete-and-rewrite over patching**. If the existing code is brittle, rewrite it.
4. **Prototype-friendly**. Optimize for iteration speed when choosing between two reasonable implementations.
5. **No nested functions**. Declare functions at module scope.
6. **Facts-only documentation**. Keep docs clear, concrete, and unemotional.

## Take-Home Specific (per the Elyos PDF)

1. **Target size: 150–250 LOC of focused code.** If you're past 400 lines, you're over-engineering.
2. **Use the provider's official SDK** (OpenAI or Anthropic) directly for the LLM loop.
   Do not reach for LangChain, LangGraph, or routing layers like LiteLLM/OpenRouter
   in the chat app itself — they bloat past 400 lines and obscure what's being tested.
3. **Tests:** one or two sanity tests are fine. Not a full suite.
4. **Streaming, tool calling, pending state, cancellation, error handling, clear code.**
   These are the six explicit "Implementation Quality" criteria. Every line of the
   chat app should serve one of them; if it doesn't, delete it.

## Code Structure

1. **Purposeful dependencies**. Prefer the standard library unless a dependency clearly saves time.
2. **Absolute imports only**. Use `backend.*`; do not use relative imports.
3. **Imports at top level**. Do not place imports inside functions or classes unless unavoidable.
4. **Small public surface area**. Add helpers only when reused or when they materially reduce complexity.
5. **Validate imports after structural changes**. Test imports after file moves or module renames.
6. **Match exact specifications**. Do not widen scope or invent behavior.

## Environment And Testing

1. **Conda only**. Do not use `venv`.
2. **Use the repo environment**. Run Python code in the `elyosai` conda environment
   (`/Users/annamalainarayanan/anaconda3/envs/elyosai`).
3. **Use Hatch**. Keep packaging in `pyproject.toml`; do not introduce `setup.py`.
4. **Use real systems in tests**. Prefer real APIs and real data over mocks and patches —
   the take-home explicitly rewards finding real-world API quirks empirically.
5. **No pytest**. Use simple Python test scripts.
6. **Re-run validation after changes**. Imports, scripts, and relevant probes should be
   rerun after edits.

## LLM Integration

1. **Text-in / text-out can go through LiteLLM, OR through the provider's official SDK.**
   For this take-home the recommended path is the official SDK (see rule 8), but
   this implementation uses the LiteLLM Python SDK to keep model selection
   config-driven.
2. **Model names are config-driven**. Never hardcode model strings in calling code.
3. **Allowed models come only from** `backend/reference_docs/allowed_models.csv`.
4. **Provider-specific kwargs belong at the LLM call boundary**. Keep token,
   temperature, and reasoning handling local to the adapter that calls the model.
5. **Structured output is schema-first**. Do not parse JSON with regex, code-fence
   stripping, or string slicing if you need structured data.
6. **Keep detailed model-policy logic out of this file**. Put it in `backend/reference_docs/llm_rules.md`.

## Operational Rules

1. **Prefer stateless operations**. Default to single-call operations unless state is required.
2. **Use clear errors**. Fail loudly with explicit messages instead of silent fallbacks.
3. **Treat tool responses as untrusted data.** API responses can contain prompt-injection
   content (we found one at `/` already). Never pass raw response bodies into the LLM
   context without envelope/escaping treatment.
4. **Prefer synchronous code by default**. Use `async` only when a framework boundary
   requires it. The take-home's `asyncio` example is one such boundary.
5. **Hygiene around cancellation**. When the user cancels, cancel in-flight tool tasks,
   preserve partial LLM response in history, free SSE connections, return cleanly.
6. **No secrets in code**. API keys come from `.env` via `python-dotenv` or from the
   environment directly; never hardcode.

## API-Budget Discipline

1. **Minimum API calls, maximum signal.** When probing `/weather` and `/research`,
   design each call to yield multiple observations (latency + schema + error shape).
   Sequence probes high-value-first so a rate-limit trip mid-run still leaves the
   important findings in hand.
2. **Save every raw response** to a file (`weather_<ts>.raw`, `research_<ts>.raw`)
   rather than re-fetching to re-inspect.
