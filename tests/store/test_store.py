"""Store: migrations, WAL, DAO round-trips (Wave 7, T7.1)."""

from __future__ import annotations

import json

from quellgeist import store
from quellgeist.store import dao
from quellgeist.store.models import Incident, RunRecord


def _incident(iid="inc-1", status="queued"):
    return Incident(
        id=iid,
        source="webhook",
        received_ts="2026-07-09T10:00:00Z",
        signals_ref=f"/snap/{iid}",
        status=status,
        hint=None,
    )


def test_init_db_creates_schema_and_enables_wal(tmp_path):
    db = tmp_path / "q.db"
    store.init_db(db)
    conn = store.connect(db)
    try:
        mode = conn.execute("PRAGMA journal_mode").fetchone()[0]
        assert mode.lower() == "wal"
        tables = {
            r[0]
            for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
        }
        assert {"incidents", "runs", "diagnoses", "evidence", "events"} <= tables
    finally:
        conn.close()


def test_migrations_are_idempotent(tmp_path):
    db = tmp_path / "q.db"
    conn = store.connect(db)
    try:
        first = store.apply_migrations(conn)
        second = store.apply_migrations(conn)
        assert first == ["001"]  # applied once
        assert second == []  # no-op on re-run
    finally:
        conn.close()


def test_incident_and_run_round_trip(tmp_path):
    db = tmp_path / "q.db"
    store.init_db(db)
    conn = store.connect(db)
    try:
        dao.create_incident(conn, _incident())
        got = dao.get_incident(conn, "inc-1")
        assert got is not None and got.status == "queued" and got.source == "webhook"

        dao.set_incident_status(conn, "inc-1", "pending_review")
        assert dao.get_incident(conn, "inc-1").status == "pending_review"

        run = RunRecord(
            id="run-1",
            incident_id="inc-1",
            model="fake",
            started_ts="2026-07-09T10:00:01Z",
            ended_ts="2026-07-09T10:00:03Z",
            steps=3,
            outcome="diagnosed",
            abstained=False,
            fabricated="",
            prompt_tokens=100,
            completion_tokens=20,
            latency_s=1.5,
            trace_json=json.dumps({"messages": []}),
        )
        dao.record_run(conn, run)
        dao.record_diagnosis(
            conn,
            "run-1",
            summary="s",
            diagnosis_json=json.dumps({"hypotheses": []}),
        )
        dao.record_evidence(conn, "run-1", [(0, "log", "2"), (0, "commit", "a1b2c3d")])
        dao.append_event(conn, "inc-1", "diagnosed", run_id="run-1")

        runs = dao.list_runs(conn, "inc-1")
        assert [r.id for r in runs] == ["run-1"]
        assert runs[0].prompt_tokens == 100 and runs[0].abstained is False

        ev_rows = conn.execute(
            "SELECT handle_type, handle_id FROM evidence WHERE run_id='run-1' "
            "ORDER BY handle_type"
        ).fetchall()
        assert {(r[0], r[1]) for r in ev_rows} == {("commit", "a1b2c3d"), ("log", "2")}

        events = dao.list_events(conn, "inc-1")
        assert [e["kind"] for e in events] == ["diagnosed"]
    finally:
        conn.close()


def test_get_incident_missing_returns_none(tmp_path):
    db = tmp_path / "q.db"
    store.init_db(db)
    conn = store.connect(db)
    try:
        assert dao.get_incident(conn, "nope") is None
    finally:
        conn.close()
