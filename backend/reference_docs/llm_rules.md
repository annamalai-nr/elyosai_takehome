# LLM and Voice Model Rules — Elyos Take-Home (ported from Eugenix CP2)

This file is ported from `eugenix_cp2/backend/reference_docs/llm_rules.md`.
It documents the LiteLLM / ChatLiteLLM kwargs rules used by
`backend/llm_utils/litellm_kwargs.py`.

The Elyos take-home allows OpenAI, Anthropic, or similar. The original prompt
recommends official SDKs, but `backend/chat/` deliberately uses the LiteLLM
Python SDK for text LLM calls to support provider switching. Voice/realtime
models remain out of scope for the take-home.

## Source of truth

- Allowed model names: `backend/reference_docs/allowed_models.csv`.
- Text-model parameter support: LiteLLM docs (`https://docs.litellm.ai/docs/completion/input`).
- OpenAI Realtime API docs for `gpt-realtime-1.5` and `gpt-4o-transcribe`.
- Gemini Live API docs for `gemini-3.1-flash-live-preview`.
- ElevenLabs SDK docs for TTS and STT.

---

## Models covered by this doc

**Text models** (LiteLLM / ChatLiteLLM rules apply):
`gpt-5.4`, `gpt-5.4-pro`, `gpt-5.4-mini`, `gpt-5.5`, `gpt-5.5-pro`,
`anthropic/claude-opus-4-7`, `anthropic/claude-opus-4-6`, `anthropic/claude-sonnet-4-6`, `anthropic/claude-haiku-4-5-20251001`,
`gemini/gemini-3.1-pro-preview`, `gemini/gemini-3.1-flash-preview`, `gemini/gemini-3.1-flash-lite-preview`.

**OpenAI Realtime** (native WebSocket SDK; NOT covered by LiteLLM text rules):
`gpt-realtime-1.5` — bidirectional audio streaming, best quality.

**OpenAI STT** (native OpenAI SDK; NOT covered by LiteLLM text rules):
`gpt-4o-transcribe` — highest-accuracy batch transcription.
`gpt-4o-transcribe-diarize` — use when speaker diarization is required.

**Gemini Realtime** (native Google Gen AI SDK; NOT covered by LiteLLM text rules):
`gemini-3.1-flash-live-preview` — latest Gemini Live API model, bidirectional audio.

**Gemini TTS** (native Google Gen AI SDK; NOT covered by LiteLLM text rules):
`gemini-3.1-flash-tts-preview` — latest Gemini TTS preview model.

**ElevenLabs TTS** (native ElevenLabs SDK; NOT covered by LiteLLM text rules):
`eleven_v3` — highest quality, 70+ languages, best for pre-generated audio.
`eleven_flash_v2_5` — ultra-low latency (<75 ms), 32 languages, best for real-time streaming.

**ElevenLabs STT** (native ElevenLabs SDK; NOT covered by LiteLLM text rules):
`scribe_v2` — batch transcription, 90+ languages, speaker diarization, word-level timestamps.
`scribe_v2_realtime` — streaming transcription, ~150 ms latency.

---

## Take-home specific notes

- The **take-home CLI chat application** (`backend/chat/`) uses the LiteLLM
  Python SDK for text LLM calls, supporting OpenAI and Anthropic models.
  Config lives at `backend/chat/config.yaml`; `drop_params=True` is used so
  provider-unsupported params are silently dropped.
- For the **on-site pair-programming session**, audio I/O is added via
  Deepgram (STT) and ElevenLabs (TTS). The native-SDK rules above apply.

---

## Config contract (for `backend/chat/config.yaml`)

**Text LLM (default):**
- `llm.model_name` (must be in `allowed_models.csv` with `type=text`)
- `llm.max_tokens`
- `llm.temperature`
- `llm.reasoning_effort`

The take-home's chat app config lives at `backend/chat/config.yaml` (package-owned).
This single text-model config block is all that's in scope here. The
ticket/chat-service-specific blocks from Eugenix CP2 are not in scope.

---

## Text LLM rules (LiteLLM / ChatLiteLLM)

### Token caps

- GPT-5.4 and GPT-5.5 family: send `max_completion_tokens` (includes reasoning tokens).
- All other text models: send `max_tokens`.

### Temperature rules

- **Gemini text models**: keep `temperature = 1.0`. Setting lower can cause degraded performance.
- **OpenAI GPT-5.4 / GPT-5.5 family**: `temperature` only supported when `reasoning_effort = none`.
- **Anthropic Claude (Opus 4.6, Sonnet 4.6, Haiku 4.5)**: `temperature = 0.0` for deterministic
  classification and structured outputs; `temperature = 0.7` for conversational turns.
- **Anthropic Claude Opus 4.7**: omit sampling parameters unless provider docs explicitly support them.

### Reasoning / effort knob

- OpenAI GPT-5.4/5.5: passed as `reasoning_effort` (`none`, `low`, `medium`, `high`, `xhigh`).
- Gemini text models: LiteLLM maps to Gemini thinking controls.
- Anthropic: LiteLLM maps to Claude thinking budgets.

---

## Implementation checklist

- Read all model and voice settings from `backend/chat/config.yaml`.
- Keep code-level config normalised and translate to provider-correct kwargs at the call boundary.
- Prefer `drop_params=True` per LiteLLM call (text models only).
- If you add/remove models: update `allowed_models.csv` and keep this file in sync.

## Scope Boundary

- This file covers LLM and voice invocation mechanics only.
- Product and assignment constraints belong in `project_context.md`.
