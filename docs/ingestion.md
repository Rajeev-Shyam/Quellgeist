# Using Quellgeist on your real data

Quellgeist triages a **point-in-time snapshot** of an incident from three read-only
signals — structured logs, recent deploys, and metric time-series. Out of the box
the tools read three canonical files; this guide shows how to get *your* real data
into them with `quellgeist ingest`, and how the reliability guarantee is enforced
at real-use time. (Background: [DR-0022](quellgeist-adr-log.md).)

> Quellgeist is not a live-monitoring agent. You capture a snapshot around the
> incident window, ingest it, and diagnose — a deliberate design choice
> ([architecture](architecture.md)).

## The one-liner

```bash
# 1. normalise your real sources into the three canonical files
quellgeist ingest \
  --logs    /var/log/myapp/            # a file or a whole directory
  --deploys deploys.json               # a JSON array, GitHub payload, or `git log` text
  --metrics prom.json                  # a Prometheus response or a canonical array
  --out-dir ./signals

# 2. point the tools at them and diagnose (add --model / a provider key)
export QG_LOG_PATH=./signals/incident_logs.jsonl
export QG_DEPLOY_LOG=./signals/deploy_log.json
export QG_METRICS_PATH=./signals/metrics.json
quellgeist diagnose --show-trace --strict-citations
```

`ingest` prints those `export` lines for you. You can ingest only the sources you
have — `--logs` alone is fine.

## What `ingest` accepts

### Logs (`--logs PATH`)
A single file **or a directory** of files. Each file may be:
- **JSONL** — one JSON object per line (the most common shipper format).
- **A JSON array** of objects (a common export shape).
- **Plain text** — each line is kept as `msg`, with a best-effort leading timestamp
  and embedded level (`ERROR`/`WARN`/…) lifted out.
- **A mix** of the above, including the odd malformed line — bad lines are coerced
  or skipped and counted, **never fatal**.

Field names are mapped from what real shippers emit onto the canonical schema
(first match wins, case-insensitive):

| canonical | accepted aliases |
|---|---|
| `ts` | `ts`, `timestamp`, `time`, `@timestamp`, `datetime`, `date`, `eventTime` |
| `level` | `level`, `severity`, `levelname`, `lvl`, `log_level`, `loglevel` |
| `route` | `route`, `path`, `url`, `uri`, `endpoint`, `request_path`, `target` |
| `status` | `status`, `status_code`, `statusCode`, `http_status`, `code` |
| `msg` | `msg`, `message`, `log`, `event`, `text`, `body`, `detail`, `error` |

Timestamps are coerced to canonical UTC (`YYYY-MM-DDTHH:MM:SSZ`) from ISO-8601 with
`Z`/offsets, fractional seconds, a space-separated form, or epoch seconds/ms. A
**source-stable integer `id`** (what a `LogRef` cites — [DR-0009](quellgeist-adr-log.md))
is preserved when present, else assigned in ingest order; a directory reassigns ids
across the merged, time-sorted stream so per-file ids can't collide.

### Deploys (`--deploys PATH`)
- A **JSON array** of `{sha, ts, msg, files}` (aliases like `commit`/`hash`,
  `message`/`subject`, `changed_files` are accepted).
- A **GitHub commits payload** (`[{sha, commit:{message, author:{date}}, files:[…]}]`).
- **`git log` text** in this exact format:
  ```bash
  git log --no-color --pretty=format:'%H%x1f%cI%x1f%s' --name-only -n 50 > deploys.txt
  quellgeist ingest --deploys deploys.txt --out-dir ./signals
  ```

### Metrics (`--metrics PATH`)
- A **Prometheus** range or instant query response (`{"data":{"result":[…]}}`); the
  series name is `__name__` (or a stable label join). Grab a window around the incident:
  ```bash
  curl -s 'http://prom:9090/api/v1/query_range?query=process_resident_memory_bytes&start=…&end=…&step=15s' > prom.json
  ```
- An already-canonical JSON array of `{metric, unit, points:[{ts, value}]}`.

The `metric` name is the cited handle, so it always passes through verbatim.

## Robustness knobs

Real production logs are large. `query_logs` returns at most the most-recent
`QG_MAX_ROWS` rows per call (default **200**) so one observation can't blow the
model's context window — narrow with `--since`/`level`/`route`, or raise the cap:

```bash
export QG_MAX_ROWS=500     # rows per query_logs observation (0 = uncapped)
export QG_MAX_POINTS=1000  # points per metric series (0 = uncapped)
```

The **full, uncapped** signal set is still used for the citation check below, so the
cap never causes a false fabrication flag.

## The reliability guarantee, at real-use time

Quellgeist's headline property — *every claim cites a real evidence handle, or it
abstains* — is enforced when you run it on your data, not just in the eval harness.
After a live diagnosis the CLI checks every cited `LogRef.id` / `CommitRef.sha` /
`MetricRef.id` against your real signals:

- clean → nothing printed (or `citations=ok` under `--show-trace`);
- a cited handle absent from your signals → a `warning:` on stderr, and with
  `--strict-citations` a **non-zero exit (3)** so CI can gate on it;
- no signals loaded (misconfiguration / empty files) → `citations=unverified`, never
  a false alarm.

This is the same deterministic, keyless check the eval suite uses
([`quellgeist.agent.citations`](../src/quellgeist/agent/citations.py)).

## Reasoner

`ingest` and `diagnose --demo` need no model. A live `diagnose` needs a reasoner —
a hosted model (`--model gemini/… ` + a provider key) or a local one
(`--model ollama_chat/…`); see the README's *Running the model*.

## Known limits

- Whole files are read into memory; a streaming reader for multi-GB logs is a
  deferred follow-up (the token-blowup — the fatal failure — is already handled by
  the observation cap).
- Point-in-time snapshots only; live tailing is out of scope by design.
- Plain-text log parsing is best-effort — structured JSON logs give the sharpest
  citations.
