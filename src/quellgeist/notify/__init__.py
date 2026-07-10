"""quellgeist.notify — emit a diagnosis to Slack + HTML (Wave 8, T8.1).

Per [DR-0023](../../../docs/quellgeist-adr-log.md) decision 4 and the
[v2 spec](../../../docs/quellgeist-v2-spec.md) §Components. **Fail-closed:** ``publish``
refuses to emit a fabricated diagnosis, and the review gate only ever passes it the
post-verifier diagnosis (an unverified run is never posted). Reuses
``output/postmortem.render_postmortem_html`` unchanged; the Slack webhook URL is the only
new outbound egress (env-only).
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from quellgeist.agent.schema import Diagnosis
from quellgeist.notify.html import render_html, write_html
from quellgeist.notify.slack import build_payload, post_slack

if TYPE_CHECKING:  # avoid a runtime import cycle (service.app imports notify)
    from quellgeist.service.config import ServiceConfig

__all__ = [
    "PublishRefused",
    "publish",
    "render_html",
    "write_html",
    "build_payload",
    "post_slack",
]


class PublishRefused(Exception):
    """Raised when the fail-closed guard blocks a post (e.g. a fabricated diagnosis)."""


def publish(
    diagnosis: Diagnosis,
    *,
    incident_id: str,
    fabricated: bool,
    config: ServiceConfig,
    page_url: str | None = None,
) -> dict:
    """Fail-closed publish of a VERIFIED diagnosis: write the postmortem HTML artifact and
    (if a webhook is configured) post to Slack. Refuses a fabricated diagnosis. ``diagnosis``
    MUST be the post-verifier diagnosis — the gate never calls this for an unverified run.
    """
    if fabricated:
        raise PublishRefused("refusing to publish a fabricated diagnosis (fail-closed)")
    html_path = write_html(
        diagnosis,
        Path(config.html_dir) / f"{incident_id}.html",
        title=f"Incident {incident_id} — Postmortem",
    )
    slack_posted = False
    if config.slack_webhook_url:
        post_slack(
            diagnosis,
            incident_id=incident_id,
            webhook_url=config.slack_webhook_url,
            poster=config.slack_poster,
            page_url=page_url,
        )
        slack_posted = True
    return {"html_path": str(html_path), "slack_posted": slack_posted}
