"""Structured JSON logging for the agent/service process (Wave 7, T7.2).

Configures ``structlog`` to emit one JSON object per event with the bound correlation
ids (``incident_id``/``run_id``) merged in, so container logs are machine-parseable and
correlatable. Idempotent and process-scoped; the CLI does not call it (the CLI's stdout
is the postmortem — logging there would pollute the pipeable artifact), only the service
process does at startup.
"""

from __future__ import annotations

import structlog

_configured = False


def configure_logging(*, json_output: bool = True) -> None:
    """Install the JSON (or dev-console) structlog pipeline once per process."""
    global _configured
    if _configured:
        return
    renderer = (
        structlog.processors.JSONRenderer()
        if json_output
        else structlog.dev.ConsoleRenderer()
    )
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,  # incident_id/run_id
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso", utc=True),
            renderer,
        ],
        logger_factory=structlog.PrintLoggerFactory(),  # stdout, one line per event
    )
    _configured = True


def get_logger(name: str = "quellgeist.service") -> structlog.BoundLogger:
    return structlog.get_logger(name)
