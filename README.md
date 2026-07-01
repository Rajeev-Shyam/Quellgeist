# Quellgeist

[![ci](https://github.com/Rajeev-Shyam/Quellgeist/actions/workflows/ci.yml/badge.svg)](https://github.com/Rajeev-Shyam/Quellgeist/actions/workflows/ci.yml)
[![reliability](https://img.shields.io/badge/reliability-61%2F65%20·%200%20fabricated-brightgreen)](docs/case-studies/wave3-reliability-rate.md)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Python 3.12+](https://img.shields.io/badge/python-3.12%2B-blue.svg)](https://www.python.org/downloads/)

> First-line incident triage you can trust: ranked root-cause hypotheses where **every claim cites a real evidence handle** — and the agent **abstains rather than guess**.

Quellgeist is a model-agnostic AI agent for first-line production-incident triage.
It runs a legible JSON-action ReAct loop over read-only tools (structured logs +
recent deploys + metric time-series), then emits a structured **Diagnosis**:
confidence-ranked root-cause hypotheses, each backed by a structured evidence
handle (`LogRef.id` / `CommitRef.sha` / `MetricRef.id`) the agent actually saw —
never free text. Two ideas set it apart:

- **Cite-by-structured-handle.** Evidence is a checkable handle, not a sentence,
  so a fabricated citation is *measurable* and **deterministically rejected** by a
  keyless fabrication check — not a matter of fuzzy string-matching.
- **Abstain-over-hallucinate.** A confidently-stated wrong cause is the worst
  possible answer, so *"insufficient evidence"* is a first-class outcome.

> **Status: WIP — Wave 4 in progress (cost / fine-tune).** All three failure
> classes generate and gate across a 65-scenario suite; the best full run is
> **61/65 passed, 0 fabricated** (Cerebras Gemma-4-31B; `resource_exhaustion` a
> clean 15/15), and the advisory **LLM-judge is validated** at **Cohen's kappa
> 0.81**. The Wave-4 baseline is now measured: the intended local reasoner (base
> Qwen3-4B via Ollama) scores **0/65 fixtures · 0/16 holdout — with zero
> fabrication across all 81**: reliably safe, not yet useful, the honest floor
> the fine-tune must beat (DR-0019). When this agent misses it's *incomplete* or
> *too cautious*, never confidently fabricating. See
> [Status & roadmap](#status--roadmap) · [baseline case study](docs/case-studies/wave4-qwen-baseline.md).

## Why it's different

| | |
|---|---|
| **Evidence is a handle** | Each hypothesis cites a log row's source-stable `id` or a commit `sha`, copied verbatim from a tool result — the unit the deterministic fabrication check looks up. Prose lives in a display-only `note`. (DR-0009) |
| **Abstention is a feature** | When signals are weak the agent returns `abstained=true` with a reason and an empty hypotheses list — enforced by the schema. |
| **Model-agnostic by construction** | The loop parses JSON actions from plain chat text, so it's identical on Gemini's free tier and a local 4-bit Qwen — no dependence on any backend's native function-calling. Swap models with one config change. (DR-0008, DR-0010) |
| **Reliability is gated, not asserted** | A keyless, deterministic CI gate (ruff + black + `pytest`, including the fixture-backed eval harness) runs on every push. |

## Quickstart (~30 seconds)

Requires [uv](https://docs.astral.sh/uv/) and Python 3.12+.

```bash
uv sync                                   # 1. install deps into a venv

uv run uvicorn demo.app.main:app          # 2. start the toy service (leave running)

# --- in a second shell, from the repo root ---
uv run python -m demo.chaos.bad_deploy    # 3. inject a simulated bad deploy
curl -s localhost:8000/login              # 4. trip /login -> 500s + structured error logs
uv run quellgeist diagnose --show-trace   # 5. diagnose (needs a model; see below)

uv run python -m demo.chaos.reset         # back to a green slate
```

Step 5 needs a reasoner — see [Running the model](#running-the-model). Without a
key, `quellgeist diagnose` degrades to a one-line error and exit 1 (never a
traceback); the [example session](#example-session) below shows the output shape
rendered deterministically from a fixture.

## Architecture

A custom, legible loop is the orchestration layer; the three read-only tools are
the evidence interface; the `Diagnosis` schema is the contract that the
postmortem renderer and the eval judge both read.

```mermaid
flowchart TD
    trigger(["incident trigger - CLI"]) --> loop
    model["reasoner via LiteLLM<br/>(Gemini or local Qwen, swappable)"] -. "chat completion" .-> loop

    subgraph loopbox["model-agnostic JSON-action ReAct loop"]
      loop["run_loop()<br/>decide, call tool, observe, repeat"]
    end

    loop -- "query_logs" --> logs["logs tool<br/>structured JSONL, stable ids"]
    loop -- "get_recent_commits" --> commits["commits tool<br/>deploy_log.json, shas"]
    loop -- "query_metrics" --> metrics["metrics tool<br/>time-series, named series"]
    logs -- "rows + ids" --> loop
    commits -- "commits + shas" --> loop
    metrics -- "series + names" --> loop

    loop --> diag["Diagnosis (schema.py)<br/>ranked hypotheses citing<br/>LogRef.id / CommitRef.sha / MetricRef.id, or abstains"]
    diag --> pm["postmortem renderer<br/>deterministic Markdown"]
    diag --> judge["eval judge<br/>fixture scenarios, CI gate"]
```

All three tools are also exposed as **MCP servers** over stdio
(`python -m quellgeist.servers.logs_mcp`, `…commits_mcp`, `…metrics_mcp`). The
agent currently reuses the same tool *functions* in-process behind a `ToolSpec`
registry; a stdio MCP-*client* path (the agent driving the servers over the
wire) is on the roadmap (DR-0010).

## Example session

Inject the bad deploy — it drops a marker that flips `verify_token` into a
NoneType regression and writes a `deploy_log.json` whose offending commit landed
just before the errors (real `stdout`, paths shown relative to the repo root):

```text
$ uv run python -m demo.chaos.bad_deploy
injected bad deploy a1b2c3d (touched demo/app/auth.py) at 2026-06-24T12:22:43Z
  marker:     demo/.bad_deploy
  deploy log: demo/deploy_log.json
next: hit /login to generate the 500s, then `quellgeist diagnose`
```

With a reasoner configured, `quellgeist diagnose` reads the logs + deploys and
emits a postmortem. The CI environment has no validated model key (DR-0012), so
the diagnosis below is **rendered from gold** — built deterministically from the
fixture's labelled cause and evidence handles via `render_postmortem`, *not*
live model output:

```text
# Incident Postmortem (rendered from gold)

## Root-cause hypotheses

### 1. Bad deploy a1b2c3d (10:01:50Z) refactored auth.py and introduced a NoneType error in verify_token; /login 500s begin ~20s later at 10:02:12Z.  (confidence: 1.00)

Evidence:
- log #2
- commit a1b2c3d
```

Reproduce that render yourself (no model needed):

```bash
uv run python - <<'PY'
from evals.scenarios.generator import load_scenario
from quellgeist.agent.schema import Diagnosis, Hypothesis
from quellgeist.output.postmortem import render_postmortem

s = load_scenario("evals/scenarios/fixtures/bad_deploy_0001.json")
gold = Diagnosis(hypotheses=[
    Hypothesis(cause=s.gold_cause, confidence=1.0, evidence=s.gold_evidence_refs)
])
print(render_postmortem(gold, title="Incident Postmortem (rendered from gold)"))
PY
```

The point isn't the prose — it's that **`log #2`** and **`commit a1b2c3d`** are
exact handles into the real signals, not paraphrases. A live run additionally
fills in a one-line summary and suggested actions, and abstains outright when the
evidence is too weak to name a confident cause.

## Running the model

The reasoner is any [LiteLLM](https://docs.litellm.ai/) model string, selected by
`--model` or the `QG_MODEL` env var (default `gemini/gemini-3.5-flash`). Provider
keys are read from the environment by LiteLLM; nothing is stored in the repo.

```bash
export QG_MODEL="gemini/gemini-3.5-flash"
export GEMINI_API_KEY="…"
uv run quellgeist diagnose --show-trace
```

Or fully local and offline via [Ollama](https://ollama.com) — the intended home
default (DR-0008; exact artifact pinned in DR-0019), no API key involved:

```bash
ollama pull qwen3:4b-instruct-2507-q4_K_M
export QG_MODEL="ollama_chat/qwen3:4b-instruct-2507-q4_K_M"
uv run quellgeist diagnose --show-trace
```

Heads-up (DR-0012): a Gemini key on an unvalidated, no-billing project returns
`429 limit: 0` on current models, so the shipped CI gate is deliberately
**keyless** and model-driven evals are key-gated and run **out-of-band**
(DR-0015). At home the intended default reasoner is a local **Qwen3-4B** via
Ollama (DR-0008).

### Running the eval (reasoner + verifier + LLM-judge)

The fixture eval scores the reasoner with a deterministic keyword judge + a
zero-fabrication check (the keyless gate), and can additionally run two model
layers (DR-0016): a **verifier** that confirms cited evidence supports each
hypothesis (forcing abstention otherwise) and an advisory **LLM-judge** rubric.

```bash
export GEMINI_API_KEY="…"
export QG_MODEL="gemini/gemini-3.5-flash"
QG_VERIFY=1 QG_JUDGE_LLM=1 \
QG_MIN_CALL_INTERVAL_S=6 \      # pace calls under the free-tier RPM (avoids 429 bursts)
  uv run python -m evals.run_evals
```

`QG_VERIFIER_MODEL` / `QG_JUDGE_MODEL` override the model per layer (default
`QG_MODEL`). An unreachable backend (quota/503/timeout) **or** a rejected
credential (missing/invalid/stale key) is reported as a **skip**, not a failure
(DR-0015/DR-0017), so the out-of-band eval never reddens on a free-tier hiccup.
The LLM-judge's scores are **advisory** (they never gate). On a human-labelled
gold subset it agreed with human verdicts at **Cohen's kappa 0.81** using an
independent judge (`groq/llama-3.1-8b-instant` ≠ the reasoner) — validated on that
subset (DR-0018); still self-grading whenever `QG_JUDGE_MODEL` equals the reasoner.

> **CI's out-of-band eval runs on Groq** (`groq/llama-3.3-70b-versatile`, gated on
> `GROQ_API_KEY`): Gemini's free tier proved unusable from cloud CI (429 → 503 →
> timeout → invalid-key), so the reasoner was swapped with one env var — the
> model-agnostic thesis in action (DR-0017). The intended *home* default remains a
> local Qwen3-4B (DR-0008).

## Status & roadmap

Built in **rolling waves** — only the current wave is implemented in detail
(see [`docs/quellgeist-plan-rolling-wave.md`](docs/quellgeist-plan-rolling-wave.md)).
The full decision history lives in the
[**ADR log**](docs/quellgeist-adr-log.md).

| Wave | Scope | Status |
|---|---|---|
| 0 | De-risk the model bet (4B can orchestrate the loop) | ✅ done — default = Qwen3-4B (DR-0008) |
| 1 | Bad-deploy slice: demo → break → diagnose → postmortem; eval harness + CI | ✅ done — spine built & unit-tested |
| 2 | Reliability core: verifier pass, deterministic fabrication check, abstention, LLM-as-judge | ✅ built — keyless deterministic gate + opt-in verifier/judge; first real run passed with zero fabrication (DR-0016/DR-0017). Judge validation + a reliability *rate* carry into Wave 3 |
| 3 | Breadth: config/env + resource-exhaustion classes, metrics, ~50 scenarios | ✅ done — 3 classes across a 65-scenario suite; first full run **61/65, 0 fabricated**; judge validated (kappa 0.81). See the [reliability](docs/case-studies/wave3-reliability-rate.md) + [judge](docs/case-studies/wave3-judge-validation.md) case studies |
| **4** | **Cost / fine-tune: QLoRA Qwen3-4B vs base vs frontier, with/without verifier** | 🚧 **in progress** — baseline measured: base Qwen3-4B **0/65 fixtures · 0/16 holdout · 0 fabricated** — all safe abstentions, the floor the fine-tune must beat (DR-0019, [case study](docs/case-studies/wave4-qwen-baseline.md)) |
| 5 | Polish & ship: HTML render, security pass, MCP registry, launch | ⏳ deferred |
| 6 | Resolution-verification loop | ⏳ cut-first |

Deferred features carry `NotImplementedError` stubs on purpose (e.g.
`generate_scenarios`) — the wave boundary is deliberate, not unfinished.

## Reliability gate

The deterministic CI gate is the reliability contract: **128 tests** (ruff +
black via pre-commit, then `pytest` — covering the loop's never-crash /
graceful-abstention behaviour, the deterministic fabrication check and
cite-based judge gate, the verifier and advisory LLM-judge, parameterised
scenario generation, the judge-validation harness, the server filters, the
postmortem renderer, and the fixture-backed eval harness) on Python 3.12 and 3.13.

Out of band, the **model-driven eval** runs the reasoner over the 65-scenario
suite. The latest full run scored **61/65 passed, 0 fabricated evidence**
(Cerebras Gemma-4-31B) — per-class breakdown + the failure analysis in the
[reliability case study](docs/case-studies/wave3-reliability-rate.md).

```bash
uv run pytest tests/ -q
uv run pre-commit run --all-files
```

## Development & contributing

See [CONTRIBUTING.md](CONTRIBUTING.md) for the dev setup, conventions, and the
wave model, and [SECURITY.md](SECURITY.md) for reporting and the no-secrets /
toy-demo policy.

## License

[MIT](LICENSE) © Rajeev Shyam Kumar.
