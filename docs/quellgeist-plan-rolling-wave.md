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

**Repo structure (✓ = exists after Wave 1; otherwise target wave):**
```
quellgeist/
  pyproject.toml · README.md · LICENSE (MIT)         # ✓ (README still WIP)
  # pyproject has [tool.pytest.ini_options] pythonpath = ["."]  ✓ (so top-level evals/ imports in tests)
  src/quellgeist/
    agent/
      schema.py        # ✓ Diagnosis contract (DR-0009)
      providers.py     # ✓ LiteLLM wrapper + retry/backoff
      loop.py          # ✓ JSON-action ReAct loop -> LoopResult
      prompts.py       # ✓
      verifier.py      # Wave 2
    servers/
      logs_mcp.py      # ✓ query_logs (stable ids)
      commits_mcp.py   # ✓ get_recent_commits over deploy_log.json
      metrics_mcp.py   # Wave 3
    output/
      postmortem.py    # ✓ Markdown renderer (HTML deferred)
    cli.py             # ✓ `quellgeist diagnose`
  demo/
    app/               # ✓ FastAPI toy service (structlog JSONL)
    chaos/             # ✓ bad_deploy.py · reset.py
    docker-compose.yml # (if created in Tasks 1–3)
  evals/
    scenarios/
      generator.py                  # ✓ Scenario schema + loader (parameterised gen = Wave 3)
      fixtures/bad_deploy_0001.json # ✓ first scenario
      holdout/                      # Wave 4  (NOTE: holdout ≠ generator distribution)
    spikes/wave0_spike.ipynb        # Wave 0 throwaway (provenance)
    judge.py             # ✓ STUB (keyword/handle match; real LLM-judge = Wave 2)
    fabrication_check.py # Wave 2 (deterministic handle-lookup vs FULL real-signal set)
    run_evals.py         # ✓ fixture-based harness (real-model eval job = Wave 2, key-gated)
  tests/
    servers/ · agent/ · output/ · evals/ · test_cli.py   # ✓ 37 tests
  .github/workflows/evals.yml   # ✓ keyless deterministic gate (lint + pytest)
  docs/                         # flat; combined single-file ADR log (not per-file ADRs)
    quellgeist-adr-log.md       # the ADR log
    quellgeist-plan-rolling-wave.md  # this file
    case-studies/               # wave0-findings.md, etc.
```
(Each package dir has an `__init__.py`.)

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
- [x] Initialise repo, Python 3.12, `pyproject.toml` (deps: fastapi, uvicorn, mcp, litellm, anthropic, pydantic, pytest, prometheus-client, structlog or python-json-logger). *(pydantic ships with fastapi but list it explicitly.)*
- [x] Add `schema.py` with the shared diagnosis contract — `LogRef`/`CommitRef` (+ `MetricRef` stub for Wave 3), `EvidenceRef` discriminated union, `Hypothesis`, `Diagnosis` (with `abstained`/`abstention_reason`). See DR-0009. Tasks 4–9 import from here.
- [x] Add MIT `LICENSE` with your name; stub `README.md` (one-line description + "WIP").
- [x] Set up `pre-commit` (ruff + black) and a `.gitignore`.
- [x] Commit: `chore: scaffold repo, license, tooling, diagnosis schema`.

### Task 2: Toy FastAPI demo app
**Files:** Create `demo/app/main.py`, `demo/app/__init__.py`
- [x] Build a minimal FastAPI service with 2–3 endpoints (e.g. `/health`, `/login`, `/data`) that emit **structured JSON logs** per request (timestamp, level, route, status, message).
- [x] Add a `/metrics` endpoint exposing Prometheus-style counters (request count, error count, in-flight) — stub now, used properly in Wave 3.
- [x] Acceptance: `uvicorn demo.app.main:app` runs; hitting endpoints produces JSON log lines; `/metrics` returns text.
- [x] Commit: `feat(demo): toy FastAPI app with structured JSON logs`.

### Task 3: Chaos — bad-deploy injection + reset
**Files:** Create `demo/chaos/bad_deploy.py`, `demo/chaos/reset.py`
- [x] `bad_deploy.py`: introduce a controlled regression (e.g. a code path on `/login` that throws after a "deploy"), and write a fake git commit/deploy marker (commit to the demo app's own git history or a `deploy_log.json`) timestamped at the break.
- [x] `reset.py`: revert the regression and clear the marker.
- [x] Acceptance: run `bad_deploy.py` → `/login` errors + a deploy marker exists with a timestamp just before the first error; `reset.py` restores green.
- [x] Commit: `feat(chaos): bad-deploy injection and reset`.

### Task 4: Custom logs MCP server
**Files:** Create `src/quellgeist/servers/logs_mcp.py`, `tests/servers/test_logs_mcp.py`
- [x] Implement an MCP server (stdio transport) exposing `query_logs(since, level, route)` returning matching structured-log entries, **each with its source-stable `id`** (log-line number / ingest counter — NOT the index within the filtered result, so an evidence handle resolves the same regardless of query). This `id` is what `LogRef` cites (DR-0009).
- [x] **Step: write the failing test** — `test_query_logs_filters_by_level` feeds known log lines and asserts only `ERROR` rows return, **each carrying its original source `id`**.
- [x] **Step: run it, confirm fail → implement parser + filter → confirm pass.**
- [x] Write tight tool descriptions (the model relies on them — Wave 2 tests description quality).
- [x] Commit: `feat(servers): structured-log MCP server with query_logs (stable ids)`.

### Task 5: Commits MCP server  ✅ DONE  *(was: "Wire GitHub MCP (reuse)")*
**Files created:** `src/quellgeist/servers/commits_mcp.py`, `tests/servers/test_commits_mcp.py` *(not `providers.py`)*
- [x] Custom thin `get_recent_commits(since, limit)` over `demo/deploy_log.json` (JSON array), newest-first, `sha` verbatim. **Real GitHub MCP rejected for v1** (token/network/offline/CI) — see DR-0011.
- [x] 6 tests green (newest-first, since, limit, sha-verbatim, missing-file→[], non-array→raises).
- [x] Commit: `feat(servers): commits MCP server with get_recent_commits over deploy_log.json`
- ⚠ Deviation: MCP *client* wiring (loop ↔ servers over stdio) deferred to Task 6, then deferred entirely — the loop calls tools **in-process** (DR-0010).

### Task 6: Provider abstraction + agent loop  ✅ DONE
**Files created:** `agent/providers.py`, `agent/loop.py`, `agent/prompts.py`, `tests/agent/test_loop.py`, `tests/agent/test_providers.py`
- [x] `providers.py`: LiteLLM wrapper, swappable via `QG_MODEL`; lazy `litellm` import; **explicit retry/backoff** (503/429/500/timeout) + 3 retry tests.
- [x] `loop.py`: **JSON-action ReAct loop** (NOT native function-calling), step cap, returns **`LoopResult`** (Diagnosis + fidelity trace), graceful abstention on exhaustion; tools `query_logs` + `get_recent_commits` wired **in-process**.
- [x] `prompts.py`: cite by `id`/`sha` only, abstain over guessing; forces evidence `type`.
- [x] Failing test → `test_loop_calls_logs_then_diagnoses` (mocked provider). 6 loop tests.
- [x] DR-0009 measurement = `cited_but_unseen_handles()` (run-scoped proxy; real check = Wave 2).
- [x] Commit: `feat(agent): evidence-gathering loop returning a structured Diagnosis` *(amended to fold in retry)*
- ⚠ Acceptance + the actual id-fidelity number **NOT yet measured** — blocked by Gemini limit:0/503; pending the Qwen-at-home run.

### Task 7: Postmortem output  ✅ DONE
- [x] Markdown renderer (HTML deferred); evidence as handle + `note`; abstention rendered explicitly. **No timeline section** (Diagnosis carries handles, not timestamps — deferred).
- [x] Failing test → `test_postmortem_includes_evidence_refs`. 6 tests.
- [x] Commit: `feat(output): templated postmortem renderer`

### Task 8: CLI entry point  ✅ DONE
- [x] `quellgeist diagnose` (argparse; `--out/--model/--max-steps/--title/--show-trace`); stdout = postmortem, stderr = diagnostics; provider failure → clean exit 1. Invoke via `uv run quellgeist diagnose`.
- [x] 4 offline CLI tests (scripted fake provider).
- [x] Commit: `feat(cli): quellgeist diagnose command`
- ⚠ Live acceptance (deploy → diagnose → postmortem; reset → insufficient-evidence) **NOT demonstrated** — model-gated.

### Task 9: Eval harness skeleton + first scenario + CI  ✅ DONE
- [x] Scenario schema + loader (`generator.py`); reuses `EvidenceRef` for `gold_evidence_refs`. Fixture at `evals/scenarios/fixtures/bad_deploy_0001.json`.
- [x] `run_evals.py`: **fixture-based** (NOT the live app); serves canned signals through the real server filter logic; injectable provider. `judge.py` = keyword/handle **STUB** (real LLM-judge = Wave 2; `fabrication_check.py` = Wave 2).
- [x] Failing test → `tests/evals/test_runner.py` (4 tests, mocked).  *(Gap: `run_all()`/`main()` untested.)*
- [x] `.github/workflows/evals.yml`: **keyless deterministic gate** (lint + `pytest`). Real-model eval = Wave 2, **key-gated** (DR-0012).
- [x] Commit: `feat(evals): harness skeleton + first bad-deploy scenario + CI`
- [x] Added: `pyproject` `[tool.pytest.ini_options] pythonpath = ["."]`.

**Wave 1 exit criteria:** the from-clean-clone demo path is built and unit-tested (37 tests) but **not yet demonstrated against a real model** (blocked by Gemini limit:0/503); CI runs the eval **harness** green (deterministic), not yet a real-model eval. **Gate: Wave 1 is not "closed" until one live Qwen run produces a correct evidence-cited postmortem AND the DR-0009 id-fidelity number is recorded.**

---

## Wave 2 — Reliability Core *(rolling — detail at wave start)*

**Objective:** make the headline reliability guarantee real on the bad-deploy class.
**Entry criteria:** Wave 1 exit met.
**Carry-forward blockers note:** Qwen id-fidelity run + live-log-path confirmation are prerequisites before Wave 2 coding.
**Rough tasks:** add the **verifier-model pass** (a stronger model — default Gemini's free API tier, Claude swappable — confirms cited evidence exists/supports each claim; downgrade or abstain otherwise); implement the **deterministic fabrication check** (every cited evidence item must exist in the real signals); add **abstention**; replace the judge stub with **LLM-as-judge on a rubric**; build a small **human-labelled gold subset** to validate the judge; set concrete reliability bars after a baseline; publish a CI reliability report/badge.
**Beyond the existing rough tasks:** (1) evals/fabrication_check.py — deterministic handle-lookup against the full real-signal set / gold_evidence_refs (fixes the cited_but_unseen proxy); (2) verifier pass — resolve the DR-0012 Gemini-vs-alternative question first; (3) real LLM-as-judge + human gold subset (replaces the keyword stub); (4) key-gated CI eval job (if secrets.GEMINI_API_KEY != '') + reliability report/badge; (5) carry-forward fixes from the output review (test run_all/main; validate since format; consider the stdio MCP client adapter). Keep the train/eval distribution-separation constraint front-and-centre.

**Progress (2026-06-25) — deterministic core done; model-coupled layers held as stubs (deliberate gate):**
- [x] (1) `evals/fabrication_check.py` — full-signal-set membership, fail-closed; wired into the harness so a fabricated handle fails the scenario (DR-0013). **Done, deterministic, tested.**
- [x] (2) verifier pass — **BUILT** (`agent/verifier.py`, DR-0016): resolves cited handles to real rows, asks the model if the evidence supports each cause, drops the unsupported, forces abstention if none survive; conservative; opt-in via `QG_VERIFY=1`. Model-agnostic (gemini-3.5-flash now, Qwen later). Offline-tested.
- [x] (3) LLM-as-judge — **BUILT** (`evals/llm_judge.py`, DR-0016): rubric verdict (correct_cause/evidence_valid/actions_sensible + score) vs gold; opt-in via `QG_JUDGE_LLM=1`. **Advisory only** — the deterministic keyword judge + fabrication check stay the keyless gate; rubric scores are unvalidated until a **human gold subset** exists. Offline-tested.
- [x] (4) model eval is **out-of-band** (`eval.yml`: manual + merges to main), key-gated, and **quota-tolerant** — an unreachable/walled backend SKIPs (exit 0), only a model that ran-and-failed reddens (DR-0015). `ci.yml` (keyless lint+test) is the sole PR gate. Model **pinned to `gemini/gemini-3.5-flash`** (the old default silently ran 2.0-flash). Reliability **report/badge: TODO** (still no real numbers — free tier may be walled).
- [x] (5) carry-forward: `run_all`/`main` tested; `since` format validated. stdio MCP client: still deferred (DR-0010).
- **Still open (block the *numbers*, not the build):** a **paced real run with a working key** to produce the first numbers (free tier viable with `QG_MIN_CALL_INTERVAL_S`, DR-0016); a **human-labelled gold subset** before the LLM-judge's scores are trusted; the **Qwen3-4B id-fidelity run** (the final reasoner; gemini-3.5-flash is the build/CI stand-in). Until a real run lands, **no real-model reliability numbers are quoted.**

**Key design constraint (from review):** keep the eval's *held-out* scenarios separate from anything used to tune prompts/model — see Wave 4 note on train/eval separation.
**Exit criteria:** on the bad-deploy class, correct cause #1 in a high majority of runs, **zero fabricated causes on the eval set**, validated judge. *(Build done — deterministic gate + verifier + LLM-judge all shipped; the first real run on Groq passed with zero fabrication, DR-0017. Still unmet and carried into Wave 3: a **validated judge** (human gold subset, judge ≠ reasoner) and a **measured reliability rate** across the ~50-scenario suite — one fixture is a smoke test, not a rate. The Qwen3-4B id-fidelity run against this harness also remains open.)*

### Wave 2 → Wave 3 boundary review (2026-07-01)

Ran the *Wave Review Checklist* (below) at the boundary:

- **What this wave taught us that changes downstream:** the model-agnostic design earned its keep — Gemini's free tier proved unusable from cloud CI (429 → 503 → timeout → invalid-key), and a one-env-var swap to Groq `llama-3.3-70b-versatile` produced the first real **PASS** with zero fabrication. Reading the *actual* diagnosis (not the score) caught a judge false-negative → DR-0017. Downstream effect: the LLM-judge stays advisory until a human gold subset exists, and Wave 3's first job (parameterised generation) is what unblocks the rate, the gold subset, and the judge validation.
- **Docs brought current (this review):** the README (was "Wave 1 / 44 tests / Wave 2 deferred") and the brief's "evals on every push" language were stale relative to the merged Wave 2 build + DR-0015/DR-0017; both synced. The ADR log's DR-0011/DR-0012 body-header transposition (labels swapped relative to the index) was corrected.
- **Cut/defer check:** no scope cut this boundary; Wave 6 (resolution-verification) remains the cut-first item.
- **Decisions unchanged:** no locked decision changed at this boundary, so no new DR was opened for the sync — DR-0008 (Qwen default), DR-0009/DR-0013 (handles + fabrication check), DR-0016 (verifier/judge built), and DR-0017 (cite-based judge + Groq in CI) all still hold. Next id remains **DR-0018**.
- **Next wave:** Wave 3's objective + rough tasks are below; they get re-scoped to full task/step detail at Wave 3 kickoff (the immediate next step). **Start with parameterised scenario generation** (`generator.py::generate_scenarios`) — it unblocks the reliability rate, the human gold subset, and the judge validation. Keep the train/eval **distribution-separation** constraint (DR-0003) front-and-centre from the first generated fixture, and build the held-out set (`evals/scenarios/holdout/`) from a *different* distribution than the tuning set.

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
