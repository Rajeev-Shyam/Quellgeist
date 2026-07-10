"""The Wave-9 demo fix script heals auth and records a fix deploy WITHOUT truncating the
incident log (so post-fix traffic remains observable for resolution verification).

Monkeypatches the module's paths to a tmp dir so the real ``demo/`` is never touched.
"""

from __future__ import annotations

import json

from demo.chaos import fix_deploy


def test_fix_deploy_heals_and_records_without_truncating(tmp_path, monkeypatch):
    flag = tmp_path / ".bad_deploy"
    deploy_log = tmp_path / "deploy_log.json"
    incident_log = tmp_path / "incident_logs.jsonl"
    flag.touch()
    deploy_log.write_text(
        json.dumps([{"sha": "a1b2c3d", "ts": "2026-07-09T09:59:00Z", "msg": "bad"}])
    )
    original_log = '{"id": 0, "level": "ERROR"}\n'  # prior evidence
    incident_log.write_text(original_log)
    # Point QG_LOG_PATH at our incident log so that IF fix_deploy ever touched it (a
    # regression toward reset.py's truncation) this test would catch it.
    monkeypatch.setenv("QG_LOG_PATH", str(incident_log))
    monkeypatch.setattr(fix_deploy, "_FLAG", flag)
    monkeypatch.setattr(fix_deploy, "_DEPLOY_LOG", deploy_log)

    fix_deploy.main()

    assert not flag.exists()  # auth healed
    deploys = json.loads(deploy_log.read_text())
    assert any(c["sha"] == fix_deploy._FIX_SHA for c in deploys)  # fix recorded
    assert any(c["sha"] == "a1b2c3d" for c in deploys)  # prior deploy preserved
    # byte-for-byte unchanged — fix_deploy must NOT truncate/rotate the log (unlike reset.py)
    assert incident_log.read_text() == original_log


def test_fix_deploy_is_idempotent(tmp_path, monkeypatch):
    flag = tmp_path / ".bad_deploy"
    deploy_log = tmp_path / "deploy_log.json"
    monkeypatch.setattr(fix_deploy, "_FLAG", flag)
    monkeypatch.setattr(fix_deploy, "_DEPLOY_LOG", deploy_log)

    fix_deploy.main()
    fix_deploy.main()  # second run must not duplicate the fix entry

    deploys = json.loads(deploy_log.read_text())
    assert sum(c["sha"] == fix_deploy._FIX_SHA for c in deploys) == 1
