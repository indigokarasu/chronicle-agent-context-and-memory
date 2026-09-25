#!/usr/bin/env python3
"""
Chronicle — prefetch evaluation harness (§g3, R1).

Chronicle injects `retrieval.get_context()` into every user turn before the
model ever sees it (`provider.prefetch`: token_budget 1200, exclude_automation
True, relevance_gate True — see provider.py). Whether that injection actually
carries the evidence a real question needs was previously only checkable by
reading a live conversation after the fact — which is how a purchase question
with 199 matching transactions in the store was found to inject nothing. This
script asks the same question the same way, against a store already on disk,
and reports what came back — without a model call, a network socket, or a
write to that store.

Deterministic and read-only:
  * the embedder is forced through `embeddings.NullProbe()`, which resolves to
    a DegradedEmbedder on every machine regardless of what the config claims
    is running locally (engine/embeddings.py) — no HTTP call to the local
    embed server, no socket of any kind, and the same result on every run.
    Retrieval runs lexical-only (FTS + structured), which is exactly the
    degraded mode Chronicle itself falls back to when the embed server is
    down, so this also doubles as that path's smoke test.
  * `get_context()` is Chronicle's own read surface (§18: hybrid retrieval,
    answer-support verification, abstention gating all live below it, but it
    writes nothing). This script never calls `chronicle_remember`, never
    drives `capture`, and never calls `core.initialize()` — which would touch
    session/principal rows and run startup recovery — because the principal
    it evaluates as is passed straight to `get_context()` instead. The one
    write `ChronicleCore.__init__` always performs (idempotent
    predicate/derivation-rule seeding, unconditional for every process that
    constructs an engine, args-independent) is unavoidable short of building
    the retrieval stack by hand; it changes nothing this run's inputs decide.

Usage:
    python3 scripts/prefetch_eval.py <config.yaml> <chronicle.db> [questions.json]

`config.yaml` is a Hermes-style config file (a top-level `memory:` section) or
a bare memory-config mapping — either is accepted, so a hand-written eval
config needs no wrapper. `chronicle.db` is the store to evaluate against,
whatever its `db_path` declares (see `_engine_for` for why pointing an
arbitrary path in takes a small detour through `hermes_home`). `questions.json`
is a JSON array of strings; omitted, this runs a built-in set of 10 generic
questions spanning people, places, purchases, schedule and documents —
generic wording only, so the script carries no real names and is safe to keep
in the tree this repository publishes nightly.
"""
from __future__ import annotations

import json
import re
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from engine.core import ChronicleCore
from engine.embeddings import NullProbe

# Two questions per category named in the brief -- people, places, purchases,
# schedule, documents. Deliberately generic: no names, places or products, so
# this built-in list carries no one deployment's data into the public tree.
BUILTIN_QUESTIONS = [
    "Who have I mentioned most recently?",
    "What do I know about the people I talk to regularly?",
    "What places have I mentioned going to?",
    "Where did I say I was planning to travel?",
    "What have I bought recently?",
    "What purchases or transactions have I talked about?",
    "What do I have scheduled coming up?",
    "When is my next appointment?",
    "What documents have I referenced?",
    "What files or attachments have I mentioned?",
]

# provider.prefetch()'s own settings (provider.py), reproduced here rather
# than imported: this script evaluates what the injection WOULD be even when
# prefetch's own config (retrieval.prefetch_budget /
# retrieval.prefetch_relevance_gate) has been turned down for a deployment,
# so the numbers stay comparable across stores.
PREFETCH_TOKEN_BUDGET = 1200

# Line-prefix taxonomy for `get_context`'s rendered output (see
# engine/retrieval.py `_render` for belief lines, `_get_context_inner`'s
# federated-channel and tail sections for the rest). Kept here as plain
# strings rather than imported from engine/retrieval.py: these are RENDER
# strings, not an API, and a future change to them should make this script's
# counts visibly stale rather than silently wrong.
_FEDERATED_RE = re.compile(r"^\[FEDERATED ([^\]]+)\] ")
_BELIEF_RE = re.compile(r"^(?:\[DRAFT\] )?\[(?:FACT|DERIVED|NOTE|EPISODE)\] ")
_TAIL_RE = re.compile(r"^\[(?:DIRECTIVE|CONTRADICTION|CRITICAL|DIGEST)\] ")


def _load_memory_config(config_path: str) -> dict:
    """Same shape `ChronicleCore._load_memory_config` reads from a live
    `config.yaml`: a top-level `memory:` section. A bare memory-shaped mapping
    (no `memory:` wrapper) is accepted too, for a hand-written eval config."""
    import yaml
    raw = yaml.safe_load(Path(config_path).read_text()) or {}
    if not isinstance(raw, dict):
        return {}
    mem = raw.get("memory")
    return dict(mem) if isinstance(mem, dict) else dict(raw)


def _engine_for(config_path: str, store_path: str) -> ChronicleCore:
    """Build a `ChronicleCore` bound to exactly `store_path`, no matter what
    `db_path` (if any) `config_path` declares.

    `ChronicleCore.__init__` (engine/core.py) resolves `db_path` in a way that
    only ever accepts an override starting with the literal string
    `"~/.hermes"` — any other explicit `db_path` is silently DISCARDED in
    favor of `<hermes_home>/commons/db/chronicle/chronicle.db`. That
    resolution is out of scope for this task (R1 touches federated.py,
    config.py and this script only), so rather than fight it: pass the
    sentinel `db_path` it does honor, `"~/.hermes"` verbatim, and pass
    `store_path` itself as `hermes_home`. The substitution
    `"~/.hermes" -> str(Path(hermes_home))` then resolves to exactly
    `store_path`, with no other part of construction touched -- `hermes_home`
    is read nowhere else before `get_context()` runs (this script never calls
    `initialize()`, `start_sources()`, or anything that would read it as a
    real Hermes home directory).
    """
    cfg = _load_memory_config(config_path)
    cfg["db_path"] = "~/.hermes"
    return ChronicleCore.get(store_path, cfg, embedder_probe=NullProbe())


def _classify(ctx: str) -> dict:
    """Bucket every non-empty rendered line into exactly one source kind.

    `federated` is broken out per provider -- breadth there is what R1
    changes. `belief` is the Tier-1 ranked fact/note/episode block. Everything
    left that is not a directive/contradiction/critical/digest tail line is
    `transcript`: raw session excerpts and their `[SESSION ...]` headers,
    neither of which carries a fixed per-line prefix of its own.
    """
    federated: Counter = Counter()
    belief = 0
    transcript = 0
    for line in ctx.splitlines():
        if not line:
            continue
        m = _FEDERATED_RE.match(line)
        if m:
            federated[m.group(1)] += 1
            continue
        if _BELIEF_RE.match(line):
            belief += 1
            continue
        if _TAIL_RE.match(line):
            continue
        transcript += 1
    return {"federated": dict(federated), "belief_lines": belief, "transcript_lines": transcript}


def evaluate(core: ChronicleCore, questions: list, principal: str = "default") -> None:
    for q in questions:
        ctx = core.retrieval.get_context(
            q, token_budget=PREFETCH_TOKEN_BUDGET, principal=principal,
            epistemic=core.epistemic, exclude_automation=True, relevance_gate=True)
        kinds = _classify(ctx)
        debug_keys = sorted((core.retrieval.last_context_debug or {}).keys())
        print("=== %s" % q)
        print("  chars_injected   : %d" % len(ctx))
        print("  federated        : %s" % (kinds["federated"] or "{}"))
        print("  belief_lines     : %d" % kinds["belief_lines"])
        print("  transcript_lines : %d" % kinds["transcript_lines"])
        print("  context_debug    : %s" % debug_keys)


def main(argv=None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    if len(argv) < 2:
        print(__doc__)
        return 2
    config_path, store_path = argv[0], argv[1]
    questions_path = argv[2] if len(argv) > 2 else None

    if questions_path:
        loaded = json.loads(Path(questions_path).read_text())
        if not isinstance(loaded, list) or not all(isinstance(q, str) for q in loaded):
            print("questions file must be a JSON array of strings", file=sys.stderr)
            return 2
        questions = loaded
    else:
        questions = BUILTIN_QUESTIONS

    core = _engine_for(config_path, store_path)
    evaluate(core, questions)
    return 0


if __name__ == "__main__":
    sys.exit(main())
