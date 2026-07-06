"""DR-0020 zero-contamination checks — artifact-level, fail-closed.

The existing bank-disjointness test guards the GENERATOR; these checks guard
the ARTIFACTS: every serialized training line is scanned for anything the
holdout could ever render. Raw ``distribution_tokens("holdout")`` is
insufficient in both directions (DR-0020 decision 7): several bank entries are
unrendered ``{key}``/``{mod}`` templates (false negatives on rendered commit
messages and error signatures), and naive substring matching false-positives
(``/billing`` occurs inside legitimate fixtures paths like
``demo/app/billing.py``). So the scan set is TEMPLATE-EXPANDED and matching is
boundary-aware. Commit shas are not in any token bank and get their own veto,
which must include the hand-authored anchor (its shas are not generator
output).
"""

from __future__ import annotations

import functools
import json
import re
from pathlib import Path

from evals.scenarios.generator import bank_vocabulary, generate_scenarios

_FIXTURES_DIR = Path(__file__).resolve().parents[1] / "scenarios" / "fixtures"


@functools.cache
def bank_scan_strings(split: str) -> tuple[str, ...]:
    """Every concrete string a split's bank can render: the literal token
    groups plus all template expansions (commit messages over module stems,
    error signatures over modules/keys) plus the culprit file paths. For
    ``"holdout"`` this is the contamination scan set; for ``"fixtures"`` it is
    the training-vocabulary set the matrix's holdout-trace audit looks for in
    tool-call arguments (DR-0020 decision 8 -- the train split reuses the
    fixtures bank verbatim)."""
    v = bank_vocabulary(split)
    strings: set[str] = set()
    for group in (
        "routes",
        "modules",
        "config_files",
        "config_keys",
        "decoy_msgs",
        "resource_metrics",
        "resource_msgs",
        "resource_errors",
    ):
        strings.update(v[group])
    stems = [m.split(".")[0] for m in v["modules"]]
    strings.update(t.format(mod=s) for t in v["deploy_msgs"] for s in stems)
    strings.update(t.format(module=m) for t in v["code_errors"] for m in v["modules"])
    strings.update(t.format(key=k) for t in v["config_msgs"] for k in v["config_keys"])
    strings.update(
        t.format(key=k) for t in v["config_errors"] for k in v["config_keys"]
    )
    strings.update(f"demo/app/{s}.py" for s in stems)
    strings.update(f"demo/app/{m.split('_')[0]}.py" for m in v["resource_metrics"])
    return tuple(sorted(strings))


def holdout_scan_strings() -> tuple[str, ...]:
    """The holdout bank's scan set -- the original DR-0020 decision-7 surface."""
    return bank_scan_strings("holdout")


# Boundary form: (?<!\w)tok(?!\w). Known, accepted limitation: for tokens whose
# first char is non-word (the five holdout routes), a leak embedded directly
# after a word char ("api/search") is NOT caught — the same lookbehind is what
# keeps the holdout route '/billing' from false-positive-matching the
# legitimate fixtures path 'demo/app/billing.py' (billing is a FIXTURES module
# stem). No recipe composes holdout tokens into sub-paths, and the measured
# recall on serialized holdout scenarios is 16/16 with 0 false positives on the
# committed fixtures; revisit if a template ever renders routes into paths.


@functools.cache
def _fast_scan(split: str) -> re.Pattern[str]:
    """One alternation over every scan string (longest-first so a superstring
    wins over its own substrings) — the clean-path check runs ~17x faster than
    a per-token loop over the 300-example corpus."""
    toks = sorted(bank_scan_strings(split), key=len, reverse=True)
    return re.compile(r"(?<!\w)(?:" + "|".join(map(re.escape, toks)) + r")(?!\w)")


@functools.cache
def _per_token(split: str) -> tuple[tuple[str, re.Pattern[str]], ...]:
    return tuple(
        (tok, re.compile(r"(?<!\w)" + re.escape(tok) + r"(?!\w)"))
        for tok in bank_scan_strings(split)
    )


def find_bank_tokens(text: str, split: str) -> set[str]:
    """The ``split``-bank-renderable strings present in ``text`` (empty =
    clean), boundary-aware. Fast single-regex pass on the clean path; the
    per-token loop runs only to NAME the matched tokens once something hit."""
    if not _fast_scan(split).search(text):
        return set()
    return {tok for tok, pat in _per_token(split) if pat.search(text)}


def find_holdout_leaks(text: str) -> set[str]:
    """The holdout-renderable strings present in ``text`` (empty = clean)."""
    return find_bank_tokens(text, "holdout")


def assert_no_holdout_leakage(text: str, where: str) -> None:
    leaks = find_holdout_leaks(text)
    assert not leaks, f"holdout contamination in {where}: {sorted(leaks)}"


def holdout_shas() -> set[str]:
    """Holdout commit shas, from the generator (in-memory — the builder never
    reads the holdout directory; the tests separately check the committed dir)."""
    return {c["sha"] for s in generate_scenarios("holdout") for c in s.commits}


def committed_fixture_ids_and_shas(
    fixtures_dir: Path = _FIXTURES_DIR,
) -> tuple[set[str], set[str]]:
    """Ids and commit shas of the COMMITTED fixtures, read from disk — the
    hand-authored anchor is not generator output, so a generator-based check
    would miss exactly the item DR-0020 calls out."""
    ids: set[str] = set()
    shas: set[str] = set()
    for path in sorted(fixtures_dir.glob("*.json")):
        doc = json.loads(path.read_text(encoding="utf-8"))
        ids.add(doc["id"])
        shas.update(c["sha"] for c in doc["commits"])
    return ids, shas
