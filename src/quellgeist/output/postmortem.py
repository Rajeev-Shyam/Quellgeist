"""Postmortem renderer (Wave 1, Task 7; HTML target added Wave 5, Task 2).

Pure render of a Diagnosis into a templated postmortem -- deterministic and
model-free, so it is fully unit-testable. Evidence is rendered as its structured
handle (log #id / commit sha / metric id) PLUS its note, so each citation is both
human-readable and traceable back to the real signal (DR-0009). The abstained
case is rendered explicitly rather than as an empty report.

Both output formats (Markdown and HTML) render the SAME Diagnosis fields in the
same order and derive every citation from the single ``_render_evidence`` helper,
so the human-readable evidence handle is identical in either format. A parity test
(`tests/output/test_postmortem.py`) asserts the two never drift on the causes,
handles, and actions they show. Both are pure and deterministic -- no model call.

A timeline section is deliberately omitted in v1: a Diagnosis carries evidence
*handles*, not timestamps, so a faithful timeline needs the handles resolved back
to their source rows -- a small follow-on once the loop passes resolved evidence
through, not something to fabricate here.
"""

from __future__ import annotations

import html
from pathlib import Path
from typing import Literal

from quellgeist.agent.schema import Diagnosis, EvidenceRef


def _render_evidence(ref: EvidenceRef) -> str:
    if ref.type == "commit":
        head = f"commit {ref.sha}"
    elif ref.type == "metric":
        head = f"metric {ref.id}"
    else:  # log
        head = f"log #{ref.id}"
    return f"{head} — {ref.note}" if ref.note else head


def render_postmortem(
    diagnosis: Diagnosis, *, title: str = "Incident Postmortem"
) -> str:
    lines: list[str] = [f"# {title}", ""]

    if diagnosis.summary:
        lines += ["## Summary", diagnosis.summary, ""]

    if diagnosis.abstained:
        lines += [
            "## Insufficient evidence",
            "The agent did not find enough evidence to name a confident root cause.",
            "",
            f"Reason: {diagnosis.abstention_reason}",
            "",
        ]
        return "\n".join(lines).rstrip() + "\n"

    lines += ["## Root-cause hypotheses", ""]
    for i, h in enumerate(diagnosis.hypotheses, start=1):
        lines.append(f"### {i}. {h.cause}  (confidence: {h.confidence:.2f})")
        lines.append("")
        lines.append("Evidence:")
        lines += [f"- {_render_evidence(ref)}" for ref in h.evidence]
        lines.append("")

    if diagnosis.suggested_actions:
        lines += ["## Suggested actions", ""]
        lines += [f"- {a}" for a in diagnosis.suggested_actions]
        lines.append("")

    return "\n".join(lines).rstrip() + "\n"


_HTML_STYLE = """\
:root { color-scheme: light dark; }
* { box-sizing: border-box; }
body {
  font: 16px/1.6 -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
  max-width: 46rem; margin: 2rem auto; padding: 0 1rem;
  color: #1a1a1a; background: #fff;
}
h1 { font-size: 1.6rem; margin: 0 0 1rem; }
h2 { font-size: 1.2rem; margin: 2rem 0 .5rem; border-bottom: 1px solid #e5e5e5; padding-bottom: .25rem; }
h3 { font-size: 1.05rem; margin: 1.5rem 0 .25rem; }
.confidence { font-weight: 400; color: #666; font-size: .9em; }
.evidence-label { margin: .25rem 0; color: #444; }
ul { margin: .25rem 0 1rem; padding-left: 1.5rem; }
li { margin: .15rem 0; }
code, .handle { font-family: ui-monospace, SFMono-Regular, Menlo, monospace; }
.abstain { border-left: 4px solid #c99a00; padding-left: 1rem; }
@media (prefers-color-scheme: dark) {
  body { color: #e6e6e6; background: #16181c; }
  h2 { border-bottom-color: #2c2f36; }
  .confidence { color: #9aa0aa; }
  .evidence-label { color: #b8bcc4; }
}
"""


def _esc(text: str) -> str:
    """HTML-escape dynamic text (model-authored causes/notes/actions)."""
    return html.escape(text, quote=False)


def render_postmortem_html(
    diagnosis: Diagnosis, *, title: str = "Incident Postmortem"
) -> str:
    """Render a Diagnosis to a self-contained HTML page (Wave 5, Task 2).

    Deterministic and model-free like the Markdown renderer, and reading the same
    fields in the same order. The page is fully self-contained -- styles inlined,
    no external assets -- so it is portable as a single file. All dynamic text is
    HTML-escaped; evidence-handle text comes from the shared ``_render_evidence``.
    """
    body: list[str] = [f"<h1>{_esc(title)}</h1>"]

    if diagnosis.summary:
        body += ["<h2>Summary</h2>", f"<p>{_esc(diagnosis.summary)}</p>"]

    if diagnosis.abstained:
        body += [
            "<h2>Insufficient evidence</h2>",
            '<div class="abstain">',
            "<p>The agent did not find enough evidence to name a confident "
            "root cause.</p>",
            f"<p>Reason: {_esc(diagnosis.abstention_reason or '')}</p>",
            "</div>",
        ]
    else:
        body.append("<h2>Root-cause hypotheses</h2>")
        for i, h in enumerate(diagnosis.hypotheses, start=1):
            body.append(
                f"<h3>{i}. {_esc(h.cause)} "
                f'<span class="confidence">(confidence: {h.confidence:.2f})</span></h3>'
            )
            body.append('<p class="evidence-label">Evidence:</p>')
            body.append("<ul>")
            body += [
                f'<li class="handle">{_esc(_render_evidence(ref))}</li>'
                for ref in h.evidence
            ]
            body.append("</ul>")

        if diagnosis.suggested_actions:
            body.append("<h2>Suggested actions</h2>")
            body.append("<ul>")
            body += [f"<li>{_esc(a)}</li>" for a in diagnosis.suggested_actions]
            body.append("</ul>")

    return (
        "<!doctype html>\n"
        '<html lang="en">\n<head>\n<meta charset="utf-8">\n'
        '<meta name="viewport" content="width=device-width, initial-scale=1">\n'
        f"<title>{_esc(title)}</title>\n"
        f"<style>\n{_HTML_STYLE}</style>\n</head>\n<body>\n"
        + "\n".join(body)
        + "\n</body>\n</html>\n"
    )


def _resolve_format(
    path: str | Path, fmt: Literal["md", "html"] | None
) -> Literal["md", "html"]:
    """Pick the output format: explicit ``fmt`` wins; otherwise infer from the
    file extension (``.html``/``.htm`` -> HTML), defaulting to Markdown."""
    if fmt is not None:
        return fmt
    return "html" if Path(path).suffix.lower() in {".html", ".htm"} else "md"


def write_postmortem(
    diagnosis: Diagnosis,
    path: str | Path,
    *,
    title: str = "Incident Postmortem",
    fmt: Literal["md", "html"] | None = None,
) -> Path:
    """Write the postmortem to ``path``. Format is ``fmt`` if given, else inferred
    from the extension (``.html``/``.htm`` -> HTML, otherwise Markdown), so existing
    ``.md`` callers are unchanged."""
    p = Path(path)
    render = (
        render_postmortem_html
        if _resolve_format(path, fmt) == "html"
        else render_postmortem
    )
    p.write_text(render(diagnosis, title=title), encoding="utf-8")
    return p
