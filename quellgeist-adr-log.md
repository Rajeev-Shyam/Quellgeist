# Quellgeist — Decision Records (ADR Log)

A **living, flexible** log of the load-bearing decisions for this project. Records are intentionally lightweight and marked **provisional** — they are meant to be revisited at wave boundaries and updated or superseded as we learn. Use the lightweight template for new decisions; only go extended for genuinely large, hard-to-reverse ones.

**Status legend:** Proposed · Accepted (provisional) · Accepted (firm) · Deprecated · Superseded
**Convention:** new records get the next `DR-NNNN`; when a decision changes, supersede rather than silently edit (keep the history).

| # | Title | Status | Revisit at |
|---|-------|--------|-----------|
| DR-0001 | Project concept: incident-triage agent over MCP | Accepted (provisional) | After Wave 0 spike |
| DR-0002 | Model strategy: model-agnostic, fine-tuned Qwen3.5 4B + a stronger verifier | Accepted (provisional) | Wave 0 gate; Wave 4 results |
| DR-0003 | Reliability: verifier pass + fabrication check + abstention + held-out evals | Accepted (provisional) | Wave 2 baseline |
| DR-0004 | Fine-tune compute: hybrid local PoC + cloud training | Accepted (provisional) | Wave 4 |
| DR-0005 | Distribution: official MCP registry + CI + v1 launch | Accepted (provisional) | Wave 5 |
| DR-0006 | Stack & surfaces: Python + FastAPI toy demo + CLI core | Accepted (provisional) | Wave 1 |

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

**Status:** Accepted (provisional) · **Date:** 2026-06-18 · **Decided by:** Rajeev

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
