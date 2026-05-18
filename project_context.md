# Project Context — Elyos Take-Home

This file is for take-home–specific product, scope, and assignment constraints.

Do not infer missing rules from code structure alone. Add entries below only
when they cite either a primary source (the take-home PDF, the Elyos website,
or the recon findings) or a dated user instruction.

## Primary Sources

- The take-home PDF (`Elyos Interview 2.0.pdf`) — the only formal documentation
  of `/weather` and `/research`. Per the PDF: *"This is the complete official
  documentation. Any other behaviors you observe are part of the challenge."*
- `elyos_api_recon_findings.html` — unauthenticated reconnaissance of the host,
  documenting what's actually exposed beyond the PDF.
- `api_quirks_research_v3.html` — the hypothesis-driven probe checklist.
- `elyos_research_report.html` — broader research on Elyos as a company.
- Direct user instructions during the session (cited inline by date).

## Current Policy

- This file avoids restating unverified assumptions.
- When a project rule is added, cite either a primary source or a dated user
  instruction.

---

## Assignment Shape

**Submission requires:**
1. Link to code (GitHub repo, zip, or similar).
2. Link to Loom video (10–15 minutes).
3. AI-assistant session transcript (Claude Code / Cursor / Copilot `/export`).

**Build target:**

A command-line chat application that:
1. Accepts text input from the user.
2. Sends input to an LLM (OpenAI / Anthropic / similar).
3. Streams the response back to the terminal in real time.
4. Supports tool calling with two APIs: `/weather` (fast, ~200 ms) and `/research` (slow, 3–8 s).
5. Shows pending state while a slow tool is in flight.
6. Supports cancellation (Ctrl+C) of long-running operations.
7. Handles APIs gracefully — they have planted quirks.

**Target code size:** 150–250 LOC. Past 400 = over-engineering.

*Source: take-home PDF.*

---

## The Two APIs

| Endpoint | Method | Query param | Latency | Auth |
|---|---|---|---|---|
| `/weather` | GET | `location` (string) | ~200 ms | `X-API-Key` header |
| `/research` | GET | `topic` (string) | 3–8 s | `X-API-Key` header |

Base URL: `https://elyos-interview-907656039105.europe-west2.run.app`.

API key for this candidate: stored in `.env` as `ELYOS_API_KEY` (see `.env`).

*Source: take-home PDF; user instruction 2026-05-16.*

---

## Known Recon Findings (before any authenticated probing)

These came from 11 unauthenticated GETs against the host (zero budget spent):

1. **Prompt injection planted at `/`.** An HTML comment in the root response
   contains instructions targeting LLMs. Treat this as evidence that Elyos
   cares about untrusted-content handling. Defensive default: never pass raw
   API response bodies into LLM context without envelope/escape treatment.
2. **`/health` is undocumented but live.** Returns `{"status":"healthy"}`.
   Proves "complete official documentation" is narrative, not literal.
3. **OpenAPI / Swagger / ReDoc intentionally disabled.** All three FastAPI
   doc surfaces return 404. Empirical probing is the intended path.
4. **Stack confirmed:** FastAPI on Google Cloud Run, region `europe-west2`,
   HTTP/2 with HTTP/3 advertised.

*Source: `elyos_api_recon_findings.html`, 2026-05-16.*

---

## Investigation vs. Build (Workstream Separation)

The take-home conflates two concerns that should be tackled separately:

- **Investigation** — find quirks in `/weather` and `/research` via standalone
  probe scripts. Output: `DISCOVERIES.md` with confirmed observations.
  Tool: `initial_api_invocations/probe_injection.py` and any follow-on probe
  scripts. This wins the "API Discovery & Handling" evaluation criterion.
- **Build** — the chat application itself. Uses the same APIs but only needs
  to handle a realistic subset of discovered quirks. Graded on streaming +
  tool calling + cancellation + pending state + error handling + code clarity.

Do not interleave. Investigate first, then build with informed handling.

*Source: user instruction 2026-05-16.*

---

## Evaluation Criteria (verbatim from the PDF)

1. **Implementation Quality** — streaming works, both tool calls work, pending
   state during slow ops, cancellation actually cancels, errors handled
   gracefully, code clear and maintainable.
2. **API Discovery & Handling** — found unexpected behaviours, handled them
   gracefully, can explain what was discovered and why. The PDF says this
   section is *particularly important*.
3. **Communication** — Loom video clear and organised, trade-offs discussed,
   weaknesses acknowledged honestly.

---

## What This Repo Does NOT Cover

- **Voice (Deepgram / ElevenLabs / OpenAI Realtime).** Mentioned in the PDF
  only as "familiarize yourself" for the on-site, no implementation needed
  for the take-home.
- **CRM/FSM integrations** (Simpro / JobLogic / etc.). Not part of the
  take-home; relevant only as Elyos product context.
- **Telephony, websockets, audio streaming.** Pure CLI exercise.
- **Tests beyond one or two sanity checks.** The PDF says no full test suite.
- **Fancy UI.** Plain CLI is the deliverable.

---

## Build Phasing

- **Phase 0 — Setup** (10 min): conda env, repo init, `.env`, `pip install -e .`
- **Phase 1 — Investigation** (60–90 min): probe `/weather` and `/research`
  thoroughly, log to `DISCOVERIES.md`. Already partially done (recon at `/`
  and infrastructure paths covered).
- **Phase 2 — Build** (60–90 min): the streaming CLI in the chat app shape
  given by the take-home's starter template. Target 150–250 LOC.
- **Phase 3 — Harden** (30 min): add deliberate handling for the realistic
  subset of discovered quirks.
- **Phase 4 — Loom** (20 min): demo (3–4) → API discovery (3–4) → code
  walkthrough (3–4) → trade-offs (2–3) → self-critique (1–2).
- **Phase 5 — Submit** (10 min): GitHub link + Loom link + AI session export.

*Source: take-home PDF; user-validated 2026-05-16.*
