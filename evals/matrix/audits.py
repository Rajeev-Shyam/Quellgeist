"""Trace-level audits for the comparison matrix (DR-0020 decision 8).

Pass rates cannot distinguish a learned broad-first policy from a memorised
script (a vocabulary-blind positional policy passes 81/81 -- DR-0020 context),
so every matrix cell records what the traces DID alongside what they scored:

- ``unobserved_argument_values``: tool-call argument values that appear in no
  earlier observation of the same trace -- the direct measurement that
  speculative filtering (the DR-0019 baseline failure mode) is fixed. Same
  containment semantics as the training builder's evidence-derived-narrowing
  gate (``evals/training/trajectories.py``), applied to live transcripts.
- ``fixtures_bank_argument_leaks``: tool-call argument values containing
  fixtures/train-bank vocabulary (boundary-aware, template-expanded -- the
  train split reuses the fixtures bank verbatim). Meaningful on HOLDOUT traces
  only: on fixtures-distribution runs grounded narrowing legitimately carries
  these tokens, so the runner applies this audit to holdout cells.
- ``train_timestamp_argument_leaks``: argument values that are exact
  train-corpus timestamps AND unobserved in-trace -- the channel the
  token-bank scans cannot see (both splits share the timestamp epoch,
  DR-0020 decision 8).
- ``semantic_core`` / ``core_overlaps_train``: the DR-0020 context-4 core
  (class x route x error signature x culprit message x files/metric), so
  fixtures results are reported split into core-overlapping vs core-fresh
  subsets instead of as one "generalisation" number.
"""

from __future__ import annotations

import functools
from collections.abc import Iterator
from typing import Any

from evals.scenarios.generator import Scenario, generate_scenarios
from evals.training.contamination import find_bank_tokens
from quellgeist.agent.actions import JSONActionError, extract_json

_OBS_PREFIX = "Observation from "

Violation = dict[str, Any]


def _tool_actions(
    messages: list[dict[str, str]],
) -> Iterator[tuple[str, dict[str, Any], tuple[str, ...]]]:
    """Yield ``(action, args, observations_seen_before_this_call)`` for every
    parseable tool action in a transcript. Unparseable assistant turns are
    schema violations counted elsewhere; ``diagnose`` turns cite evidence,
    which the fabrication check owns -- neither is an *argument* audit's job."""
    seen: list[str] = []
    for m in messages:
        if m["role"] == "user" and m["content"].startswith(_OBS_PREFIX):
            seen.append(m["content"])
        elif m["role"] == "assistant":
            try:
                obj = extract_json(m["content"])
            except JSONActionError:
                continue
            action = obj.get("action")
            args = obj.get("args")
            if action and action != "diagnose" and isinstance(args, dict):
                yield str(action), args, tuple(seen)


def unobserved_argument_values(messages: list[dict[str, str]]) -> list[Violation]:
    """Tool-call argument values not contained in any EARLIER observation of
    the same trace. ``None`` means "no filter" and is never a violation; the
    taught policy's broad first call is argument-free, so on a policy-following
    trace this list is empty and every entry is a speculative filter.

    Containment is substring (``str(value) in obs``), matching the training
    builder's evidence-derived-narrowing gate verbatim so the two agree. Known
    blind spot inherited from that gate: a short or numeric value (e.g.
    ``limit=5``) trivially appears inside some observation (an id, a timestamp
    digit), so it reads as "observed" even when speculative. This does not
    weaken the measurement of the DR-0019 failure mode, whose invented values
    are long strings -- ``route`` (e.g. ``api/v1/orders``) and over-narrow
    ``since`` timestamps -- which never spuriously match; it only means the
    audit does not adjudicate numeric filters, which the taught policy does not
    emit anyway."""
    out: list[Violation] = []
    for action, args, seen in _tool_actions(messages):
        for name, value in args.items():
            if value is None:
                continue
            if not any(str(value) in obs for obs in seen):
                out.append({"action": action, "arg": name, "value": value})
    return out


def fixtures_bank_argument_leaks(messages: list[dict[str, str]]) -> list[Violation]:
    """Tool-call argument values carrying fixtures/train-bank vocabulary.
    On a holdout trace no observation can contain these tokens (disjoint
    banks), so any hit is training vocabulary re-entering as a filter value --
    the specific channel DR-0020 decision 8 names."""
    out: list[Violation] = []
    for action, args, _seen in _tool_actions(messages):
        for name, value in args.items():
            if value is None:
                continue
            tokens = find_bank_tokens(str(value), "fixtures")
            if tokens:
                out.append(
                    {
                        "action": action,
                        "arg": name,
                        "value": value,
                        "tokens": sorted(tokens),
                    }
                )
    return out


@functools.cache
def _train_scenarios() -> tuple[Scenario, ...]:
    return tuple(generate_scenarios("train"))


@functools.cache
def train_timestamps() -> frozenset[str]:
    """Every timestamp string the train corpus can contain: scenario ``now``,
    log ``ts``, commit ``ts``, and metric point ``ts`` values."""
    out: set[str] = set()
    for s in _train_scenarios():
        out.add(s.now)
        out.update(r["ts"] for r in s.logs if "ts" in r)
        out.update(c["ts"] for c in s.commits if "ts" in c)
        for series in s.metrics:
            out.update(p["ts"] for p in series.get("points", []) if "ts" in p)
    return frozenset(out)


def train_timestamp_argument_leaks(messages: list[dict[str, str]]) -> list[Violation]:
    """Argument values that are exact train-seen timestamps AND appear in no
    earlier observation. An observed timestamp is grounded even if it happens
    to collide with a train value (both splits share the epoch); an UNOBSERVED
    one on a holdout trace can only have come from training memory."""
    ts = train_timestamps()
    out: list[Violation] = []
    for action, args, seen in _tool_actions(messages):
        for name, value in args.items():
            if not isinstance(value, str) or value not in ts:
                continue
            if not any(value in obs for obs in seen):
                out.append({"action": action, "arg": name, "value": value})
    return out


def semantic_core(s: Scenario) -> tuple[Any, ...]:
    """The DR-0020 context-4 semantic core: class x route x error signature x
    culprit message x files/metric. Two scenarios with equal cores differ only
    in ids/shas/timestamps -- a post-tune pass on a core-overlapping fixture is
    same-bank recall of a trained core, not recombination."""
    gold_shas = {r.sha for r in s.gold_evidence_refs if r.type == "commit"}
    culprit = next((c for c in s.commits if c.get("sha") in gold_shas), None)
    err = next((r for r in s.logs if r.get("level") == "ERROR"), None)
    return (
        s.failure_class,
        err["route"] if err else None,
        err["msg"] if err else None,
        culprit["msg"] if culprit else None,
        tuple(culprit["files"]) if culprit else None,
        s.metrics[0]["metric"] if s.metrics else None,
    )


@functools.cache
def train_cores() -> frozenset[tuple[Any, ...]]:
    return frozenset(semantic_core(s) for s in _train_scenarios())


def core_overlaps_train(s: Scenario) -> bool:
    return semantic_core(s) in train_cores()
