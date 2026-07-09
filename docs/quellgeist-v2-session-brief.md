# Quellgeist v2 — Session Brief (read this first, before touching anything)

> **You are a fresh Claude instance picking up Quellgeist v2.** This is a
> Claude-to-Claude continuation doc, not human docs. Its job is to let you execute
> Wave 7+ **without drift, gaps, or hallucination**. Read it top to bottom before
> proposing or writing anything. The two companion docs are the authority for
> *why* ([DR-0023](quellgeist-adr-log.md)) and *what*
> ([`quellgeist-v2-spec.md`](quellgeist-v2-spec.md)); this is *how*.

---

## 0. Grounding facts (verify, don't assume)

- **Repo:** `github.com/Rajeev-Shyam/Quellgeist`. Latest commit at scoping time:
  `0af7090` ("feat(ingest): real-data ingestion + real-file robustness (DR-0022)"),
  dated 2026-07-09, confirmed = `origin/main` = `origin/HEAD`, 0 commits behind.
  **First action:** `git fetch && git log --oneline -3` and confirm you're at or ahead of
  `0af7090`; if the repo moved, re-read the changed files before trusting this brief.
- **Build/run:** `uv sync`; `uv run pytest tests/ -q`; `uv run pre-commit run --all-files`.
  Python 3.12+. The deterministic gate is **keyless** — keep it that way.
- **Test count:** **247 collected test cases from 215 `def test_` functions** — verified
  2026-07-09 via `uv run pytest tests/ --collect-only -q` (the delta is parametrised
  expansion). "247 tests" is accurate; quote it as *collected cases*, not function count.
- **Owner's working preferences (apply to every reply):** conclusion first; bullets over prose;
  no emoji; casual, dry humour fine; one concrete next step at the end; chunk long info and
  check in; single recommendation before alternatives; AuDHD-friendly (don't dump walls or long
  question-lists). Treat him as a competent peer — no hand-holding on fundamentals.

---

## 1. THE DO-NOT-TOUCH LIST (this is the whole point of this brief)

Editing any of these silently invalidates the fine-tune's **0/16 → 12/16** headline. If a task
seems to need one of these changed, **stop and flag it** — the answer is almost always "wrap it
in a new module," not "edit it."

| # | Frozen | Exact location | Why untouchable |
|---|---|---|---|
| F1 | Tool description strings | `src/quellgeist/servers/tools.py` → `QUERY_LOGS_DESC`, `GET_RECENT_COMMITS_DESC`, `QUERY_METRICS_DESC` | byte-identical to the DR-0020 train/serve prompt |
| F2 | Evidence + diagnosis schema & field order | `src/quellgeist/agent/schema.py` | the tuned model emits this exact JSON |
| F3 | Committed corpora | `evals/scenarios/fixtures/`, `evals/scenarios/holdout/` | the measured train/holdout split |
| F4 | Observation + retry string format | `src/quellgeist/agent/loop.py` (`f"Observation from {action}: {json.dumps(rows)}"`, `_retry_msg`) | byte-identical to training turns |
| F5 | Shared filters | `src/quellgeist/servers/filters.py` | on the frozen eval path |
| F6 | `run_loop` decision logic | `src/quellgeist/agent/loop.py` | the measured artifact; wrap, never edit |

**All v2 code goes in NEW modules:** `src/quellgeist/service/`, `.../orchestrator/`, `.../store/`,
`.../observability/`, `.../notify/`; and **new eval dirs** for the structure-varied / out-of-
structure corpora + the timing-aware verifier variant. Reuse frozen modules by **calling** them.

**Prove you didn't drift** (run before every merge):
```bash
uv run pytest tests/ -q                       # all green, including the eval-path tests
uv run python - <<'PY'                          # frozen tool strings byte-check
from quellgeist.servers.tools import QUERY_LOGS_DESC, GET_RECENT_COMMITS_DESC, QUERY_METRICS_DESC
import hashlib
print(hashlib.sha256((QUERY_LOGS_DESC+GET_RECENT_COMMITS_DESC+QUERY_METRICS_DESC).encode()).hexdigest())
PY
# golden committed in tests/frozen/test_frozen_surface.py:
#   f4277d8f10d296c6ffcaf760905db67d96749a29d4719f9b65df1c28c08232e8
git diff --stat origin/main -- src/quellgeist/servers/tools.py src/quellgeist/agent/schema.py \
  src/quellgeist/agent/loop.py src/quellgeist/servers/filters.py evals/scenarios
# ^ this diff MUST be empty for the frozen paths.
```

The frozen-surface regression test (`tests/frozen/test_frozen_surface.py`, added in this
setup session) already asserts F1 (the golden hash above), F2 (schema field order), and F4
(`_retry_msg` + the observation format) — run the suite and it fails loudly on any drift.

---

## 2. The decided v2 scope (do NOT re-litigate — decided via a 30-Q MCQ, 2026-07-09)

| Area | Decision | Source |
|---|---|---|
| Direction | Two additive tracks: **live service** (primary) + **generalisation/reliability** | Q1 mix |
| Audience | Portfolio **and** point at real infra | Q2 |
| Trigger | **Signed inbound webhook** | Q4 |
| Output | **Slack + self-contained HTML page** | Q5 |
| Persistence | **SQLite (WAL)** — default from no-pref | Q6 |
| Concurrency | **Must handle concurrent** incidents (workers + isolated snapshots) | Q7 |
| Packaging | **Ship a Dockerfile** | Q8 |
| Abstention ceiling | **Timing-aware verifier** (culprit-after-errors) | Q9 |
| Model | **Stay on Qwen3-4B** (no 8B) | Q12 |
| New evidence type | **None in v2**; if ever, **verifier-only, no retrain** | Q13/Q14 |
| Self-observability | **v2 requirement** (correlation ids, structlog, persisted runs+cost) | Q15 |
| Dashboard | **No** live dashboard (offline matrix suffices) | Q16 |
| Demo | **3-min end-to-end screen-share is the goal** | Q17 |
| Interview framing | Pre-empt **observability / ops** | Q18 |
| Wave 6 | **In scope** (sandbox resolution-verification, no prod mutation) | Q3 |
| Launch | **v2 in parallel; launch v1+v2 together** | Q20 |
| Repo | **Public** (raises secret-hygiene bar); **Wave 7+ in this repo** | Q21/Q24 |
| MCP-client wire path | **Nice-to-have / deferred** | Q25 |
| HITL | **In scope** (hint injection + review gate; wrapper, not the frozen loop) | Q27 |
| Generalisation | **Go after it** (structure-varied + public-postmortem holdout) | Q28/Q29 |
| Compute | **Same as Wave 4** (RTX 5060 8GB / free Colab); **GPU budget available** | Q23/Q11 |

**Judgment calls made on "No preference" answers — treat as defaults, confirm before building:**
SQLite (not Postgres); async only in the service layer with the sync core wrapped in a threadpool;
keep Quellgeist distinct from Aperture; develop on a `v2` branch merged for a combined launch;
`resource_exhaustion` trajectory-mix is **optional** (verifier abstention is interim safety).

---

## 3. Working agreements (guardrails against the failure modes)

1. **Design before building.** This repo runs on the brainstorming → spec → plan → build flow.
   The spec exists; when you start a wave, invoke the **writing-plans** skill for that wave, get a
   go, then build. Do **not** jump to implementation skills before the wave's plan is agreed.
2. **Adversarial review before durable outputs.** Poke holes in each wave's plan/code before you
   commit — the owner explicitly values this.
3. **Rolling waves.** Only detail the current wave. Open its DR (DR-0024…DR-0027) at kickoff; run
   the boundary-review checklist at its close (`docs/quellgeist-plan-rolling-wave.md`).
4. **Never reopen training inside a ship wave.** Track B training (DR-0026) is its own decision;
   do not entangle it with the service waves.
5. **Keep the deterministic gate green and keyless.** Model-driven evals stay out-of-band.
6. **Fail-closed in the service.** Unlike the CLI (warn-by-default), the autonomous poster must
   **not** post a fabricated diagnosis — surface it for review.
7. **Secrets are env-only.** Public repo. Add `.env.example`; never commit a key or Slack token.
8. **Ground every claim in the repo.** If you're about to assert a number/behaviour, open the file.

---

## 4. Ordered task plan

Each task: **goal · files (all NEW unless noted) · acceptance · tests**. Waves map to the spec.

### Wave 7 — Service spine + persistence + observability
- **T7.1 `store`** — SQLite WAL, the 5-table schema (spec §Data model), DAO, `migrations/`.
  *Acceptance:* create/read incident+run round-trips; WAL on; migration applies clean.
  *Tests:* DAO unit + a migration test.
- **T7.2 `observability`** — `contextvars` run-id/incident-id binding, structlog JSON config for
  the agent process, `summarize_usage(provider)` reading the existing `CallUsage` list (no edit to
  `providers.py`). *Acceptance:* a run emits correlation-tagged JSON logs and a persisted cost sum.
- **T7.3 `service` (ingress)** — async FastAPI: `POST /incidents` (HMAC-signed, idempotent),
  `GET /healthz`; on accept, **snapshot** the incident's signals to a per-incident dir and enqueue.
  *Acceptance:* signed POST → 202 + id; bad signature → 401; duplicate delivery → no-op.
  *Tests:* signature verify, idempotency, snapshot isolation.
- **T7.4 worker pool + `orchestrator.investigate`** — bounded workers run the **frozen** `run_loop`
  in a thread executor over the isolated snapshot; run the fabrication check; persist the run.
  *Acceptance:* concurrency test (N incidents, no cross-read); each run persisted with trace+cost.
- **T7.5 Frozen-surface regression test** — golden hash of F1 strings + F4 format; assert the eval
  path (`evals.run_evals.scenario_tools`) still imports/runs. *Acceptance:* fails if any frozen
  artifact changes. **(Landed early in the setup session — see `tests/frozen/`.)**
- **Boundary review + open DR-0027 (HITL) next.**

### Wave 8 — Output + HITL
- **T8.1 `notify`** — Slack emitter (idempotent per incident) + HTML via
  `output/postmortem.render_postmortem_html` (reused). *Acceptance:* approved diagnosis posts to
  both, once. **Fail-closed:** a fabricated diagnosis is not posted.
- **T8.2 Review gate** — `pending_review → approved|steered|rejected → posted`; HTML page
  (`GET /incidents/{id}`) + `POST .../review`; `steer` re-runs `investigate` with the steer as a
  hint. *Acceptance:* each transition audited in `events`; reject posts nothing.
- **T8.3 Hint-at-trigger** — webhook `hint` stored + passed to `investigate`. Between-steps hint is
  a **stretch**; if it would touch F4 strings, ship trigger-time only. *Acceptance:* a hint changes
  the run's operator context **without** editing frozen strings.
- **Boundary review.**

### Wave 9 — Resolution-verification (Wave-6 content) + packaging
- **T9.1 `orchestrator.verify_resolution`** — after a sandbox fix (new demo "fix"/reset), re-read
  signals, assert error-signature-gone / metrics-recovered, append a verdict. **No prod mutation.**
  *Acceptance:* recovered/not-recovered/inconclusive verdict persisted.
- **T9.2 Dockerfile + `compose.yml`** — non-root service image; compose wires demo + agent + Ollama
  + shared volume. *Acceptance:* `docker build` + `compose up` runs the **3-min end-to-end demo**.
- **T9.3 SECURITY.md additions** — webhook auth/replay, Slack egress scope, operator endpoints.
- **Boundary review.** After Wave 9, the live-service track is launch-ready alongside v1.

### Wave 10 — Track B (reliability/generalisation, parallel)
- **T10.1 Timing-aware verifier** (DR-0024) — new variant flags culprit-commit-after-first-error;
  pinned separately; original path intact. *Acceptance:* new abstention probes pass; frozen holdout
  still reported.
- **T10.2 Structure-varied corpus + public-postmortem out-of-structure holdout** (DR-0025) — NEW
  dirs only; curated-with-attribution, never verbatim. *Acceptance:* the out-of-structure holdout is
  provably disjoint from the frozen holdout; any new fine-tune reports **both** numbers.
- **T10.3 (optional) `resource_exhaustion` mix** (DR-0026) — only if pursued; model stays 4B.

---

## 5. First concrete next step

Confirm the five "No preference" defaults in §2 (SQLite, sync-core-in-threadpool, distinct-from-
Aperture, `v2` branch, optional resource_exhaustion), then invoke **writing-plans** for **Wave 7
only** and produce T7.1–T7.5 as a detailed plan. Do not start Wave 8+ planning until Wave 7 is
agreed. Keep the frozen-surface diff empty at every step.

---

## 6. Known gaps & drifts in v1 (context, so you don't re-discover them)

Grounded in a full read of `0af7090`:

1. **Stateless / single-incident / synchronous CLI** — the core v2 motivation. (architecture)
2. **No live trigger** — CLI-only invocation. (gap)
3. **Self-observability absent in the agent** — `structlog` only in `demo/` + `ingest/normalize.py`;
   the loop/providers emit no structured run telemetry; `CallUsage` is in-memory on the provider,
   never persisted/correlated. (gap → Wave 7)
4. **No deployment artifact** — only `uv run`; no Dockerfile. (gap → Wave 9)
5. **MCP framing vs runtime** — tools are *published* as MCP servers but the agent reuses their
   *functions* in-process; the stdio MCP-*client* path is roadmap-only (DR-0010). Name this
   honestly; it's deferred (Q25), not fixed in v2. (framing drift)
6. **`resource_exhaustion` 0/N transfer** — the tuned model can't diagnose the class, only abstain.
   (documented reliability gap → optional Track B)
7. **Adversarial-abstention 6/12** — shared ceiling with the 31B frontier; intrinsic model abstention
   collapsed to 0/12 (verifier load-bearing). (→ timing-aware verifier)
8. **Holdout is out-of-vocabulary but IN-structure** — both corpora share one skeleton; a positional
   script passes the judge 81/81 (DR-0020 decision 1). The biggest honesty caveat. (→ Track B)
9. **`--strict-citations` is warn-by-default** — a fabricated citation still renders unless `--strict`.
   The service must be **fail-closed** by default (spec §Error handling).
10. **`QG_MAX_ROWS` keeps the most-recent tail** — on a very large real log, culprit evidence older
    than the tail could become unresolvable. Documented tradeoff (DR-0022); note for real-data runs.
11. **Doc-precision:** "247 tests" = 247 collected cases from 215 `def test_` functions — resolved
    (§0); safe to quote.
12. **Claim-precision:** the "$0 offline" headline must keep the offline column's **verifier local**
    (the matrix runner already pins it to the base local artifact) — say so.

New drift risks v2 itself introduces (mitigations in the spec): per-incident **signal isolation**;
webhook **idempotency**; **secret hygiene** on a public repo; keeping the new out-of-structure corpus
**disjoint** from the frozen holdout.
