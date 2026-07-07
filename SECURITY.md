# Security Policy

Quellgeist is a pre-v1 work-in-progress portfolio project and is **not** yet
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
  are key-gated and run out-of-band (not on PRs), so a fork PR never reaches a
  secret (DR-0012/DR-0015).
- Local environment files (`.env`, `.env.*`) and the runtime demo artifacts are
  git-ignored. Never commit a real key.

## The demo is a toy

The FastAPI service under `demo/` exists only to *produce signals to diagnose*.
It is intentionally minimal and has **no real authentication**: the `/login`
"token verification" is a simulated check that the chaos scripts flip into a
deliberate regression (`demo/app/auth.py`). Do not deploy the demo as a real
service or treat its endpoints as secure.

## Threat model (the published MCP servers)

Quellgeist ships three read-only MCP servers over stdio — `query_logs`
(`logs_mcp`), `get_recent_commits` (`commits_mcp`), and `query_metrics`
(`metrics_mcp`). They are the project's real published attack surface, so the
design holds four properties, each checkable against `src/quellgeist/servers/`:

- **Least privilege — read-only by construction.** Every tool only opens a file
  for reading (`open(..., "r")` / `Path.read_text()`) and filters the parsed rows
  in-process. Nothing in a server writes, deletes, executes, spawns a subprocess,
  or evaluates input — there is no state-mutating code path. So a compromised or
  prompt-injected model driving these tools cannot *change* anything; the worst it
  can do is read the canned signals it is already allowed to read.

- **Scoped access — one operator-configured file per server, no path from input.**
  Each server reads exactly one local file, chosen by an environment variable the
  operator sets (`QG_LOG_PATH`, `QG_DEPLOY_LOG`, `QG_METRICS_PATH`) with a
  repo-relative default. Crucially, **the tool arguments never influence which file
  is opened** — `since` / `level` / `route` / `name` / `limit` are filter
  predicates applied *after* the file is loaded. There is no path-traversal
  surface: a caller cannot point a tool at `/etc/passwd` or `../../secrets`,
  because callers do not supply paths at all.

- **No SSRF, no network.** The servers never open a socket, resolve a host, or
  fetch a URL — there is no network client anywhere in `servers/`. They read local
  files and return JSON. (The reasoner reaches a model via LiteLLM, but that is the
  agent process, configured by the operator — not something these servers expose or
  the tool inputs can steer.) With no outbound request and no URL input, there is no
  server-side-request-forgery surface.

- **Input validation — fail loud, never mis-filter.** The one structured input,
  `since`, is validated to a canonical zero-padded UTC form (`%Y-%m-%dT%H:%M:%SZ`)
  before use; a non-canonical timestamp is rejected with a clear error (which the
  agent loop turns into a schema-violation retry) rather than silently mis-comparing
  (`servers/filters.py::_require_canonical_ts`). The other filters are exact-equality
  checks against already-parsed values — there is no SQL, shell, or template into
  which a crafted `level` / `route` / `name` could inject. Malformed source files
  raise rather than silently dropping a row, because a dropped row would corrupt the
  evidence guarantee (DR-0009), not merely a display.

Two honest boundaries: the **demo** service under `demo/` is intentionally insecure
(see *The demo is a toy* above) and is not a published server; and the source files
the servers read are **trusted operator inputs**, not attacker-supplied — a hostile
*log file* is out of scope the same way a hostile `/etc/hosts` is out of scope for
any tool that reads local config.

## Security scanning

Two keyless scanners run in CI on every push and pull request, in their own
[`security` workflow](.github/workflows/security.yml) — kept separate from the
`ci.yml` merge gate so a newly-published advisory never blocks an unrelated merge:

- **bandit** — static analysis of the shipped package (`bandit -r src/`). Clean; the
  single low-severity hit (retry-backoff jitter via `random`, not a cryptographic
  use) is annotated `# nosec B311` at its call site.
- **pip-audit** — known-CVE scan of the locked dependency tree
  (`pip-audit --skip-editable`). Clean at the current lock.

Run them locally with:

```bash
uv sync --group security
uv run bandit -r src/
uv run pip-audit --skip-editable
```

### MCP-server scan (pre-release)

An MCP scanner inspects a *running* server's advertised tools (for tool-poisoning,
injected instructions, or over-broad scope), so it needs a live server rather than a
CI step. Before publishing, scan each stdio server with
[`mcp-scan`](https://github.com/invariantlabs-ai/mcp-scan), e.g.:

```bash
uvx mcp-scan@latest scan -- uv run python -m quellgeist.servers.logs_mcp
```

Repeat for `commits_mcp` and `metrics_mcp`, and keep the clean report with the
release (DR-0005).
