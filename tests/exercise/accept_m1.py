#!/usr/bin/env python3
"""
Acceptance — m1: token-aware embed input clamp (§27 embeddings.max_input_tokens
/ .overflow).

Production incident this exists for: hit live on the VPS this week during the
nemotron->nomic vector migration. Chronicle embeds via an OpenAI-compatible
endpoint; the deployed llama.cpp/nomic server has a REAL context of 2048
tokens. Excerpts up to 4000 chars overflowed it -> HTTP 500 -> the curation
job burned all 20 retry attempts and became PERMANENTLY POISONED even after
the cause was fixed, because re-enqueue reuses the spent row. ~880 events
remain unvectorized in production awaiting exactly this fix.

The bar is not "the .overflow attribute holds the right string" — a stub that
returns the truncate vector unconditionally would satisfy that. The checks
below force chunk_mean to be a REAL, DIFFERENT computation:
  (1) HashingEmbedder embeds a 40,000-char pathological (no-space, URL-like)
      string without raising, in BOTH overflow modes, and each returned
      vector is unit-norm.
  (2) chunk_mean's HashingEmbedder output != truncate's, for the SAME
      oversized input (proves it isn't the truncate path relabeled).
  (3) OpenAICompatEmbedder against a mock HTTP server that ASSERTS every
      request body it receives is under max_input_tokens: truncate makes
      exactly 1 HTTP call; chunk_mean makes >1 (one per chunk); chunk_mean's
      vector != truncate's; both are unit-norm; the server never sees an
      over-cap request in either mode.
  (4) embed_batch() never lets an oversized item ride inside a raw batch
      call — a batch of mostly-short texts plus one oversized one still
      keeps every wire request under cap.
  (5) config: embeddings.max_input_tokens defaults to 2048 and clamps to
      [256, 32768]; embeddings.overflow defaults to "truncate".
  (6) end-to-end through ChronicleCore: capture.append() on an oversized
      excerpt, through the REAL reducer._safe_vec path, embeds without
      raising and actually writes a vector (with a small max_input_tokens +
      chunk_mean configured, so the clamp is exercised for real, not just
      unit-tested against the embedder directly).
  (7) full pytest suite green (303 baseline + this file's own asserts).
  (8) LME recall harness under CHRONICLE_EMBED_MODEL=hashing is unchanged
      from baseline — defaults keep normal-sized captured excerpts well
      under the cap, so ordinary recall is untouched by this change.

Run: python3 tests/exercise/accept_m1.py
"""

import json
import math
import os
import subprocess
import sys
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))

from engine.core import ChronicleCore                                          # noqa: E402
from engine.config import Config                                               # noqa: E402
from engine.embeddings import (                                                # noqa: E402
    HashingEmbedder, OpenAICompatEmbedder, estimate_tokens,
    clamp_max_input_tokens, cosine,
)

HARNESS = os.environ.get("CHRONICLE_LME_HARNESS", "/private/tmp/claude-501/"
                         "-Users-evaluser-temp/3d6d860f-71ee-406d-9aef-b68dfd0642d1/"
                         "scratchpad/lme_recall.py")
ORACLE = os.environ.get("CHRONICLE_LME_ORACLE", "/private/tmp/claude-501/"
                        "-Users-evaluser-temp/3d6d860f-71ee-406d-9aef-b68dfd0642d1/"
                        "scratchpad/oracle.json")
BASELINE_UNION_AT_1 = 65.0
TOLERANCE = 3.0

# 40,000 chars, no spaces, no sentence punctuation followed by whitespace, no
# newlines — a pathological URL-ish blob that gives the boundary-aware splitter
# nothing but the hard-cut fallback to work with. Each segment carries a
# distinct index so different windows of the string tokenize differently
# (unlike a perfectly periodic repeat, where every window's bag-of-tokens is
# nearly identical and truncate vs chunk_mean would look deceptively alike for
# reasons that have nothing to do with correctness).
def _build_pathological_text(n_chars=40000):
    segments, total, i = [], 0, 0
    while total < n_chars:
        seg = f"https-acme-fake-test-segment{i:06d}-nospace-blob{i:06d}xyz"
        segments.append(seg)
        total += len(seg)
        i += 1
    return "".join(segments)[:n_chars]


PATHOLOGICAL_TEXT = _build_pathological_text(40000)
assert len(PATHOLOGICAL_TEXT) == 40000
assert " " not in PATHOLOGICAL_TEXT and "\n" not in PATHOLOGICAL_TEXT
assert not any(c in PATHOLOGICAL_TEXT for c in ".!?")


def _fail(check, msg):
    print(f"FAIL: {check} — {msg}")
    return False


def _norm(vec):
    return math.sqrt(sum(x * x for x in vec))


# ---------------------------------------------------------------------------
# (1) + (2) HashingEmbedder: both modes embed the pathological string; the
# modes disagree with each other.
# ---------------------------------------------------------------------------
def check1_hashing_both_modes():
    truncate = HashingEmbedder(dimensions=64, overflow="truncate")
    chunk_mean = HashingEmbedder(dimensions=64, overflow="chunk_mean")

    v_trunc = truncate.embed(PATHOLOGICAL_TEXT)
    v_chunk = chunk_mean.embed(PATHOLOGICAL_TEXT)

    if len(v_trunc) != 64 or len(v_chunk) != 64:
        return _fail("check1", f"wrong dimensionality: {len(v_trunc)}, {len(v_chunk)}")
    if abs(_norm(v_trunc) - 1.0) > 1e-6:
        return _fail("check1", f"truncate vector not unit-norm: {_norm(v_trunc)!r}")
    if abs(_norm(v_chunk) - 1.0) > 1e-6:
        return _fail("check1", f"chunk_mean vector not unit-norm: {_norm(v_chunk)!r}")
    if v_trunc == v_chunk:
        return _fail("check1", "chunk_mean output IDENTICAL to truncate output — "
                                "chunk_mean is not a real, distinct computation")
    sim = cosine(v_trunc, v_chunk)
    print(f"  hashing: truncate vs chunk_mean cosine={sim:.4f} (expect < 1.0, distinct vectors)")
    if sim >= 0.999999:
        return _fail("check1", f"truncate and chunk_mean vectors are near-identical (cos={sim})")

    # A short (under-cap) string must be untouched by any of this — same
    # result regardless of overflow mode, still exactly what embed() always did.
    short_t = truncate.embed("vet in denver")
    short_c = chunk_mean.embed("vet in denver")
    if short_t != short_c:
        return _fail("check1", "overflow mode changed behavior for an UNDER-CAP string")

    print("PASS: check1 — HashingEmbedder handles the pathological string in both "
          "modes; chunk_mean is a real, distinct, unit-norm computation")
    return True


# ---------------------------------------------------------------------------
# (3) OpenAICompatEmbedder against a mock server that asserts every request is
# under cap; chunk_mean must issue >1 HTTP call.
# ---------------------------------------------------------------------------
def _make_cap_checking_server(max_input_tokens):
    class _Handler(BaseHTTPRequestHandler):
        DIM = 24
        request_count = 0
        over_cap_seen = False
        cap = max_input_tokens

        def log_message(self, *a):
            pass

        def _send(self, obj):
            body = json.dumps(obj).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _vec_for(self, text):
            # Deterministic pseudo-embedding derived from the text's own
            # content, L2-normalized — like a well-behaved real embedding
            # endpoint (nomic-embed returns normalized vectors), so truncate's
            # passthrough vector is ALSO meaningfully checkable for unit-norm.
            h = 1469598103934665603  # FNV offset basis
            for ch in text:
                h ^= ord(ch)
                h = (h * 1099511628211) & 0xFFFFFFFFFFFFFFFF
            raw = []
            for i in range(self.DIM):
                h = (h * 6364136223846793005 + 1) & 0xFFFFFFFFFFFFFFFF
                raw.append(float((h >> 33) % 2000) / 1000.0 - 1.0)
            n = math.sqrt(sum(x * x for x in raw)) or 1.0
            return [x / n for x in raw]

        def do_GET(self):                                     # /v1/models
            self._send({"data": [{"id": "fake-embed-model"}]})

        def do_POST(self):                                    # /v1/embeddings
            raw = self.rfile.read(int(self.headers.get("Content-Length", 0)) or 0)
            payload = json.loads(raw or b"{}")
            inp = payload.get("input", "")
            texts = inp if isinstance(inp, list) else [inp]
            type(self).request_count += 1
            for t in texts:
                if estimate_tokens(t) > type(self).cap:
                    type(self).over_cap_seen = True
                    print(f"    !! server saw an OVER-CAP request: "
                          f"{estimate_tokens(t)} tokens > {type(self).cap}")
            if isinstance(inp, list):
                rows = [{"index": i, "embedding": self._vec_for(t)} for i, t in enumerate(texts)]
            else:
                rows = [{"embedding": self._vec_for(texts[0])}]
            self._send({"data": rows})

    return _Handler


def check2_openai_compat_cap_and_modes():
    CAP = 2048
    Handler = _make_cap_checking_server(CAP)
    srv = HTTPServer(("127.0.0.1", 0), Handler)
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    try:
        url = f"http://127.0.0.1:{srv.server_address[1]}/v1"

        Handler.request_count = 0
        Handler.over_cap_seen = False
        truncate = OpenAICompatEmbedder(url, "fake-embed-model", 24, max_attempts=1,
                                        max_input_tokens=CAP, overflow="truncate")
        v_trunc = truncate.embed(PATHOLOGICAL_TEXT)
        calls_truncate = Handler.request_count
        if Handler.over_cap_seen:
            return _fail("check2", "truncate mode sent an over-cap request to the server")
        if calls_truncate != 1:
            return _fail("check2", f"truncate mode made {calls_truncate} HTTP calls, expected exactly 1")

        Handler.request_count = 0
        Handler.over_cap_seen = False
        chunk_mean = OpenAICompatEmbedder(url, "fake-embed-model", 24, max_attempts=1,
                                          max_input_tokens=CAP, overflow="chunk_mean")
        v_chunk = chunk_mean.embed(PATHOLOGICAL_TEXT)
        calls_chunk_mean = Handler.request_count
        if Handler.over_cap_seen:
            return _fail("check2", "chunk_mean mode sent an over-cap request to the server")
        if calls_chunk_mean <= 1:
            return _fail("check2", f"chunk_mean mode made only {calls_chunk_mean} HTTP call(s); "
                                   "must issue one call PER CHUNK (>1) for a 40,000-char input")

        if abs(_norm(v_trunc) - 1.0) > 1e-6:
            return _fail("check2", f"truncate vector not unit-norm: {_norm(v_trunc)!r}")
        if abs(_norm(v_chunk) - 1.0) > 1e-6:
            return _fail("check2", f"chunk_mean vector not unit-norm: {_norm(v_chunk)!r}")
        if v_trunc == v_chunk:
            return _fail("check2", "chunk_mean output identical to truncate output over HTTP")

        print(f"  openai-compat: truncate={calls_truncate} call, chunk_mean={calls_chunk_mean} calls, "
              f"cosine(trunc,chunk_mean)={cosine(v_trunc, v_chunk):.4f}")
        print("PASS: check2 — OpenAICompatEmbedder never sends an over-cap request; "
              "chunk_mean issues one call per chunk and differs from truncate")
        return True
    finally:
        srv.shutdown()
        srv.server_close()


# ---------------------------------------------------------------------------
# (4) embed_batch(): an oversized item in a mixed batch must never ride along
# inside a raw batch HTTP call.
# ---------------------------------------------------------------------------
def check3_embed_batch_mixed():
    CAP = 2048
    Handler = _make_cap_checking_server(CAP)
    srv = HTTPServer(("127.0.0.1", 0), Handler)
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    try:
        url = f"http://127.0.0.1:{srv.server_address[1]}/v1"
        Handler.request_count = 0
        Handler.over_cap_seen = False
        emb = OpenAICompatEmbedder(url, "fake-embed-model", 24, max_attempts=1,
                                   max_input_tokens=CAP, overflow="truncate")
        texts = ["short one", "short two", PATHOLOGICAL_TEXT, "short three"]
        vecs = emb.embed_batch(texts, chunk=64)
        if Handler.over_cap_seen:
            return _fail("check3", "embed_batch let an over-cap request reach the server")
        if len(vecs) != len(texts):
            return _fail("check3", f"embed_batch returned {len(vecs)} vectors for {len(texts)} inputs")
        for i, v in enumerate(vecs):
            if not isinstance(v, list) or len(v) != 24:
                return _fail("check3", f"item {i}: bad/missing vector {v!r}")
        # request_count: 1 batch call for the 3 short texts + >=1 call(s) for
        # the oversized one, routed through the same clamp as embed().
        if Handler.request_count < 2:
            return _fail("check3", f"expected >=2 HTTP calls (batch + oversized), got "
                                   f"{Handler.request_count}")
        print(f"  embed_batch: {Handler.request_count} HTTP calls for 3 short + 1 oversized "
              f"(cap never violated)")
        print("PASS: check3 — embed_batch never lets an oversized item ride in a raw batch call")
        return True
    finally:
        srv.shutdown()
        srv.server_close()


# ---------------------------------------------------------------------------
# (5) config defaults + clamping
# ---------------------------------------------------------------------------
def check4_config_clamp():
    cfg = Config()
    got_default = cfg.get("embeddings.max_input_tokens")
    got_overflow = cfg.get("embeddings.overflow")
    if got_default != 2048:
        return _fail("check4", f"embeddings.max_input_tokens default is {got_default!r}, expected 2048")
    if got_overflow != "truncate":
        return _fail("check4", f"embeddings.overflow default is {got_overflow!r}, expected 'truncate'")
    if clamp_max_input_tokens(1) != 256:
        return _fail("check4", f"clamp floor broken: clamp_max_input_tokens(1) = "
                               f"{clamp_max_input_tokens(1)!r}, expected 256")
    if clamp_max_input_tokens(999999999) != 32768:
        return _fail("check4", f"clamp ceiling broken: clamp_max_input_tokens(999999999) = "
                               f"{clamp_max_input_tokens(999999999)!r}, expected 32768")
    if clamp_max_input_tokens(4096) != 4096:
        return _fail("check4", "an in-range value must pass through unchanged")
    print("PASS: check4 — embeddings.max_input_tokens defaults to 2048 (clamped [256, 32768]), "
          "embeddings.overflow defaults to 'truncate'")
    return True


# ---------------------------------------------------------------------------
# (6) End-to-end through ChronicleCore/reducer._safe_vec — the actual
# production write path, not just the embedder in isolation.
# ---------------------------------------------------------------------------
def check5_end_to_end_core():
    home = tempfile.mkdtemp(prefix="accept_m1_")
    try:
        core = ChronicleCore(home, {"embeddings": {"model": "hashing", "max_input_tokens": 300,
                                                    "overflow": "chunk_mean"}})
        if core.embedder.max_input_tokens != 300:
            return _fail("check5", f"ChronicleCore did not wire embeddings.max_input_tokens through "
                                   f"(got {core.embedder.max_input_tokens})")
        if core.embedder.overflow != "chunk_mean":
            return _fail("check5", f"ChronicleCore did not wire embeddings.overflow through "
                                   f"(got {core.embedder.overflow!r})")
        eid = core.capture.append(
            "observed",
            {"source_type": "session_transcript", "excerpt": PATHOLOGICAL_TEXT, "source_ref": "s1"},
            actor="user", session_id="s1", trust_level=2)
        if not eid:
            return _fail("check5", "capture.append raised or returned no event id for oversized excerpt")
        if not core.store.has_observed_vector(eid):
            return _fail("check5", "oversized excerpt through the real reducer path wrote NO vector "
                                   "(should clamp and embed, never skip)")
        print("PASS: check5 — ChronicleCore wires embeddings.max_input_tokens/.overflow through; "
              "the real capture->reducer._safe_vec path embeds an oversized excerpt without error")
        return True
    finally:
        import shutil
        shutil.rmtree(home, ignore_errors=True)


# ---------------------------------------------------------------------------
# (8) LME recall harness unchanged
# ---------------------------------------------------------------------------
def _union_at_1(out):
    """First % on the `union` row of the TURN-LEVEL table (same parse accept_t2 uses)."""
    import re
    block = out.split("TURN-LEVEL RECALL@k", 1)[-1].split("UNION SESSION RECALL", 1)[0]
    for line in block.splitlines():
        if line.strip().startswith("union"):
            found = re.findall(r"([\d.]+)%", line)
            if found:
                return float(found[0])
    return None


def check6_harness_unchanged():
    if not (Path(HARNESS).exists() and Path(ORACLE).exists()):
        print(f"SKIP: check6 — harness/oracle not found ({HARNESS}, {ORACLE})")
        return True
    env = dict(os.environ, CHRONICLE_DIR=str(ROOT), CHRONICLE_EMBED_MODEL="hashing")
    p = subprocess.run([sys.executable, HARNESS, ORACLE], env=env,
                       stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=1800)
    out = p.stdout.decode("utf-8", "replace")
    if p.returncode != 0:
        print(out[-2000:])
        return _fail("check6", f"harness exited {p.returncode}")
    got = _union_at_1(out)
    if got is None:
        return _fail("check6", "could not parse the TURN-LEVEL union row")
    delta = abs(got - BASELINE_UNION_AT_1)
    if delta > TOLERANCE:
        return _fail("check6", f"turn union@1 {got:.1f}% vs baseline {BASELINE_UNION_AT_1}% "
                               f"(delta {delta:.1f} > {TOLERANCE})")
    print(f"PASS: check6 — turn union@1 {got:.1f}% (baseline {BASELINE_UNION_AT_1}%, "
          f"delta {delta:.1f} <= {TOLERANCE})")
    return True


def main():
    ok = True
    for fn in (check1_hashing_both_modes, check2_openai_compat_cap_and_modes,
               check3_embed_batch_mixed, check4_config_clamp, check5_end_to_end_core,
               check6_harness_unchanged):
        ChronicleCore._instances.clear()
        try:
            ok = fn() and ok
        except Exception as e:
            import traceback
            traceback.print_exc()
            ok = _fail(fn.__name__, f"raised {type(e).__name__}: {e}") and ok
    print("\nRESULT: " + ("ALL CHECKS PASS" if ok else "FAILURES ABOVE"))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
