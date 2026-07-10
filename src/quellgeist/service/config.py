"""Service configuration / dependencies (Wave 7, T7.3).

A single injectable config so ``create_app`` is testable with a temp DB, a temp signals
dir, and a scripted provider factory (no network, no real model). ``from_env`` builds the
production config; every secret is env-only (public repo, DR-0023 decision 10).
"""

from __future__ import annotations

import os
from collections.abc import Callable
from dataclasses import dataclass

from quellgeist.agent.providers import Provider


@dataclass
class ServiceConfig:
    db_path: str = "./var/quellgeist.db"
    signals_dir: str = "./var/signals"
    webhook_secret: str = ""  # empty => the service rejects ALL webhooks (fail-closed)
    num_workers: int = 2
    queue_maxsize: int = 1000  # bounded queue -> backpressure, not unbounded memory
    max_body_bytes: int = 1_000_000  # reject bodies larger than this (413)
    model: str = "ollama_chat/qwen3:4b-instruct-2507-q4_K_M"
    # sources the ingress snapshots per incident (the operator's live signal files)
    log_path: str = "demo/incident_logs.jsonl"
    deploy_path: str = "demo/deploy_log.json"
    metrics_path: str = "demo/metrics.json"
    # test seam: inject a scripted provider; None => a real LiteLLM provider
    provider_factory: Callable[[], Provider] | None = None

    # --- Wave 8: verifier (T8.0), notify (T8.1), operator surface + auth (T8.2), replay ---
    # Verifier is pinned SEPARATELY from the reasoner (DR-0016: the tuned model must not
    # verify itself). Empty / equal-to-`model` => no verifier => runs stay 'unverified' and
    # the review gate refuses to post them (fail-closed).
    verifier_model: str = ""  # QG_VERIFIER_MODEL
    verifier_provider_factory: Callable[[], Provider] | None = None  # test seam
    # Slack: the ONLY new outbound egress, scoped to this webhook URL (env-only). Empty =>
    # Slack posting is skipped (the HTML postmortem is still written).
    slack_webhook_url: str = ""  # QG_SLACK_WEBHOOK_URL
    slack_poster: Callable[[str, dict], None] | None = (
        None  # test seam; None => real httpx
    )
    html_dir: str = (
        "./var/postmortems"  # where an approved postmortem's HTML is written
    )
    # Operator surface auth: empty => the operator endpoints are fail-closed (rejected).
    operator_token: str = ""  # QG_OPERATOR_TOKEN
    # Replay bound: >0 => require a fresh X-Quellgeist-Timestamp within this many seconds.
    webhook_max_skew_s: int = 0  # QG_WEBHOOK_MAX_SKEW_S

    def __post_init__(self) -> None:
        # Fail fast on misconfiguration rather than starting a subtly-broken service:
        # num_workers<=0 -> a "healthy" pool that processes nothing; queue_maxsize<=0 ->
        # an asyncio.Queue that is silently UNBOUNDED (no backpressure); max_body_bytes<=0
        # -> every request rejected. Clear error at construction beats a silent runtime hole.
        if self.num_workers < 1:
            raise ValueError(f"num_workers must be >= 1, got {self.num_workers}")
        if self.queue_maxsize < 1:
            raise ValueError(f"queue_maxsize must be >= 1, got {self.queue_maxsize}")
        if self.max_body_bytes < 1:
            raise ValueError(f"max_body_bytes must be >= 1, got {self.max_body_bytes}")

    def make_provider(self) -> Provider:
        if self.provider_factory is not None:
            return self.provider_factory()
        from quellgeist.agent.providers import LiteLLMProvider

        return LiteLLMProvider(model=self.model)

    def make_verifier_provider(self) -> Provider | None:
        """Build the verifier provider, pinned SEPARATELY from the reasoner. DR-0016: the
        tuned model must NEVER verify itself, so only return a provider when a DISTINCT
        model (or a test factory) is configured; otherwise None -> the run is 'unverified'
        and the review gate refuses to post it (fail-closed)."""
        if self.verifier_provider_factory is not None:
            return self.verifier_provider_factory()
        if not self.verifier_model or self.verifier_model == self.model:
            return None
        from quellgeist.agent.providers import LiteLLMProvider

        return LiteLLMProvider(model=self.verifier_model)

    @classmethod
    def from_env(cls) -> ServiceConfig:
        def _int(name, default):
            try:
                return int(os.environ.get(name, default))
            except ValueError:
                return default

        return cls(
            db_path=os.environ.get("QG_DB_PATH", "./var/quellgeist.db"),
            signals_dir=os.environ.get("QG_SIGNALS_DIR", "./var/signals"),
            webhook_secret=os.environ.get("QG_WEBHOOK_SECRET", ""),
            num_workers=_int("QG_WORKERS", 2),
            queue_maxsize=_int("QG_QUEUE_MAXSIZE", 1000),
            max_body_bytes=_int("QG_MAX_BODY_BYTES", 1_000_000),
            model=os.environ.get(
                "QG_MODEL", "ollama_chat/qwen3:4b-instruct-2507-q4_K_M"
            ),
            log_path=os.environ.get("QG_LOG_PATH", "demo/incident_logs.jsonl"),
            deploy_path=os.environ.get("QG_DEPLOY_LOG", "demo/deploy_log.json"),
            metrics_path=os.environ.get("QG_METRICS_PATH", "demo/metrics.json"),
            verifier_model=os.environ.get("QG_VERIFIER_MODEL", ""),
            slack_webhook_url=os.environ.get("QG_SLACK_WEBHOOK_URL", ""),
            html_dir=os.environ.get("QG_HTML_DIR", "./var/postmortems"),
            operator_token=os.environ.get("QG_OPERATOR_TOKEN", ""),
            webhook_max_skew_s=_int("QG_WEBHOOK_MAX_SKEW_S", 0),
        )
