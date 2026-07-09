"""Real-data ingestion (v1.1, DR-0022).

Quellgeist's three read-only tools speak one canonical schema each (a log row is
``{id, ts, level, route, status, msg}``; a deploy is ``{sha, ts, msg, files}``; a
metric series is ``{metric, unit, points:[{ts, value}]}``). Real operators do not
have data in that shape -- they have JSON logs from Loki/CloudWatch/ELK with
different field names, a ``git log``, and a Prometheus range query. This package is
the **adapter layer** that turns those real sources into the canonical schema,
tolerantly (a malformed line is skipped, never fatal) and with source-stable ids
assigned in ingest order (the DR-0009 citation contract).

It is additive and does not touch the frozen measurement path (the eval harness
serves in-memory fixtures through ``servers.filters`` directly): normalising an
already-canonical row is a value-preserving no-op, guarded by a test.
"""

from __future__ import annotations

from quellgeist.ingest.normalize import (
    normalize_commits,
    normalize_level,
    normalize_log_rows,
    normalize_metric_series,
    normalize_ts,
)
from quellgeist.ingest.sources import (
    read_deploy_source,
    read_log_source,
    read_metrics_source,
)

__all__ = [
    "normalize_commits",
    "normalize_level",
    "normalize_log_rows",
    "normalize_metric_series",
    "normalize_ts",
    "read_deploy_source",
    "read_log_source",
    "read_metrics_source",
]
