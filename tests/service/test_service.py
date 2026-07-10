"""Service: signature, idempotency, snapshot isolation, full webhook→persist (T7.3).

Keyless: the provider is a scripted fake injected via ServiceConfig, so the worker runs
the real loop with no model.
"""

from __future__ import annotations

import asyncio
import json
import threading
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from quellgeist import notify, store
from quellgeist.agent.schema import Diagnosis
from quellgeist.notify import PublishRefused
from quellgeist.orchestrator.hint import HintProvider
from quellgeist.orchestrator.investigate import InvestigationResult
from quellgeist.service import ServiceConfig, create_app
from quellgeist.service.queue import WorkerPool
from quellgeist.service.security import sign
from quellgeist.service.snapshots import snapshot_signals
from quellgeist.store import dao
from quellgeist.store.models import Incident, RunRecord

SECRET = "test-secret-123"
OP_TOKEN = "op-token-abc"


class FakeProvider:
    def __init__(self, scripted):
        self.scripted = list(scripted)
        self.calls = []
        self.seen_messages = (
            []
        )  # each complete() call's message list (for hint assertions)

    def complete(self, messages):
        self.seen_messages.append([dict(m) for m in messages])
        return self.scripted.pop(0)


class FakeVerifier:
    """Scripted verifier provider (keyless): each per-hypothesis check returns supported."""

    def __init__(self, supported=True):
        self.supported = supported
        self.calls = []

    def complete(self, messages):
        return json.dumps({"supported": self.supported, "reason": "scripted"})


class RecordingPoster:
    """Injectable Slack poster that records instead of hitting the network."""

    def __init__(self):
        self.posts = []

    def __call__(self, url, payload):
        self.posts.append((url, payload))


def _script():
    return [
        json.dumps({"action": "query_logs", "args": {"level": "ERROR"}}),
        json.dumps({"action": "get_recent_commits", "args": {}}),
        json.dumps(
            {
                "action": "diagnose",
                "diagnosis": {
                    "summary": "bad deploy",
                    "abstained": False,
                    "hypotheses": [
                        {
                            "cause": "deploy a1b2c3d broke verify_token",
                            "confidence": 0.9,
                            "evidence": [
                                {"type": "log", "id": 2},
                                {"type": "commit", "sha": "a1b2c3d"},
                            ],
                        }
                    ],
                    "suggested_actions": ["roll back"],
                },
            }
        ),
    ]


def _sources(tmp_path):
    """Operator's live signal files the ingress will snapshot per incident."""
    (tmp_path / "logs.jsonl").write_text(
        json.dumps(
            {"id": 0, "ts": "2026-07-09T10:00:00Z", "level": "INFO", "msg": "ok"}
        )
        + "\n"
        + json.dumps(
            {
                "id": 2,
                "ts": "2026-07-09T10:00:02Z",
                "level": "ERROR",
                "msg": "NoneType in verify_token",
            }
        )
        + "\n",
        encoding="utf-8",
    )
    (tmp_path / "deploys.json").write_text(
        json.dumps(
            [
                {
                    "sha": "a1b2c3d",
                    "ts": "2026-07-09T09:59:00Z",
                    "msg": "deploy",
                    "files": ["auth.py"],
                }
            ]
        ),
        encoding="utf-8",
    )
    return tmp_path / "logs.jsonl", tmp_path / "deploys.json"


def _config(
    tmp_path,
    *,
    secret=SECRET,
    verifier_supported=None,
    slack_poster=None,
    webhook_max_skew_s=0,
):
    log_path, deploy_path = _sources(tmp_path)
    vpf = None
    if verifier_supported is not None:
        vpf = lambda: FakeVerifier(verifier_supported)  # noqa: E731
    return ServiceConfig(
        db_path=str(tmp_path / "q.db"),
        signals_dir=str(tmp_path / "signals"),
        webhook_secret=secret,
        num_workers=1,
        model="fake",
        log_path=str(log_path),
        deploy_path=str(deploy_path),
        metrics_path=str(tmp_path / "missing_metrics.json"),
        provider_factory=lambda: FakeProvider(_script()),
        operator_token=OP_TOKEN,
        html_dir=str(tmp_path / "postmortems"),
        verifier_provider_factory=vpf,
        slack_webhook_url=(
            "https://hooks.example/T/B/xxx" if slack_poster is not None else ""
        ),
        slack_poster=slack_poster,
        webhook_max_skew_s=webhook_max_skew_s,
    )


def _post(client, body: dict, *, secret=SECRET, sign_with=None):
    raw = json.dumps(body).encode()
    signature = sign(sign_with if sign_with is not None else secret, raw)
    return client.post(
        "/incidents", content=raw, headers={"x-quellgeist-signature": signature}
    )


def _op(token=OP_TOKEN):
    return {"authorization": f"Bearer {token}"}


def _status(client, iid, *, token=OP_TOKEN):
    """The authenticated JSON status endpoint (GET /incidents/{id} is now the HTML page)."""
    return client.get(f"/incidents/{iid}/status", headers=_op(token))


def test_healthz(tmp_path):
    with TestClient(create_app(_config(tmp_path))) as client:
        assert client.get("/healthz").json() == {"status": "ok"}


def test_bad_signature_rejected(tmp_path):
    with TestClient(create_app(_config(tmp_path))) as client:
        r = _post(client, {"id": "inc-1"}, sign_with="wrong-secret")
        assert r.status_code == 401


def test_missing_secret_is_fail_closed(tmp_path):
    # server configured with no secret -> reject even a "signed" request
    with TestClient(create_app(_config(tmp_path, secret=""))) as client:
        raw = json.dumps({"id": "inc-1"}).encode()
        r = client.post(
            "/incidents", content=raw, headers={"x-quellgeist-signature": sign("", raw)}
        )
        assert r.status_code == 401


def test_good_signature_enqueues(tmp_path):
    cfg = _config(tmp_path)
    with TestClient(create_app(cfg)) as client:
        r = _post(client, {"id": "inc-1"})
        assert r.status_code == 202
        assert r.json()["incident_id"] == "inc-1"
    # incident persisted + snapshot isolated to its own dir
    conn = store.connect(cfg.db_path)
    try:
        inc = dao.get_incident(conn, "inc-1")
        assert inc is not None
        assert inc.signals_ref.endswith("signals/inc-1")
        assert (tmp_path / "signals" / "inc-1" / "incident_logs.jsonl").exists()
    finally:
        conn.close()


def test_duplicate_delivery_is_idempotent(tmp_path):
    cfg = _config(tmp_path)
    with TestClient(create_app(cfg)) as client:
        first = _post(client, {"id": "dup-1"})
        second = _post(client, {"id": "dup-1"})
        assert first.status_code == 202
        assert second.status_code == 200  # no-op
    conn = store.connect(cfg.db_path)
    try:
        n = conn.execute("SELECT COUNT(*) FROM incidents WHERE id='dup-1'").fetchone()[
            0
        ]
        assert n == 1
    finally:
        conn.close()


def test_good_signature_reports_snapshot_count(tmp_path):
    with TestClient(create_app(_config(tmp_path))) as client:
        r = _post(client, {"id": "inc-cnt"})
        assert r.json()["snapshot_files"] == 2  # log + deploy present, metrics absent


def test_incident_id_path_traversal_rejected(tmp_path):
    with TestClient(create_app(_config(tmp_path))) as client:
        for bad in ("../../etc/passwd", "a/b", "..", "with space", "x" * 200):
            assert _post(client, {"id": bad}).status_code == 400, bad
    # nothing escaped the signals dir
    assert not (tmp_path.parent / "etc").exists()


def test_non_object_json_body_rejected(tmp_path):
    with TestClient(create_app(_config(tmp_path))) as client:
        for body in ("null", "42", "[1]", '"x"'):
            raw = body.encode()
            r = client.post(
                "/incidents",
                content=raw,
                headers={"x-quellgeist-signature": sign(SECRET, raw)},
            )
            assert r.status_code == 400, body


def test_non_string_hint_rejected(tmp_path):
    with TestClient(create_app(_config(tmp_path))) as client:
        raw = json.dumps({"id": "inc-h", "hint": {"a": 1}}).encode()
        r = client.post(
            "/incidents",
            content=raw,
            headers={"x-quellgeist-signature": sign(SECRET, raw)},
        )
        assert r.status_code == 400


def test_malformed_json_and_missing_id_rejected(tmp_path):
    with TestClient(create_app(_config(tmp_path))) as client:
        bad = b"{not json"
        assert (
            client.post(
                "/incidents",
                content=bad,
                headers={"x-quellgeist-signature": sign(SECRET, bad)},
            ).status_code
            == 400
        )
        assert _post(client, {"hint": "no id here"}).status_code == 400


def test_unknown_incident_returns_404(tmp_path):
    with TestClient(create_app(_config(tmp_path))) as client:
        assert _status(client, "nope").status_code == 404


def test_oversized_body_rejected_413(tmp_path):
    cfg = _config(tmp_path)
    cfg.max_body_bytes = 50
    with TestClient(create_app(cfg)) as client:
        raw = json.dumps({"id": "big", "hint": "x" * 200}).encode()
        r = client.post(
            "/incidents",
            content=raw,
            headers={"x-quellgeist-signature": sign(SECRET, raw)},
        )
        assert r.status_code == 413


def test_multi_worker_processes_all_incidents(tmp_path):
    """The real queue + multi-worker path (not a direct investigate call): N concurrent
    signed deliveries all reach a terminal persisted run."""
    cfg = _config(tmp_path)
    cfg.num_workers = 3
    ids = [f"m-{i}" for i in range(6)]
    with TestClient(create_app(cfg)) as client:
        for iid in ids:
            assert _post(client, {"id": iid}).status_code == 202
        deadline = time.monotonic() + 15.0
        while time.monotonic() < deadline:
            statuses = [_status(client, i).json()["status"] for i in ids]
            if all(s == "pending_review" for s in statuses):
                break
            time.sleep(0.05)
        assert all(_status(client, i).json()["status"] == "pending_review" for i in ids)
    conn = store.connect(cfg.db_path)
    try:
        for iid in ids:
            assert len(dao.list_runs(conn, iid)) == 1  # each processed exactly once
    finally:
        conn.close()


def test_full_webhook_to_persisted_run(tmp_path):
    """The headline path: signed POST → worker → orchestrator → persisted cited run."""
    cfg = _config(tmp_path)
    with TestClient(create_app(cfg)) as client:
        assert _post(client, {"id": "inc-9"}).status_code == 202
        # let the background worker drain (bounded poll; the fake provider is instant)
        deadline = time.monotonic() + 10.0
        status = None
        while time.monotonic() < deadline:
            body = _status(client, "inc-9").json()
            status = body["status"]
            if status == "pending_review":
                assert body["latest_run"]["outcome"] == "diagnosed"
                assert body["latest_run"]["fabricated"] == ""  # zero fabrication
                break
            time.sleep(0.05)
        assert status == "pending_review", f"worker did not finish (status={status})"

    conn = store.connect(cfg.db_path)
    try:
        (run,) = dao.list_runs(conn, "inc-9")
        assert run.outcome == "diagnosed"
        ev = conn.execute(
            "SELECT handle_type, handle_id FROM evidence WHERE run_id=?", (run.id,)
        ).fetchall()
        assert {(x[0], x[1]) for x in ev} == {("log", "2"), ("commit", "a1b2c3d")}
    finally:
        conn.close()


# --- hardening (six-persona re-review fixes: config / body-cap / durability / shutdown) ---


def test_config_rejects_nonpositive_values():
    # #9/#10: fail fast rather than start a silently-broken service (0 workers -> nothing
    # processed; queue_maxsize 0 -> a silently UNBOUNDED queue).
    for kwargs in ({"num_workers": 0}, {"queue_maxsize": 0}, {"max_body_bytes": 0}):
        with pytest.raises(ValueError):
            ServiceConfig(**kwargs)


def test_body_cap_enforced_while_streaming():
    # #2: the cap must trip WHILE reading (bounding memory) even with no Content-Length,
    # not after `await request.body()` has already buffered the whole payload.
    from fastapi import HTTPException

    from quellgeist.service.app import _read_capped_body

    class FakeReq:
        async def stream(self):
            yield b"x" * 30
            yield b"x" * 30  # running total 60 > cap 50 -> abort before the second yield

    with pytest.raises(HTTPException) as ei:
        asyncio.run(_read_capped_body(FakeReq(), 50))
    assert ei.value.status_code == 413


def test_snapshot_failure_rolls_back_and_returns_503(tmp_path, monkeypatch):
    # #6: a transient snapshot OSError rolls back the claim (frees the id) and returns a
    # retryable 503 — never permanently fails the incident behind the idempotency check.
    def _boom(*a, **k):
        raise OSError("disk full")

    monkeypatch.setattr("quellgeist.service.app.snapshot_signals", _boom)
    cfg = _config(tmp_path)
    with TestClient(create_app(cfg)) as client:
        assert _post(client, {"id": "snap-fail"}).status_code == 503
    conn = store.connect(cfg.db_path)
    try:
        assert dao.get_incident(conn, "snap-fail") is None  # rolled back, id free
    finally:
        conn.close()


def test_queue_full_sheds_503_and_rolls_back(tmp_path, monkeypatch):
    # #4: a full queue sheds with 503 and rolls back, never blocking the handler or
    # leaving a committed-but-unqueued incident.
    async def _full(self, incident_id):
        raise asyncio.QueueFull

    monkeypatch.setattr("quellgeist.service.queue.WorkerPool.enqueue", _full)
    cfg = _config(tmp_path)
    with TestClient(create_app(cfg)) as client:
        assert _post(client, {"id": "shed-1"}).status_code == 503
    conn = store.connect(cfg.db_path)
    try:
        assert dao.get_incident(conn, "shed-1") is None  # rolled back, id free to retry
    finally:
        conn.close()


def test_startup_recovery_reenqueues_stranded_incident(tmp_path):
    # #5: an incident persisted 'queued' but lost from the in-memory queue by a restart is
    # re-enqueued on startup and driven to a terminal persisted run.
    cfg = _config(tmp_path)
    store.init_db(cfg.db_path)
    snap_dir = Path(cfg.signals_dir) / "rec-1"
    snapshot_signals(
        snap_dir,
        log_path=cfg.log_path,
        deploy_path=cfg.deploy_path,
        metrics_path=cfg.metrics_path,
    )
    conn = store.connect(cfg.db_path)
    try:
        dao.create_incident(
            conn,
            Incident(
                id="rec-1",
                source="webhook",
                received_ts="2026-07-09T10:00:00Z",
                signals_ref=str(snap_dir),
                status="queued",
                hint=None,
            ),
        )
    finally:
        conn.close()

    with TestClient(create_app(cfg)) as client:  # lifespan runs recovery on startup
        deadline = time.monotonic() + 10.0
        status = None
        while time.monotonic() < deadline:
            status = _status(client, "rec-1").json()["status"]
            if status == "pending_review":
                break
            time.sleep(0.05)
        assert status == "pending_review"


def test_failed_run_reaps_snapshot(tmp_path, monkeypatch):
    # #11: a terminal-FAILED incident's snapshot dir is reaped. A persistence-chain failure
    # degrades to 'failed' via investigate's terminal guard.
    def _boom(*a, **k):
        raise RuntimeError("db write failed")

    # investigate does `from quellgeist.store import dao`, so patching the shared module
    # attribute makes its persistence chain fail -> terminal 'failed' via the guard.
    monkeypatch.setattr("quellgeist.store.dao.record_run", _boom)
    cfg = _config(tmp_path)
    with TestClient(create_app(cfg)) as client:
        assert _post(client, {"id": "fail-1"}).status_code == 202
        deadline = time.monotonic() + 10.0
        status = None
        while time.monotonic() < deadline:
            status = _status(client, "fail-1").json()["status"]
            if status == "failed":
                break
            time.sleep(0.05)
        assert status == "failed"
    assert not (Path(cfg.signals_dir) / "fail-1").exists()  # snapshot reaped


def test_shutdown_joins_worker_threads(tmp_path):
    # #7: after stop(), no executor thread survives to write to the store.
    cfg = _config(tmp_path)
    cfg.num_workers = 2
    with TestClient(create_app(cfg)) as client:
        assert _post(client, {"id": "sd-1"}).status_code == 202
    alive = [
        t
        for t in threading.enumerate()
        if t.name.startswith("qg-worker") and t.is_alive()
    ]
    assert alive == []


# --- re-review fixes on the hardening diff (reaper vs persisted status; recovery dedup) ---


def test_reaper_keeps_snapshot_when_incident_not_persisted_failed(
    tmp_path, monkeypatch
):
    # re-review B: investigate() may return a 'failed' RunRecord while the terminal 'failed'
    # write was swallowed (row still 'running'). The reaper must key off the PERSISTED
    # status, not the in-memory result — else it deletes a snapshot recovery still needs.
    cfg = _config(tmp_path)
    store.init_db(cfg.db_path)
    snap = Path(cfg.signals_dir) / "keep-1"
    snapshot_signals(
        snap,
        log_path=cfg.log_path,
        deploy_path=cfg.deploy_path,
        metrics_path=cfg.metrics_path,
    )
    conn = store.connect(cfg.db_path)
    try:
        dao.create_incident(
            conn,
            Incident(
                id="keep-1",
                source="webhook",
                received_ts="2026-07-09T10:00:00Z",
                signals_ref=str(snap),
                status="running",  # terminal 'failed' write was lost -> still running
                hint=None,
            ),
        )
    finally:
        conn.close()

    def _fake_investigate(incident_id, signals_ref, **kw):
        run = RunRecord(id="r", incident_id=incident_id, model="m", started_ts="t")
        return InvestigationResult(run, None, [])  # outcome defaults to 'failed'

    monkeypatch.setattr("quellgeist.service.queue.investigate", _fake_investigate)
    WorkerPool(cfg)._process_sync("keep-1")
    assert snap.exists()  # NOT reaped: persisted status is 'running', not 'failed'


def test_recovery_reconciles_completed_running_incident(tmp_path):
    # re-review C: a 'running' incident that already has a completed run is reconciled to
    # pending_review at startup, NOT re-run (no duplicate run persisted).
    cfg = _config(tmp_path)
    store.init_db(cfg.db_path)
    snap = Path(cfg.signals_dir) / "done-1"
    snapshot_signals(
        snap,
        log_path=cfg.log_path,
        deploy_path=cfg.deploy_path,
        metrics_path=cfg.metrics_path,
    )
    conn = store.connect(cfg.db_path)
    try:
        dao.create_incident(
            conn,
            Incident(
                id="done-1",
                source="webhook",
                received_ts="2026-07-09T10:00:00Z",
                signals_ref=str(snap),
                status="running",
                hint=None,
            ),
        )
        dao.record_run(
            conn,
            RunRecord(
                id="run-done",
                incident_id="done-1",
                model="m",
                started_ts="2026-07-09T10:00:01Z",
                outcome="diagnosed",
            ),
        )
    finally:
        conn.close()

    with TestClient(create_app(cfg)) as client:  # recovery runs during startup
        assert _status(client, "done-1").json()["status"] == "pending_review"
    conn = store.connect(cfg.db_path)
    try:
        assert len(dao.list_runs(conn, "done-1")) == 1  # NOT re-run -> still one run
    finally:
        conn.close()


# ============================ Wave 8 — Output + HITL ==============================


def _wait_status(client, iid, target, timeout=10.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if _status(client, iid).json()["status"] == target:
            break
        time.sleep(0.05)
    return _status(client, iid).json()["status"]


def _post_review(client, iid, body, *, token=OP_TOKEN):
    return client.post(f"/incidents/{iid}/review", json=body, headers=_op(token))


def _diag(abstained=False):
    if abstained:
        return Diagnosis(abstained=True, abstention_reason="none")
    return Diagnosis(
        summary="bad deploy",
        abstained=False,
        hypotheses=[
            {
                "cause": "deploy a1b2c3d broke verify_token",
                "confidence": 0.9,
                "evidence": [{"type": "log", "id": 2}],
            }
        ],
        suggested_actions=["roll back"],
    )


# --- T8.0: verifier wiring --------------------------------------------------------


def test_verifier_populates_verified_json(tmp_path):
    cfg = _config(tmp_path, verifier_supported=True)
    with TestClient(create_app(cfg)) as client:
        assert _post(client, {"id": "v-1"}).status_code == 202
        assert _wait_status(client, "v-1", "pending_review") == "pending_review"
    conn = store.connect(cfg.db_path)
    try:
        (run,) = dao.list_runs(conn, "v-1")
        verified = json.loads(dao.get_diagnosis(conn, run.id)["verified_json"])
        assert verified["abstained"] is False  # supported -> hypothesis kept
    finally:
        conn.close()


def test_verifier_forced_abstention_when_unsupported(tmp_path):
    cfg = _config(tmp_path, verifier_supported=False)
    with TestClient(create_app(cfg)) as client:
        assert _post(client, {"id": "v-2"}).status_code == 202
        assert _wait_status(client, "v-2", "pending_review") == "pending_review"
    conn = store.connect(cfg.db_path)
    try:
        (run,) = dao.list_runs(conn, "v-2")
        verified = json.loads(dao.get_diagnosis(conn, run.id)["verified_json"])
        assert verified["abstained"] is True  # verifier dropped the unsupported hyp
    finally:
        conn.close()


def test_no_verifier_leaves_run_unverified(tmp_path):
    cfg = _config(tmp_path)  # no verifier configured
    with TestClient(create_app(cfg)) as client:
        assert _post(client, {"id": "v-3"}).status_code == 202
        assert _wait_status(client, "v-3", "pending_review") == "pending_review"
    conn = store.connect(cfg.db_path)
    try:
        (run,) = dao.list_runs(conn, "v-3")
        assert dao.get_diagnosis(conn, run.id)["verified_json"] is None
    finally:
        conn.close()


def test_verifier_never_pins_the_reasoner_model():
    # DR-0016: no verifier unless a DISTINCT model/factory is pinned (the tuned model must
    # not verify itself). Same model => None => runs stay unverified (fail-closed).
    assert (
        ServiceConfig(model="tuned", verifier_model="tuned").make_verifier_provider()
        is None
    )
    assert ServiceConfig(model="tuned").make_verifier_provider() is None  # unset
    assert (
        ServiceConfig(model="tuned", verifier_model="stronger").make_verifier_provider()
        is not None
    )


# --- T8.3: hint injection ---------------------------------------------------------


def test_hint_provider_appends_one_operator_message():
    base = FakeProvider(["r1", "r2"])
    hp = HintProvider(base, "look at the auth deploy")
    msgs = [{"role": "system", "content": "s"}, {"role": "user", "content": "t"}]
    hp.complete(msgs)
    hp.complete(msgs)  # second call must NOT append again
    hints = [m for m in msgs if m["content"].startswith("Operator hint:")]
    assert hints == [
        {"role": "user", "content": "Operator hint: look at the auth deploy"}
    ]
    assert base.calls == []  # delegated attribute access works (no AttributeError)


def test_hint_reaches_the_model_through_the_live_path(tmp_path):
    cfg = _config(tmp_path)
    captured = {}
    base_factory = cfg.provider_factory
    cfg.provider_factory = lambda: captured.setdefault("p", base_factory())
    with TestClient(create_app(cfg)) as client:
        r = _post(client, {"id": "h-1", "hint": "check verify_token"})
        assert r.status_code == 202
        assert _wait_status(client, "h-1", "pending_review") == "pending_review"
    first_call = captured["p"].seen_messages[0]
    assert any(
        m["role"] == "user" and m["content"] == "Operator hint: check verify_token"
        for m in first_call
    )


# --- T8.1: notify (fail-closed) ---------------------------------------------------


def test_notify_publish_writes_html_and_posts_slack(tmp_path):
    poster = RecordingPoster()
    cfg = _config(tmp_path, slack_poster=poster)
    out = notify.publish(_diag(), incident_id="n-1", fabricated=False, config=cfg)
    assert Path(out["html_path"]).exists() and out["slack_posted"] is True
    assert len(poster.posts) == 1 and "n-1" in poster.posts[0][1]["text"]


def test_notify_publish_refuses_fabricated(tmp_path):
    cfg = _config(tmp_path, slack_poster=RecordingPoster())
    with pytest.raises(PublishRefused):
        notify.publish(_diag(), incident_id="n-2", fabricated=True, config=cfg)


def test_notify_skips_slack_when_no_webhook(tmp_path):
    cfg = _config(tmp_path)  # no slack_poster => slack_webhook_url empty
    out = notify.publish(_diag(), incident_id="n-3", fabricated=False, config=cfg)
    assert out["slack_posted"] is False and Path(out["html_path"]).exists()


# --- T8.2: review gate + operator auth --------------------------------------------


def test_operator_endpoints_require_auth(tmp_path):
    with TestClient(create_app(_config(tmp_path))) as client:
        assert client.get("/incidents/x").status_code == 401
        assert client.get("/incidents/x/status").status_code == 401
        assert (
            client.post("/incidents/x/review", json={"decision": "approve"}).status_code
            == 401
        )
        assert client.get("/incidents/x", headers=_op("wrong")).status_code == 401


def test_operator_surface_fail_closed_without_token(tmp_path):
    cfg = _config(tmp_path)
    cfg.operator_token = ""
    with TestClient(create_app(cfg)) as client:
        assert client.get("/incidents/x", headers=_op()).status_code == 503


def test_review_approve_posts_verified(tmp_path):
    poster = RecordingPoster()
    cfg = _config(tmp_path, verifier_supported=True, slack_poster=poster)
    with TestClient(create_app(cfg)) as client:
        assert _post(client, {"id": "r-1"}).status_code == 202
        assert _wait_status(client, "r-1", "pending_review") == "pending_review"
        r = _post_review(client, "r-1", {"decision": "approve", "reviewed_by": "alice"})
        assert r.status_code == 200 and r.json()["status"] == "posted"
        assert _status(client, "r-1").json()["status"] == "posted"
    assert len(poster.posts) == 1
    assert (Path(cfg.html_dir) / "r-1.html").exists()


def test_review_reject_posts_nothing(tmp_path):
    poster = RecordingPoster()
    cfg = _config(tmp_path, verifier_supported=True, slack_poster=poster)
    with TestClient(create_app(cfg)) as client:
        assert _post(client, {"id": "r-2"}).status_code == 202
        _wait_status(client, "r-2", "pending_review")
        assert (
            _post_review(client, "r-2", {"decision": "reject"}).json()["status"]
            == "rejected"
        )
    assert poster.posts == []


def test_review_approve_refuses_unverified(tmp_path):
    cfg = _config(tmp_path, slack_poster=RecordingPoster())  # no verifier => unverified
    with TestClient(create_app(cfg)) as client:
        assert _post(client, {"id": "r-3"}).status_code == 202
        _wait_status(client, "r-3", "pending_review")
        assert _post_review(client, "r-3", {"decision": "approve"}).status_code == 409


def test_review_steer_reruns_investigation(tmp_path):
    cfg = _config(tmp_path, verifier_supported=True)
    with TestClient(create_app(cfg)) as client:
        assert _post(client, {"id": "r-4"}).status_code == 202
        _wait_status(client, "r-4", "pending_review")
        r = _post_review(
            client, "r-4", {"decision": "steer", "steer_text": "check metrics"}
        )
        assert r.json()["status"] == "pending_review"
    conn = store.connect(cfg.db_path)
    try:
        assert len(dao.list_runs(conn, "r-4")) == 2  # a fresh steered run was added
    finally:
        conn.close()


def test_review_twice_is_conflict(tmp_path):
    cfg = _config(tmp_path, verifier_supported=True, slack_poster=RecordingPoster())
    with TestClient(create_app(cfg)) as client:
        assert _post(client, {"id": "r-5"}).status_code == 202
        _wait_status(client, "r-5", "pending_review")
        assert _post_review(client, "r-5", {"decision": "approve"}).status_code == 200
        assert _post_review(client, "r-5", {"decision": "approve"}).status_code == 409


def test_refused_approve_does_not_record_approval(tmp_path):
    # review re-review B: a fail-closed refusal must NOT persist review_decision='approve'.
    cfg = _config(tmp_path, slack_poster=RecordingPoster())  # no verifier -> unverified
    with TestClient(create_app(cfg)) as client:
        assert _post(client, {"id": "b-1"}).status_code == 202
        _wait_status(client, "b-1", "pending_review")
        assert (
            _post_review(
                client, "b-1", {"decision": "approve", "reviewed_by": "bob"}
            ).status_code
            == 409
        )
    conn = store.connect(cfg.db_path)
    try:
        (run,) = dao.list_runs(conn, "b-1")
        assert dao.get_diagnosis(conn, run.id)["review_decision"] is None
    finally:
        conn.close()


def test_steer_reports_failed_when_rerun_degrades(tmp_path, monkeypatch):
    # review re-review C: steer must report the ACTUAL resulting status, not a hard-coded
    # 'pending_review', when the re-run degrades to terminal 'failed'.
    cfg = _config(tmp_path, verifier_supported=True)
    with TestClient(create_app(cfg)) as client:
        assert _post(client, {"id": "c-1"}).status_code == 202
        _wait_status(client, "c-1", "pending_review")

        def _boom(*a, **k):
            raise RuntimeError("db down")

        monkeypatch.setattr("quellgeist.store.dao.record_run", _boom)
        r = _post_review(client, "c-1", {"decision": "steer", "steer_text": "x"})
        assert r.json()["status"] == "failed"


def test_get_incident_page_is_html(tmp_path):
    cfg = _config(tmp_path, verifier_supported=True)
    with TestClient(create_app(cfg)) as client:
        assert _post(client, {"id": "pg-1"}).status_code == 202
        _wait_status(client, "pg-1", "pending_review")
        r = client.get("/incidents/pg-1", headers=_op())
        assert r.status_code == 200
        assert "text/html" in r.headers["content-type"]
        assert "<h1>" in r.text


# --- webhook replay window --------------------------------------------------------


def _post_ts(client, body, ts, *, secret=SECRET):
    raw = json.dumps(body).encode()
    return client.post(
        "/incidents",
        content=raw,
        headers={
            "x-quellgeist-signature": sign(secret, raw, str(ts)),
            "x-quellgeist-timestamp": str(ts),
        },
    )


def test_replay_window_requires_fresh_signed_timestamp(tmp_path):
    cfg = _config(tmp_path, webhook_max_skew_s=300)
    with TestClient(create_app(cfg)) as client:
        now = int(time.time())
        assert _post_ts(client, {"id": "rp-1"}, now).status_code == 202
        assert (
            _post_ts(client, {"id": "rp-2"}, now - 10_000).status_code == 401
        )  # stale
        assert _post(client, {"id": "rp-3"}).status_code == 401  # missing timestamp


def test_replay_disabled_ignores_timestamp(tmp_path):
    with TestClient(create_app(_config(tmp_path))) as client:  # skew 0 (default)
        assert _post(client, {"id": "rp-4"}).status_code == 202
