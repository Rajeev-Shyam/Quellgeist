# DR-0020 fine-tune runbook (Wave 4, Task 3)

The GPU legs are user-run (DR-0004: local PoC → free/cloud GPU); everything
here is prepared so each step is a paste-and-run. The pipeline encodes DR-0020
§9's constraints — vendored official chat template (no `<think>` scaffolding),
per-turn loss masking with `train:false` context turns never trained, no
packing, max_seq_len 4096, Q4_K_M GGUF as the evaluated artifact, hand-authored
Modelfile (never Ollama's template autodetect).

## 0. One-time setup (any machine with internet)

```bash
# from the repo root — build the corpus with the project interpreter
python -m evals.training.build          # writes evals/training/data/train.jsonl (316 examples)
python -m venv .venv-finetune
```

Activate the venv before `pip install` and every later `python finetune/...` step
(the GPU legs all run inside it):

- **Linux / macOS / Colab:** `source .venv-finetune/bin/activate`
- **Windows PowerShell:** `.\.venv-finetune\Scripts\Activate.ps1` — Windows creates `Scripts\`, never `bin/`

```bash
pip install -r finetune/requirements.txt
```

## 1. CPU preflight — run before any GPU minute

```bash
python finetune/prepare.py
```

This vendors the official `Qwen/Qwen3-4B-Instruct-2507` chat template to
`finetune/chat_template.jinja` (asserting it carries no thinking scaffolding),
renders + masking-audits all 316 examples with the exact code `train.py`
trains with, replaces the char-based length estimates with **real BPE
counts** (asserting everything fits 4096), and checks the Jinja-vs-Modelfile
template parity. It writes `finetune/render_report.json` — **commit the
vendored template + report** (they pin what the run used).

## 2. Pipeline smoke (local RTX 5060 8GB, or T4)

```bash
python finetune/train.py --output runs/poc --max-steps 30
```

~30 optimizer steps: the goal is loss visibly falling (the DR-0008 spike saw
0.41 → 0.05 over 30 steps on its corpus) and no OOM at batch 1 × grad-accum 16
× seq 4096. If Blackwell + bitsandbytes misbehaves locally, do everything on a
free Colab T4 instead — same commands after cloning the repo and running
steps 0–1 there.

## 3. The real run

```bash
python finetune/train.py --output runs/full     # 2 epochs ≈ 40 optimizer steps
```

Then export is automatic (Q4_K_M GGUF under `runs/full/gguf/`). LoRA adapters
land in `runs/full/lora/` — keep them (re-exports via `--export-only`).

## 4. Serve it

```bash
python finetune/make_modelfile.py runs/full
ollama create quellgeist-qwen3-dr0020 -f runs/full/Modelfile
ollama show --template quellgeist-qwen3-dr0020   # must be the ChatML template, NOT blank
```

Post-export checklist (each catches a silent-failure mode verified upstream):

- `ollama show --template` prints the ChatML template (autodetect miss = blank
  = policy collapse);
- GGUF metadata has `eos_token_id 151645` (`<|im_end|>`) — check with
  `python -c "from gguf import GGUFReader; r=GGUFReader('<file>.gguf'); print([f for f in r.fields if 'eos' in f])"`
  or `llama.cpp`'s `gguf-dump`;
- one-scenario smoke:
  `QG_MODEL=ollama_chat/quellgeist-qwen3-dr0020 uv run quellgeist diagnose` —
  the model should open with a broad `query_logs` (no invented `route`).

## 5. Measure (Task 4 — the matrix tooling is in `evals/matrix/`)

Every cell per DR-0020 §8: **pin the verifier explicitly** (never the
`QG_MODEL` fallback — the tuned model must not verify itself), **≥3 passes**
per cell (temp-0 local decoding is not run-to-run deterministic, DR-0019), and
run the probes alongside the corpora. Use the matrix cell runner — it
*enforces* the verifier pin (unpinned or self-identical = config error),
instruments real per-scenario token/call counts, and runs the DR-0020 §8
trace audits alongside the scores:

```bash
export QG_MODEL="ollama_chat/quellgeist-qwen3-dr0020"
export QG_VERIFIER_MODEL="ollama_chat/qwen3:4b-instruct-2507-q4_K_M"   # pinned: the BASE artifact
export PYTHONUTF8=1

# holdout (PRIMARY axis) and fixtures (secondary; auto-reported split into
# core-overlapping vs core-fresh), 3 passes each, verifier on:
uv run python -u -m evals.matrix.run_cell --cell-id tuned+verifier--holdout \
  --scenarios evals/scenarios/holdout --verify
uv run python -u -m evals.matrix.run_cell --cell-id tuned+verifier--fixtures \
  --verify

# probes (never trained on): abstain recall ≥ 90%; structure = reported, not gated
uv run python -u -m evals.matrix.run_cell --cell-id tuned+verifier--abstain-probe \
  --scenarios evals/training/probes/abstention --score abstain --verify
uv run python -u -m evals.matrix.run_cell --cell-id tuned+verifier--structure-probe \
  --scenarios evals/training/probes/structure --verify

# repeat the four cells with the BASE artifact in QG_MODEL (and any other
# model column), then merge everything into the comparison table:
uv run python -m evals.matrix.report runs/matrix/*/cell.json --out matrix-report.md
```

(The plain `evals.run_evals` / `run_abstention_probe` commands still work for
one-off smokes; the matrix runner is the same harness with the DR-0020 §8
riders enforced and the cost/audit columns recorded.)

Acceptance (DR-0019/DR-0020): holdout > 0/16 · fabrication 0 everywhere ·
abstention-probe recall ≥ 90% over the repeated passes. Claims use the DR's
pre-registered wording: the holdout is out-of-vocabulary, in-structure.

Windows notes from the baseline session: run the venv interpreter via
`.venv-finetune\Scripts\python.exe` (or activate with `Activate.ps1`). The bash
blocks above use bash idioms — in PowerShell, translate `export FOO=bar` to
`$env:FOO='bar'`, and inline `FOO=1 BAR=2 cmd` prefixes to separate `$env:`
assignments before the command. Set `PYTHONUTF8=1` for any redirected run;
disable the 5-minute AC sleep timer for long runs
(`powercfg /change standby-timeout-ac 0`).
