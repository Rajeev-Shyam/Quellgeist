from datetime import UTC, datetime

from quellgeist.agent.loop import ToolSpec, run_loop
from quellgeist.agent.providers import LiteLLMProvider
from quellgeist.servers.commits_mcp import get_recent_commits
from quellgeist.servers.logs_mcp import query_logs

tools = [
    ToolSpec(
        "query_logs",
        "Query structured incident logs; optional since/level/route filters; returns rows each with a stable integer id.",
        query_logs,
    ),
    ToolSpec(
        "get_recent_commits",
        "List recent deploys newest-first; optional since/limit; returns commits with sha, ts, msg, files.",
        get_recent_commits,
    ),
]

now = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
r = run_loop(LiteLLMProvider(), tools, now=now, max_steps=8)

print(
    "abstained:",
    r.diagnosis.abstained,
    "| steps:",
    r.steps,
    "| violations:",
    len(r.schema_violations),
)
for h in r.diagnosis.hypotheses:
    ev = [(e.type, getattr(e, "sha", getattr(e, "id", None))) for e in h.evidence]
    print(round(h.confidence, 2), "|", h.cause, "|", ev)
print("fabrication early-read (cited but unseen):", r.cited_but_unseen_handles())
print("tool calls:", r.tool_calls)
if r.schema_violations:
    print("violations:", r.schema_violations)
