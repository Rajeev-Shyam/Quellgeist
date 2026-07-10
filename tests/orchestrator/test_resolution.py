"""Resolution-verification (Wave 9, T9.1): deterministic, keyless, snapshot-independent.

Every case drives ``verify_resolution`` over explicit ``current_signals`` (or live files),
asserting the recovered/not_recovered/inconclusive verdict and its persisted event — no
model, no network.
"""

from __future__ import annotations

import json

import pytest

from quellgeist import store
from quellgeist.orchestrator import ResolutionError, verify_resolution
from quellgeist.service.config import ServiceConfig
from quellgeist.store import dao
from quellgeist.store.models import Incident, RunRecord

RUN_START = "2026-07-09T10:00:00Z"
RUN_END = "2026-07-09T10:00:05Z"
FIX_TS = "2026-07-09T10:05:00Z"  # the fix deploy lands after the run


def _log(ts, level, route, status, id_):
    return {"id": id_, "ts": ts, "level": level, "route": route, "status": status}


def _setup(tmp_path, *, status="posted", ended=RUN_END):
    db = tmp_path / "q.db"
    store.init_db(db)
    conn = store.connect(db)
    dao.create_incident(
        conn,
        Incident("inc", "webhook", RUN_START, str(tmp_path / "snap"), status),
    )
    dao.record_run(
        conn,
        RunRecord(
            id="run-1",
            incident_id="inc",
            model="fake",
            started_ts=RUN_START,
            ended_ts=ended,
            outcome="diagnosed",
        ),
    )
    conn.close()
    return ServiceConfig(db_path=str(db))


# --- the three verdicts ---------------------------------------------------------


def test_recovered_when_signature_clears_and_post_traffic_is_healthy(tmp_path):
    config = _setup(tmp_path)
    logs = [
        _log("2026-07-09T10:00:02Z", "ERROR", "/login", 500, 0),  # incident (pre-fix)
        _log("2026-07-09T10:00:03Z", "ERROR", "/login", 500, 1),
        _log("2026-07-09T10:06:00Z", "INFO", "/login", 200, 2),  # healthy post-fix
    ]
    commits = [{"sha": "f1c2d3e", "ts": FIX_TS, "msg": "fix: restore guard"}]
    v = verify_resolution("inc", config=config, current_signals=(logs, commits, []))
    assert v.verdict == "recovered"
    assert v.error_routes == ["/login"]
    assert v.residual_error_routes == []
    assert v.recovered_routes == ["/login"]
    assert v.since == FIX_TS  # boundary auto-derived from the fix deploy


def test_not_recovered_when_errors_persist_after_the_fix(tmp_path):
    config = _setup(tmp_path)
    logs = [
        _log("2026-07-09T10:00:02Z", "ERROR", "/login", 500, 0),
        _log("2026-07-09T10:06:00Z", "ERROR", "/login", 500, 1),  # STILL erroring
    ]
    commits = [{"sha": "f1c2d3e", "ts": FIX_TS, "msg": "fix"}]
    v = verify_resolution("inc", config=config, current_signals=(logs, commits, []))
    assert v.verdict == "not_recovered"
    assert v.residual_error_routes == ["/login"]


def test_inconclusive_when_signature_not_visible(tmp_path):
    """A reset that truncated the log leaves no pre-fix error signature to check."""
    config = _setup(tmp_path)
    logs = [_log("2026-07-09T10:06:00Z", "INFO", "/login", 200, 0)]  # only post-fix
    commits = [{"sha": "f1c2d3e", "ts": FIX_TS, "msg": "fix"}]
    v = verify_resolution("inc", config=config, current_signals=(logs, commits, []))
    assert v.verdict == "inconclusive"
    assert v.error_routes == []


def test_inconclusive_when_no_post_fix_traffic(tmp_path):
    config = _setup(tmp_path)
    logs = [_log("2026-07-09T10:00:02Z", "ERROR", "/login", 500, 0)]  # nothing after
    commits = [{"sha": "f1c2d3e", "ts": FIX_TS, "msg": "fix"}]
    v = verify_resolution("inc", config=config, current_signals=(logs, commits, []))
    assert v.verdict == "inconclusive"
    assert v.unconfirmed_routes == ["/login"]


def test_multi_route_partial_recovery_is_inconclusive(tmp_path):
    """A 2-route signature where only one route has post-fix traffic must NOT over-claim
    'recovered' — the silent route is unconfirmed."""
    config = _setup(tmp_path)
    logs = [
        _log("2026-07-09T10:00:02Z", "ERROR", "/login", 500, 0),
        _log("2026-07-09T10:00:02Z", "ERROR", "/pay", 500, 1),
        _log("2026-07-09T10:06:00Z", "INFO", "/login", 200, 2),  # /pay stays silent
    ]
    v = verify_resolution("inc", config=config, current_signals=(logs, [], []))
    assert v.verdict == "inconclusive"
    assert v.recovered_routes == ["/login"]
    assert v.unconfirmed_routes == ["/pay"]


def test_all_signature_routes_confirmed_is_recovered(tmp_path):
    config = _setup(tmp_path)
    logs = [
        _log("2026-07-09T10:00:02Z", "ERROR", "/login", 500, 0),
        _log("2026-07-09T10:00:02Z", "ERROR", "/pay", 500, 1),
        _log("2026-07-09T10:06:00Z", "INFO", "/login", 200, 2),
        _log("2026-07-09T10:06:01Z", "INFO", "/pay", 200, 3),  # both confirmed healthy
    ]
    v = verify_resolution("inc", config=config, current_signals=(logs, [], []))
    assert v.verdict == "recovered"
    assert v.recovered_routes == ["/login", "/pay"]
    assert v.unconfirmed_routes == []


def test_routeless_signature_never_claims_recovered(tmp_path):
    """A routeless error (e.g. a worker crash log with no route) can't be attributed to the
    post-fix routeless traffic, so it is inconclusive, never recovered."""
    config = _setup(tmp_path)
    logs = [
        {"id": 0, "ts": "2026-07-09T10:00:02Z", "level": "ERROR", "msg": "job crashed"},
        {"id": 1, "ts": "2026-07-09T10:06:00Z", "level": "INFO", "msg": "worker tick"},
    ]
    v = verify_resolution("inc", config=config, current_signals=(logs, [], []))
    assert v.verdict == "inconclusive"
    assert v.recovered_routes == []
    assert v.unconfirmed_routes == ["<unrouted>"]


def test_routeless_error_still_present_is_not_recovered(tmp_path):
    config = _setup(tmp_path)
    logs = [
        {"id": 0, "ts": "2026-07-09T10:00:02Z", "level": "ERROR", "msg": "job crashed"},
        {"id": 1, "ts": "2026-07-09T10:06:00Z", "level": "ERROR", "msg": "job crashed"},
    ]
    v = verify_resolution("inc", config=config, current_signals=(logs, [], []))
    assert v.verdict == "not_recovered"
    assert v.residual_error_routes == ["<unrouted>"]


# --- boundary derivation --------------------------------------------------------


def test_explicit_since_overrides_derived_boundary(tmp_path):
    config = _setup(tmp_path)
    logs = [
        _log("2026-07-09T10:00:02Z", "ERROR", "/login", 500, 0),
        _log("2026-07-09T10:03:00Z", "INFO", "/login", 200, 1),  # between end and fix
    ]
    # With since pinned before the healthy line, it counts as post-fix -> recovered.
    v = verify_resolution(
        "inc",
        config=config,
        current_signals=(logs, [], []),
        since="2026-07-09T10:01:00Z",
    )
    assert v.verdict == "recovered"
    assert v.since == "2026-07-09T10:01:00Z"


def test_boundary_falls_back_to_run_end_without_a_fix_deploy(tmp_path):
    config = _setup(tmp_path)
    # No deploy after the run -> boundary = run.ended_ts (RUN_END).
    logs = [
        _log("2026-07-09T10:00:02Z", "ERROR", "/login", 500, 0),
        _log("2026-07-09T10:06:00Z", "INFO", "/login", 200, 1),
    ]
    v = verify_resolution("inc", config=config, current_signals=(logs, [], []))
    assert v.since == RUN_END
    assert v.verdict == "recovered"


# --- persistence + errors -------------------------------------------------------


def test_verdict_is_persisted_as_a_resolution_event(tmp_path):
    config = _setup(tmp_path)
    logs = [
        _log("2026-07-09T10:00:02Z", "ERROR", "/login", 500, 0),
        _log("2026-07-09T10:06:00Z", "INFO", "/login", 200, 1),
    ]
    verify_resolution("inc", config=config, current_signals=(logs, [], []))
    conn = store.connect(config.db_path)
    try:
        ev = dao.latest_event(conn, "inc", "resolution")
        assert ev is not None and ev["run_id"] == "run-1"
        detail = json.loads(ev["detail_json"])
        assert detail["verdict"] == "recovered"
    finally:
        conn.close()


def test_unknown_incident_and_missing_run_raise(tmp_path):
    config = _setup(tmp_path)
    with pytest.raises(ResolutionError) as ei:
        verify_resolution("nope", config=config, current_signals=([], [], []))
    assert ei.value.status_code == 404
    with pytest.raises(ResolutionError) as er:
        verify_resolution(
            "inc", config=config, run_id="ghost", current_signals=([], [], [])
        )
    assert er.value.status_code == 404


def test_no_run_to_verify_raises_409(tmp_path):
    db = tmp_path / "q.db"
    store.init_db(db)
    conn = store.connect(db)
    dao.create_incident(
        conn, Incident("bare", "webhook", RUN_START, str(tmp_path / "s"), "queued")
    )
    conn.close()
    config = ServiceConfig(db_path=str(db))
    with pytest.raises(ResolutionError) as e:
        verify_resolution("bare", config=config, current_signals=([], [], []))
    assert e.value.status_code == 409


# --- reads live files + metric corroboration ------------------------------------


def test_reads_live_signal_files_when_no_seam(tmp_path):
    """Cover the real _read_current_signals path via config's live paths."""
    db = tmp_path / "q.db"
    store.init_db(db)
    conn = store.connect(db)
    dao.create_incident(
        conn, Incident("inc", "webhook", RUN_START, str(tmp_path / "s"), "posted")
    )
    dao.record_run(
        conn,
        RunRecord(
            "run-1", "inc", "fake", RUN_START, ended_ts=RUN_END, outcome="diagnosed"
        ),
    )
    conn.close()
    log_file = tmp_path / "live.jsonl"
    log_file.write_text(
        json.dumps(_log("2026-07-09T10:00:02Z", "ERROR", "/login", 500, 0))
        + "\n"
        + json.dumps(_log("2026-07-09T10:06:00Z", "INFO", "/login", 200, 1))
        + "\n"
    )
    config = ServiceConfig(
        db_path=str(db),
        log_path=str(log_file),
        deploy_path=str(tmp_path / "absent-deploys.json"),
        metrics_path=str(tmp_path / "absent-metrics.json"),
    )
    v = verify_resolution("inc", config=config)
    assert v.verdict == "recovered"


def test_metric_notes_record_error_rate_trend(tmp_path):
    config = _setup(tmp_path)
    logs = [
        _log("2026-07-09T10:00:02Z", "ERROR", "/login", 500, 0),
        _log("2026-07-09T10:06:00Z", "INFO", "/login", 200, 1),
    ]
    metrics = [
        {
            "metric": "qg_errors_total",
            "unit": "",
            "points": [
                {"ts": "2026-07-09T10:00:02Z", "value": 12.0},
                {"ts": "2026-07-09T10:06:00Z", "value": 0.0},
            ],
        }
    ]
    v = verify_resolution("inc", config=config, current_signals=(logs, [], metrics))
    assert any("qg_errors_total" in n and "down" in n for n in v.metric_notes)
