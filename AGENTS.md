# Agent Instructions (Elyos Take-Home Repo)

## Non-negotiables

- Follow `north_stars.md` for coding constraints (simplicity, single
  responsibility, absolute imports, no pytest, conda-only, ~250 LOC target).
- Follow `backend/reference_docs/llm_rules.md` for any LLM calls. The take-home
  recommends the provider's official SDK directly; the LiteLLM helpers are
  available but optional.
- Allowed model names live in `backend/reference_docs/allowed_models.csv`.
- Project-specific context belongs in `project_context.md`. Do not infer
  missing assignment rules.
- This is a **CLI streaming-chat take-home**, not a voice product. Voice APIs
  (Deepgram, ElevenLabs, OpenAI Realtime) are explicitly out of scope for the
  take-home itself; they only matter for the on-site pair-programming session.
- **API key handling:** `.env` holds `ELYOS_API_KEY`. Always load via
  `python-dotenv`; never echo to stdout; never commit.
- **Untrusted API responses:** the recon at `/` already surfaced a planted
  prompt-injection payload. Defensive default: never pass raw tool-response
  bodies into LLM context without envelope/escape treatment.

## Agent Behaviour

- **Surface assumptions; don't silently pick.** If a request has more than
  one reasonable interpretation, name them and ask. If something is unclear,
  stop and ask. If a simpler approach exists, say so; push back when warranted.
- **Surgical edits only — touch only what you must; clean up only your own mess.**
  Every changed line must trace directly to the current request. Don't
  "improve" adjacent code, comments, or formatting. Don't refactor things
  that aren't broken. Match existing style even if you'd do it differently.
- **State success criteria up front for multi-step work.** Write a plain-python
  validator or a specific manual check, then loop until it passes.
- **Two workstreams, kept separate:** investigation (probe scripts → DISCOVERIES.md)
  and build (chat app). Investigation runs to completion before the build
  starts. Do not interleave.
