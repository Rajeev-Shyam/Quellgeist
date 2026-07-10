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

## Wave 3 — Breadth: Classes 2 & 3 + Metrics

**Status: COMPLETE (2026-07-01). Outcome: 3 classes across a 65-scenario suite; first full rate 61/65 · 0 fabricated (Gemma-4-31B stand-in, `wave3-reliability-rate.md`); judge validated at kappa 0.81 (DR-0018, `wave3-judge-validation.md`).**

**Objective:** add config/env-var and resource-exhaustion classes; bring metrics online.
**Entry criteria:** Wave 2 reliability bar met on class 1.
**Rough tasks:** build the **metrics MCP server** + real Prometheus counters in the demo app; chaos scripts for config/env and resource-exhaustion; extend `generator.py` to **parameterised generation** (templates → variants) toward ~50 scenarios across the three classes; re-validate the judge on a gold subset spanning all classes.
**Exit criteria:** all three classes pass their reliability bars; ~50-scenario suite green in CI. *(Met — see the Wave 3 exit table in `wave3-reliability-rate.md`. Known deferrals: the demo's live resource-exhaustion chaos script is unwired (the eval path via scenario `metrics` is fully wired and tested), and the stdio MCP client adapter remains deferred, DR-0010.)*

### Wave 3 → Wave 4 boundary review (2026-07-02)

Ran the *Wave Review Checklist* (below) at the boundary:

- **What this wave (and the bridge into Wave 4) taught us that changes downstream:** (a) the model-agnostic thesis held again — Groq's daily quota exhausted mid-wave and a one-env-var swap to Cerebras produced the merged 61/65; (b) development moved to a machine with a local GPU, so **local serving via Ollama is now real** (Ollama 0.31.1 + pinned `qwen3:4b-instruct-2507-q4_K_M`, ~6.3 s/scenario on an RTX 5060 8GB, $0, fully offline) — the serving leg of DR-0004 is no longer deferred; (c) the **base Qwen3-4B baseline is measured** (DR-0019): 0/65 fixtures · 0/16 holdout · **zero fabrication across all 81** — reliably safe, completely ineffective, failure mode = speculative filtering. The cost story now has an honest floor and a specific behaviour for the fine-tune to fix.
- **Docs brought current (this review):** the brief's build-sequence statuses (Wave 3 was still "current"), the README status/roadmap/tool count, and this plan's Wave 3 status line. A real gap found by auditing the docs against the code: the CLI wired only two of the three tools (`query_metrics` was missing from `quellgeist diagnose` while the eval path had it) — fixed with a regression test.
- **Cut/defer check:** Wave 6 (resolution-verification) remains the cut-first item. The training-data trajectory format gets its own DR before anything is built (it shapes what the fine-tune learns; not a detail).
- **Decisions:** DR-0019 opened (baseline + pinned serving artifact; refines DR-0008). Next id **DR-0020**.
- **Next wave:** Wave 4 is re-scoped to task detail below. The holdout has now been *evaluated* (its purpose) but never tuned on — keep DR-0003's separation absolute: **train on the fixtures distribution, compare on the holdout.**

## Wave 4 — Cost / Fine-tune *(COMPLETE — 2026-07-06; see the boundary review below)*

**Objective:** the cost thesis with a measured (honest) result — *fine-tuned local Qwen3-4B + verifier ≈ frontier-only quality at a fraction of the cost* (a hypothesis to test, not a promise).
**Entry criteria:** stable base-model behaviour + evals from Wave 3 — met.
**Critical (from review):** the **holdout must come from a different distribution than the fine-tuning data** (DR-0003, as refined by DR-0020: the fixtures share the training bank by design, so the post-tune fixtures number is a same-bank diagnostic, not a generalisation eval), or the headline number measures memorisation, not skill. The holdout exists (16 scenarios, disjoint token banks) and is selected only explicitly (`QG_SCENARIOS_DIR`).

### Task 1: Baseline the intended reasoner  ✅ DONE (DR-0019)
- [x] Pin the local serving artifact: Ollama `qwen3:4b-instruct-2507-q4_K_M`, `QG_MODEL=ollama_chat/…` — env-only swap, no code change.
- [x] Measure base Qwen3-4B under the Gemma run's conditions: **fixtures 0/65 · 0 fabricated; holdout 0/16 · 0 fabricated** (`wave4-qwen-baseline.md`).
- [x] Harness: `QG_SCENARIOS_DIR` selects the holdout explicitly; CLI tool-surface gap fixed (`query_metrics`).

### Task 2: Training data from the generator *(built — awaiting human review of the sample)*
- [x] **DR-0020 (Accepted, provisional — design PR #13): trajectory format.** Decided: full ReAct trajectories in the exact runtime message shapes (messages-array JSONL, per-turn loss masking), programmatic teacher-free synthesis from a fresh-seeded fixtures-bank train split, abstention *founded* (15–25%, abstain-after-investigation, hard variants ≥50% of abstain mass, contrastive near-pairs) + trap examples, fail-closed build gates incl. a citation-prefix check stricter than the fabrication check, and pre-registered claims wording (the deterministic gate has a measured script ceiling: a positional policy passes 81/81). See the DR for the full decision, incl. the two never-trained probe sets (abstention recall; structure perturbation).
- [x] **Builder built (`evals/training/`)**: `python -m evals.training.build` deterministically emits 316 trajectories (abstain 19%, hard-abstain 60%, near-pairs 33%, traps 10%) from the **fixtures distribution only** (train split seed 20260703, `train_` namespace — not the 65 committed fixtures), replayed through the REAL `run_loop` so every message is byte-identical to inference; artifacts live outside `evals/scenarios/`; both probe sets committed (12 abstention + `run_abstention_probe` runner; 10 structure — the culprit-not-newest items provably defeat the positional script).
- [x] Mechanical acceptance (CI-enforced): zero holdout contamination + fixtures-readout integrity (id + expanded-token-bank boundary scan + sha sets, run against the committed corpora incl. the hand-authored anchor; metric-name disjointness vs the holdout); deterministic rebuild; build gates green on 100% of examples. Tests 129 → 159 (the generator's per-split invariant tests now also cover the train/probe splits).
- [x] Human review of the committed 20-trajectory sample (`evals/training/sample_trajectories.jsonl`) — reviewed via the merged Task-2 builder PR. **Task 2 complete.**

### Task 3: QLoRA fine-tune (user-run: local PoC → cloud)
- [x] **Pipeline prepared (`finetune/`, runbook in its README):** CPU preflight (`prepare.py` vendors the official Instruct-2507 chat template — asserting no think-scaffolding — masking-audits all 316 rendered examples with the same code `train.py` trains with, and replaces the char-based length estimates with real BPE counts), shared rendering+labeling module, QLoRA train/export script (r=16, 2 epochs, no packing, Q4_K_M GGUF), hand-authored Modelfile writer (ChatML template parity-checked against the Jinja render; num_ctx pinned; repeat_penalty 1.0 across cells).
- [x] **User-run:** local PoC / T4 smoke — done on a free Colab T4 (loss 1.40→0.36 over 30 steps, no OOM at batch 1 × grad-accum 16 × seq 4096); Blackwell path skipped as planned.
- [x] **User-run:** real run (2 epochs, loss→0.16), Q4_K_M GGUF exported, `ollama create` + serving checklist passed (ChatML template non-blank, eos=151645, broad-`query_logs` smoke). Vendored template + render report reproduced byte-identically at preflight (already committed).

### Task 4: The comparison matrix (the headline)
- [x] **Tooling built (`evals/matrix/`)**: `run_cell` (one cell = model × verifier × scenario set × ≥3 passes; the DR-0020 §8 verifier pin is fail-closed — unpinned or self-identical verifier is a config error, not a warning; per-scenario cost from the backend's real usage reports; `cell.json` written only on completion, and stale artifacts cleared at start, so a partial run can't read as a measurement), `audits` (unobserved tool-call args; fixtures-bank tokens + train-seen timestamps on holdout traces; the core-overlap split — the DR's 21/65 fixtures overlap and 258 train cores are recomputed as permanent tests), `report` (cross-cell markdown with a `passes×steps`/`conditions` column that flags any ablation cell so it can't blend into a same-conditions table, and the pre-registered claims wording verbatim in the footer). Tests 159 → 178. Adversarially reviewed (measurement-integrity pass); **known, accepted limitations, stated not implied:** (a) `--passes` defaults to 3 but is not itself fail-closed — a `<3`-pass cell runs and is *flagged* in the report rather than refused (an intentional escape for smokes/ablations); (b) the verifier pin is exact model-string equality, so two litellm aliases for one artifact would slip past — pin to a different family (the BASE artifact), not a re-spelling; (c) the unobserved-args and train-timestamp audits are computed and their *results* persisted per scenario, but full observation transcripts are not stored, so those two audits are re-verifiable only by re-running the cell (the bank-token audit is recomputable from the stored `tool_calls`). The measured **runs** below remain open.
- [x] Fine-tuned vs base vs the Gemma-4-31B frontier stand-in (`cerebras/gemma-4-31b`), with/without verifier, on cost AND quality, primary axis = the holdout, 3 passes/cell. **Result: base 0/16 → tuned 12/16; frontier 10/16 (directional); `wave4-qwen-finetune.md`.** (Frontier numbers are directional — single/two-pass — a fully-logged 3-pass frontier column is a Wave-5 follow-up.)
- [x] Instrument real per-scenario token/call counts during these runs (observation sizes, loop turns, verifier calls) — measured cost, not estimates. *(Instrumentation shipped with the tooling: `CallUsage` records on the provider, read as per-scenario deltas by `run_cell`; the numbers land with the runs.)*
- [x] Measurement integrity (DR-0020): verifier pinned to the BASE artifact in every cell; trace audits clean on all tuned cells (0 unobserved/bank/timestamp violations vs the base's ~281/pass); fixtures reported core-split (overlap 0.71 n=21 / fresh 0.75 n=44); abstention + structure probes run (0/12 model · 6/12 system; 7/10); pre-registered claims wording applied throughout.

### Task 5: Publish
- [x] Case study (`wave4-qwen-finetune.md`) + README cost story updated — the honest two-sided result: frontier-competitive capability at $0, `resource_exhaustion` unlearned, and adversarial abstention a frontier-shared 6/12 ceiling.

**Exit criteria:** a published, honest cost/quality comparison across the holdout — **met** (`docs/case-studies/wave4-qwen-finetune.md`).

### Wave 4 → Wave 5 boundary review (2026-07-06)

- **Result:** the DR-0020 QLoRA fine-tune of Qwen3-4B, trained on a free Colab T4 and measured with `evals/matrix`. Base **0/16 → tuned 12/16** on the reserved holdout, **0 fabrication**, **0 speculative-filtering** (base ~281/pass), and *cheaper* than the base (3,439 vs 7,558 reasoner tok/scenario; 3.1 vs 7.8 calls). Non-memorisation triangulated three ways (fixtures 0.74 ≈ holdout 0.75; core-fresh 0.75 ≥ core-overlap 0.71; structure probe 7/10 with real culprit-not-newest reasoning). Full write-up: `docs/case-studies/wave4-qwen-finetune.md`.
- **What this wave taught us that changes downstream:** (a) the fine-tune installs a policy an untuned 31B frontier does *not* follow — the Gemma-4-31B stand-in scored **10/16** on the same holdout (below the tuned 4B) with 77 speculative-filter violations, so the tuned local 4B is **frontier-competitive at $0**; (b) **adversarial abstention is an unsolved, shared ceiling** — the tuned+verifier system's 6/12 recall *equals* the frontier's own 6/12, catching complementary traps (frontier: timing; verifier: evidence-absence), which points at a timing-aware verifier as a future upgrade; (c) the tuned model's *intrinsic* abstention collapsed to 0/12 (the verifier is load-bearing), and one class (`resource_exhaustion`) did not transfer at all (0/N; the frontier passes it) — a training-coverage gap.
- **Acceptance vs DR-0019/DR-0020:** holdout > 0/16 ✅ (12/16); fabrication 0 everywhere ✅; abstain recall ≥ 90% ❌ (0/12 model, 6/12 system — but frontier-parity; the bar is unmet by *every* configuration, a task-hardness finding, not a fine-tune-specific failure).
- **Docs brought current (this review):** this plan (Task 3/4/5 ticked, Wave 4 closed, Wave 5 promoted to current), the ADR log (DR-0019/DR-0020 marked measured), the README status/roadmap/cost story, and the new fine-tune case study.
- **Cut/defer check:** Wave 6 (resolution-verification) remains the cut-first item. Two follow-ups logged for Wave 5+: a fully-logged 3-pass frontier column (this wave's frontier numbers are directional), and a targeted `resource_exhaustion` trajectory-mix + a timing-aware verifier (DR-0021 territory, deferred).
- **Next wave:** Wave 5 (Polish & Ship) — re-scoped to full task/step detail at kickoff; strong enough to launch on the tuned model.

## Wave 5 — Polish & Ship *(current — re-scoped to task detail 2026-07-07)*

**Objective:** make it adoptable and launch it. The *widest* wave by task count
but the *shallowest* by risk — bounded engineering + launch work, no research
uncertainty. Ship on the tuned model (Wave 4 done).
**Entry criteria:** Wave 4 complete (tuned model measured, case study published) — met.
**Ordering (recommended):** security pass first (a responsible-publish prerequisite,
CI-shaped and high-confidence) → HTML postmortem render (self-contained, demoable)
→ MCP Registry + OIDC auto-publish (the real new engineering) → launch last. Docs
(architecture doc + polish) run alongside; much is already done.

### Task 1: Security pass on the published MCP servers *(do first — publish prerequisite)*
- [x] **Scanners wired into CI** as their own `security` workflow (kept off the
      deterministic merge gate so a new advisory never blocks an unrelated merge):
      `bandit -r src/` (the one B311 hit — retry-backoff jitter, not crypto —
      annotated `# nosec B311` at its call site) and `pip-audit --skip-editable`
      (bumped `pydantic-settings` 2.14.1→2.14.2 to clear GHSA-4xgf-cpjx-pc3j). Both
      keyless and green; pinned via a `security` dependency group.
- [~] `semgrep` — **skipped for now**: bandit + pip-audit cover the static + CVE
      surface on this small read-only codebase; revisit only if a gap appears (don't
      stack redundant tools).
- [ ] Run an **MCP-specific scanner** (`mcp-scan` / Cisco `mcp-scanner`) against the
      three servers live — **documented as a pre-release step in `SECURITY.md`** (it
      needs a running server, so it is not a CI step); run it and keep the clean
      report at publish time (Task 4).
- [x] **`SECURITY.md` threat-model section** added (DR-0005): least privilege
      (read-only, no state mutation), scoped access (one operator-configured file per
      server; tool args never choose the path → no traversal), no SSRF (no network
      client anywhere in `servers/`), and input validation (`since` canonicalised; no
      SQL/shell/template injection surface) — each grounded in the actual code.
- **Acceptance:** scanner job green (or a documented, justified allowlist);
  MCP-scanner report clean; `SECURITY.md` threat model merged; DR-0005 closed.

### Task 2: HTML postmortem render *(Markdown already ships)* ✅ DONE
- [x] Added the **HTML** target: `render_postmortem_html` + `write_postmortem(fmt=…)`
      — a self-contained, style-inlined, light/dark-aware page (no external assets),
      deterministic and model-free. Both formats read the same `Diagnosis` fields and
      share the one `_render_evidence` helper (a parity test guards drift). CLI
      `--format md|html`; `--out` infers from the extension; stdout stays Markdown.
- [x] Unit-tested (self-contained page, evidence handles, abstained case, HTML
      escaping of model-authored text, md/html parity, extension inference). Tests
      179 → 187. Live web UI stays **deferred to post-v1**.
- **Acceptance:** `quellgeist diagnose … --out postmortem.html` writes a valid
  standalone page; tests cover it; deterministic gate green. **Met.**

### Task 3: Docs — architecture doc + polish *(largely pre-done)* ✅ DONE
- [x] `docs/architecture.md` written: component + sequence diagrams, the
      loop → tools → verifier → postmortem pipeline, the model-agnostic seam
      (`QG_MODEL`), the layered reliability guards, the read-only tool posture, the
      train/holdout separation, and a module map — each linked to its DR.
- [x] README polish: architecture-doc pointer + HTML-output note added; a `security`
      workflow badge added; status/roadmap/cost story current post-Wave-4; the
      fine-tune + Wave 0/2/3 case studies are linked.
- **Acceptance:** architecture doc merged and linked from README. **Met.**

### Task 4: Publish the MCP servers *(the meatiest genuinely-new chunk)* — scaffolding done; publish is user-gated
- [x] **`server.json` authored** per the registry schema (`2025-10-17`) for all three
      servers (`mcp/{logs,commits,metrics}/server.json`): reverse-DNS names under
      `io.github.Rajeev-Shyam/*`, PyPI package `quellgeist`, `uvx` runtime, stdio
      transport, env-var docs. Console entry points added so each is `uvx --from
      quellgeist quellgeist-<x>-mcp`; PyPI ownership `mcp-name:` markers in the README.
- [x] **CI auto-publish wired** via GitHub **OIDC** — `publish-mcp.yml`
      (`mcp-publisher login github-oidc` → publish each manifest) + `publish-pypi.yml`
      (PyPI Trusted Publishing). Both **tag-gated** (`v*`), no stored secret.
- [ ] **User-gated to finish (see `docs/publishing.md`):** claim the PyPI name +
      register the trusted publisher; `mcp-publisher publish --dry-run` to confirm the
      manifest against the live schema; cut a `v0.1.0` tag; then claim the
      **Glama / PulseMCP / mcp.so** listings.
- **Acceptance:** a tag push publishes to PyPI + the MCP Registry via OIDC with no
  stored secret; listings claimed. *Scaffolding met; awaits the release tag.*

### Task 5: Launch *(last)* — copy drafted; posting is user-gated
- [x] **Launch copy drafted** (`docs/launch.md`): GitHub release notes, Show HN,
      r/mcp, r/LocalLLaMA, Product Hunt, and a PulseMCP newsletter pitch — all
      leading with the security-first + abstain-over-hallucinate thesis and the
      $0-offline frontier-competitive result, with the named gaps stated (claims
      discipline). Includes a pre-launch checklist.
- [ ] **User-gated:** make the repo public, verify the clean-clone demo, cut the
      release, and post (space the channels out). Send the PulseMCP email.
- **Acceptance:** launch posted; evals/badge live; repo public and demo-runnable.
  *Copy ready; posting awaits the user.*

**Exit criteria:** public repo, runnable demo, evals/badge live, server(s)
registered, launch posted. After Wave 5, only Wave 6 (resolution-verification,
cut-first) remains — **Wave 5 is the last required wave before a shippable v1.**

**Status (2026-07-07):** all five tasks' *engineering* is complete — security pass
(Task 1, merged), HTML render (Task 2), architecture doc + README polish (Task 3),
publish scaffolding (Task 4), launch copy (Task 5). What remains is **user-gated
and outside code**: claim the PyPI name + register the trusted publisher, cut a
`v0.1.0` tag (fires the OIDC publish workflows), claim the ecosystem listings, make
the repo public, and post the launch. v1 is one release tag away.

**Post-review hardening (2026-07-07):** a six-lens review (dev/architect/perf/
security/QA/PM) found no blocker bugs. Fixes landed: robustness (JSON parser,
verifier fail-closed, negative-limit, CLI clean errors + a keyless run silenced
from 86 lines to 2), a docs-honesty sweep (badge/test-count/CONTRIBUTING/model
reachability), supply-chain hardening (SHA-pinned actions, checksum-verified
`mcp-publisher`, workflow `permissions`, scoped sdist), GitHub scaffolding, and the
three high-value refactors: a FastMCP-free single-sourced tool contract (CLI import
627→172 ms, closes the train/serve description skew), a canonical evidence-handle
accessor, and a keyless `quellgeist diagnose --demo`. 179 → 198 tests.

**Backlog carried in from Wave 4 (do NOT block the launch on these):** (a) a
fully-logged 3-pass frontier column — Wave 4's `gemma-4-31b` numbers are
directional; re-run both frontier cells off-GPU (API-only) to promote them and
regenerate `matrix-report.md`; (b) a targeted `resource_exhaustion` trajectory-mix
+ a timing-aware verifier — a **new training decision (DR-0021), out of scope for a
polish-and-ship wave.** Don't reopen training inside Wave 5.

## v1.1 (post-v1) — Real-data ingestion + robustness *(shipped 2026-07-09; DR-0022)*

**Scope:** broaden v1 from "diagnoses three hand-authored files" to "point it at
your real incident," without touching the frozen DR-0020 measurement surface (tool
descriptions, evidence schema, corpora, observation format, `filters`). Motivated by
three reproduced real-data failures: a single non-JSON line crashed `query_logs`; no
observation cap (a 5k-line log → ~277k tokens in one turn); rigid `…Z`-only timestamps.

**Shipped:**
- `src/quellgeist/ingest/` — field-alias + timestamp/level normalisation and tolerant
  readers for real logs (file/dir; JSONL/JSON/plain-text/mixed/malformed), deploys
  (JSON / GitHub payload / `git log` text), and metrics (Prometheus / canonical array),
  with source-stable id assignment (DR-0009). Value-preserving on canonical rows
  (guarded test: the whole fixture suite round-trips unchanged).
- `quellgeist ingest` — writes the three canonical files + copy-pasteable next-steps.
- Real-file robustness in `servers/tools` (CLI/MCP path only): tolerant log reading +
  a most-recent-N observation cap (`QG_MAX_ROWS`/`QG_MAX_POINTS`); commits/metrics
  readers stay strict (DR-0009 "surface real corruption").
- The deterministic fabrication check relocated into the installed package
  (`quellgeist.agent.citations`; `evals` re-exports it), and wired into
  `quellgeist diagnose` (warn by default; `--strict-citations` → exit 3) so the
  cite-or-abstain guarantee runs at real-use time.
- A deterministic real-shaped E2E harness (`tests/e2e/`) proving no-crash, bounded
  observation, correct cited diagnosis, and zero fabrication on messy data. 198 → 247
  tests; ruff + black + bandit green.

**Deferred (non-blocking):** a streaming reader for multi-GB logs; more ingest adapters
(journald, Datadog, OTLP) as real users ask; an optional in-loop citation verifier.
Training decisions (DR-0021 corpus revision; resource_exhaustion trajectory-mix) remain
unopened — this increment is deliberately not a training change.

## v2 (Wave 7+) — Live incident-response service + generalisation track *(scoped 2026-07-09; DR-0023)*

**Program decision:** [DR-0023](quellgeist-adr-log.md). **Design spec:**
[`quellgeist-v2-spec.md`](quellgeist-v2-spec.md). **Execution brief (how):**
[`quellgeist-v2-session-brief.md`](quellgeist-v2-session-brief.md).

v2 wraps the proven v1 core in a **live, concurrent, observable incident-response
service** (signed webhook → worker pool runs the *unchanged* `run_loop` → persisted
run + cost → HITL review gate → Slack + HTML → sandbox resolution re-check), plus a
parallel reliability track (timing-aware verifier; out-of-structure generalisation
eval). **Two additive tracks, not a rewrite — the frozen DR-0020 measurement surface
is never touched** (enforced by `tests/frozen/test_frozen_surface.py`, landed in the
setup session). All v2 code lives in new modules: `service/`, `orchestrator/`,
`store/`, `observability/`, `notify/`, and new eval dirs.

Rolling-wave discipline: only the current wave is detailed to task level. Each wave's
DR (DR-0024…DR-0027) opens at kickoff via the **writing-plans** flow; the boundary
checklist runs at its close.

| Wave | Scope | Status |
|---|---|---|
| **7** | Service spine: `store` (SQLite WAL) + `observability` + `service` (signed webhook, healthz) + worker pool + isolated snapshots + run persistence + the frozen-surface guard | ✅ built — signed webhook → concurrent workers → persisted cited runs; incident-scoped tool closures for isolation; 254 → 274 tests; frozen diff empty |
| 8 | Output + HITL: `notify` (Slack + HTML), review gate (approve/steer/reject), hint-at-trigger | ⏳ scoped |
| 9 | Resolution-verification (Wave-6 content, sandbox only) + Dockerfile + `compose.yml` + SECURITY.md | ⏳ scoped |
| 10 | Track B (parallel): timing-aware verifier (DR-0024) + structure-varied/out-of-structure evals (DR-0025) + optional `resource_exhaustion` mix (DR-0026) | ⏳ scoped |

**Setup landed (pre-Wave-7):** the three v2 docs (DR-0023, spec, brief), this plan
section, `tests/frozen/test_frozen_surface.py` (the anti-drift guard — golden tool-string
hash + schema field order + observation/retry format), `.env.example`, and new-module
scaffolds.

**Wave 7 built (T7.1–T7.5):** `store` (SQLite WAL + migrations + DAO), `observability`
(contextvar correlation ids + structlog JSON + `summarize_usage` over the existing
`CallUsage`, no edit to `providers.py`), `orchestrator` (`investigate`: run the frozen
loop → deterministic fabrication check → persist trace+cost → `pending_review`), and
`service` (async FastAPI: HMAC-signed `POST /incidents`, idempotent, per-incident signal
snapshots, bounded worker pool running the sync loop in a thread executor; `GET /healthz`;
`GET /incidents/{id}` JSON status). **Key design decision (refines the spec's env
hand-wave):** the worker builds **incident-scoped tool closures** bound to the snapshot
dir instead of mutating process-global `os.environ` — the only thread-safe way to isolate
concurrent incidents; reuses the frozen tool-description strings + `ingest`/`filters`,
touching nothing frozen. Fail-closed (empty webhook secret rejects all; a fabricated
citation is persisted, not posted). Live uvicorn boot verified; frozen diff empty.

**Six-persona review + fixes (2026-07-09, post-merge):** senior architect / QA / acceptance
/ security / SWE / PM reviewed Wave 7. Fixes landed (all additive, frozen surface still
untouched): **incident_id path-traversal validation** (`^[A-Za-z0-9_-]{1,128}$`), non-object
JSON body & non-string hint → 400 (were 500), **request body size cap** (413) + **bounded
queue**, **create-before-snapshot ordering + atomic snapshot** (no torn-snapshot race),
**terminal-state guarantee** in `investigate` (a persistence failure yields a `failed`
incident with the diagnosis preserved in the event log — never stuck at `running`),
**graceful worker-pool drain** on shutdown (no orphaned executor thread), **event-loop
offload** of all blocking SQLite/file work (`asyncio.to_thread` + sync GET), structlog
config precedence, usage captured on failed runs, `_now` de-duplicated, lazy `app` build.
274 → 284 tests; ruff+black+bandit green.

**Carried into Wave 8 (from the PM review — do NOT ship posting without these):**
- **T8.0 (prerequisite): wire the base verifier (`agent.verifier.verify`) into
  `orchestrator.investigate` before any auto-post.** The live path is currently
  *fabrication-checked only*; DR-0023 marks the verifier "load-bearing" for the system-level
  6/12 abstention number, so posting an unverified diagnosis would ship the intrinsic 0/12
  behaviour under a verified-reliability claim. Pin the verifier separately (never
  `QG_MODEL`; DR-0016).
- **Operator-endpoint auth**: `GET /incidents/{id}` is currently unauthenticated (exposes run
  metadata) and the webhook has no replay window — both are Wave-8 items alongside the HTML
  review UI (add a shared-secret/session check + an `X-Quellgeist-Timestamp` freshness bound).
- **Verify the combined v1+v2 launch decision** at the boundary (v1 Wave-5 launch tasks are
  still user-gated).

### Wave 8 — Output + HITL *(SHIPPED; DR-0027)*

Additive only; frozen surface byte-locked (guard green); deterministic keyless gate green.

- **T8.0 — verifier in the live path.** `investigate()` runs `agent.verifier.verify` after
  the fabrication check with a **separately-pinned** provider (`QG_VERIFIER_MODEL`, never
  `QG_MODEL` — DR-0016; `ServiceConfig.make_verifier_provider` returns `None` when the model
  is unset or equals the reasoner). The verified diagnosis is persisted in
  `diagnoses.verified_json` and is the ONLY postable artifact. A verifier outage leaves the
  run *unverified* (recorded, reviewable, not postable) rather than failing it.
- **T8.1 — `notify`, fail-closed.** `notify.publish` writes the postmortem HTML (reuses
  `output.postmortem.render_postmortem_html`) and posts to Slack (`QG_SLACK_WEBHOOK_URL`,
  injectable poster seam); refuses a fabricated diagnosis (`PublishRefused`).
- **T8.2 — review gate + operator surface.** `orchestrator.review.apply_review` drives
  `pending_review → approved|steered|rejected → posted`, auditing every transition in
  `events`; approve→post (fail-closed: refuses fabricated OR unverified), reject→nothing,
  steer→re-run `investigate` with the steer as a hint. `GET /incidents/{id}` is the HTML page,
  `POST /incidents/{id}/review` drives the gate — both **bearer-auth-gated**
  (`QG_OPERATOR_TOKEN`, fail-closed); JSON polling moved to `GET /incidents/{id}/status`.
- **T8.3 — hint at trigger.** `orchestrator.hint.HintProvider` wraps the run provider and
  injects the operator hint as one extra message on the first `complete()` — the frozen loop
  is untouched. Between-steps injection stays out (stretch).
- **Review fold-ins shipped:** operator-endpoint auth (above) + an opt-in webhook replay
  window (`X-Quellgeist-Timestamp` freshness folded into the HMAC, `QG_WEBHOOK_MAX_SKEW_S`).
- **Known limit (honest):** snapshot disk-bounding is complete for `failed`; `pending_review`
  snapshots persist for review/steer and are reaped when Wave 9 adds `posted`/`rejected` reaping.

**Next:** Wave 9 = resolution-verification (`verify_resolution`, sandbox) + Dockerfile/compose;
Track B (DR-0024–0026) unchanged. Verify the combined v1+v2 launch decision at the boundary.

## Wave 6 — Resolution-verification Loop *(pulled into v2 Wave 9; DR-0023 decision 6)*

**Objective:** after a controlled fix is applied in the sandbox, the agent re-reads signals and confirms recovery. No autonomous prod mutation.
**Status:** no longer cut-first — **in scope for v2 as Wave 9** (`orchestrator.verify_resolution`, sandbox-only). Original note preserved: pure upside; the DR-0001 no-prod-mutation boundary holds.

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
