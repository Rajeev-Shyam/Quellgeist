"""Tests for the Wave-4 comparison-matrix tooling (plan Task 4, DR-0020 §8).

Offline throughout — scripted fake providers, no model, no network. Covers the
cell runner's fail-closed verifier pin, the scoring modes, the trace-level
audits (including recomputing DR-0020's recorded core-overlap numbers from the
committed corpora), the provider usage instrumentation, and the report merge.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path
from types import SimpleNamespace

import litellm
import pytest

from evals.matrix import audits, report, run_cell
from evals.scenarios.generator import generate_scenarios, load_scenario
from quellgeist.agent.loop import FALLBACK_ABSTENTION_PREFIXES, run_loop
from quellgeist.agent.providers import LiteLLMProvider

REPO = Path(__file__).parents[2]
FIXTURES_DIR = REPO / "evals" / "scenarios" / "fixtures"
ANCHOR = FIXTURES_DIR / "bad_deploy_0001.json"
ABSTENTION_PROBE_DIR = REPO / "evals" / "training" / "probes" / "abstention"


@pytest.fixture(autouse=True)
def _scrub_env(monkeypatch):
    for var in ("QG_SCENARIOS_DIR", "QG_MODEL", "QG_VERIFIER_MODEL", "QG_VERIFY"):
        monkeypatch.delenv(var, raising=False)


class FakeProvider:
    def __init__(self, scripted):
        self.scripted = list(scripted)

    def complete(self, messages):
        return self.scripted.pop(0)


def _diagnose(cause, evidence):
    return json.dumps(
        {
            "action": "diagnose",
            "diagnosis": {
                "summary": "s",
                "abstained": False,
                "hypotheses": [
                    {"cause": cause, "confidence": 0.9, "evidence": evidence}
                ],
            },
        }
    )


_CORRECT_SCRIPT = [
    json.dumps({"action": "query_logs", "args": {}}),
    json.dumps({"action": "get_recent_commits", "args": {}}),
    _diagnose(
        "bad deploy a1b2c3d broke auth.verify_token",
        [
            {"type": "log", "id": 2, "note": "first 500"},
            {"type": "commit", "sha": "a1b2c3d"},
        ],
    ),
]


def _one_scenario_dir(tmp_path: Path, source: Path = ANCHOR) -> Path:
    d = tmp_path / "scenarios"
    d.mkdir()
    shutil.copy(source, d / source.name)
    return d


# --------------------------------------------------------------------------- #
# run_cell
# --------------------------------------------------------------------------- #


def test_run_cell_writes_passes_and_summary(tmp_path, capsys):
    scenarios = _one_scenario_dir(tmp_path)
    out = tmp_path / "out"
    rc = run_cell.main(
        [
            "--cell-id",
            "smoke",
            "--scenarios",
            str(scenarios),
            "--passes",
            "2",
            "--out",
            str(out),
        ],
        provider=FakeProvider(_CORRECT_SCRIPT * 2),
    )
    assert rc == 0
    for k in (1, 2):
        lines = (out / f"pass_{k}.jsonl").read_text().splitlines()
        assert len(lines) == 1
        record = json.loads(lines[0])
        assert record["passed"] is True
        assert record["scenario_id"] == "bad_deploy_0001"
        assert record["steps"] == 3
        assert record["tool_calls"] == [
            ["query_logs", {}],
            ["get_recent_commits", {}],
        ]
        # broad, argument-free calls -> no speculative-filter violations
        assert record["audit"]["unobserved_args"] == []
        # non-holdout cell: the bank/timestamp audits must be OFF, not zero
        assert "bank_token_args" not in record["audit"]
        assert record["observation_chars"] > 0
    cell = json.loads((out / "cell.json").read_text())
    assert cell["aggregate"]["passed_per_pass"] == [1, 1]
    assert cell["aggregate"]["pass_rate_mean"] == 1.0
    assert cell["aggregate"]["fabricating_total"] == 0
    assert cell["holdout_audits"] is False
    assert cell["scenario_count"] == 1 and cell["passes"] == 2


def test_run_cell_clears_a_prior_longer_run(tmp_path):
    """A re-run with fewer passes must not leave a prior run's pass_N.jsonl or
    stale cell.json behind -- a measurement dir reflects exactly this run."""
    scenarios = _one_scenario_dir(tmp_path)
    out = tmp_path / "out"
    rc = run_cell.main(
        [
            "--cell-id",
            "c",
            "--scenarios",
            str(scenarios),
            "--passes",
            "3",
            "--out",
            str(out),
        ],
        provider=FakeProvider(_CORRECT_SCRIPT * 3),
    )
    assert rc == 0
    assert {p.name for p in out.glob("pass_*.jsonl")} == {
        "pass_1.jsonl",
        "pass_2.jsonl",
        "pass_3.jsonl",
    }
    rc = run_cell.main(
        [
            "--cell-id",
            "c",
            "--scenarios",
            str(scenarios),
            "--passes",
            "1",
            "--out",
            str(out),
        ],
        provider=FakeProvider(list(_CORRECT_SCRIPT)),
    )
    assert rc == 0
    assert {p.name for p in out.glob("pass_*.jsonl")} == {"pass_1.jsonl"}


def test_run_cell_speculative_filter_is_flagged(tmp_path):
    scenarios = _one_scenario_dir(tmp_path)
    out = tmp_path / "out"
    script = [
        # First call filters on values NO observation grounded — the DR-0019
        # baseline failure mode the audit exists to measure.
        json.dumps({"action": "query_logs", "args": {"route": "api/v1/orders"}}),
        json.dumps({"action": "get_recent_commits", "args": {}}),
        _diagnose(
            "bad deploy a1b2c3d broke auth.verify_token",
            [{"type": "log", "id": 2}, {"type": "commit", "sha": "a1b2c3d"}],
        ),
    ]
    rc = run_cell.main(
        [
            "--cell-id",
            "spec",
            "--scenarios",
            str(scenarios),
            "--passes",
            "1",
            "--out",
            str(out),
        ],
        provider=FakeProvider(script),
    )
    assert rc == 0
    record = json.loads((out / "pass_1.jsonl").read_text())
    assert record["audit"]["unobserved_args"] == [
        {"action": "query_logs", "arg": "route", "value": "api/v1/orders"}
    ]
    cell = json.loads((out / "cell.json").read_text())
    assert cell["aggregate"]["unobserved_arg_violations_total"] == 1


def test_verify_requires_pinned_verifier_model(tmp_path, capsys):
    scenarios = _one_scenario_dir(tmp_path)
    rc = run_cell.main(
        [
            "--cell-id",
            "x",
            "--scenarios",
            str(scenarios),
            "--verify",
            "--out",
            str(tmp_path / "out"),
        ],
        provider=FakeProvider([]),
    )
    assert rc == 2
    assert "QG_VERIFIER_MODEL" in capsys.readouterr().err


def test_verify_rejects_self_verification(tmp_path, capsys, monkeypatch):
    monkeypatch.setenv("QG_MODEL", "ollama_chat/tuned")
    monkeypatch.setenv("QG_VERIFIER_MODEL", "ollama_chat/tuned")
    scenarios = _one_scenario_dir(tmp_path)
    rc = run_cell.main(
        [
            "--cell-id",
            "x",
            "--scenarios",
            str(scenarios),
            "--verify",
            "--out",
            str(tmp_path / "out"),
        ],
        provider=FakeProvider([]),
    )
    assert rc == 2
    assert "verify itself" in capsys.readouterr().err


def test_empty_scenario_dir_is_a_config_error(tmp_path):
    empty = tmp_path / "empty"
    empty.mkdir()
    rc = run_cell.main(
        ["--cell-id", "x", "--scenarios", str(empty)],
        provider=FakeProvider([]),
    )
    assert rc == 2


def test_abstain_scoring_passes_deliberate_and_fails_fallback(tmp_path):
    probe_file = sorted(ABSTENTION_PROBE_DIR.glob("*.json"))[0]
    scenarios = _one_scenario_dir(tmp_path, probe_file)

    deliberate = json.dumps(
        {
            "action": "diagnose",
            "diagnosis": {
                "abstained": True,
                "abstention_reason": "no correlated deploy for the errors seen",
                "hypotheses": [],
            },
        }
    )
    out1 = tmp_path / "deliberate"
    rc = run_cell.main(
        [
            "--cell-id",
            "a",
            "--scenarios",
            str(scenarios),
            "--passes",
            "1",
            "--score",
            "abstain",
            "--out",
            str(out1),
        ],
        provider=FakeProvider([deliberate]),
    )
    assert rc == 0
    record = json.loads((out1 / "pass_1.jsonl").read_text())
    assert record["deliberate_abstained"] and record["passed"]
    cell = json.loads((out1 / "cell.json").read_text())
    assert cell["aggregate"]["abstain_recall_mean"] == 1.0

    # 8 garbage turns -> the loop's step-exhaustion fallback: abstained, but
    # NOT deliberately — must not count as recall (DR-0020 decision 6).
    out2 = tmp_path / "forced"
    rc = run_cell.main(
        [
            "--cell-id",
            "b",
            "--scenarios",
            str(scenarios),
            "--passes",
            "1",
            "--score",
            "abstain",
            "--out",
            str(out2),
        ],
        provider=FakeProvider(["not json"] * 8),
    )
    assert rc == 0
    record = json.loads((out2 / "pass_1.jsonl").read_text())
    assert record["abstained_final"] and not record["deliberate_abstained"]
    assert not record["passed"]


def test_holdout_cell_enables_bank_and_timestamp_audits(tmp_path):
    holdout_file = sorted((REPO / "evals" / "scenarios" / "holdout").glob("*.json"))[0]
    scenarios = _one_scenario_dir(tmp_path, holdout_file)
    out = tmp_path / "out"
    train_ts = sorted(audits.train_timestamps())[0]
    script = [
        # fixtures-bank route + an unobserved train-corpus timestamp as filter
        # args on a HOLDOUT trace: both DR-0020 §8 leak channels at once.
        json.dumps(
            {
                "action": "query_logs",
                "args": {"route": "/login", "since": train_ts},
            }
        ),
        json.dumps(
            {
                "action": "diagnose",
                "diagnosis": {
                    "abstained": True,
                    "abstention_reason": "nothing conclusive",
                    "hypotheses": [],
                },
            }
        ),
    ]
    rc = run_cell.main(
        [
            "--cell-id",
            "hold",
            "--scenarios",
            str(scenarios),
            "--passes",
            "1",
            "--out",
            str(out),
        ],
        provider=FakeProvider(script),
    )
    assert rc == 0
    record = json.loads((out / "pass_1.jsonl").read_text())
    assert record["audit"]["bank_token_args"] == [
        {
            "action": "query_logs",
            "arg": "route",
            "value": "/login",
            "tokens": ["/login"],
        }
    ]
    assert record["audit"]["train_ts_args"] == [
        {"action": "query_logs", "arg": "since", "value": train_ts}
    ]
    # holdout scenarios carry no core flag (cores are a fixtures-bank concept)
    assert "core_overlap" not in record


# --------------------------------------------------------------------------- #
# audits
# --------------------------------------------------------------------------- #


def _msgs(*turns):
    return [{"role": role, "content": content} for role, content in turns]


def test_unobserved_argument_values_semantics():
    speculative = _msgs(
        ("system", "s"),
        ("user", "trigger"),
        ("assistant", json.dumps({"action": "query_logs", "args": {"route": "/x"}})),
    )
    assert audits.unobserved_argument_values(speculative) == [
        {"action": "query_logs", "arg": "route", "value": "/x"}
    ]
    grounded = _msgs(
        ("system", "s"),
        ("user", "trigger"),
        ("assistant", json.dumps({"action": "query_logs", "args": {}})),
        ("user", 'Observation from query_logs: [{"route": "/x", "level": "ERROR"}]'),
        (
            "assistant",
            json.dumps(
                {"action": "query_logs", "args": {"route": "/x", "level": "ERROR"}}
            ),
        ),
    )
    assert audits.unobserved_argument_values(grounded) == []
    # None means "no filter" — never a violation; malformed turns are skipped
    # (they are schema violations, counted elsewhere).
    broad = _msgs(
        ("assistant", json.dumps({"action": "query_logs", "args": {"route": None}})),
        ("assistant", "not json at all"),
    )
    assert audits.unobserved_argument_values(broad) == []


def test_fixtures_bank_leak_flags_fixtures_not_holdout_vocab():
    call = _msgs(
        ("assistant", json.dumps({"action": "query_logs", "args": {"route": "/login"}}))
    )
    (violation,) = audits.fixtures_bank_argument_leaks(call)
    assert violation["tokens"] == ["/login"]
    holdout_vocab = _msgs(
        (
            "assistant",
            json.dumps({"action": "query_logs", "args": {"route": "/search"}}),
        )
    )
    assert audits.fixtures_bank_argument_leaks(holdout_vocab) == []


def test_train_timestamp_leak_requires_unobserved():
    ts = sorted(audits.train_timestamps())[0]
    unobserved = _msgs(
        ("assistant", json.dumps({"action": "query_logs", "args": {"since": ts}}))
    )
    assert audits.train_timestamp_argument_leaks(unobserved) == [
        {"action": "query_logs", "arg": "since", "value": ts}
    ]
    observed = _msgs(
        ("assistant", json.dumps({"action": "query_logs", "args": {}})),
        ("user", f'Observation from query_logs: [{{"ts": "{ts}"}}]'),
        ("assistant", json.dumps({"action": "query_logs", "args": {"since": ts}})),
    )
    assert audits.train_timestamp_argument_leaks(observed) == []


def test_core_overlap_reproduces_the_dr0020_numbers():
    """DR-0020 context 4, recomputed from the committed corpora: the fresh-
    seeded train split has 258 distinct semantic cores, and exactly 21 of the
    65 committed fixtures share an exact core with it. If either number moves,
    the corpus or the core definition changed — both are DR-visible events."""
    assert len(audits.train_cores()) == 258
    fixtures = [load_scenario(p) for p in sorted(FIXTURES_DIR.glob("*.json"))]
    assert len(fixtures) == 65
    overlapping = [s.id for s in fixtures if audits.core_overlaps_train(s)]
    assert len(overlapping) == 21
    # The hand-authored anchor carries strings the bank does not cover
    # (DR-0020) — it can never be core-overlapping.
    assert "bad_deploy_0001" not in overlapping


def test_holdout_cores_never_overlap_train():
    holdout = [
        load_scenario(p)
        for p in sorted((REPO / "evals" / "scenarios" / "holdout").glob("*.json"))
    ]
    assert holdout and not any(audits.core_overlaps_train(s) for s in holdout)


# --------------------------------------------------------------------------- #
# provider usage instrumentation
# --------------------------------------------------------------------------- #


def _ok(text="ok", usage=None):
    return SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content=text))],
        usage=usage,
    )


def test_provider_records_token_usage(monkeypatch):
    monkeypatch.setattr(
        litellm,
        "completion",
        lambda **k: _ok(usage=SimpleNamespace(prompt_tokens=11, completion_tokens=7)),
    )
    p = LiteLLMProvider(model="gemini/x")
    p.complete([{"role": "user", "content": "hi"}])
    p.complete([{"role": "user", "content": "again"}])
    assert len(p.calls) == 2
    assert p.calls[0].prompt_tokens == 11
    assert p.calls[0].completion_tokens == 7
    assert p.calls[0].latency_s >= 0.0


def test_provider_usage_none_when_backend_reports_nothing(monkeypatch):
    monkeypatch.setattr(litellm, "completion", lambda **k: _ok(usage=None))
    p = LiteLLMProvider(model="gemini/x")
    p.complete([{"role": "user", "content": "hi"}])
    assert p.calls[0].prompt_tokens is None
    assert p.calls[0].completion_tokens is None


def test_fallback_prefixes_match_the_loop():
    """The shared constant must keep matching the strings the loop actually
    synthesizes — the abstention probe and the matrix's deliberate-abstention
    scoring both depend on the prefix relationship."""
    result = run_loop(
        FakeProvider(["garbage"]),
        [],
        now="2026-05-01T08:00:00Z",
        max_steps=1,
    )
    assert result.diagnosis.abstained
    assert (result.diagnosis.abstention_reason or "").startswith(
        FALLBACK_ABSTENTION_PREFIXES
    )


# --------------------------------------------------------------------------- #
# report
# --------------------------------------------------------------------------- #


def _cell(cell_id, passed_per_pass, n, score_mode="gate", recall=None):
    passes = len(passed_per_pass)
    return {
        "cell_id": cell_id,
        "score_mode": score_mode,
        "model": "ollama_chat/m",
        "verify": True,
        "verifier_model": "ollama_chat/base",
        "scenarios_dir": "evals/scenarios/holdout",
        "scenario_count": n,
        "passes": passes,
        "per_pass": [
            {
                "pass": i + 1,
                "passed": p,
                "fabricating": 0,
                "deliberate_abstentions": 0,
                "unobserved_arg_violations": 0,
                "bank_token_violations": 0,
                "train_ts_violations": 0,
                "reasoner_tokens": 1000,
                "verifier_tokens": None,
                "reasoner_calls": 3 * n,
                "verifier_calls": 0,
                "wall_s": 60.0,
            }
            for i, p in enumerate(passed_per_pass)
        ],
        "aggregate": {
            "passed_per_pass": passed_per_pass,
            "pass_rate_mean": sum(passed_per_pass) / (n * passes),
            "passed_min": min(passed_per_pass),
            "passed_max": max(passed_per_pass),
            "fabricating_total": 0,
            "abstain_recall_mean": recall,
            "unobserved_arg_violations_total": 0,
            "bank_token_violations_total": 0,
            "train_ts_violations_total": 0,
            "core_overlapping": None,
            "core_fresh": None,
        },
    }


def test_report_renders_cells_and_claims_footer(tmp_path, capsys):
    a = tmp_path / "a.json"
    b = tmp_path / "b.json"
    a.write_text(json.dumps(_cell("tuned--holdout", [4, 5, 4], 16)))
    b.write_text(json.dumps(_cell("base--holdout", [0, 0, 0], 16)))
    rc = report.main([str(a), str(b), "--out", str(tmp_path / "r.md")])
    out = capsys.readouterr().out
    assert rc == 0
    assert "| tuned--holdout |" in out and "| base--holdout |" in out
    assert "4,5,4 /16" in out
    assert "out-of-vocabulary, in-structure" in out  # the pre-registered wording
    assert (tmp_path / "r.md").read_text()


def test_report_refuses_a_missing_cell(tmp_path, capsys):
    rc = report.main([str(tmp_path / "never_completed" / "cell.json")])
    assert rc == 1
    assert "never completed" in capsys.readouterr().err


def test_train_split_shape_matches_dr0020():
    """The train split the audits regenerate must stay the DR-0020 split:
    seed 20260703, 296 scenarios, class counts 96/128/72, train_ ids."""
    train = generate_scenarios("train")
    assert len(train) == 296
    by_class = {}
    for s in train:
        by_class[s.failure_class] = by_class.get(s.failure_class, 0) + 1
        assert s.id.startswith("train_")
    assert by_class == {
        "bad_deploy": 96,
        "config_error": 128,
        "resource_exhaustion": 72,
    }
