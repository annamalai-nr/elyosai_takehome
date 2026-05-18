# Fix Round 1: Constraint Sentence

Companion to [2026-05-18-research-api-hallucination.md](2026-05-18-research-api-hallucination.md).

---

## What was applied

A constraint sentence was added to `SYSTEM_PROMPT` in `backend/chat/prompts.py`:

> "When using research_topic, your response must be based ONLY on the 'summary' and 'sources' fields returned in the tool result. Do not supplement with information from your own knowledge. If the summary is brief or generic, say so plainly to the user — do not expand it."

The applying session also restructured the prompt into markdown sections (exact diff not captured).

---

## Result: FAILED

The model still hallucinated. Test:

```
python -m backend.chat
> research solar energy briefly
```

Model's response:

> "Solar energy is a major renewable energy source... Recent research focuses on improving solar cell efficiency, lowering manufacturing costs, and integrating solar power into grids and storage systems. Key areas include **perovskite solar cells, tandem cell designs, and better battery pairing for intermittent generation.**"

The specifics (perovskite cells, tandem designs, battery pairing) are not present in the tool result.

---

## Why it failed

This is a well-studied problem in ReAct agent design. An abstract constraint sentence competes with the model's training to be helpful — and training wins. Three specific deficiencies:

1. **No grounding directive.** The prompt never told the model its role is to present tool results faithfully, not to contribute its own knowledge. Without this framing, the model defaults to "be maximally helpful."

2. **No refusal-as-valid-output.** The prompt never gave the model explicit permission to say "the API didn't return enough detail." Without that permission, the model fills gaps rather than acknowledging them.

3. **No concrete example.** The model had no demonstrated pattern of what a correct faithful response looks like for a thin tool result. Abstract rules without examples are weak constraints.

---

## References

- [OpenAI: Developing Hallucination Guardrails](https://developers.openai.com/cookbook/examples/developing_hallucination_guardrails)
- [AWS: Stop AI Agent Hallucinations — 4 Essential Techniques](https://dev.to/aws/stop-ai-agent-hallucinations-4-essential-techniques-2i94)
- [arxiv: Reducing Tool Hallucination via Reliability Alignment](https://arxiv.org/html/2412.04141v1)
