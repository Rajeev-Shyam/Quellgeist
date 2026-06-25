# Quellgeist — Decision Records (ADR Log)

A **living, flexible** log of the load-bearing decisions for this project. Records are intentionally lightweight and marked **provisional** — they are meant to be revisited at wave boundaries and updated or superseded as we learn. Use the lightweight template for new decisions; only go extended for genuinely large, hard-to-reverse ones.

**Status legend:** Proposed · Accepted (provisional) · Accepted (firm) · Deprecated · Superseded
**Convention:** new records get the next `DR-NNNN`; when a decision changes, supersede rather than silently edit (keep the history).

| # | Title | Status | Revisit at |
|---|-------|--------|-----------|
| DR-0001 | Project concept: incident-triage agent over MCP | Accepted (provisional) | After Wave 0 spike |
| DR-0002 | Model strategy: model-agnostic, fine-tuned Qwen3.5 4B + a stronger verifier | Superseded by DR-0007 | — |
| DR-0003 | Reliability: verifier pass + fabrication check + abstention + held-out evals | Accepted (provisional) | Wave 2 baseline |
| DR-0004 | Fine-tune compute: hybrid local PoC + cloud training | Accepted (provisional) | Wave 4 |
| DR-0005 | Distribution: official MCP registry + CI + v1 launch | Accepted (provisional) | Wave 5 |
| DR-0006 | Stack & surfaces: Python + FastAPI toy demo + CLI core | Accepted (provisional) | Wave 1 |
| DR-0007 | Model selection: Qwen3.5-4B default, Qwen3-4B fallback, Qwen3-8B bigger candidate | Superseded by DR-0008 | — |
| DR-0008 | Wave 0 gate outcome: Qwen3-4B confirmed as default reasoner | Accepted (firm) | Wave 4 results |
| DR-0009 | Evidence as structured handles + deterministic handle-lookup fabrication check | Accepted (provisional) | Wave 2 baseline |
| DR-0010 | Agent loop: JSON-action ReAct, in-process tools (stdio client deferred), measure-not-enforce | Accepted (provisional) | Wave 2 baseline |
| DR-0011 | Commits source: thin custom MCP over deploy_log.json (real GitHub MCP rejected for v1) | Accepted (provisional) | Wave 5 (distribution) |
| DR-0012 | Verifier/free-tier reality: Gemini free tier returns limit:0 unvalidated; model-calling CI must be key-gated | Accepted (provisional) — refines DR-0003 | Wave 2 verifier |
| DR-0013 | Deterministic fabrication check: full-signal-set membership, fail-closed, at eval time | Accepted (provisional) — implements DR-0009 | Wave 3 (metrics) |
| DR-0014 | Verifier + LLM-judge: model-agnostic config now, model-coupled logic deferred to stubs pending DR-0012 + the Qwen run | Accepted (provisional) — refines DR-0003/DR-0012 | After the Qwen id-fidelity run |
| DR-0015 | CI model eval is out-of-band + quota-tolerant (skip≠fail); default model pinned/corrected to gemini-3.5-flash | Accepted (provisional) — refines DR-0012 | After a non-walled key exists |

---

# DR-0001: Project concept — incident-triage agent over MCP

**Status:** Accepted (provisional) · **Date:** 2026-06-18 · **Decided by:** Rajeev (with Claude as thinking partner)

## Context
First portfolio project targeting AI-company (Anthropic/OpenAI-style) FDE roles. Needs to demonstrate FDE-grade ability, be open-source, and stand out.

## Decision
Build an open-source AI agent that performs first-line **incident triage** (ranked root-cause hypotheses + cited evidence + suggested actions) by orchestrating MCP servers — not another MCP server, and not another MCP eval/lint tool.

## Alternatives Considered
- **Build an MCP server (wrapping a tool)** — rejected: the category is saturated (10k+ servers); building one more signals nothing.
- **Build an MCP eval/lint harness** — rejected: also already crowded (official Inspector, MCPJam ~2k stars, mcp-tef, Arcade Evals).
- **Vertical business-workflow agent / dev-ops coding assistant** — rejected earlier: from-scratch cost (vertical) or crowded + invites comparison to Cursor/Claude Code (coding assistant).

## Consequences
**Good:** differentiation comes from workflow depth + demonstrated reliability + a cost story — exactly FDE-shaped. Reproducible demo possible with no proprietary data.
**Trade-offs:** "incident triage" is bottomless; needs hard scoping.
**Watch out for:** MCP here is partly a **portfolio signal** rather than the leanest engineering choice for a self-contained agent — acceptable and intentional, but be honest about it in the writeup.

## Notes
Supersedes the earlier working names "Triagent" and "Mayday" → final name **Quellgeist**. Priority order updated 2026-06-18 to elevate orchestration depth (now top-two).

---

# DR-0002: Model strategy — model-agnostic, fine-tuned Qwen3.5 4B + a stronger verifier

**Status:** Superseded by DR-0007 (then DR-0008) · **Date:** 2026-06-18 · **Decided by:** Rajeev

> **Superseded.** The default reasoner is now **Qwen3-4B** — see DR-0007 (model selection) then DR-0008 (Wave 0 gate outcome). Body retained for history.

## Context
Want cost efficiency (a small local model) without sacrificing the reliability that is priority #1, and flexibility to swap models per environment (office vs home).

## Decision
Model-agnostic via a provider abstraction. Default reasoner = **fine-tuned Qwen3.5 4B**; a **stronger model runs a verifier pass (default: Gemini's free API tier)**; other models callable by config.

## Alternatives Considered
- **Gemma 4 4B** — reuses prior fine-tuning experience, but non-Apache licence and historically weaker tool-use than Qwen.
- **Mistral Small 4** — strong fine-tuning ergonomics; kept as a fallback option.
- **Frontier-only (Claude/GPT)** — simplest, best quality, but no cost story and no "local" thesis.
- **Claude as the verifier** — desirable, but blocked: only a Claude Max app subscription is available, which is not a programmatic API (see Watch out).

## Consequences
**Good:** Apache-2.0 (clean for an MIT project); strong family tool-use + toggleable thinking mode; provider abstraction also solves the office/home model-swap; Gemini free-tier verifier means the cost story extends to the verifier too.
**Trade-offs:** a 4B is weaker at multi-step orchestration than the family's flagship.
**Watch out for (from review):**
- "Best tool-calling at 4B" is **unproven** — the Wave 0 spike tests **4B vs 9B head-to-head**; if 4B is inadequate, move default to **Qwen3.5 9B** (or a hosted-open model) and supersede this record. Do not claim frontier-parity until measured.
- **If 9B is chosen:** local QLoRA on 8GB VRAM is impractical → do all fine-tuning on cloud, and expect tighter local serving (a 4-bit 9B fits 8GB only at short/medium context).
- **Verifier access:** work = Claude Team (web app only); home = Claude Max (Claude Desktop + CLI). The **shipped default + CI** verifier runs on an API-key model — default **Gemini free tier** — because adopters/CI lack the Max plan and a subscription isn't a distribution-grade app backend. At home you can optionally run Claude as the verifier via the Claude Agent SDK / Claude Code on Max (good input for the Wave 4 cost/quality study); add a Claude API key later if you want it automated.
- Option to mix: keep 4B as the *proposer* and use a larger/hosted model only as the *verifier*.

---

# DR-0003: Reliability approach — verifier pass + fabrication check + abstention + held-out evals

**Status:** Accepted (provisional) · **Date:** 2026-06-18 · **Decided by:** Rajeev

## Context
The project's #1 differentiator is *provable* reliability; the headline claim is "zero confidently-stated fabricated causes" on the eval set.

## Decision
Layer three guardrails — a **verifier-model pass** (a stronger model confirms evidence supports each claim; default Gemini's free API tier, Claude swappable), a **deterministic fabrication check** (every cited evidence item must exist in the real signals), and **abstention** ("insufficient evidence"). Score diagnoses with **LLM-as-judge on a rubric**, validated against a **human-labelled gold subset**. Generate ~50 scenarios via parameterised failure injection, evaluated in CI.

## Alternatives Considered
- **Exact-match / ranked scoring only** — too brittle / too coarse for partial-credit reasoning.
- **LLM-judge alone** — rejected as the sole mechanism: circular without a human-validated subset, and weak for the "no fabrication" guarantee (hence the deterministic check).

## Consequences
**Good:** a credible, measured reliability story; CI badge as a public signal.
**Trade-offs:** building the harness + judge validation is real effort (and the highest-value effort).
**Watch out for (from review):**
- **Train/eval distribution leak** — fine-tuning data and the eval set must NOT come from the same generator, or numbers measure memorisation. Maintain an explicit **held-out** scenario set (hand-authored or differently parameterised).
- Phrase "zero fabrication" as *on the eval set*, not absolute.
- Verifier defaults to Gemini's free API tier (zero cost); if you later use a paid API for the verifier, the cost across ~50 scenarios × iterations is small.

---

# DR-0004: Fine-tune compute — hybrid local PoC + cloud training

**Status:** Accepted (provisional) · **Date:** 2026-06-18 · **Decided by:** Rajeev

## Context
Home rig is an RTX 5060 (8GB VRAM), Ryzen 9, 16GB RAM. Fine-tuning is in v1.

## Decision
**Hybrid:** prototype the QLoRA fine-tune locally on the 8GB card to validate the pipeline; run the real/iterating training on a **cloud GPU** (Modal default for reproducibility + office-runnable; Vast.ai if cheapest matters); **serve** the fine-tuned 4-bit model locally via Ollama.

## Alternatives Considered
- **All-local training** — rejected: 8GB is too tight for comfortable 4B training iteration (small batch/short seq, OOM risk, slow), and not feasible for 9B.
- **All-cloud** — fine but unnecessary for 4B; local serving + a local PoC are free and capable.
- **Colab / RunPod** — viable cloud alternatives (Colab simplest one-off; RunPod easiest templates).

## Consequences
**Good:** fast iteration for a few dollars; reproducible cloud training script doubles as a portfolio artifact; local serving keeps inference free and private.
**Trade-offs:** a second environment (cloud) to manage.
**Watch out for:** confirm you're OK paying a few dollars for cloud runs. If 9B is chosen (DR-0002), training is cloud-only. Training data is **synthetic**, so GDPR/data-residency concerns with US GPU providers do **not** apply here.

---

# DR-0005: Distribution — official MCP registry + CI auto-publish + v1 launch

**Status:** Accepted (provisional) · **Date:** 2026-06-18 · **Decided by:** Rajeev

## Context
Goal is active adoption/stars. Need a distribution plan that fits how the MCP ecosystem actually works.

## Decision
Publish a `server.json` for the **custom MCP server(s)** to the **Official MCP Registry** with **CI auto-publish** on each tagged release (GitHub OIDC); claim the auto-crawled listings on Glama/PulseMCP/mcp.so. Promote the **agent itself** at v1 via GitHub + launch channels (HN, r/mcp, r/LocalLLaMA, Product Hunt) and aim for the PulseMCP newsletter.

## Alternatives Considered
- **GitHub only** — simpler, but misses ecosystem discoverability for the servers.
- **Manual registry submissions** — rejected: listings go stale; CI auto-publish avoids that.

## Consequences
**Good:** registry + CI plumbing is itself an ecosystem-fluency signal; broad discoverability.
**Trade-offs:** launch effort; multiple directories.
**Watch out for:** registries list **servers**, not the agent — stars for the agent come from the README/demo + launch posts. Do a **security pass** on published servers before listing — run an MCP scanner (e.g. Invariant Labs' `mcp-scan` or Cisco's `mcp-scanner`) plus `bandit`/`semgrep`/`pip-audit` in CI, and ship a `SECURITY.md` + a one-paragraph threat model. "Claimed/verified + clean" is the trust signal. (Context: 2026 surveys found the large majority of MCP servers have path-traversal/command-injection exposure — don't be one of them.)

---

# DR-0006: Stack & surfaces — Python + FastAPI toy demo + CLI core

**Status:** Accepted (provisional) · **Date:** 2026-06-18 · **Decided by:** Rajeev

## Context
Need one coherent language across agent, demo app, evals, and fine-tuning, plus a demo stack that is fast to build and break — without spreading effort across too many user-facing surfaces.

## Decision
**Python** throughout. Demo = a minimal **FastAPI** service (intentionally toy) with structured JSON logs + Prometheus metrics. Evidence interface = **mix**: reuse GitHub MCP + ship 1–2 thin custom MCP servers (logs, metrics). Provider plumbing via LiteLLM; agent loop custom. **CLI is the single core**; postmortems render to an HTML/Markdown file; the webhook is a thin, optional adapter.

## Alternatives Considered
- **TypeScript/Node** — better for npx distribution, but Python wins for fine-tuning ecosystem + FastAPI demo + prior experience.
- **Plausibly-real demo app** — rejected for v1: toy is faster to build/break and foregrounds diagnosis quality.
- **Live read-only web UI** — deferred to post-v1: it competes directly with reliability time (priority #1).

## Consequences
**Good:** one language end-to-end; fast iteration; toy app demos cleanly; minimal surface area.
**Trade-offs:** a toy app risks looking unconvincing.
**Watch out for (from review):**
- Make the **failure scenarios** realistic even though the app is minimal — the diagnosis quality is the star.
- **Surface area is collapsed:** CLI is the single core; render postmortems to an HTML/Markdown file (no live web UI in v1); the webhook is a thin, optional adapter reusing the CLI core. A real UI is post-v1.

---

# DR-0007: Model selection — Qwen3.5-4B default, Qwen3-4B fine-tune fallback, Qwen3-8B as the bigger free-trainable candidate

**Status:** Superseded by DR-0008 · **Date:** 2026-06-18 · **Decided by:** Rajeev (with Claude as thinking partner)
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

---

# DR-0008: Wave 0 gate outcome — Qwen3-4B confirmed as the default reasoner

**Status:** Accepted (firm) — on building v1 on Qwen3-4B. One sub-point open (3.5 free-hardware fine-tune unmeasured; see Watch out).
**Date:** 2026-06-18 · **Decided by:** Rajeev (with Claude as thinking partner)
**Supersedes:** DR-0007 (set DR-0007 → Superseded) · **Revisit at:** Wave 4 results

## Context
DR-0007 named **Qwen3.5-4B** the default reasoner and **Qwen3-4B** the fine-tune-safety fallback, and explicitly deferred the final choice to the **Wave 0 spike gate** (decide on capability *and* free-GPU trainability). The spike has now run on a free Colab T4. This record captures the outcome.

## Decision
Default reasoner for v1 = **Qwen3-4B** (`unsloth/Qwen3-4B`, 4-bit QLoRA via `FastLanguageModel`). **Qwen3.5-4B** (`unsloth/Qwen3.5-4B`) is retained as an inference-capable option but is **not** the default, because on the only free GPU available (T4 / Turing) the current Unsloth build runs it in **fp32** with a **torch fallback** for its GDN/Mamba layers — making it materially slower. **Qwen3-8B** remains the escalation path if a larger reasoner is later justified.

## Evidence (single hand-built bad_deploy fixture, greedy decoding, free Colab T4)
- **Capability (n=1):** both Qwen3-4B and Qwen3.5-4B called the right tools, ranked the bad deploy #1, and cited only real evidence (no fabrication). Gemini free-tier reference agreed.
- **Inference speed:** Qwen3-4B **19.6s** (3 steps) vs Qwen3.5-4B **54.3s** (3 steps), each in its best free-T4 config.
- **Free-T4 fine-tune (Qwen3-4B):** QLoRA smoke trained — loss 0.41 → 0.05 over 30 steps, `train_runtime` 255s (~8.5 s/step), GGUF (f16) export succeeded.
- **Qwen3.5-4B precision:** loads fp32 ("fp16 won't work for qwen3_5" per Unsloth; no bf16 on Turing) + "fast path not available" torch fallback — reproduced in **Unsloth's own official notebook**, so it is a property of the build/hardware, not our code.

## Alternatives Considered
- **Keep Qwen3.5-4B as default (DR-0007's plan)** — rejected: degraded (fp32 + torch fallback) and ~2.7× slower on the only free hardware; the cost thesis depends on running cheaply *there*.
- **Qwen3.5-4B via a paid Ampere GPU (bf16)** — rejected: out of scope (no paid compute) unless a deliberate spend decision is made.
- **Pin an older Unsloth to try to restore fp16 for 3.5** — deferred: unverified (the older-build precision behaviour was never confirmed); not worth the rabbit hole when 3-4B is already proven.
- **Qwen3-8B now** — deferred: only if a 4B proves too weak on later failure classes; not indicated by the bad_deploy result.

## Consequences
**Good:** the default is the only candidate proven *end-to-end* on free hardware (capable + trains + exports); Apache-2.0; native 4-bit fp16 path, no missing kernels; the clean true-4-bit cost story lives here; model-agnostic design made the swap a one-line config change.
**Trade-offs:** Qwen3.5-4B was marginally sharper in phrasing on the one scenario, so we trade a small capability edge for a large free-hardware speed/robustness edge. Loses 3.5's 262K context and newest-model framing.
**Watch out for:**
- **Qwen3.5's free-hardware fine-tune was never directly measured** — only its inference fp32/slowness and fp32 *load* were observed. The decision rests on Qwen3-4B's proven superiority, not on a measured 3.5 fine-tune failure. If 3.5 is ever reconsidered, measure its actual sec/step first.
- **Capability is n=1** (one bad_deploy fixture). Re-confirm on config/env and resource-exhaustion classes in Wave 3.
- **Abstention / "insufficient evidence" was not exercised** in the spike — the headline reliability guarantee is still unproven (Wave 2).
- **Qwen3-4B fine-tune *quality* is unproven** — the smoke trained on ~12 near-identical rows (memorisation). Real data + a separate holdout is Wave 4.
- **Fabrication check needs fuzzy/structured matching** — both models cited evidence as *paraphrases* of real rows, not exact strings (Wave 2 design constraint).
- **GGUF export tax:** a full export re-downloads the ~8 GB base + installs llama.cpp + quantises (~25 min). In Wave 4, iterate on the LoRA adapter and export GGUF once at the end.

## Notes
- Resolves the brief's open item "exact Qwen3.5 build/quant for local serving."
- Qwen3.5 is a VLM — Unsloth loads it via `FastVisionModel`, and its chat template needs list-of-parts content, not bare strings. Recorded so it isn't rediscovered.
- Spike artifacts: `bad_deploy_0001.json` (graduates to `evals/scenarios/fixtures/`); findings → `docs/case-studies/wave0-findings.md`.
- Related: DR-0002 (superseded by DR-0007), DR-0007 (superseded here), DR-0003 (reliability/verifier — unchanged), DR-0004 (fine-tune compute — note: in the office/browser context, training is free Colab/Kaggle, not local), DR-0006 (stack).

# DR-0009: Evidence citation — structured handles + deterministic handle-lookup check

**Status:** Accepted (provisional) · **Date:** 2026-06-19 · **Decided by:** Rajeev (with Claude as thinking partner)
**Refines:** DR-0003 (reliability) · **Revisit at:** Wave 2 baseline

## Context
Wave 0 (DR-0008) found that both candidate models cite evidence as **paraphrases** of the real log/commit rows, not verbatim strings. The headline guarantee — *zero confidently-stated fabricated causes* — rests on a **deterministic** fabrication check, so the check cannot depend on matching the model's free text (a pure exact-string compare would flag correct evidence as fabricated).

## Decision
The agent cites evidence **only as structured handles** — a log row's source-stable `id` or a commit `sha` (a metric id is added in Wave 3) — in the diagnosis object's `evidence` field. Each handle may carry a display-only `note`; the postmortem renders the `note`s plus a per-diagnosis `summary`. The deterministic fabrication check becomes a set-membership lookup: every cited handle must resolve to a real signal. *Existence* is the deterministic check; *whether the evidence supports the claim* is left to the verifier-model pass; *overall quality* to the LLM-judge. Contract lives in `src/quellgeist/agent/schema.py`; check in `evals/fabrication_check.py` (built in Wave 2).

## Alternatives Considered
- **Free-text evidence + a normalizing/fuzzy checker** — rejected: puts a parser or similarity threshold inside the hard guarantee → false positives (real evidence flagged) or false negatives (fabrication "close enough" to pass); degrades the claim from *deterministic* to *mostly*; and is a retrofit treadmill as new phrasings appear.
- **A separate top-level `description` field (earlier sketch)** — superseded by per-handle `note` + `summary`: the gloss travels with the thing it describes, and the renderer and the check read different fields of the same object.

## Consequences
**Good:** the fabrication check is ~10 lines with no thresholds and is reviewer-legible; existence / support / quality are cleanly separated across the three reliability layers; adding `MetricRef` in Wave 3 is additive (discriminated union on `type`).
**Trade-offs:** the model must emit exact ids/shas — a prompt constraint and a possible source of schema-violation retries on a 4B; the diagnosis object carries both machine handles and human notes.
**Watch out for:**
- **`id` must be source-stable, not positional.** A log row's `id` is assigned at ingest (log-line number / monotonic counter), **not** the index within a filtered `query_logs` result — otherwise a handle resolves to different rows under different filters and the check compares against a moving target. (In `bad_deploy_0001` ids equal positions only because the fixture is unfiltered.)
- **id-citation fidelity on a 4B is unproven.** Wave 0 only showed paraphrasing when the model was *free*; it never tested copying ids under constraint. Measure citation fidelity early in Wave 1; do not assume reliable id-copying until measured.
- **Abstention (`abstained` / `abstention_reason`) is in the schema but still unexercised** until Wave 2.
- **When metrics land (Wave 3), extend `assert_no_fabrication` to handle `MetricRef`** — as currently written it fails *open* on unknown ref types; prefer fail-closed.
- **Ranking:** the `hypotheses` list is pre-sorted best-first; `confidence` is the model's advisory value, not a guarantee of monotonic order — sort on consume if you rely on it.

## Notes
- Resolves the Wave 0 carry-forward "fabrication check needs fuzzy/structured matching" by choosing **structured**.
- `bad_deploy_0001.json` gains per-row `id`s and a `gold_evidence_refs` field under this decision.
- Related: DR-0003 (reliability — refined here), DR-0008 (the Wave 0 finding that motivated this), DR-0006 (stack).

# DR-0010 — Agent loop architecture

##  Decision
a legible model-agnostic JSON-action ReAct loop (model emits {"action":…} text, we parse) rather than native function-calling; tools wired in-process behind a ToolSpec registry in Wave 1 with the real stdio MCP client deferred; loop returns a LoopResult carrying the diagnosis + a fidelity trace (schema_violations, seen_handles, cited_but_unseen_handles) and measures, does not enforce, fabrication (schema validity is enforced with retry→graceful abstention).

## Rationale
model-agnosticism across Gemini and local 4-bit Qwen; legibility; keeps the deterministic guarantee in Wave 2 where it belongs.

## Watch-outs
MCP-over-the-wire not yet demonstrated; cited_but_unseen is a run-scoped proxy, not the real check; provider retry rescues transient failures only. Refines DR-0006; revisit Wave 2.


# DR-0012 — Verifier / free-tier reality (refines DR-0003)

##  Decision
ship a thin custom commits MCP server (get_recent_commits over demo/deploy_log.json) rather than reuse the real GitHub MCP.

## Considered
GitHub's official API server (needs PAT + network + real pushed commits — collides with CI/offline/self-contained); the reference local git server mcp-server-git (real git, offline, but needs real commits + a chaos redesign).

## Rationale
the plan sanctioned the deploy_log.json path; keeps the demo reproducible, offline, token-free; the loop stays tool-agnostic so the real GitHub MCP is a clean post-v1 adapter. Refines DR-0006; revisit at Wave 5.

# DR-0011 — Commits evidence source

##   Finding (web-verified, 2026)
 a Gemini API key on an unvalidated, no-billing project returns 429 limit:0 on current models — Google gates the real free allowance behind account validation (linking a billing account; $0 within free limits but a card is required).

## Consequence
(a) model-calling CI cannot be the always-green gate — fork-PR runs have no secret, and quota/503 are external; keep the deterministic gate (tests + Wave 2 fabrication check) keyless and key-gate the verifier/judge/eval jobs; (b) the "free, no-card, CI-friendly Gemini verifier" assumption is dented — decide deliberately in Wave 2 whether Gemini-with-billing-linked stays the default or another verifier is chosen.

## Status
Accepted (provisional); revisit at Wave 2 verifier.

# DR-0013 — Deterministic fabrication check (implements DR-0009)

**Status:** Accepted (provisional) · **Date:** 2026-06-25 · **Revisit at:** Wave 3 (metrics)

## Decision
`evals/fabrication_check.py` does a pure set-membership lookup: every cited handle `(type, id/sha)` must exist in the **full** signal set (all log ids + all commit shas of the scenario), checked at **eval time** against the complete signals — NOT in the loop, which only has the run-scoped `seen_handles` proxy. **Fail-closed:** a handle whose type/key is absent (including `MetricRef` until Wave 3 brings metrics into the signal set) counts as fabricated. Wired into the harness so a fabricated handle fails the scenario even when the keyword judge passes (zero-fabricated-causes is the headline bar). Existence only; *support* is the verifier's job, *quality* the judge's.

## Considered
Checking against `gold_evidence_refs` only (rejected: that is gold-matching, the judge's concern, not existence); enforcing in the loop via `cited_but_unseen` (rejected: that proxy over-flags real-but-unqueried ids — DR-0009 / Wave-1 review).

## Rationale
Makes DR-0009's "existence is the deterministic check" real and keyless; fixes the `cited_but_unseen` over-flagging by checking against all real signals, not just queried ones. Deterministic, fully tested (check + harness wiring).

## Watch-outs
When metrics land (Wave 3), extend `real_signal_handles` to include metric ids so legitimate `MetricRef` citations stop failing closed. Implements DR-0009; revisit Wave 3.

# DR-0014 — Verifier + LLM-judge: model-agnostic config now, logic deferred (refines DR-0003, DR-0012)

**Status:** Accepted (provisional) · **Date:** 2026-06-25 · **Revisit at:** after the Qwen id-fidelity run + the DR-0012 decision

## Decision
Wire the model-agnostic **config knobs** now — `QG_VERIFIER_MODEL` / `QG_JUDGE_MODEL` → `default_verifier_provider` / `default_judge_provider` (fall back to `QG_MODEL`) — but **defer the verifier/judge LOGIC to tracked `NotImplementedError` stubs** (`agent/verifier.py`, `evals/llm_judge.py`) until (a) the DR-0012 verifier/judge-model question is decided and (b) the Qwen3-4B id-fidelity run measures how the real reasoner cites evidence. The deterministic keyword judge (`evals/judge.py`) stays the **keyless gate**; the LLM judge will be the key-gated quality scorer, validated against a human-labelled gold subset before any score is quoted.

## Considered
Building the verifier/judge prompt+parse logic now against an assumed model (rejected: bakes in untested assumptions about the 4B's citation behaviour, which the Qwen run exists to measure); replacing the keyword judge with the LLM judge outright (rejected: makes the gate model-dependent — contradicts DR-0012); hard-coding a verifier vendor (rejected: re-introduces the Gemini `limit:0` problem — config-driven model-agnosticism defers the choice cleanly).

## Rationale
Keeps the model-agnostic thesis (config, not vendor lock) and a keyless deterministic gate, without writing model-coupled logic before prompt fidelity is measured.

## Watch-outs
The verifier and LLM judge are **stubs** — building them is gated on the Qwen id-fidelity run (still pending) and the DR-0012 decision. The LLM judge additionally needs a **human-labelled gold subset** before its scores are trusted. **No real-model reliability numbers exist yet — none are quoted anywhere.** Refines DR-0003 and DR-0012; revisit after the Qwen run.

# DR-0015 — CI model eval is out-of-band + quota-tolerant; default model corrected (refines DR-0012)

**Status:** Accepted (provisional) · **Date:** 2026-06-25 · **Revisit at:** when a non-walled model key exists

## Context
The Wave-2 key-gated eval job (run on every PR/push) went **red**. Two root causes: (a) the repo had a `GEMINI_API_KEY` secret, so the job did NOT skip — it called the model and the **free tier 429'd** (`RequestsPerMinute/Day…FreeTier`, `RESOURCE_EXHAUSTED`); the provider's retry/backoff deliberately does not rescue a `limit:0`/quota error, so it propagated and the harness crashed (exit 1). (b) The job **never pinned `QG_MODEL`**, so it silently used the stale library default `gemini/gemini-2.0-flash` instead of the intended `gemini-3.5-flash`. DR-0012 (key-gating) was thus **necessary but insufficient**: a *present-but-walled* key still reddens CI.

## Decision
1. **Model id:** correct `DEFAULT_MODEL` to `gemini/gemini-3.5-flash` (a real current id; the old default was stale and inconsistent with the provider's own Gemini-3.x notes) and **pin `QG_MODEL` explicitly in CI** — never rely on the implicit default.
2. **Quota-tolerance:** the harness treats *provider unavailability* — 429/quota, 503, 500, timeout, connection error, surfaced after `complete`'s retries — as a **SKIP (exit 0)**, distinct from a model that ran and produced a bad diagnosis (still returns 1 → red). Classifier: `is_provider_unavailable` in `providers.py`; `run_evals.main` skips on it.
3. **Topology:** move the model eval **off feature PRs/pushes** into its own `eval.yml` (manual `workflow_dispatch` + merges to `main`). `ci.yml` (keyless lint+test) is the **only** PR gate.

## Considered
`continue-on-error: true` on the job (rejected: masks genuine eval failures as green and still burns quota every push); keeping it on every PR but quota-tolerant (rejected: burns free-tier quota + ~30s per push for a no-op); `gemini/gemini-flash-latest` floating alias (rejected: a reliability project pins versions for reproducibility).

## Consequence
PRs gate purely on the deterministic job — green on forks and during quota outages. The model eval is a **reporting** job: real numbers when a working key exists, a clean skip otherwise. **Still no real-model numbers** — the free tier may remain walled until billing is linked or a different backend is chosen (the open DR-0012 decision) / the local Qwen run. Refines DR-0012; revisit when a non-walled key exists.
