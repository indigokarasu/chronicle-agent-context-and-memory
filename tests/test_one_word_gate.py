"""
Chronicle — a short message's ONE shared word is not enough on its own.

A message with three content words or fewer passes the injection gate on a
single shared word. Measured on the production store (64 such matches over 250
real messages), most were coincidences: "system health check" brought a
prescription refill (its attribute is `health_event`), "fix all the issues"
refunds that were "issued", "every 10 mins" two contacts named Min, "set it
up" a model-switching chat. Each item's STORED vector says what the words
cannot: the plainly unrelated scored 0.32-0.64 against the message, the
plainly related 0.66-0.75 (a few loosely related fell on both sides).
So a one-word match is kept only when the item's vector is near the message's.
A short item with no vector of this model is embedded on the spot (a few per
turn). A match nothing can vouch for -- a long item never embedded, an
embedder that cannot answer in time -- is left out: a busy embedder used to
let every coincidence back in. A model with no measured floor keeps the word
rule.

Fixtures use obviously fake values; vectors are hand-placed.
"""

import shutil
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from _tmp_support import temp_home

from unittest import mock

from engine import retrieval as R
from engine.core import ChronicleCore
from engine.embeddings import pack

CFG = {"embeddings": {"model": "hashing"}}
SID = "20260917_010203_cd34ef"
QUERY = "System health check"
NEAR, FAR = [0.96, 0.28, 0.0, 0.0], [0.0, 0.0, 1.0, 0.0]
TAG = "nomic-embed-text[prefixed]"


def _floor(core, value):
    core.cfg._d["retrieval"]["prefetch_min_similarity"] = value


class FakeServer:
    """What the gate uses of a remote embedder: the model it reports, its task
    prefixes, its breaker, and one raw request."""
    model = "/opt/models/nomic-embed-text-v1.5.Q8_0.gguf"
    dimensions = 4
    use_task_prefixes = True

    def __init__(self, fail=False):
        self.fail, self.calls, self._open_until = fail, [], 0.0

    def model_tag(self):
        return TAG

    def _embed_raw_batch(self, texts, timeout):
        self.calls.append((list(texts), timeout))
        if self.fail:
            raise TimeoutError("busy")
        return [[1.0, 0.0, 0.0, 0.0] if t.startswith("search_query: ")
                else NEAR if "Zorblax" in t else FAR for t in texts]

    def embed(self, *_a, **_k):
        raise AssertionError("the gated path embeds nothing but the query, and only raw")

    embed_query = embed_document = embed


class TestOneWordMatches(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.home = temp_home(prefix="oneword_")
        cls.core = core = ChronicleCore.get(cls.home, CFG)
        core.initialize(SID, principal_id="default")
        cls.ids = {}
        for key, attribute, body in (
                ("far", "health_event", "Zorbaxol prescription refill ordered for Pat Testley"),
                ("near", "server_health", "the Zorblax dashboard lives at the Riverton office"),
                ("two_words", "note", "the system health check runs nightly for Acme Fake Co"),
                ("no_vector", "insurance", "health insurance card for Robin Placeholder"),
                ("other_model", "gym", "health club membership at SunFake 9000 Gym"),
                ("short_vector", "clinic", "health clinic hours for Izakaya Nonesuch staff"),
                ("near_unembedded", "pager", "Zorblax health pager rota starts Monday"),
                ("long_unembedded", "diary", "health diary: " + "Glimmerfen walking notes, " * 12)):
            core.capture.append("asserted", {
                "kind": "fact",
                "key": {"entity_id": "user", "predicate_canonical": attribute, "attribute": attribute,
                        "qualifiers_hash": "", "qualifiers": {}, "owner": "default", "domain": "user"},
                "body": body, "confidence": 0.9, "source_event": "x", "source_type": "user_direct",
                "domain": "user"}, actor="user", owner="default", trust_level=3)
            core.process_pending()
            cls.ids[key] = core.store._conn().execute(
                "SELECT belief_id FROM facts WHERE attribute=?", (attribute,)).fetchone()[0]
        with core.store.transaction() as c:
            c.execute("DELETE FROM memory_vectors")
            for key, vec, tag in (("far", FAR, TAG), ("near", NEAR, TAG), ("two_words", FAR, TAG),
                                  ("other_model", FAR, "some-other-model"), ("short_vector", FAR[:3], TAG)):
                c.execute("INSERT INTO memory_vectors(belief_id,kind,embedding,model,created_at) "
                          "VALUES(?,?,?,?,?)", (cls.ids[key], "fact", pack(vec), tag, "2026-09-17"))
        # Two of the user's own messages, each sharing only "health" with the query.
        core.capture.observe("The tomato plants in Riverton are in poor health again.", "Sorry to hear.",
                             session_id=SID)
        core.capture.observe("The Zorblax status page health tile went green.", "Good.", session_id=SID)
        core.capture.finalize_session(SID, "clean_exit")
        core.process_pending()
        with core.store.transaction() as c:
            c.execute("DELETE FROM observed_vectors")
            for eid, payload in c.execute("SELECT event_id, payload FROM events WHERE type='observed' "
                                          "AND session_id=?", (SID,)).fetchall():
                vec = FAR if "tomato" in payload else NEAR if "status page" in payload else None
                if vec:
                    c.execute("INSERT INTO observed_vectors(event_id,embedding,model,owner,created_at) "
                              "VALUES(?,?,?,?,?)", (eid, pack(vec), TAG, "default", "2026-09-17"))

    @classmethod
    def tearDownClass(cls):
        ChronicleCore._instances.pop(cls.home, None)
        shutil.rmtree(cls.home, ignore_errors=True)

    def ctx(self, q=QUERY, server=None, floor="auto"):
        r = self.core.retrieval
        saved_emb = r.embedder
        r.embedder = server if server is not None else FakeServer()
        _floor(self.core, floor)
        try:
            return r.get_context(q, token_budget=1200, principal="default",
                                 exclude_automation=True, relevance_gate=True), r.embedder
        finally:
            r.embedder = saved_emb
            _floor(self.core, "auto")

    def test_the_fixture_matches_every_fact_on_its_words(self):
        """With no floor, the word rule alone takes them all -- otherwise the
        tests below prove nothing."""
        out, _ = self.ctx(floor=None)
        for word in ("Zorbaxol", "dashboard", "Acme Fake Co", "Robin Placeholder", "SunFake 9000",
                     "Izakaya Nonesuch", "tomato", "status page", "pager rota", "Glimmerfen"):
            self.assertIn(word, out)

    def test_a_coincidence_is_dropped_a_match_in_meaning_kept(self):
        out, _ = self.ctx()
        self.assertNotIn("Zorbaxol", out)
        self.assertIn("dashboard", out)
        one = self.core.retrieval.last_context_debug["relevance_gate"]["one_word"]
        self.assertIn(("health", False), {(d["word"], d["kept"]) for d in one})
        self.assertIn(("health", True), {(d["word"], d["kept"]) for d in one})

    def test_the_users_own_messages_are_checked_the_same_way(self):
        out, _ = self.ctx()
        self.assertNotIn("tomato", out)
        self.assertIn("status page", out)

    def test_two_shared_words_need_no_vector_check(self):
        self.assertIn("Acme Fake Co", self.ctx()[0])

    def test_a_short_item_with_no_usable_vector_is_embedded_now(self):
        """No vector, another model's, or another length: embedded on the spot."""
        with mock.patch.object(R, "_GATE_EMBED_ITEMS", 10):
            out, server = self.ctx()
        for gone in ("Robin Placeholder", "SunFake 9000", "Izakaya Nonesuch"):
            self.assertNotIn(gone, out)
        self.assertIn("pager rota", out)
        docs = [t for texts, _ in server.calls for t in texts if t.startswith("search_document: ")]
        self.assertEqual(len(docs), 4, docs)

    def test_a_long_item_with_no_vector_is_left_out(self):
        self.assertNotIn("Glimmerfen", self.ctx()[0])

    def test_a_few_items_per_turn_are_embedded_the_rest_left_out(self):
        out, server = self.ctx()
        docs = [t for texts, _ in server.calls for t in texts if t.startswith("search_document: ")]
        self.assertEqual(len(docs), R._GATE_EMBED_ITEMS)
        kept = sum(w in out for w in ("Robin Placeholder", "SunFake 9000", "Izakaya Nonesuch", "pager rota"))
        self.assertEqual(kept, int(any("pager rota" in d for d in docs)))   # only the near one, if reached

    def test_the_turn_budget_bounds_every_request(self):
        with mock.patch.object(R, "_GATE_EMBED_BUDGET", 0.0):
            out, server = self.ctx()
        self.assertEqual(server.calls, [])
        self.assertNotIn("Zorbaxol", out)
        self.assertIn("Acme Fake Co", out)         # two shared words need no vector

    def test_the_query_is_embedded_once_raw_and_prefixed(self):
        _out, server = self.ctx()
        queries = [(texts, t) for texts, t in server.calls if texts[0].startswith("search_query: ")]
        self.assertEqual(queries[0][0], ["search_query: " + QUERY])
        self.assertEqual(len(queries), 1)
        self.assertTrue(all(len(texts) == 1 and t <= R._GATE_EMBED_TIMEOUT for texts, t in server.calls))

    def test_a_longer_message_needs_two_words_and_embeds_nothing(self):
        _out, server = self.ctx("Is the Zorblax server health dashboard still at the Riverton office?")
        self.assertEqual(server.calls, [])

    def test_an_embedder_that_fails_leaves_one_word_matches_out(self):
        out, server = self.ctx(server=FakeServer(fail=True))
        self.assertEqual(len(server.calls), 1)          # the query; nothing more is tried
        self.assertNotIn("Zorbaxol", out)
        self.assertNotIn("dashboard", out)              # unvouched, even the near one
        self.assertIn("Acme Fake Co", out)

    def test_an_open_breaker_is_not_asked(self):
        import time
        server = FakeServer()
        server._open_until = time.monotonic() + 60
        out, _ = self.ctx(server=server)
        self.assertEqual(server.calls, [])
        self.assertNotIn("Zorbaxol", out)

    def test_auto_knows_no_floor_for_an_unknown_model(self):
        server = FakeServer()
        server.model = "acme-fake-embedder-2"
        out, _ = self.ctx(server=server)
        self.assertEqual(server.calls, [])
        self.assertIn("Zorbaxol", out)

    def test_an_explicit_floor_applies_to_any_model(self):
        server = FakeServer()
        server.model = "acme-fake-embedder-2"
        out, _ = self.ctx(server=server, floor=0.5)
        self.assertNotIn("Zorbaxol", out)
        self.assertIn("dashboard", out)

    def test_hashing_is_never_asked(self):
        r = self.core.retrieval
        _floor(self.core, 0.5)
        try:
            self.assertIsNone(r._gate_vector(QUERY, True, 1.0))
            out = r.get_context(QUERY, token_budget=1200, principal="default",
                                exclude_automation=True, relevance_gate=True)
        finally:
            _floor(self.core, "auto")
        self.assertIn("Zorbaxol", out)


if __name__ == "__main__":
    unittest.main()
