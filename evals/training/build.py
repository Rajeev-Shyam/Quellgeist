"""Rebuild the DR-0020 training artifacts (Wave 4, Task 2).

``python -m evals.training.build`` writes:

- ``evals/training/data/train.jsonl`` — the full training corpus (LOCAL build
  artifact, gitignored: the build is deterministic, so what was reviewed is
  what is trained on without committing megabytes of generated JSONL);
- ``evals/training/sample_trajectories.jsonl`` — the committed, human-reviewed
  N=20 sample spanning every variant (plan Task 2 acceptance);
- ``evals/training/probes/{abstention,structure}/*.json`` — the two committed,
  never-trained probe sets.

Deterministic and idempotent: re-running leaves ``git`` clean. Every artifact
passes the zero-contamination vetoes BEFORE it is written (fail-closed): the
template-expanded boundary scan, the holdout + committed-fixtures sha sets
(anchor included), and the id-namespace checks. This module never reads the
eval-scenario selection env var or the holdout directory — its only scenario
sources are the ``train``/``probe`` splits (enforced by a source-scan test).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from evals.scenarios.build import scenario_json, write_split
from evals.training.contamination import (
    assert_no_holdout_leakage,
    committed_fixture_ids_and_shas,
    holdout_shas,
)
from evals.training.probes import build_probes
from evals.training.trajectories import build_examples, corpus_stats

_HERE = Path(__file__).parent
_DATA = _HERE / "data"
_SAMPLE = _HERE / "sample_trajectories.jsonl"
_PROBES = _HERE / "probes"

# variant -> how many of it the reviewed sample carries (total 20)
_SAMPLE_MIX = {
    "canonical_logs_first": 4,
    "canonical_commits_first": 2,
    "narrowing": 2,
    "recovery": 3,
    "retry": 1,
    "metric_bait": 2,
    "decoy_bait": 1,
    "no_culprit": 1,
    "no_incident": 1,
    "time_shift": 1,
    "weak_link": 1,
    "decoy_wall": 1,
}


def select_sample(examples: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """A deterministic 20-example review sample covering every variant
    (examples arrive sorted by id; we take the first N of each)."""
    sample: list[dict[str, Any]] = []
    for variant, n in _SAMPLE_MIX.items():
        sample.extend([e for e in examples if e["variant"] == variant][:n])
    assert len(sample) == sum(_SAMPLE_MIX.values())
    return sample


def _veto(text: str, where: str, banned_shas: set[str]) -> None:
    assert_no_holdout_leakage(text, where)
    assert '"hold_' not in text, f"{where}: reserved hold_ id namespace present"
    for sha in sorted(banned_shas):
        assert sha not in text, f"{where}: eval-corpus sha {sha} present"


def main() -> None:
    fixture_ids, fixture_shas = committed_fixture_ids_and_shas()
    banned_shas = fixture_shas | holdout_shas()

    examples = build_examples()
    lines = [json.dumps(e) for e in examples]
    for example, line in zip(examples, lines, strict=True):
        _veto(line, example["id"], banned_shas)
        assert example["scenario_id"].startswith("train_"), example["id"]
        assert example["scenario_id"] not in fixture_ids, example["id"]
    sample = select_sample(examples)

    abstention, structure = build_probes()
    for s in abstention + structure:
        _veto(scenario_json(s), s.id, banned_shas)
        assert s.id.startswith("probe_"), s.id

    _DATA.mkdir(exist_ok=True)
    (_DATA / "train.jsonl").write_text("\n".join(lines) + "\n", encoding="utf-8")
    _SAMPLE.write_text(
        "\n".join(json.dumps(e) for e in sample) + "\n", encoding="utf-8"
    )
    write_split(abstention, _PROBES / "abstention")
    write_split(structure, _PROBES / "structure")

    stats = corpus_stats(examples)
    print(f"wrote {stats['examples']} examples to {_DATA / 'train.jsonl'}")
    print(
        f"  abstain {stats['abstain_share']:.1%} (hard {stats['hard_abstain_share']:.0%},"
        f" near-pairs {stats['near_pair_share']:.0%}) · traps {stats['trap_share']:.1%}"
    )
    print(f"wrote {len(sample)} reviewed-sample examples to {_SAMPLE}")
    print(
        f"wrote {len(abstention)} abstention-probe scenarios to {_PROBES / 'abstention'}"
    )
    print(
        f"wrote {len(structure)} structure-probe scenarios to {_PROBES / 'structure'}"
    )


if __name__ == "__main__":
    main()
