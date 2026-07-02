"""Scenario schema + loader + parameterised generation.

A Scenario bundles an injected failure's canned signals (logs, commits, and --
for resource incidents -- metric series) with the gold root cause and the gold
evidence handles a correct diagnosis must cite. Wave 1 shipped one hand-authored
fixture; Wave 3 turns generation into templates -> variants across failure
classes.

Two EVAL splits are generated from **disjoint parameter banks** (routes,
modules, config keys, metric names, error signatures, commit-message
templates): ``fixtures`` (the eval corpus) and ``holdout`` (reserved). Drawing
the holdout from a DIFFERENT distribution than the fixtures is the whole point
-- eval numbers then measure skill, not memorisation (DR-0003 / DR-0004
held-out constraint). Two TRAINING-side splits (``train`` and ``probe``,
DR-0020) deliberately reuse the fixtures bank verbatim under fresh seeds and
their own id namespaces: training stays on the fixtures distribution while the
committed eval items themselves are never trained on.

Three failure classes are generated: ``bad_deploy`` and ``config_error`` (logs +
commits) and ``resource_exhaustion`` (adds a metric series that climbs to a
ceiling). Every resource scenario still has a culprit commit, so the deterministic
judge's commit-citation check (DR-0017) is unchanged; the distinctive metric is a
required gold handle, which forces the agent to actually read metrics.
"""

from __future__ import annotations

import random
from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from quellgeist.agent.schema import EvidenceRef

_TS_FMT = "%Y-%m-%dT%H:%M:%SZ"
_HEX = "0123456789abcdef"
# A fixed anchor -- generation must NOT read the wall clock, or the corpus would
# change every run and never reconcile with the committed fixtures.
_EPOCH = datetime(2026, 5, 1, 8, 0, 0)


class Scenario(BaseModel):
    id: str
    failure_class: str
    now: str
    logs: list[dict[str, Any]] = Field(default_factory=list)
    commits: list[dict[str, Any]] = Field(default_factory=list)
    # Metric series (resource_exhaustion only; empty for the log+commit classes).
    metrics: list[dict[str, Any]] = Field(default_factory=list)
    gold_cause: str
    gold_evidence: list[str] = Field(
        default_factory=list
    )  # legacy free-text; unused by harness
    gold_evidence_refs: list[EvidenceRef] = Field(default_factory=list)


def load_scenario(path: str | Path) -> Scenario:
    return Scenario.model_validate_json(Path(path).read_text(encoding="utf-8"))


# --------------------------------------------------------------------------- #
# Parameterised generation (Wave 3)
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class _Bank:
    """A split's generative vocabulary. Two banks (fixtures / holdout) share NO
    tokens, so the two splits are drawn from disjoint distributions (DR-0003)."""

    seed: int
    # "fixtures" -> bad_deploy_0002 ; "holdout" -> hold_bad_deploy_01 ; any other
    # value doubles as the id-namespace prefix (DR-0020: "train"/"probe" ->
    # train_bad_deploy_0001 / probe_bad_deploy_0001).
    id_style: str
    counts: tuple[tuple[str, int], ...]  # (failure_class, n) in generation order
    routes: tuple[str, ...]
    modules: tuple[str, ...]  # dotted code paths, e.g. "auth.verify_token"
    config_files: tuple[str, ...]
    config_keys: tuple[str, ...]
    deploy_msgs: tuple[str, ...]  # culprit commit msg templates -- {mod}
    config_msgs: tuple[str, ...]  # culprit commit msg templates -- {key}
    decoy_msgs: tuple[str, ...]  # innocent commit messages
    code_errors: tuple[str, ...]  # bad_deploy error signatures -- {module}
    config_errors: tuple[str, ...]  # config_error signatures -- {key}
    resource_metrics: tuple[str, ...]  # resource metric-series names (the handle id)
    resource_msgs: tuple[str, ...]  # resource culprit commit messages
    resource_errors: tuple[str, ...]  # resource downstream error signatures


_FIXTURES_BANK = _Bank(
    seed=20260701,
    id_style="fixtures",
    # bad_deploy starts at id 0002 -- 0001 is the hand-authored anchor fixture.
    counts=(("bad_deploy", 24), ("config_error", 25), ("resource_exhaustion", 15)),
    routes=("/login", "/data", "/checkout", "/profile", "/orders"),
    modules=(
        "auth.verify_token",
        "billing.charge",
        "cart.total",
        "session.load",
        "orders.place",
    ),
    config_files=("config/settings.py", "app/config.yaml", ".env"),
    config_keys=(
        "DATABASE_URL",
        "REDIS_HOST",
        "STRIPE_KEY",
        "SESSION_TTL",
        "MAX_CONNECTIONS",
    ),
    deploy_msgs=(
        "deploy: refactor {mod} token parsing",
        "deploy: optimise {mod} hot path",
        "deploy: rewrite {mod} handler",
    ),
    config_msgs=(
        "config: rotate {key}",
        "chore: update {key} for prod",
        "config: change {key} default",
    ),
    decoy_msgs=(
        "docs: update README",
        "test: add coverage for utils",
        "chore: bump linter",
        "style: reformat imports",
    ),
    code_errors=(
        "TypeError: 'NoneType' object is not subscriptable in {module}",
        "AttributeError: 'NoneType' object has no attribute 'get' in {module}",
        "KeyError: 'user' in {module}",
    ),
    config_errors=(
        "KeyError: '{key}' not set",
        "missing required env var {key}",
        "ValueError: invalid literal for int() for {key}",
    ),
    resource_metrics=(
        "db_connections_in_use",
        "memory_rss_bytes",
        "worker_queue_depth",
        "open_file_descriptors",
        "thread_pool_active",
    ),
    resource_msgs=(
        "perf: reuse connections without closing them",
        "config: cut the connection pool in half",
        "deploy: preload the full dataset into memory",
    ),
    resource_errors=(
        "TimeoutError: could not acquire a connection",
        "OperationalError: too many connections open",
        "MemoryError: allocation failed",
    ),
)

_HOLDOUT_BANK = _Bank(
    seed=20260702,
    id_style="holdout",
    counts=(("bad_deploy", 6), ("config_error", 6), ("resource_exhaustion", 4)),
    # Every token below is disjoint from _FIXTURES_BANK: a different distribution.
    routes=("/search", "/upload", "/billing", "/notify", "/report"),
    modules=(
        "cache.fetch",
        "queue.enqueue",
        "report.render",
        "search.index",
        "upload.store",
    ),
    config_files=("settings/prod.py", "conf/app.toml", "env/production.env"),
    config_keys=(
        "CACHE_TTL",
        "QUEUE_URL",
        "SMTP_HOST",
        "PAGE_SIZE",
        "WORKER_COUNT",
    ),
    deploy_msgs=(
        "deploy: migrate {mod} backend",
        "deploy: inline {mod} cache",
        "deploy: split {mod} module",
    ),
    config_msgs=(
        "config: retune {key}",
        "chore: adjust {key} for scale",
        "config: swap {key} provider",
    ),
    decoy_msgs=(
        "docs: fix changelog",
        "test: quiet a flaky case",
        "ci: cache dependencies",
        "refactor: rename helpers",
    ),
    code_errors=(
        "TypeError: 'NoneType' object is not iterable in {module}",
        "IndexError: list index out of range in {module}",
        "RecursionError: maximum recursion depth exceeded in {module}",
    ),
    config_errors=(
        "KeyError: '{key}' missing from config",
        "environment variable {key} is undefined",
        "TypeError: int() argument must be a string for {key}",
    ),
    resource_metrics=(
        "cache_entries_resident",
        "socket_conns_active",
        "heap_used_bytes",
        "pending_jobs_backlog",
        "gc_pause_seconds",
    ),
    resource_msgs=(
        "refactor: keep sockets open across requests",
        "config: shrink the worker budget",
        "deploy: buffer the whole response in RAM",
    ),
    resource_errors=(
        "ResourceWarning: connection pool exhausted",
        "BlockingIOError: no worker slots free",
        "OSError: cannot allocate memory",
    ),
)

# DR-0020: the fine-tune train split and the probe pool reuse the fixtures
# VOCABULARY verbatim (training stays on the fixtures distribution; the holdout
# bank is never sampled) but draw FRESH scenarios under their own seeds and id
# namespaces -- never the committed eval items. config_error is weighted up in
# the train split: it has 3x the semantic-core entropy of the other classes.
_TRAIN_BANK = replace(
    _FIXTURES_BANK,
    seed=20260703,
    id_style="train",
    counts=(("bad_deploy", 96), ("config_error", 128), ("resource_exhaustion", 72)),
)

# Source pool for the two DR-0020 probe sets (abstention recall; structure
# perturbation). The pool itself is never an artifact -- evals/training ablates
# or perturbs these scenarios and commits only the derived probe files.
_PROBE_BANK = replace(
    _FIXTURES_BANK,
    seed=20260704,
    id_style="probe",
    counts=(("bad_deploy", 8), ("config_error", 8), ("resource_exhaustion", 6)),
)

_BANKS: dict[str, _Bank] = {
    "fixtures": _FIXTURES_BANK,
    "holdout": _HOLDOUT_BANK,
    "train": _TRAIN_BANK,
    "probe": _PROBE_BANK,
}


def bank_vocabulary(split: str) -> dict[str, tuple[str, ...]]:
    """A split's generative vocabulary, by named group. The DR-0020
    contamination scan needs the GROUPS (not the flat union) because several
    bank entries are unrendered templates (``{key}``/``{mod}``/``{module}``)
    that must be format-expanded before they can be matched against rendered
    training text."""
    b = _bank(split)
    return {
        "routes": b.routes,
        "modules": b.modules,
        "config_files": b.config_files,
        "config_keys": b.config_keys,
        "deploy_msgs": b.deploy_msgs,
        "config_msgs": b.config_msgs,
        "decoy_msgs": b.decoy_msgs,
        "code_errors": b.code_errors,
        "config_errors": b.config_errors,
        "resource_metrics": b.resource_metrics,
        "resource_msgs": b.resource_msgs,
        "resource_errors": b.resource_errors,
    }


def distribution_tokens(split: str) -> set[str]:
    """The generative vocabulary of a split -- the union of its bank's token
    groups (derived from ``bank_vocabulary`` so the two views can never
    enumerate different group lists). Used to assert the fixtures and holdout
    splits are drawn from DISJOINT distributions (DR-0003)."""
    return set().union(*bank_vocabulary(split).values())


def _bank(split: str) -> _Bank:
    try:
        return _BANKS[split]
    except KeyError:
        raise ValueError(
            f"unknown split {split!r}; expected one of {sorted(_BANKS)}"
        ) from None


def _fmt(dt: datetime) -> str:
    return dt.strftime(_TS_FMT)


def _sha(rng: random.Random, exclude: frozenset[str] = frozenset()) -> str:
    """A deterministic 7-hex-char pseudo-sha unique within a scenario."""
    while True:
        s = "".join(rng.choice(_HEX) for _ in range(7))
        if s not in exclude:
            return s


def _resource_metric(
    rng: random.Random, name: str, t_deploy: datetime, t_first_err: datetime
) -> dict[str, Any]:
    """A metric series that sits at a baseline, then climbs to a ceiling from the
    culprit deploy onward -- the tell a resource-exhaustion diagnosis must cite."""
    baseline = rng.randrange(3, 12)
    ceiling = rng.choice((64, 100, 128, 200, 256))
    points: list[dict[str, Any]] = []
    for k in range(3):  # baseline before the deploy
        ts = t_deploy - timedelta(minutes=(3 - k) * 2)
        points.append({"ts": _fmt(ts), "value": baseline + rng.randrange(0, 3)})
    for k in range(1, 5):  # climb toward the ceiling after the deploy
        ts = t_deploy + timedelta(seconds=k * 20)
        points.append(
            {"ts": _fmt(ts), "value": round(baseline + (ceiling - baseline) * k / 4)}
        )
    points.append({"ts": _fmt(t_first_err), "value": ceiling})  # pinned at the ceiling
    return {"metric": name, "unit": "count", "points": points}


def _make_scenario(
    *, sid: str, failure_class: str, bank: _Bank, rng: random.Random, index: int
) -> Scenario:
    """Build one internally-consistent scenario: an INFO baseline, an ERROR burst
    on a route beginning shortly after a culprit deploy, plus a decoy commit and a
    little cross-route noise. For ``resource_exhaustion`` a metric series climbing
    to a ceiling is added and cited as the gold evidence (with the commit). The
    gold refs always resolve to real signals, so a gold diagnosis passes the judge
    with zero fabrication (verified in tests)."""
    base = _EPOCH + timedelta(days=index, minutes=rng.randrange(0, 300))
    route = rng.choice(bank.routes)
    noise_route = rng.choice([r for r in bank.routes if r != route])
    culprit_sha = _sha(rng)
    decoy_sha = _sha(rng, exclude=frozenset({culprit_sha}))
    gap = rng.choice((15, 20, 30, 45))
    n_errors = rng.choice((2, 3, 4))
    n_baseline = rng.choice((2, 3))

    t_deploy = base + timedelta(minutes=rng.randrange(1, 5))
    t_decoy = base - timedelta(days=1, minutes=rng.randrange(0, 600))
    t_first_err = t_deploy + timedelta(seconds=gap)

    metric_name = None
    metric_series = None
    if failure_class == "bad_deploy":
        module = rng.choice(bank.modules)
        mod_file = f"demo/app/{module.split('.')[0]}.py"
        culprit_msg = rng.choice(bank.deploy_msgs).format(mod=module.split(".")[0])
        err_sig = rng.choice(bank.code_errors).format(module=module)
        culprit_files = [mod_file]
        gold_cause = (
            f"Bad deploy {culprit_sha} ({_fmt(t_deploy)[11:]}) touched {mod_file} "
            f"and introduced an error in {module}; {route} 500s begin ~{gap}s "
            f"later at {_fmt(t_first_err)[11:]}."
        )
    elif failure_class == "config_error":
        cfg = rng.choice(bank.config_files)
        key = rng.choice(bank.config_keys)
        culprit_msg = rng.choice(bank.config_msgs).format(key=key)
        err_sig = rng.choice(bank.config_errors).format(key=key)
        culprit_files = [cfg]
        gold_cause = (
            f"Config change {culprit_sha} ({_fmt(t_deploy)[11:]}) edited {cfg} "
            f"({key}) and broke {route}; errors begin ~{gap}s later at "
            f"{_fmt(t_first_err)[11:]}."
        )
    elif failure_class == "resource_exhaustion":
        metric_name = rng.choice(bank.resource_metrics)
        metric_series = _resource_metric(rng, metric_name, t_deploy, t_first_err)
        culprit_msg = rng.choice(bank.resource_msgs)
        err_sig = rng.choice(bank.resource_errors)
        culprit_files = [f"demo/app/{metric_name.split('_')[0]}.py"]
        gold_cause = (
            f"Resource exhaustion: deploy {culprit_sha} ({_fmt(t_deploy)[11:]}) "
            f"-- {culprit_msg} -- drove {metric_name} to its ceiling; {route} "
            f"errors begin ~{gap}s later at {_fmt(t_first_err)[11:]}."
        )
    else:  # pragma: no cover - guarded by the caller's fixed class list
        raise ValueError(f"unsupported failure_class {failure_class!r}")

    rows: list[tuple[datetime, str, str, int, str]] = []
    for k in range(n_baseline):
        ts = t_deploy - timedelta(minutes=(n_baseline - k) * 2)
        rows.append((ts, "INFO", route, 200, f"{route} ok"))
    for k in range(n_errors):
        rows.append(
            (t_first_err + timedelta(seconds=k * gap), "ERROR", route, 500, err_sig)
        )
    rows.append(
        (
            t_first_err + timedelta(seconds=5),
            "INFO",
            noise_route,
            200,
            f"{noise_route} ok",
        )
    )
    rows.sort(key=lambda r: r[0])

    logs = [
        {
            "id": i,
            "ts": _fmt(ts),
            "level": level,
            "route": rt,
            "status": status,
            "msg": msg,
        }
        for i, (ts, level, rt, status, msg) in enumerate(rows)
    ]
    first_error_id = next(row["id"] for row in logs if row["level"] == "ERROR")

    commits = [
        {
            "sha": decoy_sha,
            "ts": _fmt(t_decoy),
            "msg": rng.choice(bank.decoy_msgs),
            "files": ["README.md"],
        },
        {
            "sha": culprit_sha,
            "ts": _fmt(t_deploy),
            "msg": culprit_msg,
            "files": culprit_files,
        },
    ]

    now = _fmt(rows[-1][0] + timedelta(minutes=rng.randrange(2, 9)))

    if failure_class == "resource_exhaustion":
        metrics = [metric_series]
        gold_refs: list[dict[str, Any]] = [
            {"type": "metric", "id": metric_name},
            {"type": "commit", "sha": culprit_sha},
        ]
    else:
        metrics = []
        gold_refs = [
            {"type": "log", "id": first_error_id},
            {"type": "commit", "sha": culprit_sha},
        ]

    return Scenario(
        id=sid,
        failure_class=failure_class,
        now=now,
        logs=logs,
        commits=commits,
        metrics=metrics,
        gold_cause=gold_cause,
        gold_evidence_refs=gold_refs,
    )


def _scenario_id(bank: _Bank, failure_class: str, offset: int) -> str:
    if bank.id_style == "fixtures":
        # bad_deploy is offset by the hand-authored anchor (id 0001).
        base = 2 if failure_class == "bad_deploy" else 1
        return f"{failure_class}_{base + offset:04d}"
    if bank.id_style == "holdout":
        return f"hold_{failure_class}_{offset + 1:02d}"
    # train/probe (DR-0020): the id_style doubles as the namespace prefix, so
    # training-side ids can never collide with an eval item on disk.
    return f"{bank.id_style}_{failure_class}_{offset + 1:04d}"


def generate_scenarios(split: str = "fixtures") -> list[Scenario]:
    """Deterministically generate the scenarios for a split — the eval corpora
    ("fixtures"/"holdout") or the DR-0020 training-side splits ("train"/"probe").
    Same split -> identical output every run (seeded PRNG, fixed epoch); the
    training corpus and probe sets are byte-derived from this, so changes here
    change what gets trained on. The hand-authored ``bad_deploy_0001`` fixture
    is NOT produced here."""
    bank = _bank(split)
    rng = random.Random(bank.seed)
    out: list[Scenario] = []
    for failure_class, n in bank.counts:
        for offset in range(n):
            out.append(
                _make_scenario(
                    sid=_scenario_id(bank, failure_class, offset),
                    failure_class=failure_class,
                    bank=bank,
                    rng=rng,
                    index=len(out),
                )
            )
    return out
