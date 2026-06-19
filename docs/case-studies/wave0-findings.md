# Wave 0 — Findings & Model Gate

*Spike: de-risk the load-bearing model bet · 2026-06-18*
*Environment: free Google Colab T4 (Turing, ~15 GB, no bf16) · Unsloth 2026.6.7 · Transformers 5.x (record exact patch on first run) · greedy decoding · n = 1 fixture (`bad_deploy_0001`)*

---

## Conclusion (the gate decision)

**Default reasoner for v1 = Qwen3-4B.** On a single hand-built bad-deploy incident, a 4B-class model is adequate for the orchestration this project depends on — both Qwen3-4B and Qwen3.5-4B drove the 3-step tool-calling loop, used the tool results, ranked the bad deploy as cause #1, and cited only real evidence, matching the Gemini free-tier reference. The deciding factor was **free-hardware economics, not capability**: on the only available free GPU (Colab T4 / Turing, no bf16), Qwen3.5-4B runs in **fp32 with a torch fallback** for its GDN/Mamba layers — reproduced in Unsloth's own official notebook, so it is a property of the build/hardware, not our code — taking **54.3s vs Qwen3-4B's 19.6s** for the same loop (~2.7× slower). Qwen3-4B also passed the **load-bearing fine-tune smoke test** on the same T4 (4-bit QLoRA, loss 0.41 → 0.05 over 30 steps, ~8.5 s/step, f16 GGUF export OK); Qwen3.5-4B's fine-tune was not measured. Qwen3.5-4B is retained as an inference-only option; **Qwen3-8B** is the escalation if a 4B proves too weak on later failure classes. Full record: **DR-0008**.

---

## Setup

- **Fixture:** `bad_deploy_0001` — one hand-authored bad-deploy incident (canned structured logs + git/deploy history + a labelled gold cause and gold evidence). Graduates to `evals/scenarios/fixtures/bad_deploy_0001.json`.
- **Loop:** a minimal model-agnostic JSON-action ReAct loop over two canned tools (`query_logs`, `get_recent_commits`), identical across model families.
- **Candidates:** Qwen3.5-4B (`unsloth/Qwen3.5-4B`, bf16-LoRA family, VLM) and Qwen3-4B (`unsloth/Qwen3-4B`, mature 4-bit QLoRA, dense).
- **Reference:** Gemini free tier (one-shot, raw evidence, no loop) — quality bar and the project's later verifier model.

---

## Results

| Criterion | Qwen3.5-4B | Qwen3-4B | Gemini ref |
|---|---|---|---|
| Called right tool(s) | ✅ | ✅ | n/a (one-shot) |
| Used tool results | ✅ | ✅ | n/a |
| Deploy ranked cause #1 | ✅ | ✅ | ✅ |
| Evidence all real (no fabrication) | ✅ | ✅ | ✅ |
| Loop steps to answer | 3 | 3 | n/a |
| Inference wall-clock (full loop) | 54.3s (fp32 + torch fallback) | **19.6s** | n/a |
| Fine-tune ran on free T4 | **not measured** | ✅ (4-bit QLoRA) | n/a |
| Loss dropped over 30 steps | not measured | ✅ (0.41 → 0.05) | n/a |
| Fine-tune seconds/step | not measured | ~8.5 s/step (255s total) | n/a |
| GGUF export OK | untested | ✅ (f16) | n/a |

---

## What the results mean

- **Capability is a tie at n=1.** Both 4B models diagnosed correctly and stayed grounded. Qwen3.5-4B was marginally sharper in phrasing — not enough to outweigh the hardware cost.
- **The split is hardware, not intelligence.** Qwen3.5's GDN/Mamba layers have no fast kernel on Turing in the current Unsloth build, forcing fp32 + a torch fallback. This is why it's ~2.7× slower and why the cost thesis — which depends on running *cheaply on free hardware* — favours Qwen3-4B.
- **Qwen3-4B is the only candidate proven end-to-end on free hardware**: capable + trains + exports. That is the whole point of Wave 0.

---

## Gate decision (tree applied)

- Qwen3-4B tool-use adequate **and** fine-tune ran acceptably on free T4 → **default = Qwen3-4B.** ✅ (this branch)
- ~~Qwen3.5-4B adequate but fine-tune flaky/slow → default = Qwen3-4B, keep 3.5 inference-only~~ (also points to Qwen3-4B)
- ~~Both 4B weak → escalate to Qwen3-8B~~ (not triggered)

Recorded in **DR-0008** (supersedes DR-0007). DR-0008 status: Accepted (firm) on building v1 on Qwen3-4B.

---

## What Wave 0 did *not* prove (carry-forward)

- **Capability is n=1** — one bad-deploy fixture. Re-confirm on config/env and resource-exhaustion classes in **Wave 3**.
- **Abstention / "insufficient evidence" was never exercised** — the headline reliability guarantee is still unproven. **Wave 2.**
- **Fine-tune *quality* is unproven** — the smoke test trained on ~12 near-identical rows (memorisation). Real data + a separate-distribution holdout is **Wave 4**.
- **Fabrication check needs fuzzy/structured matching** — both models cited evidence as *paraphrases* of the gold rows, not verbatim strings. A pure exact-string check won't hold; design the Wave 1 diagnosis schema so evidence carries **structured handles** (log-row id, commit SHA) the model echoes, with the prose description separate. **Wave 1 schema → Wave 2 check.**
- **Qwen3.5-4B's free-hardware fine-tune speed is unmeasured** — the decision rests on Qwen3-4B's proven superiority, not a measured 3.5 failure. Measure sec/step before ever reconsidering 3.5.
