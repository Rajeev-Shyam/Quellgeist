-- Quellgeist v2 store — initial schema (Wave 7, T7.1; DR-0023 decision 2).
-- Forward-only. The DDL mirrors docs/quellgeist-v2-spec.md §Components verbatim.

CREATE TABLE incidents (
  id            TEXT PRIMARY KEY,          -- idempotency key (webhook delivery/incident id)
  source        TEXT NOT NULL,             -- 'webhook' | 'cli' | 'poll'
  received_ts   TEXT NOT NULL,             -- canonical UTC
  signals_ref   TEXT NOT NULL,             -- path to the isolated snapshot dir
  status        TEXT NOT NULL,             -- queued|running|pending_review|posted|rejected|failed
  hint          TEXT
);

CREATE TABLE runs (
  id            TEXT PRIMARY KEY,
  incident_id   TEXT NOT NULL REFERENCES incidents(id),
  model         TEXT NOT NULL,
  started_ts    TEXT NOT NULL,
  ended_ts      TEXT,
  steps         INTEGER,
  outcome       TEXT NOT NULL,             -- diagnosed | abstained | failed
  abstained     INTEGER NOT NULL DEFAULT 0,
  fabricated    TEXT,                      -- '' clean | JSON list of fabricated handles | NULL unverified
  prompt_tokens INTEGER,
  completion_tokens INTEGER,
  latency_s     REAL,                      -- summed CallUsage
  trace_json    TEXT                       -- full LoopResult transcript (messages/tool_calls/violations)
);

CREATE TABLE diagnoses (
  run_id          TEXT PRIMARY KEY REFERENCES runs(id),
  summary         TEXT,
  diagnosis_json  TEXT NOT NULL,
  verified_json   TEXT,                    -- post-verifier diagnosis (may force abstention)
  reviewed_by     TEXT,
  review_decision TEXT,
  steer_text      TEXT
);

CREATE TABLE evidence (
  run_id      TEXT NOT NULL REFERENCES runs(id),
  hyp_index   INTEGER NOT NULL,
  handle_type TEXT NOT NULL,
  handle_id   TEXT NOT NULL,
  PRIMARY KEY (run_id, hyp_index, handle_type, handle_id)
);

CREATE TABLE events (                      -- append-only audit log
  id          INTEGER PRIMARY KEY AUTOINCREMENT,
  incident_id TEXT NOT NULL,
  run_id      TEXT,
  ts          TEXT NOT NULL,
  kind        TEXT NOT NULL,
  detail_json TEXT
);

CREATE INDEX idx_runs_incident ON runs(incident_id);
CREATE INDEX idx_events_incident ON events(incident_id);
