"""Tests for the deterministic timing-aware verifier (Wave 10, T10.1; DR-0024).

Keyless and model-free by construction -- causal ordering is a timestamp
comparison, so every case here is exact, not statistical.
"""

from __future__ import annotations

from quellgeist.agent.schema import CommitRef, Diagnosis, Hypothesis, LogRef
from quellgeist.agent.timing_verifier import (
    _first_error_ts,
    _parse_ts,
    verify_timing,
)

# First error at 10:02:12; the deploy that would need to cause it is the variable.
LOGS = [
    {
        "id": 0,
        "ts": "2026-06-18T09:55:01Z",
        "level": "INFO",
        "route": "/x",
        "msg": "ok",
    },
    {
        "id": 2,
        "ts": "2026-06-18T10:02:12Z",
        "level": "ERROR",
        "route": "/x",
        "msg": "boom",
    },
    {
        "id": 3,
        "ts": "2026-06-18T10:03:00Z",
        "level": "ERROR",
        "route": "/x",
        "msg": "boom",
    },
]


def _commit(sha: str, ts: str) -> dict:
    return {"sha": sha, "ts": ts, "msg": "deploy", "files": ["demo/app/auth.py"]}


def _diag(cause: str, evidence: list) -> Diagnosis:
    return Diagnosis(
        summary="s",
        hypotheses=[Hypothesis(cause=cause, confidence=0.9, evidence=evidence)],
    )


# --------------------------------------------------------------------------- #
# Core rule: a cause cannot post-date its effect.
# --------------------------------------------------------------------------- #


def test_culprit_after_first_error_is_dropped_to_abstention():
    d = _diag("deploy a1 broke it", [CommitRef(sha="a1"), LogRef(id=2)])
    commits = [_commit("a1", "2026-06-18T10:12:00Z")]  # 10 min AFTER first error
    res = verify_timing(d, LOGS, commits)
    assert res.diagnosis.abstained
    assert res.forced_abstention
    assert res.dropped == ["deploy a1 broke it"]
    assert "cannot follow its effect" in res.diagnosis.abstention_reason


def test_culprit_before_first_error_survives():
    d = _diag("deploy a1 broke it", [CommitRef(sha="a1"), LogRef(id=2)])
    commits = [_commit("a1", "2026-06-18T10:01:50Z")]  # 22 s BEFORE first error
    res = verify_timing(d, LOGS, commits)
    assert not res.diagnosis.abstained
    assert len(res.diagnosis.hypotheses) == 1
    assert res.verdicts[0].supported


def test_culprit_exactly_at_first_error_survives():
    # A tie is NOT a strict violation -- deploy landing at the first error second is
    # a plausible trigger, so timing does not rule it out (support verifier's call).
    d = _diag("deploy a1 broke it", [CommitRef(sha="a1")])
    commits = [_commit("a1", "2026-06-18T10:02:12Z")]
    res = verify_timing(d, LOGS, commits)
    assert not res.diagnosis.abstained


# --------------------------------------------------------------------------- #
# Conservative in its OWN direction: only drops on a PROVABLE violation.
# --------------------------------------------------------------------------- #


def test_hypothesis_with_no_cited_commit_is_untouched():
    d = _diag("something in the logs", [LogRef(id=2)])
    res = verify_timing(d, LOGS, [_commit("a1", "2026-06-18T10:12:00Z")])
    assert (
        not res.diagnosis.abstained
    )  # timing has nothing to say about log-only claims


def test_unresolvable_commit_is_not_a_timing_drop():
    # A cited sha absent from the signals is the fabrication check's job, not timing's.
    d = _diag("deploy zzz broke it", [CommitRef(sha="zzz")])
    res = verify_timing(d, LOGS, [_commit("a1", "2026-06-18T10:12:00Z")])
    assert not res.diagnosis.abstained


def test_one_cited_commit_before_error_keeps_hypothesis():
    # Two cited commits, one before the first error: the causal story is viable.
    d = _diag(
        "deploy a1/a2 broke it",
        [CommitRef(sha="a1"), CommitRef(sha="a2")],
    )
    commits = [
        _commit("a1", "2026-06-18T10:12:00Z"),  # after
        _commit("a2", "2026-06-18T10:01:00Z"),  # before -> anchors the cause
    ]
    res = verify_timing(d, LOGS, commits)
    assert not res.diagnosis.abstained


def test_all_cited_commits_after_error_is_dropped():
    d = _diag("deploy a1/a2 broke it", [CommitRef(sha="a1"), CommitRef(sha="a2")])
    commits = [
        _commit("a1", "2026-06-18T10:12:00Z"),
        _commit("a2", "2026-06-18T10:20:00Z"),
    ]
    res = verify_timing(d, LOGS, commits)
    assert res.diagnosis.abstained


def test_no_dated_error_means_no_objection():
    logs = [{"id": 1, "level": "ERROR", "route": "/x", "msg": "boom"}]  # no ts
    d = _diag("deploy a1 broke it", [CommitRef(sha="a1")])
    res = verify_timing(d, logs, [_commit("a1", "2026-06-18T10:12:00Z")])
    assert not res.diagnosis.abstained


def test_unparseable_commit_ts_means_no_objection():
    d = _diag("deploy a1 broke it", [CommitRef(sha="a1")])
    commits = [{"sha": "a1", "ts": "not-a-date", "msg": "d", "files": []}]
    res = verify_timing(d, LOGS, commits)
    assert not res.diagnosis.abstained


def test_already_abstained_passes_through_unchanged():
    d = Diagnosis(abstained=True, abstention_reason="no culprit", hypotheses=[])
    res = verify_timing(d, LOGS, [_commit("a1", "2026-06-18T10:12:00Z")])
    assert res.diagnosis is d
    assert res.verdicts == []


# --------------------------------------------------------------------------- #
# Multi-hypothesis: drop only the timing-impossible ones.
# --------------------------------------------------------------------------- #


def test_mixed_hypotheses_drops_only_the_late_one():
    d = Diagnosis(
        summary="s",
        hypotheses=[
            Hypothesis(cause="late a1", confidence=0.9, evidence=[CommitRef(sha="a1")]),
            Hypothesis(
                cause="early a2", confidence=0.8, evidence=[CommitRef(sha="a2")]
            ),
        ],
    )
    commits = [
        _commit("a1", "2026-06-18T10:12:00Z"),  # after -> dropped
        _commit("a2", "2026-06-18T10:01:00Z"),  # before -> survives
    ]
    res = verify_timing(d, LOGS, commits)
    assert not res.diagnosis.abstained
    assert [h.cause for h in res.diagnosis.hypotheses] == ["early a2"]
    assert res.dropped == ["late a1"]


# --------------------------------------------------------------------------- #
# Helpers.
# --------------------------------------------------------------------------- #


def test_parse_ts_handles_z_suffix_and_rejects_junk():
    assert _parse_ts("2026-06-18T10:02:12Z") is not None
    assert _parse_ts("2026-06-18T10:02:12") is not None
    assert _parse_ts("nope") is None
    assert _parse_ts(None) is None
    assert _parse_ts(12345) is None


def test_first_error_ts_picks_the_earliest_error():
    got = _first_error_ts(LOGS)
    assert got is not None
    assert got == _parse_ts("2026-06-18T10:02:12Z")


# --------------------------------------------------------------------------- #
# Corpus-grounded probe: the real time_shift class abstains, keyless (acceptance).
# --------------------------------------------------------------------------- #


def test_timing_probes_all_abstain():
    from evals.training.timing_probes import build_timing_probes, timing_abstains

    probes = build_timing_probes()
    assert probes, "expected a non-empty timing probe set"
    # Deterministic verifier -> 100% recall is the bar, not a majority.
    assert all(timing_abstains(p) for p in probes)


def test_timing_probe_scenarios_actually_postdate_the_error():
    # Guard the probe construction itself: each culprit really is after the error.
    from evals.training.timing_probes import build_timing_probes
    from quellgeist.agent.timing_verifier import _first_error_ts, _parse_ts

    for p in build_timing_probes():
        first_err = _first_error_ts(p.scenario.logs)
        culprit = next(c for c in p.scenario.commits if c["sha"] == p.culprit_sha)
        assert _parse_ts(culprit["ts"]) > first_err
