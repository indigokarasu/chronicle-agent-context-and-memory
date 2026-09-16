"""
Chronicle — tests for host-model piggyback plumbing (Ladder 9, task H1).

Coverage maps 1:1 onto the spec's acceptance list:

  (a) enabled + valid fenced JSON  -> facts land through the NORMAL assert path
      with provenance `source: host_model`
  (b) enabled + invalid JSON / wrong schema / no fence / oversized / misaddressed
      -> nothing written, request expired, no exception, heuristic path untouched
  (c) disabled (the default)       -> zero behavioral difference. Proven twice:
      structurally (no registry rows, no attachment, no parse) and empirically,
      by diffing a full store dump against the actual pre-H1 tree
  (d) at most ONE request attached per turn, even with a full queue
  (e) rendered requests are <=400 chars, enforced not merely aimed at
  (f) queue cap + oldest-expiry
  plus the schema_version 5 -> 6 old-DB upgrade.

Fixtures are obviously fake (Pat Testley, Acme Fake Co, Sam Vimes) per the
ladder's shared constraints.
"""

from __future__ import annotations

import json
import os
import shutil
import sqlite3
import subprocess
import sys
import tempfile        # A11 converted every call site it SAW to temp_home();
                      # the sites below are class-scoped (temp_home's dirs are
                      # reaped after each TEST, which would delete a setUpClass
                      # home mid-class) or have their own try/finally cleanup.
                      # conftest still sandboxes TMPDIR, so nothing escapes.
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from _tmp_support import temp_home
sys.path.insert(0, str(Path(__file__).parent))

from engine.hostmodel import (  # noqa: E402
    EXTRACTOR_VERSION,
    MAX_PENDING,
    MAX_REQUEST_CHARS,
    PROVENANCE_SOURCE,
    HostModelRegistry,
    parse_reply,
    render_request,
)
from engine.embeddings import embedder_model_tag  # noqa: E402
from engine.store import SCHEMA_VERSION, MemoryStore, _has_col, _has_table  # noqa: E402
# The dump's exclusion list and turn fixture, imported rather than restated: the
# emptiness assertions below are DERIVED from the exclusion list, so that
# excluding a row-bearing table can never pass silently.
from h1_store_dump import DELIBERATE_MODEL_COLUMNS, H1_TABLES, TURNS  # noqa: E402
from provider import ChronicleMemoryProvider  # noqa: E402

# The tree this one must be byte-identical to at default config.
#
# H1 was built directly on v550, so that WAS the right baseline standalone. It
# is not the right baseline inside the ladder-9 integration: eleven other tasks
# landed first and several of them intentionally change what a capture writes
# (E2 adds query_proxy_vectors rows, E5 adds novelty/occurrence_count values,
# E4 adds supersede_candidates, E7 adds entity_centroids). Diffing against v550
# would therefore report those deliberate changes as H1 regressions and prove
# nothing about H1 either way.
#
# The claim H1 actually makes -- "with piggyback off, the store is what it was
# WITHOUT H1" -- is isolated by diffing against the integration commit
# immediately before this merge. That was a git worktree pinned at `L9 E7`
# (`v560_preH1`).
#
# Ladder 10 A4 RE-BASELINES that worktree, for a reason worth stating rather
# than just doing. A4 removed the `uuid.uuid4` pin from h1_store_dump.py --
# the pin existed to hide the very defect A4 fixed -- and with it gone the
# pre-A4 tree cannot produce the same dump TWICE: `extractions.id` and
# `identity_candidates.id` were minted per run, and two consecutive probes of
# `v560_preH1` differ on exactly those four rows (measured). A tree that
# disagrees with itself is not a baseline. A4 also intentionally changes those
# same two id columns (uuid4 -> content hash), so even a stable pre-A4 dump
# would report an intended change as an H1 regression -- exactly the reason
# v550 stopped being the baseline at the top of this comment.
#
# The pin is therefore a worktree at A4's own commit, L10_A4_base. The v5.7.0
# integration uses that ONE baseline for all three inertness probes (this one
# and the two in tests/test_acl_topology.py).
#
# A6 is the first post-H1 task that deliberately changes what a DEFAULT capture
# flow writes: the heuristic floor now captures multiple facts per sentence,
# reaches real email addresses, and refuses to file a first-person preference as
# an always-inject norm. Diffing against the bare pin would therefore report
# A6's intended effect as a regression, proving nothing either way.
#
# Re-pinning cannot fix that, because the baseline this test needs is
# "everything in this tree EXCEPT the thing under test", and no commit carries
# A6's extraction without H1 -- H1 landed first. So the pin stays and A6's two
# files are OVERLAID onto a scratch copy of it (BASE_OVERLAY below). Base and
# head then differ by everything except A6's extraction, and since that
# everything is asserted here to be inert, the dumps must match.
#
# The overlay is well defined, and it was re-verified when the pin moved:
# `engine/extraction.py` and `engine/criticality.py` are byte-identical at
# `L9 E7` (65cfa12), at v5.6.0 (c7ca775) and at A4 (1e2b3c2, = L10_A4_base),
# so copying this tree's copies in really is applying A6's patch to the base.
# This tree's extraction.py additionally carries A2's allow_remote guard, which
# is inert at defaults -- and that it is inert is not assumed here, it is what
# this test measured green at every integration step BEFORE A6 landed.
#
# What the assertion therefore says now, at full strength: A6 is the ONLY thing
# in the entire ladder-10 merge that changes the default capture flow.
# Override with CHRONICLE_BASE_TREE to point elsewhere.
BASE_TREE = Path(os.environ.get("CHRONICLE_BASE_TREE")
                 or (Path(__file__).parent.parent.parent / "L10_A4_base"))
PROBE = Path(__file__).parent / "h1_store_dump.py"
# The files A6 changes. Kept explicit and short: an overlay wide enough to carry
# H1 itself would make the test vacuous, so it may only ever list files whose
# base revision this tree's commit is a direct descendant of.
BASE_OVERLAY = ("engine/extraction.py", "engine/criticality.py")


def fenced(obj) -> str:
    """A host reply carrying `obj` in the one accepted block shape."""
    return "Sure thing.\n```json\n%s\n```\nAnything else?" % json.dumps(obj)


class _ProviderCase(unittest.TestCase):
    """A live provider over a throwaway store. `piggyback` is the only knob."""

    piggyback = True

    def setUp(self):
        self.home = temp_home(prefix="h1-")
        config = {"embeddings": {"model": "hashing"}}
        if self.piggyback is not None:
            config["host_model"] = {"piggyback": self.piggyback}
        self.provider = ChronicleMemoryProvider()
        self.provider.initialize("s-h1", hermes_home=self.home, principal_id="assistant",
                                 config=config)
        self.core = self.provider.core
        self.registry = self.core.host_model

    def tearDown(self):
        shutil.rmtree(self.home, ignore_errors=True)

    # -- helpers ----------------------------------------------------------

    def facts(self):
        return self.core.store.query_beliefs("facts", "1=1", (), 100)

    def host_facts(self):
        out = []
        for row in self.facts():
            prov = json.loads(row.get("provenance") or "{}")
            if prov.get("source") == PROVENANCE_SOURCE:
                out.append(row)
        return out

    def attach_one(self) -> str:
        """Run the attach hook and return the request id now in flight."""
        rendered = self.provider.pre_llm_call()
        self.assertTrue(rendered, "expected a request to be attached")
        self.assertLessEqual(len(rendered), MAX_REQUEST_CHARS)
        return self.registry.attached_request()["request_id"]

    def offer_turn(self, user="Pat Testley started at Acme Fake Co last week.",
                   assistant="Good to know."):
        self.provider.sync_turn(user, assistant, session_id="s-h1")


# ---------------------------------------------------------------------------
# (a) enabled + a valid reply -> facts via the normal write path
# ---------------------------------------------------------------------------
class TestValidReplyLandsFacts(_ProviderCase):
    def test_valid_fenced_json_writes_fact_with_host_model_provenance(self):
        self.offer_turn()
        rid = self.attach_one()
        self.provider.sync_turn("thanks", fenced({
            "request_id": rid, "kind": "extract_facts",
            "facts": [{"subject": "Pat Testley", "attribute": "works_at", "value": "Acme Fake Co"}]}),
            session_id="s-h1")

        landed = self.host_facts()
        self.assertEqual(len(landed), 1)
        row = landed[0]
        self.assertEqual(row["entity_id"], "pat_testley")
        self.assertEqual(row["predicate_canonical"], "works_at")
        self.assertEqual(row["value"], "Acme Fake Co")
        self.assertEqual(row["status"], "active")
        self.assertEqual(row["extractor_version"], EXTRACTOR_VERSION)
        prov = json.loads(row["provenance"])
        self.assertEqual(prov["source"], "host_model")
        # ... and it is the ORDINARY belief envelope otherwise: same provenance
        # keys, real confidence, indexed for search like any other fact.
        self.assertEqual(prov["source_type"], "session_transcript")
        self.assertIn("extracted_at", prov)
        self.assertGreater(row["confidence"], 0)
        self.assertEqual(self.registry.get(rid)["status"], "answered")

    def test_user_subject_routes_to_the_user_entity(self):
        self.offer_turn("I just joined Acme Fake Co.", "Congratulations.")
        rid = self.attach_one()
        self.provider.sync_turn("yes", fenced({
            "request_id": rid, "kind": "extract_facts",
            "facts": [{"subject": "user", "attribute": "works_at", "value": "Acme Fake Co"}]}),
            session_id="s-h1")
        landed = self.host_facts()
        self.assertEqual(len(landed), 1)
        self.assertEqual(landed[0]["entity_id"], "user")
        self.assertEqual(json.loads(landed[0]["provenance"])["source_type"], "user_direct")

    def test_multiple_facts_all_land(self):
        self.offer_turn()
        rid = self.attach_one()
        self.provider.sync_turn("ok", fenced({
            "request_id": rid, "kind": "extract_facts", "facts": [
                {"subject": "Pat Testley", "attribute": "works_at", "value": "Acme Fake Co"},
                {"subject": "Pat Testley", "attribute": "lives_in", "value": "Fake City"}]}),
            session_id="s-h1")
        self.assertEqual(len(self.host_facts()), 2)

    def test_answered_request_is_not_reattached(self):
        self.offer_turn()
        rid = self.attach_one()
        self.provider.sync_turn("ok", fenced({
            "request_id": rid, "kind": "extract_facts",
            "facts": [{"subject": "Sam Vimes", "attribute": "works_at", "value": "Acme Fake Co"}]}),
            session_id="s-h1")
        self.assertEqual(self.registry.get(rid)["status"], "answered")
        # The next attach picks up the request the reply turn itself enqueued —
        # an answered request is never offered again.
        self.assertTrue(self.provider.pre_llm_call())
        self.assertNotEqual(self.registry.attached_request()["request_id"], rid)


# ---------------------------------------------------------------------------
# (b) enabled + a bad reply -> expired, nothing written, no exception
# ---------------------------------------------------------------------------
class TestBadRepliesAreDroppedSilently(_ProviderCase):
    def _reject(self, reply_text):
        """Offer a turn, attach, feed `reply_text` back, assert nothing landed."""
        self.offer_turn("My name is Pat Testley and I work at Acme Fake Co in Fake City.",
                        "Noted, Pat - Acme Fake Co in Fake City it is.")
        rid = self.attach_one()
        self.provider.sync_turn("ok", reply_text, session_id="s-h1")  # must not raise
        self.assertEqual(self.host_facts(), [], "a rejected reply wrote a belief")
        self.assertEqual(self.registry.get(rid)["status"], "expired")
        # The heuristic path is untouched: draining curation still yields exactly
        # the beliefs the heuristic extractor always produced for that turn (the
        # first-person name fact and the turn's episode), and not one of them
        # carries host-model provenance.
        self.core.process_pending()
        self.assertTrue(self.core.store.query_beliefs("episodes", "1=1", (), 10))
        self.assertIn(("user", "name", "Pat Testley"),
                      [(f["entity_id"], f["attribute"], f["value"]) for f in self.facts()])
        self.assertEqual(self.host_facts(), [])

    def test_no_fence_at_all(self):
        self._reject("Pat Testley works at Acme Fake Co, I think.")

    def test_fence_without_json_tag(self):
        self._reject("```\n{\"facts\": []}\n```")

    def test_malformed_json(self):
        self._reject("```json\n{this is not json at all,,}\n```")

    def test_json_array_instead_of_object(self):
        self._reject("```json\n[1, 2, 3]\n```")

    def test_unterminated_fence(self):
        self._reject('```json\n{"request_id": "x", "kind": "extract_facts", "facts": []}')

    def test_extra_top_level_key_is_rejected(self):
        self.offer_turn()
        rid = self.attach_one()
        self._reject_payload(rid, {
            "request_id": rid, "kind": "extract_facts", "confidence": 0.9,
            "facts": [{"subject": "Pat Testley", "attribute": "works_at", "value": "Acme Fake Co"}]})

    def test_missing_facts_key_is_rejected(self):
        self.offer_turn()
        rid = self.attach_one()
        self._reject_payload(rid, {"request_id": rid, "kind": "extract_facts"})

    def test_wrong_kind_is_rejected(self):
        self.offer_turn()
        rid = self.attach_one()
        self._reject_payload(rid, {"request_id": rid, "kind": "doc2query", "questions": ["where?"]})

    def test_wrong_request_id_is_rejected(self):
        self.offer_turn()
        rid = self.attach_one()
        self._reject_payload(rid, {
            "request_id": "deadbeefcafe", "kind": "extract_facts",
            "facts": [{"subject": "Pat Testley", "attribute": "works_at", "value": "Acme Fake Co"}]})

    def test_extra_key_inside_a_fact_is_rejected(self):
        self.offer_turn()
        rid = self.attach_one()
        self._reject_payload(rid, {"request_id": rid, "kind": "extract_facts", "facts": [
            {"subject": "Pat Testley", "attribute": "works_at", "value": "Acme Fake Co",
             "confidence": 0.9}]})

    def test_non_string_value_is_rejected(self):
        self.offer_turn()
        rid = self.attach_one()
        self._reject_payload(rid, {"request_id": rid, "kind": "extract_facts", "facts": [
            {"subject": "Pat Testley", "attribute": "headcount", "value": 42}]})

    def test_empty_facts_list_is_rejected(self):
        self.offer_turn()
        rid = self.attach_one()
        self._reject_payload(rid, {"request_id": rid, "kind": "extract_facts", "facts": []})

    def test_too_many_facts_is_rejected(self):
        self.offer_turn()
        rid = self.attach_one()
        self._reject_payload(rid, {"request_id": rid, "kind": "extract_facts", "facts": [
            {"subject": "Sam Vimes", "attribute": "likes", "value": "item %d" % i}
            for i in range(9)]})

    def test_oversized_block_is_rejected(self):
        self.offer_turn()
        rid = self.attach_one()
        self._reject_payload(rid, {"request_id": rid, "kind": "extract_facts", "facts": [
            {"subject": "Pat Testley", "attribute": "works_at", "value": "x" * 5000}]})

    def test_dotted_attribute_is_rejected(self):
        self.offer_turn()
        rid = self.attach_one()
        self._reject_payload(rid, {"request_id": rid, "kind": "extract_facts", "facts": [
            {"subject": "Pat Testley", "attribute": "user.works_at", "value": "Acme Fake Co"}]})

    def _reject_payload(self, rid, obj):
        self.provider.sync_turn("ok", fenced(obj), session_id="s-h1")
        self.assertEqual(self.host_facts(), [], "a rejected reply wrote a belief")
        self.assertEqual(self.registry.get(rid)["status"], "expired")


# ---------------------------------------------------------------------------
# Pure validator/renderer units — no store.
# ---------------------------------------------------------------------------
class TestParseAndValidate(unittest.TestCase):
    def _req(self, kind="extract_facts", payload=None):
        return {"request_id": "abc123abc123", "kind": kind,
                "payload": json.dumps(payload or {"text": "Pat Testley joined Acme Fake Co."})}

    def test_valid_extract_facts(self):
        req = self._req()
        out = parse_reply(fenced({
            "request_id": "abc123abc123", "kind": "extract_facts",
            "facts": [{"subject": " Pat Testley ", "attribute": "works_at",
                       "value": " Acme Fake Co "}]}), req)
        self.assertEqual(out, {"kind": "extract_facts", "facts": [
            {"subject": "Pat Testley", "attribute": "works_at", "value": "Acme Fake Co"}]})

    def test_size_gate_is_independent_of_schema(self):
        """The same VALID reply passes at the default cap and is dropped under a
        small one — so the oversize rejection is really the size gate."""
        req = self._req()
        reply = fenced({"request_id": "abc123abc123", "kind": "extract_facts",
                        "facts": [{"subject": "Pat Testley", "attribute": "works_at",
                                   "value": "Acme Fake Co"}]})
        self.assertIsNotNone(parse_reply(reply, req))
        self.assertIsNone(parse_reply(reply, req, 50))

    def test_empty_and_none_inputs(self):
        self.assertIsNone(parse_reply("", self._req()))
        self.assertIsNone(parse_reply(None, self._req()))
        self.assertIsNone(parse_reply(fenced({}), None))

    def test_nested_object_inside_the_block_still_matches_the_fence(self):
        req = self._req()
        self.assertIsNone(parse_reply(fenced({
            "request_id": "abc123abc123", "kind": "extract_facts",
            "facts": [{"subject": "Pat", "attribute": "works_at", "value": {"nested": 1}}]}), req))

    def test_doc2query_valid_and_bounds(self):
        req = self._req("doc2query")
        ok = parse_reply(fenced({"request_id": "abc123abc123", "kind": "doc2query",
                                 "questions": ["Where does Pat Testley work?"]}), req)
        self.assertEqual(ok["questions"], ["Where does Pat Testley work?"])
        self.assertIsNone(parse_reply(fenced({
            "request_id": "abc123abc123", "kind": "doc2query",
            "questions": ["q%d" % i for i in range(5)]}), req))       # >4
        self.assertIsNone(parse_reply(fenced({
            "request_id": "abc123abc123", "kind": "doc2query", "questions": []}), req))
        self.assertIsNone(parse_reply(fenced({
            "request_id": "abc123abc123", "kind": "doc2query", "questions": [7]}), req))

    def test_rerank_valid_and_bounds(self):
        req = self._req("rerank", {"query": "where does Pat work",
                                   "candidates": ["a", "b", "c"]})
        self.assertEqual(parse_reply(fenced({
            "request_id": "abc123abc123", "kind": "rerank", "order": [2, 0, 1]}), req),
            {"kind": "rerank", "order": [2, 0, 1]})
        for bad in ([3], [0, 0], [-1], ["0"], [True], [], list(range(60))):
            self.assertIsNone(parse_reply(fenced({
                "request_id": "abc123abc123", "kind": "rerank", "order": bad}), req),
                "order %r should be rejected" % (bad,))

    def test_rerank_without_candidates_is_rejected(self):
        req = self._req("rerank", {"query": "q"})
        self.assertIsNone(parse_reply(fenced({
            "request_id": "abc123abc123", "kind": "rerank", "order": [0]}), req))


# ---------------------------------------------------------------------------
# (e) rendering is bounded
# ---------------------------------------------------------------------------
class TestRenderingIsBounded(unittest.TestCase):
    def _render(self, kind, payload):
        return render_request({"request_id": "abc123abc123", "kind": kind,
                               "payload": json.dumps(payload)})

    def test_every_kind_stays_within_400_chars_on_a_huge_payload(self):
        cases = (("extract_facts", {"text": "Pat Testley. " * 4000}),
                 ("doc2query", {"text": "Acme Fake Co. " * 4000}),
                 ("rerank", {"query": "q" * 4000,
                             "candidates": ["candidate %d %s" % (i, "z" * 500)
                                            for i in range(200)]}))
        for kind, payload in cases:
            rendered = self._render(kind, payload)
            self.assertLessEqual(len(rendered), MAX_REQUEST_CHARS, kind)
            self.assertIn("abc123abc123", rendered, kind)
            self.assertIn(kind, rendered, kind)

    def test_config_can_shrink_but_never_grow_the_cap(self):
        store = _MemStoreStub()
        big = HostModelRegistry(store, _CfgStub({"host_model.max_request_chars": 100000}))
        self.assertEqual(big.request_char_cap(), MAX_REQUEST_CHARS)
        small = HostModelRegistry(store, _CfgStub({"host_model.max_request_chars": 120}))
        self.assertEqual(small.request_char_cap(), 120)
        rendered = render_request({"request_id": "abc123abc123", "kind": "extract_facts",
                                   "payload": json.dumps({"text": "x" * 900})},
                                  small.request_char_cap())
        self.assertLessEqual(len(rendered), 120)

    def test_no_literal_fence_in_the_request(self):
        """Chronicle's own request text must not look like a reply."""
        rendered = self._render("extract_facts", {"text": "Pat Testley joined Acme Fake Co."})
        self.assertNotIn("```", rendered)

    def test_unknown_or_empty_request_renders_nothing(self):
        self.assertEqual(render_request(None), "")
        self.assertEqual(render_request({"request_id": "x", "kind": "nope", "payload": "{}"}), "")


class _CfgStub:
    def __init__(self, values):
        self._v = values

    def get(self, path, default=None):
        return self._v.get(path, default)


class _MemStoreStub:
    pass


# ---------------------------------------------------------------------------
# (d) one per turn, and (f) queue cap + oldest-expiry
# ---------------------------------------------------------------------------
class TestQueueDiscipline(_ProviderCase):
    def test_queue_cap_expires_the_oldest_pending_first(self):
        ids = [self.registry.enqueue("extract_facts", {"text": "turn %d" % i, "n": i})
               for i in range(MAX_PENDING + 8)]
        counts = self.registry.counts()
        self.assertEqual(counts["pending"], MAX_PENDING)
        self.assertEqual(counts["expired"], 8)
        for rid in ids[:8]:
            self.assertEqual(self.registry.get(rid)["status"], "expired")
        for rid in ids[8:]:
            self.assertEqual(self.registry.get(rid)["status"], "pending")

    def test_configured_cap_is_honoured(self):
        registry = HostModelRegistry(self.core.store,
                                     _CfgStub({"host_model.max_pending": 3}))
        for i in range(5):
            registry.enqueue("extract_facts", {"text": "t%d" % i})
        self.assertEqual(registry.counts()["pending"], 3)

    def test_at_most_one_request_attached_per_turn_with_a_full_queue(self):
        for i in range(MAX_PENDING + 8):
            self.registry.enqueue("extract_facts", {"text": "turn %d" % i})
        rendered = self.provider.pre_llm_call()
        self.assertTrue(rendered)
        self.assertLessEqual(len(rendered), MAX_REQUEST_CHARS)
        attached = [r for r in self.registry.list_requests(limit=200) if r["attached_at"]]
        self.assertEqual(len(attached), 1)
        # A second call in the same turn attaches nothing: one in flight, always.
        self.assertEqual(self.provider.pre_llm_call(), "")
        attached = [r for r in self.registry.list_requests(limit=200) if r["attached_at"]]
        self.assertEqual(len(attached), 1)

    def test_fifo_order_oldest_pending_attaches_first(self):
        first = self.registry.enqueue("extract_facts", {"text": "oldest"})
        self.registry.enqueue("extract_facts", {"text": "newer"})
        self.assertIn(first, self.provider.pre_llm_call())

    def test_empty_queue_attaches_nothing(self):
        self.assertEqual(self.provider.pre_llm_call(), "")

    def test_unknown_kind_is_refused(self):
        with self.assertRaises(ValueError):
            self.registry.enqueue("summarize_everything", {})


# ---------------------------------------------------------------------------
# (c) doc2query / rerank land in the holding table — E2/E3 are NOT reimplemented
# ---------------------------------------------------------------------------
class TestHoldingTableForUnintegratedKinds(_ProviderCase):
    def test_doc2query_result_is_parked_not_written_as_a_belief(self):
        rid = self.registry.enqueue("doc2query", {"belief_id": "b_fake",
                                                  "text": "Pat Testley works at Acme Fake Co."})
        self.provider.pre_llm_call()
        before = len(self.facts())
        self.provider.sync_turn("ok", fenced({
            "request_id": rid, "kind": "doc2query",
            "questions": ["Where does Pat Testley work?", "Who works at Acme Fake Co?"]}),
            session_id="s-h1")
        self.assertEqual(self.registry.get(rid)["status"], "answered")
        self.assertEqual(len(self.facts()), before)  # no belief written
        parked = self.registry.results(kind="doc2query")
        self.assertEqual(len(parked), 1)
        self.assertEqual(json.loads(parked[0]["result"])["questions"],
                         ["Where does Pat Testley work?", "Who works at Acme Fake Co?"])

    def test_rerank_result_is_parked(self):
        rid = self.registry.enqueue("rerank", {"query": "where does Pat work",
                                               "candidates": ["a", "b", "c"]})
        self.provider.pre_llm_call()
        self.provider.sync_turn("ok", fenced({
            "request_id": rid, "kind": "rerank", "order": [2, 0]}), session_id="s-h1")
        parked = self.registry.results(kind="rerank")
        self.assertEqual(len(parked), 1)
        self.assertEqual(json.loads(parked[0]["result"])["order"], [2, 0])


# ---------------------------------------------------------------------------
# (c) DISABLED BY DEFAULT — the critical property
# ---------------------------------------------------------------------------
class TestDisabledByDefaultIsInert(_ProviderCase):
    piggyback = None  # no host_model key at all: pure DEFAULTS

    def test_default_config_has_piggyback_off(self):
        self.assertFalse(self.core.cfg.get("host_model.piggyback"))
        self.assertFalse(self.registry.enabled())

    def test_full_flow_at_defaults_writes_nothing_to_the_registry(self):
        for user, assistant in (("My name is Pat Testley.", "Hello, Pat."),
                                ("I work at Acme Fake Co.", "Noted."),
                                ("Always answer in metric.", "Understood.")):
            self.assertEqual(self.provider.pre_llm_call(), "")
            self.provider.sync_turn(user, assistant, session_id="s-h1")
            self.core.process_pending()
        # Nothing enqueued, nothing attached, nothing parked.
        self.assertEqual(self.registry.counts(), {"pending": 0, "answered": 0, "expired": 0})
        self.assertEqual(self.registry.list_requests(), [])
        self.assertEqual(self.registry.results(), [])
        # The heuristic path ran normally...
        self.assertTrue(self.facts())
        # ... and NOT ONE belief carries host-model provenance.
        self.assertEqual(self.host_facts(), [])

    def test_a_fenced_json_reply_is_ignored_entirely_when_disabled(self):
        """Even a perfectly-formed reply is inert: nothing was ever asked."""
        self.provider.sync_turn("Tell me about Pat.", fenced({
            "request_id": "abc123abc123", "kind": "extract_facts",
            "facts": [{"subject": "Pat Testley", "attribute": "works_at",
                       "value": "Acme Fake Co"}]}), session_id="s-h1")
        self.assertEqual(self.registry.list_requests(), [])
        self.assertEqual(self.host_facts(), [])

    def test_excluded_tables_exist_and_are_empty_after_a_real_flow(self):
        """Derived from the dump's OWN exclusion list, and asserted after the
        dump's own turn fixture has actually run.

        Both halves matter. Naming the tables here instead of reading H1_TABLES
        would leave the exclusion list unguarded — adding a row-bearing table to
        it would quietly remove those rows from the byte-identity comparison
        while every test stayed green. Asserting on a FRESH store would be just
        as weak: every table is empty before anything is written, so the check
        would pass for any table at all. The flow is what gives the emptiness
        claim teeth."""
        for user, assistant in TURNS:
            self.provider.sync_turn(user, assistant, session_id="s-h1")
            self.core.process_pending()

        self.assertTrue(H1_TABLES, "the exclusion list is empty; nothing is being guarded")
        conn = self.core.store._conn()
        for table in H1_TABLES:
            self.assertTrue(_has_table(conn, table), "excluded table %s does not exist" % table)
            self.assertEqual(
                conn.execute("SELECT COUNT(*) FROM %s" % table).fetchone()[0], 0,
                "%s is excluded from the inertness dump but is NOT empty at default "
                "config -- excluding it hides real rows from the byte-identity proof" % table)
        # The flow really did write: without this, "all excluded tables are
        # empty" could hold simply because nothing was stored at all.
        self.assertTrue(self.core.store.iter_memory_vectors())
        self.assertTrue(self.facts())

    def test_deliberate_model_columns_carry_the_active_tag(self):
        """The assertion that LICENSES the dump's DELIBERATE_MODEL_COLUMNS.

        A column excluded from the byte-identity dump is only allowed there if
        something asserts its value directly; otherwise excluding it would hide
        whatever it holds. Derived from the dump's own tuple, for the same
        reason the H1_TABLES check above is: naming session_index.model here
        instead would leave the list unguarded, and a second entry could be
        added with nothing checking it.

        The claim asserted is STRONGER than byte-identity could be. Byte
        identity can only say "this cell matches the base tree's cell", and the
        base tree has no such cell. This says the cell equals
        embedder_model_tag() of the embedder that actually ran -- the A0e
        contract itself -- for every vectored row the flow wrote."""
        for user, assistant in TURNS:
            self.provider.sync_turn(user, assistant, session_id="s-h1")
            self.core.process_pending()
        # The dump probe's flow ends the session; session_index is written by
        # the session_summarize job that ending queues, so without this the
        # table is empty and the assertion below would be vacuous.
        self.provider.on_session_end([])
        self.core.process_pending()

        self.assertTrue(DELIBERATE_MODEL_COLUMNS,
                        "the exclusion tuple is empty; nothing is being guarded")
        active = embedder_model_tag(self.core.embedder)
        self.assertTrue(active, "fixture has no embedder to stamp with")
        conn = self.core.store._conn()
        for table, column in DELIBERATE_MODEL_COLUMNS:
            self.assertTrue(_has_col(conn, table, column),
                            "%s.%s is excluded from the dump but does not exist"
                            % (table, column))
            rows = conn.execute("SELECT %s FROM %s WHERE embedding IS NOT NULL "
                                "AND length(embedding)>0" % (column, table)).fetchall()
            self.assertTrue(rows, "%s wrote no vectored rows: the exclusion would be "
                                  "vacuous" % table)
            for row in rows:
                self.assertEqual(row[0], active,
                                 "%s.%s is hidden from the byte-identity proof and does NOT "
                                 "carry the active canonical tag" % (table, column))

    def test_heuristic_provenance_has_no_source_key_at_all(self):
        """The absence is load-bearing: it is what makes the disabled path
        byte-identical rather than merely equivalent."""
        self.provider.sync_turn("My name is Pat Testley.", "Hello, Pat.", session_id="s-h1")
        self.core.process_pending()
        rows = self.facts()
        self.assertTrue(rows)
        for row in rows:
            self.assertNotIn("source", json.loads(row["provenance"]))


class TestDisabledMatchesPreH1TreeExactly(unittest.TestCase):
    """The empirical half of the disabled-by-default regression.

    Runs ONE identical end-to-end flow (capture -> process -> sync_turn, with the
    attach hook called every turn) against the pre-H1 base tree and against this
    tree, with the clock and uuid4 frozen, then diffs a canonical dump of every
    row of every table. Byte-identical output is the claim; anything else is a
    behavioral regression, wherever it came from.
    """

    def _dump(self, tree: Path) -> str:
        proc = subprocess.run([sys.executable, str(PROBE), str(tree)],
                              cwd=str(tree), stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        self.assertEqual(proc.returncode, 0,
                         "probe failed in %s: %s" % (tree, proc.stderr.decode()[-2000:]))
        return proc.stdout.decode()

    def _this_tree_with_the_a6_patch_backed_out(self, dest: Path) -> Path:
        """A scratch copy of THIS tree carrying the BASE tree's extraction.

        The overlay runs in this direction, not the other one, and the reason is
        a merge fact rather than a preference. A6's own version of this test
        copied THIS tree's `engine/extraction.py` onto a copy of the base. That
        worked while this tree's extraction.py was "v5.6.0 plus A6". After the
        v5.7.0 merge it is "v5.6.0 plus A2 plus A6", and A2's guard imports
        `RemoteEndpointRefused` / `check_endpoint` from `engine.embeddings` --
        symbols the base tree's embeddings.py does not have, so the base would
        not even import. Widening BASE_OVERLAY to carry embeddings.py would drag
        A11b, A0fix and A10b into the "base" and make the comparison vacuous,
        which is exactly what A6's own rule about this list forbids.

        Backing the patch OUT of a copy of this tree keeps the overlay at two
        files and keeps every other module the merged one. The claim is
        unchanged and stated the other way round: with A6's extraction removed,
        this tree writes byte-for-byte what the baseline writes -- so A6 is the
        only thing in the whole ladder-10 merge that changes default capture.

        RESTATED after the reconciliation onto published `main`: A6 is the only
        thing in the ladder-10 MERGE that changes default capture, and upstream's
        `TransitiveLocationRule` (7bfcf46) is the only thing outside it that
        does. Both are backed out here; see
        `_back_out_the_upstream_derivation_rule`. Anything else that appears in
        this diff is still a regression, wherever it came from.
        """
        here = Path(__file__).parent.parent
        shutil.copytree(str(here), str(dest),
                        ignore=shutil.ignore_patterns(".git", "__pycache__", "*.pyc",
                                                      "*.db", "*.db-wal", "*.db-shm"))
        for rel in BASE_OVERLAY:
            self.assertTrue((BASE_TREE / rel).exists(),
                            "overlay file %s does not exist in the base tree; the pin moved "
                            "and the overlay is no longer a patch onto it" % rel)
            shutil.copy2(str(BASE_TREE / rel), str(dest / rel))
        self._back_out_the_upstream_derivation_rule(dest)
        return dest

    # The ONLY rows published `main` writes that the pre-H1 base does not, once
    # A6's extraction and upstream's TransitiveLocationRule are backed out.
    # Enumerated, not pattern-matched: a list that grows silently is how this
    # test would stop meaning anything. Adding to it is a deliberate act that
    # says "upstream changed default capture again, and we looked at it".
    UPSTREAM_CAPTURE_ADDITIONS = ("meta\t[\"profile_summary:",)

    def _assert_only_upstreams_known_capture_additions(self, base_dump, ours_dump):
        """Byte-identical, EXCEPT for upstream's known capture additions.

        `profile_summary:<owner>` (engine/reducer.py, engine/core.py) exists in
        published `main` and in neither the pre-H1 base nor the pre-reconciliation
        v5.7.0 tree, so it is upstream's, it is new, and it is legitimate. It is
        allowed here BY NAME. Every other difference -- in either direction --
        still fails, including a base row that stopped being written, which is
        why this checks both directions rather than just tolerating extra lines.
        """
        import difflib
        base_lines, our_lines = base_dump.splitlines(), ours_dump.splitlines()
        gone, added = [], []
        for line in difflib.unified_diff(base_lines, our_lines, lineterm="", n=0):
            if line.startswith(("+++", "---", "@@")):
                continue
            if line.startswith("-"):
                gone.append(line[1:])
            elif line.startswith("+"):
                added.append(line[1:])
        self.assertEqual(gone, [],
                         "rows the pre-H1 base writes and this tree no longer does:\n%s"
                         % "\n".join(gone[:20]))
        unexpected = [a for a in added
                      if not any(a.startswith(k) for k in self.UPSTREAM_CAPTURE_ADDITIONS)]
        self.assertEqual(unexpected, [],
                         "rows this tree writes that neither the pre-H1 base nor upstream's "
                         "known additions account for:\n%s" % "\n".join(unexpected[:20]))

    def _back_out_the_upstream_derivation_rule(self, dest: Path) -> None:
        """Remove `TransitiveLocationRule` from the scratch copy's starter rules.

        The SECOND thing that changes default capture, found when v5.7.0 was
        reconciled onto published `main`. Upstream 7bfcf46 appended
        `TransitiveLocationRule()` to `derivation._STARTER_RULES`, a hard-coded
        list with no config gate (`derivation.enabled` is DORMANT -- derivation
        cannot be switched off from config), so it fires on the default write
        path and writes a `transitive_location` belief the pre-H1 base never
        wrote. That is legitimate NEW UPSTREAM BEHAVIOUR, not a regression, and
        not something H1 or A6 did -- so the honest repair is to back it out
        alongside A6's extraction and keep the byte-identical claim, rather than
        widen the claim until it stops meaning anything.

        Edited as text on the COPY, in the same direction as the A6 backout and
        for the same reason: the base tree predates the rule and has no version
        of this file that could be overlaid without dragging the rest of v5.7.0's
        derivation.py out of the comparison."""
        f = dest / "engine" / "derivation.py"
        src = f.read_text(encoding="utf-8")
        old = "_STARTER_RULES = [WorkplaceLocationRule(), TransitiveLocationRule()]"
        self.assertIn(old, src,
                      "the starter-rule list moved; this backout is no longer a patch onto it "
                      "and the byte-identical claim must be restated, not silently widened")
        f.write_text(src.replace(old, "_STARTER_RULES = [WorkplaceLocationRule()]", 1),
                     encoding="utf-8")

    def test_store_dump_is_byte_identical_to_the_base_tree(self):
        if not (BASE_TREE / "provider.py").exists():
            self.skipTest("base tree not available at %s" % BASE_TREE)
        base_dump = self._dump(BASE_TREE)
        self.assertTrue(base_dump.strip(), "base probe produced an empty dump")
        scratch = tempfile.mkdtemp(prefix="h1-noa6-")
        try:
            without_a6 = self._this_tree_with_the_a6_patch_backed_out(Path(scratch) / "tree")
            self._assert_only_upstreams_known_capture_additions(
                base_dump, self._dump(without_a6))
        finally:
            shutil.rmtree(scratch, ignore_errors=True)

    def test_the_overlay_is_what_makes_the_dumps_match(self):
        """The overlay must not be able to hide a real regression.

        The bare pin (no overlay) is asserted to DIFFER, so this file can never
        pass by overlaying so much of the tree that the code under test comes
        along with it: if the two dumps ever agree WITHOUT the A6 patch, the
        patch stopped changing the default flow and the overlay should be
        deleted, not kept.
        """
        if not (BASE_TREE / "provider.py").exists():
            self.skipTest("base tree not available at %s" % BASE_TREE)
        here = Path(__file__).parent.parent
        self.assertNotEqual(
            self._dump(BASE_TREE), self._dump(here),
            "the A6 extraction patch no longer changes the default capture flow; "
            "drop BASE_OVERLAY and diff the bare pin again")

    def test_the_probe_itself_is_deterministic(self):
        """Two probes of THIS tree, back to back, with nothing but the capture
        clock pinned. Before A4 this was false -- extractions.id and
        identity_candidates.id were fresh uuid4s per run and only the probe's
        own `uuid.uuid4` monkeypatch hid it -- so the comparison above was
        measuring a pinned artefact, not the store."""
        here = Path(__file__).parent.parent
        first = self._dump(here)
        self.assertTrue(first.strip())
        self.assertEqual(first, self._dump(here),
                         "the default flow still writes a random id somewhere")


# ---------------------------------------------------------------------------
# schema_version 5 -> 6
# ---------------------------------------------------------------------------
class TestSchemaMigration(unittest.TestCase):
    def setUp(self):
        self.dir = temp_home(prefix="h1-mig-")
        self.db = os.path.join(self.dir, "chronicle.db")

    def tearDown(self):
        shutil.rmtree(self.dir, ignore_errors=True)

    def _make_v5_db(self):
        """A store as an older build left it: no host_model_* tables, version 5."""
        store = MemoryStore(self.db)
        store.append_event({
            "event_id": "ev_old", "type": "observed",
            "payload": {"source_type": "session_transcript",
                        "excerpt": "Pat Testley works at Acme Fake Co."},
            "parents": [], "actor": "user", "owner": "default", "trust_level": 2,
            "session_id": "s-old", "branch_id": "s-old",
            "occurred_at": "2026-01-01T00:00:00.00Z", "recorded_at": "2026-01-01T00:00:00.00Z",
            "prev_head": "", "sig": None})
        conn = sqlite3.connect(self.db)
        conn.execute("DROP TABLE IF EXISTS host_model_requests")
        conn.execute("DROP TABLE IF EXISTS host_model_results")
        conn.execute("UPDATE meta SET value='5' WHERE key='schema_version'")
        conn.commit()
        conn.close()

    def test_old_db_upgrades_in_place(self):
        self._make_v5_db()
        store = MemoryStore(self.db)                      # reopen == migrate
        conn = store._conn()
        self.assertTrue(_has_table(conn, "host_model_requests"))
        self.assertTrue(_has_table(conn, "host_model_results"))
        self.assertEqual(store.get_meta("schema_version"), str(SCHEMA_VERSION))
        # H1 claimed 6 when it was built against a v5 store, as did E5 (novelty)
        # and E7 (identity). The ladder-9 integration sequenced them into one
        # chain and host-model plumbing landed at 9; §H2's two drain tables
        # continued the same chain at 10, F4c's rerank_hints.owner column
        # continued it at 11, and A0fix's procedures.body -- the column that
        # actually RECORDS the text a procedure's vector was made of, instead of
        # leaving re-embeds to rebuild it from the 40-char name -- continues it
        # again at 12, and A0e's session_index.model -- the column that records
        # a session-summary vector's geometry, the last embedding-bearing table
        # that had none -- at 13.
        #
        # The v5.7.0 integration continues the SAME chain: six ladder-10 trees
        # each claimed 12 and/or 13 against v5.6.0's 11, and they are sequenced
        # into one ladder exactly as E5/E7/H1 were. 14 = A1's
        # rerank_hints.principal, 15 = A1b's owner/read_acl on goals and
        # reflections, 16 = A3's maintenance_runs, 17 = A13's narrowed
        # curation_jobs task CHECK, 18 = A7's queue + vector-census indexes.
        # Rungs land as their trees merge; the number below is the top of the
        # chain as it stands in this tree. See engine/store.py.
        self.assertEqual(SCHEMA_VERSION, 18)
        # Pre-existing data survives, and the new queue is usable immediately.
        self.assertIsNotNone(store.get_event("ev_old"))
        registry = HostModelRegistry(store, _CfgStub({"host_model.piggyback": True}))
        rid = registry.enqueue("extract_facts", {"text": "Pat Testley"})
        self.assertEqual(registry.get(rid)["status"], "pending")

    def _make_v10_db(self):
        """A store shaped like a pre-F4c v10 build: rerank_hints exists (§H2)
        but has no owner column yet, and already carries a live row -- so the
        migration test proves the ALTER TABLE...DEFAULT backfills EXISTING
        rows, not just future ones."""
        MemoryStore(self.db)                              # creates a fresh v11 db...
        conn = sqlite3.connect(self.db)
        conn.execute("DROP TABLE IF EXISTS rerank_hints")  # ...rebuilt one version back
        conn.execute("""
            CREATE TABLE rerank_hints (
                query_key TEXT NOT NULL, belief_id TEXT NOT NULL, weight REAL NOT NULL,
                tokens TEXT NOT NULL DEFAULT '[]', query_text TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL, expires_at TEXT NOT NULL,
                PRIMARY KEY(query_key, belief_id))""")
        conn.execute(
            "INSERT INTO rerank_hints(query_key,belief_id,weight,tokens,query_text,"
            "created_at,expires_at) VALUES('k1','b1',1.0,'[]','q',"
            "'2026-01-01T00:00:00.000Z','2099-01-01T00:00:00.000Z')")
        conn.execute("UPDATE meta SET value='10' WHERE key='schema_version'")
        conn.commit()
        conn.close()

    def test_v10_db_upgrades_rerank_hints_with_owner_column(self):  # F4c
        self._make_v10_db()
        store = MemoryStore(self.db)                       # reopen == migrate
        conn = store._conn()
        self.assertTrue(_has_col(conn, "rerank_hints", "owner"))
        self.assertEqual(store.get_meta("schema_version"), str(SCHEMA_VERSION))

        # The pre-existing row survived the ALTER and got the DEFAULT owner --
        # not dropped, not NULL.
        rows = [tuple(r) for r in
               conn.execute("SELECT owner FROM rerank_hints WHERE query_key='k1'").fetchall()]
        self.assertEqual(rows, [("default",)])

        # The table is immediately usable, owner-scoped, post-migration.
        store.add_rerank_hints("k2", "q2", ["tok"], [("b2", 1.0)],
                               "2099-01-01T00:00:00.000Z", owner="alice")
        self.assertEqual(len(store.live_rerank_hints(owner="alice")), 1)
        self.assertEqual(len(store.live_rerank_hints(owner="bob")), 0)

        # Re-running the migration on an already-migrated connection is a
        # no-op, not an error -- the same probe-then-ALTER discipline every
        # other step in the ladder uses.
        store._migrate(conn)
        self.assertTrue(_has_col(conn, "rerank_hints", "owner"))

    def test_migrate_probe_recreates_a_dropped_table(self):
        """Exercises the _has_table branch directly, without the CREATE-IF-NOT-
        EXISTS script masking it."""
        store = MemoryStore(self.db)
        conn = store._conn()
        conn.execute("DROP TABLE host_model_requests")
        conn.commit()
        self.assertFalse(_has_table(conn, "host_model_requests"))
        store._migrate(conn)
        self.assertTrue(_has_table(conn, "host_model_requests"))

    def test_has_table_is_false_for_a_missing_table(self):
        store = MemoryStore(self.db)
        self.assertFalse(_has_table(store._conn(), "no_such_table_at_all"))


if __name__ == "__main__":
    unittest.main()
