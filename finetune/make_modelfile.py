"""Write the tuned artifact's Modelfile — hand-authored, never autodetected.

DR-0020 §9: ``ollama create`` template autodetection fuzzy-matches the GGUF's
embedded template and, on a miss, silently ships NO template (requests then
render without ChatML framing and the tuned policy collapses). So the
Modelfile is explicit: a ChatML Go template that renders byte-identically to
the vendored training template (``prepare.py`` asserts the equivalence), the
context window pinned (Ollama silently front-truncates otherwise — truncation
can sever a cited handle's observation from the diagnose turn), both stop
markers, and ``repeat_penalty 1.0`` so greedy decode isn't distorted against
the repetitive JSON the fine-tune teaches (set the same for base-model cells:
apples-to-apples, DR-0020 §8).

    python finetune/make_modelfile.py runs/full [--gguf runs/full/gguf/<file>.gguf]
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

# Renders every message as "<|im_start|>{role}\n{content}<|im_end|>\n" plus the
# bare generation prompt — the official Qwen3-Instruct-2507 ChatML shape.
TEMPLATE = (
    "{{- range .Messages }}<|im_start|>{{ .Role }}\n"
    "{{ .Content }}<|im_end|>\n"
    "{{ end }}<|im_start|>assistant\n"
)

MODELFILE = '''FROM {gguf}
TEMPLATE """{template}"""
PARAMETER num_ctx 8192
PARAMETER stop "<|im_end|>"
PARAMETER stop "<|im_start|>"
PARAMETER repeat_penalty 1.0
'''


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("run_dir", help="training output dir (e.g. runs/full)")
    parser.add_argument(
        "--gguf", help="explicit GGUF path (default: newest under <run_dir>/gguf)"
    )
    args = parser.parse_args()
    run_dir = Path(args.run_dir)

    if args.gguf:
        gguf = Path(args.gguf)
    else:
        candidates = sorted((run_dir / "gguf").glob("*.gguf"))
        if not candidates:
            print(f"no .gguf under {run_dir / 'gguf'}", file=sys.stderr)
            return 1
        gguf = candidates[-1]

    path = run_dir / "Modelfile"
    path.write_text(
        MODELFILE.format(gguf=gguf.resolve(), template=TEMPLATE), encoding="utf-8"
    )
    print(f"wrote {path}")
    print(f"  ollama create quellgeist-qwen3-dr0020 -f {path}")
    print(
        "  ollama show --template quellgeist-qwen3-dr0020   # eyeball vs chat_template.jinja"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
