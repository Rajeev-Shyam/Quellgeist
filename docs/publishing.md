# Publishing the MCP servers (Wave 5, Task 4)

Quellgeist ships three read-only stdio MCP servers. They publish to the **Official
MCP Registry** (metadata-only — it points at the PyPI package, it doesn't host it)
on each tagged release, via two tag-gated workflows that use OIDC and store **no
secrets**:

- [`publish-pypi.yml`](../.github/workflows/publish-pypi.yml) — builds and uploads
  the `quellgeist` package to PyPI via **PyPI Trusted Publishing**.
- [`publish-mcp.yml`](../.github/workflows/publish-mcp.yml) — publishes each
  `mcp/*/server.json` to the MCP Registry via **GitHub OIDC** (`mcp-publisher
  login github-oidc`). The `io.github.Rajeev-Shyam/*` namespace is authenticated
  by this repo's OIDC token.

Both fire only on a `v*` tag, so nothing publishes until you deliberately cut a
release. The MCP publish runs after PyPI because the registry verifies package
ownership by finding the `mcp-name:` markers (in [`README.md`](../README.md)) in
the **published PyPI README**.

### Supply-chain hardening (security review, DR-0005)

- **Third-party actions are SHA-pinned** across all workflows (not `@v4`/`@v5`/a
  branch), so a moved tag can't inject code into the OIDC-privileged release jobs.
  Keep them current with Dependabot (`.github/dependabot.yml`, `package-ecosystem:
  "github-actions"`) or `pin-github-action`, and update the `# vX.Y.Z` comments
  when you bump. **Exception:** `pypa/gh-action-pypi-publish` is a Docker action
  whose image is tagged by version/branch, not commit SHA, so it *cannot* be
  SHA-pinned (a SHA ref → nonexistent `:<sha>` image) — it's pinned to the
  pypa-maintained `release/v1` branch, with PyPI Trusted Publishing (OIDC) as the
  real trust anchor.
- **`mcp-publisher` is pinned to an exact version** (`MCP_PUBLISHER_VERSION` in
  `publish-mcp.yml`) and downloaded over TLS from the official
  `modelcontextprotocol/registry` release — the pinned version + authenticated
  HTTPS source is the baseline. (That release publishes no standard-named
  checksums asset, so we match the project's own documented install rather than
  fail on a guessed name.) Bump the version deliberately.
- Every workflow declares a **minimal top-level `permissions:`** (`contents: read`,
  plus `id-token: write` only in the two publish jobs).
- The **published sdist excludes `demo/` and `tests/`** so the toy auth never ships
  in a release artifact.

## One-time setup (before the first release)

1. **Claim the PyPI package name.** Confirm `quellgeist` is available (or pick a
   name) on <https://pypi.org>. Update `[project].name` in `pyproject.toml` and the
   `identifier` in each `mcp/*/server.json` if you change it.
2. **Configure PyPI Trusted Publishing** at
   <https://pypi.org/manage/account/publishing/>: add a *pending publisher* for
   owner `Rajeev-Shyam`, repo `Quellgeist`, workflow `publish-pypi.yml`,
   environment `pypi`. No token is stored anywhere.
3. **(Optional) create the `pypi` GitHub environment** in repo settings, matching
   the `environment: pypi` in the workflow, if you want a manual approval gate.

The MCP Registry side needs no setup: OIDC + the `io.github.*` namespace prove you
own this GitHub repo.

## Cutting a release

```bash
# 1. Bump the version in pyproject.toml AND in each mcp/*/server.json
#    (both the top-level "version" and packages[0].version).
# 2. Validate the manifests locally before tagging (recommended):
#    download mcp-publisher, then in each dir:
#      (cd mcp/logs && mcp-publisher publish --dry-run)   # confirm the schema
# 3. Tag and push:
git tag v0.1.0
git push origin v0.1.0
```

The tag triggers `publish-pypi.yml` (→ PyPI) then `publish-mcp.yml` (→ MCP
Registry). Watch both in the Actions tab.

> **Note on the run command:** each manifest runs the server as
> `uvx --from quellgeist <script>` via `runtimeArguments`. If `mcp-publisher`'s
> validator (schema `2025-10-17`) rejects that encoding, adjust
> `runtimeArguments`/`packageArguments` per the error and re-run `--dry-run` — the
> schema evolves, so treat the manifests as a validated-before-publish starting
> point.

## After publishing — claim the auto-crawled listings

The Registry entry is auto-crawled into the ecosystem directories. Claim each so
the listing shows "verified" and links back here:

- **Glama** — <https://glama.ai/mcp/servers> (sign in with GitHub, claim the repo).
- **PulseMCP** — <https://www.pulsemcp.com> (submit / claim; aim for the newsletter).
- **mcp.so** — <https://mcp.so> (claim the crawled entry).

Keep the security posture ([`SECURITY.md`](../SECURITY.md)) — read-only, scoped,
least-privilege, plus a clean `mcp-scan` report — front and centre in each listing;
it's the trust signal (DR-0005).
