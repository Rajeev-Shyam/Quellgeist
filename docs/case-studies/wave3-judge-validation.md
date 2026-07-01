# Wave 3 — validating the LLM-judge against human labels

*2026-07-01. The first time the advisory LLM-judge was measured against a
human-labelled gold subset (DR-0018) — the step that decides whether its rubric
scores can be trusted at all.*

## Why this run matters

The LLM-judge (`evals/llm_judge.py`) has always been **advisory**: it scores a
diagnosis on a rubric (correct cause? valid evidence? sensible actions?), but the
keyless deterministic judge + fabrication check are the gate. Its scores were
explicitly *not to be quoted* until two things were true (DR-0003, DR-0017):

1. it **agrees with human judgment** on a labelled set, and
2. the judge model is **independent of the reasoner** (or the score is just the
   model grading its own family).

Wave 3 built the machinery for exactly this: a hand-authored, corpus-independent
gold subset (`evals/judge_validation/labelled_cases.json`) and an agreement
harness (`evals/validate_judge.py`). This is the first real run of it.

## The run

Triggered via the manual `judge-validation.yml` workflow, judge model set to
**`groq/llama-3.1-8b-instant`** — deliberately a *different, smaller* model than
the `llama-3.3-70b-versatile` reasoner, so the number is independent, not
self-graded:

```
judge model = groq/llama-3.1-8b-instant
labelled cases: 11
verdict agreement:         10/11 (0.91)
  correct_cause agreement:  10/11 (0.91)
  evidence_valid agreement: 9/11 (0.82)
Cohen's kappa (verdict):   0.81
disagreements (human vs judge):
  - config_error__weak_evidence: human=fail judge=pass
```

**Cohen's kappa 0.81** — "almost perfect" on the Landis–Koch scale, comfortably
past DR-0018's ≥ 0.6 ("substantial") bar. On this subset, with an independent
judge, the LLM-judge tracks human verdicts. Its rubric scores can now be quoted
**as validated on this subset**.

## The one disagreement — and why it's reassuring

The single verdict miss is instructive. `config_error__weak_evidence` is a
diagnosis that names the right cause ("a config change removed the SMTP_URL
default") but cites the **wrong commit** as evidence — a decoy *test* commit
(`77aa001`) rather than the actual config change (`c0ffee1`). The human label is
**fail** (`evidence_valid = false`: the cited evidence is real but irrelevant).
The 8B judge called it **pass**, reasoning that the diagnosis "provides valid
evidence" — it credited a real-but-decoy citation without checking that it
pointed at the true culprit.

That is a genuine blind spot of a small LLM-judge. But it is precisely the class
of error the **deterministic gate** is built to catch: `evals/judge.py` requires
the *gold* commit to be cited, and `evals/fabrication_check.py` checks handle
existence — a diagnosis that cites the decoy instead of the gold commit fails the
keyless gate regardless of what the LLM-judge thinks. **The two layers cover each
other's gaps:** the deterministic gate enforces exact, correct citations; the LLM
rubric adds semantic judgment on top. Neither is trusted alone.

## Honest status

- **Validated, with scope.** Kappa 0.81 is a real, independent validation — but on
  **11 hand-authored cases** with a single 8B judge. A larger subset, a stronger
  judge, and ideally more than one human labeller would strengthen it further. The
  number is quotable *with that scope stated*, not as an absolute.
- **This is the judge number, not the reliability rate.** The headline
  reliability *rate* (correct-cause-#1 + zero-fabrication across the ~65-scenario
  suite) is still **unmeasured** — the Groq free tier's daily quota keeps skipping
  the full `eval.yml` run. Judge validation and the reliability rate are separate
  numbers; only the former is in hand.

## Reproduce

```bash
export GROQ_API_KEY="…"
export QG_JUDGE_MODEL="groq/llama-3.1-8b-instant"   # any model != the reasoner
uv run python -m evals.validate_judge
```
Or run the `judge-validation` workflow (Actions → Run workflow). It makes ~11
judge calls, so it completes even when the full eval is quota-blocked.
