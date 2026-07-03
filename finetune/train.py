"""QLoRA fine-tune of Qwen3-4B-Instruct-2507 on the DR-0020 corpus (Task 3).

GPU leg — run on the RTX 5060 (8GB) PoC or a free Colab/Kaggle T4 (the DR-0008
spike's precedent). ``finetune/prepare.py`` must have run first (it vendors
the chat template and audits the corpus this script trains on).

    python finetune/train.py --output runs/poc --max-steps 30   # pipeline smoke
    python finetune/train.py --output runs/full                 # the real run
    python finetune/train.py --output runs/full --export-only   # re-export GGUF

Everything DR-0020 §9 pins is encoded here: the vendored template (never the
mirror's), per-turn loss masking via the shared rendering module, no packing,
max_seq_len 4096, and a Q4_K_M GGUF export (the serving-realistic artifact the
comparison matrix evaluates — never the fp16 merge). Toolchain APIs (Unsloth
load/export signatures) were verified against upstream sources on 2026-07-02;
re-verify against the installed versions at kickoff, per the DR.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
HERE = Path(__file__).resolve().parent
BASE_MODEL = (
    "unsloth/Qwen3-4B-Instruct-2507"  # weights; template comes from the vendored file
)
TEMPLATE_PATH = HERE / "chat_template.jinja"
CORPUS = REPO / "evals" / "training" / "data" / "train.jsonl"
MAX_SEQ_LEN = 4096
SEED = 20260707


def load_features(tokenizer) -> list[dict[str, list[int]]]:
    from finetune.rendering import render_example

    examples = [json.loads(ln) for ln in CORPUS.read_text().splitlines()]
    return [render_example(tokenizer, e, max_seq_len=MAX_SEQ_LEN) for e in examples]


class _Collator:
    """Right-pad a batch; labels pad with -100 so padding never trains."""

    def __init__(self, pad_id: int) -> None:
        self.pad_id = pad_id

    def __call__(self, features):
        import torch

        width = max(len(f["input_ids"]) for f in features)

        def pad(seq, value):
            return seq + [value] * (width - len(seq))

        return {
            "input_ids": torch.tensor(
                [pad(f["input_ids"], self.pad_id) for f in features]
            ),
            "labels": torch.tensor([pad(f["labels"], -100) for f in features]),
            "attention_mask": torch.tensor(
                [pad(f["attention_mask"], 0) for f in features]
            ),
        }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", required=True)
    parser.add_argument("--max-steps", type=int, default=-1, help="-1 = full 2 epochs")
    parser.add_argument("--export-only", action="store_true")
    args = parser.parse_args()
    out = Path(args.output)
    out.mkdir(parents=True, exist_ok=True)

    from unsloth import FastLanguageModel  # lazy: GPU-only environment

    if args.export_only:
        # Re-export must load the TRAINED adapters — loading BASE_MODEL here
        # would silently export an untuned model labeled as the tuned artifact
        # and poison every comparison cell.
        assert (out / "lora").is_dir(), f"{out / 'lora'} missing — train first"
        load_from = str(out / "lora")
    else:
        load_from = BASE_MODEL
    model, tokenizer = FastLanguageModel.from_pretrained(
        model_name=load_from,
        max_seq_length=MAX_SEQ_LEN,
        load_in_4bit=True,
        dtype=None,  # auto: fp16 on T4, bf16 on newer
    )
    # DR-0020 §9: the vendored OFFICIAL template, never a mirror's (Unsloth's
    # Instruct-2507 mirror injects <think> handling the runtime never produces)
    template = TEMPLATE_PATH.read_text(encoding="utf-8")
    assert "<think>" not in template and "reasoning_content" not in template
    tokenizer.chat_template = template
    if tokenizer.pad_token_id is None:
        tokenizer.pad_token = "<|endoftext|>"
    assert tokenizer.pad_token_id is not None
    assert tokenizer.pad_token_id != tokenizer.eos_token_id

    if not args.export_only:
        model = FastLanguageModel.get_peft_model(
            model,
            r=16,
            lora_alpha=16,
            lora_dropout=0.0,
            target_modules=[
                "q_proj",
                "k_proj",
                "v_proj",
                "o_proj",
                "gate_proj",
                "up_proj",
                "down_proj",
            ],
            use_gradient_checkpointing="unsloth",
            random_state=SEED,
        )
        features = load_features(tokenizer)
        print(
            f"{len(features)} examples; max {max(len(f['input_ids']) for f in features)} tokens"
        )

        from transformers import Trainer, TrainingArguments

        trainer = Trainer(
            model=model,
            train_dataset=features,
            data_collator=_Collator(tokenizer.pad_token_id),
            args=TrainingArguments(
                output_dir=str(out / "checkpoints"),
                per_device_train_batch_size=1,
                gradient_accumulation_steps=16,  # effective batch 16
                num_train_epochs=2,
                max_steps=args.max_steps,
                learning_rate=2e-4,
                lr_scheduler_type="cosine",
                warmup_steps=10,
                logging_steps=5,
                optim="adamw_8bit",
                seed=SEED,
                save_strategy="no",
                report_to="none",
                # plain list-of-dicts dataset + custom collator: make the
                # no-column-surgery behaviour explicit
                remove_unused_columns=False,
                # no packing anywhere: one trajectory per sequence (DR-0020 §9)
            ),
        )
        trainer.train()
        model.save_pretrained(str(out / "lora"))
        tokenizer.save_pretrained(str(out / "lora"))

    # Export: LoRA-merge to 16-bit, then llama.cpp GGUF at Q4_K_M — the
    # serving-realistic artifact. Evaluate THIS, not the fp16 merge.
    model.save_pretrained_gguf(
        str(out / "gguf"), tokenizer, quantization_method="q4_k_m"
    )
    print(
        f"\nGGUF written under {out / 'gguf'} — next:\n"
        f"  python finetune/make_modelfile.py {out}\n"
        f"  ollama create quellgeist-qwen3-dr0020 -f {out / 'Modelfile'}\n"
        "then the serving checklist in finetune/README.md (template + eos checks)."
    )
    return 0


if __name__ == "__main__":
    sys.path.insert(0, str(REPO))
    raise SystemExit(main())
