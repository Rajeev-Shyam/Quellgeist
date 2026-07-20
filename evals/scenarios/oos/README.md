# Out-of-structure holdout (scaffold) — DR-0025 / Wave 10 T10.2

**Status: scaffolding.** This directory holds the *machinery and rules* for the
out-of-structure (OOS) generalisation holdout, plus two clearly-labelled
**synthetic** seed scenarios that exercise the guards. The real curated corpus is
authored later (it needs human curation of public postmortems and a GPU fine-tune
to report a number); this scaffold exists so that work drops into a tested frame
instead of a blank page.

## Why this exists (the honest caveat it answers)

The frozen `fixtures/` (65) and `holdout/` (16) corpora are out-of-**vocabulary**
but share one **skeleton**: two commits (one culprit, one decoy), the culprit is
the newest commit, a single error route, a fixed log length. A positional script
(“cite the newest commit + the first 500”) passes the judge on that skeleton
without learning a policy (DR-0020: 81/81 for a positional script). The frozen
holdout therefore cannot, on its own, distinguish a memorised script from a
learned policy.

The OOS holdout breaks the **skeleton itself** and draws incidents from a
different origin, so a passing number is evidence of *structural generalisation*,
not skeleton-fitting.

## Hard rules (do not relax without a new DR)

1. **Never in the frozen dirs.** OOS scenarios live here, never in `fixtures/` or
   `holdout/`. The frozen-surface guard (`tests/frozen/test_frozen_surface.py`)
   byte-locks those counts (65 / 16); this dir is a sibling and does not touch them.
2. **Provably disjoint from the frozen holdout.** No id collision and no byte-equal
   scenario. Enforced by `tests/evals/test_oos_scaffold.py`. Any fine-tune must
   still report the **frozen** holdout number (for `0/16 → 12/16` comparability)
   **and** the OOS number (for the generalisation claim) — never one in place of
   the other (DR-0025).
3. **Out of structure, not just out of vocabulary.** Each scenario must break the
   frozen skeleton in at least one structural way: commit count ≠ 2, culprit not
   the newest commit, more than one error route, or a materially different log
   length. The guard asserts this.
4. **Copyright: curated, never verbatim.** Real scenarios are *paraphrased/curated*
   from public outage writeups — incident **structure and shape only**, never the
   source’s wording. Every scenario carries attribution metadata (below) and
   `"verbatim": false`. A scenario sourced from a real writeup must set a real
   `source_url`; synthetic scaffold scenarios set `source: "SYNTHETIC-SCAFFOLD"`.
5. **Normalised through `ingest`.** Real writeups enter through the existing
   ingest/normalize layer (`docs/ingestion.md`) so the on-disk shape is identical
   to `fixtures/`; the harness reads them with `load_scenario` unchanged.

## Attribution metadata (extra JSON keys; ignored by the `Scenario` model)

```json
{
  "oos_meta": {
    "source": "SYNTHETIC-SCAFFOLD | <short label of the public writeup>",
    "source_url": null,           // required (non-null) for a real curated scenario
    "curation": "synthetic | paraphrased",
    "verbatim": false,            // MUST be false — copyright
    "skeleton_breaks": ["commit_count", "culprit_not_newest", "multi_route", "log_length"],
    "attribution": "human-readable note on provenance / license"
  }
}
```

`Scenario` (pydantic) ignores unknown keys, so these ride along in the file and are
read by the guard test and by humans — they do not change how the harness loads or
scores the scenario.

## Running the OOS set (once it is real)

```bash
# reported ALONGSIDE the frozen holdout, never instead of it
QG_SCENARIOS_DIR=evals/scenarios/oos uv run python -m evals.run_evals
```

The synthetic seeds here are structurally valid and load/score, but they are
placeholders — replace them with curated scenarios before quoting an OOS number.
