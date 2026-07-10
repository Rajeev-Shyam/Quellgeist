"""Slack emitter (Wave 8, T8.1; DR-0023 decision 4).

Posts a compact incident summary to a Slack incoming-webhook URL — the **only** new
outbound egress in the codebase, scoped to that URL (env-only, ``QG_SLACK_WEBHOOK_URL``).
The HTTP call is injectable (``poster``) so the deterministic gate never touches the
network. Idempotency and the fail-closed guard are the caller's job (``notify.publish``
refuses a fabricated diagnosis; the review gate posts once per incident).
"""

from __future__ import annotations

from collections.abc import Callable

from quellgeist.agent.schema import Diagnosis

# A poster takes (webhook_url, json_payload) and performs the POST (or records it, in tests).
SlackPoster = Callable[[str, dict], None]


def build_payload(
    diagnosis: Diagnosis, *, incident_id: str, page_url: str | None = None
) -> dict:
    """Build a Slack message payload from the (verified) diagnosis. Text-only for maximum
    webhook compatibility; the operator HTML page carries the full detail."""
    if diagnosis.abstained:
        headline = "*abstained* — insufficient verified evidence"
        detail = diagnosis.abstention_reason or ""
    else:
        top = diagnosis.hypotheses[0] if diagnosis.hypotheses else None
        headline = (
            f"*root cause* — {' '.join(top.cause.split())} "
            f"(confidence {top.confidence:.2f})"
            if top
            else "*diagnosed*"
        )
        detail = diagnosis.summary or ""
    lines = [f":rotating_light: Incident `{incident_id}` — {headline}"]
    if detail:
        lines.append(detail)
    if page_url:
        lines.append(f"<{page_url}|Open the postmortem>")
    return {"text": "\n".join(lines)}


def _httpx_post(webhook_url: str, payload: dict) -> None:
    import httpx

    resp = httpx.post(webhook_url, json=payload, timeout=10.0)
    resp.raise_for_status()


def post_slack(
    diagnosis: Diagnosis,
    *,
    incident_id: str,
    webhook_url: str,
    poster: SlackPoster | None = None,
    page_url: str | None = None,
) -> None:
    """POST the diagnosis summary to ``webhook_url`` (via ``poster`` or real httpx)."""
    payload = build_payload(diagnosis, incident_id=incident_id, page_url=page_url)
    (poster or _httpx_post)(webhook_url, payload)
