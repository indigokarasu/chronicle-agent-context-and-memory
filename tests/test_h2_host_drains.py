"""
Chronicle — H2: draining the host-model piggyback (ladder 9, issue #8 H2).

H1 built the plumbing and deliberately stopped: validated `doc2query` and
`rerank` replies were parked in `host_model_results` with nothing to consume
them, and `embeddings.doc2query.excerpts` wrote rows that retrieval dropped on
the floor. H2 finishes the concept. Four claims, one test class each:

  1. doc2query drain — a host's questions become real `query_proxy_vectors`
     rows, through the SAME delete-then-write path Tier-1 templates use, under
     a documented merge rule (doc2query.MERGE_RULE) and the same <=4 bound,
     with host provenance recorded in `host_model_proxies`.
  2. rerank drain — a host verdict becomes bounded, expiring query->evidence
     hints, and a REPEATED query measurably benefits from it through real
     search(). The bar for this task, so it is tested on ranks and scores from
     the live engine rather than on the hint table's contents.
  3. extract_facts — end-to-end verification of the drain H1 already shipped.
  4. excerpt tier — `embeddings.doc2query.excerpts` now resolves through the
     raw/observed channel instead of dropping. Default stays off; proxies are
     cleaned up when their event is pruned.

Plus the property none of the above may cost: at DEFAULT config nothing here
runs and both new tables stay empty (TestH2DisabledPathIsInert), which is the
emptiness assertion that licenses excluding them from the H1 inertness dump.

Fixtures are obviously fake throughout (Pat Testley, Acme Fake Co).
"""

import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent))

from engine import access, doc2query
from engine.core import ChronicleCore
from engine.hostmodel import PROVENANCE_SOURCE
from engine.retrieval import hint_signature
from engine.store import _has_table
from h1_store_dump import H1_TABLES, TURNS
from provider import ChronicleMemoryProvider

# A fact key whose attribute has NO Tier-1 template (doc2query._FACT_TEMPLATES),
# so every proxy on it can only have come from the host. Used wherever a test
# needs the host contribution to be unambiguous.
_UNTEMPLATED_KEY = {"entity_id": "ent_pat_testley", "entity_name": "Pat Testley",
                    "predicate_canonical": "favorite_pastry", "attribute": "favorite_pastry",
                    "qualifiers_hash": "", "qualifiers": {}}
# works_at HAS templates ("where does {name} work", "what is {name}'s job"), so
# it is the one to use when the MERGE is what is under test.
_TEMPLATED_KEY = {"entity_id": "ent_pat_testley", "entity_name": "Pat Testley",
                  "predicate_canonical": "works_at", "attribute": "works_at",
                  "qualifiers_hash": "", "qualifiers": {}}


def fenced(obj) -> str:
    return "Right.\n```json\n%s\n```\nAnything else?" % json.dumps(obj)


class _H2Case(unittest.TestCase):
    """A live provider with piggyback ON over a throwaway store."""

    piggyback = True

    def setUp(self):
        self.home = tempfile.mkdtemp(prefix="h2-")
        config = {"embeddings": {"model": "hashing"}}
        if self.piggyback is not None:
            config["host_model"] = {"piggyback": self.piggyback}
        self.provider = ChronicleMemoryProvider()
        self.provider.initialize("s-h2", hermes_home=self.home, principal_id="assistant",
                                 config=config)
        self.core = self.provider.core
        self.store = self.core.store
        self.registry = self.core.host_model

    def tearDown(self):
        shutil.rmtree(self.home, ignore_errors=True)

    # -- helpers ----------------------------------------------------------

    def seed_fact(self, key, body="Acme Fake Co"):
        self.core.capture.append("asserted", {
            "kind": "fact", "key": dict(key), "body": body, "confidence": 0.9,
            "source_event": "src-" + key["attribute"], "source_type": "user_direct",
            "domain": "user"}, actor="user", trust_level=4, session_id="s-h2")
        self.core.process_pending()
        rows = self.store.query_beliefs("facts", "attribute=?", (key["attribute"],), 5)
        self.assertTrue(rows, "fixture wrote no fact")
        return rows[0]["belief_id"]

    def proxies(self, item_id):
        return [r for r in self.store.iter_query_proxy_vectors() if r["belief_id"] == item_id]

    def questions(self, item_id):
        return [r["question"] for r in sorted(self.proxies(item_id),
                                              key=lambda r: r["proxy_idx"])]

    def pending(self, kind):
        return [r for r in self.registry.list_requests(status="pending") if r["kind"] == kind]

    def answer_request(self, request, body):
        """Resolve `request` through the REAL provider path: mark it in flight,
        then hand the host's reply to sync_turn, which parses and applies it.

        Only the attach step is done directly. pre_llm_call attaches strictly
        oldest-first, and these fixtures deliberately queue several kinds at
        once, so going through it would make which request is under test a
        function of fixture ordering. tests/test_host_model.py already pins the
        FIFO attach behaviour itself; test_the_attach_hook_offers_the_drain_kinds
        below pins that H2's new request kinds reach it at all."""
        self.registry.mark_attached(request["request_id"])
        payload = dict(body)
        payload["request_id"] = request["request_id"]
        self.provider.sync_turn("thanks", fenced(payload), session_id="s-h2")
        return self.registry.get(request["request_id"])["status"]


# ---------------------------------------------------------------------------
# 1. doc2query drain
# ---------------------------------------------------------------------------
class TestDoc2QueryDrain(_H2Case):

    def test_host_questions_land_as_proxies_and_are_retrievable(self):
        """§H2.1 acceptance: host doc2query questions retrievable via the proxy
        path, with host provenance."""
        b_id = self.seed_fact(_UNTEMPLATED_KEY, body="cardamom bun")
        self.assertEqual(self.questions(b_id), [],
                         "fixture attribute was supposed to have no templates")

        req = self.pending("doc2query")
        self.assertEqual(len(req), 1, "the write path did not offer doc2query work")
        self.assertEqual(json.loads(req[0]["payload"])["belief_id"], b_id)
        self.assertEqual(self.answer_request(req[0], {
            "kind": "doc2query",
            "questions": ["which pastry does Pat Testley like best",
                          "what is Pat Testley's favourite bakery order"]}), "answered")

        # The questions are proxy rows on the parent...
        self.assertEqual(self.questions(b_id),
                         ["which pastry does Pat Testley like best",
                          "what is Pat Testley's favourite bakery order"])
        # ...marked host_model, in the side table that carries the provenance.
        rows = self.store.host_proxy_rows(b_id)
        self.assertEqual([r["source"] for r in rows], ["host_model", "host_model"])
        self.assertEqual(rows[0]["request_id"], req[0]["request_id"])

        # ...and they actually retrieve the PARENT, through the proxy channel,
        # for a question that shares nothing with the fact's own value.
        hits = self.core.retrieval.search("which pastry does Pat Testley like best", limit=5)
        top = [h for h in hits if h["belief_id"] == b_id]
        self.assertTrue(top, "host proxy did not retrieve its parent")
        self.assertIn("vector_proxy", top[0]["channels"])
        # §E2: the proxy's own text is never surfaced as content.
        self.assertEqual(top[0]["value"], "cardamom bun")

    def test_merge_rule_is_host_first_then_template_fill(self):
        """§H2.1's documented merge rule, on an attribute that HAS templates."""
        b_id = self.seed_fact(_TEMPLATED_KEY)
        templates = self.questions(b_id)
        self.assertEqual(templates, ["where does Pat Testley work",
                                     "what is Pat Testley's job"])

        self.answer_request(self.pending("doc2query")[0], {
            "kind": "doc2query", "questions": ["who employs Pat Testley"]})

        # Host question first, then the templates fill the rest of the budget:
        # AUGMENT, because one host question left room for both templates.
        self.assertEqual(self.questions(b_id), ["who employs Pat Testley"] + templates)
        self.assertEqual(doc2query.MERGE_RULE, "host_first_template_fill")

    def test_a_full_host_set_replaces_the_templates_within_the_volume_bound(self):
        """The other half of the rule: 4 host questions leave no room, and the
        <=MAX_PROXIES bound is enforced against the MERGED set, not per side."""
        b_id = self.seed_fact(_TEMPLATED_KEY)
        self.assertEqual(len(self.questions(b_id)), 2)

        host = ["host question %d about Pat Testley" % i for i in range(4)]
        self.answer_request(self.pending("doc2query")[0],
                            {"kind": "doc2query", "questions": host})

        self.assertEqual(self.questions(b_id), host)
        self.assertEqual(len(self.proxies(b_id)), doc2query.MAX_PROXIES)
        self.assertNotIn("where does Pat Testley work", self.questions(b_id))

    def test_store_proxies_caps_the_volume_itself(self):
        """M2b: pin the `[:MAX_PROXIES]` slice inside Reducer.store_proxies.

        Every production caller pre-caps — merge_questions returns at most
        MAX_PROXIES and doc2query_text slices too — so removing the slice is an
        equivalent mutant against the drain tests above, and the last line of
        defence for the volume bound would be untested. Called directly with an
        over-length list, which is the only way to distinguish 'the bound is
        enforced here' from 'nothing has happened to violate it yet'."""
        b_id = self.seed_fact(_UNTEMPLATED_KEY, body="cardamom bun")
        written = self.core.reducer.store_proxies(
            b_id, "fact", ["fake question %d" % i for i in range(9)])

        self.assertEqual(written, doc2query.MAX_PROXIES)
        self.assertEqual(len(self.proxies(b_id)), doc2query.MAX_PROXIES)
        self.assertEqual(self.questions(b_id),
                         ["fake question %d" % i for i in range(doc2query.MAX_PROXIES)])

    def test_delete_before_regenerate_is_respected_by_the_drain(self):
        """Integration fix D applies to host output too: a SHRINKING question
        count must not strand the higher-idx rows of the previous generation."""
        b_id = self.seed_fact(_UNTEMPLATED_KEY, body="cardamom bun")
        self.answer_request(self.pending("doc2query")[0], {
            "kind": "doc2query",
            "questions": ["fake question a", "fake question b",
                          "fake question c", "fake question d"]})
        self.assertEqual(len(self.proxies(b_id)), 4)

        # A second, thinner reply for the same parent.
        req2 = self.pending("doc2query")
        if not req2:
            self.registry.enqueue("doc2query", {"belief_id": b_id, "kind": "fact",
                                                "text": "cardamom bun"})
            req2 = self.pending("doc2query")
        self.answer_request(req2[0], {"kind": "doc2query", "questions": ["fake question z"]})

        self.assertEqual(self.questions(b_id), ["fake question z"])
        self.assertEqual(len(self.store.host_proxy_rows(b_id)), 1)

    def test_host_questions_survive_a_projection_rebuild(self):
        """Why host_model_proxies is durable — and why it is deliberately NOT in
        truncate_projection's teardown list.

        A rebuild wipes query_proxy_vectors (integration fix E) and replays the
        log, which regenerates the TEMPLATE proxies from scratch. The host's
        questions are not in the log and cannot be regenerated from it, so if
        they were treated as projection state they would be lost for good on
        the first rebuild. Kept, they are merged back in on the replayed write."""
        b_id = self.seed_fact(_TEMPLATED_KEY)
        self.answer_request(self.pending("doc2query")[0], {
            "kind": "doc2query", "questions": ["who employs Pat Testley"]})
        self.assertEqual(self.questions(b_id)[0], "who employs Pat Testley")

        self.core.reducer.rebuild()

        self.assertEqual(self.questions(b_id)[0], "who employs Pat Testley",
                         "the rebuild threw the host questions away")
        # The templates came back too — this is a merge, not a host-only reset.
        self.assertIn("where does Pat Testley work", self.questions(b_id))

    def test_retracting_the_parent_takes_the_host_questions_with_it(self):
        """Retract/supersede means the item is GONE, not being regenerated, so
        unlike the delete-then-write path this one must clear host_model_proxies
        as well — otherwise the table leaks a row per dead belief forever."""
        b_id = self.seed_fact(_UNTEMPLATED_KEY, body="cardamom bun")
        self.answer_request(self.pending("doc2query")[0], {
            "kind": "doc2query", "questions": ["which pastry does Pat Testley like best"]})
        self.assertTrue(self.store.host_proxy_rows(b_id))

        self.store.update_belief("facts", b_id, status="retracted")

        self.assertEqual(self.store.host_proxy_rows(b_id), [])
        self.assertEqual(self.proxies(b_id), [])

    def test_a_reply_about_an_unknown_parent_parks_but_writes_nothing(self):
        """Discriminating partner: the drain must not invent a parent.

        The payload declares a `kind`, exactly as the real offer does — so this
        also pins that the declaration is NOT trusted as a substitute for the
        parent existing. A belief retracted between request and reply is the
        live version of this case."""
        rid = self.registry.enqueue("doc2query", {"belief_id": "b_no_such_belief",
                                                  "kind": "fact", "text": "Pat Testley"})
        before = len(self.store.iter_query_proxy_vectors())
        self.assertEqual(self.answer_request(self.registry.get(rid), {
            "kind": "doc2query", "questions": ["a question about nothing"]}), "answered")
        self.assertEqual(len(self.store.iter_query_proxy_vectors()), before)
        self.assertEqual(self.store.host_proxy_rows("b_no_such_belief"), [])
        # ...but the reply is still recorded, which is what makes the drop
        # visible instead of silent.
        self.assertEqual(len(self.registry.results(kind="doc2query")), 1)


# ---------------------------------------------------------------------------
# 2. rerank drain — the acceptance bar
# ---------------------------------------------------------------------------
_RERANK_NOTES = (
    # The answer-bearing item. Deliberately the WORST lexical match for the
    # query below: it shares only the subject's name.
    ("truth", "Pat Testley took a job at Acme Fake Co in the spring."),
    # Two keyword decoys that legitimately out-rank it on FTS + a bag-of-words
    # embedder, which is the situation a reranker exists to fix.
    ("decoy1", "Pat Testley wonders where the workday goes and where work ends."),
    ("decoy2", "Pat Testley asked where to work out and where the gym is."),
    ("noise", "Pat Testley plays guitar in a fake band called The Testers."),
)

_QUERY = "where does Pat Testley work"

# Hand-written expiry stamps for hints inserted directly into the store.
#
# THE FRACTION MUST BE EXACTLY 3 DIGITS, matching what store.now_iso()/_iso_in()
# actually produce. Python 3.9's datetime.fromisoformat accepts only 3- or
# 6-digit fractions, and retrieval._hint_freshness parses BOTH created_at and
# expires_at to compute a hint's decay — so a stamp like "...00:00.00Z" (two
# digits) fails to parse, freshness comes back 0.0, and the hint silently
# carries ZERO weight. A test built on such a fixture asserts nothing: it passes
# whether or not the code under test works, because no hint was ever in play.
# That is exactly how the first version of the injection test below went
# vacuous. Any test using these constants must also assert the hint is LIVE.
_FAR_FUTURE = "2099-01-01T00:00:00.000Z"
_LONG_PAST = "2000-01-01T00:00:00.000Z"
# Distinctive tokens {testley, work}. Jaccard against:
_SIMILAR = "what company does Pat Testley work for"   # {company,testley,work} -> 0.67, applies
_UNRELATED = "where is Pat Testley employed"          # {employed,testley}     -> 0.33, does not


class TestRerankDrain(_H2Case):

    def seed_notes(self):
        for subject, body in _RERANK_NOTES:
            self.core.capture.append("asserted", {
                "kind": "note", "key": {"note_type": "belief", "subject": subject},
                "body": body, "confidence": 0.9, "source_event": "src-" + subject,
                "source_type": "user_direct", "domain": "user"},
                actor="user", trust_level=4, session_id="s-h2")
        self.core.process_pending()
        rows = {r["subject"]: r["belief_id"]
                for r in self.store.query_beliefs("notes", "1=1", (), 50)}
        return rows

    def ranks(self, query):
        return [h["belief_id"] for h in self.core.retrieval.search(query, limit=10)]

    def host_says_truth_is_best(self, truth_id, query=_QUERY):
        """Answer the rerank request search() itself queued FOR `query`, putting
        the answer-bearing note first.

        Selected by the payload's own query text, not by recency: every search
        in these fixtures queues its own offer, so "the newest pending rerank"
        would silently file the verdict under whichever query ran last."""
        req = [r for r in self.pending("rerank")
               if json.loads(r["payload"]).get("query") == query]
        self.assertTrue(req, "search() did not offer rerank work for %r" % query)
        req = req[-1]
        ids = json.loads(req["payload"])["candidate_ids"]
        self.assertIn(truth_id, ids, "the truth was not among the offered candidates")
        rest = [i for i in range(len(ids)) if i != ids.index(truth_id)]
        self.assertEqual(self.answer_request(
            req, {"kind": "rerank", "order": [ids.index(truth_id)] + rest}), "answered")

    def test_a_repeated_query_benefits_from_a_prior_host_rerank_verdict(self):
        """THE ACCEPTANCE BAR (§H2.2). Rank and score both move, through real
        search(), because of a verdict the host gave on an EARLIER turn."""
        ids = self.seed_notes()
        truth = ids["truth"]

        first = self.core.retrieval.search(_QUERY, limit=10)
        before_rank = [h["belief_id"] for h in first].index(truth)
        before_score = first[before_rank]["score"]
        self.assertGreater(before_rank, 0,
                           "fixture failed: the answer already ranked first, so there "
                           "is no benefit left for a rerank verdict to deliver")

        self.host_says_truth_is_best(truth)
        self.assertGreaterEqual(self.store.count_rerank_hints(), 1)

        second = self.core.retrieval.search(_QUERY, limit=10)
        after_rank = [h["belief_id"] for h in second].index(truth)
        after_score = second[after_rank]["score"]

        self.assertEqual(after_rank, 0,
                         "the host's top-ranked evidence did not reach rank 1 on the repeat")
        self.assertLess(after_rank, before_rank)
        self.assertGreater(after_score, before_score)
        self.assertIn("host_hint", second[after_rank]["channels"])

    def test_a_similar_query_benefits_and_an_unrelated_one_does_not(self):
        """'Applied to SIMILAR future queries' — and the discriminating half:
        a query below the Jaccard floor is left exactly as it was.

        _SIMILAR overlaps _QUERY on {testley, work} out of {company, testley,
        work} = 0.67, above the 0.6 floor. _UNRELATED overlaps on {testley} out
        of {employed, testley, work} = 0.33, below it."""
        ids = self.seed_notes()
        truth = ids["truth"]
        self.core.retrieval.search(_QUERY, limit=10)   # queues the offer
        similar_before = self.ranks(_SIMILAR)
        unrelated_before = self.ranks(_UNRELATED)
        self.host_says_truth_is_best(truth)

        similar_after = self.core.retrieval.search(_SIMILAR, limit=10)
        entry = [h for h in similar_after if h["belief_id"] == truth][0]
        self.assertIn("host_hint", entry["channels"])
        self.assertLess([h["belief_id"] for h in similar_after].index(truth),
                        similar_before.index(truth),
                        "a similar query did not benefit from the verdict")

        after = self.core.retrieval.search(_UNRELATED, limit=10)
        self.assertEqual([h["belief_id"] for h in after], unrelated_before)
        for hit in after:
            self.assertNotIn("host_hint", hit["channels"])

    def test_a_similar_query_is_nudged_less_than_an_exact_repeat(self):
        """The overlap SCALES the weight; it is not a pass/fail gate above the
        floor.

        Asserted on the hint weights themselves rather than on final scores:
        the E3 reranker re-maps every query's blended scores back onto that
        query's OWN [lo, hi] fusion envelope, so a post-rerank score delta is
        not comparable across two different queries and would make this a test
        of the envelope, not of the hint."""
        ids = self.seed_notes()
        truth = ids["truth"]
        self.core.retrieval.search(_QUERY, limit=10)   # queues the offer
        self.host_says_truth_is_best(truth)

        exact = self.core.retrieval._hint_scores(_QUERY)[truth]
        similar = self.core.retrieval._hint_scores(_SIMILAR)[truth]
        self.assertGreater(similar, 0.0)
        self.assertGreater(exact, similar)
        # 0.67 overlap on a fresh (freshness ~1.0) top-ranked hint.
        self.assertAlmostEqual(similar / exact, 2.0 / 3.0, places=2)
        self.assertEqual(self.core.retrieval._hint_scores(_UNRELATED), {})

    def test_hints_are_reciprocal_rank_and_omissions_are_not_penalties(self):
        ids = self.seed_notes()
        self.core.retrieval.search(_QUERY, limit=10)
        req = self.pending("rerank")[-1]
        cand = json.loads(req["payload"])["candidate_ids"]
        self.answer_request(req, {"kind": "rerank", "order": [1, 0]})

        rows = {r["belief_id"]: r["weight"] for r in self.store.live_rerank_hints()}
        self.assertEqual(rows[cand[1]], 1.0)
        self.assertEqual(rows[cand[0]], 0.5)
        # Everything the host left out has NO row — never a negative one.
        for bid in cand[2:]:
            self.assertNotIn(bid, rows)
        self.assertTrue(all(w > 0 for w in rows.values()))
        self.assertEqual(len(ids), 4)

    def test_a_hint_naming_a_real_non_candidate_belief_cannot_inject_it(self):
        """Hints re-weight; they never introduce. A verdict naming a belief this
        query does not surface must change nothing.

        THE HINTED BELIEF MUST BE REAL. An invented id like "b_not_a_candidate"
        makes this test vacuous against the realistic bug: an inject-on-miss
        implementation resolves the missing id through store.find_belief, and an
        id that exists nowhere resolves to nothing, so the mutant has nothing to
        inject and stays green. Hinting a genuinely stored belief that this
        query simply does not retrieve is what puts the mutant in reach.

        Three preconditions, each guarding a distinct way this could go vacuous:
          (a) the belief RESOLVES  — so an inject-on-miss bug can act on it;
          (b) it is NOT a candidate — checked at limit=50, far above the limit
              the assertion uses, so "absent" means absent from the ranking
              rather than merely cut off by the [:limit] slice;
          (c) the hint is LIVE and weighted — a hint whose freshness has decayed
              to zero (what a mis-formatted expires_at produces, see
              _FAR_FUTURE) is dropped by _hint_scores before search() ever sees
              it, and "nothing was injected" would hold trivially.
        """
        self.seed_notes()
        # A real, stored, clearly off-topic belief: shares no distinctive token
        # with _QUERY, so no channel proposes it.
        self.core.capture.append("asserted", {
            "kind": "note", "key": {"note_type": "belief", "subject": "offtopic"},
            "body": "Sam Vimes baked twelve loaves of rye bread for the harvest festival.",
            "confidence": 0.9, "source_event": "src-offtopic", "source_type": "user_direct",
            "domain": "user"}, actor="user", trust_level=4, session_id="s-h2")
        self.core.process_pending()
        offtopic = {r["subject"]: r["belief_id"]
                    for r in self.store.query_beliefs("notes", "1=1", (), 50)}["offtopic"]

        # (a)
        self.assertIsNotNone(self.store.find_belief(offtopic),
                             "the hinted belief must be resolvable, or an inject-on-miss "
                             "bug has nothing to resolve and this test proves nothing")
        # (b)
        self.assertNotIn(offtopic,
                         [h["belief_id"] for h in self.core.retrieval.search(_QUERY, limit=50)],
                         "the off-topic fixture IS a candidate for this query, so "
                         "'it was not injected' would prove nothing")

        key, tokens = hint_signature(_QUERY)
        # F4c: rerank_hints is owner-scoped, and this fixture writes directly
        # to the store rather than through _apply_rerank -- so the write must
        # name the SAME owner _hint_scores will derive from this core's
        # active_principal, or the hint is invisible for a reason unrelated to
        # what this test is actually proving.
        owner = access.user_of(self.core.retrieval.active_principal)
        self.store.add_rerank_hints(key, _QUERY, tokens, [(offtopic, 1.0)], _FAR_FUTURE,
                                    owner=owner)

        # (c)
        scores = self.core.retrieval._hint_scores(_QUERY)
        self.assertIn(offtopic, scores,
                      "the fixture hint is not live, so this test proves nothing")
        self.assertGreater(scores[offtopic], 0.0,
                           "the fixture hint carries zero weight, so this test proves nothing")

        hits = self.core.retrieval.search(_QUERY, limit=10)
        self.assertNotIn(offtopic, [h["belief_id"] for h in hits],
                         "a hint introduced a belief no retrieval channel surfaced")
        for hit in hits:
            self.assertNotIn("host_hint", hit["channels"])

    def test_a_hint_written_for_one_owner_never_reweights_a_different_owners_identical_query(self):
        # F4c review finding: rerank_hints was store-global, so ANY owner's
        # verdict could re-weight ANY other owner's textually similar query --
        # ordering influence only, but real cross-owner leakage all the same.
        # Proven two ways: directly against _hint_scores (the function F4c
        # changed to filter by the querying principal's owner), and end-to-end
        # through this fixture's own real search() -- which names a real,
        # resolvable belief and the query search() itself just offered rerank
        # work for, so a pre-fix build would visibly reorder it.
        ids = self.seed_notes()
        truth = ids["truth"]
        self.core.retrieval.search(_QUERY, limit=10)   # queues the offer, as usual
        mine = access.user_of(self.core.retrieval.active_principal)   # "_user" for "assistant"
        foreign = mine + "-someone-else"                              # a distinct owner bucket

        key, tokens = hint_signature(_QUERY)
        self.store.add_rerank_hints(key, _QUERY, tokens, [(truth, 1.0)], _FAR_FUTURE,
                                    owner=foreign)

        # (1) Directly at the function F4c changed: a foreign-owner hint is
        # invisible to this principal's lookup.
        self.assertEqual(self.core.retrieval._hint_scores(_QUERY), {},
                         "a hint stored under a DIFFERENT owner reweighted this query")

        # (2) End-to-end: real search() ranking for the fixture's own owner is
        # completely untouched by a same-belief, same-query hint that belongs
        # to someone else.
        before = self.ranks(_QUERY)
        hits = self.core.retrieval.search(_QUERY, limit=10)
        self.assertEqual([h["belief_id"] for h in hits], before)
        for hit in hits:
            self.assertNotIn("host_hint", hit["channels"])

        # And the isolation is real SCOPING, not a hint that simply never
        # fires: the identical row, written under the right owner, applies.
        self.store.add_rerank_hints(key, _QUERY, tokens, [(truth, 1.0)], _FAR_FUTURE, owner=mine)
        self.assertIn(truth, self.core.retrieval._hint_scores(_QUERY))

    def test_expired_hints_are_ignored_and_pruned(self):
        self.seed_notes()
        key, tokens = hint_signature(_QUERY)
        self.store.add_rerank_hints(key, _QUERY, tokens, [("b_whatever", 1.0)],
                                    _LONG_PAST)
        self.assertEqual(self.store.live_rerank_hints(), [])
        # And the next write sweeps the dead row out of the table entirely.
        self.store.add_rerank_hints("otherkey", "other", ["other"], [("b_other", 1.0)],
                                    _FAR_FUTURE)
        self.assertEqual(self.store.count_rerank_hints(), 1)

    def test_the_table_is_capped_oldest_first(self):
        for i in range(10):
            self.store.add_rerank_hints("key%02d" % i, "q%d" % i, ["token%d" % i],
                                        [("b_%d" % i, 1.0)], _FAR_FUTURE,
                                        max_entries=4)
        self.assertEqual(self.store.count_rerank_hints(), 4)
        survivors = {r["query_key"] for r in self.store.live_rerank_hints()}
        self.assertEqual(survivors, {"key06", "key07", "key08", "key09"})

    def test_hints_do_not_survive_a_projection_rebuild(self):
        """They are (query -> belief_id) pointers; a rebuild need not reissue
        those ids, so a surviving hint would point at nothing."""
        self.seed_notes()
        key, tokens = hint_signature(_QUERY)
        self.store.add_rerank_hints(key, _QUERY, tokens, [("b_x", 1.0)],
                                    _FAR_FUTURE)
        self.assertEqual(self.store.count_rerank_hints(), 1)
        self.store.truncate_projection()
        self.assertEqual(self.store.count_rerank_hints(), 0)

    def test_weight_zero_is_an_exact_off_switch(self):
        self.seed_notes()
        truth = {r["subject"]: r["belief_id"]
                 for r in self.store.query_beliefs("notes", "1=1", (), 50)}["truth"]
        before = self.ranks(_QUERY)
        self.host_says_truth_is_best(truth)
        self.core.retrieval.cfg = _ZeroWeightCfg(self.core.cfg)
        try:
            self.assertEqual(self.ranks(_QUERY), before)
        finally:
            self.core.retrieval.cfg = self.core.cfg


class _ZeroWeightCfg:
    """cfg proxy that zeroes only the hint weight."""

    def __init__(self, inner):
        self.inner = inner

    def get(self, key, default=None):
        if key == "host_model.rerank_hints.weight":
            return 0.0
        return self.inner.get(key, default)


# ---------------------------------------------------------------------------
# 3. extract_facts — end-to-end verification (§H2.3, test-only)
# ---------------------------------------------------------------------------
class TestExtractFactsEndToEnd(_H2Case):

    def test_turn_to_request_to_reply_to_retrievable_belief(self):
        """The whole loop, in order, with no step simulated: a real turn queues
        the work, the real attach hook renders it into the prompt, a host reply
        on the NEXT turn is parsed and applied, and the resulting belief is
        retrievable through search() carrying host provenance."""
        self.provider.sync_turn("Pat Testley just joined Acme Fake Co as a baker.",
                                "Congratulations to Pat.", session_id="s-h2")
        self.core.process_pending()

        req = self.pending("extract_facts")
        self.assertEqual(len(req), 1)
        self.assertIn("Pat Testley", json.loads(req[0]["payload"])["text"])

        rendered = self.provider.pre_llm_call()
        self.assertTrue(rendered.startswith("[chronicle]"))
        self.assertLessEqual(len(rendered), 400)
        rid = self.registry.attached_request()["request_id"]
        self.assertIn(rid, rendered)

        self.provider.sync_turn("thanks", fenced({
            "request_id": rid, "kind": "extract_facts",
            "facts": [{"subject": "Pat Testley", "attribute": "works_at",
                       "value": "Acme Fake Co"}]}), session_id="s-h2")
        self.core.process_pending()
        self.assertEqual(self.registry.get(rid)["status"], "answered")

        landed = [r for r in self.store.query_beliefs("facts", "1=1", (), 100)
                  if json.loads(r.get("provenance") or "{}").get("source") == PROVENANCE_SOURCE]
        self.assertEqual(len(landed), 1)
        self.assertEqual(landed[0]["value"], "Acme Fake Co")
        self.assertEqual(landed[0]["attribute"], "works_at")
        # The third provenance marker H1 defined: host-derived facts are
        # separable from both heuristic ("extractor-v1") and LLM-extractor
        # output forever after.
        self.assertEqual(landed[0]["extractor_version"], "host-model-v1")

        hits = self.core.retrieval.search("where does Pat Testley work", limit=10)
        self.assertIn(landed[0]["belief_id"], [h["belief_id"] for h in hits])

    def test_an_invalid_reply_expires_the_request_and_writes_nothing(self):
        """Discriminating partner for the same loop."""
        self.provider.sync_turn("Pat Testley just joined Acme Fake Co.", "Noted.",
                                session_id="s-h2")
        rid = self.registry.attached_request() or self.registry.next_pending()
        self.provider.pre_llm_call()
        rid = self.registry.attached_request()["request_id"]
        before = len(self.store.query_beliefs("facts", "1=1", (), 100))

        self.provider.sync_turn("thanks", "```json\n{not json at all}\n```",
                                session_id="s-h2")
        self.assertEqual(self.registry.get(rid)["status"], "expired")
        self.assertEqual(len(self.store.query_beliefs("facts", "1=1", (), 100)), before)

    def test_the_attach_hook_offers_the_drain_kinds(self):
        """H2 added two producers of work (belief writes offer doc2query,
        searches offer rerank). Both must be renderable by the same ≤400-char
        hook, or the drains can never run in production."""
        self.seed_fact(_TEMPLATED_KEY)
        self.core.retrieval.search("where does Pat Testley work", limit=5)
        kinds = {r["kind"] for r in self.registry.list_requests(status="pending")}
        self.assertIn("doc2query", kinds)
        self.assertIn("rerank", kinds)
        seen = set()
        for _ in range(3):
            request = self.registry.next_pending()
            if request is None:
                break
            rendered = self.provider.pre_llm_call()
            self.assertTrue(rendered)
            self.assertLessEqual(len(rendered), 400)
            seen.add(request["kind"])
            self.registry.mark_expired(request["request_id"])
        self.assertTrue({"doc2query", "rerank"} & seen)


# ---------------------------------------------------------------------------
# 4. excerpt tier (§H2.4)
# ---------------------------------------------------------------------------
class TestExcerptTier(unittest.TestCase):

    def make_core(self, excerpts):
        home = tempfile.mkdtemp(prefix="h2x-")
        self.addCleanup(shutil.rmtree, home, True)
        core = ChronicleCore(home, {"embeddings": {"model": "hashing",
                                                   "doc2query": {"excerpts": excerpts}}})
        core.initialize("s-x", principal_id="assistant")
        return core

    def observe(self, core, text):
        core.capture.observe(text, "Understood.", session_id="s-x")
        core.process_pending()
        return [r for r in core.store.iter_query_proxy_vectors() if r["kind"] == "observed"]

    def test_default_config_writes_no_excerpt_proxies(self):
        core = self.make_core(False)
        self.assertEqual(self.observe(core, "The Acme Fake Co server room flooded on Tuesday."),
                         [])

    def test_enabled_excerpt_proxies_resolve_through_the_raw_channel(self):
        """The claim: with the flag on, an excerpt proxy now CREDITS its parent
        event in retrieve_raw. Before H2 these rows resolved against the facts
        table and were dropped without trace."""
        core = self.make_core(True)
        rows = self.observe(core, "The Acme Fake Co server room flooded on Tuesday.")
        self.assertTrue(rows, "the flag wrote no excerpt proxies")
        event_id = rows[0]["belief_id"]

        # The proxy scan resolves to the parent EVENT id, not to a belief.
        emb = core.retrieval.query_understanding(rows[0]["question"])["embedding"]
        self.assertIn(event_id, [eid for eid, _s in core.retrieval._observed_proxies(emb, 10)])
        # ...and the belief tier no longer wastes a slot trying to resolve it.
        self.assertNotIn(event_id,
                         [bid for bid, _k, _s in core.retrieval._vector_proxies(emb, 10)])

        hits = core.retrieval.retrieve_raw(rows[0]["question"], limit=10)
        self.assertIn(event_id, [h["event_id"] for h in hits])

    def test_excerpt_proxies_are_cleaned_up_when_the_event_is_pruned(self):
        """No orphans: an excerpt proxy must not outlive the span it resolves
        to, or a forgotten event keeps scoring through the back door."""
        core = self.make_core(True)
        rows = self.observe(core, "The Acme Fake Co server room flooded on Tuesday.")
        event_id = rows[0]["belief_id"]

        core.store.delete_observed_vector(event_id)

        self.assertEqual([r for r in core.store.iter_query_proxy_vectors()
                          if r["belief_id"] == event_id], [])

    def test_the_prune_script_takes_excerpt_proxies_with_the_vectors(self):
        """scripts/prune_vectors.py is the retroactive half of
        embeddings.exclude_session_prefixes. Leaving proxies behind would let a
        pruned session keep scoring through the raw channel — i.e. silently
        undo the prune for exactly the sessions someone asked to exclude."""
        import sqlite3

        from scripts.prune_vectors import prune_vectors

        core = self.make_core(True)
        rows = self.observe(core, "The Acme Fake Co server room flooded on Tuesday.")
        self.assertTrue(rows)
        db = core.store.db_path

        prune_vectors(db, ["s-x"])

        conn = sqlite3.connect(db)
        try:
            self.assertEqual(conn.execute(
                "SELECT COUNT(*) FROM query_proxy_vectors WHERE kind='observed'").fetchone()[0], 0)
            self.assertEqual(conn.execute(
                "SELECT COUNT(*) FROM observed_vectors").fetchone()[0], 0)
        finally:
            conn.close()

    def test_belief_proxies_are_untouched_by_the_excerpt_cleanup(self):
        """Guards the edit: the delete is scoped by kind='observed', so it can
        never reach a belief that happens to share an id-shaped string."""
        core = self.make_core(True)
        core.capture.append("asserted", {
            "kind": "fact", "key": dict(_TEMPLATED_KEY), "body": "Acme Fake Co",
            "confidence": 0.9, "source_event": "src-x", "source_type": "user_direct",
            "domain": "user"}, actor="user", trust_level=4, session_id="s-x")
        core.process_pending()
        b_id = core.store.query_beliefs("facts", "1=1", (), 5)[0]["belief_id"]
        before = core.store.count_query_proxy_vectors(b_id)
        self.assertGreater(before, 0)

        core.store.delete_excerpt_proxies(b_id)

        self.assertEqual(core.store.count_query_proxy_vectors(b_id), before)


# ---------------------------------------------------------------------------
# The property all of the above may not cost
# ---------------------------------------------------------------------------
class TestH2DisabledPathIsInert(_H2Case):
    piggyback = None  # no host_model key at all: pure DEFAULTS

    def test_every_excluded_table_is_empty_at_defaults(self):
        """The assertion that LICENSES the inertness dump's exclusion list.

        Iterates H1_TABLES itself rather than naming tables. That is the whole
        point: the exclusion list is a hole in the byte-identity proof, and a
        hardcoded companion assertion does not guard the hole, it guards two
        specific names that happen to be in it today. Add a row-bearing table to
        H1_TABLES — memory_vectors, say — and a hardcoded check stays green
        while the dump silently stops comparing real rows. Derived from the list,
        the same edit fails here immediately.

        Runs the dump probe's OWN turn fixture (h1_store_dump.TURNS) so the
        emptiness claim is made about exactly the flow the exclusion is granted
        for, plus a search and an answer to cover H2's two read-path enqueue
        sites."""
        for user, assistant in TURNS:
            self.provider.sync_turn(user, assistant, session_id="s-h2")
            self.core.process_pending()
        self.core.retrieval.search("where does Pat Testley work", limit=5)
        self.core.retrieval.answer("where does Pat Testley work")

        self.assertTrue(H1_TABLES, "the exclusion list is empty; nothing is being guarded")
        conn = self.store._conn()
        for table in H1_TABLES:
            self.assertTrue(_has_table(conn, table), "excluded table %s does not exist" % table)
            self.assertEqual(
                conn.execute("SELECT COUNT(*) FROM %s" % table).fetchone()[0], 0,
                "%s is excluded from the inertness dump but is NOT empty at default "
                "config -- excluding it hides real rows from the byte-identity proof" % table)
        # ...and the heuristic path still ran, so the flow above was real.
        self.assertTrue(self.store.query_beliefs("facts", "1=1", (), 50))
        self.assertTrue(self.store.iter_memory_vectors(),
                        "fixture wrote no vectors, so 'excluded tables are empty' is untested "
                        "against any table that would actually have rows")

    def test_no_requests_are_offered_at_defaults(self):
        """H2 added two enqueue sites (belief writes, searches). Neither may
        fire with piggyback off."""
        self.core.capture.append("asserted", {
            "kind": "fact", "key": dict(_TEMPLATED_KEY), "body": "Acme Fake Co",
            "confidence": 0.9, "source_event": "src-d", "source_type": "user_direct",
            "domain": "user"}, actor="user", trust_level=4, session_id="s-h2")
        self.core.process_pending()
        self.core.retrieval.search("where does Pat Testley work", limit=5)
        self.assertEqual(self.registry.counts(), {"pending": 0, "answered": 0, "expired": 0})

    def test_template_proxies_are_written_exactly_as_before(self):
        """The merge lookup runs on the default path too (host_proxy_questions
        is consulted on every proxy write). With an empty host set the merge is
        the identity on the template list — order included."""
        self.core.capture.append("asserted", {
            "kind": "fact", "key": dict(_TEMPLATED_KEY), "body": "Acme Fake Co",
            "confidence": 0.9, "source_event": "src-t", "source_type": "user_direct",
            "domain": "user"}, actor="user", trust_level=4, session_id="s-h2")
        self.core.process_pending()
        b_id = self.store.query_beliefs("facts", "1=1", (), 5)[0]["belief_id"]
        self.assertEqual([r["question"] for r in sorted(self.proxies(b_id),
                                                        key=lambda r: r["proxy_idx"])],
                         ["where does Pat Testley work", "what is Pat Testley's job"])


class TestMergeRuleUnit(unittest.TestCase):
    """doc2query.merge_questions in isolation — the identity case is the one
    the inertness proof rests on."""

    def test_empty_host_set_is_the_identity_on_the_templates(self):
        templates = ["where does Pat Testley work", "what is Pat Testley's job"]
        self.assertEqual(doc2query.merge_questions([], templates), templates)
        self.assertEqual(doc2query.merge_questions(None, templates), templates)

    def test_duplicates_are_collapsed_case_insensitively(self):
        self.assertEqual(
            doc2query.merge_questions(["Where does Pat Testley work"],
                                      ["where does Pat Testley work", "what is Pat Testley's job"]),
            ["Where does Pat Testley work", "what is Pat Testley's job"])

    def test_the_cap_applies_to_the_merged_set(self):
        merged = doc2query.merge_questions(["h1", "h2", "h3"], ["t1", "t2", "t3"])
        self.assertEqual(merged, ["h1", "h2", "h3", "t1"])
        self.assertEqual(len(merged), doc2query.MAX_PROXIES)

    def test_non_strings_are_skipped_not_raised_on(self):
        self.assertEqual(doc2query.merge_questions([123, None, "ok"], ["t1"]), ["ok", "t1"])


class TestHintSignature(unittest.TestCase):

    def test_word_order_and_punctuation_do_not_matter(self):
        self.assertEqual(hint_signature("Where does Pat Testley work?")[0],
                         hint_signature("pat testley work where")[0])

    def test_a_different_subject_files_a_different_key(self):
        self.assertNotEqual(hint_signature("where does Pat Testley work")[0],
                            hint_signature("where does Sam Vimes work")[0])

    def test_an_all_stopword_query_files_nothing(self):
        self.assertEqual(hint_signature("what is it")[0], "")
        self.assertEqual(hint_signature("")[0], "")


if __name__ == "__main__":
    unittest.main()
