"""Orchestrator: investigate persistence, abstention, concurrency isolation (T7.4)."""

from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor

from quellgeist import store
from quellgeist.agent.providers import CallUsage
from quellgeist.orchestrator import incident_tools, investigate
from quellgeist.store import dao
from quellgeist.store.models import Incident


class FakeProvider:
    def __init__(self, scripted, calls=None):
        self.scripted = list(scripted)
        self.calls = list(calls or [])

    def complete(self, messages):
        return self.scripted.pop(0)


def _snapshot(d, log_rows, commits, metrics=None):
    d.mkdir(parents=True, exist_ok=True)
    (d / "incident_logs.jsonl").write_text(
        "".join(json.dumps(r) + "\n" for r in log_rows), encoding="utf-8"
    )
    (d / "deploy_log.json").write_text(json.dumps(commits), encoding="utf-8")
    (d / "metrics.json").write_text(json.dumps(metrics or []), encoding="utf-8")
    return d


def _diagnose(log_id, sha):
    return json.dumps(
        {
            "action": "diagnose",
            "diagnosis": {
                "summary": "bad deploy broke it",
                "abstained": False,
                "hypotheses": [
                    {
                        "cause": "deploy broke verify_token",
                        "confidence": 0.9,
                        "evidence": [
                            {"type": "log", "id": log_id},
                            {"type": "commit", "sha": sha},
                        ],
                    }
                ],
                "suggested_actions": ["roll back"],
            },
        }
    )


def _investigate_script(log_id, sha):
    return [
        json.dumps({"action": "query_logs", "args": {"level": "ERROR"}}),
        json.dumps({"action": "get_recent_commits", "args": {}}),
        _diagnose(log_id, sha),
    ]


def test_incident_tools_read_their_own_snapshot(tmp_path):
    """Direct isolation: two tool sets bound to different dirs never cross-read."""
    a = _snapshot(
        tmp_path / "a",
        [{"id": 0, "ts": "2026-07-09T10:00:00Z", "level": "ERROR", "msg": "A-only"}],
        [],
    )
    b = _snapshot(
        tmp_path / "b",
        [{"id": 0, "ts": "2026-07-09T10:00:00Z", "level": "ERROR", "msg": "B-only"}],
        [],
    )
    ta = {t.name: t.fn for t in incident_tools(a)}
    tb = {t.name: t.fn for t in incident_tools(b)}
    assert ta["query_logs"]()[0]["msg"] == "A-only"
    assert tb["query_logs"]()[0]["msg"] == "B-only"


def test_investigate_persists_cited_run(tmp_path):
    db = tmp_path / "q.db"
    store.init_db(db)
    conn = store.connect(db)
    dao.create_incident(
        conn,
        Incident(
            "inc-1", "webhook", "2026-07-09T10:00:00Z", str(tmp_path / "snap"), "queued"
        ),
    )
    conn.close()

    snap = _snapshot(
        tmp_path / "snap",
        [
            {"id": 0, "ts": "2026-07-09T10:00:00Z", "level": "INFO", "msg": "ok"},
            {
                "id": 2,
                "ts": "2026-07-09T10:00:02Z",
                "level": "ERROR",
                "msg": "NoneType in verify_token",
            },
        ],
        [
            {
                "sha": "a1b2c3d",
                "ts": "2026-07-09T09:59:00Z",
                "msg": "deploy",
                "files": ["auth.py"],
            }
        ],
    )
    provider = FakeProvider(
        _investigate_script(2, "a1b2c3d"),
        calls=[CallUsage(prompt_tokens=100, completion_tokens=20, latency_s=1.0)],
    )

    res = investigate("inc-1", snap, provider=provider, db_path=db, model="fake")

    assert not res.diagnosis.abstained
    assert res.fabricated == []  # every citation resolves in this snapshot

    conn = store.connect(db)
    try:
        runs = dao.list_runs(conn, "inc-1")
        assert len(runs) == 1
        r = runs[0]
        assert r.outcome == "diagnosed" and r.fabricated == ""
        assert r.prompt_tokens == 100 and r.completion_tokens == 20  # cost captured
        assert dao.get_incident(conn, "inc-1").status == "pending_review"
        ev = conn.execute(
            "SELECT handle_type, handle_id FROM evidence WHERE run_id=?", (r.id,)
        ).fetchall()
        assert {(x[0], x[1]) for x in ev} == {("log", "2"), ("commit", "a1b2c3d")}
        kinds = [e["kind"] for e in dao.list_events(conn, "inc-1")]
        assert "diagnosed" in kinds
    finally:
        conn.close()


def test_investigate_records_abstention(tmp_path):
    db = tmp_path / "q.db"
    store.init_db(db)
    conn = store.connect(db)
    dao.create_incident(
        conn,
        Incident(
            "inc-2", "webhook", "2026-07-09T10:00:00Z", str(tmp_path / "s2"), "queued"
        ),
    )
    conn.close()
    snap = _snapshot(
        tmp_path / "s2",
        [{"id": 0, "ts": "2026-07-09T10:00:00Z", "level": "INFO", "msg": "quiet"}],
        [],
    )
    abstain = json.dumps(
        {
            "action": "diagnose",
            "diagnosis": {
                "abstained": True,
                "abstention_reason": "insufficient",
                "hypotheses": [],
            },
        }
    )
    provider = FakeProvider([abstain])

    res = investigate("inc-2", snap, provider=provider, db_path=db, model="fake")

    assert res.diagnosis.abstained
    conn = store.connect(db)
    try:
        (r,) = dao.list_runs(conn, "inc-2")
        assert r.outcome == "abstained" and r.abstained is True
        assert dao.get_incident(conn, "inc-2").status == "pending_review"
    finally:
        conn.close()


class _BoomProvider:
    calls: list = []

    def complete(self, messages):
        raise RuntimeError("provider down")


def test_investigate_persists_failed_on_provider_error(tmp_path):
    db = tmp_path / "q.db"
    store.init_db(db)
    conn = store.connect(db)
    dao.create_incident(
        conn,
        Incident(
            "inc-f", "webhook", "2026-07-09T10:00:00Z", str(tmp_path / "sf"), "queued"
        ),
    )
    conn.close()
    snap = _snapshot(
        tmp_path / "sf",
        [{"id": 0, "ts": "2026-07-09T10:00:00Z", "level": "INFO", "msg": "x"}],
        [],
    )

    res = investigate("inc-f", snap, provider=_BoomProvider(), db_path=db, model="fake")

    assert res.diagnosis.abstained  # degraded fallback
    conn = store.connect(db)
    try:
        (r,) = dao.list_runs(conn, "inc-f")
        assert r.outcome == "failed"
        assert (
            dao.get_incident(conn, "inc-f").status == "failed"
        )  # NOT stuck at running
        assert "failed" in [e["kind"] for e in dao.list_events(conn, "inc-f")]
    finally:
        conn.close()


def test_investigate_failed_persistence_is_terminal_and_preserves_diagnosis(
    tmp_path, monkeypatch
):
    """A failure in the persistence chain (after run_loop succeeds) must still leave the
    incident terminal (not 'running') and keep the diagnosis in the event log."""
    db = tmp_path / "q.db"
    store.init_db(db)
    conn = store.connect(db)
    dao.create_incident(
        conn,
        Incident(
            "inc-p", "webhook", "2026-07-09T10:00:00Z", str(tmp_path / "sp"), "queued"
        ),
    )
    conn.close()
    snap = _snapshot(
        tmp_path / "sp",
        [
            {
                "id": 2,
                "ts": "2026-07-09T10:00:02Z",
                "level": "ERROR",
                "msg": "verify_token",
            }
        ],
        [
            {
                "sha": "a1b2c3d",
                "ts": "2026-07-09T09:59:00Z",
                "msg": "d",
                "files": ["a.py"],
            }
        ],
    )
    # make the post-run_loop persistence blow up
    monkeypatch.setattr(
        dao,
        "record_diagnosis",
        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("db kaput")),
    )
    provider = FakeProvider(_investigate_script(2, "a1b2c3d"))

    investigate("inc-p", snap, provider=provider, db_path=db, model="fake")

    conn = store.connect(db)
    try:
        assert dao.get_incident(conn, "inc-p").status == "failed"  # not stuck 'running'
        failed = [e for e in dao.list_events(conn, "inc-p") if e["kind"] == "failed"]
        assert failed and "diagnosis" in (failed[-1]["detail_json"] or "")  # preserved
    finally:
        conn.close()


def test_concurrent_investigations_are_isolated(tmp_path):
    """N incidents in parallel: each run's trace only ever saw ITS OWN snapshot's
    handles — the concurrency-correctness guarantee (no shared global env)."""
    db = tmp_path / "q.db"
    store.init_db(db)
    conn = store.connect(db)
    for iid, snapname in (("A", "snapA"), ("B", "snapB")):
        dao.create_incident(
            conn,
            Incident(
                iid,
                "webhook",
                "2026-07-09T10:00:00Z",
                str(tmp_path / snapname),
                "queued",
            ),
        )
    conn.close()

    _snapshot(
        tmp_path / "snapA",
        [{"id": 1, "ts": "2026-07-09T10:00:01Z", "level": "ERROR", "msg": "A error"}],
        [
            {
                "sha": "aaaa111",
                "ts": "2026-07-09T09:59:00Z",
                "msg": "A deploy",
                "files": ["a.py"],
            }
        ],
    )
    _snapshot(
        tmp_path / "snapB",
        [{"id": 1, "ts": "2026-07-09T10:00:01Z", "level": "ERROR", "msg": "B error"}],
        [
            {
                "sha": "bbbb222",
                "ts": "2026-07-09T09:59:00Z",
                "msg": "B deploy",
                "files": ["b.py"],
            }
        ],
    )

    def run(iid, snapname, sha):
        provider = FakeProvider(_investigate_script(1, sha))
        return investigate(
            iid, tmp_path / snapname, provider=provider, db_path=db, model="fake"
        )

    with ThreadPoolExecutor(max_workers=2) as pool:
        futs = [
            pool.submit(run, "A", "snapA", "aaaa111"),
            pool.submit(run, "B", "snapB", "bbbb222"),
        ]
        results = {f.result().run.incident_id: f.result() for f in futs}

    assert results["A"].fabricated == [] and results["B"].fabricated == []

    conn = store.connect(db)
    try:
        for iid, own, other in (
            ("A", "aaaa111", "bbbb222"),
            ("B", "bbbb222", "aaaa111"),
        ):
            (r,) = dao.list_runs(conn, iid)
            seen = json.loads(r.trace_json)["seen_handles"]
            seen_shas = {h[1] for h in seen if h[0] == "commit"}
            assert own in seen_shas, f"{iid} should see its own deploy"
            assert (
                other not in seen_shas
            ), f"{iid} must NOT see the other incident's deploy"
            assert dao.get_incident(conn, iid).status == "pending_review"
    finally:
        conn.close()
