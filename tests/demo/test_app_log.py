"""Tests for the demo app's incident-log lifecycle (Wave 1, Task 2).

Importing demo.app.main must NOT truncate an existing incident log; only the
app's lifespan startup does. The assertions run in a subprocess so the demo's
module-level globals (structlog config, the Prometheus registry, the append
file handle) never leak into the pytest process.
"""

from __future__ import annotations

import os
import subprocess
import sys
import textwrap
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]


def test_import_preserves_log_but_startup_truncates(tmp_path):
    log = tmp_path / "incident_logs.jsonl"
    content = '{"id": 0, "msg": "pre-existing"}\n'
    log.write_text(content, encoding="utf-8")

    script = textwrap.dedent(f"""
        import asyncio
        import os
        os.environ["QG_LOG_PATH"] = {str(log)!r}

        import demo.app.main as main
        # Importing the module alone must leave the existing log untouched.
        assert open({str(log)!r}, encoding="utf-8").read() == {content!r}, "import truncated the log"

        # Entering the lifespan (app startup) is what resets the log.
        async def _startup():
            async with main.lifespan(main.app):
                pass

        asyncio.run(_startup())
        assert open({str(log)!r}, encoding="utf-8").read() == "", "startup did not truncate the log"
        print("OK")
        """)
    proc = subprocess.run(
        [sys.executable, "-c", script],
        cwd=REPO_ROOT,
        env={**os.environ, "PYTHONPATH": str(REPO_ROOT)},
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 0, proc.stderr
    assert proc.stdout.strip().endswith("OK")
