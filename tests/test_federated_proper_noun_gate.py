"""
Chronicle — F1b: the federated one-word gate trusts the keyword channel's own
proper noun, without a vector.

Measured on the live store: "what did I buy at Amazon last week" shares
exactly one content word with a matching transaction row ("amazon" -- a
purchase record never says "buy"), so the injection relevance gate's one-word
cosine floor (retrieval.prefetch_min_similarity, 0.65 for nomic) applied, the
real embedder scored 0.52-0.59, and every Amazon line was dropped although the
row was exactly what the keyword channel searched for and found. The floor
stays -- it exists because 71 of 75 one-word matches on the production store
were coincidences -- but a federated hit is not an arbitrary one-word
coincidence when the shared word is a PROPER NOUN of the query: capitalised in
what the person actually typed, and not merely the query's first word (a
sentence start, not a name). That is the token the keyword channel searched
on, which is tighter evidence than the floor was ever standing in for.

Fixtures use an obviously fake merchant name and a fake local-db provider
(same shape `tests/test_r1_channel_max_dbs.py` uses) rather than a real
`LocalDBProvider` against a file -- this proves the GATE's decision, not the
keyword search F1 already covers.
"""

import shutil
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from _tmp_support import temp_home

from engine.core import ChronicleCore
from engine.federated import FederatedChannel

CFG = {"embeddings": {"model": "hashing"}}
SID = "20260925_010203_ab12cd"

# Every candidate text this fake embedder is asked about scores the SAME low
# cosine against the query -- comfortably under both floors (0.65 one-word,
# 0.60 few-word) here. So anything kept in these tests is kept because of the
# proper-noun bypass, never because it happened to score well.
QUERY_VEC = [1.0, 0.0, 0.0, 0.0]
LOW_VEC = [0.5, 0.8660254037844386, 0.0, 0.0]      # cosine 0.5 with QUERY_VEC
TAG = "nomic-embed-text[prefixed]"


class FakeServer:
    """What the gate uses of a remote embedder: one raw request, task
    prefixes, a breaker, and the model id the floor is resolved from."""
    model = "/opt/models/nomic-embed-text-v1.5.Q8_0.gguf"
    dimensions = 4
    use_task_prefixes = True

    def __init__(self):
        self.calls = []
        self._open_until = 0.0

    def model_tag(self):
        return TAG

    def _embed_raw_batch(self, texts, timeout):
        self.calls.append(list(texts))
        return [QUERY_VEC if t.startswith("search_query: ") else LOW_VEC for t in texts]

    def embed(self, *_a, **_k):
        raise AssertionError("the gated path embeds nothing but the query, and only raw")

    embed_query = embed_document = embed


class _FakeProvider:
    """Just enough surface for FederatedChannel.query(): a fixed set of hits,
    ignoring the tokens it is asked about -- F1's keyword search itself is
    covered by tests/test_localdb_token_priority.py, not this file."""

    def __init__(self, name, hits):
        self.name = name
        self.db_path = "fake:%s" % name
        self._hits = list(hits)

    def is_available(self):
        return True

    def search(self, tokens, owner=None, principal=None, max_tables=None, max_rows=None):
        return list(self._hits)

    def identity_candidate(self, hit):
        return {"provider": self.name, "table": hit.get("table"), "row_id": hit.get("row_id"),
                "external_id": hit.get("external_id"), "cached_projection": hit.get("projection"),
                "entity_id": None, "status": "pending_review"}


def _hit(row_id, projection):
    return {"provider": "ledger", "table": "transactions", "row_id": row_id,
            "external_id": "transactions:%d" % row_id, "projection": projection}


class TestFederatedProperNounBypass(unittest.TestCase):
    """The Amazon-shaped case: a federated line sharing ONE word with the
    query, that word a proper noun, kept without a vector -- and everything
    that is NOT that shape still goes through the cosine floor."""

    @classmethod
    def setUpClass(cls):
        cls.home = temp_home(prefix="fedpropernoun_")
        cls.core = core = ChronicleCore.get(cls.home, CFG)
        core.initialize(SID, principal_id="default")

    @classmethod
    def tearDownClass(cls):
        ChronicleCore._instances.pop(cls.home, None)
        shutil.rmtree(cls.home, ignore_errors=True)

    def ctx(self, query, hits):
        r = self.core.retrieval
        saved_emb, saved_fed = r.embedder, r.federated
        r.embedder = FakeServer()
        r.federated = FederatedChannel(cfg=None, providers=[_FakeProvider("ledger", hits)])
        try:
            return r.get_context(query, token_budget=1200, principal="default",
                                 exclude_automation=True, relevance_gate=True)
        finally:
            r.embedder = saved_emb
            r.federated = saved_fed

    def test_a_federated_one_word_proper_noun_match_needs_no_vector(self):
        out = self.ctx("Did I buy anything at Wrenfield?",
                       [_hit(1, "merchant=Wrenfield Hardware; amount=42.10")])
        self.assertIn("Wrenfield Hardware", out)
        one = self.core.retrieval.last_context_debug["relevance_gate"]["one_word"]
        self.assertIn(("wrenfield", True, "proper noun"),
                      {(d["word"], d["kept"], d.get("why")) for d in one})

    def test_a_federated_one_word_common_word_match_still_needs_the_bar(self):
        """"buy" is a shared word too, but it is lowercase in the query (never
        a proper noun) -- the floor still applies, and the low-similarity
        fixture score means it is dropped."""
        out = self.ctx("Did I buy anything at Wrenfield?",
                       [_hit(2, "note=buy two get one free, unrelated store")])
        self.assertNotIn("buy two get one free", out)
        one = self.core.retrieval.last_context_debug["relevance_gate"]["one_word"]
        self.assertIn(("buy", False), {(d["word"], d["kept"]) for d in one})

    def test_a_capitalised_first_word_does_not_bypass(self):
        """"Buy" opens the sentence -- capitalised, but at position 0 -- so it
        is not a proper noun of the query and still needs the bar, same as
        the plain lowercase case above."""
        out = self.ctx("Buy something from Wrenfield today",
                       [_hit(3, "note=buy two get one free, unrelated store")])
        self.assertNotIn("buy two get one free", out)


class TestBeliefsAndExcerptsKeepTheOldRule(unittest.TestCase):
    """F1b's bypass is scoped to kind=='federated' only. A BELIEF matched on
    the exact same one-word proper noun must still clear the cosine floor --
    session excerpts use the identical `_relevant`/`_close_enough` call with
    kind='excerpts' and are covered unchanged by tests/test_one_word_gate.py,
    which this change does not touch."""

    @classmethod
    def setUpClass(cls):
        cls.home = temp_home(prefix="fedpropernoun_belief_")
        cls.core = core = ChronicleCore.get(cls.home, CFG)
        core.initialize(SID, principal_id="default")
        core.capture.append("asserted", {
            "kind": "fact",
            "key": {"entity_id": "user", "predicate_canonical": "note", "attribute": "note",
                    "qualifiers_hash": "", "qualifiers": {}, "owner": "default", "domain": "user"},
            "body": "Wrenfield closes early on weekends", "confidence": 0.9, "source_event": "x",
            "source_type": "user_direct", "domain": "user"}, actor="user", owner="default", trust_level=3)
        core.process_pending()

    @classmethod
    def tearDownClass(cls):
        ChronicleCore._instances.pop(cls.home, None)
        shutil.rmtree(cls.home, ignore_errors=True)

    def test_a_belief_one_word_proper_noun_match_is_still_gated_by_the_bar(self):
        r = self.core.retrieval
        saved_emb, saved_fed = r.embedder, r.federated
        r.embedder = FakeServer()
        r.federated = None
        try:
            out = r.get_context("Did I buy anything at Wrenfield?", token_budget=1200,
                                principal="default", exclude_automation=True, relevance_gate=True)
        finally:
            r.embedder = saved_emb
            r.federated = saved_fed
        self.assertNotIn("closes early", out)


if __name__ == "__main__":
    unittest.main()
