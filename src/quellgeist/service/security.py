"""Webhook signature verification (Wave 7, T7.3; DR-0023 decision 10).

HMAC-SHA256 over the RAW request body with a shared secret from the environment,
verified before any work is done. **Fail-closed:** an empty secret (misconfigured
server) or a missing/blank signature rejects the request — a public-repo service must
not accept unauthenticated triggers. Comparison is constant-time.
"""

from __future__ import annotations

import hashlib
import hmac

_PREFIX = "sha256="


def sign(secret: str, body: bytes) -> str:
    """The expected header value for ``body`` under ``secret`` (``sha256=<hex>``)."""
    digest = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    return _PREFIX + digest


def verify_signature(secret: str, body: bytes, signature: str | None) -> bool:
    """True iff ``signature`` matches ``sign(secret, body)``. Fail-closed on a missing
    secret or signature."""
    if not secret or not signature:
        return False
    return hmac.compare_digest(sign(secret, body), signature)
