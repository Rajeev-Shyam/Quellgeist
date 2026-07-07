## What & why

<!-- What does this change, and why? Link the issue / ADR (DR-00xx) if relevant. -->

## Wave / scope

<!-- Which wave does this belong to? Keep PRs within the current wave's scope
     (see docs/quellgeist-plan-rolling-wave.md). -->

## Checklist

- [ ] `uv run pre-commit run --all-files` is clean (ruff + black + hooks)
- [ ] `uv run pytest tests/` passes; new behavior has tests
- [ ] Claims discipline: any quoted number is recomputed from its raw log and
      labelled (directional / single-pass where applicable)
- [ ] No secrets committed; read-only/least-privilege posture preserved for the
      MCP servers
- [ ] Docs updated if behavior/flags/claims changed
