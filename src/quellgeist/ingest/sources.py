"""Read real-world sources into canonical rows, tolerantly.

Each ``read_*`` returns canonical rows (via ``normalize``) and NEVER raises on a
malformed line: a bad line is coerced or skipped and counted, and the count is
returned so the caller (the CLI / the tool layer) can warn the operator. This is
the load-bearing "don't fall over on real data" property probed in the review: a
single non-JSON line in a real log used to crash the whole tool call.

Supported log inputs: a JSONL file (one object per line), a JSON array file, a
directory of either, or plain text (each line coerced to a ``msg`` with a
best-effort leading timestamp + level). Supported deploy inputs: a JSON array
(incl. a GitHub-style commits payload) or ``git log`` text in the documented
format. Supported metric inputs: a Prometheus range/instant query response or an
already-canonical JSON array.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from quellgeist.ingest.normalize import (
    normalize_commits,
    normalize_log_rows,
    normalize_metric_series,
)

# A leading timestamp (ISO-8601 or "YYYY-MM-DD HH:MM:SS…") at the start of a line.
_LEADING_TS = re.compile(r"^\[?(\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}:\d{2}[^\s\]]*)\]?")
_LEVEL_TOKEN = re.compile(
    r"\b(CRITICAL|FATAL|ERROR|ERR|WARNING|WARN|NOTICE|INFO|DEBUG|TRACE)\b", re.I
)
# git-log unit/record separators used by the documented pretty-format.
_US = "\x1f"


@dataclass
class ReadResult:
    """Canonical rows plus how many raw lines had to be skipped/coerced, so the
    caller can surface a one-line warning instead of failing silently."""

    rows: list[dict[str, Any]] = field(default_factory=list)
    skipped: int = 0
    coerced: int = 0
    files: int = 0


def _coerce_text_line(line: str) -> dict[str, Any]:
    """Best-effort structure for a non-JSON log line: keep the whole line as
    ``msg``, lift a leading timestamp and any embedded level token."""
    raw: dict[str, Any] = {"msg": line}
    m = _LEADING_TS.match(line)
    if m:
        raw["ts"] = m.group(1)
    lvl = _LEVEL_TOKEN.search(line)
    if lvl:
        raw["level"] = lvl.group(1)
    return raw


def _read_raw_log_file(path: Path, result: ReadResult) -> list[dict[str, Any]]:
    """Return raw (un-normalised) row dicts from one file, tolerantly."""
    text = path.read_text(encoding="utf-8", errors="replace")
    stripped = text.lstrip()

    # Whole-file JSON array of objects (a common export shape).
    if stripped.startswith("["):
        try:
            data = json.loads(text)
            if isinstance(data, list):
                raw: list[dict[str, Any]] = []
                for item in data:
                    if isinstance(item, dict):
                        raw.append(item)
                    else:
                        result.skipped += 1
                return raw
        except json.JSONDecodeError:
            pass  # fall through to line-based

    # Line-based: JSONL, or plain text, or a mix.
    raw = []
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        if line.startswith("{"):
            try:
                obj = json.loads(line)
                if isinstance(obj, dict):
                    raw.append(obj)
                    continue
            except json.JSONDecodeError:
                pass
        # not a JSON object -> coerce the text line rather than dropping it
        raw.append(_coerce_text_line(line))
        result.coerced += 1
    return raw


def read_log_source(path: str | Path) -> ReadResult:
    """Read a log file or a directory of log files into canonical log rows.

    A single file preserves any int ``id`` it already carries (so a canonical
    demo/exported log is unchanged). A directory merges its files in name order
    and assigns fresh source-stable ids across the whole stream (per-file ids
    would collide), sorting the merged rows by timestamp so ``since`` works."""
    p = Path(path)
    result = ReadResult()
    if not p.exists():
        return result

    if p.is_dir():
        files = sorted(f for f in p.iterdir() if f.is_file())
        raw: list[dict[str, Any]] = []
        for f in files:
            result.files += 1
            for row in _read_raw_log_file(f, result):
                row.pop("id", None)  # force fresh, non-colliding ids across files
                raw.append(row)
        rows = normalize_log_rows(raw)
        rows.sort(key=lambda r: r.get("ts", ""))
        # reassign ids in final (time) order so ids increase with time
        for i, r in enumerate(rows):
            r["id"] = i
        result.rows = rows
        return result

    result.files = 1
    result.rows = normalize_log_rows(_read_raw_log_file(p, result))
    return result


def from_git_log_text(text: str) -> list[dict[str, Any]]:
    """Parse ``git log`` output in the documented format:

        git log --no-color --pretty=format:%H%x1f%cI%x1f%s --name-only

    Each commit is a ``sha<US>iso-date<US>subject`` header line followed by its
    changed files (one per line) until a blank line. Unrecognised lines are
    ignored, so a slightly different invocation degrades rather than crashes."""
    commits: list[dict[str, Any]] = []
    current: dict[str, Any] | None = None
    for line in text.splitlines():
        if _US in line:
            parts = line.split(_US)
            if len(parts) >= 3:
                current = {
                    "sha": parts[0].strip(),
                    "ts": parts[1].strip(),
                    "msg": parts[2].strip(),
                    "files": [],
                }
                commits.append(current)
                continue
        stripped = line.strip()
        if not stripped:
            current = None
        elif current is not None:
            current["files"].append(stripped)
    return commits


def read_deploy_source(path: str | Path) -> ReadResult:
    """Read a deploy/commit source: a JSON array (or GitHub-style payload) or
    ``git log`` text. Returns canonical ``{sha, ts, msg, files}`` rows."""
    p = Path(path)
    result = ReadResult()
    if not p.exists():
        return result
    result.files = 1
    text = p.read_text(encoding="utf-8", errors="replace")
    stripped = text.lstrip()

    raw: list[dict[str, Any]]
    if stripped.startswith(("[", "{")):
        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            data = None
        if isinstance(data, dict):
            # GitHub commits API nests fields under "commit"; flatten shallowly.
            data = data.get("commits") or data.get("data") or [data]
        raw = _flatten_commit_dicts(data) if isinstance(data, list) else []
    else:
        raw = from_git_log_text(text)

    result.rows = normalize_commits(raw)
    return result


def _flatten_commit_dicts(items: list[Any]) -> list[dict[str, Any]]:
    """Accept both flat commit dicts and GitHub's nested ``{sha, commit:{message,
    author:{date}}}`` shape."""
    out: list[dict[str, Any]] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        inner = item.get("commit")
        if isinstance(inner, dict):
            author = inner.get("author") or inner.get("committer") or {}
            out.append(
                {
                    "sha": item.get("sha") or item.get("id") or "",
                    "ts": inner.get("date")
                    or (author.get("date") if isinstance(author, dict) else ""),
                    "msg": inner.get("message", ""),
                    "files": [
                        f.get("filename")
                        for f in item.get("files", [])
                        if isinstance(f, dict)
                    ],
                }
            )
        else:
            out.append(item)
    return out


def read_metrics_source(path: str | Path) -> ReadResult:
    """Read a metrics source: a Prometheus range/instant query response, an
    already-canonical JSON array of series, or a single series dict."""
    p = Path(path)
    result = ReadResult()
    if not p.exists():
        return result
    result.files = 1
    try:
        data = json.loads(p.read_text(encoding="utf-8", errors="replace"))
    except json.JSONDecodeError:
        return result

    if isinstance(data, dict) and "data" in data and isinstance(data["data"], dict):
        result.rows = normalize_metric_series(_from_prometheus(data["data"]))
    elif isinstance(data, dict):
        result.rows = normalize_metric_series([data])
    elif isinstance(data, list):
        result.rows = normalize_metric_series(data)
    return result


def _from_prometheus(data: dict[str, Any]) -> list[dict[str, Any]]:
    """Convert a Prometheus ``data`` block (``resultType`` matrix/vector) to
    canonical series. The series NAME is ``__name__`` when present, else a
    stable join of its label set."""
    series: list[dict[str, Any]] = []
    for res in data.get("result", []):
        if not isinstance(res, dict):
            continue
        labels = res.get("metric", {}) or {}
        name = labels.get("__name__")
        if not name:
            others = {k: v for k, v in labels.items() if k != "__name__"}
            name = (
                "{" + ",".join(f"{k}={v}" for k, v in sorted(others.items())) + "}"
                if others
                else "series"
            )
        points: list[dict[str, Any]] = []
        pairs = res.get("values") or ([res["value"]] if "value" in res else [])
        for pair in pairs:
            if isinstance(pair, (list, tuple)) and len(pair) == 2:
                ts, value = pair
                try:
                    value = float(value)
                except (TypeError, ValueError):
                    pass
                points.append({"ts": ts, "value": value})
        series.append({"metric": name, "unit": "", "points": points})
    return series
