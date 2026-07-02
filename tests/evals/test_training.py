"""Tests for the DR-0020 training-data pipeline. Deterministic, no model.

The builder's fail-closed gates already run inside ``build_examples`` (an
example that violates one cannot exist); these tests pin the properties from
the OUTSIDE — determinism, composition, byte-fidelity to the runtime prompts,
zero contamination of the serialized artifacts (anchor included), probe-set
integrity, and that the committed sample/probes reconcile with a rebuild.
"""

from __future__ import annotations

import ast
import json
from pathlib import Path

import pytest

from evals.fabrication_check import check_fabrication
from evals.judge import judge
from evals.run_evals import scenario_tools
from evals.scenarios.build import scenario_json
from evals.scenarios.generator import (
    Scenario,
    distribution_tokens,
    generate_scenarios,
    load_scenario,
)
from evals.training import build as training_build
from evals.training.contamination import (
    assert_no_holdout_leakage,
    committed_fixture_ids_and_shas,
    find_holdout_leaks,
    holdout_shas,
)
from evals.training.probes import build_probes
from evals.training.trajectories import build_examples, corpus_stats
from quellgeist.agent.loop import run_loop
from quellgeist.agent.prompts import build_system_prompt, user_trigger
from quellgeist.agent.schema import Diagnosis, Hypothesis

_TRAINING_DIR = Path(__file__).resolve().parents[2] / "evals" / "training"


@pytest.fixture(autouse=True)
def _no_ambient_verifier(monkeypatch):
    # The probe runner reads QG_VERIFY from the environment; a developer with
    # verifier env exported must not make these hermetic tests call a live
    # model (same class of leak tests/evals/test_runner.py scrubs for).
    monkeypatch.delenv("QG_VERIFY", raising=False)
    monkeypatch.delenv("QG_VERIFIER_MODEL", raising=False)


@pytest.fixture(scope="module")
def examples():
    return build_examples()


@pytest.fixture(scope="module")
def probes():
    return build_probes()


# --------------------------------------------------------------------------- #
# The train/probe splits (generator side)
# --------------------------------------------------------------------------- #


def test_train_split_shares_the_fixtures_bank_and_avoids_the_holdout():
    # DR-0020 decision 3: training stays on the fixtures DISTRIBUTION (same
    # vocabulary) while the holdout bank stays untouched.
    assert distribution_tokens("train") == distribution_tokens("fixtures")
    assert distribution_tokens("train").isdisjoint(distribution_tokens("holdout"))
    assert distribution_tokens("probe") == distribution_tokens("fixtures")


def test_train_split_ids_are_namespaced_and_fresh():
    train = generate_scenarios("train")
    assert len(train) == 296
    assert all(s.id.startswith("train_") for s in train)
    fixture_ids, fixture_shas = committed_fixture_ids_and_shas()
    assert fixture_ids.isdisjoint({s.id for s in train})
    train_shas = {c["sha"] for s in train for c in s.commits}
    assert train_shas.isdisjoint(fixture_shas)  # incl. the hand-authored anchor
    assert train_shas.isdisjoint(holdout_shas())


# --------------------------------------------------------------------------- #
# The corpus
# --------------------------------------------------------------------------- #


def test_build_is_deterministic(examples):
    again = build_examples()
    assert examples == again


def test_composition_matches_dr0020(examples):
    # DR-0020 decision 5 starting points: 15-25% abstain, >=50% of abstain mass
    # hard, ~1/3 contrastive near-pairs, ~10% traps.
    stats = corpus_stats(examples)
    assert 0.15 <= stats["abstain_share"] <= 0.25
    assert stats["hard_abstain_share"] >= 0.5
    assert stats["near_pair_share"] >= 0.30
    assert 0.07 <= stats["trap_share"] <= 0.13


def test_messages_are_byte_identical_to_the_runtime_prompts(examples):
    # The system prompt and trigger must be the loop's own bytes — composed the
    # way run_loop composes tool_lines from scenario_tools' ToolSpecs.
    tools = scenario_tools(generate_scenarios("train")[0])
    system = build_system_prompt([f"{t.name}: {t.description}" for t in tools])
    for e in examples:
        assert e["messages"][0] == {"role": "system", "content": system}
        trigger = e["messages"][1]
        assert trigger["role"] == "user"
        assert trigger["content"].startswith("An incident is occurring as of ")
    # spot-check the trigger against user_trigger for one example per class
    by_class = {e["failure_class"]: e for e in examples}
    for e in by_class.values():
        now = e["messages"][1]["content"].split(" as of ")[1].split(".")[0]
        assert e["messages"][1]["content"] == user_trigger(now)


def test_turn_structure_and_masking(examples):
    for e in examples:
        roles = [m["role"] for m in e["messages"]]
        assert roles[0] == "system" and roles[1] == "user"
        assert roles[2:] == ["assistant", "user"] * ((len(roles) - 3) // 2) + [
            "assistant"
        ], e["id"]
        for m in e["messages"]:
            if m["role"] != "assistant":
                assert "train" not in m, e["id"]  # only assistant turns carry it
        final = e["messages"][-1]
        assert final.get("train") is not False, e["id"]  # the terminal is trained
        obj = json.loads(final["content"])
        assert obj["action"] == "diagnose"
    masked = [
        e for e in examples if any(m.get("train") is False for m in e["messages"])
    ]
    # exactly the recovery + retry variants carry a masked context turn
    assert {e["variant"] for e in masked} == {"recovery", "retry"}


def test_recovery_teaches_broaden_on_empty(examples):
    for e in examples:
        if e["variant"] != "recovery":
            continue
        msgs = e["messages"]
        assert msgs[2].get("train") is False  # the speculative call is context
        assert msgs[3]["content"] == "Observation from query_logs: []"
        assert json.loads(msgs[4]["content"]) == {"action": "query_logs", "args": {}}
        assert msgs[4].get("train") is not False  # the broad fallback is trained


def test_retry_embeds_the_loops_real_retry_message(examples):
    retries = [e for e in examples if e["variant"] == "retry"]
    assert retries
    for e in retries:
        msgs = e["messages"]
        assert msgs[2].get("train") is False
        assert msgs[3]["content"].startswith(
            "Your previous response was not a valid action: tool query_logs "
            "failed: ValueError: since must be"
        ), e["id"]
        assert json.loads(msgs[4]["content"]) == {"action": "query_logs", "args": {}}


def test_metric_bait_traps_query_metrics_and_cite_no_metric(examples):
    baits = [e for e in examples if e["variant"] == "metric_bait"]
    assert baits
    for e in baits:
        contents = [m["content"] for m in e["messages"]]
        assert "Observation from query_metrics: []" in contents, e["id"]
        final = json.loads(contents[-1])
        cited_types = {
            ev["type"] for h in final["diagnosis"]["hypotheses"] for ev in h["evidence"]
        }
        assert "metric" not in cited_types, e["id"]


def test_abstain_examples_investigate_first_and_use_the_runtime_shape(examples):
    abstains = [e for e in examples if e["kind"] == "abstain"]
    for e in abstains:
        tool_calls = [
            json.loads(m["content"])["action"]
            for m in e["messages"][:-1]
            if m["role"] == "assistant"
        ]
        # abstention is earned by looking: both broad signals precede it
        assert {"query_logs", "get_recent_commits"} <= set(tool_calls), e["id"]
        diag = json.loads(e["messages"][-1]["content"])["diagnosis"]
        Diagnosis(**diag)  # validates the abstention invariant
        assert diag["abstained"] is True and diag["hypotheses"] == []


# --------------------------------------------------------------------------- #
# Contamination (artifact-level)
# --------------------------------------------------------------------------- #


def test_serialized_corpus_is_holdout_clean(examples):
    fixture_ids, fixture_shas = committed_fixture_ids_and_shas()
    banned = fixture_shas | holdout_shas()
    for e in examples:
        line = json.dumps(e)
        assert_no_holdout_leakage(line, e["id"])
        assert '"hold_' not in line
        for sha in banned:
            assert sha not in line, f"{e['id']}: {sha}"
        assert e["scenario_id"].startswith("train_")
        assert e["scenario_id"] not in fixture_ids


def test_scan_catches_planted_leaks_without_false_positives():
    # expanded-template recall: a rendered holdout commit message and error
    # signature, a holdout route, and a holdout culprit path must all be caught
    for planted in (
        "deploy: migrate cache backend",
        "environment variable QUEUE_URL is undefined",
        "/search",
        "demo/app/upload.py",
        "cache_entries_resident",
    ):
        assert find_holdout_leaks(f"prefix {planted} suffix"), planted
    # boundary-awareness: fixtures-legitimate text must not trip the scan
    # (committed serialized fixtures are the strongest no-false-positive corpus)
    fixtures_dir = Path(__file__).resolve().parents[2] / "evals/scenarios/fixtures"
    text = "\n".join(p.read_text(encoding="utf-8") for p in fixtures_dir.glob("*.json"))
    assert find_holdout_leaks(text) == set()
    # and the serialized holdout must trip it comprehensively
    holdout_dir = fixtures_dir.parent / "holdout"
    for p in holdout_dir.glob("*.json"):
        assert find_holdout_leaks(p.read_text(encoding="utf-8")), p.name


def _code_strings(path: Path) -> list[str]:
    """Every string constant in a module's CODE — docstrings excluded (they may
    legitimately mention the eval-selection mechanism; code must not use it)."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    docstrings: set[int] = set()
    for node in ast.walk(tree):
        body = getattr(node, "body", None)
        if (
            isinstance(
                node, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)
            )
            and body
            and isinstance(body[0], ast.Expr)
            and isinstance(body[0].value, ast.Constant)
            and isinstance(body[0].value.value, str)
        ):
            docstrings.add(id(body[0].value))
    return [
        n.value
        for n in ast.walk(tree)
        if isinstance(n, ast.Constant)
        and isinstance(n.value, str)
        and id(n) not in docstrings
    ]


def test_builder_never_touches_the_eval_scenario_selection():
    # DR-0020 decision 7: builder path isolation. The training pipeline may
    # veto against holdout HANDLES (contamination.py, in-memory), but the
    # builder modules must never read the eval scenario dirs or the
    # env-var selection mechanism — no code string names either.
    exempt = {"contamination.py"}  # the veto side references holdout handles
    for path in sorted(_TRAINING_DIR.glob("*.py")):
        if path.name in exempt:
            continue
        for value in _code_strings(path):
            assert "QG_SCENARIOS_DIR" not in value, (path.name, value)
            assert "holdout" not in value, (path.name, value)


# --------------------------------------------------------------------------- #
# Probe sets
# --------------------------------------------------------------------------- #


def _gold(s: Scenario) -> Diagnosis:
    return Diagnosis(
        hypotheses=[
            Hypothesis(
                cause=s.gold_cause, confidence=1.0, evidence=s.gold_evidence_refs
            )
        ]
    )


def _positional_script_diagnosis(s: Scenario) -> Diagnosis:
    """The measured DR-0020 script ceiling: cite the newest commit, the first
    ERROR row, and the single metric name — reading no token semantics."""
    newest = max(s.commits, key=lambda c: c["ts"])
    first_err = min((r for r in s.logs if r["level"] == "ERROR"), key=lambda r: r["id"])
    evidence: list = [
        {"type": "log", "id": first_err["id"]},
        {"type": "commit", "sha": newest["sha"]},
    ]
    if s.metrics:
        evidence.append({"type": "metric", "id": s.metrics[0]["metric"]})
    return Diagnosis(
        hypotheses=[Hypothesis(cause="script", confidence=0.9, evidence=evidence)]
    )


def test_probe_sets_are_deterministic_and_namespaced(probes):
    abstention, structure = probes
    again_a, again_s = build_probes()
    assert [s.model_dump() for s in abstention] == [s.model_dump() for s in again_a]
    assert [s.model_dump() for s in structure] == [s.model_dump() for s in again_s]
    assert len(abstention) == 12 and len(structure) == 10
    train_ids = {s.id for s in generate_scenarios("train")}
    for s in abstention + structure:
        assert s.id.startswith("probe_")
        assert s.id not in train_ids


def test_abstention_probe_items_are_unanswerable_by_construction(probes):
    abstention, _ = probes
    recipes = {s.id.rsplit("__", 1)[1] for s in abstention}
    assert recipes == {
        "no_culprit",
        "no_incident",
        "time_shift",
        "weak_link",
        "decoy_wall",
    }
    for s in abstention:
        assert s.gold_evidence_refs == []  # no gold handles: nothing to cite
        recipe = s.id.rsplit("__", 1)[1]
        if recipe == "no_culprit":
            assert len(s.commits) == 1
        if recipe == "no_incident":
            assert not any(r["level"] == "ERROR" for r in s.logs)
        if recipe == "time_shift":
            errs = [r for r in s.logs if r["level"] == "ERROR"]
            newest = max(s.commits, key=lambda c: c["ts"])
            assert newest["ts"] > errs[-1]["ts"]  # the candidate postdates the errors


def test_structure_probe_items_stay_gold_solvable(probes):
    _, structure = probes
    for s in structure:
        gold = _gold(s)
        assert judge(gold, s).passed, s.id
        assert check_fabrication(gold, s.logs, s.commits, s.metrics).ok, s.id


def test_structure_probe_defeats_the_positional_script(probes):
    # The probe's reason to exist: the script ceiling passes 81/81 on the
    # committed corpora, so at least the culprit-not-newest items must fail it.
    _, structure = probes
    not_newest = [s for s in structure if s.id.endswith("__culprit_not_newest")]
    assert not_newest
    for s in not_newest:
        assert not judge(_positional_script_diagnosis(s), s).passed, s.id


# --------------------------------------------------------------------------- #
# Committed artifacts reconcile with a rebuild (idempotency)
# --------------------------------------------------------------------------- #


def test_committed_sample_and_probes_match_a_rebuild(examples, probes):
    sample = training_build.select_sample(examples)
    committed = (_TRAINING_DIR / "sample_trajectories.jsonl").read_text(
        encoding="utf-8"
    )
    assert committed == "\n".join(json.dumps(e) for e in sample) + "\n"
    abstention, structure = probes
    for scenarios, sub in ((abstention, "abstention"), (structure, "structure")):
        directory = _TRAINING_DIR / "probes" / sub
        on_disk = sorted(p.name for p in directory.glob("*.json"))
        assert on_disk == sorted(f"{s.id}.json" for s in scenarios)
        for s in scenarios:
            path = directory / f"{s.id}.json"
            assert path.read_text(encoding="utf-8") == scenario_json(s)


def test_probe_scenarios_load_through_the_normal_loader(probes):
    # the structure probe doubles as a plain eval set (QG_SCENARIOS_DIR) and
    # every probe file must round-trip the Scenario schema
    _, structure = probes
    for sub in ("abstention", "structure"):
        for path in sorted((_TRAINING_DIR / "probes" / sub).glob("*.json")):
            load_scenario(path)


# --------------------------------------------------------------------------- #
# The abstention-probe runner
# --------------------------------------------------------------------------- #


class _CannedProvider:
    """Always answers with the same action text."""

    def __init__(self, text: str) -> None:
        self.text = text

    def complete(self, messages):
        return self.text


def test_abstention_probe_runner_scores_abstention_as_pass(capsys):
    from evals.training.run_abstention_probe import main

    abstainer = _CannedProvider(
        json.dumps(
            {
                "action": "diagnose",
                "diagnosis": {
                    "abstained": True,
                    "abstention_reason": "no supported cause",
                    "hypotheses": [],
                },
            }
        )
    )
    assert main(abstainer) == 0
    out = capsys.readouterr().out
    assert (
        "abstain recall 12/12 (+0 forced, not counted); 0 with fabricated evidence"
        in out
    )


class _GuessingProvider:
    """Queries commits, then confidently blames the newest one it observed —
    the exact failure mode the probe exists to catch, with zero fabrication
    (the cited handle is real, just unjustified)."""

    def complete(self, messages):
        last = messages[-1]["content"]
        if not last.startswith("Observation from get_recent_commits: "):
            return json.dumps({"action": "get_recent_commits", "args": {}})
        newest = json.loads(last.removeprefix("Observation from get_recent_commits: "))[
            0
        ]
        return json.dumps(
            {
                "action": "diagnose",
                "diagnosis": {
                    "abstained": False,
                    "hypotheses": [
                        {
                            "cause": "guessed: the newest commit must be it",
                            "confidence": 0.9,
                            "evidence": [{"type": "commit", "sha": newest["sha"]}],
                        }
                    ],
                },
            }
        )


def test_abstention_probe_runner_flags_a_guessing_model(capsys):
    from evals.training.run_abstention_probe import main

    # zero fabrication, but 0% deliberate abstention -> the single-pass floor fails
    assert main(_GuessingProvider()) == 1
    out = capsys.readouterr().out
    assert (
        "abstain recall 0/12 (+0 forced, not counted); 0 with fabricated evidence"
        in out
    )


def test_run_loop_replay_of_a_committed_sample_line(examples):
    # End-to-end spot check: replaying a committed example's assistant turns
    # through the real loop reproduces the example's messages byte-for-byte.
    e = next(x for x in examples if x["variant"] == "narrowing")
    scenario = next(s for s in generate_scenarios("train") if s.id == e["scenario_id"])
    script = [m["content"] for m in e["messages"] if m["role"] == "assistant"]

    class _Replay:
        def complete(self, messages):
            return script[sum(1 for m in messages if m["role"] == "assistant")]

    result = run_loop(
        _Replay(), scenario_tools(scenario), now=scenario.now, max_steps=8
    )
    stored = [{"role": m["role"], "content": m["content"]} for m in e["messages"]]
    assert result.messages == stored  # LoopResult.messages IS the transcript
