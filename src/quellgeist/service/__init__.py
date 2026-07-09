"""quellgeist.service — async FastAPI ingress + operator HTML surface. SCAFFOLD (Wave 7–8).

Not yet implemented. Per [DR-0023](../../../docs/quellgeist-adr-log.md) decision 1
and the [v2 spec](../../../docs/quellgeist-v2-spec.md) §Components. The trigger is a
**signed inbound webhook**; accepted incidents are snapshotted (per-incident signal
isolation) and enqueued to a worker pool that runs the **synchronous** ``run_loop`` in
a thread executor — async lives only here, never in the frozen loop.

Planned surface:
- ``create_app(deps) -> FastAPI`` — app factory.
- ``POST /incidents`` (HMAC-signed → 202 + incident id; idempotent on delivery id),
  ``GET /healthz``, ``GET /incidents/{id}`` (HTML), ``POST /incidents/{id}/hint``,
  ``POST /incidents/{id}/review`` (approve|steer|reject).

Security (public repo): the webhook secret (``QG_WEBHOOK_SECRET``) is verified over the
raw body before any work; secrets are env-only. **Fail-closed:** a fabricated diagnosis
is surfaced for review, never posted (stricter than the CLI's warn-by-default).

Depends on ``store``, the job queue, ``observability``, ``orchestrator`` — not the loop
directly.
"""

from __future__ import annotations

__all__: list[str] = []
