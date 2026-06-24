# Contributing to Quellgeist

Thanks for your interest! Quellgeist is built in **rolling waves** — only the
current wave is implemented in detail, and scope is kept deliberately tight.
Please skim the wave model below before proposing changes.

## Development setup

The project uses [uv](https://docs.astral.sh/uv/) (with hatchling) and targets
Python 3.12+.

```bash
uv sync                              # create the venv and install deps + dev tools
uv run pytest tests/ -q              # run the test suite
uv run pre-commit run --all-files    # ruff (lint + import sort) + black + hooks
```

Optionally install the git hook so the checks run on every commit:

```bash
uv run pre-commit install
```

## Conventions

- **Style:** `ruff` (rules `E,F,I,B,UP`; `E501` ignored) and `black`, both at 88
  columns. Every module starts with `from __future__ import annotations` and
  uses full type hints.
- **Docstrings** reference the relevant decision record (`DR-xxxx`) wherever a
  design choice is load-bearing — see [`docs/quellgeist-adr-log.md`](docs/quellgeist-adr-log.md).
- **Commits** follow [Conventional Commits](https://www.conventionalcommits.org/)
  (`feat:`, `fix:`, `refactor:`, `chore:`, `docs:`, `ci:` …), logically grouped.
- **Tests:** add tests for new behaviour; never weaken or delete an existing test
  to make a change pass. The deterministic `pytest` gate is the reliability
  contract.

## The wave model

Work is sequenced into waves (see
[`docs/quellgeist-plan-rolling-wave.md`](docs/quellgeist-plan-rolling-wave.md)):

- **Wave 1 (current):** thin vertical slice — bad-deploy diagnosis end-to-end.
  The loop *measures* citation fidelity (`cited_but_unseen`); it does not yet
  enforce it.
- **Wave 2:** reliability core — verifier pass, deterministic fabrication check,
  abstention, and an LLM-as-judge validated against a human gold subset.
- **Wave 3+:** breadth (more failure classes + metrics), the cost/fine-tune
  study, then polish and launch.

Please keep PRs within the current wave's scope; deferred features carry
`NotImplementedError` stubs on purpose. To tackle a future wave, open an issue
to discuss first.
