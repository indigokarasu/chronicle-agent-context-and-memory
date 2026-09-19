"""Measure the chars/token ratio of a corpus (stdlib only) — A10.

Usage: /usr/bin/python3 scripts/measure_chars_per_token.py <corpus.json> [...]

This is the standing basis for `engine.embeddings._CHARS_PER_TOKEN` — the
ESTIMATE — and for judging any safety margin stacked on top of it; rerun it
when either is questioned rather than re-deriving the argument.

A10b separates the two: the estimate is the tree's best guess at the true
ratio, and each call site adds a NAMED margin sized for its own failure mode
(engine.embeddings.MARGINS). This script measures the estimate's basis and then
reports what each registered margin costs in over-estimation, so a margin can
never be justified by "it feels safer" alone.

A10 asks for the estimator constant to be justified against real tokenizer
behaviour. No BPE tokenizer is installed (tiktoken / transformers / tokenizers
/ sentencepiece all absent) and no network or paid API is permitted, so this
measures the two quantities that ARE observable offline:

  chars/word   -- whitespace words.
  chars/atom   -- "atoms" = maximal runs of [A-Za-z0-9] plus each single
                  non-alphanumeric, non-space char.

Atoms are the granularity a byte-level BPE (GPT-2 / cl100k / Llama) starts
from: its pre-tokenizer splits at exactly these boundaries and then merges
BYTES WITHIN a piece, absorbing the leading space into the following token.
So every atom costs AT LEAST one token, and a long or rare atom costs more:

    tokens >= atoms      =>      true chars/token <= chars/atom

i.e. chars/atom is an UPPER BOUND on the corpus's true chars/token ratio.
Any estimator constant strictly below that bound therefore OVER-estimates the
true token count -- which is the safe direction for a budget cap.
"""
import json
import os
import re
import sys

ATOM = re.compile(r"[A-Za-z0-9]+|[^A-Za-z0-9\s]")


def walk(o, out):
    if isinstance(o, str):
        out.append(o)
    elif isinstance(o, dict):
        for v in o.values():
            walk(v, out)
    elif isinstance(o, list):
        for v in o:
            walk(v, out)


for path in sys.argv[1:]:
    with open(path) as f:
        data = json.load(f)
    texts = []
    walk(data, texts)
    blob = "\n".join(t for t in texts if len(t) > 40)   # prose only, not ids/keys
    chars, words, atoms = len(blob), len(blob.split()), len(ATOM.findall(blob))
    cpa = chars / max(1, atoms)
    print("%-20s chars=%9d words=%8d atoms=%9d | chars/word=%.3f "
          "chars/atom=%.3f (upper bound on true chars/token)"
          % (os.path.basename(path), chars, words, atoms,
             chars / max(1, words), cpa))
    # Read the estimate and the margins from the ONE place they live, so this
    # script can never drift into being a second opinion about either.
    sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
    from engine.embeddings import _CHARS_PER_TOKEN, MARGINS  # noqa: E402

    print("%-20s   ESTIMATE chars/%d over-estimates true tokens by >= %.2fx"
          % ("", _CHARS_PER_TOKEN, cpa / _CHARS_PER_TOKEN))
    for m in MARGINS:
        effective = _CHARS_PER_TOKEN * m.den / m.num
        print("%-20s     + margin %-18s (x%d/%d) -> effective chars/%.2f, "
              "over-estimates by >= %.2fx"
              % ("", m.name, m.num, m.den, effective, cpa / effective))
