"""A keyless demo diagnosis (Wave 5).

``quellgeist diagnose --demo`` renders this, deterministically and with **no model
or API key**, so a clean clone shows a real-shaped, evidence-cited postmortem on the
very first run. It is the gold-labelled diagnosis for the demo bad-deploy incident
(the same incident the README quickstart injects) — **not** live model output; a
live run produces the same shape from the model. Ships inside the package so the
CLI stays self-contained (no dependency on the eval corpora).
"""

from __future__ import annotations

from quellgeist.agent.schema import CommitRef, Diagnosis, Hypothesis, LogRef


def demo_diagnosis() -> Diagnosis:
    """The bad_deploy incident's gold diagnosis, cited by structured handles."""
    return Diagnosis(
        summary="Bad deploy a1b2c3d broke /login — a NoneType error in auth.verify_token.",
        hypotheses=[
            Hypothesis(
                cause=(
                    "Bad deploy a1b2c3d (10:01:50Z) refactored auth.py and introduced "
                    "a NoneType error in verify_token; /login 500s begin ~20s later at "
                    "10:02:12Z."
                ),
                confidence=1.0,
                evidence=[
                    LogRef(
                        id=2,
                        note="first /login 500 — TypeError 'NoneType' in auth.verify_token",
                    ),
                    CommitRef(
                        sha="a1b2c3d",
                        note="deploy: refactor token parsing — touched demo/app/auth.py",
                    ),
                ],
            )
        ],
        suggested_actions=[
            "Roll back deploy a1b2c3d",
            "Add a regression test exercising auth.verify_token with a missing token",
        ],
    )
