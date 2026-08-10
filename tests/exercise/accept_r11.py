"""
Acceptance — R11: chunked durability for large evicted spans (I17).

Before this fix, `_ensure_durable` (engine-side: context.py, the context-engine
plugin) stored an evicted span as `excerpt: content[:4000]` — a silent hard
truncation. Once compress() dropped that span from the live window, everything
past character 4000 was gone: not evicted-but-recoverable, just gone. That is
a durability violation in spirit even though nothing raised: I17 promises a
span is evicted only once it is (or is made) durable, and a truncated copy is
not the same span.

The fix reuses engine.capture._split_excerpt — the same boundary-aware
chunker capture.observe() already uses for long turns — so a large span
becomes N sibling `observed` events (chunk_index/chunk_count), each under the
configured cap, and "".join(chunks) reproduces the original byte for byte.

The bar is not "some events got written" — a stub that stores the first 4000
chars as chunk 0 and drops the rest would still show "events were created".
The checks below force the reconstruction to be genuinely complete:
  (1) a span far past the old 4000-char cliff round-trips byte-exact through
      the store, split into >1 sibling events.
  (2) the chunks _ensure_durable actually wrote are IDENTICAL, in order, to
      calling the real splitter directly on the same content/cap — proving
      this is the shared chunker, not a bespoke reimplementation.
  (3) a span just one character over the old hardcoded 4000 cliff (4001
      chars) is not truncated — the exact regression this task exists for.
  (4) a small span (under cap) is untouched: exactly one chunk, content
      unchanged — no regression for the common case.
  (5) end-to-end through the real compress() eviction path (not just calling
      _ensure_durable directly): a large mid-window message gets evicted from
      the live window AND is fully recoverable from the store, and the
      `compressed` audit event's evicted_spans count is unaffected.

Run: python3 tests/exercise/accept_r11.py
"""

import json
import sys
import tempfile
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))

from engine.core import ChronicleCore                                          # noqa: E402
from engine.capture import _split_excerpt                                      # noqa: E402
from context import ChronicleContextEngine                                     # noqa: E402


def _make_engine(core, session_id="test_session", principal_id="test_user"):
    eng = ChronicleContextEngine()
    eng.core = core
    eng._session_id = session_id
    eng._principal_id = principal_id
    return eng


def _reconstruct(core, session_id, source_ref=None):
    """Pull every `observed`/context_eviction event for the session, sorted by
    chunk_index, and join their excerpts. Uses the store's real query API
    (get_events_by_session), not a raw SQL probe against internals."""
    rows = core.store.get_events_by_session(session_id, types=["observed"])
    chunks = []
    for row in rows:
        payload = row["payload"]
        payload = json.loads(payload) if isinstance(payload, str) else payload
        if payload.get("source_type") != "context_eviction":
            continue
        if source_ref is not None and payload.get("source_ref") != source_ref:
            continue
        chunks.append((payload.get("chunk_index", 0), payload["excerpt"]))
    chunks.sort(key=lambda c: c[0])
    return chunks, "".join(c[1] for c in chunks)


# Realistic prose, not a repeated character — exercises the real
# boundary-aware splitter (sentence ends / message starts) instead of only
# ever hitting the hard-cut fallback.
def _lorem(n_chars):
    sentence = ("The quarterly review with Pat Testley at Acme Fake Co covered "
                "onboarding, billing, and the migration timeline. ")
    out = []
    total = 0
    while total < n_chars:
        out.append(sentence)
        total += len(sentence)
    return "".join(out)[:n_chars]


def test_large_span_round_trips_byte_exact_and_is_split():
    """(1) A span well past the old 4000-char cliff is stored losslessly,
    across multiple sibling events."""
    home = tempfile.mkdtemp(prefix="accept_r11_")
    try:
        core = ChronicleCore(home, {"embeddings": {"model": "hashing"}})
        eng = _make_engine(core)
        content = _lorem(9000)
        eng._ensure_durable({"role": "assistant", "content": content})

        chunks, reconstructed = _reconstruct(core, "test_session")
        assert len(chunks) > 1, f"expected multiple chunks for a 9000-char span, got {len(chunks)}"
        assert reconstructed == content, (
            f"reconstruction mismatch: expected {len(content)} chars, got {len(reconstructed)}")
        print(f"PASS: 9000-char span -> {len(chunks)} chunks, byte-exact reconstruction")
    finally:
        shutil.rmtree(home, ignore_errors=True)


def test_chunks_match_the_shared_splitter_exactly():
    """(2) _ensure_durable's chunks are the SAME chunks _split_excerpt would
    produce directly — proving it reuses capture's chunker, not a
    reimplementation that happens to also reconstruct correctly."""
    home = tempfile.mkdtemp(prefix="accept_r11_")
    try:
        core = ChronicleCore(home, {"embeddings": {"model": "hashing"}})
        eng = _make_engine(core)
        content = _lorem(12345)
        eng._ensure_durable({"role": "user", "content": content})

        chunks, _ = _reconstruct(core, "test_session")
        stored = [c for _, c in chunks]
        cap = core.capture._excerpt_cap()
        expected = _split_excerpt(content, cap)
        assert stored == expected, (
            f"stored chunks diverge from engine.capture._split_excerpt(content, {cap}) — "
            f"{len(stored)} stored vs {len(expected)} expected")
        print(f"PASS: {len(stored)} stored chunks match _split_excerpt(content, cap={cap}) exactly")
    finally:
        shutil.rmtree(home, ignore_errors=True)


def test_4001_chars_no_longer_truncated_at_the_old_cliff():
    """(3) The exact regression: one character past the OLD hardcoded 4000
    cap must not be dropped."""
    home = tempfile.mkdtemp(prefix="accept_r11_")
    try:
        core = ChronicleCore(home, {"embeddings": {"model": "hashing"}})
        eng = _make_engine(core)
        content = _lorem(4001)
        assert len(content) == 4001
        eng._ensure_durable({"role": "assistant", "content": content})

        _, reconstructed = _reconstruct(core, "test_session")
        assert len(reconstructed) == 4001, (
            f"old content[:4000] truncation regression: got {len(reconstructed)} chars back, "
            f"expected 4001 — the last character(s) were dropped")
        assert reconstructed == content
        print("PASS: 4001-char span (1 over the old cliff) is fully recovered, not truncated to 4000")
    finally:
        shutil.rmtree(home, ignore_errors=True)


def test_small_span_is_a_single_chunk_no_regression():
    """(4) Common case unaffected: content under the cap is one event, byte-identical."""
    home = tempfile.mkdtemp(prefix="accept_r11_")
    try:
        core = ChronicleCore(home, {"embeddings": {"model": "hashing"}})
        eng = _make_engine(core)
        content = "Short note about the Acme Fake Co renewal."
        eng._ensure_durable({"role": "user", "content": content})

        chunks, reconstructed = _reconstruct(core, "test_session")
        assert len(chunks) == 1, f"expected exactly 1 chunk for a short span, got {len(chunks)}"
        assert chunks[0][0] == 0
        assert reconstructed == content
        print("PASS: short span stored as exactly 1 chunk, unchanged content")
    finally:
        shutil.rmtree(home, ignore_errors=True)


def test_end_to_end_compress_eviction_is_lossless():
    """(5) Through the real compress() eviction path: a large mid-window
    message is evicted from the live window and is fully recoverable from
    the store; the compressed-event bookkeeping is unaffected."""
    home = tempfile.mkdtemp(prefix="accept_r11_")
    try:
        core = ChronicleCore(home, {"embeddings": {"model": "hashing"}})
        eng = _make_engine(core, session_id="e2e_session")

        big = _lorem(6000)
        system = [{"role": "system", "content": "You are a helpful assistant."}]
        head = [{"role": "user", "content": f"head message {i}"} for i in range(3)]
        middle = ([{"role": "assistant", "content": big}] +
                  [{"role": "user", "content": f"mid filler {i}"} for i in range(5)])
        tail = [{"role": "assistant", "content": f"tail message {i}"} for i in range(6)]
        messages = system + head + middle + tail

        result = eng.compress(messages)

        assert big not in [m.get("content") for m in result], (
            "the large mid-window message was expected to be evicted from the live window")

        events = core.store.get_events_by_type("compressed")
        events = [e for e in events if e["session_id"] == "e2e_session"]
        assert len(events) == 1, f"expected exactly 1 compressed audit event, got {len(events)}"
        audit = json.loads(events[0]["payload"]) if isinstance(events[0]["payload"], str) else events[0]["payload"]
        assert audit["evicted_spans"] == 6, f"expected 6 evicted spans (big + 5 filler), got {audit['evicted_spans']}"

        # Every evicted span (big + 5 short filler ones) is a context_eviction
        # group of its own; chunk_index only orders siblings WITHIN one span's
        # group, so isolate `big`'s group by chunk_count (it is the only span
        # that split into >1 chunk — the filler messages are single-chunk).
        rows = core.store.get_events_by_session("e2e_session", types=["observed"])
        big_chunks = []
        for row in rows:
            payload = row["payload"]
            payload = json.loads(payload) if isinstance(payload, str) else payload
            if payload.get("source_type") == "context_eviction" and payload.get("chunk_count", 1) > 1:
                big_chunks.append((payload["chunk_index"], payload["excerpt"]))
        assert len(big_chunks) > 1, f"expected the large span to be split into >1 chunks, got {len(big_chunks)}"
        big_chunks.sort(key=lambda c: c[0])
        reconstructed_big = "".join(c[1] for c in big_chunks)
        assert reconstructed_big == big, (
            "evicted large span not fully recoverable from the store: "
            f"expected {len(big)} chars, got {len(reconstructed_big)}")
        print(f"PASS: end-to-end compress() evicts the large span; {len(big_chunks)} durable chunks "
              f"recover it byte-exact; compressed audit event evicted_spans={audit['evicted_spans']}")
    finally:
        shutil.rmtree(home, ignore_errors=True)


if __name__ == "__main__":
    test_large_span_round_trips_byte_exact_and_is_split()
    test_chunks_match_the_shared_splitter_exactly()
    test_4001_chars_no_longer_truncated_at_the_old_cliff()
    test_small_span_is_a_single_chunk_no_regression()
    test_end_to_end_compress_eviction_is_lossless()
    print("\nAll R11 acceptance tests passed.")
