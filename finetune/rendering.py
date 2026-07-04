"""Shared trajectory rendering + label masking (DR-0020 decision 9).

One function owns how a training example becomes ``input_ids``/``labels``:
``prepare.py`` runs it over the whole corpus as a CPU preflight (masking audit,
real-BPE length check) and ``train.py`` runs the SAME code to build the actual
training features — so what was audited is what is trained on.

Masking contract:
- loss ONLY on assistant turns, and only those without ``"train": false``
  (the loss-masked speculative/malformed context turns of recovery/retry
  examples must never become targets);
- the per-turn span starts AFTER the ``<|im_start|>assistant\\n`` header (the
  header frames every turn identically; the decision content is the target)
  and runs through the turn's ``<|im_end|>`` and its trailing newline, so the
  model learns to stop;
- spans are located by incremental prefix rendering, which is exact for the
  ChatML template (each message renders independently); a per-example
  prefix-consistency assert fails closed if the template ever stops being
  prefix-stable.
"""

from __future__ import annotations

from typing import Any

ASSISTANT_HEADER = "<|im_start|>assistant\n"
IM_END = "<|im_end|>"

# Thinking-scaffolding markers that must never appear in the vendored template
# (Unsloth's Instruct-2507 mirror injects them; the runtime never produces think
# output, so training on them is skew — DR-0020 §9). Shared by prepare.py and
# train.py so the two guards cannot drift.
THINKING_POISONS = ("<think>", "reasoning_content", "enable_thinking")


def strip_train_flags(messages: list[dict[str, Any]]) -> list[dict[str, str]]:
    """The template must never see the masking metadata."""
    return [{"role": m["role"], "content": m["content"]} for m in messages]


def _prefix_ids(tokenizer, messages: list[dict[str, str]]) -> list[int]:
    # return_dict=False pins the bare list[int] return the span arithmetic
    # below requires: transformers 5.x defaults apply_chat_template(tokenize=
    # True) to a BatchEncoding, 4.x returned the flat id list. The token ids
    # are identical either way — only the wrapper changed.
    return tokenizer.apply_chat_template(
        messages, tokenize=True, add_generation_prompt=False, return_dict=False
    )


def render_example(
    tokenizer, example: dict[str, Any], *, max_seq_len: int
) -> dict[str, list[int]]:
    """Tokenize one trajectory and build its loss labels. Fails closed on any
    deviation from the expected template shape."""
    messages = strip_train_flags(example["messages"])
    ident = example["id"]
    for m in example["messages"]:
        assert "<|im_" not in m["content"] and "<think>" not in m["content"], ident

    full_ids = _prefix_ids(tokenizer, messages)
    assert len(full_ids) <= max_seq_len, (
        f"{ident}: {len(full_ids)} tokens exceeds max_seq_len={max_seq_len} — "
        "a truncated diagnose turn would train the malformed-output failure "
        "the loop retries on (DR-0020 decision 9)"
    )
    header_ids = tokenizer(ASSISTANT_HEADER, add_special_tokens=False).input_ids
    assert tokenizer.decode(header_ids) == ASSISTANT_HEADER

    labels = [-100] * len(full_ids)
    trained_spans = 0
    for i, message in enumerate(example["messages"]):
        if message["role"] != "assistant":
            continue
        start = len(_prefix_ids(tokenizer, messages[:i]))
        end = len(_prefix_ids(tokenizer, messages[: i + 1]))
        # prefix-consistency: the template must render messages independently,
        # or span arithmetic silently trains the wrong tokens
        assert full_ids[:end] == _prefix_ids(tokenizer, messages[: i + 1]), ident
        assert (
            tokenizer.decode(full_ids[start : start + len(header_ids)])
            == ASSISTANT_HEADER
        ), f"{ident}: assistant turn {i} does not start with the ChatML header"
        if message.get("train") is False:
            continue  # masked context turn: stays -100 end to end
        span = slice(start + len(header_ids), end)
        labels[span] = full_ids[span]
        decoded = tokenizer.decode(full_ids[span])
        assert (
            decoded.startswith(message["content"]) and IM_END in decoded
        ), f"{ident}: trained span for turn {i} is not content+{IM_END}"
        trained_spans += 1
    assert trained_spans >= 1, f"{ident}: nothing to train"
    return {
        "input_ids": full_ids,
        "labels": labels,
        "attention_mask": [1] * len(full_ids),
    }


def audit_example(tokenizer, example: dict[str, Any], *, max_seq_len: int) -> int:
    """Render and re-verify the masking from the OUTSIDE: decode every trained
    label span and check it against the example's unmasked assistant contents.
    Returns the example's token length (for the corpus report)."""
    feats = render_example(tokenizer, example, max_seq_len=max_seq_len)
    ids, labels = feats["input_ids"], feats["labels"]
    spans: list[str] = []
    current: list[int] = []
    for tok, lab in zip(ids, labels, strict=True):
        if lab != -100:
            current.append(tok)
        elif current:
            spans.append(tokenizer.decode(current))
            current = []
    if current:
        spans.append(tokenizer.decode(current))
    expected = [
        m["content"]
        for m in example["messages"]
        if m["role"] == "assistant" and m.get("train") is not False
    ]
    assert len(spans) == len(expected), example["id"]
    for got, want in zip(spans, expected, strict=True):
        assert got.startswith(want), (example["id"], want[:60])
        tail = got[len(want) :]
        assert tail.rstrip("\n") == IM_END, (example["id"], repr(tail))
    return len(ids)
