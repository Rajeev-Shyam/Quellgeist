"""Revert the simulated bad deploy and restore a green slate.

Removes the .bad_deploy marker (auth.verify_token healthy again), deletes
deploy_log.json, and truncates the incident log so the next diagnose sees a clean
signal. The running app's id counter is NOT reset — post-reset lines continue
monotonically (harmless). Restart uvicorn if you want ids from 0.
"""

from __future__ import annotations

import os
from pathlib import Path

_DEMO = Path(__file__).resolve().parents[1]
_FLAG = _DEMO / ".bad_deploy"
_DEPLOY_LOG = _DEMO / "deploy_log.json"
_INCIDENT_LOG = Path(os.getenv("QG_LOG_PATH", _DEMO / "incident_logs.jsonl"))


def main() -> None:
    _FLAG.unlink(missing_ok=True)
    _DEPLOY_LOG.unlink(missing_ok=True)
    if _INCIDENT_LOG.exists():
        _INCIDENT_LOG.write_text("")  # truncate; app's O_APPEND handle stays valid
    print(
        "reset: marker cleared, deploy_log.json removed, incident log truncated — green"
    )


if __name__ == "__main__":
    main()
