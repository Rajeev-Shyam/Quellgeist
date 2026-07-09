"""Per-incident signal snapshots (Wave 7, T7.3; DR-0023 concurrency isolation).

On accept, the ingress copies the operator's current signal files into a per-incident
directory. That frozen snapshot is what the worker's incident-scoped tools read, so a
signal file that keeps changing (or a second concurrent incident) can never alter this
run's evidence. Canonical filenames match the tool factory's expectations.
"""

from __future__ import annotations

import shutil
from pathlib import Path

from quellgeist.orchestrator.tools_factory import (
    SNAPSHOT_DEPLOY,
    SNAPSHOT_LOG,
    SNAPSHOT_METRICS,
)


def snapshot_signals(
    dest_dir: str | Path,
    *,
    log_path: str | None,
    deploy_path: str | None,
    metrics_path: str | None,
) -> Path:
    """Copy whichever of the three source signal files exist into ``dest_dir`` under
    the canonical names. Returns the snapshot directory (created if needed)."""
    dest = Path(dest_dir)
    dest.mkdir(parents=True, exist_ok=True)
    for src, name in (
        (log_path, SNAPSHOT_LOG),
        (deploy_path, SNAPSHOT_DEPLOY),
        (metrics_path, SNAPSHOT_METRICS),
    ):
        if src and Path(src).exists():
            shutil.copyfile(src, dest / name)
    return dest
