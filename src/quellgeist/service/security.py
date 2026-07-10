"""Webhook signature verification (Wave 7, T7.3; DR-0023 decision 10).

HMAC-SHA256 over the RAW request body with a shared secret from the environment,
verified before any work is done. **Fail-closed:** an empty secret (misconfigured
server) or a missing/blank signature rejects the request — a public-repo service must
not accept unauthenticated triggers. Comparison is constant-time.
"""

from __future__ import annotations

import hashlib
import hmac
import time

_PREFIX = "sha256="


def sign(secret: str, body: bytes, timestamp: str | None = None) -> str:
    """The expected header value for ``body`` under ``secret`` (``sha256=<hex>``). When a
    ``timestamp`` is given it is bound into the signed material (``<ts>.<body>``), so a
    captured request cannot be replayed with a fresh timestamp (Wave 8 replay window).
    """
    signed = body if timestamp is None else timestamp.encode() + b"." + body
    digest = hmac.new(secret.encode(), signed, hashlib.sha256).hexdigest()
    return _PREFIX + digest


def verify_signature(
    secret: str, body: bytes, signature: str | None, timestamp: str | None = None
) -> bool:
    """True iff ``signature`` matches ``sign(secret, body, timestamp)``. Fail-closed on a
    missing secret or signature."""
    if not secret or not signature:
        return False
    return hmac.compare_digest(sign(secret, body, timestamp), signature)


def timestamp_within_skew(timestamp: str | None, max_skew_s: int) -> bool:
    """True iff ``timestamp`` (unix seconds) is within ``max_skew_s`` of now. Fail-closed on
    a missing or unparseable value — the caller only invokes this when the replay window is
    enabled, so a bad/absent timestamp must reject."""
    if not timestamp:
        return False
    try:
        ts = float(timestamp)
    except ValueError:
        return False
    return abs(time.time() - ts) <= max_skew_s
