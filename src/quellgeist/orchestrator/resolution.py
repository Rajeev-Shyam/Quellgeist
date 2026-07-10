"""Sandbox resolution-verification (Wave 9, T9.1; DR-0028; the Wave-6 content of DR-0023
decision 6).

After a controlled fix is applied to the **sandbox / demo** service, ``verify_resolution``
re-reads the operator's *current* live signals and decides whether the incident's error
signature has cleared, appending a ``ResolutionVerdict`` to the run's ``events``. It is:

- **Read-only, no production mutation** — it only *observes* the sandbox (DR-0001 boundary
  holds); it never applies or reverts a fix.
- **Deterministic and keyless** — no model call. The verdict is a set-membership comparison
  over the error signature, so it stays on the keyless gate (no ``QG_MODEL`` needed).
- **Snapshot-independent** — it reads the *current* live signal files, not the frozen
  incident snapshot, so it keeps working after the snapshot is reaped at ``posted`` /
  ``rejected`` (Wave 9 completes that reaping). The incident's error signature is recovered
  from the pre-fix window of those same current signals.

Verdict definition (log-signature driven; metric deltas recorded as corroborating detail):

- **recovered** — EVERY route that was erroring before the fix has post-fix traffic and no
  post-fix errors (the fix is confirmed by fresh healthy activity on all of them).
- **not_recovered** — at least one signature route is still erroring after the fix boundary.
- **inconclusive** — the error signature is not visible in the current signals (e.g. the log
  was reset/rotated), or at least one signature route is unconfirmed: it has no post-fix
  traffic to judge, or it is the unattributable routeless bucket (healthy routeless traffic
  can't be tied to the failed source). We report honestly rather than over-claim recovery.

The recovery boundary (``since``) defaults to the most recent deploy after the run started
(the presumed fix), else the run's end. An operator can override it explicitly.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from typing import TYPE_CHECKING

from quellgeist.ingest.sources import (
    read_deploy_source,
    read_log_source,
    read_metrics_source,
)
from quellgeist.store import connect, dao

if TYPE_CHECKING:  # avoid a runtime import cycle (service.app imports this via review)
    from quellgeist.service.config import ServiceConfig

RECOVERED = "recovered"
NOT_RECOVERED = "not_recovered"
INCONCLUSIVE = "inconclusive"

# Log levels that count as an error signal, alongside a 5xx status code.
_ERROR_LEVELS = {"ERROR", "ERR", "CRITICAL", "FATAL"}
_NO_ROUTE = "<unrouted>"


class ResolutionError(Exception):
    """A resolution check that cannot be applied (missing incident / no run). The
    ``status_code`` maps directly to the HTTP response, mirroring ``ReviewError``."""

    def __init__(self, message: str, status_code: int = 404) -> None:
        super().__init__(message)
        self.status_code = status_code


@dataclass
class ResolutionVerdict:
    verdict: str  # recovered | not_recovered | inconclusive
    reason: str
    run_id: str
    since: str | None  # the recovery-window boundary actually used
    error_routes: list[str]  # the incident's error signature (routes)
    residual_error_routes: list[str]  # signature routes STILL erroring post-fix
    recovered_routes: list[
        str
    ]  # signature routes with confirmed-healthy post-fix traffic
    unconfirmed_routes: list[
        str
    ]  # signature routes with no post-fix traffic to confirm
    metric_notes: list[str]  # corroborating metric deltas (informational)


def _is_error(row: dict) -> bool:
    level = row.get("level")
    if isinstance(level, str) and level.upper() in _ERROR_LEVELS:
        return True
    status = row.get("status")
    if isinstance(status, bool):  # bool is an int subclass; never a status code
        return False
    if isinstance(status, int) and status >= 500:
        return True
    if isinstance(status, str) and status.isdigit() and int(status) >= 500:
        return True
    return False


def _route(row: dict) -> str:
    r = row.get("route")
    return r if isinstance(r, str) and r else _NO_ROUTE


def _fix_boundary(commits: list[dict], started_ts: str, ended_ts: str | None) -> str:
    """The recovery-window boundary: the most recent deploy strictly after the run
    started (the presumed fix deploy), else the run's end, else its start. Lexicographic
    compare is valid for the canonical zero-padded UTC form the whole system uses."""
    later = [
        c.get("ts", "")
        for c in commits
        if isinstance(c.get("ts"), str) and c["ts"] > started_ts
    ]
    if later:
        return max(later)
    return ended_ts or started_ts


def _metric_notes(metrics: list[dict], since: str) -> list[str]:
    """Corroborating (non-authoritative) note: for any error-named metric series, compare
    the peak value before vs after the fix boundary. Recorded for the operator; it does not
    override the log-signature verdict (kept deterministic and simple)."""
    notes: list[str] = []
    for series in metrics:
        name = series.get("metric")
        if not isinstance(name, str) or "error" not in name.lower():
            continue
        pre = [
            p.get("value")
            for p in series.get("points", [])
            if isinstance(p.get("ts"), str) and p["ts"] < since
        ]
        post = [
            p.get("value")
            for p in series.get("points", [])
            if isinstance(p.get("ts"), str) and p["ts"] >= since
        ]
        pre_vals = [v for v in pre if isinstance(v, (int, float))]
        post_vals = [v for v in post if isinstance(v, (int, float))]
        if pre_vals and post_vals:
            pre_peak, post_peak = max(pre_vals), max(post_vals)
            trend = "down" if post_peak < pre_peak else "flat/up"
            notes.append(f"{name}: peak {pre_peak}->{post_peak} ({trend})")
    return notes


def _read_current_signals(
    config: ServiceConfig,
) -> tuple[list[dict], list[dict], list[dict]]:
    """Tolerantly read the operator's CURRENT live signal files (not the frozen incident
    snapshot). Reuses the ingest readers, so a messy real log never crashes the check.
    """
    return (
        read_log_source(config.log_path).rows,
        read_deploy_source(config.deploy_path).rows,
        read_metrics_source(config.metrics_path).rows,
    )


def verify_resolution(
    incident_id: str,
    *,
    config: ServiceConfig,
    run_id: str | None = None,
    current_signals: tuple[list[dict], list[dict], list[dict]] | None = None,
    since: str | None = None,
) -> ResolutionVerdict:
    """Re-read the current sandbox signals and decide whether ``incident_id`` recovered,
    persisting the verdict as a ``resolution`` event. ``run_id`` defaults to the incident's
    latest run. ``current_signals`` is a test seam (``(logs, commits, metrics)``); when
    omitted the live files at ``config.log_path`` / ``deploy_path`` / ``metrics_path`` are
    read. ``since`` overrides the auto-derived fix boundary."""
    conn = connect(config.db_path)
    try:
        incident = dao.get_incident(conn, incident_id)
        if incident is None:
            raise ResolutionError("unknown incident", 404)
        runs = dao.list_runs(conn, incident_id)
        if not runs:
            raise ResolutionError("no run to verify", 409)
        if run_id is None:
            run = runs[-1]
        else:
            run = next((r for r in runs if r.id == run_id), None)
            if run is None:
                raise ResolutionError("unknown run for this incident", 404)

        logs, commits, metrics = (
            current_signals
            if current_signals is not None
            else _read_current_signals(config)
        )
        boundary = since or _fix_boundary(commits, run.started_ts, run.ended_ts)

        pre = [r for r in logs if str(r.get("ts", "")) < boundary]
        post = [r for r in logs if str(r.get("ts", "")) >= boundary]
        error_routes = {_route(r) for r in pre if _is_error(r)}
        post_error_routes = {_route(r) for r in post if _is_error(r)}
        post_routes = {_route(r) for r in post}

        residual = sorted(error_routes & post_error_routes)  # still erroring post-fix
        # A signature route counts as recovered ONLY with confirming post-fix traffic and no
        # post-fix error. The routeless bucket (_NO_ROUTE) is never confirmable — healthy
        # routeless traffic can't be attributed to the same source that errored — so it can
        # only be `not_recovered` (if it still errors) or `inconclusive`, never `recovered`.
        recovered = sorted(
            r
            for r in error_routes
            if r != _NO_ROUTE and r in post_routes and r not in post_error_routes
        )
        # Anything neither still-erroring nor confirmed-recovered is UNCONFIRMED: a signature
        # route with no post-fix traffic to judge, or the unattributable routeless bucket.
        unconfirmed = sorted(error_routes - set(residual) - set(recovered))
        metric_notes = _metric_notes(metrics, boundary)

        if not error_routes:
            verdict, reason = (
                INCONCLUSIVE,
                "no pre-fix error signature is visible in the current signals "
                "(the incident errors may have been reset/rotated out); cannot judge "
                "recovery",
            )
        elif residual:
            verdict, reason = (
                NOT_RECOVERED,
                f"still erroring after the fix on: {', '.join(residual)}",
            )
        elif unconfirmed:
            # residual is empty, but not every signature route is confirmed healthy — do NOT
            # over-claim recovery (a multi-route incident where one route is silent, or a
            # routeless signature). Report honestly.
            verdict, reason = (
                INCONCLUSIVE,
                (f"recovered on {', '.join(recovered)}; " if recovered else "")
                + f"no post-fix traffic confirms recovery on: {', '.join(unconfirmed)}",
            )
        else:  # every signature route confirmed healthy, none still erroring
            verdict, reason = (
                RECOVERED,
                f"error signature cleared and post-fix traffic is healthy on: "
                f"{', '.join(recovered)}",
            )

        result = ResolutionVerdict(
            verdict=verdict,
            reason=reason,
            run_id=run.id,
            since=boundary,
            error_routes=sorted(error_routes),
            residual_error_routes=residual,
            recovered_routes=recovered,
            unconfirmed_routes=unconfirmed,
            metric_notes=metric_notes,
        )
        dao.append_event(
            conn,
            incident_id,
            "resolution",
            run_id=run.id,
            detail_json=json.dumps(asdict(result)),
        )
        return result
    finally:
        conn.close()
