#!/usr/bin/env python3
"""
Chronicle — A0 real-embedder acceptance check (not part of the pytest gate).

Everything else in the A0 suite runs against hashing-backed fakes, which is what
makes it deterministic and offline. This one runs against a REAL local embedding
server, because the defect A0 fixes is about what a real server calls itself:

  * ollama /v1/models reports "nomic-embed-text:latest"
  * llama.cpp --embedding reports "/opt/llama-embed/nomic-embed-text-v1.5.Q8_0.gguf"

Both are the same model and the same geometry. Before A0, a store written by one
and read by the other saw a permanent mismatch it could never heal.

Case 1 — `embeddings.model: auto` against the live endpoint: whatever the server
         reports, a full capture -> process flow must stamp the CANONICAL tag on
         every vector table.
Case 2 — the same flow under an embedder that REPORTS a gguf path (llama.cpp's
         self-report) while embedding through the same endpoint: the stamped tag
         must be byte-identical to case 1's.

Usage:
    CHRONICLE_EMBED_BASE_URL=http://localhost:11434/v1 \
        python3 tests/exercise/accept_a0_real_embedder.py

Exit codes: 0 = pass   1 = fail   3 = no local embedding endpoint (skipped)
"""

from __future__ import annotations

import os
import shutil
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from engine.core import ChronicleCore
from engine.embeddings import (
    OpenAICompatEmbedder,
    canonical_model_id,
    embedder_model_tag,
    get_embedder,
)

GGUF_PATH = "/opt/llama-embed/nomic-embed-text-v1.5.Q8_0.gguf"
# table -> the column holding the packed vector (entity_centroids calls it sum_vec)
TABLES = {"observed_vectors": "embedding", "memory_vectors": "embedding",
          "query_proxy_vectors": "embedding", "entity_centroids": "sum_vec"}
TURNS = [
    "I am Pat Testley\nI work at Acme Fake Co\nI live in Springfield",
    "My manager is Dana Fictional\nI moved to Riverton last spring",
]


class LlamaCppLikeEmbedder(OpenAICompatEmbedder):
    """Reports a gguf FILE PATH as its model, the way llama.cpp --embedding does,
    while sending `wire_model` on the wire so the check can run against whatever
    local server is actually up. `self.model` is the REPORTED name — exactly the
    string Chronicle used to store verbatim."""

    def __init__(self, base_url, reported, wire_model, dims):
        super().__init__(base_url, reported, dims)
        self.wire_model = wire_model

    def _embed_raw(self, text, timeout):
        real, self.model = self.model, self.wire_model
        try:
            return super()._embed_raw(text, timeout)
        finally:
            self.model = real

    def _embed_raw_batch(self, texts, timeout):
        real, self.model = self.model, self.wire_model
        try:
            return super()._embed_raw_batch(texts, timeout)
        finally:
            self.model = real


def _run_flow(embedder):
    home = tempfile.mkdtemp(prefix="a0_real_")
    try:
        core = ChronicleCore(home, {"embeddings": {"model": "hashing"}})
        core.embedder = embedder
        core.reducer.embedder = embedder
        core.initialize("s1", principal_id="assistant")
        for t in TURNS:
            core.capture.observe(t, "", session_id="s1")
        core.process_pending()
        core.curation.drain()
        conn = core.store._conn()
        out = {}
        for table, col in TABLES.items():
            rows = conn.execute("SELECT model, COUNT(*), length(%s) FROM %s "
                                "GROUP BY model, length(%s)" % (col, table, col)).fetchall()
            out[table] = [(r[0], r[1], r[2]) for r in rows]
        return out
    finally:
        shutil.rmtree(home, ignore_errors=True)


def _report(label, tags, expected):
    ok = True
    for table, groups in tags.items():
        if not groups:
            # NOT `continue` with `ok` untouched: main() prints "the SAME canonical
            # tag ... on every vector table", and a table that wrote no rows at all
            # cannot support that claim. Passing here turns a regression that stops
            # writing one of the four tables into a green run.
            print(f"  {label} BAD {table}: (empty) -- no vectors were written")
            ok = False
            continue
        for tag, cnt, blen in groups:
            mark = "OK " if tag == expected else "BAD"
            if tag != expected:
                ok = False
            dims = (blen // 4) if blen else "?"
            print(f"  {label} {mark} {table}: {cnt} rows  tag={tag!r}  dims={dims}")
    return ok


def main() -> int:
    base = os.environ.get("CHRONICLE_EMBED_BASE_URL") or "http://localhost:11434/v1"
    os.environ["CHRONICLE_EMBED_BASE_URL"] = base
    os.environ.pop("CHRONICLE_EMBED_MODEL", None)
    print(f"endpoint: {base}")

    live = get_embedder("auto", 768, base, None)
    if not isinstance(live, OpenAICompatEmbedder):
        print(f"SKIP: no real embedding backend at {base} (got {type(live).__name__})")
        return 3
    expected = embedder_model_tag(live)
    print(f"server reports    : {live.model!r}")
    print(f"canonical id      : {canonical_model_id(live.model)!r}")
    print(f"tag to be stamped : {expected!r}")
    print(f"dimensions        : {live.dimensions}")

    print("\nCase 1 — model: auto against the live endpoint")
    ok1 = _report("[auto]", _run_flow(live), expected)

    print("\nCase 2 — an embedder REPORTING a gguf path")
    fake = LlamaCppLikeEmbedder(base, GGUF_PATH, live.model, live.dimensions)
    fake.dimensions = live.dimensions
    print(f"  reports: {fake.model!r} -> tag {embedder_model_tag(fake)!r}")
    ok2 = embedder_model_tag(fake) == expected
    if not ok2:
        print(f"  BAD: gguf-path reporter stamps {embedder_model_tag(fake)!r}, not {expected!r}")
    ok2 = _report("[gguf]", _run_flow(fake), expected) and ok2

    print()
    if ok1 and ok2:
        print(f"PASS: both reported names stamp the SAME canonical tag {expected!r} "
              f"on every vector table.")
        return 0
    print("FAIL: a reported name leaked into a stored tag.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
