# Wave 4 — the base-Qwen3-4B baseline (the floor the fine-tune must beat)

*2026-07-02. The first measurement of the intended default reasoner (DR-0008) on
this harness — run locally, offline, on consumer hardware. Also the first time
the reserved holdout set was evaluated by any model.*

## Headline

```
reasoner = ollama_chat/qwen3:4b-instruct-2507-q4_K_M   (local Ollama, RTX 5060 8GB,
QG_VERIFY=1, LLM-judge off, max_steps=8 — same conditions as the Gemma-4-31B run)

fixtures  (65, generator distribution):  0/65 passed · 0 fabricated
holdout   (16, reserved distribution):   0/16 passed · 0 fabricated
```

- **Zero fabrication — 81/81 (100%).** Across every scenario in both sets, the
  base model never cited a handle it hadn't seen. The headline guarantee holds
  even on a 4-bit 4B that is otherwise failing.
- **Zero full passes.** 80 of 81 scenarios ended in abstention; one
  (`resource_exhaustion_0001`) named the correct cause and cited the culprit
  commit but missed the other gold handles (`correct_cause=True,
  evidence_matches=False`).
- **The failures are all "safe."** No scenario produced a
  confidently-wrong-with-fabrication diagnosis — the failure mode the project
  exists to prevent. The base model is *reliably useless*: perfectly safe,
  completely ineffective.

## The failure mode: speculative filtering

Reading the traces (not just the scores) shows one consistent behaviour. The
model's **first** tool call filters on values it has never seen:

```
query_logs({'since': '…T10:10:00Z', 'level': 'ERROR', 'route': 'api/v1/orders'})
```

- `route='api/v1/orders'` appears in **every** scenario's trace — it exists in
  none of them (fixture routes are `/data`, `/login`, …). It is a pretraining
  prior, not an observation.
- `since` windows are guessed off the incident timestamp and routinely exclude
  the entire log range.
- Faced with empty observations, the model tries *more* speculative filters
  rather than falling back to one broad query, exhausts its 8 steps, and the
  loop abstains gracefully. (Its stock metric-name guesses — memory /
  connections / queue depth — happen to match the corpus vocabulary, which is
  why `resource_exhaustion` produced the single near-miss.)

Contrast Gemma-4-31B under identical conditions: 61/65, broad-first queries.
The gap between a 31B stand-in and the untuned 4B **is** the Wave-4 cost story,
and speculative filtering is the precise behaviour the fine-tune (on
generator-distribution trajectories, never the holdout — DR-0003) has to fix.

## Notes from the run

- **Cost and latency:** the full 65-scenario set completed in **6.8 minutes**
  (log stamps 21:45:11 → 21:51:58; ~6.3 s/scenario end-to-end, sub-second model
  calls per the Ollama server log) on a laptop GPU, at **$0**, fully offline
  (WiFi off — nothing in the eval path needs a network). That is the cost side
  of the thesis working; quality is what's missing.
- **JSON discipline was near-perfect:** 2 scenarios of 81 logged a single
  schema violation each (one was an invented `file` kwarg on `query_logs`);
  the loop's retry path absorbed both. `verifier_dropped=0` everywhere — with
  no hypotheses to check, the verifier layer was effectively idle.
- **Local decoding is not deterministic at temperature 0:** in pre-run smoke
  tests, `resource_exhaustion_0001` fully diagnosed (correct commit, sensible
  rollback action) in one pass and abstained in the next, without any change.
  Single-run numbers on local serving carry variance; the comparison matrix
  should plan for repeated passes.
- **The holdout stayed clean:** this run *evaluated* the reserved set for the
  first time (that's its purpose) but nothing has ever been tuned on it. The
  train/eval separation (DR-0003) remains intact.

## Honest caveats

- **One run per set.** No variance bars; see the non-determinism note above.
- **This is the base model.** DR-0008's bet was always *fine-tuned* Qwen3-4B +
  verifier; this number is the "before" picture, not the verdict on the bet.
- **Q4_K_M quantisation.** The 4-bit artifact is the deployment-realistic
  choice, but a higher-precision run would isolate how much quantisation
  contributes to the failure mode (candidate ablation).
- **The corpus vocabulary is generator-made.** A model that guesses filter
  values may do relatively better on real-world-shaped data where its priors
  are less wrong — this corpus punishes priors hard.

## What this sets up

| Comparison cell (Wave 4 matrix) | Status |
|---|---|
| Base Qwen3-4B, verifier on — fixtures | **0/65 · 0 fabricated (this run)** |
| Base Qwen3-4B, verifier on — holdout | **0/16 · 0 fabricated (this run)** |
| Gemma-4-31B stand-in — fixtures | 61/65 · 0 fabricated (Wave 3) |
| Fine-tuned Qwen3-4B — holdout | the number that decides the thesis |

## Reproduce

```bash
ollama pull qwen3:4b-instruct-2507-q4_K_M
export QG_MODEL="ollama_chat/qwen3:4b-instruct-2507-q4_K_M"
QG_VERIFY=1 uv run python -m evals.run_evals                                  # fixtures
QG_VERIFY=1 QG_SCENARIOS_DIR=evals/scenarios/holdout \
  uv run python -m evals.run_evals                                           # holdout
```
