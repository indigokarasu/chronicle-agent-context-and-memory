"""
Acceptance test for t6 — chunked capture, no silent truncation (§12.1).

The bar is *exact reconstruction*, not "FTS returned something": store._fts_query
strips '_' and ORs the terms, so a bare `if hits:` on "SENTINEL_019" is satisfied
by any event containing the word "SENTINEL" and would pass on the truncating
baseline. Every check here therefore asserts on the stored excerpts themselves.

Run: python3 tests/exercise/accept_t6.py
"""

import json
import shutil
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from engine.capture import _split_excerpt
from engine.core import ChronicleCore

_HOMES = []


def make_core(config=None):
    """Fresh store + offline hashing embedder (deterministic, no network)."""
    home = tempfile.mkdtemp(prefix="accept_t6_")
    _HOMES.append(home)
    cfg = {"embeddings": {"model": "hashing"}}
    cfg.update(config or {})
    return ChronicleCore(home, cfg)


def observed_chunks(core, session_id):
    """The session's session_transcript excerpts, in chunk order."""
    out = []
    for ev in core.store.get_events_by_session(session_id):
        if ev["type"] != "observed":
            continue
        p = ev["payload"]
        p = json.loads(p) if isinstance(p, str) else p
        if p.get("source_type") != "session_transcript":
            continue
        out.append((p.get("chunk_index", 0), p.get("excerpt", ""), ev["occurred_at"]))
    out.sort(key=lambda r: r[0])
    return out


def build_turn(n_sentinels=20):
    """~15000 chars of numbered sentinel sentences separated by filler."""
    filler = "Lorem ipsum dolor sit amet, consectetur adipiscing elit. " * 12
    parts = []
    for i in range(n_sentinels):
        parts.append("SENTINEL_%03d the quick brown fox jumps over the lazy dog in the field." % i)
        parts.append(filler)
    return "\n".join(parts)


# -- 1. no data loss ---------------------------------------------------------

def test_exact_reconstruction():
    """Concatenated chunk excerpts must equal the excerpt observe() built, and the
    event count must equal the chunk count. Fails on the truncating baseline."""
    core = make_core()
    core.initialize("s1")
    body = build_turn()
    expected = "User: {}\nAssistant: {}".format("t6 acceptance", body)
    chunks = _split_excerpt(expected, core.capture._excerpt_cap())
    print("input %d chars -> %d chunks (cap %d)" % (len(expected), len(chunks),
                                                    core.capture._excerpt_cap()))

    core.capture.observe("t6 acceptance", body, session_id="s1")
    core.process_pending()

    rows = observed_chunks(core, "s1")
    if len(rows) != len(chunks):
        print("FAIL reconstruction: %d observed events for %d chunks" % (len(rows), len(chunks)))
        return False
    rebuilt = "".join(e for _, e, _ in rows)
    if rebuilt != expected:
        print("FAIL reconstruction: rebuilt %d chars != input %d chars" % (len(rebuilt), len(expected)))
        return False
    if len({o for _, _, o in rows}) != 1:
        print("FAIL reconstruction: sibling chunks disagree on occurred_at")
        return False
    print("PASS exact reconstruction: %d events, %d chars round-tripped byte for byte, "
          "one shared occurred_at" % (len(rows), len(rebuilt)))
    return True


# -- 2. sentinels are individually retrievable -------------------------------

def test_sentinels_retrievable():
    """start / middle / end sentinels must each be found by fts_search_observed AND
    actually appear in a returned excerpt (the OR-of-terms sanitizer makes a bare
    truthiness check meaningless)."""
    core = make_core()
    core.initialize("s2")
    body = build_turn()
    core.capture.observe("t6 acceptance", body, session_id="s2")
    core.process_pending()

    ok = True
    for label, i in (("start", 0), ("middle", 10), ("end", 19)):
        key = "SENTINEL_%03d" % i
        hits = core.store.fts_search_observed(key, limit=5)
        exact = [h for h in hits if key in (h.get("excerpt") or "")]
        if not exact:
            print("FAIL %s %s: %d hit(s), none containing the sentinel" % (label, key, len(hits)))
            ok = False
            continue
        print("PASS %s %s: found verbatim in %d of %d hit(s)" % (label, key, len(exact), len(hits)))
    return ok


# -- 3. the dedup trap -------------------------------------------------------

def test_identical_siblings_survive():
    """event_id hashes type+payload+parents+actor+occurred_at and append_event
    returns early on a duplicate id, so byte-identical sibling chunks collapse
    into ONE event unless the payload carries chunk_index."""
    core = make_core({"capture": {"max_excerpt_chars": 500}})
    core.initialize("s3")
    body = "abc def. " * 229                       # splits into repeating identical chunks
    expected = "User: {}\nAssistant: {}".format("u", body)
    chunks = _split_excerpt(expected, 500)
    dupes = len(chunks) - len(set(chunks))
    if dupes < 1:
        print("FAIL dedup trap: fixture produced no identical sibling chunks")
        return False

    core.capture.observe("u", body, session_id="s3")
    rows = observed_chunks(core, "s3")
    if len(rows) != len(chunks):
        print("FAIL dedup trap: %d events for %d chunks (%d identical) — siblings were dropped"
              % (len(rows), len(chunks), dupes))
        return False
    if "".join(e for _, e, _ in rows) != expected:
        print("FAIL dedup trap: chunks do not reconstruct the input")
        return False
    print("PASS dedup trap: %d chunks (%d byte-identical) -> %d distinct events"
          % (len(chunks), dupes, len(rows)))
    return True


# -- 4. splitter contract ----------------------------------------------------

def test_split_newline_only():
    """With no [.!?] anywhere, the splitter must still fall back to newline
    boundaries (spec: '[.!?]\\s or newline') rather than hard-cutting."""
    text = "\n".join("PARA%02d %s" % (i, "word " * 20) for i in range(12))
    if any(p in text for p in (".", "!", "?")):
        print("FAIL newline-only split: fixture contains sentence punctuation")
        return False
    cap = 150
    chunks = _split_excerpt(text, cap)
    if len(chunks) <= 1 or "".join(chunks) != text:
        print("FAIL newline-only split: %d chunks, lossless=%s"
              % (len(chunks), "".join(chunks) == text))
        return False
    if any(len(c) > cap for c in chunks):
        print("FAIL newline-only split: a chunk exceeds cap")
        return False
    if not all(c.endswith("\n") for c in chunks[:-1]):
        print("FAIL newline-only split: a non-final chunk did not end on a newline")
        return False
    print("PASS newline-only split: %d chunks, every non-final boundary on \\n" % len(chunks))
    return True


def test_cap_clamped():
    """capture.max_excerpt_chars is honoured and clamped to [500, 16000]."""
    cases = [(None, 4000), (9000, 9000), (10, 500), (10 ** 9, 16000), ("nope", 4000)]
    ok = True
    for raw, want in cases:
        cfg = {} if raw is None else {"capture": {"max_excerpt_chars": raw}}
        got = make_core(cfg).capture._excerpt_cap()
        if got != want:
            print("FAIL cap clamp: %r -> %d, want %d" % (raw, got, want))
            ok = False
    if ok:
        print("PASS cap clamp: default 4000, honoured mid-range, clamped to [500, 16000], "
              "garbage falls back")
    return ok


if __name__ == "__main__":
    tests = [test_exact_reconstruction, test_sentinels_retrievable,
             test_identical_siblings_survive, test_split_newline_only, test_cap_clamped]
    results = []
    for t in tests:
        try:
            results.append(bool(t()))
        except Exception as exc:                    # a crash is a failure, not a stack trace
            print(f"FAIL {t.__name__}: {type(exc).__name__}: {exc}")
            results.append(False)
    for home in _HOMES:
        shutil.rmtree(home, ignore_errors=True)
    print("\n%d/%d acceptance checks passed" % (sum(results), len(results)))
    sys.exit(0 if all(results) else 1)
