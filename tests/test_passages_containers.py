"""Chronicle — passages (whole documents) and containers (engine/passages.py).

A federated record's one projection vector sees its first thousand characters.
Passages are extra vectors over the rest of its text, stored beside it as
"<external_id>#p<n>"; search counts the record ONCE, at its best passage, and
shows that passage re-cut from the source. Records sharing a declared
container (a thread, a folder) collapse to the best one with a count. Every
fixture here is synthetic.
"""

import importlib.util
import json
import math
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from engine import passages as P  # noqa: E402
from engine.config import Config  # noqa: E402
from engine.core import ChronicleCore  # noqa: E402
from engine.embeddings import pack  # noqa: E402
from engine.localdb import LocalDBProvider  # noqa: E402
from engine.store import PROJECTION_TABLES  # noqa: E402

HAVE_NUMPY = importlib.util.find_spec("numpy") is not None
_needs_numpy = unittest.skipUnless(HAVE_NUMPY, "the float16 cache needs numpy")


# -- helpers ------------------------------------------------------------------

def _core():
    core = ChronicleCore(tempfile.mkdtemp(), {"embeddings": {"model": "hashing"}})
    core.initialize(session_id="eval", principal_id="assistant")
    return core


def _qvec(core, text):
    return list(core.retrieval.query_understanding(text)["embedding"])


def _unit(v):
    n = math.sqrt(sum(x * x for x in v))
    return [x / n for x in v]


def _near(q, noise, seed):
    """A unit vector at a controlled distance from q (larger noise, lower cosine)."""
    import random
    rng = random.Random(seed)
    r = _unit([rng.gauss(0, 1) for _ in q])
    return _unit([a + noise * b for a, b in zip(q, r)])


def _cos(a, b):
    return sum(x * y for x, y in zip(a, b))


def _add(core, provider, external_id, vec, owner="assistant"):
    core.store.add_projection_vector(provider, external_id, pack(vec), "hashing-v1", owner)


def _sweep(core):
    core.store.enqueue_curation("federate_sweep", {})
    core.curation.drain(max_jobs=10)


def _set_cache(core, on):
    core.cfg._d.setdefault("retrieval", {}).setdefault("projection_cache", {})["enabled"] = on


def _proj_hits(core, query, limit=10):
    return [r for r in core.retrieval.retrieve_raw(query, limit=limit)
            if r["event_id"].startswith("proj:")]


PARAS = (
    "Kayaking on Fake Lake at dawn: the paddle route runs past the old boathouse "
    "and the north shore reeds, about two hours round trip in calm water.",
    "The Acme Fake Co quarterly budget for the widget line was cut by a tenth; "
    "travel is frozen and the offsite moves to the spring.",
    "Renewing a Fakeland passport takes six weeks; bring two photos, the old "
    "passport, and the signed form to the counter on the second floor.",
)


def _docs_db(tmp, content=None):
    """A document table plus a separate content database joined on file_id --
    the shape where a record's full text lives outside its own row."""
    src = str(Path(tmp) / "docs.db")
    body = str(Path(tmp) / "doc_text.db")
    c = sqlite3.connect(src)
    c.execute("CREATE TABLE documents (id INTEGER PRIMARY KEY, file_id TEXT, name TEXT, "
              "folder TEXT)")
    c.executemany("INSERT INTO documents VALUES (?,?,?,?)", [
        (1, "f-one", "Field notes.pdf", "Home/Notes/2026"),
        (10, "f-ten", "Other file.pdf", "Home/Other"),
    ])
    c.commit()
    c.close()
    c = sqlite3.connect(body)
    c.execute("CREATE TABLE document_content (file_id TEXT PRIMARY KEY, content TEXT)")
    c.execute("INSERT INTO document_content VALUES (?, ?)",
              ("f-one", content if content is not None else "\n\n".join(PARAS)))
    c.execute("INSERT INTO document_content VALUES (?, ?)", ("f-ten", "short text"))
    c.commit()
    c.close()
    entry = {"name": "docs", "path": src, "table": "documents", "id_column": "id",
             "name_column": "name", "content_columns": ["name", "folder"],
             "capability": "documents", "read_only": True,
             "passages": {"from": {"path": body, "table": "document_content",
                                   "key_column": "file_id", "join_column": "file_id",
                                   "text_column": "content"},
                          "size": 200}}
    return src, body, entry


# -- the split ----------------------------------------------------------------

class TestSplitter(unittest.TestCase):
    def test_deterministic_and_bounded(self):
        text = "\n\n".join(PARAS * 20)
        a = P.split_passages(text, 300, 48)
        b = P.split_passages(text, 300, 48)
        self.assertEqual(a, b)
        self.assertTrue(a)
        self.assertTrue(all(0 < len(x) <= 300 for x in a))
        # Nothing lost or invented under the cap: the words come back in order.
        self.assertEqual(" ".join(a).split(), text.split())

    def test_paragraphs_are_kept_whole_when_they_fit(self):
        paras = ["A" * 400, "B" * 400, "C" * 400]
        self.assertEqual(P.split_passages("\n\n".join(paras), 900),
                         ["A" * 400 + "\n\n" + "B" * 400, "C" * 400])

    def test_lines_then_sentences_then_words_then_a_hard_cut(self):
        lines = "\n".join("%02d " % i + "x" * 97 for i in range(20))
        out = P.split_passages(lines, 900)
        self.assertEqual([x.count("\n") for x in out], [7, 7, 3])      # whole lines
        self.assertTrue(all(len(x) <= 900 for x in out))
        sent = " ".join("Sentence %d has enough words to be a sentence." % i for i in range(40))
        out = P.split_passages(sent, 250)
        self.assertTrue(all(x.endswith(".") for x in out), out)          # at sentence ends
        words = " ".join("w%03d" % i for i in range(400))                 # no sentence ends
        out = P.split_passages(words, 250)
        self.assertTrue(all(x.split()[-1].startswith("w") and len(x) <= 250 for x in out))
        self.assertEqual(" ".join(out).split(), words.split())
        self.assertEqual([len(x) for x in P.split_passages("z" * 2000, 900)], [900, 900, 200])

    def test_cap_empty_and_line_endings(self):
        self.assertEqual(len(P.split_passages("word " * 100000, 900, 48)), 48)
        self.assertEqual(P.split_passages("", 900), [])
        self.assertEqual(P.split_passages(None, 900), [])
        self.assertEqual(P.split_passages("a\r\nb", 900), P.split_passages("a\nb", 900))
        # A size below the floor cannot mint thousands of tiny passages.
        self.assertTrue(all(len(x) >= 100 for x in P.split_passages("q" * 1000, 5)[:-1]))

    def test_passage_ids(self):
        ext = P.passage_external_id("docs:7", 3)
        self.assertEqual(ext, "docs:7#p3")
        self.assertEqual(P.split_passage_id(ext), ("docs:7", 3))
        for not_one in ("docs:7", "docs:7#p03", "docs:7#px", "#p3", "", None):
            self.assertIsNone(P.split_passage_id(not_one)[1], not_one)


class TestSpecs(unittest.TestCase):
    def test_column_and_from_forms(self):
        cfg = Config({})
        self.assertEqual(cfg.get("federation.passages.size"), 900)
        self.assertEqual(cfg.get("federation.passages.max_per_record"), 48)
        ps = P.passage_spec({"name": "chats", "table": "days", "passages": {"column": "body"}}, cfg)
        self.assertEqual((ps.column, ps.size, ps.max_per_record, ps.id_column),
                         ("body", 900, 48, "id"))
        _s, _b, entry = _docs_db(tempfile.mkdtemp())
        ps = P.passage_spec(entry, cfg)
        self.assertEqual((ps.from_table, ps.key_column, ps.join_column, ps.text_column, ps.size),
                         ("document_content", "file_id", "file_id", "content", 200))
        cfg2 = Config({"federation": {"passages": {"size": 500, "max_per_record": 4}}})
        ps = P.passage_spec({"name": "c", "table": "t", "passages": {"column": "x"}}, cfg2)
        self.assertEqual((ps.size, ps.max_per_record), (500, 4))
        self.assertNotEqual(ps.recipe("m"), ps._replace(size=600).recipe("m"))

    def test_unexecutable_blocks_raise(self):
        base = {"name": "c", "table": "t"}
        for bad in ({"column": "x", "from": {"path": "p"}}, {}, {"size": 900},
                    {"from": {"path": "p", "table": "t"}}, {"column": "x", "size": 10}):
            with self.subTest(bad=bad):
                if not bad:
                    self.assertIsNone(P.passage_spec(dict(base, passages=bad)))
                    continue
                with self.assertRaises(ValueError):
                    P.passage_spec(dict(base, passages=bad))
        self.assertEqual(P.container_spec({"container": {"column": "thread_id"}}).label, "thread_id")
        with self.assertRaises(ValueError):
            P.container_spec({"container": {"label": "thread"}})


class TestLocalDbLookup(unittest.TestCase):
    def test_batched_string_keyed_and_schema_checked(self):
        path = str(Path(tempfile.mkdtemp()) / "t.db")
        c = sqlite3.connect(path)
        c.execute("CREATE TABLE rows (id INTEGER PRIMARY KEY, grp TEXT)")
        c.executemany("INSERT INTO rows VALUES (?,?)", [(i, "g%d" % (i % 3)) for i in range(1, 1201)])
        c.commit()
        c.close()
        db = LocalDBProvider("t", path, table="rows")
        got = db.lookup("rows", "id", list(range(1, 1201)) + ["7"], ["grp"])
        self.assertEqual(len(got), 1200)                    # past one IN-list chunk
        self.assertEqual(got["7"], {"grp": "g1"})
        self.assertEqual(db.lookup("rows", "id", [1], ["nope"]), {})
        self.assertEqual(db.lookup("absent", "id", [1], ["grp"]), {})


# -- retrieval ----------------------------------------------------------------

class TestPassagesInSearch(unittest.TestCase):
    QUERY = "the Acme Fake Co quarterly budget"

    def setUp(self):
        self.core = _core()
        self.tmp = tempfile.mkdtemp()
        _src, _body, self.entry = _docs_db(self.tmp)
        self.core.cfg._d["federation"]["local_dbs"] = [self.entry]
        _sweep(self.core)
        self.ext = "docs:1"
        self.assertIsNotNone(self.core.store.find_pointer("documents", "docs", self.ext))
        self.pieces = P.split_passages("\n\n".join(PARAS), 200)
        self.assertEqual(len(self.pieces), 3)
        q = _qvec(self.core, self.QUERY)
        self.vecs = {self.ext: _near(q, 3.0, 1),
                     self.ext + "#p0": _near(q, 1.5, 2),
                     self.ext + "#p1": _near(q, 0.3, 3),         # the best
                     self.ext + "#p2": _near(q, 0.9, 4)}
        for ext, v in self.vecs.items():
            _add(self.core, "docs", ext, v)
        self.best = _cos(q, self.vecs[self.ext + "#p1"])
        self.assertGreater(self.best, max(_cos(q, v) for k, v in self.vecs.items()
                                          if k != self.ext + "#p1"))

    def _check(self):
        hits = _proj_hits(self.core, self.QUERY)
        mine = [h for h in hits if h["event_id"].startswith("proj:docs:")]
        self.assertEqual([h["event_id"] for h in mine], ["proj:docs:" + self.ext])
        text = mine[0]["excerpt"]
        self.assertIn(self.pieces[1], text)                     # the best passage, re-cut
        self.assertNotIn("Kayaking", text)
        self.assertNotIn("passport", text)
        self.assertIn("passage 2 of 3", text)
        self.assertIn("Field notes.pdf", text)                  # the record it belongs to
        self.assertIn("Home/Notes/2026", text)
        self.assertAlmostEqual(mine[0]["score"], self.best * 0.5, delta=1e-6)

    def test_one_result_per_record_showing_its_best_passage(self):
        _set_cache(self.core, False)
        self._check()

    @_needs_numpy
    def test_same_through_the_float16_cache(self):
        _set_cache(self.core, True)
        self._check()

    def test_a_passage_the_source_no_longer_has_renders_the_plain_card(self):
        _set_cache(self.core, False)
        c = sqlite3.connect(self.entry["passages"]["from"]["path"])
        c.execute("UPDATE document_content SET content='now short' WHERE file_id='f-one'")
        c.commit()
        c.close()
        mine = [h for h in _proj_hits(self.core, self.QUERY)
                if h["event_id"] == "proj:docs:" + self.ext]
        self.assertEqual(len(mine), 1)
        self.assertNotIn("passage", mine[0]["excerpt"])
        self.assertIn("Field notes.pdf", mine[0]["excerpt"])


class TestContainersCollapse(unittest.TestCase):
    QUERY = "the offsite travel plan"

    def setUp(self):
        self.core = _core()
        self.tmp = tempfile.mkdtemp()
        src = str(Path(self.tmp) / "mail.db")
        c = sqlite3.connect(src)
        c.execute("CREATE TABLE messages (id INTEGER PRIMARY KEY, thread_id TEXT, "
                  "sender_name TEXT, subject TEXT, snippet TEXT)")
        c.executemany("INSERT INTO messages VALUES (?,?,?,?,?)", [
            (1, "t-1", "Pat Testley", "Offsite", "moving the offsite to spring"),
            (2, "t-1", "Sam Sample", "Re: Offsite", "spring works, travel frozen"),
            (3, "t-2", "Dee Dummy", "Travel", "the travel plan for the offsite"),
        ])
        c.commit()
        c.close()
        self.entry = {"name": "mailbox", "path": src, "table": "messages", "id_column": "id",
                      "name_column": "sender_name", "content_columns": ["subject", "snippet"],
                      "capability": "mail", "read_only": True,
                      "container": {"column": "thread_id", "label": "thread"}}
        self.core.cfg._d["federation"]["local_dbs"] = [self.entry]
        _sweep(self.core)
        q = _qvec(self.core, self.QUERY)
        _add(self.core, "mailbox", "mailbox:1", _near(q, 0.8, 11))
        _add(self.core, "mailbox", "mailbox:2", _near(q, 0.2, 12))     # best of thread t-1
        _add(self.core, "mailbox", "mailbox:3", _near(q, 0.5, 13))
        _set_cache(self.core, False)

    def test_records_sharing_a_container_collapse_to_the_best_with_a_count(self):
        hits = {h["event_id"]: h for h in _proj_hits(self.core, self.QUERY)}
        self.assertEqual(sorted(hits), ["proj:mailbox:mailbox:2", "proj:mailbox:mailbox:3"])
        best = hits["proj:mailbox:mailbox:2"]["excerpt"]
        self.assertIn("and 1 more in this thread", best)
        self.assertIn("Pat Testley", best)                      # names the one folded in
        self.assertNotIn("more in this thread", hits["proj:mailbox:mailbox:3"]["excerpt"])

    def test_the_container_key_is_never_stored_in_the_card(self):
        # A column in the card is part of every row's content hash: adding the
        # key there would re-embed the whole source.
        for ext in ("mailbox:1", "mailbox:2", "mailbox:3"):
            ptr = self.core.store.find_pointer("mail", "mailbox", ext)
            proj = json.loads(ptr["cached_projection"])
            self.assertNotIn("thread_id", proj["fields"])
            self.assertNotIn("t-1", json.dumps(proj))

    def test_a_container_column_the_source_lacks_fails_the_sweep(self):
        self.entry["container"] = {"column": "no_such_column", "label": "thread"}
        self.core.cfg._d["federation"]["local_dbs"] = [self.entry]
        with self.assertRaises(RuntimeError) as cm:
            self.core.curation._task_federate_sweep({})
        self.assertIn("no_such_column", str(cm.exception))


class TestChangedRowDropsItsPassages(unittest.TestCase):
    def test_sweep_drops_vector_passages_and_ledger_row_of_that_record_only(self):
        core = _core()
        src, _body, entry = _docs_db(tempfile.mkdtemp())
        core.cfg._d["federation"]["local_dbs"] = [entry]
        _sweep(core)
        d = len(_qvec(core, "x"))
        v = _unit([1.0] * d)
        for ext in ("docs:1", "docs:1#p0", "docs:1#p1", "docs:1#p2",
                    "docs:10", "docs:10#p0",          # a neighbour whose id extends ours
                    "docs:1#pnote"):                   # not a passage id: never matched
            _add(core, "docs", ext, v)
        conn = core.store._conn()
        for ext, n in (("docs:1", 3), ("docs:10", 1)):
            conn.execute("INSERT INTO passage_state(provider, external_id, content_hash, "
                         "text_hash, n, recipe, built_at) VALUES('docs',?,?,?,?,?,?)",
                         (ext, "h", "t", n, "v1", "now"))
        conn.commit()

        c = sqlite3.connect(src)
        c.execute("UPDATE documents SET name='Field notes (final).pdf' WHERE id=1")
        c.commit()
        c.close()
        _sweep(core)

        left = sorted(r[0] for r in conn.execute(
            "SELECT external_id FROM projection_vectors WHERE provider='docs'"))
        self.assertEqual(left, sorted(["docs:10", "docs:10#p0", "docs:1#pnote"]))
        state = [r[0] for r in conn.execute("SELECT external_id FROM passage_state")]
        self.assertEqual(state, ["docs:10"])

    def test_passage_state_is_projection_state(self):
        self.assertIn("passage_state", PROJECTION_TABLES)
        core = _core()
        conn = core.store._conn()
        conn.execute("INSERT INTO passage_state(provider, external_id, n) VALUES('p','p:1',2)")
        conn.commit()
        core.store.truncate_projection()
        self.assertEqual(conn.execute("SELECT COUNT(*) FROM passage_state").fetchone()[0], 0)


# -- the float16 cache counts records, not rows --------------------------------

@_needs_numpy
class TestCacheShortlistsRecords(unittest.TestCase):
    """With passages, the top-`limit` records can reach far below the limit-th
    best ROW. A row-level cut would drop them; the cache must return exactly
    what the paged scan returns."""

    QUERIES = ("kayaking on Fake Lake", "the Acme Fake Co quarterly budget",
               "renewing a Fakeland passport")

    @classmethod
    def setUpClass(cls):
        import numpy as np
        cls.core = _core()
        rng = np.random.default_rng(5)

        def off(q, dist):
            r = rng.standard_normal(q.shape[0])
            return _unit((q + dist * r / np.linalg.norm(r)).tolist())

        n = 0
        for qi, text in enumerate(cls.QUERIES):
            q = np.asarray(_qvec(cls.core, text), dtype=np.float64)
            # One record whose 30 passages crowd the very top ...
            _add(cls.core, "prov", "hog-%d" % qi, off(q, 3.0))
            for j in range(30):
                _add(cls.core, "prov", "hog-%d#p%d" % (qi, j), off(q, rng.uniform(0.05, 0.2)))
            # ... and ordinary records, some with passages, all below them.
            for j in range(40):
                ext = "rec-%04d" % n
                prov = "prov%d" % (n % 2)
                _add(cls.core, prov, ext, off(q, rng.uniform(0.4, 2.0)),
                     owner="other" if j % 9 == 4 else "assistant")
                for k in range(j % 4):
                    _add(cls.core, prov, "%s#p%d" % (ext, k), off(q, rng.uniform(0.4, 2.0)))
                n += 1

    def _run(self, text, on, limit):
        _set_cache(self.core, on)
        return [(r["event_id"], float(r["score"]))
                for r in self.core.retrieval.retrieve_raw(text, limit=limit)]

    def test_same_records_and_scores_as_the_paged_scan(self):
        for text in self.QUERIES:
            for limit in (1, 3, 5, 10, 25):
                with self.subTest(q=text, limit=limit):
                    off = self._run(text, False, limit)
                    on = self._run(text, True, limit)
                    self.assertTrue(off)
                    self.assertEqual([e for e, _ in on], [e for e, _ in off])
                    for (_a, s1), (_b, s2) in zip(on, off):
                        self.assertAlmostEqual(s1, s2, delta=1e-6)
                    ids = [e for e, _ in off]
                    self.assertFalse([e for e in ids if "#p" in e], "a passage leaked as a hit")
                    self.assertEqual(len(ids), len(set(ids)))
                    if limit >= 5:
                        # The crowding record is ONE hit, and the rest still come.
                        self.assertGreaterEqual(len(ids), 5)
        cache = getattr(self.core.store, "_projection_vector_cache", None)
        self.assertIsNotNone(cache)
        self.assertGreater(cache.served, 0)


# -- the source map counts records with a vector ---------------------------------

class TestCacheMapCountsRecords(unittest.TestCase):
    def test_passages_do_not_count_as_coverage(self):
        from engine import cache_map
        core = _core()
        src, _body, entry = _docs_db(tempfile.mkdtemp())
        core.cfg._d["federation"]["local_dbs"] = [entry]
        core.cfg._d["cache_map"]["sources"] = {"docs": {"label": "Docs", "unit": "files",
                                                         "date_column": ""}}
        _sweep(core)
        v = _unit([1.0] * len(_qvec(core, "x")))
        for ext in ("docs:1", "docs:1#p0", "docs:1#p1", "docs:1#p2", "docs:1#p3"):
            _add(core, "docs", ext, v)
        core.store._conn().commit()
        text = cache_map.build(core.store.db_path, core.cfg)
        line = next(ln for ln in text.splitlines() if ln.startswith("- Docs"))
        self.assertIn("2 files", line)
        self.assertIn("50% searchable by meaning", line)


if __name__ == "__main__":
    unittest.main()
