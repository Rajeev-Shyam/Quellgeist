"""Apply a simulated fix deploy (the sandbox recovery step for Wave-9 resolution checks).

The counterpart to ``bad_deploy.py``: it clears the ``.bad_deploy`` marker (so
``auth.verify_token`` takes its healthy path again) and APPENDS a fix deploy entry to
``demo/deploy_log.json`` timestamped now. Unlike ``reset.py`` it does NOT truncate the
incident log — the prior errors stay on record, so re-hitting ``/login`` after this appends
fresh healthy lines and ``orchestrator.verify_resolution`` can observe the recovery
(cleared error signature + healthy post-fix traffic). Idempotent. Runs from the repo root.

Demo flow: bad_deploy -> hit /login (errors) -> quellgeist diagnose / service -> fix_deploy
-> hit /login (now healthy) -> verify_resolution -> `recovered`.
"""

from __future__ import annotations

import json
import os
from datetime import UTC, datetime
from pathlib import Path

_DEMO = Path(__file__).resolve().parents[1]  # .../demo
_FLAG = _DEMO / ".bad_deploy"
# Honor QG_DEPLOY_LOG so the fix deploy lands where the agent reads it (the shared volume
# under compose); defaults to the local demo file for the plain CLI demo.
_DEPLOY_LOG = Path(os.getenv("QG_DEPLOY_LOG", _DEMO / "deploy_log.json"))
_FMT = "%Y-%m-%dT%H:%M:%SZ"
_FIX_SHA = "f1c2d3e"


def main() -> None:
    healed = _FLAG.exists()
    _FLAG.unlink(missing_ok=True)  # auth.verify_token healthy again

    deploy_log: list[dict] = []
    if _DEPLOY_LOG.exists():
        try:
            loaded = json.loads(_DEPLOY_LOG.read_text())
            if isinstance(loaded, list):
                deploy_log = loaded
        except json.JSONDecodeError:
            deploy_log = []

    ts = datetime.now(UTC).strftime(_FMT)
    if not any(c.get("sha") == _FIX_SHA for c in deploy_log):
        deploy_log.append(
            {
                "sha": _FIX_SHA,
                "ts": ts,
                "msg": "fix: restore token None-guard in auth.verify_token",
                "files": ["demo/app/auth.py"],
            }
        )
    _DEPLOY_LOG.write_text(json.dumps(deploy_log, indent=2) + "\n")

    print(
        f"applied fix deploy {_FIX_SHA} (healed auth.verify_token) at {ts}"
        if healed
        else f"auth already healthy; recorded fix deploy {_FIX_SHA} at {ts}"
    )
    print(f"  deploy log: {_DEPLOY_LOG}")
    print("next: hit /login to generate healthy lines, then verify resolution")


if __name__ == "__main__":
    main()
