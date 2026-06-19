"""Token verification for the demo service.

Healthy by default. When a bad deploy is injected (demo/chaos/bad_deploy.py drops
the demo/.bad_deploy marker), verify_token takes a refactored path that lost its
None-guard: a missing token makes claims None and claims["sub"] raises TypeError —
the regression the agent must trace back to the deploy that touched this file.
"""

from __future__ import annotations

from pathlib import Path

_FLAG = Path(__file__).resolve().parents[2] / "demo" / ".bad_deploy"


def _bad_deploy_active() -> bool:
    return _FLAG.exists()


def _parse_claims(token: str | None) -> dict:
    if not token:
        return {}
    return {"sub": "demo-user"}


def _parse_claims_refactored(token: str | None):
    # Simulated deploy a1b2c3d: refactor returns None (not {}) for a missing token.
    if not token:
        return None
    return {"sub": "demo-user"}


def verify_token(token: str | None) -> dict:
    if _bad_deploy_active():
        claims = _parse_claims_refactored(token)
        try:
            return {"user": claims["sub"]}  # TypeError when claims is None
        except TypeError as e:
            # log captures the message, not the traceback — surface the location
            raise TypeError(f"{e} in auth.verify_token") from e
    claims = _parse_claims(token)
    return {"user": claims.get("sub", "anon")}
