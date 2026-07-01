# Wave 3 — the first full reliability rate (three classes, real model)

*2026-07-01. The first time the whole eval corpus — all three failure classes,
65 scenarios — ran end-to-end against a real model and produced a **rate**, not a
smoke test.*

## Headline

```
reasoner = cerebras/gemma-4-31b   (Gemma 4 31B, Cerebras free tier, QG_VERIFY=1)
61/65 scenarios passed; 0 with fabricated evidence
```

- **Zero fabrication — 65/65 (100%).** Every diagnosis cited only evidence that
  exists in the real signals. The headline guarantee the whole project is built
  on held across the entire corpus, on a real model, first full run.
- **Full pass — 61/65 (93.8%).** "Pass" is the strict gate: the top hypothesis
  pins the gold commit **and** the diagnosis cites *every* gold evidence handle
  **and** nothing is fabricated. Past the ≥ 80% "high majority" bar.
- **Correct cause #1 — 64/65 (98.5%).** Only one scenario failed to name the
  right cause (an abstention); the other 64 identified it.

## Per class

| Class | Passed | Notes |
|---|---|---|
| `bad_deploy` | 24/25 | one evidence-citation miss |
| `config_error` | 22/25 | two citation misses + one abstention |
| `resource_exhaustion` | **15/15** | the new metrics-backed class — perfect |

That `resource_exhaustion` went 15/15 is the strongest single result: it's the
class that *requires reading metrics* (the gold cites a `MetricRef`), so a clean
sweep says the metric path — the MCP server, `query_metrics`, and metric-aware
fabrication/verifier — works end to end.

## The four misses — all "safe" failures

None were confidently-wrong-with-fabrication (the failure mode the project exists
to prevent). They split into two benign kinds:

- **Three "correct cause, incomplete citation"** (`bad_deploy_0003`,
  `config_error_0014`, `config_error_0017`): `correct_cause=True` but
  `evidence_matches=False`. The model named the right cause and cited the culprit
  commit, but didn't cite *every* gold handle (e.g. it skipped the specific error
  log). The deterministic gate requires the full gold set, so these fail — but the
  diagnosis is right, just under-cited. `fabricated=∅` on all three.
- **One over-cautious abstention** (`config_error_0018`): the model returned
  "insufficient evidence" where a confident diagnosis was warranted. A false
  abstention is the *conservative* failure — the agent declined to guess rather
  than inventing a cause. `verifier_dropped=0`, so this was the model's own call,
  not a forced abstention.

Both kinds are exactly the reliability profile we want: when the agent is wrong,
it's *incomplete* or *too cautious*, never *confidently fabricating*.

## Notes from the run

- **JSON-action robustness was perfect:** `violations=0` on all 65 scenarios —
  Gemma-4-31B emitted zero malformed actions (better than `llama-3.3-70b`, which
  needed the loop's retry path on the single-fixture run).
- **The retry path earned its keep:** Cerebras threw transient provider errors
  mid-run; the provider's retry/backoff recovered them and all 65 scenarios
  completed (none skipped).
- **Getting here was the model-agnostic thesis, again:** Groq's free tier hit its
  daily quota, so a one-env-var swap to `cerebras/gemma-4-31b` produced the number
  from a Codespace. No code changed.

## Honest caveats

- **One run, one model.** This is Gemma-4-31B on a single pass. The intended
  default reasoner is a local **Qwen3-4B** (DR-0008); that number is still a Wave-4
  measurement. Gemma here is a capable stand-in, not the final story.
- **Generated corpus, not human-diverse.** The 65 scenarios come from the
  parameterised generator; the held-out set (`evals/scenarios/holdout/`, a
  different distribution) has not been run against a model yet.
- **This is the deterministic-gate rate.** The advisory LLM-judge was off in this
  run; the gate is the keyless deterministic judge + fabrication check. The judge
  itself was separately validated at kappa 0.81 (`wave3-judge-validation.md`).

## Wave 3 exit — met

| Exit criterion | Result |
|---|---|
| All three classes pass their reliability bar | ✅ 24/25 · 22/25 · 15/15 |
| ~50-scenario suite runs and reports a real rate | ✅ 65 scenarios → 61/65 |
| Zero fabricated causes on the eval set | ✅ 0/65 |
| Validated judge | ✅ kappa 0.81 (DR-0018) |

## Reproduce

```bash
export CEREBRAS_API_KEY="…"
export QG_MODEL="cerebras/gemma-4-31b"    # any LiteLLM model your key can call
QG_VERIFY=1 QG_MIN_CALL_INTERVAL_S=1 uv run python -m evals.run_evals
```
