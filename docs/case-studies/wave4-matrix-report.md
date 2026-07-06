<!-- Committed evidence for wave4-qwen-finetune.md — the logged output of
     `python -m evals.matrix.report runs/matrix/*/cell.json` (2026-07-06).
     Six 3-pass local cells (base + tuned ± verifier + fixtures + both probes),
     served via Ollama on a Colab T4. The frontier stand-in (gemma-4-31b) is
     DIRECTIONAL and therefore not in this logged table — see the addendum. -->

# Wave-4 comparison matrix

| cell | model | verifier | set (n) | passes×steps | passed/pass | mean rate | fab | abstain recall | audits u/b/t | reasoner tok/scen | verifier tok/scen | calls/scen | s/scen | fixtures core split | conditions |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| base--holdout | ollama_chat/qwen3:4b-instruct-2507-q4_K_M | off | holdout (16) | 3×8 | 0,0,0 /16 | 0.00 | 0 | — | 843/0/15 | 7,558 | — | 7.8 | 11.0 |  | · |
| tuned+verifier--abstain-probe | ollama_chat/quellgeist-qwen3-dr0020 | ollama_chat/qwen3:4b-instruct-2507-q4_K_M | abstention (12) | 3×8 | 0,0,0 /12 | 0.00 | 0 | 0.00 | 0/0/0 | 3,457 | 416 | 3.1 | 19.4 |  | · |
| tuned+verifier--fixtures | ollama_chat/quellgeist-qwen3-dr0020 | ollama_chat/qwen3:4b-instruct-2507-q4_K_M | fixtures (65) | 3×8 | 48,48,48 /65 | 0.74 | 0 | — | 0/0/0 | 3,706 | 447 | 3.2 | 19.8 | overlap 0.71 (n=21) / fresh 0.75 (n=44) | · |
| tuned+verifier--holdout | ollama_chat/quellgeist-qwen3-dr0020 | ollama_chat/qwen3:4b-instruct-2507-q4_K_M | holdout (16) | 3×8 | 12,12,12 /16 | 0.75 | 0 | — | 0/0/0 | 3,439 | 416 | 3.1 | 10.0 |  | · |
| tuned+verifier--structure-probe | ollama_chat/quellgeist-qwen3-dr0020 | ollama_chat/qwen3:4b-instruct-2507-q4_K_M | structure (10) | 3×8 | 7,7,7 /10 | 0.70 | 0 | — | 0/0/0 | 4,619 | 598 | 3.6 | 21.2 | overlap 1.00 (n=1) / fresh 0.67 (n=9) | · |
| tuned--holdout | ollama_chat/quellgeist-qwen3-dr0020 | off | holdout (16) | 3×8 | 12,12,12 /16 | 0.75 | 0 | — | 0/0/0 | 3,439 | — | 3.1 | 8.6 |  | · |

Audit columns: u = unobserved tool-call argument values, b = fixtures-bank tokens in holdout filter arguments, t = train-seen timestamps as unobserved holdout arguments (DR-0020 decision 8; b/t are 0 by construction on non-holdout cells, where those audits are off). The `passes×steps` and `conditions` columns exist so an ablation cell (fewer than 3 passes, a non-default max_steps, or a self-verify cell) cannot blend into a same-conditions comparison: `·` = the standard 3-pass, max_steps-8 conditions; a ⚠ names the deviation. The abstain-recall ≥90% acceptance is REPORTED here; it is adjudicated by `evals.training.run_abstention_probe` (the probe's single-pass floor), never gated in this table.

Claims wording (pre-registered, DR-0020 decision 8): the post-tune FIXTURES number measures *same-bank recombination* (report it split core-overlapping vs core-fresh); the HOLDOUT is *out-of-vocabulary, in-structure* — a holdout win supports exactly one claim: the tuned model executes the broad-first, copy-from-observation policy on tokens it has never seen, instead of regurgitating training vocabulary. No cell supports claims about unseen incident structure or real incidents.

## Frontier addendum (directional — not run to the 3-pass logged standard)

The Gemma-4-31B frontier stand-in (`cerebras/gemma-4-31b`, paid API) was run
outside the logged 3-pass standard, so its numbers live here as directional
context rather than as gated cells:

| cell | model | passes | result | speculative-filter | latency |
|---|---|---|---|---|---|
| frontier--holdout | cerebras/gemma-4-31b | 1 (directional) | 10/16 | 77 violations | 120–180 s/scen |
| frontier--abstain-probe | cerebras/gemma-4-31b | 2 full + identical 3rd start | 6/12 | ~57 violations | 39–140 s/scen |

Frontier abstention by trap type: `time_shift` 3/3, `no_incident` 2/2,
`weak_link` 1/3, `no_culprit` 0/2, `decoy_wall` 0/2 — complementary to the
tuned+verifier system's own 6/12 (which catches `no_culprit`/`no_incident` but
misses `time_shift`/`weak_link`). A fully-logged 3-pass frontier column is a
Wave-5 follow-up.
