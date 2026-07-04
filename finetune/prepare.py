"""CPU preflight for the DR-0020 fine-tune — run this BEFORE any GPU minute.

``python finetune/prepare.py`` (from the repo root, in the training venv):

1. **Vendors the OFFICIAL chat template.** Downloads the
   ``Qwen/Qwen3-4B-Instruct-2507`` tokenizer, asserts its template carries no
   thinking scaffolding (``<think>``/``reasoning_content`` — Unsloth's mirror
   of this model adds some; the official template must not, DR-0020 §9), and
   writes it to ``finetune/chat_template.jinja``. Training always uses the
   vendored bytes, never whatever template a mirror shipped.
2. **Renders the full corpus** (``evals/training/data/train.jsonl`` — build it
   first with ``python -m evals.training.build``) through the exact
   rendering+masking code ``train.py`` will use, auditing every example's
   label spans from the outside.
3. **Replaces the char-based length estimates with real BPE counts** and
   asserts every example fits ``MAX_SEQ_LEN`` untruncated.
4. **Checks the Modelfile parity preconditions**: renders a sample
   conversation through the Jinja template and through a Python emulation of
   the ChatML Go template ``make_modelfile.py`` writes, asserting byte
   equality (the live cross-check against the served template is the
   runbook's ``ollama show --template`` step).

Writes ``finetune/render_report.json`` with the numbers. Exits non-zero on any
violation — fail closed, per the working agreements.
"""

from __future__ import annotations

import hashlib
import json
import statistics
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
HERE = Path(__file__).resolve().parent
MODEL_ID = "Qwen/Qwen3-4B-Instruct-2507"
TEMPLATE_PATH = HERE / "chat_template.jinja"
CORPUS = REPO / "evals" / "training" / "data" / "train.jsonl"
REPORT = HERE / "render_report.json"
MAX_SEQ_LEN = 4096
EOS_ID = 151645  # <|im_end|> — re-checked in the exported GGUF's metadata


def vendor_template(tokenizer) -> str:
    from finetune.rendering import THINKING_POISONS

    template = tokenizer.chat_template
    assert template, "tokenizer has no chat template"
    for poison in THINKING_POISONS:
        assert poison not in template, (
            f"chat template contains {poison!r} — this is a thinking-variant "
            "template (likely a mirror's); the runtime never produces think "
            "scaffolding and training on it is skew (DR-0020 §9)"
        )
    TEMPLATE_PATH.write_text(template, encoding="utf-8")
    return template


def emulate_go_template(messages: list[dict[str, str]]) -> str:
    """What make_modelfile.py's ChatML Go template renders for a conversation
    (without the trailing generation prompt): every message becomes
    ``<|im_start|>{role}\\n{content}<|im_end|>\\n``."""
    return "".join(
        f"<|im_start|>{m['role']}\n{m['content']}<|im_end|>\n" for m in messages
    )


def main() -> int:
    from transformers import AutoTokenizer  # lazy: heavy import

    from finetune.rendering import audit_example, strip_train_flags

    if not CORPUS.exists():
        print(
            f"{CORPUS} missing — run `python -m evals.training.build` first",
            file=sys.stderr,
        )
        return 1

    tokenizer = AutoTokenizer.from_pretrained(MODEL_ID)
    template = vendor_template(tokenizer)
    tokenizer.chat_template = template  # train with exactly the vendored bytes

    # tokenizer sanity (DR-0020 §9): no special-token auto-wrap (a BOS/framing
    # token would double against the vendored template); pad != eos so no
    # collator can mask the stop token out of the labels
    with_special = tokenizer("x", add_special_tokens=True).input_ids
    without_special = tokenizer("x", add_special_tokens=False).input_ids
    assert with_special == without_special, (
        f"tokenizer auto-adds special tokens ({with_special} vs "
        f"{without_special}) — would skew the vendored-template rendering"
    )
    assert tokenizer.eos_token_id == EOS_ID, tokenizer.eos_token_id
    assert tokenizer.pad_token_id is not None, "no pad token set"
    assert tokenizer.pad_token_id != tokenizer.eos_token_id, "pad == eos"

    examples = [json.loads(ln) for ln in CORPUS.read_text().splitlines()]
    lengths: list[int] = []
    for e in examples:
        lengths.append(audit_example(tokenizer, e, max_seq_len=MAX_SEQ_LEN))

    # Jinja-vs-Go-template parity on a real conversation shape
    sample = strip_train_flags(examples[0]["messages"])
    jinja = tokenizer.apply_chat_template(
        sample, tokenize=False, add_generation_prompt=False
    )
    go = emulate_go_template(sample)
    assert jinja == go, (
        "official Jinja render != ChatML Go-template render — fix "
        "make_modelfile.py's TEMPLATE before training (first divergence at "
        f"char {next(i for i, (a, b) in enumerate(zip(jinja, go, strict=False)) if a != b)})"
    )

    report = {
        "model_id": MODEL_ID,
        "examples": len(examples),
        "token_length": {
            "min": min(lengths),
            "median": int(statistics.median(lengths)),
            "max": max(lengths),
            "max_seq_len": MAX_SEQ_LEN,
        },
        "template_sha256": hashlib.sha256(template.encode()).hexdigest(),
        "template_bytes": len(template),
        "eos_token_id": EOS_ID,
    }
    REPORT.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2))
    print(
        f"\nOK: {len(examples)} examples rendered + masking-audited; template "
        f"vendored to {TEMPLATE_PATH.relative_to(REPO)}"
    )
    return 0


if __name__ == "__main__":
    sys.path.insert(0, str(REPO))
    raise SystemExit(main())
