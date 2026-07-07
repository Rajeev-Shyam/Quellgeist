# Launch copy (Wave 5, Task 5) — drafts

Ready-to-post drafts for each channel. **Post these yourself** once the repo is
public, the demo runs from a clean clone, and (optionally) the servers are in the
MCP Registry. Keep the honesty bar from the case studies: lead with the two-sided
result, name the gaps — never "beats the frontier at everything".

The one-liner everything reuses:

> **Quellgeist** — an incident-triage agent where every root-cause claim cites a
> real evidence handle, and the agent **abstains rather than guess**. A fine-tuned
> local 4B is frontier-competitive on this task at **$0, fully offline** — with the
> gaps stated honestly.

Headline numbers (all recomputed from logs; see the
[case study](case-studies/wave4-qwen-finetune.md)): base **0/16 → tuned 12/16**
holdout, **0 fabrication**, *cheaper* than the base; beats a 31B frontier stand-in
(10/16) on holdout capability at $0; adversarial abstention a **shared 6/12
ceiling** the frontier also hits; one class (`resource_exhaustion`) didn't transfer.

---

## GitHub release (v0.1.0)

**Title:** Quellgeist v0.1.0 — cite-or-abstain incident triage, frontier-competitive at $0

Quellgeist runs a legible JSON-action ReAct loop over three read-only MCP servers
(logs / deploys / metrics) and emits a structured diagnosis where every hypothesis
cites a real evidence handle — a log id, a commit sha, a metric name — copied
verbatim from a tool result. A fabricated citation is *deterministically rejected*,
and "insufficient evidence" is a first-class outcome.

**What's proven (measured, not asserted):**
- Fine-tuned local Qwen3-4B: **0/16 → 12/16** on a reserved holdout, **0
  fabrication**, and *cheaper* than the base model.
- **Frontier-competitive at $0, fully offline** — beats a 31B stand-in (10/16) on
  holdout capability and tool-discipline.
- Reliability is a **keyless deterministic CI gate**; the servers are read-only,
  scoped, least-privilege, scanned in CI (bandit + pip-audit) with a threat model.

**Honest limits:** adversarial abstention is a **shared 6/12 ceiling** (the 31B
frontier also lands 6/12); the `resource_exhaustion` class didn't transfer to the
fine-tune (the frontier passes it). Details in the case study.

Runs from a clean clone in ~30s (see the README quickstart). MIT.

---

## Hacker News — Show HN

**Title:** Show HN: Quellgeist – incident-triage agent that cites evidence or abstains

Hi HN. Quellgeist is a first-line incident-triage agent built around one idea: a
confidently-stated wrong root cause is the worst possible output, so every claim
must cite a **structured evidence handle** (a log id / commit sha / metric name)
the model actually saw, and the agent **abstains** when evidence is weak. Because
evidence is a checkable handle rather than prose, a fabricated citation is
*deterministically* rejected — not fuzzy-matched.

The part I found most interesting to measure: I fine-tuned a local 4B (Qwen3-4B,
QLoRA, served via Ollama) and compared it against its base and a 31B frontier
stand-in on a **held-out** scenario set with disjoint token banks. The tuned 4B
went from 0/16 to 12/16 with zero fabrication, came out *cheaper* than the base
(fewer tokens/calls), and beat the 31B on holdout capability — at $0 and fully
offline.

I tried hard not to oversell it. Two limits are real and in the write-up:
adversarial abstention tops out at 6/12 traps — and the 31B frontier hits the
*same* 6/12 ceiling, so it's a task-hardness finding, not a fine-tune regression;
and one failure class (`resource_exhaustion`) didn't transfer at all.

Everything is model-agnostic (swap the reasoner with one env var), the reliability
gate is keyless and deterministic, and the three evidence tools ship as read-only
MCP servers with a threat model + scanners in CI. Runs from a clean clone in ~30s.

Repo: <https://github.com/Rajeev-Shyam/Quellgeist> · Case study + numbers in the
README. Feedback welcome — especially on the abstention ceiling.

---

## r/mcp

**Title:** Quellgeist: three read-only MCP servers + an agent that cites evidence or abstains

Sharing a project built *around* MCP rather than being one more server. Quellgeist
is an incident-triage agent that orchestrates three read-only MCP servers
(`query_logs`, `get_recent_commits`, `query_metrics`) and produces a diagnosis
where every hypothesis cites a real handle from a tool result — fabricated
citations are deterministically rejected, and the agent abstains when evidence is
thin.

MCP-relevant bits you might care about:
- The servers are **read-only, scoped, least-privilege** — one operator-configured
  local file each, no network, no write path, tool args can't choose the path (no
  traversal). There's a threat model in SECURITY.md and `bandit` + `pip-audit` run
  in CI; an `mcp-scan` pass is part of the release checklist.
- Published to the **Official MCP Registry** via GitHub OIDC auto-publish (no
  stored secrets) — `uvx --from quellgeist quellgeist-logs-mcp`.
- The agent drives tools via a model-agnostic JSON-action loop, so it runs
  identically on a hosted frontier model or a local 4-bit Qwen.

Repo + threat model + registry entry: <https://github.com/Rajeev-Shyam/Quellgeist>

---

## r/LocalLLaMA

**Title:** Fine-tuned Qwen3-4B beats a 31B stand-in on a held-out triage task — at $0, fully offline (with honest gaps)

I built an incident-triage agent and used it to answer a specific question: can a
*local* fine-tuned 4B do frontier-grade work on a bounded task? Setup: Qwen3-4B,
QLoRA on a free Colab T4, served via Ollama with a hand-authored ChatML Modelfile;
compared against its own base and a 31B frontier stand-in on a **held-out** set
(disjoint token banks, never trained on), 3 scored passes per cell.

Results (all recomputed from raw logs):
- Base **0/16 → tuned 12/16** on holdout, **0 fabrication**, and *cheaper* than the
  base (~half the tokens, ~40% of the calls) because it stops flailing.
- The 31B stand-in scored **10/16** on the same holdout — the tuned 4B wins on
  capability and tool-discipline, at $0 and fully offline.
- Non-memorisation triangulated three ways (fixtures ≈ holdout; core-fresh ≥
  core-overlap; a structure probe with real culprit-not-newest reasoning).

Honest gaps (in the write-up): intrinsic abstention collapsed (a verifier is
load-bearing), the system's adversarial-abstention recall is 6/12 — and the 31B
frontier hits the *same* 6/12; and `resource_exhaustion` didn't transfer (the
frontier passes it). So: "a fine-tuned local 4B is frontier-competitive here", not
"a 4B beats a 31B at everything."

Modelfile/serving notes + full method: <https://github.com/Rajeev-Shyam/Quellgeist>

---

## Product Hunt

**Tagline:** Incident triage that cites its evidence — or admits it doesn't know.

**Description:** Quellgeist is an open-source AI agent for first-line incident
triage. It reads your logs, deploys, and metrics through read-only MCP servers and
returns ranked root-cause hypotheses where every claim cites a real evidence
handle — never a paraphrase. Fabricated citations are deterministically rejected,
and "insufficient evidence" is a first-class answer. A fine-tuned local 4B model
makes it frontier-competitive at $0 and fully offline. Model-agnostic, MIT,
security-reviewed, runs from a clean clone in 30 seconds.

**First comment:** Built this to scratch a specific itch: agents that
confidently invent root causes are worse than useless during an incident. So the
whole design makes fabrication *measurable* (cite structured handles, check them
deterministically) and makes abstention a feature. Happy to talk about the
fine-tune result and — especially — the abstention ceiling it still shares with a
31B frontier.

---

## PulseMCP newsletter pitch (email)

**Subject:** Quellgeist — a security-first, abstain-over-hallucinate MCP triage agent

Hi PulseMCP team — I just launched Quellgeist, an open-source incident-triage agent
built on three read-only MCP servers. The angle that may fit your readers: it's
*security-first* (read-only, scoped, least-privilege servers with a published
threat model + CI scanners) and *reliability-first* (every claim cites a checkable
evidence handle; the agent abstains rather than guess). It's model-agnostic, and a
fine-tuned local 4B makes it frontier-competitive at $0 and fully offline — with
the gaps documented honestly, not hand-waved.

Registry: `io.github.Rajeev-Shyam/quellgeist-*` · Repo:
<https://github.com/Rajeev-Shyam/Quellgeist>. Happy to provide anything you need.

---

## Pre-launch checklist

- [ ] Repo public; README quickstart verified from a clean clone.
- [ ] `ci` + `security` badges green on `main`.
- [ ] Servers published to the MCP Registry (`docs/publishing.md`); `mcp-scan`
      report captured.
- [ ] GitHub release cut (v0.1.0) with the notes above.
- [ ] Posts: HN → r/mcp → r/LocalLLaMA → Product Hunt (space them out); PulseMCP
      email sent.
- [ ] Numbers in every post match the case study verbatim (claims discipline).
