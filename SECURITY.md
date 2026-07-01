# Security Policy

Quellgeist is a Wave-1 work-in-progress portfolio project and is **not** yet
intended for production deployment. Even so, security matters: the MCP servers
it ships are a real attack surface once published (see DR-0005 in the
[ADR log](docs/quellgeist-adr-log.md)).

## Reporting a vulnerability

Please report security issues **privately** — not in a public issue or PR:

- Open a private advisory via **GitHub → Security → Report a vulnerability** on
  this repository

You can expect an acknowledgement within a few days. Please allow a reasonable
window to address the issue before any public disclosure.

## No secrets in the repository

- No API keys, tokens, or credentials are committed. Model access is configured
  at runtime via environment variables (`QG_MODEL` plus the provider's own key
  variables, which LiteLLM reads).
- The deterministic CI gate (lint + `pytest`) is **keyless** by design, so it
  runs on fork pull requests without exposing secrets. Live model-driven evals
  are key-gated and deferred to Wave 2 (DR-0012).
- Local environment files (`.env`, `.env.*`) and the runtime demo artifacts are
  git-ignored. Never commit a real key.

## The demo is a toy

The FastAPI service under `demo/` exists only to *produce signals to diagnose*.
It is intentionally minimal and has **no real authentication**: the `/login`
"token verification" is a simulated check that the chaos scripts flip into a
deliberate regression (`demo/app/auth.py`). Do not deploy the demo as a real
service or treat its endpoints as secure.

## Scope

The read-only tools (`query_logs`, `get_recent_commits`) only read local files —
a JSONL incident log and a JSON deploy log — resolved from environment-configured
paths; they never write, execute, or reach the network. A fuller threat model
and an MCP-scanner pass are planned for Wave 5 (DR-0005).
