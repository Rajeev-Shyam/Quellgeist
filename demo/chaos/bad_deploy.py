"""Inject a simulated bad deploy.

Drops demo/.bad_deploy (flips auth.verify_token to its buggy path) and writes
demo/deploy_log.json with the offending deploy timestamped ~30s ago — just before
the /login 500s you'll generate next. Idempotent. Runs from the repo root.
"""

from __future__ import annotations

import json
import os
from datetime import UTC, datetime, timedelta
from pathlib import Path

_DEMO = Path(__file__).resolve().parents[1]  # .../demo
_FLAG = _DEMO / ".bad_deploy"
# Honor QG_DEPLOY_LOG so the deploy signal lands where the agent reads it (the shared
# volume under compose); defaults to the local demo file for the plain CLI demo.
_DEPLOY_LOG = Path(os.getenv("QG_DEPLOY_LOG", _DEMO / "deploy_log.json"))
_FMT = "%Y-%m-%dT%H:%M:%SZ"


def _iso(dt: datetime) -> str:
    return dt.strftime(_FMT)


def main() -> None:
    now = datetime.now(UTC)
    deploy_log = [
        {
            "sha": "9f8e7d6",
            "ts": _iso(now - timedelta(days=1)),
            "msg": "docs: update README",
            "files": ["README.md"],
        },
        {
            "sha": "a1b2c3d",
            "ts": _iso(now - timedelta(seconds=30)),
            "msg": "deploy: refactor token parsing",
            "files": ["demo/app/auth.py"],
        },
    ]
    _DEPLOY_LOG.write_text(json.dumps(deploy_log, indent=2) + "\n")
    _FLAG.touch()
    print(
        f"injected bad deploy a1b2c3d (touched demo/app/auth.py) at {deploy_log[-1]['ts']}"
    )
    print(f"  marker:     {_FLAG}")
    print(f"  deploy log: {_DEPLOY_LOG}")
    print("next: hit /login to generate the 500s, then `quellgeist diagnose`")


if __name__ == "__main__":
    main()
