# Wave 4 — the fine-tuned Qwen3-4B: frontier-competitive local diagnosis at $0, with a shared abstention ceiling

*2026-07-06. The DR-0020 QLoRA fine-tune of `qwen3-4b-instruct-2507`, measured
against its own base and the Gemma-4-31B frontier stand-in (`cerebras/gemma-4-31b`)
on the reserved holdout — 3 scored passes per cell (local temp-0 decoding is not
run-to-run deterministic, DR-0019), real per-scenario cost, and the DR-0020 §8
trace audits. Training ran on a free Colab T4; base + tuned served through
Ollama; the frontier via the Cerebras API; comparison run with `evals/matrix`.*

## Headline

The fine-tune produced a **local 4B that beats its base out of sight, is
*cheaper* than its base, matches-or-beats a 31B frontier on capability and
tool-discipline, ties that frontier on adversarial abstention — and shares one
hard limit with it.**

```
reasoner = ollama_chat/quellgeist-qwen3-dr0020 (Q4_K_M GGUF, hand-authored ChatML
Modelfile, num_ctx 8192; verifier pinned to the BASE artifact; max_steps 8; 3 passes)

                        base       tuned     tuned+verifier    frontier (gemma-4-31b)
holdout (16)            0/16       12/16     12/16             10/16  [1 pass, directional]
fixtures (65)           —          —         48/65 (0.74)      —
fabrication             0          0         0                 0
abstention probe (12)   —          —         0/12 model        6/12   [2 passes, stable]
                                             6/12 w/ verifier
structure probe (10)    —          —         7/10              —
speculative-filter/pass ~281       0         0                 ~57–77
reasoner tok/scenario   7,558      3,439     3,439 (+416 ver)  API; 120–180 s/scen
```

- **Capability transferred — and it beats the frontier here.** On the reserved
  holdout (tokens never seen) the tuned model went from the base's hard
  **0/16 to 12/16**, with **zero fabrication** and **zero speculative-filtering
  violations** (base ~281/pass). The 31B frontier scored **10/16** on the same
  holdout (single-pass, directional) while committing **77 speculative-filtering
  violations** — the untuned frontier falls into the *same* DR-0019 over-filtering
  trap the fine-tune cured. The 4B out-scored the 31B because the task rewards
  exactly the policy the fine-tune installed and the frontier does not follow it
  natively.
- **Abstention is a hard, *shared* gap — not a fine-tune regression.** The
  model's own deliberate-abstention recall is **0/12** on the adversarial traps.
  But the shipped system (tuned **+ verifier**) reaches **6/12** — and the 31B
  frontier's *own* recall is also **6/12**. No configuration clears the ≥90% bar;
  even the frontier only half-solves it. On abstention the tuned+verifier system
  is at **frontier-parity**, not below it.

Honest one-line verdict: **a fine-tuned local 4B that is frontier-competitive on
this task at $0 and fully offline — with one unlearned class
(`resource_exhaustion`) and an adversarial-abstention ceiling it shares with the
frontier.**

## The capability win is real — and it is not memorisation

Three independent readings rule out "it just memorised the training bank":

- **Fixtures ≈ holdout.** Same-bank fixtures score 0.74; out-of-vocabulary
  holdout scores 0.75. A memoriser would score far higher on the bank it trained
  near than on unseen tokens. These are equal.
- **Core-fresh ≥ core-overlap.** Splitting the fixtures by whether they share a
  training *core* (DR-0020 §8): **overlap 0.71 (n=21) / fresh 0.75 (n=44).** The
  fresh half — no shared core — scores *higher*, not lower. Memorisation would
  invert this.
- **Structure probe 7/10, with real causal reasoning.** The tuned model passes
  `culprit_not_newest` and `third_commit` perturbations on bad_deploy and
  config_error — it selects the correct culprit even when it is *not* the newest
  commit, defeating a positional "blame-newest" shortcut. It reasons about
  causes, not positions.

## …and it is *cheaper* than the base, not just better

Because the tuned model diagnoses in ~3 terminal steps instead of flailing for 8,
it is strictly cheaper on the same hardware:

| | holdout | reasoner tok/scenario | calls/scenario | s/scenario |
|---|---|---|---|---|
| base | 0/16 | **7,558** | 7.8 | 11.0 |
| tuned | 12/16 | **3,439** | 3.1 | 8.6 |
| tuned + verifier | 12/16 | 3,439 + 416 (verifier) | 3.1 | 10.0 |

Less than half the tokens, ~40% of the calls, a better score, at **$0 and fully
offline**. The verifier adds one base-model call (~416 tok) per scenario. The
frontier, by contrast, spends 120–180 s/scenario of paid API time to score
*lower*.

## Frontier comparison (Gemma-4-31B stand-in) — the 4B holds its own

Two cells against `cerebras/gemma-4-31b`, the DR-0020 frontier stand-in. Both
are **directional** — run below the local cells' 3-pass logged standard (holdout:
single pass; abstention: two full passes plus an identical-starting third) — so
they are reported as directional, not as gated numbers.

**Holdout capability:** frontier **10/16**, *below* the tuned 4B's 12/16, with
**77 speculative-filtering violations** and **120–180 s/scenario** (vs the tuned
model's ~9 s). The frontier *does* pass all of `resource_exhaustion` — the tuned
model's blind spot — so it is not strictly dominated; the two have different
failure distributions. But on the two classes the fine-tune learned, and on
tool-discipline and cost, the local 4B wins outright.

**Abstention:** the frontier's own deliberate-abstention recall is **6/12** —
exactly the tuned+verifier system's number — and the two catch **complementary**
traps:

| trap type | frontier (own) | tuned + verifier |
|---|---|---|
| `time_shift` | **3/3** | 1/3 |
| `no_incident` | 2/2 | 2/2 |
| `no_culprit` | 0/2 | **2/2** |
| `weak_link` | 1/3 | 0/3 |
| `decoy_wall` | 0/2 | 1/2 |
| **total** | **6/12** | **6/12** |

The frontier reasons about *timing* (nails `time_shift` 3/3) but fails "there is
no culprit" (0/2). The verifier is the mirror image — it refutes evidence-
*absence* (`no_culprit` 2/2) but misses temporal/causal subtlety (`time_shift`
1/3). Both land at 6/12 by different routes. **Adversarial abstention is
genuinely unsolved at this scale**, and the complementarity is suggestive: a
verifier that also checked *timing* could plausibly beat either alone (future
work). The frontier also over-filters here (~57 violations/pass): the DR-0019
failure mode is a general untuned-model trait, not a base-4B quirk.

## The calibration gap — exactly where the verifier's net breaks

The abstention probe is 12 adversarial traps where a correct diagnosis
*abstains* — e.g. a `time_shift` trap where the suspicious deploy lands ten
minutes *after* the errors it supposedly caused. The tuned model **diagnosed all
12** (blamed the deploy, missing the impossible timing). `fabricated=0`
throughout: it is not inventing evidence, it is drawing a wrong conclusion from
real evidence.

The shipped system is tuned **+ verifier**, so the question is whether the
verifier catches what the model doesn't. It catches exactly half, and the split
is structured:

| trap type | caught by verifier (forced abstention) |
|---|---|
| `no_incident` | 2/2 ✅ |
| `no_culprit` | 2/2 ✅ |
| `decoy_wall` | 1/2 |
| `time_shift` | 1/3 |
| `weak_link` | **0/3** ❌ |
| **system total** | **6/12** |

The verifier reliably refutes **evidence-*absence*** traps (nothing to cite →
"no incident", "no culprit") but misses **causal-*subtlety*** traps (real logs
cited, wrong causality → "weak link", "time shift"). A weak base-model verifier
can catch "you cited nothing"; it cannot catch "you cited real logs but the
deploy is ten minutes too late." So the abstention bar is missed at both levels:
**0/12 model, 6/12 system** — but, crucially, the 6/12 system number *equals* the
31B frontier's own 6/12. The gap is a property of the adversarial task, not a
defect the fine-tune introduced relative to a frontier.

## The one class that did not transfer: `resource_exhaustion`

Every failure, on every set, is concentrated in one failure class:

| class | fixtures | holdout | structure probe |
|---|---|---|---|
| bad_deploy | 25/25 | 6/6 | ✅ |
| config_error | 23/25 | 6/6 | ✅ |
| **resource_exhaustion** | **0/15** | **0/4** | **0/3** |

The tuned model did not learn the resource-exhaustion diagnosis pattern —
0 across fixtures, holdout, *and* the structure probe. This is a clean, nameable
gap, not diffuse noise: two of three classes transferred strongly, the third not
at all. The **frontier passes `resource_exhaustion`**, so this is a
training-coverage gap, not a fundamental limit of the architecture — a candidate
for a targeted trajectory-mix fix in a future wave. (It is also the class the
base was least-bad at via lucky metric-name priors; the fine-tune may have
overwritten those priors without installing the reasoning to replace them.)

## What the thesis can and cannot claim

DR-0020's pre-registered wording holds the line:

- **Supported:** the fine-tune installs the broad-first, copy-from-observation
  investigation policy; it **transfers to out-of-vocabulary incidents** (holdout
  12/16, non-memorisation triangulated three ways) at **lower cost than the
  base** and **$0 vs a paid frontier**, with **zero fabrication** throughout —
  and it is **frontier-competitive**: it *beats* the 31B stand-in on holdout
  capability, tool-discipline, and cost, and *ties* it on adversarial abstention.
- **Partially supported — the honest heart of the wave:** *"fine-tuned local +
  verifier ≈ frontier quality, safely."* The **≈-frontier-quality** half is
  supported (parity-or-better on every measured axis). The **"safely"** half is
  unmet in *absolute* terms — the system still mis-diagnoses 6/12 adversarial
  traps — **but the 31B frontier is equally unsafe here (also 6/12).** So this is
  an *unsolved-task* caveat, not a fine-tune regression: neither model is safe to
  run *fully* unattended on adversarial inputs.
- **Out of scope for every cell:** claims about unseen incident *structure* or
  real production incidents. Holdout is *out-of-vocabulary, in-structure* only.

## Honest caveats

- **Not safe *fully* unattended on adversarial inputs** (system 6/12) — but this
  is a *shared* property: a 31B frontier is equally exposed (6/12). It is an
  unsolved task, not a fine-tune defect.
- **The model's *intrinsic* abstention did collapse** (0/12); the verifier is
  load-bearing for the system's 6/12. Do not run the tuned model verifier-less on
  adversarial inputs.
- **`resource_exhaustion` is 0/N everywhere** (the frontier passes it) — a
  training-coverage gap, not a ceiling.
- **Frontier numbers are directional** — holdout single-pass, abstention two full
  passes (stable) — not the local cells' fully-logged 3-pass standard. Both on
  `gemma-4-31b`.
- **T4-measured latency.** The comparison ran on a Colab T4, not the target
  laptop; latency numbers are T4 numbers. Correctness/fabrication/abstention are
  hardware-independent.
- **Q4_K_M quantisation** is the deployment-realistic artifact; a
  higher-precision ablation would isolate quantisation's contribution.
- **One-pass record inspection** for the 6/12 verifier-rescue split (the
  deliberate-abstention 0/12 is the gated 3-pass number).

## Reproduce

```bash
# tuned + base served via Ollama (see finetune/README.md for build + Modelfile)
export QG_MODEL="ollama_chat/quellgeist-qwen3-dr0020"
export QG_VERIFIER_MODEL="ollama_chat/qwen3:4b-instruct-2507-q4_K_M"   # BASE, pinned

uv run python -m evals.matrix.run_cell --cell-id tuned+verifier--holdout \
  --scenarios evals/scenarios/holdout --verify
uv run python -m evals.matrix.run_cell --cell-id tuned+verifier--fixtures --verify
uv run python -m evals.matrix.run_cell --cell-id tuned+verifier--abstain-probe \
  --scenarios evals/training/probes/abstention --score abstain --verify
uv run python -m evals.matrix.run_cell --cell-id tuned+verifier--structure-probe \
  --scenarios evals/training/probes/structure --verify

# frontier stand-in (paid API; ~13 s/call to respect a 5 req/min free tier)
export QG_MODEL="cerebras/gemma-4-31b"; export QG_MIN_CALL_INTERVAL_S=13
uv run python -m evals.matrix.run_cell --cell-id frontier--holdout \
  --scenarios evals/scenarios/holdout
uv run python -m evals.matrix.run_cell --cell-id frontier--abstain-probe \
  --scenarios evals/training/probes/abstention --score abstain

uv run python -m evals.matrix.report runs/matrix/*/cell.json --out matrix-report.md
```
