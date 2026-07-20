"""Guards for the out-of-structure holdout scaffold (Wave 10, T10.2; DR-0025).

These enforce the invariants the OOS holdout must keep even while it is only a
scaffold, so real curated scenarios drop into an already-guarded frame:

* it loads through the same `load_scenario` the harness uses (ingest-compatible);
* it is provably disjoint from the frozen holdout AND fixtures (no id collision,
  no byte-equal scenario);
* every scenario is genuinely OUT OF STRUCTURE (breaks the frozen skeleton), not
  merely out of vocabulary;
* every scenario carries attribution and is `verbatim: false` (copyright);
* the frozen corpora counts are untouched (the OOS dir is a sibling, not a leak).
"""

from __future__ import annotations

import json
from pathlib import Path

from evals.scenarios.generator import load_scenario

_SCEN = Path(__file__).parents[2] / "evals" / "scenarios"
OOS = _SCEN / "oos"
HOLDOUT = _SCEN / "holdout"
FIXTURES = _SCEN / "fixtures"


def _oos_files() -> list[Path]:
    return sorted(OOS.glob("*.json"))


def _raw(p: Path) -> dict:
    return json.loads(p.read_text(encoding="utf-8"))


def _culprit_sha(doc: dict) -> str | None:
    return next(
        (r["sha"] for r in doc["gold_evidence_refs"] if r.get("type") == "commit"),
        None,
    )


def test_oos_dir_is_non_empty_and_loads():
    files = _oos_files()
    assert files, "expected at least one OOS scaffold scenario"
    for p in files:
        s = load_scenario(p)  # ingest/harness-compatible; raises on a bad shape
        assert s.id and s.logs and s.commits


def test_oos_is_disjoint_from_frozen_corpora():
    frozen_ids = {
        _raw(p)["id"]
        for p in list(HOLDOUT.glob("*.json")) + list(FIXTURES.glob("*.json"))
    }
    # a stable structural fingerprint of the frozen scenarios (ordering-independent
    # of the extra oos_meta key, which frozen scenarios don't carry)
    frozen_prints = {
        _fingerprint(_raw(p))
        for p in list(HOLDOUT.glob("*.json")) + list(FIXTURES.glob("*.json"))
    }
    for p in _oos_files():
        doc = _raw(p)
        assert doc["id"] not in frozen_ids, f"{doc['id']} collides with a frozen id"
        assert (
            _fingerprint(doc) not in frozen_prints
        ), f"{doc['id']} is byte-equal to a frozen scenario"


def _fingerprint(doc: dict) -> str:
    core = {k: doc[k] for k in ("failure_class", "now", "logs", "commits") if k in doc}
    return json.dumps(core, sort_keys=True)


def test_every_oos_scenario_breaks_the_frozen_skeleton():
    # frozen skeleton := exactly 2 commits, culprit is the newest commit, exactly
    # one error route. Each OOS scenario must break >=1 of those, matching what its
    # oos_meta claims.
    for p in _oos_files():
        doc = _raw(p)
        commits = doc["commits"]
        err_routes = {r["route"] for r in doc["logs"] if r["level"] == "ERROR"}
        culprit = _culprit_sha(doc)
        newest_sha = max(commits, key=lambda c: c["ts"])["sha"]

        breaks = set()
        if len(commits) != 2:
            breaks.add("commit_count")
        if culprit is not None and culprit != newest_sha:
            breaks.add("culprit_not_newest")
        if len(err_routes) > 1:
            breaks.add("multi_route")

        assert breaks, f"{doc['id']} does not break the frozen skeleton"
        claimed = set(doc.get("oos_meta", {}).get("skeleton_breaks", []))
        # every structurally-detected break must be declared (log_length is declared
        # but not auto-detected here, so we only require detected ⊆ declared)
        assert breaks <= claimed, f"{doc['id']} breaks {breaks - claimed} undeclared"


def test_every_oos_scenario_has_attribution_and_is_not_verbatim():
    for p in _oos_files():
        meta = _raw(p).get("oos_meta")
        assert meta, f"{p.name} is missing oos_meta"
        assert meta.get("verbatim") is False, f"{p.name} must be verbatim: false"
        assert meta.get("source"), f"{p.name} must name a source"
        assert meta.get("attribution"), f"{p.name} must carry an attribution note"
        # a REAL curated scenario must point at its writeup; synthetic scaffold need not
        if meta["source"] != "SYNTHETIC-SCAFFOLD":
            assert meta.get("source_url"), f"{p.name} (real) must set source_url"


def test_frozen_corpora_counts_unaffected_by_oos():
    # redundant with the frozen-surface guard, but local + explicit: adding the OOS
    # sibling dir must not change the byte-locked 65 / 16.
    assert len(list(FIXTURES.glob("*.json"))) == 65
    assert len(list(HOLDOUT.glob("*.json"))) == 16
