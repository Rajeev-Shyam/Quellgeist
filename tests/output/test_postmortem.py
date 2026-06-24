"""Tests for the postmortem renderer (Wave 1, Task 7)."""

from __future__ import annotations

from quellgeist.agent.schema import CommitRef, Diagnosis, Hypothesis, LogRef, MetricRef
from quellgeist.output.postmortem import render_postmortem, write_postmortem


def _diagnosis() -> Diagnosis:
    return Diagnosis(
        summary="Bad deploy a1b2c3d broke /login.",
        hypotheses=[
            Hypothesis(
                cause="deploy a1b2c3d broke auth.verify_token",
                confidence=0.9,
                evidence=[
                    LogRef(id=2, note="first 500"),
                    CommitRef(sha="a1b2c3d", note="touched auth.py"),
                ],
            ),
            Hypothesis(
                cause="unrelated config drift", confidence=0.2, evidence=[LogRef(id=5)]
            ),
        ],
        suggested_actions=["roll back a1b2c3d", "add a regression test"],
    )


def test_postmortem_includes_evidence_refs():
    out = render_postmortem(_diagnosis())
    assert "log #2" in out
    assert "commit a1b2c3d" in out
    assert "first 500" in out  # note rendered alongside the handle
    assert "touched auth.py" in out


def test_hypotheses_rendered_best_first():
    out = render_postmortem(_diagnosis())
    assert out.index("### 1.") < out.index("### 2.")
    assert "confidence: 0.90" in out


def test_summary_and_actions_present():
    out = render_postmortem(_diagnosis())
    assert "Bad deploy a1b2c3d broke /login." in out
    assert "roll back a1b2c3d" in out


def test_abstained_renders_reason_and_no_hypotheses():
    d = Diagnosis(
        abstained=True,
        abstention_reason="no deploy correlates with the errors",
        hypotheses=[],
    )
    out = render_postmortem(d)
    assert "Insufficient evidence" in out
    assert "no deploy correlates with the errors" in out
    assert "### 1." not in out
    assert "Root-cause hypotheses" not in out


def test_evidence_handles_all_three_types():
    d = Diagnosis(
        hypotheses=[
            Hypothesis(
                cause="c",
                confidence=0.5,
                evidence=[
                    LogRef(id=7),
                    CommitRef(sha="deadbee"),
                    MetricRef(id="cpu.usage"),
                ],
            )
        ]
    )
    out = render_postmortem(d)
    assert "log #7" in out
    assert "commit deadbee" in out
    assert "metric cpu.usage" in out


def test_write_postmortem_writes_file(tmp_path):
    p = write_postmortem(_diagnosis(), tmp_path / "pm.md")
    assert p.exists()
    assert "log #2" in p.read_text(encoding="utf-8")
