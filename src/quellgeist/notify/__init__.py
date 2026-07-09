"""quellgeist.notify — emit a diagnosis to Slack + HTML. SCAFFOLD (Wave 8, T8.1).

Not yet implemented. Per [DR-0023](../../../docs/quellgeist-adr-log.md) decision 4
and the [v2 spec](../../../docs/quellgeist-v2-spec.md) §Components. Idempotent per
incident; **fail-closed** (a fabricated diagnosis is never posted).

Planned surface:
- ``post_slack(diagnosis, incident) -> None`` — idempotent; the Slack webhook URL is
  the ONLY new outbound egress in the codebase (``QG_SLACK_WEBHOOK_URL``, env-only).
- ``write_html(diagnosis, path) -> None`` — delegates to
  ``output.postmortem.render_postmortem_html`` (reused verbatim; already XSS-safe).

Reuses ``output/postmortem.py`` unchanged.
"""

from __future__ import annotations

__all__: list[str] = []
