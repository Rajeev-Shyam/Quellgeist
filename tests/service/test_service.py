"""Service: signature, idempotency, snapshot isolation, full webhook→persist (T7.3).

Keyless: the provider is a scripted fake injected via ServiceConfig, so the worker runs
the real loop with no model.
"""

from __future__ import annotations

import json
import time

from fastapi.testclient import TestClient

from quellgeist import store
from quellgeist.service import ServiceConfig, create_app
from quellgeist.service.security import sign
from quellgeist.store import dao

SECRET = "test-secret-123"


class FakeProvider:
    def __init__(self, scripted):
        self.scripted = list(scripted)
        self.calls = []

    def complete(self, messages):
        return self.scripted.pop(0)


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


def _config(tmp_path, *, secret=SECRET):
    log_path, deploy_path = _sources(tmp_path)
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
    )


def _post(client, body: dict, *, secret=SECRET, sign_with=None):
    raw = json.dumps(body).encode()
    signature = sign(sign_with if sign_with is not None else secret, raw)
    return client.post(
        "/incidents", content=raw, headers={"x-quellgeist-signature": signature}
    )


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
        assert client.get("/incidents/nope").status_code == 404


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
            statuses = [client.get(f"/incidents/{i}").json()["status"] for i in ids]
            if all(s == "pending_review" for s in statuses):
                break
            time.sleep(0.05)
        assert all(
            client.get(f"/incidents/{i}").json()["status"] == "pending_review"
            for i in ids
        )
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
            body = client.get("/incidents/inc-9").json()
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
