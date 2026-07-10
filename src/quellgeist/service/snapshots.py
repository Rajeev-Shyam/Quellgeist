"""Per-incident signal snapshots (Wave 7, T7.3; DR-0023 concurrency isolation).

On accept, the ingress copies the operator's current signal files into a per-incident
directory. That frozen snapshot is what the worker's incident-scoped tools read, so a
signal file that keeps changing (or a second concurrent incident) can never alter this
run's evidence. Canonical filenames match the tool factory's expectations.

Written **atomically** (build in a temp dir, then ``os.replace`` into place): the
ingress only snapshots after it has *won* the idempotency INSERT, and the atomic rename
means a partially-copied dir is never visible to a worker (review: torn-snapshot race).
"""

from __future__ import annotations

import os
import shutil
import uuid
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
) -> tuple[Path, int]:
    """Atomically materialise ``dest_dir`` with whichever of the three source signal
    files exist, under the canonical names. Returns ``(dest, copied_count)`` so the
    caller can flag a degraded (zero-source) snapshot."""
    dest = Path(dest_dir)
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.parent / f".{dest.name}.tmp-{uuid.uuid4().hex[:8]}"
    tmp.mkdir(parents=True, exist_ok=True)
    copied = 0
    try:
        for src, name in (
            (log_path, SNAPSHOT_LOG),
            (deploy_path, SNAPSHOT_DEPLOY),
            (metrics_path, SNAPSHOT_METRICS),
        ):
            if src and Path(src).exists():
                shutil.copyfile(src, tmp / name)
                copied += 1
        os.replace(tmp, dest)  # atomic rename into place (same filesystem)
    except BaseException:
        shutil.rmtree(tmp, ignore_errors=True)
        raise
    return dest, copied


def discard_snapshot(dest_dir: str | Path) -> None:
    """Remove a per-incident snapshot dir once it is no longer needed. Called for
    TERMINAL incidents: a 'failed' run (worker) and — since Wave 9 — 'posted'/'rejected'
    (the review gate), closing the disk-growth limit carried out of Wave 8. A
    'pending_review' incident KEEPS its snapshot — the review gate / steer re-run reads
    it — so the dir is not reaped until the incident actually closes. Resolution
    verification reads LIVE signals, not the snapshot, so reaping at 'posted' is safe.
    Best-effort: a cleanup failure must never crash the caller."""
    shutil.rmtree(Path(dest_dir), ignore_errors=True)
