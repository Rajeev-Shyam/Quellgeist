# Quellgeist — Implementation Plan (Rolling Wave)

> **How to execute:** Implement task-by-task. Each task is a self-contained, testable change ending in a commit. Two execution styles work: (a) a fresh agent/subagent per task with review between tasks, or (b) inline batch execution with checkpoints. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build Quellgeist — an open-source, model-agnostic, MCP-powered agent that diagnoses production incidents (ranked root-cause hypotheses + cited evidence + suggested actions), proven reliable via a breakable demo stack and a CI eval suite.

**Architecture:** A custom agent loop gathers evidence through MCP servers (GitHub + custom logs/metrics), a fine-tuned Qwen3-4B proposes a ranked diagnosis, and a stronger model (default: Gemini's free API tier) verifies evidence and forces abstention. Outputs render as a templated postmortem. A deliberately-breakable FastAPI demo stack and a parameterised eval suite make reliability reproducible and measured.

**Tech Stack:** Python 3.12 · FastAPI (demo app) · MCP Python SDK · LiteLLM (provider abstraction) · Ollama (local serving) · Qwen3-4B (+ a stronger verifier model; default Gemini's free API tier — a Claude Max plan is the app, not an API) · pytest (tests + evals) · GitHub Actions (CI) · Modal or Vast.ai (cloud GPU for training; free Colab/Kaggle T4 in the office/browser context) · prometheus-client.

---

## How This Rolling Wave Plan Works

This is a **Rolling Wave** plan, by deliberate choice — it is meant to be updated continuously, not frozen.

- **Only the current wave is detailed** to task/step level. Later waves are intentionally coarse (objective + entry/exit criteria + rough task list).
- **At each wave boundary**, run the *Wave Review Checklist* (bottom of this doc): fold in what you learned, re-scope the next wave to full detail, adjust or cut downstream work.
- **Cut-first item under time pressure:** the resolution-verification loop (Wave 6). Reliability (Waves 1–2) is non-negotiable.
- Deviation from the standard plan format is intentional: greenfield + rolling-wave means future-wave code is not pre-written (it would be speculative). Wave 0–1 are execution-ready; later waves get that treatment when reached.

**Proposed repo structure (locked in Wave 1):**
```
quellgeist/
  pyproject.toml · README.md · LICENSE (MIT)
  src/quellgeist/
    agent/         loop.py · prompts.py · providers.py · verifier.py
    servers/       logs_mcp.py · metrics_mcp.py        # custom MCP servers
    output/        postmortem.py
    cli.py
  demo/
    app/           FastAPI toy service
    chaos/         failure injection + reset scripts
    docker-compose.yml
  evals/
    scenarios/     generator.py · fixtures/ · holdout/  # NOTE: holdout ≠ generator distribution
    spikes/        wave0_spike.ipynb                     # Wave 0 throwaway notebook (provenance)
    judge.py · fabrication_check.py · run_evals.py
  .github/workflows/evals.yml
  docs/
    decisions/     ADRs · README.md (index)
    plans/         this file
    case-studies/
```

---

## Wave 0 — De-risk the Load-bearing Bet (Spike, ~1 day)

**Status: COMPLETE (2026-06-18). Outcome: default reasoner = Qwen3-4B (escalation Qwen3-8B); see DR-0008.**

**Why first:** the entire project assumes a small (4B) model can orchestrate multi-step evidence-gathering and tool calls well enough. If it can't, that changes the model choice or the architecture — cheaper to learn now than in Wave 4.

**Objective:** confirm a 4B-class model can drive a 2–3 step tool-calling loop and produce a structured, evidence-grounded answer on one hand-built incident example.

- [x] Install Ollama locally; pull a 4B instruct build; confirm it serves and responds. *(Executed in-notebook via Unsloth on a free Colab T4 — no local machine in the office context.)*
- [x] Write a throwaway script: give the model 2 fake "tools" (return canned logs / canned git log) and one incident prompt; see whether it (a) calls the right tool, (b) uses the result, (c) outputs a sensible cause + evidence.
- [x] Repeat the same prompt through a hosted reference (Gemini free tier) for a quality reference.
- [x] **Decision gate (test the two 4B families head-to-head):** Qwen3-4B adequate → proceed with Qwen3-4B (local PoC viable, cleanest cost story). 4B weak across both families → escalate to **Qwen3-8B** (free-trainable dense), **not** Qwen3.5-9B; note the consequences (cloud-only training, tighter local serving). Update the ADR log either way.

**Exit criteria:** a written one-paragraph finding on 4B tool-use adequacy + the gate decision recorded in the ADR log. *(Recorded in DR-0008; findings in `docs/case-studies/wave0-findings.md`.)*

---

## Wave 1 — Thin Vertical Slice: Bad-Deploy Diagnosis End-to-End (detailed)

**Objective:** one failure class (bad deploy) working through the *entire* pipeline — demo app → break it → agent reads logs + git via MCP → produces a postmortem — plus an eval harness skeleton in CI. Prove the whole spine on one case before adding breadth.

### Task 1: Repo scaffold
**Files:** Create `pyproject.toml`, `README.md`, `LICENSE`, `src/quellgeist/__init__.py`, `src/quellgeist/agent/schema.py`
- [ ] Initialise repo, Python 3.12, `pyproject.toml` (deps: fastapi, uvicorn, mcp, litellm, anthropic, pydantic, pytest, prometheus-client, structlog or python-json-logger). *(pydantic ships with fastapi but list it explicitly.)*
- [ ] Add `schema.py` with the shared diagnosis contract — `LogRef`/`CommitRef` (+ `MetricRef` stub for Wave 3), `EvidenceRef` discriminated union, `Hypothesis`, `Diagnosis` (with `abstained`/`abstention_reason`). See DR-0009. Tasks 4–9 import from here.
- [ ] Add MIT `LICENSE` with your name; stub `README.md` (one-line description + "WIP").
- [ ] Set up `pre-commit` (ruff + black) and a `.gitignore`.
- [ ] Commit: `chore: scaffold repo, license, tooling, diagnosis schema`.

### Task 2: Toy FastAPI demo app
**Files:** Create `demo/app/main.py`, `demo/app/__init__.py`
- [ ] Build a minimal FastAPI service with 2–3 endpoints (e.g. `/health`, `/login`, `/data`) that emit **structured JSON logs** per request (timestamp, level, route, status, message).
- [ ] Add a `/metrics` endpoint exposing Prometheus-style counters (request count, error count, in-flight) — stub now, used properly in Wave 3.
- [ ] Acceptance: `uvicorn demo.app.main:app` runs; hitting endpoints produces JSON log lines; `/metrics` returns text.
- [ ] Commit: `feat(demo): toy FastAPI app with structured JSON logs`.

### Task 3: Chaos — bad-deploy injection + reset
**Files:** Create `demo/chaos/bad_deploy.py`, `demo/chaos/reset.py`
- [ ] `bad_deploy.py`: introduce a controlled regression (e.g. a code path on `/login` that throws after a "deploy"), and write a fake git commit/deploy marker (commit to the demo app's own git history or a `deploy_log.json`) timestamped at the break.
- [ ] `reset.py`: revert the regression and clear the marker.
- [ ] Acceptance: run `bad_deploy.py` → `/login` errors + a deploy marker exists with a timestamp just before the first error; `reset.py` restores green.
- [ ] Commit: `feat(chaos): bad-deploy injection and reset`.

### Task 4: Custom logs MCP server
**Files:** Create `src/quellgeist/servers/logs_mcp.py`, `tests/servers/test_logs_mcp.py`
- [ ] Implement an MCP server (stdio transport) exposing `query_logs(since, level, route)` returning matching structured-log entries, **each with its source-stable `id`** (log-line number / ingest counter — NOT the index within the filtered result, so an evidence handle resolves the same regardless of query). This `id` is what `LogRef` cites (DR-0009).
- [ ] **Step: write the failing test** — `test_query_logs_filters_by_level` feeds known log lines and asserts only `ERROR` rows return, **each carrying its original source `id`**.
- [ ] **Step: run it, confirm fail → implement parser + filter → confirm pass.**
- [ ] Write tight tool descriptions (the model relies on them — Wave 2 tests description quality).
- [ ] Commit: `feat(servers): structured-log MCP server with query_logs (stable ids)`.

### Task 5: Wire GitHub MCP (reuse)
**Files:** Create `src/quellgeist/agent/providers.py` (MCP client config)
- [ ] Wire the existing GitHub MCP server (read-only) so the agent can fetch recent commits/diffs; for the demo, point it at the demo app's repo (or read the local `deploy_log.json` if simpler for v1).
- [ ] Acceptance: a manual call lists the last N commits including the bad-deploy marker.
- [ ] Commit: `feat(agent): connect GitHub MCP (read-only) for deploy/commit history`.

### Task 6: Provider abstraction + minimal agent loop (hosted model first)
**Files:** Create `src/quellgeist/agent/loop.py`, `src/quellgeist/agent/prompts.py`, `tests/agent/test_loop.py`
- [ ] `providers.py`: LiteLLM wrapper so the model is swappable by config (hosted while iterating; Ollama/local in Wave 4).
- [ ] `loop.py`: a legible decide→call→observe→repeat loop with a step cap; tools = `query_logs` + git history; returns a `Diagnosis` (from `schema.py`).
- [ ] `prompts.py`: the diagnosis system prompt — ranked hypotheses, each citing evidence **only by the `id`/`sha` returned by the tools** (human explanation goes in each handle's `note`, never paraphrase the identifier); if the signals don't support a confident cause, **set `abstained=true` with a reason instead of guessing**.
- [ ] **Step: write the failing test** — `test_loop_calls_logs_then_diagnoses` with a mocked provider asserts the loop calls `query_logs` and returns a `Diagnosis` whose evidence are resolvable handles.
- [ ] **Step (measurement, per DR-0009):** log how often the model emits a malformed/nonexistent id on the fixture — early read on id-citation fidelity on a 4B.
- [ ] **Step: fail → implement → pass.**
- [ ] Acceptance: against the broken demo app, the loop returns a `Diagnosis` naming the deploy as cause #1 with evidence handles resolving to the real log row + commit.
- [ ] Commit: `feat(agent): evidence-gathering loop returning a structured Diagnosis`.

### Task 7: Postmortem output
**Files:** Create `src/quellgeist/output/postmortem.py`, `tests/output/test_postmortem.py`
- [ ] Render a `Diagnosis` into a templated postmortem (summary, short timeline, ranked hypotheses, suggested actions). For each hypothesis, render its evidence as the handle (`log #id` / `commit sha`) **plus its `note`** so the citation is both human-readable and traceable. Handle the `abstained=true` case explicitly ("insufficient evidence"). Output to **stdout and an HTML/Markdown file**.
- [ ] **Step: failing test** — `test_postmortem_includes_evidence_refs` asserts each hypothesis line carries its evidence handle(s).
- [ ] **Step: fail → implement → pass.**
- [ ] Commit: `feat(output): templated postmortem renderer`.

### Task 8: CLI entry point
**Files:** Create `src/quellgeist/cli.py`
- [ ] `quellgeist diagnose` runs the loop against the configured demo app and prints the postmortem.
- [ ] Acceptance: `bad_deploy.py` then `quellgeist diagnose` prints a postmortem fingering the deploy; `reset.py` then `diagnose` reports healthy / insufficient-evidence.
- [ ] Commit: `feat(cli): quellgeist diagnose command`.

### Task 9: Eval harness skeleton + first scenario + CI
**Files:** Create `evals/scenarios/generator.py` (stub), `evals/run_evals.py`, `evals/judge.py` (stub), `.github/workflows/evals.yml`, `tests/evals/test_runner.py`
- [ ] Define a scenario schema (injected failure → expected root-cause label + **`gold_evidence_refs`** = the handles a correct diagnosis must cite). Use `bad_deploy_0001.json` as the first fixture.
- [ ] `run_evals.py`: spin up the demo app, inject the scenario, run the agent, capture the `Diagnosis`. Judge stub = exact/keyword match for now (real LLM-judge in Wave 2). *(The deterministic handle-lookup fabrication check using `gold_evidence_refs` lands in Wave 2 / `evals/fabrication_check.py`.)*
- [ ] **Step: failing test** for the runner on the single fixture → implement → pass.
- [ ] `.github/workflows/evals.yml`: run the eval(s) on every push; print pass/fail.
- [ ] Commit: `feat(evals): harness skeleton + first bad-deploy scenario + CI`.

**Wave 1 exit criteria:** from a clean clone, a developer can break the demo, run `quellgeist diagnose`, and get a correct, evidence-cited postmortem for the bad-deploy case; CI runs the single eval green.

---

## Wave 2 — Reliability Core *(rolling — detail at wave start)*

**Objective:** make the headline reliability guarantee real on the bad-deploy class.
**Entry criteria:** Wave 1 exit met.
**Rough tasks:** add the **verifier-model pass** (a stronger model — default Gemini's free API tier, Claude swappable — confirms cited evidence exists/supports each claim; downgrade or abstain otherwise); implement the **deterministic fabrication check** (every cited evidence item must exist in the real signals); add **abstention**; replace the judge stub with **LLM-as-judge on a rubric**; build a small **human-labelled gold subset** to validate the judge; set concrete reliability bars after a baseline; publish a CI reliability report/badge.
**Key design constraint (from review):** keep the eval's *held-out* scenarios separate from anything used to tune prompts/model — see Wave 4 note on train/eval separation.
**Exit criteria:** on the bad-deploy class, correct cause #1 in a high majority of runs, **zero fabricated causes on the eval set**, validated judge.

## Wave 3 — Breadth: Classes 2 & 3 + Metrics *(rolling)*

**Objective:** add config/env-var and resource-exhaustion classes; bring metrics online.
**Entry criteria:** Wave 2 reliability bar met on class 1.
**Rough tasks:** build the **metrics MCP server** + real Prometheus counters in the demo app; chaos scripts for config/env and resource-exhaustion; extend `generator.py` to **parameterised generation** (templates → variants) toward ~50 scenarios across the three classes; re-validate the judge on a gold subset spanning all classes.
**Exit criteria:** all three classes pass their reliability bars; ~50-scenario suite green in CI.

## Wave 4 — Cost / Fine-tune *(rolling)*

**Objective:** the cost thesis with a measured (honest) result.
**Entry criteria:** stable base-model behaviour + evals from Wave 3.
**Rough tasks:** generate **training data** from the scenario generator; **local QLoRA PoC** on the RTX 5060 to validate the pipeline; **real training on cloud GPU** (Modal default / Vast.ai cheaper); **serve locally via Ollama**; compare fine-tuned-vs-base-vs-frontier, with/without verifier, on **cost and quality** (optionally include Claude — run via the Claude Agent SDK / Claude Code on your home Max plan — as a verifier comparison vs the default Gemini free tier).
**Critical (from review):** the **eval/holdout scenarios must come from a different distribution than the fine-tuning data** (e.g. hand-authored or differently-parameterised), or the numbers measure memorisation, not skill. Build the holdout set explicitly.
**Exit criteria:** a published, honest cost/quality comparison — including the case where local proves insufficient (still a valid finding).

## Wave 5 — Polish & Ship *(rolling)*

**Objective:** make it adoptable and launch it.
**Entry criteria:** Wave 3 done (Wave 4 ideally done; can ship on base model if 4 slips).
**Rough tasks:** **render postmortems to an HTML/Markdown file** (defer a live web UI to post-v1); README + architecture doc + **≥1 written case study**; **security pass** on the published MCP servers — run an MCP scanner (`mcp-scan` / Cisco `mcp-scanner`) + `bandit`/`semgrep`/`pip-audit` in CI, ship `SECURITY.md` + a threat-model paragraph (input validation, no SSRF, scoped access, least privilege); **official MCP Registry** publish + **CI auto-publish** (GitHub OIDC) for the custom server(s); claim Glama/PulseMCP/mcp.so listings; launch posts (GitHub, HN, r/mcp, r/LocalLLaMA, Product Hunt) + aim for the PulseMCP newsletter.
**Exit criteria:** public repo, runnable demo, evals/badge live, server(s) registered, launch posted.

## Wave 6 — Resolution-verification Loop *(deferred / cut-first)*

**Objective:** after a controlled fix is applied in the sandbox, the agent re-reads signals and confirms recovery. No autonomous prod mutation.
**Note:** only attempt if Waves 1–5 are solid and time remains. Pure upside, fully expendable.

---

## Wave Review Checklist (run at every wave boundary)

- [ ] What did this wave teach us that changes downstream waves? (capacity of the model, eval realism, time spent vs estimate)
- [ ] Re-scope the next wave to full task/step detail now.
- [ ] Cut or defer anything that no longer earns its place (YAGNI).
- [ ] Update the brief and ADR log if any locked decision changed.
- [ ] Re-check timeline against remaining time; if behind, pull from the cut-list (Wave 6 first, then web UI, then trim failure classes to 2).

---

## Self-Review Notes (author)

- **Spec coverage:** every brief section maps to a wave (concept→all; reliability→Waves 1–2; failure classes→1,3; fine-tune→4; distribution→5; fix-loop→6; environment split honoured by hosted-while-iterating + cloud training).
- **Two review mitigations are built in:** Wave 0 spike (small-model capability) and the explicit train/eval distribution separation (Waves 2 & 4).
- **Known optimism:** the timeline is a hypothesis; the cut-list and rolling structure absorb slippage.
