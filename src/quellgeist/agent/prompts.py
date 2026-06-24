"""Diagnosis prompts (Wave 1, Task 6).

The agent is a JSON-action ReAct loop. Every turn it emits exactly ONE JSON
object: either a tool call or a final diagnosis. Evidence is cited ONLY by the
structured handle the tools return -- a log row's integer ``id`` or a commit
``sha`` -- copied verbatim, with any human gloss in ``note`` (DR-0009). The handle
is what the Wave 2 fabrication check verifies; an invented id is the failure mode
this prompt exists to prevent.
"""

from __future__ import annotations

_TOOL_CALL_FORMAT = """\
To gather evidence, respond with a tool action (one per turn):

{"action": "<tool_name>", "args": {<arguments>}}

You then receive the tool's JSON result as an observation. Call tools as many
times as needed before diagnosing. Respond with EXACTLY ONE JSON object per turn
and nothing else -- no prose outside the JSON.
"""

_DIAGNOSIS_CONTRACT = """\
When you have enough evidence, respond with a diagnosis action:

{"action": "diagnose", "diagnosis": {
  "summary": "<one or two sentences>",
  "abstained": false,
  "abstention_reason": null,
  "hypotheses": [
    {
      "cause": "<the root cause in plain language>",
      "confidence": 0.0,
      "evidence": [
        {"type": "log", "id": <integer id from query_logs>, "note": "<why this supports the cause>"},
        {"type": "commit", "sha": "<sha from get_recent_commits>", "note": "<why>"}
      ]
    }
  ],
  "suggested_actions": ["<concrete next step>"]
}}

Hard rules:
- Each evidence item MUST include "type" ("log" or "commit") and the matching id
  field ("id" for log, "sha" for commit). Copy the id/sha EXACTLY as the tool
  returned it -- never invent, guess, or reformat one. Explanation goes in
  "note", never in place of the id/sha.
- confidence is a number from 0.0 to 1.0. Every hypothesis needs at least one
  evidence item. List hypotheses best-first.
- If the evidence does NOT support a confident cause, do NOT guess. Emit instead:
  {"action": "diagnose", "diagnosis": {"abstained": true,
   "abstention_reason": "<what is missing>", "hypotheses": []}}
  Abstaining with an empty hypotheses list is correct when signals are weak; a
  fabricated cause is the worst possible answer.
"""


def build_system_prompt(tool_lines: list[str]) -> str:
    tools_block = "\n".join(f"- {line}" for line in tool_lines)
    return (
        "You are an incident-triage agent. A production service is misbehaving. "
        "Investigate by calling tools to gather evidence (logs, recent deploys), "
        "then produce a root-cause diagnosis backed by cited evidence.\n\n"
        f"Available tools:\n{tools_block}\n\n"
        f"{_TOOL_CALL_FORMAT}\n"
        f"{_DIAGNOSIS_CONTRACT}"
    )


def user_trigger(now: str) -> str:
    return (
        f"An incident is occurring as of {now}. Investigate with the tools, then "
        "diagnose the most likely root cause with cited evidence."
    )
