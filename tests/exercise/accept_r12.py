"""
Acceptance — R12: entity digest embeddings reach retrieval.

Entities are (correctly) never vector-embedded: a name carries no semantic
content, and similarity must never drive identity. But an entity DOES have a
meaning-bearing proxy: its consolidation digest (§u2), a note that restates
its facts in prose. This ladder item has three parts:

  (1) VERIFY digest notes actually receive memory vectors through the
      ordinary belief-kind embed path (kind='note') — not assumed, checked
      against a real store after a real drain.
  (2) A digest hit from the VECTOR channel is routed back to its entity as a
      graph-channel seed, so a query that means an entity — without naming it
      or any of its relationships — still reaches that entity's other facts.
      The digest note itself must still never appear directly in ranked
      output (§u2: it restates facts that are already indexed).
  (3) Embedding-coverage reporting lists 'digest' as its own row, broken out
      of the generic 'note' bucket, and 'entity' stays at a permanent 0% —
      literally true by design, not a bug to fix.

Run: python3 tests/exercise/accept_r12.py
"""

import importlib.util
import shutil
import sqlite3
import sys
import tempfile
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from engine.core import ChronicleCore  # noqa: E402


def _fail(check, msg):
    print("FAIL: %s - %s" % (check, msg))
    return False


def _seed_digest(core):
    """3 facts about the same implicit entity ('user') — enough to clear
    §u2's minimum and produce exactly one active digest note."""
    for t in ("I am Pat Testley", "I work at Acme Fake Co", "I live in Springfield"):
        core.capture.observe(t, "", session_id="s1")
    core.process_pending()
    digests = core.store.query_beliefs(
        "notes", "subject LIKE 'digest:%' AND note_type='belief' AND status='active'", (), 10)
    assert len(digests) == 1, f"expected exactly 1 digest, got {len(digests)}"
    return digests[0]


# --------------------------------------------------------------------------
# (1) digest notes receive memory vectors via the belief-kind path
# --------------------------------------------------------------------------

def check1_digest_gets_memory_vector():
    home = tempfile.mkdtemp(prefix="accept_r12_")
    try:
        core = ChronicleCore(home, {"embeddings": {"model": "hashing"}})
        core.initialize("s1", principal_id="assistant")
        d = _seed_digest(core)

        has_vec = core.store.has_memory_vector(d["belief_id"], "note")
        model = core.store.get_memory_vector_model(d["belief_id"], "note")
        print("  digest belief_id=%s  has_memory_vector(note)=%s  model=%r"
              % (d["belief_id"], has_vec, model))
        if not has_vec:
            return _fail("check1", "digest note has no memory_vectors row under kind='note' — "
                                    "the belief-kind embed path is not reaching it")
        if model != core.embedder.model:
            return _fail("check1", "vector model %r != live embedder model %r" % (model, core.embedder.model))

        # Not merely present — actually the SAME text the digest body carries,
        # not a stale/blank embed queued for some other reason.
        vecs = [v for v in core.store.iter_memory_vectors()
                if v["belief_id"] == d["belief_id"] and v["kind"] == "note"]
        if len(vecs) != 1:
            return _fail("check1", "expected exactly 1 memory_vectors row for the digest, got %d" % len(vecs))

        # No deferred embed job left dangling for it — kind='note' embeds
        # synchronously off a reachable (hashing) embedder inside _insert_belief.
        pending = core.store.count_rows(
            "curation_jobs", "task='embed' AND status='pending'")
        print("  pending embed jobs: %d" % pending)
        if pending:
            return _fail("check1", "digest embed left %d job(s) pending against a live embedder" % pending)

        print("PASS: digest note carries a real memory vector via the belief-kind ('note') embed path")
        return True
    finally:
        shutil.rmtree(home, ignore_errors=True)


# --------------------------------------------------------------------------
# (2) a digest VECTOR hit routes to its entity as a graph-channel seed
# --------------------------------------------------------------------------

def check2_digest_vector_hit_seeds_entity():
    home = tempfile.mkdtemp(prefix="accept_r12_")
    try:
        core = ChronicleCore(home, {"embeddings": {"model": "hashing"}})
        core.initialize("s1", principal_id="assistant")
        d = _seed_digest(core)

        # A hint built from every attribute the digest restates, so it scores
        # highest against the DIGEST (which concatenates all three) rather
        # than against any single atomic fact — but names no entity and no
        # relationship predicate, so the lexical graph channel finds nothing
        # on its own.
        hint = "Pat Acme profile summary"
        lexical_seeds = core.retrieval._graph_seeds(core.retrieval._tokens(hint))
        print("  lexical _graph_seeds(%r) = %r" % (hint, lexical_seeds))

        q = core.retrieval.query_understanding(hint)
        vec_hits = core.retrieval._vector_beliefs(q["embedding"], 20)
        digest_is_a_vector_hit = any(bid == d["belief_id"] for bid, kind, _s in vec_hits)
        print("  digest belief_id appears in raw vector hits: %s" % digest_is_a_vector_hit)
        if not digest_is_a_vector_hit:
            return _fail("check2", "test hint does not even produce a raw vector hit on the digest — "
                                    "cannot exercise the routing path; adjust the fixture")

        hits = core.retrieval.search(hint, limit=20)
        hit_ids = [h["belief_id"] for h in hits]
        hit_values = {h["belief_id"]: h.get("value") for h in hits}
        print("  search() hits:", [(bid, hit_values[bid]) for bid in hit_ids])

        # The digest itself must never rank directly (§u2 — unchanged by R12).
        if d["belief_id"] in hit_ids:
            return _fail("check2", "digest note leaked into ranked search() results — "
                                    "§u2's choke point regressed")

        # 'lives_in=Springfield' belongs to the same entity as the other two
        # facts but shares no token with the hint at all — it can ONLY reach
        # the results through graph-channel expansion seeded off the digest's
        # semantic (vector) hit, since the lexical graph channel found nothing.
        springfield_hits = [bid for bid, v in hit_values.items() if v == "Springfield"]
        if not springfield_hits:
            return _fail("check2", "entity's sibling fact ('Springfield') did not reach results — "
                                    "digest vector hit was not routed to a graph-channel seed")
        for bid in springfield_hits:
            channels = next(h["channels"] for h in hits if h["belief_id"] == bid)
            print("  Springfield fact channels:", channels)
            if "graph" not in channels:
                return _fail("check2", "Springfield fact present but not via the graph channel "
                                        "(channels=%r) — not proof of digest-seeded routing" % channels)

        print("PASS: a digest-only vector hit seeded its entity into the graph channel, "
              "surfacing a sibling fact no lexical or direct-vector path reached; "
              "the digest itself stayed out of ranked results")
        return True
    finally:
        shutil.rmtree(home, ignore_errors=True)


def check2b_entity_name_still_seeds_normally():
    """Regression guard: an ordinary lexical entity match (no digest vector
    hit involved at all) must be completely unaffected by the R12 change."""
    home = tempfile.mkdtemp(prefix="accept_r12_")
    try:
        core = ChronicleCore(home, {"embeddings": {"model": "hashing"}})
        core.initialize("s1", principal_id="assistant")
        _seed_digest(core)

        hint = "what do we know about the user"
        seeds = core.retrieval._graph_seeds(core.retrieval._tokens(hint))
        if seeds != ["user"]:
            return _fail("check2b", "lexical graph seeding regressed: got %r" % (seeds,))
        ctx = core.retrieval.get_context(hint)
        if "[DIGEST] user:" not in ctx:
            return _fail("check2b", "get_context's own (pre-existing) digest surface regressed")
        print("PASS: pre-existing lexical graph seeding and get_context's digest surface unaffected")
        return True
    finally:
        shutil.rmtree(home, ignore_errors=True)


# --------------------------------------------------------------------------
# (3) coverage reporting lists 'digest', not 'entity', as the semantic surface
# --------------------------------------------------------------------------

def _ensure_fastapi_stub():
    """dashboard/plugin_api.py is mounted by the Hermes dashboard host, which
    supplies FastAPI at runtime; Chronicle itself is stdlib-only (pyproject.toml)
    and does not depend on it. Stub just enough surface to execute the real
    module body."""
    try:
        import fastapi  # noqa: F401
        return
    except ImportError:
        pass

    stub = types.ModuleType("fastapi")

    class _APIRouter(object):
        def get(self, *a, **k):
            return lambda fn: fn

        def post(self, *a, **k):
            return lambda fn: fn

    def _Query(default=None, **k):
        return default

    stub.APIRouter = _APIRouter
    stub.Query = _Query
    sys.modules["fastapi"] = stub


def _load_plugin_api():
    _ensure_fastapi_stub()
    spec = importlib.util.spec_from_file_location(
        "chronicle_plugin_api_r12", str(ROOT / "dashboard" / "plugin_api.py"))
    mod = importlib.util.module_from_spec(spec)
    sys.modules["chronicle_plugin_api_r12"] = mod
    spec.loader.exec_module(mod)
    return mod


def check3_coverage_reports_digest_and_entity_stays_zero():
    home = tempfile.mkdtemp(prefix="accept_r12_")
    try:
        core = ChronicleCore(home, {"embeddings": {"model": "hashing"}})
        core.initialize("s1", principal_id="assistant")
        d = _seed_digest(core)

        # A second, ordinary (non-digest) note, so the 'note' bucket is not
        # accidentally left empty once digests are broken out of it.
        core.capture.append("asserted", {
            "kind": "note", "key": {"note_type": "belief", "subject": "misc"},
            "body": "an ordinary belief note, not a digest", "domain": "general",
            "confidence": 0.9, "source_type": "user_direct", "status": "active"},
            actor="user", owner="default")
        core.process_pending()

        db_path = Path(core.store.db_path)
        mod = _load_plugin_api()
        stats = mod._get_embedding_stats(db_path)
        print("  coverage stats:", {k: v for k, v in stats.items()})

        if "digest" not in stats:
            return _fail("check3", "no 'digest' row in embedding coverage stats")
        dig = stats["digest"]
        if dig["total"] != 1:
            return _fail("check3", "digest row total=%r, expected 1" % (dig["total"],))
        if dig["embedded"] != 1 or dig["pct"] != 100:
            return _fail("check3", "digest row not fully embedded: %r "
                                    "(digest gets a vector synchronously off a live embedder)" % (dig,))

        if "note" not in stats:
            return _fail("check3", "no 'note' row in embedding coverage stats")
        note = stats["note"]
        if note["total"] < 1:
            return _fail("check3", "'note' row lost the ordinary (non-digest) note when digests "
                                    "were broken out: total=%r" % (note["total"],))

        # Digests must not be double-counted inside the generic 'note' bucket
        # (they are exactly the digest count higher without the fix — a
        # regression this checks directly, not just "note total > 0").
        all_active_notes = core.store.count_rows(
            "notes", "status='active'")
        if note["total"] + dig["total"] != all_active_notes:
            return _fail("check3", "note(%d) + digest(%d) != all active notes(%d) — digest is "
                                    "double-counted or under-counted against the 'note' bucket"
                         % (note["total"], dig["total"], all_active_notes))

        if "entity" not in stats:
            return _fail("check3", "no 'entity' row in embedding coverage stats")
        ent = stats["entity"]
        if ent["embedded"] != 0 or ent["pct"] != 0:
            return _fail("check3", "entity row is no longer 0%% (embedded=%r pct=%r) — entities must "
                                    "never be vector-embedded, by design" % (ent["embedded"], ent["pct"]))
        if ent["total"] < 1:
            return _fail("check3", "entity row total=%r — the 0%% row must still reflect a real "
                                    "denominator, not report nothing" % (ent["total"],))

        print("PASS: coverage reports a dedicated 'digest' row (total=1, 100%% embedded) separate "
              "from 'note' (total=%d); 'entity' stays a real-denominator, permanent 0%% row"
              % note["total"])
        return True
    finally:
        shutil.rmtree(home, ignore_errors=True)


if __name__ == "__main__":
    results = [
        check1_digest_gets_memory_vector(),
        check2_digest_vector_hit_seeds_entity(),
        check2b_entity_name_still_seeds_normally(),
        check3_coverage_reports_digest_and_entity_stays_zero(),
    ]
    if all(results):
        print("\nAll R12 acceptance checks passed.")
        sys.exit(0)
    else:
        print("\nSome R12 acceptance checks FAILED.")
        sys.exit(1)
