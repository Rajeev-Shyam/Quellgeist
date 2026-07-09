"""Normalisation primitives: real-world fields -> the canonical tool schema.

Every function here is pure and total (never raises on plausible real input): the
whole point of ingestion is to *not* fall over on messy data. Two invariants make
this safe to run on the CLI's real-file path without disturbing the frozen demo /
eval behaviour:

- **Value-preserving on canonical input.** An already-canonical log row / commit /
  metric series comes back with identical values (``normalize_ts`` on a canonical
  ``…Z`` string returns it unchanged; a row that already has an int ``id`` keeps
  it). A test asserts the committed demo/fixture rows round-trip unchanged.
- **Source-stable ids (DR-0009).** ``normalize_log_rows`` assigns an int ``id`` in
  ingest order only when a row lacks a usable int id, so the handle a ``LogRef``
  cites is stable across queries.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

_CANONICAL_TS = "%Y-%m-%dT%H:%M:%SZ"

# Field aliases seen in the wild (ELK / Loki / CloudWatch / structlog / plain JSON).
# First match wins; canonical key on the left.
_LOG_ALIASES: dict[str, tuple[str, ...]] = {
    "ts": ("ts", "timestamp", "time", "@timestamp", "datetime", "date", "eventtime"),
    "level": ("level", "severity", "levelname", "lvl", "log_level", "loglevel"),
    "route": ("route", "path", "url", "uri", "endpoint", "request_path", "target"),
    "status": ("status", "status_code", "statuscode", "http_status", "code"),
    "msg": ("msg", "message", "log", "event", "text", "body", "detail", "error"),
}

_COMMIT_ALIASES: dict[str, tuple[str, ...]] = {
    "sha": ("sha", "commit", "commit_sha", "hash", "id", "revision"),
    "ts": ("ts", "timestamp", "date", "committed_date", "authoreddate", "time"),
    "msg": ("msg", "message", "subject", "title", "summary"),
    "files": ("files", "changed_files", "modified", "paths", "changes"),
}

_LEVEL_SYNONYMS: dict[str, str] = {
    "err": "ERROR",
    "error": "ERROR",
    "fatal": "ERROR",
    "crit": "ERROR",
    "critical": "ERROR",
    "emerg": "ERROR",
    "alert": "ERROR",
    "warn": "WARNING",
    "warning": "WARNING",
    "notice": "INFO",
    "info": "INFO",
    "information": "INFO",
    "debug": "DEBUG",
    "trace": "DEBUG",
}


def normalize_ts(value: Any) -> str:
    """Coerce a timestamp into the canonical zero-padded ``%Y-%m-%dT%H:%M:%SZ`` UTC
    form the tool filters compare lexicographically. Accepts the canonical form
    (returned unchanged), ISO-8601 with a ``Z`` or numeric offset, fractional
    seconds, a space-separated ``YYYY-MM-DD HH:MM:SS`` (assumed UTC), and epoch
    seconds/milliseconds (int/float or numeric string). Anything unparseable is
    returned stripped-but-unchanged rather than raising -- a best-effort handle
    that simply won't time-filter well is better than a crashed ingest."""
    if value is None:
        return ""
    # epoch numbers (seconds or milliseconds)
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return _from_epoch(float(value))

    s = str(value).strip()
    if not s:
        return ""

    # fast path: already canonical
    try:
        if datetime.strptime(s, _CANONICAL_TS).strftime(_CANONICAL_TS) == s:
            return s
    except ValueError:
        pass

    # ISO-8601 (fromisoformat handles offsets + fractional seconds; normalise a
    # trailing Z, which older Pythons reject, to +00:00 first).
    iso = s[:-1] + "+00:00" if s.endswith(("Z", "z")) else s
    try:
        dt = datetime.fromisoformat(iso)
        dt = dt.astimezone(UTC) if dt.tzinfo else dt.replace(tzinfo=UTC)
        return dt.strftime(_CANONICAL_TS)
    except ValueError:
        pass

    # a bare numeric string -> epoch
    try:
        return _from_epoch(float(s))
    except ValueError:
        return s  # give up, but never crash


def _from_epoch(num: float) -> str:
    # Heuristic: values past ~year 2001 in *seconds* are < 1e10; anything much
    # larger is milliseconds (a common JSON-logger convention).
    if abs(num) >= 1e11:
        num /= 1000.0
    return datetime.fromtimestamp(num, tz=UTC).strftime(_CANONICAL_TS)


def normalize_level(value: Any) -> str:
    """Uppercase a log level and fold common synonyms onto INFO/WARNING/ERROR/DEBUG
    (the vocabulary the fixtures and prompt use). Unknown levels are uppercased
    as-is rather than dropped."""
    if value is None:
        return "INFO"
    s = str(value).strip()
    if not s:
        return "INFO"
    return _LEVEL_SYNONYMS.get(s.lower(), s.upper())


def _pick(row: dict[str, Any], keys: tuple[str, ...]) -> tuple[str, Any] | None:
    """First alias present in ``row`` (case-insensitively), as ``(actual_key, value)``."""
    lowered = {k.lower(): k for k in row}
    for want in keys:
        actual = lowered.get(want)
        if actual is not None:
            return actual, row[actual]
    return None


def _coerce_status(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def normalize_log_rows(
    raw: list[dict[str, Any]], *, start_id: int = 0
) -> list[dict[str, Any]]:
    """Map arbitrary log dicts onto the canonical ``{id, ts, level, route, status,
    msg}`` shape. ``id`` is preserved when the row already carries a usable int id;
    otherwise a source-stable monotonic id is assigned in ingest order starting at
    ``start_id`` (so multi-file ingestion stays unique). ``route`` and ``status``
    are included only when present (non-HTTP logs have neither)."""
    out: list[dict[str, Any]] = []
    next_id = start_id
    for raw_row in raw:
        row: dict[str, Any] = {}

        existing = raw_row.get("id")
        if isinstance(existing, int) and not isinstance(existing, bool):
            row["id"] = existing
        else:
            row["id"] = next_id
            next_id += 1

        ts = _pick(raw_row, _LOG_ALIASES["ts"])
        row["ts"] = normalize_ts(ts[1]) if ts else ""

        level = _pick(raw_row, _LOG_ALIASES["level"])
        row["level"] = normalize_level(level[1] if level else None)

        route = _pick(raw_row, _LOG_ALIASES["route"])
        if route and route[1] is not None:
            row["route"] = str(route[1])

        status = _pick(raw_row, _LOG_ALIASES["status"])
        if status:
            coerced = _coerce_status(status[1])
            if coerced is not None:
                row["status"] = coerced

        msg = _pick(raw_row, _LOG_ALIASES["msg"])
        row["msg"] = "" if msg is None else str(msg[1] if msg else "")

        out.append(row)
        # keep assigned ids ahead of any explicit id we passed through
        if row["id"] >= next_id:
            next_id = row["id"] + 1
    return out


def normalize_commits(raw: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Map arbitrary deploy/commit dicts onto ``{sha, ts, msg, files}``. Rows with
    no resolvable ``sha`` are dropped (a commit handle must resolve to something)."""
    out: list[dict[str, Any]] = []
    for raw_row in raw:
        sha = _pick(raw_row, _COMMIT_ALIASES["sha"])
        if not sha or sha[1] in (None, ""):
            continue
        ts = _pick(raw_row, _COMMIT_ALIASES["ts"])
        msg = _pick(raw_row, _COMMIT_ALIASES["msg"])
        files = _pick(raw_row, _COMMIT_ALIASES["files"])
        files_val = files[1] if files else []
        if isinstance(files_val, str):
            files_val = [files_val]
        out.append(
            {
                "sha": str(sha[1]),
                "ts": normalize_ts(ts[1]) if ts else "",
                "msg": "" if msg is None else str(msg[1] if msg else ""),
                "files": (
                    list(files_val) if isinstance(files_val, (list, tuple)) else []
                ),
            }
        )
    return out


def normalize_metric_series(raw: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Normalise metric series onto ``{metric, unit, points:[{ts, value}]}`` with
    canonical point timestamps. The ``metric`` NAME is the cited handle (DR-0009),
    so it passes through verbatim; series without a name are dropped."""
    out: list[dict[str, Any]] = []
    for series in raw:
        name = series.get("metric")
        if name in (None, ""):
            continue
        points: list[dict[str, Any]] = []
        for p in series.get("points", []) or []:
            if not isinstance(p, dict):
                continue
            points.append(
                {"ts": normalize_ts(p.get("ts", "")), "value": p.get("value")}
            )
        out.append(
            {"metric": str(name), "unit": str(series.get("unit", "")), "points": points}
        )
    return out
