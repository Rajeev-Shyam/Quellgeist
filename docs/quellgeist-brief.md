# Project Brief — Quellgeist

*Incident Triage Copilot · open-source, model-agnostic, MCP-powered AI assistant*

---

## 1. Summary

Quellgeist is an open-source AI agent that performs the first-line diagnosis of a production incident. On a trigger, it gathers evidence from structured logs, Prometheus-style metrics, and recent git/deploy history (each via MCP), correlates the signals, and produces a confidence-ranked set of root-cause hypotheses — each backed by cited evidence — plus suggested next actions, rendered as a templated postmortem. It is model-agnostic: a **fine-tuned Qwen3-4B** does the routine reasoning for cost efficiency, and a **stronger "verifier" model** (default: Gemini's free API tier — note that a Claude Max plan is the app subscription, not a programmatic API; Claude/others are swappable if API credit is added later) confirms the evidence supports each claim and forces abstention when it doesn't. Reliability is proven, not asserted: the repo ships a deliberately-breakable demo stack and a parameterised eval suite (~50 scenarios, target). A **keyless deterministic gate** (lint + tests + the fabrication check) runs on every push; the **model-driven eval runs out-of-band and key-gated** (manual + merges to `main`), so free-tier flakiness never reddens a PR (DR-0015/DR-0017).

---

## 2. Goal & Purpose

**Primary purpose — demonstrate engineering depth.** Take a messy multi-system problem, build on platform primitives (MCP), make it *provably reliable* (evals + a verifier guarantee), engineer it for *cost* (small fine-tuned local model + a free-tier verifier), and communicate it cleanly (docs, a runnable demo, written case studies).

**Secondary purpose — real utility.** Genuinely cut time-to-diagnosis in incident response for small teams and self-hosters.

**Why this design clears the bar.** Building another MCP server, or another MCP eval/lint harness, no longer differentiates — both are saturated categories. Differentiation comes from *workflow depth + demonstrated reliability + a cost story*, which is exactly the shape of FDE work.

---

## 3. Audience & Positioning

- **Primary audience:** FDE / AI-engineering reviewers at AI companies (Anthropic/OpenAI-style). They judge MCP fluency, reliability/eval rigour, cost-aware model architecture, and communication quality.
- **Secondary users:** on-call engineers, small-team and self-hosting developers.
- **Owner / approver:** Rajeev (sole).

---

## 4. Thesis & Headline Differentiators

Ordered to match stated priorities — **orchestration depth elevated 2026-06-18** (reliability → orchestration depth → DX/docs → usefulness):

1. **A reliability guarantee, not a demo.** Headline claim: *zero confidently-stated fabricated causes* on the eval set. Backed by a separate verifier-model pass + abstention + a deterministic "does the cited evidence actually exist" check.
2. **Real agentic orchestration depth.** A legible custom loop that decides which MCP server to call, in what order, and synthesises multi-source evidence — not a thin wrapper.
3. **A cost story with a measured result.** *Small fine-tuned local model (Qwen3-4B) + a stronger verifier ≈ frontier-only quality at a fraction of the cost* — a hypothesis to test, not a promise.
4. **Clean DX & docs.** MIT-licensed, clear README + architecture notes, written incident case studies, evals visible in CI. Built for adopters/stars.

---

## 5. Architecture Overview

Quellgeist is an **orchestration + reasoning layer** on top of MCP servers — the brain that decides which tool to call, in what order, and how to turn raw signals into a diagnosis.

```
trigger (manual CLI/paste  OR  thin webhook from simulated alert)
        ↓
evidence-gathering agent loop  (decide tool → call → observe → repeat)
   ├─ GitHub MCP        → recent commits / deploys / diffs
   ├─ logs MCP (custom) → structured JSON logs
   └─ metrics MCP       → Prometheus-style metrics
        ↓
reasoning: fine-tuned Qwen3-4B proposes ranked hypotheses + evidence
        ↓
verifier pass (stronger model; default Gemini free tier): confirm evidence supports each claim; abstain if not
        ↓
output: templated postmortem to stdout + an HTML/Markdown file (ranked hypotheses + evidence + suggested actions)
        ↓
[stretch] resolution-verification: after a controlled fix, re-read signals → confirm recovery
```

**Model-agnostic provider layer (key decision).** A single provider abstraction selects each model by config, which is what makes both the cost architecture and the office/home split work (§11): **hosted model (e.g. Gemini's free API tier, or a hosted open model) at office/Codespaces; local fine-tuned Qwen3-4B (served via Ollama) at home.** Keep the *agent loop* custom and legible (that is where orchestration is shown — now a top-two priority); use a library (e.g. LiteLLM) for the undifferentiated multi-provider plumbing, including local/Ollama, Gemini, and Anthropic.

---

## 6. Scope (v1)

**In scope:**

- One target stack: a minimal Python **FastAPI** demo service (intentionally toy).
- Three failure classes, built and eval-passed in this order: **bad deploy / code regression → config / env-var error → resource exhaustion (memory / DB connections)**.
- Evidence via MCP: GitHub (reuse) + custom thin servers for structured-JSON logs and Prometheus-style metrics.
- Reasoning: model-agnostic; default = **fine-tuned Qwen3-4B**; a **stronger verifier model (default Gemini free API tier; Claude swappable)**; able to call other models.
- **Fine-tuning is in v1** (§10).
- Outputs: confidence-ranked hypotheses + cited evidence, and suggested next actions/commands, rendered in a **templated postmortem**.
- Interaction: **one-shot** diagnosis.
- A **breakable demo stack** with one-command failure injection + reset (runs in Codespaces).
- An **eval suite** (~50 scenarios via parameterised failure injection) with LLM-as-judge scoring on a rubric, a human-validated gold subset, and a deterministic fabrication check.
- **CI split (DR-0015/DR-0017):** a keyless deterministic gate runs on every push; the model-driven eval runs **out-of-band** (manual + merges to `main`) and key-gated. A public reliability report/badge follows once real numbers exist.
- **Distribution:** official MCP Registry publish + CI auto-publish for the custom server(s); v1 launch via GitHub + community channels (§12).
- **CLI as the single core**; postmortems **rendered to an HTML/Markdown file** (no live web app in v1); a **thin, optional webhook** reusing the CLI core.
- **Stretch (cut first if time tightens):** sandbox **resolution-verification loop** — after a controlled fix, re-read signals to confirm recovery. No autonomous prod mutation.
- README, architecture notes, sample postmortems, demo recording. MIT licence.

**Out of scope (v1):** multiple/arbitrary stacks or languages; autonomous writes on any real production system; any real customer/proprietary data; real alerting/monitoring infrastructure; interactive multi-turn Q&A; a live web UI; auto-generated fix PRs.

---

## 7. Decision Log

| # | Decision | Choice | Rationale |
|---|----------|--------|-----------|
| 1 | FDE flavour | AI company (Anthropic/OpenAI style) | Rewards MCP fluency, evals, cost-aware model design |
| 2 | v1 public target | 5–6 weeks | Extended to fit fine-tuning in v1 |
| 3 | Weekly time | 10–20 hrs (~50–120h total) | Drives ruthless sequencing |
| 4–5 | Priority order | Reliability → orchestration depth → DX/docs → usefulness *(orchestration elevated 2026-06-18)* | Shapes where effort goes |
| 6 | Open-source ambition | Actively chase adopters/stars | Favours a sharp, polished, documented wedge |
| 7 | Scope appetite | Depth over breadth | A reliable narrow core beats broad-and-flaky |
| 8 | Language | **Python** | Fine-tuning + FastAPI demo + prior experience align |
| 9 | Model strategy | Model-agnostic; fine-tuned open model default; stronger verifier (default Gemini free tier) | Cost + reliability + flexibility |
| 10 | Orchestration | Custom agent loop + provider abstraction (e.g. LiteLLM) | Showcase the loop (a top-two priority); don't reinvent plumbing |
| 11 | Demo stack | Python FastAPI, minimal/toy | Fast to build + break; foregrounds diagnosis quality |
| 12 | Trigger | Both: manual CLI/paste + thin webhook | Manual for demo, webhook shows integration |
| 13 | Logs | Structured JSON | Clean to parse, realistic |
| 14 | Metrics | Prometheus-style | Standard; needed for resource-exhaustion class |
| 15 | MCP transport | stdio (local) + Streamable HTTP (webhook) | SSE deprecated; use current transports |
| 16 | Failure classes | Bad deploy, config/env, resource exhaustion | Match logs+metrics+git; order deploy→config→resource |
| 17 | MCP servers | Mix: reuse GitHub + 1–2 custom (logs, metrics) | Reuse where mature, build the thin gaps |
| 18 | Form factor | CLI core + postmortem-to-file; thin optional webhook; live web UI deferred to post-v1 | Cuts surface area to protect reliability time (priority #1) |
| 19 | Eval scoring | LLM-as-judge on rubric + human gold subset + deterministic fabrication check | Partial credit; gold subset prevents circular eval |
| 20 | Anti-hallucination | Verifier-model pass (default Gemini free tier) + abstention + evidence citation | The headline guarantee |
| 21 | Eval set size | ~50 via parameterised generation + gold subset | Templates→variants makes 50 feasible; shows eval engineering |
| 22 | Outputs | Ranked hypotheses + evidence; suggested actions | Lean, high-value |
| 23 | RCA format | Templated postmortem | Deterministic, eval-friendly, professional |
| 24 | Interaction | One-shot | Lowest build, fits scope |
| 25 | Past diagnosis | Sandbox resolution-verification loop (stretch, cut-first) | Strong differentiator but heaviest feature |
| 26 | Licence | MIT | Max adoption |
| 27 | CI evals | Keyless deterministic gate every push; model eval out-of-band + key-gated (DR-0015/DR-0017); public badge once numbers exist | Visible reliability signal without free-tier flakiness gating PRs |
| 28 | Fine-tuning timing | In v1; trained on own scenario data | Cost thesis central; data synergy with eval generator |
| 29 | Reasoning model | **Qwen3-4B**; escalation **Qwen3-8B** (confirmed at the Wave 0 gate — see DR-0008) | Proven end-to-end on free T4; Apache-2.0; mature 4-bit QLoRA; strong tool-calling; toggleable thinking mode |
| 30 | Fine-tune compute | **Hybrid:** local PoC + serving on RTX 5060 (8GB); real training runs on cloud GPU (Modal default, Vast.ai cheaper) | 8GB serves a 4-bit 4B fine but is tight for training iteration |
| 31 | Distribution | Official MCP Registry + CI auto-publish; claim directories; launch agent at v1 | Cheap + high-signal; registries list the servers, launch channels drive agent stars |
| 32 | Verifier access | Shipped default + CI = **Gemini free API tier**; optionally run Claude via Agent SDK / Claude Code on Max at home; Claude API key optional later | Work = Claude Team web-only; home = Claude Max (Desktop/CLI); a subscription isn't a distribution-grade app backend |

---

## 8. Failure Classes (v1)

Built and validated one at a time; do not start the next until the current one passes its eval bar.

1. **Bad deploy / code regression** *(build first — richest showcase).* Correlate "errors began at T" with "deploy landed at T−Δ" and "the diff touched module X". The strongest single capability.
2. **Config / env-var error.** Missing/wrong configuration surfaced in logs. Common, high-signal, easy to inject cleanly.
3. **Resource exhaustion (memory / DB connections).** Needs the metrics path; validates the agent reads metrics, not just logs.

---

## 9. Reliability & Evaluation Design

The centre of gravity of the project (priority #1).

- **Scenario generation.** Parameterised failure injection: a few templates per class, varied across parameters (module, timing, log verbosity, concurrent noise) to generate ~50 labelled scenarios. Each = an injected failure + the resulting logs/metrics/git state + a labelled correct cause.
- **Scoring.** LLM-as-judge against a rubric (correct cause #1? evidence valid? actions sensible?), **validated against a human-labelled gold subset** so the judge itself is trusted.
- **Headline guarantee.** A *deterministic* fabrication check: every cited piece of evidence must exist in the real signals. With the verifier pass + abstention, target **zero confidently-stated fabricated causes** — the agent says "insufficient evidence" rather than invents.
- **CI.** A keyless deterministic gate (lint + tests + the fabrication check) runs on every push; the model-driven eval runs **out-of-band** (manual `workflow_dispatch` + merges to `main`) and is key-gated, and treats an unreachable backend or a rejected credential as a **skip, not a failure** (DR-0015/DR-0017) — so a free-tier quota/credential hiccup never reddens a PR. A public report/badge follows once real numbers exist.

**Reliability metrics (set concrete bars after a baseline run):** correct cause ranked #1 in a high majority of scenarios (e.g. ≥ 80%); zero fabricated-cause failures; judge–human agreement above an acceptable threshold on the gold subset.

---

## 10. Fine-Tuning Plan (v1)

**Model: Qwen3-4B** (escalation Qwen3-8B if a 4B proves inadequate — see DR-0008). Sequenced **late** — it depends on three things existing first: the scenario generator, a working base-model agent (to define target behaviour), and the eval harness (to measure improvement).

1. Build the base-model agent (Qwen3-4B via the provider layer / hosted while iterating) and get it passing evals.
2. Use the **scenario generator to also produce fine-tuning data** (incident context → gold diagnosis), reusing the same labelling.
3. **Prototype the QLoRA fine-tune locally** on the RTX 5060 (8GB) to validate the pipeline (small batch, gradient checkpointing, short sequences). *If Qwen3-8B is chosen, skip the local PoC — 8GB can't comfortably QLoRA an 8B — and go straight to cloud/notebook.*
4. **Run the real / iterating fine-tunes on a cloud GPU** (Modal default for reproducibility + office-runnable; Vast.ai if cheapest matters).
5. **Serve the fine-tuned model locally** at home via Ollama (a 4-bit 4B fits 8GB comfortably; a 4-bit Qwen3-8B fits only at short/medium context).
6. Measure fine-tuned vs base vs frontier-only, with and without the verifier pass, on cost *and* quality.
7. Publish the comparison as the **headline result** — including the case where local proves insufficient (still a valid finding).

---

## 11. Environment & Workflow Constraints

Work splits ~25% office / ~75% home — treated as a first-class constraint (and itself an FDE-style "work within the environment" demonstration).

- **Office (~25%):** GitHub Codespaces + online services only; **Claude Team via the web app only** (no connectors, no programmatic/API access).
- **Home (~75%):** full resources — **Claude Max** (Claude Desktop + Claude CLI), personal accounts, and local rig — **RTX 5060 (8GB VRAM), Ryzen 9, 16GB RAM**.

**How the architecture absorbs it (no work gets blocked):**
- The **model-agnostic provider config** swaps backends by environment: hosted model at office/Codespaces; local fine-tuned Qwen3-4B (Ollama) at home.
- The **FastAPI + Docker Compose demo stack runs in Codespaces**, so development and the demo are office-doable.
- **Fine-tune training runs on a cloud GPU** (online) — reachable from either location, and necessary because local 8GB is tight for training. Local serving and a local QLoRA PoC are fine on the 8GB card (4B); Qwen3-8B fine-tuning is cloud/notebook-only.
- Keep the repo/Codespace **self-contained** (no reliance on Claude connectors) so office sessions are productive.
- **Verifier stays API-key-based** (default Gemini free tier) for the shipped default and CI — adopters and CI runners won't have your Max plan, and a subscription isn't a distribution-grade app backend. At home you can optionally run/compare Claude as the verifier via the Claude Agent SDK / Claude Code on Max — useful input for the Wave 4 cost/quality study.

**Suggested allocation:** office → agent/code work in Codespaces, eval authoring against hosted endpoints, cloud-GPU training runs, docs. Home → local model serving, local QLoRA PoC, personal-Claude-account work, final integration/demo recording.

---

## 12. Distribution & Launch

Registries list **MCP servers**; Quellgeist is mainly an **agent that consumes servers** plus 1–2 custom servers it ships. Plan accordingly:

- **For the custom server(s):** publish a `server.json` to the **Official MCP Registry** under a name you own, with **CI auto-publish on each tagged release** (GitHub OIDC). It feeds the downstream directories. Then claim the auto-crawled listings on **Glama / PulseMCP / mcp.so** (the `mcp-submit` CLI can push to many at once). Doing the registry + CI plumbing is itself an ecosystem-fluency signal.
- **Security gate before listing:** run an MCP scanner (`mcp-scan` / Cisco `mcp-scanner`) + `bandit`/`semgrep`/`pip-audit` in CI, and ship a `SECURITY.md` + a one-paragraph threat model. "Claimed/verified + clean" is the trust signal.
- **For the agent (the star magnet):** a strong GitHub README + demo, then launch posts at v1 — **Hacker News, r/mcp, r/LocalLLaMA, Product Hunt** — and aim for the **PulseMCP weekly newsletter** and the awesome-mcp-servers list.
- **Timing:** set up registry + CI during the build; save launch posts for v1. Don't over-invest pre-launch.

---

## 13. Build Sequence (high-level — see the Rolling Wave plan for detail)

1. **Wave 0 spike (done):** confirmed a 4B can orchestrate the loop; default reasoner = Qwen3-4B (escalation Qwen3-8B) — see DR-0008.
2. **Wave 1 (done):** thin vertical slice — bad-deploy diagnosis end-to-end + eval/CI skeleton.
3. **Wave 2 (built):** reliability core — verifier pass + fabrication check + abstention + LLM-judge; first real run passed with zero fabrication (DR-0016/DR-0017). Judge validation (a human gold subset) + a reliability *rate* carry into Wave 3.
4. **Wave 3 (current):** breadth — classes 2 & 3 + metrics; parameterised generation toward ~50 scenarios.
5. **Wave 4:** cost/fine-tune (local PoC → cloud training → comparison).
6. **Wave 5:** polish & ship — postmortem file render, docs, case study, security pass, registry + CI, launch.
7. **Wave 6 (cut-first):** resolution-verification loop.

---

## 14. Success Criteria

- A reviewer can clone the repo and reproduce a live diagnosis with one command, no real data.
- Reliability bars met (§9): correct cause #1 in a high majority of scenarios; zero fabricated causes; validated judge.
- A published, credible **cost/quality comparison** (fine-tuned Qwen + verifier vs frontier-only).
- Evals visibly running in CI with a reliability badge.
- Portfolio-grade repo: clear README, architecture doc, demo, ≥1 written case study showing the agent's reasoning.

---

## 15. Risks & Open Items

- **Scope creep (top risk).** Three failure classes + fine-tuning + a fix-loop in 5–6 part-time weeks is full. Mitigations: build/validate one failure class fully before the next; fine-tune only after evals exist; the fix-loop is explicitly cut-first.
- **Fine-tuning in v1.** Adds dependencies (training data, cloud GPU, comparison eval) and lands late. Fallback if time runs out: ship v1 on the base model + verifier and present fine-tuning as the next milestone.
- **Model size.** The Wave 0 gate confirmed **Qwen3-4B** as the default (DR-0008); escalation = **Qwen3-8B** (free-trainable dense) only if a 4B proves too weak on later failure classes. Capability is still n=1 — re-confirm on classes 2 & 3 in Wave 3.
- **Local VRAM (8GB).** Fine for serving a 4-bit 4B and a QLoRA PoC; too tight for comfortable training iteration → real fine-tunes go to a cloud GPU.
- **Verifier access.** No standalone Anthropic API key. Work = Claude Team (web app only); home = Claude Max (Desktop + Claude CLI). The shipped default + CI verifier use **Gemini's free API tier** (portable, CI-friendly). At home you can optionally run Claude as the verifier via the Claude Agent SDK / Claude Code on Max for the cost/quality comparison; add a Claude API key later if you want it as the automated default. The cost thesis and "zero fabrication" are targets/hypotheses, not promises.
- **Reasoning reliability.** The hard core; carries most effort and differentiation. Mitigation: evals first, abstention over fabrication.
- **Eval validity.** Training and eval data must NOT come from the same generator. Mitigation: an explicit held-out scenario set + the deterministic fabrication check.
- **Security.** Published MCP servers are a real attack surface; run scanners + ship `SECURITY.md` (see §12).
- **Demo realism.** Toy app risks looking unconvincing. Mitigation: make the *failure scenarios* realistic; foreground diagnosis quality.
- **Name availability.** "Quellgeist" not yet checked — verify npm / PyPI / GitHub / a quick trademark check before committing.

**Still genuinely open:** cloud-GPU provider final pick (Modal vs Vast); postmortem template to align to. *(Resolved: exact model/quant for local serving — Qwen3-4B, 4-bit QLoRA, see DR-0008.)*
