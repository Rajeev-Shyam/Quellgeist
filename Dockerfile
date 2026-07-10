# Quellgeist v2 live incident-response service (Wave 9, T9.2; DR-0028 / DR-0023 dec. 10).
# Non-root, self-contained image. The same image runs either the agent service
# (`quellgeist.service:app`, the default CMD) or the toy demo service
# (`demo.app.main:app`, via compose's `command:`) — the demo stack is copied in but is
# NOT part of the published wheel (pyproject excludes it from the sdist).
#
# All secrets stay env-only (public repo): pass QG_WEBHOOK_SECRET / QG_OPERATOR_TOKEN /
# QG_SLACK_WEBHOOK_URL / provider keys at runtime (compose reads them from .env), never baked
# into a layer.

FROM python:3.12-slim

# Deterministic, quiet Python; no .pyc noise in the image.
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# Install the package first (its own layer) so dependency resolution is cached across
# source-only edits. pyproject references README.md + LICENSE, so both must be present.
COPY pyproject.toml README.md LICENSE ./
COPY src ./src
RUN pip install .

# The intentionally-breakable demo stack (toy service + chaos scripts) — for `compose up`.
COPY demo ./demo

# Runtime dirs the service owns: the SQLite store, per-incident snapshots, postmortem HTML,
# and the shared signal drop the demo writes and the agent reads.
ENV QG_DB_PATH=/data/quellgeist.db \
    QG_SIGNALS_DIR=/data/signals \
    QG_HTML_DIR=/data/postmortems \
    QG_LOG_PATH=/signals/incident_logs.jsonl \
    QG_DEPLOY_LOG=/signals/deploy_log.json \
    QG_METRICS_PATH=/signals/metrics.json

# Run as an unprivileged user (least privilege; SECURITY.md). Own the writable dirs.
RUN useradd --create-home --uid 10001 quell \
    && mkdir -p /data /signals \
    && chown -R quell:quell /app /data /signals
USER quell

EXPOSE 8000

# Liveness against the keyless /healthz probe (urllib raises on a non-2xx -> unhealthy).
HEALTHCHECK --interval=30s --timeout=3s --start-period=10s --retries=3 \
    CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://localhost:8000/healthz')"]

CMD ["uvicorn", "quellgeist.service:app", "--host", "0.0.0.0", "--port", "8000"]
