"""HTML postmortem output (Wave 8, T8.1).

Delegates to ``output.postmortem.render_postmortem_html`` (reused verbatim — already
self-contained and XSS-safe). ``render_html`` returns the page (used by the operator
GET endpoint to render on the fly); ``write_html`` persists it as a file artifact on
approval.
"""

from __future__ import annotations

from pathlib import Path

from quellgeist.agent.schema import Diagnosis
from quellgeist.output.postmortem import render_postmortem_html


def render_html(diagnosis: Diagnosis, *, title: str = "Incident Postmortem") -> str:
    return render_postmortem_html(diagnosis, title=title)


def write_html(
    diagnosis: Diagnosis, path: str | Path, *, title: str = "Incident Postmortem"
) -> Path:
    """Write the self-contained postmortem HTML to ``path`` (parent dirs created)."""
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(render_postmortem_html(diagnosis, title=title), encoding="utf-8")
    return p
