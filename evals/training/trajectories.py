"""DR-0020 trajectory builder — what one training example IS, made executable.

One example = one full multi-turn JSON-action ReAct trajectory in the EXACT
runtime message shapes. Nothing here re-implements a message: every trajectory
is produced by replaying a scripted action sequence through the REAL
``run_loop`` against ``run_evals.scenario_tools``, and the captured transcript
IS the training example — byte-identical to inference by construction
(DR-0020 decisions 1–3).

Scenarios come from the ``train`` split only (fixtures vocabulary, fresh seed,
``train_`` ids — never the committed eval items, never the holdout). Abstention
is FOUNDED (decision 5): ablated variants where the gold terminal is the
runtime abstained-diagnose JSON, hard variants ≥ 50% of the abstain mass,
contrastive near-pairs, plus diagnose-terminal trap examples against
pattern-fill fabrication. Every example passes the fail-closed gates before it
exists (decision 3): judge + fabrication check against its own scenario, the
citation-prefix gate (cited ⊆ observed-earlier-in-this-example), evidence-
derived narrowing arguments, and a conservative length budget.
"""

from __future__ import annotations

import json
import random
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from evals.fabrication_check import check_fabrication
from evals.judge import judge
from evals.run_evals import scenario_tools
from evals.scenarios.generator import Scenario, bank_vocabulary, generate_scenarios
from quellgeist.agent.loop import LoopResult, run_loop

_TS_FMT = "%Y-%m-%dT%H:%M:%SZ"
# Variant assignment / paraphrase draws. Scenario CONTENT comes from the train
# split's own seed (20260703, generator.py); this seed only shapes trajectories.
_SEED = 20260705
# ~4096 tokens at the conservative chars/3 bound (DR-0020 decision 9). The real
# Qwen3 BPE count is re-asserted in the training notebook before any run.
_MAX_CHARS = 12_288
_MAX_ASSISTANT_TURNS = 5  # DR-0020 decision 4: never teach burning the budget

# --------------------------------------------------------------------------- #
# Composition (DR-0020 decisions 4/5 starting points — tunables, revised
# against the abstention probe's gate and the structure probe's report).
# 296 train scenarios → 316 examples: 60 abstain (19%), 32 traps (10%),
# 36 recovery, 42 narrowing, 12 retry, 134 canonical.
# --------------------------------------------------------------------------- #
_N_ABSTAIN = {  # hard variants (time_shift/weak_link/decoy_wall) = 36/60 = 60%
    "no_culprit": 12,
    "no_incident": 12,
    "time_shift": 16,
    "weak_link": 12,  # bad_deploy only (rewrites module error signatures)
    "decoy_wall": 8,
}
_N_NEAR_PAIR = {  # of the abstain scenarios, how many ALSO appear solvable
    "no_culprit": 4,
    "no_incident": 4,
    "time_shift": 5,
    "weak_link": 4,
    "decoy_wall": 3,
}
_N_SOLVABLE = {
    "retry": 12,
    "recovery": 36,
    "narrowing": 42,
    "metric_bait": 18,  # non-resource only (empty-metrics fabrication trap)
    "decoy_bait": 14,
    "canonical_commits_first": 40,
    # the remainder of the solvable pool becomes canonical_logs_first
}

_HARD_ABSTAIN = ("time_shift", "weak_link", "decoy_wall")
# class constraints per variant/recipe: weak_link needs a code-deploy culprit
# (see _weak_link's docstring); metric_bait needs an empty metrics observation.
_CONSTRAINTS = {
    "bad_deploy": lambda s: s.failure_class == "bad_deploy",
    "non_resource": lambda s: s.failure_class != "resource_exhaustion",
}
_VARIANT_CONSTRAINT = {"weak_link": "bad_deploy", "metric_bait": "non_resource"}


def take_scenarios(
    pool: list[Scenario], n: int, *, only: str | None = None
) -> list[Scenario]:
    """Deterministically pop the first ``n`` scenarios satisfying the named
    constraint from ``pool`` (mutating it) — the one selection mechanism shared
    by the corpus and probe builders, so both draw with identical semantics."""
    predicate = _CONSTRAINTS[only] if only else None
    picked: list[Scenario] = []
    rest: list[Scenario] = []
    for s in pool:
        if len(picked) < n and (predicate is None or predicate(s)):
            picked.append(s)
        else:
            rest.append(s)
    assert len(picked) == n, f"pool exhausted taking {n} (only={only})"
    pool[:] = rest
    return picked


class ScriptedProvider:
    """Plays back a precomputed action sequence through the real ``run_loop``.
    The transcript comes back on ``LoopResult.messages`` — a documented loop
    contract, so training bytes equal inference bytes by construction."""

    def __init__(self, script: list[str]) -> None:
        self.script = list(script)
        self.calls = 0

    def complete(self, messages: list[dict[str, str]]) -> str:
        text = self.script[self.calls]
        self.calls += 1
        return text


# --------------------------------------------------------------------------- #
# Scenario field helpers
# --------------------------------------------------------------------------- #


def _gold_sha(s: Scenario) -> str:
    return next(r.sha for r in s.gold_evidence_refs if r.type == "commit")


def culprit_of(s: Scenario) -> dict[str, Any]:
    return next(c for c in s.commits if c["sha"] == _gold_sha(s))


def _decoy(s: Scenario) -> dict[str, Any]:
    return next(c for c in s.commits if c["sha"] != _gold_sha(s))


def error_rows(s: Scenario) -> list[dict[str, Any]]:
    return [r for r in s.logs if r["level"] == "ERROR"]


def parse_ts(ts: str) -> datetime:
    return datetime.strptime(ts, _TS_FMT)


def fmt_ts(dt: datetime) -> str:
    return dt.strftime(_TS_FMT)


def variant_scenario(s: Scenario, recipe: str, **updates: Any) -> Scenario:
    """A modified copy of ``s`` — the ablation/trap mechanism. The id carries
    the recipe so a variant can never shadow its base scenario."""
    doc = s.model_dump()
    doc.update(updates)
    doc["id"] = f"{s.id}__{recipe}"
    return Scenario(**doc)


# --------------------------------------------------------------------------- #
# Abstention recipes (DR-0020 decision 5). Everything not named stays
# byte-identical to the base scenario, so the abstain signal has no spurious
# surface correlate beyond the ablated element itself.
# --------------------------------------------------------------------------- #


def _no_culprit(s: Scenario, rng: random.Random) -> Scenario:
    return variant_scenario(
        s, "no_culprit", commits=[c for c in s.commits if c["sha"] != _gold_sha(s)]
    )


def _no_incident(s: Scenario, rng: random.Random) -> Scenario:
    logs = [r for r in s.logs if r["level"] != "ERROR"]
    metrics = [
        {**m, "points": [{**p, "value": m["points"][0]["value"]} for p in m["points"]]}
        for m in s.metrics
    ]  # flatten the climb to its own baseline value
    return variant_scenario(s, "no_incident", logs=logs, metrics=metrics)


def _time_shift(s: Scenario, rng: random.Random) -> Scenario:
    """All signals present at full richness; the only candidate deploy now
    POSTDATES the errors it would need to cause — the one recipe that punishes
    the cite-newest-commit shortcut."""
    last_err = parse_ts(error_rows(s)[-1]["ts"])
    shifted = fmt_ts(last_err + timedelta(minutes=10))
    commits = [
        {**c, "ts": shifted} if c["sha"] == _gold_sha(s) else c for c in s.commits
    ]
    now = fmt_ts(last_err + timedelta(minutes=15))
    return variant_scenario(s, "time_shift", commits=commits, now=now)


def _weak_link(s: Scenario, rng: random.Random) -> Scenario:
    """Error signatures rewritten to blame a module the deploy never touched
    (fixtures-bank vocabulary only). bad_deploy ONLY: a deploy that touched
    cart.py cannot explain an auth.verify_token error, so the ablation is
    cleanly unanswerable — whereas a config edit could plausibly break keys
    beyond the one its commit message names, which would make a config
    weak_link label noise rather than a hard abstention."""
    assert s.failure_class == "bad_deploy", s.id
    vocab = bank_vocabulary("train")
    culprit_stem = culprit_of(s)["files"][0].rsplit("/", 1)[-1].removesuffix(".py")
    other = rng.choice([m for m in vocab["modules"] if m.split(".")[0] != culprit_stem])
    new_msg = rng.choice(vocab["code_errors"]).format(module=other)
    logs = [{**r, "msg": new_msg} if r["level"] == "ERROR" else r for r in s.logs]
    return variant_scenario(s, "weak_link", logs=logs)


def _decoy_wall(s: Scenario, rng: random.Random) -> Scenario:
    """Both commits are decoys, the newest with bait wording naming the failing
    route — maximal temptation, zero attribution."""
    route = error_rows(s)[0]["route"]
    commits = [
        (
            {**c, "msg": f"docs: update README for {route}", "files": ["README.md"]}
            if c["sha"] == _gold_sha(s)
            else c
        )
        for c in s.commits
    ]
    return variant_scenario(s, "decoy_wall", commits=commits)


ABSTAIN_RECIPES = {
    "no_culprit": _no_culprit,
    "no_incident": _no_incident,
    "time_shift": _time_shift,
    "weak_link": _weak_link,
    "decoy_wall": _decoy_wall,
}

_ABSTAIN_REASONS = {
    "no_culprit": (
        "Logs show {n_err} ERROR entries on {route} starting {err_ts}, but the only "
        "commit in the history is an unrelated docs change — no deploy or config "
        "change explains the failure.",
        "{route} is returning 500s from {err_ts}, yet nothing in the deploy history "
        "correlates: the sole commit touches README.md only.",
        "There are real errors on {route}, but no candidate change: the commit log "
        "contains only a documentation edit, so I cannot pin a root cause.",
    ),
    # Two pools: the metric-mentioning one is ONLY used when the trajectory
    # actually observed a query_metrics result — an abstention reason must
    # never assert an observation the transcript does not contain (the same
    # grounding rule the evidence handles live under; gated in _gate).
    "no_incident": (
        "No ERROR-level logs in the window; recent deploys show no correlated "
        "failures, so there is no incident evidence to diagnose.",
        "All observed requests return 200 — nothing indicates an active incident.",
        "The logs contain only healthy traffic and the deploy history shows no "
        "correlated errors; there is nothing to attribute.",
    ),
    "no_incident_metrics": (
        "No ERROR-level logs in the window and the metrics stay at baseline; recent "
        "deploys show no correlated failures, so there is no incident evidence to "
        "diagnose.",
        "All observed requests return 200 and no metric deviates from baseline — "
        "nothing indicates an active incident.",
        "The logs show only healthy traffic, the metric series is flat, and the "
        "deploy history has no correlated errors; there is nothing to attribute.",
    ),
    "time_shift": (
        "The only candidate deploy at {deploy_ts} postdates the first error at "
        "{err_ts}, so it cannot be the cause, and no earlier change explains the "
        "errors.",
        "{route} errors begin at {err_ts}, before the {deploy_ts} deploy — the one "
        "candidate change happened after the failure it would need to cause.",
        "Temporal order rules out the visible deploy: errors start {err_ts}, the "
        "deploy lands {deploy_ts}; with no earlier change, I cannot name a cause.",
    ),
    "weak_link": (
        "Errors on {route} report '{err_msg}', but neither commit touches anything "
        "related — the deploy edited {files} and the other commit is a docs change.",
        "The failing signature '{err_msg}' matches no file either commit touched; "
        "the evidence does not connect the visible changes to the failure.",
        "{route} errors point at a component ({err_msg}) that the deploy history "
        "never modified, so the cited changes cannot be shown to be the cause.",
    ),
    "decoy_wall": (
        "Errors on {route} began at {err_ts}, but both commits are documentation-"
        "only changes to README.md; nothing in the deploy history explains the "
        "failure.",
        "Despite the commit message mentioning {route}, both commits touch only "
        "README.md — a docs edit cannot cause these 500s, and no other change "
        "exists.",
        "The only commits are README-only edits; the failing service has no "
        "correlated code or config change, so I cannot pin a root cause.",
    ),
}


# --------------------------------------------------------------------------- #
# Trap recipes (diagnose-terminal, DR-0020 decision 5)
# --------------------------------------------------------------------------- #


def _metric_bait(s: Scenario, rng: random.Random) -> Scenario:
    """Resource-flavoured error text on a non-resource scenario: the trajectory
    queries metrics, observes ``[]``, and the gold cites ONLY log+commit — the
    negative space for the metric pattern-fill fabrication channel."""
    bait = rng.choice(bank_vocabulary("train")["resource_errors"])
    logs = [{**r, "msg": bait} if r["level"] == "ERROR" else r for r in s.logs]
    return variant_scenario(s, "metric_bait", logs=logs)


def _decoy_bait(s: Scenario, rng: random.Random) -> Scenario:
    """The decoy's message names the failing route; its files/timing still
    exonerate it. The gold cites the true culprit, never the decoy."""
    route = error_rows(s)[0]["route"]
    decoy_sha = _decoy(s)["sha"]
    commits = [
        {**c, "msg": f"docs: update README for {route}"} if c["sha"] == decoy_sha else c
        for c in s.commits
    ]
    return variant_scenario(s, "decoy_bait", commits=commits)


# --------------------------------------------------------------------------- #
# Diagnose-turn prose (templated from scenario fields only — notes are
# unchecked by every deterministic gate, so templating is their only defence)
# --------------------------------------------------------------------------- #

_CAUSE_TEMPLATES = {
    "bad_deploy": (
        "Bad deploy {sha} at {deploy_ts} ({deploy_msg}) broke {route}: the first "
        "500 lands at {err_ts} with '{err_msg}'.",
        "Deploy {sha} touched {files} minutes before {route} started failing at "
        "{err_ts} — the error '{err_msg}' points straight at that change.",
        "The {deploy_ts} deploy ({sha}) introduced the failure: {route} begins "
        "returning 500s at {err_ts}, seconds after the rollout.",
        "Commit {sha} ({deploy_msg}) is the only change preceding the {route} "
        "error burst that starts at {err_ts}.",
    ),
    "config_error": (
        "Config change {sha} at {deploy_ts} ({deploy_msg}) edited {files} and broke "
        "{route}: errors begin at {err_ts} with '{err_msg}'.",
        "The {deploy_ts} config commit {sha} precedes the {route} failures by "
        "seconds — '{err_msg}' names the changed setting.",
        "Commit {sha} changed {files}; {route} starts failing at {err_ts} with a "
        "config-shaped error ('{err_msg}').",
        "{route} 500s from {err_ts} trace to the {deploy_ts} config change {sha} "
        "({deploy_msg}).",
    ),
    "resource_exhaustion": (
        "Resource exhaustion: deploy {sha} at {deploy_ts} ({deploy_msg}) drove "
        "{metric} to its ceiling; {route} errors begin at {err_ts}.",
        "After the {deploy_ts} deploy ({sha}), {metric} climbs from baseline to its "
        "ceiling and {route} starts failing at {err_ts} with '{err_msg}'.",
        "Deploy {sha} exhausts a resource: {metric} saturates right after "
        "{deploy_ts} and the first {route} error lands at {err_ts}.",
        "{metric} rises monotonically from the {deploy_ts} deploy ({sha}) until "
        "{route} errors start at {err_ts} — a classic exhaustion pattern.",
    ),
}

_SUMMARY_TEMPLATES = (
    "{route} broke at {err_ts}; the {deploy_ts} commit {sha} is the cause.",
    "Commit {sha} ({deploy_ts}) caused the {route} failures that start at {err_ts}.",
    "Root cause: {sha}, deployed {deploy_ts}, with {route} errors from {err_ts}.",
)

_ACTION_TEMPLATES = {
    "bad_deploy": (
        "Roll back commit {sha} and redeploy.",
        "Revert {sha}, then confirm {route} recovers.",
    ),
    "config_error": (
        "Revert config commit {sha} and restore the previous setting.",
        "Roll back {sha}, then verify {route} returns 200s.",
    ),
    "resource_exhaustion": (
        "Revert {sha} and watch {metric} return to baseline.",
        "Roll back commit {sha}; confirm {metric} drops below its ceiling.",
    ),
}


def _diagnosis_payload(s: Scenario, rng: random.Random) -> dict[str, Any]:
    culprit = culprit_of(s)
    err = error_rows(s)[0]
    fields = {
        "sha": culprit["sha"],
        "deploy_ts": culprit["ts"],
        "deploy_msg": culprit["msg"],
        "files": ", ".join(culprit["files"]),
        "route": err["route"],
        "err_ts": err["ts"],
        "err_msg": err["msg"],
        "metric": s.metrics[0]["metric"] if s.metrics else "",
    }
    evidence = []
    for ref in s.gold_evidence_refs:
        if ref.type == "log":
            evidence.append(
                {
                    "type": "log",
                    "id": ref.id,
                    "note": f"first ERROR on {err['route']} at {err['ts']}: {err['msg']}",
                }
            )
        elif ref.type == "metric":
            series = next(m for m in s.metrics if m["metric"] == ref.id)
            evidence.append(
                {
                    "type": "metric",
                    "id": ref.id,
                    "note": f"{series['metric']} climbs to its ceiling after the deploy",
                }
            )
        else:
            evidence.append(
                {
                    "type": "commit",
                    "sha": ref.sha,
                    "note": f"{culprit['msg']} at {culprit['ts']}, touching {fields['files']}",
                }
            )
    return {
        "summary": rng.choice(_SUMMARY_TEMPLATES).format(**fields),
        "abstained": False,
        "abstention_reason": None,
        "hypotheses": [
            {
                "cause": rng.choice(_CAUSE_TEMPLATES[s.failure_class]).format(**fields),
                "confidence": round(rng.uniform(0.7, 0.95), 2),
                "evidence": evidence,
            }
        ],
        "suggested_actions": [
            rng.choice(_ACTION_TEMPLATES[s.failure_class]).format(**fields)
        ],
    }


def _abstention_payload(s: Scenario, recipe: str, rng: random.Random) -> dict[str, Any]:
    # The reason must be grounded in what the trajectory observed: the metric-
    # mentioning no_incident pool applies only when query_metrics ran (i.e. the
    # scenario carries a metric series the script will have queried).
    if recipe == "no_incident" and s.metrics:
        recipe = "no_incident_metrics"
    errs = error_rows(s)
    err = errs[0] if errs else None
    commits_newest_first = sorted(s.commits, key=lambda c: c["ts"], reverse=True)
    fields = {
        "n_err": len(errs),
        "route": err["route"] if err else "",
        "err_ts": err["ts"] if err else "",
        "err_msg": err["msg"] if err else "",
        "deploy_ts": commits_newest_first[0]["ts"] if s.commits else "",
        "files": ", ".join(commits_newest_first[0]["files"]) if s.commits else "",
    }
    return {
        "abstained": True,
        "abstention_reason": rng.choice(_ABSTAIN_REASONS[recipe]).format(**fields),
        "hypotheses": [],
    }


# --------------------------------------------------------------------------- #
# Action scripts
# --------------------------------------------------------------------------- #


def _act(name: str, **args: Any) -> str:
    return json.dumps({"action": name, "args": args})


def _tool_script(
    s: Scenario, rng: random.Random, *, order: str, narrowed: bool, probe_metrics: bool
) -> list[str]:
    """The broad-first evidence-gathering calls (DR-0020 decision 4). Narrowing
    arguments are copied from values the prior broad observation contains."""
    err = error_rows(s)[0] if error_rows(s) else None
    logs_calls = [_act("query_logs")]
    if narrowed and err is not None:
        logs_calls.append(_act("query_logs", level="ERROR", route=err["route"]))
    commits_call = [_act("get_recent_commits")]
    script = (
        logs_calls + commits_call
        if order == "logs_first"
        else commits_call + logs_calls
    )
    if s.metrics or probe_metrics:
        script.append(_act("query_metrics"))
    return script


def _recovery_prefix(s: Scenario, rng: random.Random) -> str:
    """A realistic speculative first call that legitimately returns [] — loss-
    masked context; the trained turn is the broad fallback that follows. The
    over-narrow ``since`` variant uses the trigger's own timestamp ("logs since
    the incident was reported") — a natural guess that a real run could make,
    and one that excludes every row because all signals predate ``now``."""
    present = {r["route"] for r in s.logs}
    absent = sorted(set(bank_vocabulary("train")["routes"]) - present)
    if rng.random() < 0.5 and absent:
        return _act("query_logs", route=rng.choice(absent))
    return _act("query_logs", since=s.now)


# --------------------------------------------------------------------------- #
# Example assembly + fail-closed gates
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class _Spec:
    scenario: Scenario  # the (possibly ablated/trapped) scenario the loop replays
    base_id: str  # the base train-scenario id (audit linkage for near-pairs)
    kind: str  # "diagnose" | "abstain"
    variant: str
    script: list[str]
    masked: tuple[int, ...] = ()  # script indices whose assistant turns get train:false
    expect_violations: int = 0


def _assistant_indices(messages: list[dict[str, Any]]) -> list[int]:
    return [i for i, m in enumerate(messages) if m["role"] == "assistant"]


def _observations_before_last(messages: list[dict[str, Any]]) -> str:
    return "\n".join(
        m["content"]
        for m in messages[:-1]
        if m["role"] == "user" and m["content"].startswith("Observation from ")
    )


def _gate(example: dict[str, Any], spec: _Spec, result: LoopResult) -> None:
    s, messages = spec.scenario, example["messages"]
    ident = example["id"]
    assert result.steps == len(
        spec.script
    ), f"{ident}: loop consumed a retry we did not script"
    assert len(spec.masked) < len(
        spec.script
    ), f"{ident}: a fully-masked example trains nothing"
    assert (
        len(result.schema_violations) == spec.expect_violations
    ), f"{ident}: violations {result.schema_violations}"
    n_assistant = len(_assistant_indices(messages))
    assert n_assistant == len(spec.script)
    assert n_assistant <= _MAX_ASSISTANT_TURNS, f"{ident}: teaches step burning"
    total = sum(len(m["content"]) for m in messages)
    assert total <= _MAX_CHARS, f"{ident}: {total} chars exceeds the length budget"
    for m in messages:
        assert "<|im_" not in m["content"] and "<think>" not in m["content"], ident

    prior_obs = _observations_before_last(messages)
    if spec.kind == "diagnose":
        assert not result.diagnosis.abstained, ident
        assert judge(result.diagnosis, s).passed, f"{ident}: gold turn fails the judge"
        assert check_fabrication(
            result.diagnosis, s.logs, s.commits, s.metrics
        ).ok, f"{ident}: fabricated handle in a gold turn"
        # Citation-prefix gate (stricter than the fabrication check): cited ⊆
        # observed earlier in THIS example, at handle level and as raw bytes.
        assert result.cited_but_unseen_handles() == set(), ident
        decoy_shas = {c["sha"] for c in s.commits} - {_gold_sha(s)}
        for hyp in result.diagnosis.hypotheses:
            for ref in hyp.evidence:
                if ref.type == "log":
                    # trailing comma: log rows always carry ts after id, and it
                    # keeps '"id": 3' from matching an observed '"id": 30'
                    needle: str = f'"id": {ref.id},'
                elif ref.type == "commit":
                    needle = ref.sha
                    assert ref.sha not in decoy_shas, f"{ident}: cites the decoy"
                else:
                    needle = f'"metric": "{ref.id}"'
                assert needle in prior_obs, f"{ident}: cited {needle} never observed"
    else:
        assert result.diagnosis.abstained, ident
        assert result.diagnosis.hypotheses == [], ident
        # Reason grounding: an abstention may claim metric observations only
        # when a query_metrics observation exists in this very transcript.
        reason = (result.diagnosis.abstention_reason or "").lower()
        if "metric" in reason:
            assert any(
                m["role"] == "user"
                and m["content"].startswith("Observation from query_metrics: ")
                for m in messages[:-1]
            ), f"{ident}: reason mentions metrics never observed"

    # Evidence-derived narrowing: every argument value of an UNMASKED tool call
    # must appear in an observation the model had already seen (broad calls are
    # argument-free, so this bites exactly the narrowing turns).
    seen_so_far: list[str] = []
    script_pos = 0
    for m in messages:
        if m["role"] == "user" and m["content"].startswith("Observation from "):
            seen_so_far.append(m["content"])
        if m["role"] == "assistant":
            obj = json.loads(m["content"])
            if obj["action"] != "diagnose" and script_pos not in spec.masked:
                for value in obj["args"].values():
                    assert any(
                        str(value) in obs for obs in seen_so_far
                    ), f"{ident}: unobserved filter value {value!r}"
            script_pos += 1


def _build_example(spec: _Spec) -> dict[str, Any]:
    provider = ScriptedProvider(spec.script)
    result = run_loop(
        provider, scenario_tools(spec.scenario), now=spec.scenario.now, max_steps=8
    )
    assert provider.calls == len(
        spec.script
    ), f"{spec.scenario.id}: script not consumed"
    transcript = result.messages
    masked_msg_idx = {_assistant_indices(transcript)[i] for i in spec.masked}
    messages: list[dict[str, Any]] = []
    for i, m in enumerate(transcript):
        out: dict[str, Any] = {"role": m["role"], "content": m["content"]}
        if i in masked_msg_idx:
            out["train"] = False
        messages.append(out)
    example = {
        "id": f"{spec.base_id}.{spec.variant}",
        "scenario_id": spec.base_id,
        "failure_class": spec.scenario.failure_class,
        "kind": spec.kind,
        "variant": spec.variant,
        "messages": messages,
    }
    _gate(example, spec, result)
    return example


# --------------------------------------------------------------------------- #
# Corpus assembly
# --------------------------------------------------------------------------- #


def _solvable_spec(s: Scenario, variant: str, rng: random.Random) -> _Spec:
    order = "commits_first" if variant == "canonical_commits_first" else "logs_first"
    scenario, masked, expect_violations, probe_metrics = s, (), 0, False
    prefix: list[str] = []
    if variant == "recovery":
        prefix, masked = [_recovery_prefix(s, rng)], (0,)
    elif variant == "retry":
        # non-canonical `since` (missing Z) → the filters' loud ValueError → the
        # loop's real retry message; the corrected turn falls back to broad.
        prefix, masked, expect_violations = (
            [_act("query_logs", since=s.now[:-1])],
            (0,),
            1,
        )
    elif variant == "metric_bait":
        scenario, probe_metrics = _metric_bait(s, rng), True
    elif variant == "decoy_bait":
        scenario = _decoy_bait(s, rng)
    script = prefix + _tool_script(
        scenario,
        rng,
        order=order,
        narrowed=(variant == "narrowing"),
        probe_metrics=probe_metrics,
    )
    script.append(
        json.dumps(
            {"action": "diagnose", "diagnosis": _diagnosis_payload(scenario, rng)}
        )
    )
    return _Spec(scenario, s.id, "diagnose", variant, script, masked, expect_violations)


def _abstain_spec(
    s: Scenario, recipe: str, rng: random.Random, *, order: str | None = None
) -> _Spec:
    # Near-pair members pin order to their solvable twin's (logs_first) so the
    # pair differs ONLY in the ablated causal element (DR-0020 decision 5) —
    # otherwise the terminal-label gradient could attach to tool order.
    scenario = ABSTAIN_RECIPES[recipe](s, rng)
    order = order or rng.choice(("logs_first", "commits_first"))
    script = _tool_script(
        scenario, rng, order=order, narrowed=False, probe_metrics=False
    )
    script.append(
        json.dumps(
            {
                "action": "diagnose",
                "diagnosis": _abstention_payload(scenario, recipe, rng),
            }
        )
    )
    return _Spec(scenario, s.id, "abstain", recipe, script)


def build_examples() -> list[dict[str, Any]]:
    """The full training corpus, deterministically — same output every run
    (what was reviewed is what is trained on, DR-0020 decision 3)."""
    rng = random.Random(_SEED)
    pool = list(generate_scenarios("train"))
    rng.shuffle(pool)

    specs: list[_Spec] = []
    near_pair_bases: list[Scenario] = []
    for recipe, n in _N_ABSTAIN.items():
        chosen = take_scenarios(pool, n, only=_VARIANT_CONSTRAINT.get(recipe))
        for i, s in enumerate(chosen):
            near_pair = i < _N_NEAR_PAIR[recipe]  # contrastive: solvable twin
            specs.append(
                _abstain_spec(s, recipe, rng, order="logs_first" if near_pair else None)
            )
            if near_pair:
                near_pair_bases.append(s)
    for variant, n in _N_SOLVABLE.items():
        for s in take_scenarios(pool, n, only=_VARIANT_CONSTRAINT.get(variant)):
            specs.append(_solvable_spec(s, variant, rng))
    for s in pool:  # the remainder: canonical broad-first
        specs.append(_solvable_spec(s, "canonical_logs_first", rng))
    for s in near_pair_bases:
        specs.append(_solvable_spec(s, "canonical_logs_first", rng))

    examples = [_build_example(spec) for spec in specs]
    examples.sort(key=lambda e: e["id"])
    ids = [e["id"] for e in examples]
    assert len(ids) == len(set(ids)), "duplicate example ids"
    return examples


def corpus_stats(examples: list[dict[str, Any]]) -> dict[str, Any]:
    """Composition numbers for the build summary and the ratio tests."""
    n = len(examples)
    abstain = [e for e in examples if e["kind"] == "abstain"]
    hard = [e for e in abstain if e["variant"] in _HARD_ABSTAIN]
    traps = [e for e in examples if e["variant"] in ("metric_bait", "decoy_bait")]
    solvable_ids = {e["scenario_id"] for e in examples if e["kind"] == "diagnose"}
    near_pairs = [e for e in abstain if e["scenario_id"] in solvable_ids]
    by_variant: dict[str, int] = {}
    for e in examples:
        by_variant[e["variant"]] = by_variant.get(e["variant"], 0) + 1
    return {
        "examples": n,
        "abstain_share": len(abstain) / n,
        "hard_abstain_share": len(hard) / len(abstain),
        "near_pair_share": len(near_pairs) / len(abstain),
        "trap_share": len(traps) / n,
        "by_variant": dict(sorted(by_variant.items())),
    }
