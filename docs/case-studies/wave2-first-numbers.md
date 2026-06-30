# Wave 2 — the first real eval run (and what it caught)

*2026-06-30. The first time Quellgeist's full pipeline — evidence-gathering loop +
verifier pass + LLM-judge + deterministic gate — ran end-to-end against a real
model on the `bad_deploy_0001` fixture.*

## Getting to a run: the model-agnostic design earned its keep

The intended CI/convenience model was Gemini `2.5/3.5-flash` on the free tier. It
proved **unusable from cloud infrastructure** — four runs, four failure modes:

| Where | Result |
|---|---|
| GitHub Actions (key-gated eval) | `429 RESOURCE_EXHAUSTED` (free-tier RPM/RPD) |
| Merge-to-main eval | `503 ServiceUnavailable` |
| Manual eval (paced) | `Timeout` after ~9 calls |
| Codespace (paced) | `503 ServiceUnavailable` |

Each time the harness **skipped green, never red** — provider-unavailability is a
skip, not a reliability failure (DR-0012/DR-0015). That safety net worked exactly
as designed. But it meant *no numbers*.

The fix was the project's own thesis: **the reasoner is model-agnostic.** One env
var —

```bash
export QG_MODEL="groq/llama-3.3-70b-versatile"   # was gemini/gemini-3.5-flash
```

— swapped the entire reasoner to Groq's `llama-3.3-70b-versatile`, which completed
the run reliably on the first try. No code change; the JSON-action loop is
identical across backends (DR-0010).

## The run

```
reasoner = groq/llama-3.3-70b-versatile
[FAIL] bad_deploy_0001: correct_cause=False evidence_matches=True
       (violations=2, fabricated=∅, verifier_dropped=0, rubric=pass(1.00))
0/1 scenarios passed; 0 with fabricated evidence
```

The actual diagnosis the model produced:

> **CAUSE:** "The recent deploy of the refactored token parsing code introduced a
> bug that causes the `auth.verify_token` function to fail when encountering a
> NoneType object."
> **EVIDENCE:** `[('log', 2), ('commit', 'a1b2c3d')]`

That is **correct** — right root cause, the gold log + the gold commit, nothing
invented.

## What the run caught — four findings

1. **Zero fabrication held on a real model.** `fabricated=∅` — the headline
   guarantee (every cited handle exists in the real signals) survived first
   contact with a real reasoner. This is the floor the whole project is built on.

2. **A judge false-negative (fixed → DR-0017).** `correct_cause=False` was *wrong*.
   The deterministic keyword judge required the gold SHA to appear in the cause
   **prose** (`sha in top.cause`) — but DR-0009's design cites evidence as
   structured **handles**, which is exactly what the model did. We confirmed the
   diagnosis was correct by *reading it* (not trusting any score), then fixed
   `correct_cause` to check that the top hypothesis **cites** the gold commit, and
   added a regression test. **After the fix the scenario passes.** This is the
   "validate the judge against reality" discipline working on the very first run.

3. **The LLM-judge's `rubric=1.00` was not trustworthy here.** The judge was the
   *same model* grading its own output (`QG_JUDGE_MODEL` inherited `QG_MODEL`).
   Self-grading bias. Takeaway: run the judge on a **different / stronger** model
   (`QG_JUDGE_MODEL=…`), and treat rubric scores as advisory until validated
   against a human-labelled gold subset (DR-0003).

4. **Minor reasoner robustness:** `violations=2` — `llama-3.3-70b` emitted two
   malformed JSON actions mid-loop, and the loop's retry path recovered both
   times. Worth watching as fixtures broaden; not a bug.

## Honest status

- This is **one fixture** — a smoke test of the pipeline, **not a reliability
  rate.** Real rates need the ~50-scenario suite (Wave 3).
- The LLM-judge's scores stay **advisory** until a human gold subset exists.
- The reasoner here (Groq `llama-3.3-70b`) is a reliable stand-in; the intended
  default is a local **Qwen3-4B** (DR-0008). Both are model-agnostic swaps.

## Reproduce

```bash
export GROQ_API_KEY="…"
export QG_MODEL="groq/llama-3.3-70b-versatile"
export QG_VERIFY=1 QG_JUDGE_LLM=1
uv run python -m evals.run_evals          # expect [PASS] after the DR-0017 fix
```
