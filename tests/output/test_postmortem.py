"""Tests for the postmortem renderer (Wave 1, Task 7)."""

from __future__ import annotations

from quellgeist.agent.schema import CommitRef, Diagnosis, Hypothesis, LogRef, MetricRef
from quellgeist.output.postmortem import (
    render_postmortem,
    render_postmortem_html,
    write_postmortem,
)


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


# --- HTML render (Wave 5, Task 2) ---------------------------------------------


def test_html_is_self_contained_page():
    out = render_postmortem_html(_diagnosis(), title="Incident X")
    assert out.startswith("<!doctype html>")
    assert "<title>Incident X</title>" in out
    assert "<style>" in out and "</style>" in out  # styles inlined, no external asset
    assert "http://" not in out and "https://" not in out  # no remote references
    assert out.rstrip().endswith("</html>")


def test_html_renders_hypotheses_and_evidence():
    out = render_postmortem_html(_diagnosis())
    assert "deploy a1b2c3d broke auth.verify_token" in out
    assert "log #2 — first 500" in out  # shared evidence-handle text
    assert "commit a1b2c3d — touched auth.py" in out
    assert "confidence: 0.90" in out
    assert "roll back a1b2c3d" in out


def test_html_abstained_shows_reason_not_hypotheses():
    d = Diagnosis(
        abstained=True,
        abstention_reason="no deploy correlates with the errors",
        hypotheses=[],
    )
    out = render_postmortem_html(d)
    assert "Insufficient evidence" in out
    assert "no deploy correlates with the errors" in out
    assert "Root-cause hypotheses" not in out


def test_html_escapes_model_authored_text():
    d = Diagnosis(
        hypotheses=[
            Hypothesis(
                cause="<script>alert(1)</script> & co",
                confidence=0.5,
                evidence=[LogRef(id=1, note="<b>x</b>")],
            )
        ]
    )
    out = render_postmortem_html(d)
    assert "<script>alert(1)</script>" not in out  # never emitted raw
    assert "&lt;script&gt;alert(1)&lt;/script&gt; &amp; co" in out
    assert "&lt;b&gt;x&lt;/b&gt;" in out


def test_md_and_html_do_not_drift():
    """Both formats must show the same causes, evidence handles, and actions."""
    d = _diagnosis()
    md = render_postmortem(d)
    html_out = render_postmortem_html(d)
    for token in (
        "deploy a1b2c3d broke auth.verify_token",
        "unrelated config drift",
        "log #2 — first 500",
        "commit a1b2c3d — touched auth.py",
        "log #5",
        "roll back a1b2c3d",
        "add a regression test",
        "confidence: 0.90",
    ):
        assert token in md, f"{token!r} missing from markdown"
        assert token in html_out, f"{token!r} missing from html"


def test_write_postmortem_infers_html_from_extension(tmp_path):
    p = write_postmortem(_diagnosis(), tmp_path / "pm.html")
    body = p.read_text(encoding="utf-8")
    assert body.startswith("<!doctype html>")
    assert "deploy a1b2c3d broke auth.verify_token" in body


def test_write_postmortem_fmt_overrides_extension(tmp_path):
    # explicit fmt wins over a .txt extension
    p = write_postmortem(_diagnosis(), tmp_path / "pm.txt", fmt="html")
    assert p.read_text(encoding="utf-8").startswith("<!doctype html>")
