# DR-0007: Model selection — Qwen3.5-4B default, Qwen3-4B fine-tune fallback, Qwen3-8B as the bigger free-trainable candidate

**Status:** Accepted (provisional) · **Date:** 2026-06-18 · **Decided by:** Rajeev (with Claude as thinking partner)
**Supersedes:** DR-0002 (set DR-0002 → Superseded) · **Revisit at:** Wave 0 gate; Wave 4 results

## Context

DR-0002 named "Qwen3.5 4B" as the default reasoner and "Qwen3.5 9B" as the escalation if 4B proved too weak, with fine-tuning split between a local QLoRA proof-of-concept and cloud training. Two facts surfaced by research on 2026-06-18 invalidate parts of that plan:

1. **Qwen3.5 turned out to be a different kind of model than DR-0002 assumed.** It is not a plain dense text transformer. The Qwen3.5 family uses **Gated DeltaNet (GDN) hybrid attention** (GDN in ~75% of layers) combined with **sparse MoE**, and it is a **unified vision-language model (VLM)**. Native context is 262K. (Sources: Qwen3.5 Hugging Face model cards; QwenLM GitHub; Spheron deployment guide.)
2. **On free notebook GPUs — the only training hardware available in this working context — the 9B is not fine-tunable.** Unsloth's published LoRA VRAM figures for Qwen3.5: 4B ≈ 10 GB (bf16 LoRA), **9B ≈ 22 GB**. A free Colab/Kaggle T4 has ~15–16 GB. So Qwen3.5-9B needs an A100 / paid GPU to fine-tune, which conflicts with the no-paid-services constraint. Only the 4B tier (and dense models up to ~8–14B) fits free GPUs.

Both Qwen3.5 and Qwen3 open-weight models are **Apache-2.0** (confirmed via QwenLM GitHub) — clean for an MIT project, so DR-0002's licence rationale still holds.

## Decision

Default reasoner = **Qwen3.5-4B** (`Qwen/Qwen3.5-4B`; 4-bit/loader repo `unsloth/Qwen3.5-4B`). Carry **Qwen3-4B** (`Qwen/Qwen3-4B`) as a fine-tune-safety fallback. Re-spec the "bigger model" escalation path from Qwen3.5-9B to **Qwen3-8B** (`Qwen/Qwen3-8B`) — a dense, free-trainable model. The Wave 0 spike decides between these on capability **and** free-GPU trainability.

## Alternatives Considered

- **Keep Qwen3.5-9B as the escalation (DR-0002's plan)** — rejected: 22 GB LoRA VRAM is not free-GPU-trainable. Reachable only with a paid cloud GPU, which is out of scope unless explicitly funded.
- **Qwen3.5-4B only, no fallback** — rejected as too risky for the cost thesis: Qwen3.5 uses custom Mamba/GDN Triton kernels (Unsloth notes training is slower than usual) and is a younger fine-tuning target. If that path is flaky or too slow on a free T4, the headline cost/quality result stalls with no Plan B.
- **Qwen3-4B as the default (skip 3.5 entirely)** — rejected as the *default*, kept as the *fallback*: 3.5 is newer and stronger and has an official free Colab fine-tune notebook, so it deserves first shot. But 3.5's GDN+VLM nature is the unproven part, so a mature dense fallback is prudent.
- **Gemma / Mistral small** — unchanged from DR-0002: Gemma's non-Apache licence and Mistral kept only as a distant fallback. No reason to switch families now that two Apache-2.0 Qwen options cover both the "newest" and "safe" roles.

## Consequences

**Good:**
- Both default and fallback are Apache-2.0 4B-class models that fine-tune on free Colab/Kaggle — the cost thesis stays runnable with zero paid compute.
- Qwen3.5-4B brings 262K native context (useful for large log/metric dumps), strong tool-calling (`qwen3_coder` tool-call parser, MCP-friendly), and toggleable thinking mode.
- A dense fallback (Qwen3-4B) de-risks the single most fragile part of the plan — the fine-tune — without abandoning the stronger model for inference.

**Trade-offs:**
- Qwen3.5 fine-tunes via **bf16/16-bit LoRA**, not 4-bit QLoRA (Unsloth's recommended path for this family). The brief's "QLoRA" language needs updating, and the cleanest true-4-bit cost story actually lives with the Qwen3-4B fallback.
- Qwen3.5 is a VLM carrying vision weights we never use; serve and train **text-only** (`--language-model-only` on vLLM; text-only SFT recipe in Unsloth).
- Maintaining two candidate models through Wave 0 is slightly more spike work.

**Watch out for:**
- **Free-GPU trainability is now an explicit Wave 0 gate criterion, not an afterthought.** The capability question ("can a 4B orchestrate the loop?") is low-risk for these models; the real load-bearing bet is "does a LoRA fine-tune actually run on a free T4 for this exact architecture, at acceptable speed?" Wave 0 must smoke-test the fine-tune, not just the agent loop.
- If Qwen3.5-4B's tool-use is adequate but its fine-tune is flaky/too slow on free T4 → ship the default as Qwen3-4B and keep Qwen3.5-4B as an inference-only option.
- If 4B tool-use is weak across both families → escalate the reasoner to **Qwen3-8B** (free-trainable dense), **not** Qwen3.5-9B. Only reach for paid cloud + a 9B if a deliberate decision to spend is made (would supersede this record).
- Verify exact model IDs and the current Unsloth version on first notebook run; Qwen3.5 needs the latest Transformers (v5) and Unsloth — a "model class not found" error means update Unsloth (or add `trust_remote_code`).

## Notes

- Resolves the brief's open item "exact Qwen3.5 build/quant for local serving."
- Exact IDs to pin everywhere: `Qwen/Qwen3.5-4B`, `Qwen/Qwen3-4B`, `Qwen/Qwen3-8B`; Unsloth loaders `unsloth/Qwen3.5-4B`, `unsloth/Qwen3-4B`.
- Verifier decision (Gemini free API tier as the shipped/CI default) is unchanged — see DR-0003. In this office/browser context Claude is not a programmatic verifier; Gemini free tier also serves as the Wave 0 hosted quality reference (DR-0002's "compare against Claude hosted" is swapped to Gemini here).
- Related: DR-0002 (superseded), DR-0003 (reliability/verifier), DR-0004 (fine-tune compute — note local-PoC steps are home/out-of-band; in this context training is free Colab/Kaggle), DR-0006 (stack).

### Index row to add to `quellgeist-adr-log.md`
```
| DR-0007 | Model selection: Qwen3.5-4B default, Qwen3-4B fallback, Qwen3-8B bigger candidate | Accepted (provisional) | Wave 0 gate; Wave 4 |
```
And change the DR-0002 status cell to **Superseded by DR-0007**.
