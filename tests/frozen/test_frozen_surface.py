"""Frozen-surface regression guard (v2 setup; DR-0023 / spec §The frozen surface).

This is the anti-drift keystone for all of v2. Editing any artifact below silently
invalidates the fine-tune's headline **0/16 → 12/16** comparison — the loop was
trained and measured against these exact strings, this exact schema field order, and
these exact corpora. v2 code must live in NEW modules and REUSE the frozen ones by
calling them; if a change makes one of these assertions fail, that is the signal to
stop and wrap-in-a-new-module rather than edit.

Covers F1 (tool description strings), F2 (evidence/diagnosis schema + field order),
F4 (observation + retry string format), and a light guard on F3 (committed corpora)
and F5/F6 (the eval path still serves the frozen descriptions). See
`docs/quellgeist-v2-session-brief.md` §1 for the do-not-touch list.
"""

from __future__ import annotations

import hashlib
import inspect
from pathlib import Path

from evals.run_evals import scenario_tools
from evals.scenarios.generator import load_scenario
from quellgeist.agent import loop as loop_mod
from quellgeist.agent.loop import _retry_msg
from quellgeist.agent.schema import (
    CommitRef,
    Diagnosis,
    Hypothesis,
    LogRef,
    MetricRef,
)
from quellgeist.servers.tools import (
    GET_RECENT_COMMITS_DESC,
    QUERY_LOGS_DESC,
    QUERY_METRICS_DESC,
)

_REPO = Path(__file__).parents[2]

# --- F1: tool description strings (byte-identical to the DR-0020 train/serve prompt).
# Golden computed 2026-07-09 from origin/main@0af7090; recompute via the brief §1
# snippet. If this changes, the fine-tune must be retrained — do NOT bless the new hash.
GOLDEN_TOOL_DESC_SHA256 = (
    "f4277d8f10d296c6ffcaf760905db67d96749a29d4719f9b65df1c28c08232e8"
)


def test_frozen_tool_descriptions_hash():
    concat = QUERY_LOGS_DESC + GET_RECENT_COMMITS_DESC + QUERY_METRICS_DESC
    got = hashlib.sha256(concat.encode()).hexdigest()
    assert got == GOLDEN_TOOL_DESC_SHA256, (
        "A frozen tool description changed — this re-skews the fine-tune (DR-0020). "
        "Wrap new behaviour in a new module; do NOT reword these strings."
    )


# --- F2: evidence + diagnosis schema field order (the model emits this exact JSON).
def test_frozen_schema_field_order():
    assert list(LogRef.model_fields) == ["type", "id", "note"]
    assert list(CommitRef.model_fields) == ["type", "sha", "note"]
    assert list(MetricRef.model_fields) == ["type", "id", "note"]
    assert list(Hypothesis.model_fields) == ["cause", "confidence", "evidence"]
    assert list(Diagnosis.model_fields) == [
        "summary",
        "abstained",
        "abstention_reason",
        "hypotheses",
        "suggested_actions",
    ]


# --- F4: observation + retry string format (byte-identical to training turns).
def test_frozen_retry_message_format():
    assert _retry_msg("ERR") == (
        "Your previous response was not a valid action: ERR. Respond with "
        "EXACTLY ONE JSON object -- a tool action or a diagnose action -- and "
        "nothing else."
    )


def test_frozen_observation_format():
    src = inspect.getsource(loop_mod.run_loop)
    assert 'f"Observation from {action}: {json.dumps(rows)}"' in src, (
        "The loop's observation string format changed — training turns used this "
        "exact template (DR-0020 decision 1). Do NOT edit it."
    )


# --- F3: committed corpora (the measured train/holdout split).
def test_frozen_corpora_counts():
    fixtures = sorted((_REPO / "evals/scenarios/fixtures").glob("*.json"))
    holdout = sorted((_REPO / "evals/scenarios/holdout").glob("*.json"))
    assert len(fixtures) == 65, "fixtures count changed — the measured suite is frozen"
    assert len(holdout) == 16, "holdout count changed — the reserved holdout is frozen"


def test_frozen_anchor_scenario_gold():
    s = load_scenario(str(_REPO / "evals/scenarios/fixtures/bad_deploy_0001.json"))
    keys = {(r.type, r.ref_id) for r in s.gold_evidence_refs}
    assert keys == {("log", 2), ("commit", "a1b2c3d")}, (
        "The hand-authored anchor scenario's gold changed — it is a fixed "
        "measurement reference (DR-0020)."
    )


# --- F5/F6: the eval path still imports and serves the frozen tool descriptions.
def test_frozen_eval_path_serves_frozen_descriptions():
    s = load_scenario(str(_REPO / "evals/scenarios/fixtures/bad_deploy_0001.json"))
    specs = {t.name: t.description for t in scenario_tools(s)}
    assert specs["query_logs"] == QUERY_LOGS_DESC
    assert specs["get_recent_commits"] == GET_RECENT_COMMITS_DESC
    assert specs["query_metrics"] == QUERY_METRICS_DESC
