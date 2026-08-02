"""
Chronicle — Retrieval (§18): dual-tier + read-and-answer.

Tier 1 hits the belief layer (FTS5 + brute-force ANN + structured), fused by
Reciprocal Rank Fusion. When Tier 1 is insufficient, Tier 2 retrieves raw spans
+ session summaries (the recall floor, I23) and a read step answers from them and
writes the belief back (promote-on-read, §16.7) — so a fact present in a durable
`observed` event is answerable even if eager extraction missed it. Every path
applies, in order: ACL (active principal), status, trust/info-label, purpose
(I11), temporal validity, domain. With no support in either tier or via
derivation, it abstains (I8) rather than fabricates.
"""

from __future__ import annotations

import heapq
import json
import logging
import re
from typing import Dict, List

from . import access
from .config import DEFAULTS, check_abstain_gate
from .embeddings import unpack, cosine, batch_cosine, pack
from .trust import Calibrator, confidence_summary
from .store import now_iso, KIND_TABLE
from .vector_index import VectorIndex, MAX_K as KNN_MAX_K

logger = logging.getLogger("chronicle.retrieval")

_STOP = {"the", "a", "an", "is", "are", "what", "who", "where", "when", "how", "do", "does",
         "did", "my", "your", "of", "to", "in", "on", "for", "and", "or", "i", "me", "s",
         "was", "were", "it", "that", "this", "with", "about", "tell", "show", "name"}

_MONTHS = {m: i + 1 for i, m in enumerate(
    ["january", "february", "march", "april", "may", "june", "july",
     "august", "september", "october", "november", "december"])}
_MONTH_RX = "(" + "|".join(m[:3] + r"[a-z]*" for m in _MONTHS) + ")"
_RX_ISO = re.compile(r"\b(20\d{2})[-/](\d{1,2})[-/](\d{1,2})\b")
_RX_MDY = re.compile(r"\b" + _MONTH_RX + r"\.?\s+(\d{1,2})(?:st|nd|rd|th)?,?\s+(20\d{2})\b", re.I)
_RX_DMY = re.compile(r"\b(\d{1,2})(?:st|nd|rd|th)?\s+(?:of\s+)?" + _MONTH_RX + r"\.?,?\s+(20\d{2})\b", re.I)
_RX_MY = re.compile(r"\b" + _MONTH_RX + r"\.?,?\s+(20\d{2})\b", re.I)
_RX_Y = re.compile(r"\b(?:in|during|of)\s+(20\d{2})\b", re.I)
# Relative time expressions: yesterday, today, last/this week/month/year, N days/weeks/months ago
# "N" accepts either digits ("3 weeks ago") or word-form number names ("three
# weeks ago", "a month ago", "an hour ago" is out of scope but "a"/"an" -> 1
# reads naturally for "a week ago" / "a month ago").
_WORD_NUMS = {
    "a": 1, "an": 1, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5,
    "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10, "eleven": 11,
    "twelve": 12,
}
_RX_YESTERDAY = re.compile(r"\byesterday\b", re.I)
_RX_TODAY = re.compile(r"\btoday\b", re.I)
_RX_LAST_WEEK = re.compile(r"\blast\s+week\b", re.I)
_RX_LAST_MONTH = re.compile(r"\blast\s+month\b", re.I)
_RX_LAST_YEAR = re.compile(r"\blast\s+year\b", re.I)
_RX_THIS_WEEK = re.compile(r"\bthis\s+week\b", re.I)
_RX_THIS_MONTH = re.compile(r"\bthis\s+month\b", re.I)
_NUM_WORD = r"(\d+|" + "|".join(sorted(_WORD_NUMS, key=len, reverse=True)) + r")"
_RX_N_DAYS_AGO = re.compile(r"\b" + _NUM_WORD + r"\s+days?\s+ago\b", re.I)
_RX_N_WEEKS_AGO = re.compile(r"\b" + _NUM_WORD + r"\s+weeks?\s+ago\b", re.I)
_RX_N_MONTHS_AGO = re.compile(r"\b" + _NUM_WORD + r"\s+months?\s+ago\b", re.I)


def _month_num(name):
    low = name.lower()
    for full, num in _MONTHS.items():
        if full.startswith(low[:3]):
            return num
    return None


def _to_int(token):
    """'3' -> 3, 'three' -> 3, 'a'/'an' -> 1 (word-form or digit-form N-ago)."""
    if token.isdigit():
        return int(token)
    return _WORD_NUMS.get(token.lower())


def _parse_time_window(text, now=None):
    """Absolute or relative time expression in *text* → ("YYYY-MM-DD", "YYYY-MM-DD"), else None.

    Narrowest wins: an explicit day beats a month beats a bare year.

    Relative expressions ("last week", "yesterday", "N/word-form days/weeks/
    months ago", "this/last week/month/year") require a "now" reference point:
    "YYYY-MM-DD", or any string starting with it (e.g. full ISO-8601
    "YYYY-MM-DDTHH:MM:SSZ") -- only the calendar date is used. If a relative
    expression is found and now is absent or unparseable, returns None (never
    guesses). When now is provided, resolves relative expressions against it.
    """
    import calendar
    from datetime import datetime, timedelta

    # Try absolute patterns first (highest priority)
    m = _RX_ISO.search(text)
    if m:
        y, mo, d = int(m.group(1)), int(m.group(2)), int(m.group(3))
        if 1 <= mo <= 12 and 1 <= d <= 31:
            day = "%04d-%02d-%02d" % (y, mo, d)
            return (day, day)
    for rx, mi, di, yi in ((_RX_MDY, 1, 2, 3), (_RX_DMY, 2, 1, 3)):
        m = rx.search(text)
        if m:
            mo = _month_num(m.group(mi))
            if mo:
                day = "%04d-%02d-%02d" % (int(m.group(yi)), mo, int(m.group(di)))
                return (day, day)
    m = _RX_MY.search(text)
    if m:
        mo = _month_num(m.group(1))
        if mo:
            y = int(m.group(2))
            return ("%04d-%02d-01" % (y, mo),
                    "%04d-%02d-%02d" % (y, mo, calendar.monthrange(y, mo)[1]))
    m = _RX_Y.search(text)
    if m:
        y = m.group(1)
        return (y + "-01-01", y + "-12-31")

    # Relative patterns (require now)
    if now is None:
        return None  # Can't resolve relative without now

    # Parse now. Accepts a bare "YYYY-MM-DD" or any string that STARTS with one
    # (e.g. full ISO-8601 "YYYY-MM-DDTHH:MM:SSZ", as produced by callers that
    # stamp `now` from an event/question timestamp) -- only the calendar date
    # matters for day/week/month/year arithmetic. Anything else (missing,
    # malformed) returns None rather than guessing.
    m_now = re.match(r"(\d{4})-(\d{2})-(\d{2})", str(now))
    if not m_now:
        return None
    try:
        now_dt = datetime(int(m_now.group(1)), int(m_now.group(2)), int(m_now.group(3)))
    except (ValueError, TypeError):
        return None

    # Yesterday
    if _RX_YESTERDAY.search(text):
        target = now_dt - timedelta(days=1)
        day = target.strftime("%Y-%m-%d")
        return (day, day)

    # Today
    if _RX_TODAY.search(text):
        day = now_dt.strftime("%Y-%m-%d")
        return (day, day)

    # N days ago (digit or word-form: "3 days ago" / "three days ago")
    m = _RX_N_DAYS_AGO.search(text)
    if m:
        n = _to_int(m.group(1))
        if n is None:
            return None
        target = now_dt - timedelta(days=n)
        day = target.strftime("%Y-%m-%d")
        return (day, day)

    # N weeks ago (digit or word-form)
    m = _RX_N_WEEKS_AGO.search(text)
    if m:
        n = _to_int(m.group(1))
        if n is None:
            return None
        target = now_dt - timedelta(weeks=n)
        day = target.strftime("%Y-%m-%d")
        return (day, day)

    # N months ago (digit or word-form)
    m = _RX_N_MONTHS_AGO.search(text)
    if m:
        n = _to_int(m.group(1))
        if n is None:
            return None
        # Move back N months
        month = now_dt.month - n
        year = now_dt.year
        while month <= 0:
            month += 12
            year -= 1
        # Clamp day to valid range for target month
        max_day = calendar.monthrange(year, month)[1]
        day_val = min(now_dt.day, max_day)
        target = datetime(year, month, day_val)
        day = target.strftime("%Y-%m-%d")
        return (day, day)

    # Last week (start of the week containing last week)
    if _RX_LAST_WEEK.search(text):
        # "Last week" = the week 7+ days ago from now
        target = now_dt - timedelta(days=7)
        # Find Monday of that week
        days_since_monday = target.weekday()  # 0=Monday, 6=Sunday
        week_start = target - timedelta(days=days_since_monday)
        week_end = week_start + timedelta(days=6)
        return (week_start.strftime("%Y-%m-%d"), week_end.strftime("%Y-%m-%d"))

    # This week (Monday to Sunday of current week)
    if _RX_THIS_WEEK.search(text):
        days_since_monday = now_dt.weekday()
        week_start = now_dt - timedelta(days=days_since_monday)
        week_end = week_start + timedelta(days=6)
        return (week_start.strftime("%Y-%m-%d"), week_end.strftime("%Y-%m-%d"))

    # Last month
    if _RX_LAST_MONTH.search(text):
        # Move to previous month, same day (or last day of month if month is shorter)
        month = now_dt.month - 1
        year = now_dt.year
        if month <= 0:
            month += 12
            year -= 1
        max_day = calendar.monthrange(year, month)[1]
        day_val = min(now_dt.day, max_day)
        month_start = datetime(year, month, 1)
        month_end = datetime(year, month, max_day)
        return (month_start.strftime("%Y-%m-%d"), month_end.strftime("%Y-%m-%d"))

    # This month
    if _RX_THIS_MONTH.search(text):
        month_start = datetime(now_dt.year, now_dt.month, 1)
        max_day = calendar.monthrange(now_dt.year, now_dt.month)[1]
        month_end = datetime(now_dt.year, now_dt.month, max_day)
        return (month_start.strftime("%Y-%m-%d"), month_end.strftime("%Y-%m-%d"))

    # Last year
    if _RX_LAST_YEAR.search(text):
        year = now_dt.year - 1
        year_start = datetime(year, 1, 1)
        year_end = datetime(year, 12, 31)
        return (year_start.strftime("%Y-%m-%d"), year_end.strftime("%Y-%m-%d"))

    return None

# Content tokens that carry no discriminating power for the focus gate — every
# session transcript mentions them, so covering them proves nothing (§18.4).
_GENERIC = {"user", "name", "time", "day", "week", "thing", "info"}

# §r6: the most topic-gated standing notes get_context will append from leftover
# budget. Bounds the tail on a store where a broad focus token ("work") matches
# dozens of norm notes; the char budget is the other, harder stop.
_TOPIC_NOTE_CAP = 5


def _clamp_cfg(cfg, key, default, lo, hi):
    """An int config knob that a bad value cannot turn into an unbounded read.

    A defensive cap is worth nothing if `session_window_max_events: null` (or
    "60", or -1) in someone's config.yaml disables it. Anything unparseable
    falls back to `default`, and the result is clamped into [lo, hi]."""
    raw = cfg.get(key, default) if cfg else default
    try:
        val = int(raw)
    except (TypeError, ValueError):
        val = int(default)
    return max(lo, min(hi, val))


class RetrievalEngine:
    def __init__(self, store, cfg=None, embedder=None, derivation=None, active_principal="default",
                 vector_index=None):
        self.store = store
        self.cfg = cfg
        self.embedder = embedder
        self.derivation = derivation
        self.active_principal = active_principal
        min_obs = cfg.get("calibration.min_obs", 50) if cfg else 50
        self.calibrator = Calibrator(store, min_obs)
        self._rrf_k = cfg.get("retrieval.rrf_k", 60) if cfg else 60
        self._fts_w = cfg.get("retrieval.fts_weight", 0.4) if cfg else 0.4
        self._vec_w = cfg.get("retrieval.vector_weight", 0.6) if cfg else 0.6
        self._gate = cfg.get("retrieval.read_and_answer.confidence_gate", 0.55) if cfg else 0.55
        self._miss_threshold = cfg.get("retrieval.miss_threshold", 0.15) if cfg else 0.15
        # Optional ANN index (sqlite-vec backend) for fast KNN lookup (§27, u5).
        # Reuse the store's own instance when one exists -- ChronicleCore builds
        # exactly one and assigns it to both store.vector_index (writes) and here
        # (reads), so they share ONE `dims`/sticky-failure state instead of two
        # independently-probing duplicates. Falls back to building a fresh one
        # only for callers that construct a RetrievalEngine directly against a
        # bare store that was never wired to a core (tests, scripts).
        if vector_index is not None:
            self.vector_index = vector_index
        elif getattr(store, "vector_index", None) is not None:
            self.vector_index = store.vector_index
        elif cfg is not None:
            self.vector_index = VectorIndex(store, cfg, embedder=embedder)
        else:
            self.vector_index = None
        # Support gate (I8, §18.4). Gate + thresholds picked by
        # scripts/sweep_abstain.py; defaults mirror DEFAULTS["retrieval"] so an
        # engine built without a Config behaves the same.
        d = DEFAULTS["retrieval"]
        self._abstain_gate = check_abstain_gate(
            cfg.get("retrieval.abstain_gate", d["abstain_gate"]) if cfg else d["abstain_gate"])
        self._score_threshold = _clamp(
            cfg.get("retrieval.score_threshold", d["score_threshold"]) if cfg else d["score_threshold"])
        self._focus_coverage = _clamp(
            cfg.get("retrieval.focus_coverage", d["focus_coverage"]) if cfg else d["focus_coverage"])
        self._overlap_min_tokens = int(_clamp(
            cfg.get("retrieval.overlap_min_tokens", d["overlap_min_tokens"]) if cfg
            else d["overlap_min_tokens"], 1, 64))

    # -- query understanding (§18.2) --------------------------------------

    def _tokens(self, query: str) -> List[str]:
        return [t for t in re.findall(r"[A-Za-z0-9']+", query.lower())
                if t not in _STOP and len(t) > 1]

    def query_understanding(self, query: str) -> dict:
        tokens = self._tokens(query)
        expansions = set(tokens)
        for t in list(tokens):
            for syn in self.store.predicate_synonyms(t):
                expansions.add(syn)
        emb = None
        if self.embedder is not None:
            try:
                emb = self.embedder.embed(" ".join(expansions) or query)
            except Exception:
                emb = None  # vector channel drops out; FTS + structured still answer
        return {"raw": query, "tokens": tokens, "expanded": list(expansions), "embedding": emb}

    # -- Tier 1 (§18.1) ----------------------------------------------------

    def search(self, query, *, limit=10, domain=None, purpose="*", principal=None, now=None):
        principal = principal or self.active_principal
        q = self.query_understanding(query)
        ranked: Dict[str, dict] = {}

        def add(bid, table, rank, channel):
            row = self.store.get_belief(table, bid)
            if not row or not self._readable(row, principal, purpose, domain):
                return
            # §u2: a consolidation digest restates facts that are already indexed,
            # so letting it compete here would push its own sources down the
            # ranking and answer with a summary where a verbatim value exists.
            # One choke point covers every channel (fts, vector, graph).
            if table == "notes" and str(row.get("subject") or "").startswith("digest:"):
                return
            w = {"fts": self._fts_w, "vector": self._vec_w,
                 "graph": self._graph_w()}.get(channel, 0.3)
            entry = ranked.setdefault(bid, {"row": row, "table": table, "score": 0.0, "why": set()})
            entry["score"] += w / (self._rrf_k + rank)
            entry["why"].add(channel)

        of = self.cfg_overfetch()
        for i, r in enumerate(self.store.fts_search_beliefs(query, limit=limit * of)):
            add(r["belief_id"], _table_of_kind(r["kind"]), i + 1, "fts")
        if q["embedding"] is not None:
            for i, (bid, kind, _s) in enumerate(self._vector_beliefs(q["embedding"], limit * of)):
                add(bid, _table_of_kind(kind), i + 1, "vector")
        for tok in q["tokens"]:
            for r in self.store.query_beliefs(
                    "facts", "status IN ('active','draft') AND (value LIKE ? OR attribute LIKE ? "
                    "OR predicate_canonical LIKE ?)", (f"%{tok}%", f"%{tok}%", f"%{tok}%"), limit=limit):
                add(r["belief_id"], "facts", 5, "structured")

        # Graph channel (§18.8): the entity/relationship graph answers at READ
        # time, not just write time. Query tokens resolve to entities by name AND
        # to relationships by predicate ("wife", "sister" are predicates, not
        # entity names); one hop of active relationships then lets the neighbors'
        # facts compete in the ranking — "where does my wife work" reaches
        # works_at(spouse) through spouse(user, …), which no lexical or vector
        # channel can. Bounded (≤6 seed nodes, 1 hop, ≤8 facts/node); an empty
        # graph is a no-op.
        nodes = self._graph_seeds(q["tokens"])
        hop: List[str] = []
        for e in nodes[:3]:
            for r in self.store.query_beliefs(
                    "relationships", "(source_id=? OR target_id=?) AND status='active'", (e, e), 8):
                for nb in (r.get("source_id"), r.get("target_id")):
                    if nb and nb not in nodes and nb not in hop:
                        hop.append(nb)
        for rank, e in enumerate(nodes[:6] + hop[:6]):
            for f in self.store.query_beliefs("facts", "entity_id=? AND status='active'", (e,), 8):
                add(f["belief_id"], "facts", rank + 1, "graph")

        out = []
        for bid, e in ranked.items():
            row = e["row"]
            out.append({
                "belief_id": bid, "table": e["table"], "kind": _kind_of_table(e["table"]),
                "score": e["score"], "channels": sorted(e["why"]),
                "value": row.get("value") or row.get("body") or row.get("summary") or row.get("name"),
                "entity_id": row.get("entity_id"), "attribute": row.get("attribute"),
                "confidence": row.get("confidence"), "status": row.get("status"),
                "source_type": json.loads(row.get("provenance") or "{}").get("source_type"),
            })
        out.sort(key=lambda x: x["score"], reverse=True)
        return out[:limit]

    # -- Tier 2 (§18.1) — raw layer (recall floor) ------------------------

    def _graph_seeds(self, tokens, cap=6) -> List[str]:
        """Query tokens → entity nodes (§18.8). Names match entities directly;
        predicates ("wife", "sister") reach entities through relationships.
        Shared with get_context so the digest surface seeds on exactly the same
        entities the graph channel does, rather than a second guess at it."""
        nodes: List[str] = []
        for tok in tokens:
            if len(tok) < 3 or len(nodes) >= cap:
                continue
            for e in self.store.query_beliefs(
                    "entities", "normalized_name LIKE ? AND merged_into IS NULL",
                    (f"%{tok}%",), 2):
                if e.get("belief_id") and e["belief_id"] not in nodes:
                    nodes.append(e["belief_id"])
            for r in self.store.query_beliefs(
                    "relationships", "predicate LIKE ? AND status='active'", (f"%{tok}%",), 4):
                for nb in (r.get("source_id"), r.get("target_id")):
                    if nb and nb not in nodes:
                        nodes.append(nb)
        return nodes

    def _graph_w(self):
        try:
            gw = float(self.cfg.get("retrieval.graph_weight", 0.25)) if self.cfg else 0.25
        except (TypeError, ValueError):
            gw = 0.25
        return max(0.0, min(1.0, gw))

    def _temporal_boost(self):
        try:
            tb = float(self.cfg.get("retrieval.temporal_boost", 0.5)) if self.cfg else 0.5
        except (TypeError, ValueError):
            tb = 0.5
        return max(0.0, min(2.0, tb))

    def retrieve_raw(self, query, *, limit=20, principal=None, now=None):
        principal = principal or self.active_principal
        q = self.query_understanding(query)
        scored: Dict[str, dict] = {}
        for i, r in enumerate(self.store.fts_search_observed(query, limit=limit)):
            ev = self.store.get_event(r["event_id"])
            if ev and access.can_read(access.DEFAULT_ACL, ev["owner"], principal):
                scored.setdefault(r["event_id"], {"excerpt": r["excerpt"], "score": 0.0,
                                                  "owner": ev["owner"]})["score"] += self._fts_w / (self._rrf_k + i + 1)
        # limit <= 0 has no top-k to fill (baseline returned [] via out[:limit]) and
        # would index an empty heap, so the vector scan is skipped outright.
        if q["embedding"] is not None and limit > 0:
            # Streaming top-k (§24.3, t8): observed_vectors/session_index can hold
            # far more rows than `limit`, so the scan below never materializes the
            # full table. A candidate already in `scored` (an FTS hit, bounded to
            # <= limit entries by the loop above) is updated in place — no growth.
            # A genuinely new candidate competes for a fixed-size (`limit`) min-heap;
            # keeping only the running top-`limit` while streaming a batch at a time
            # is equivalent to sorting the whole corpus and taking the top-`limit`
            # (anything that never displaces the heap's current minimum can never
            # have outscored the true top-`limit` cutoff — the standard streaming
            # top-k argument). Memory is therefore O(batch_size + limit), not
            # O(corpus size); the event/payload fetch is skipped entirely for
            # candidates that can't possibly survive, so compute stays cheap too.
            vec_heap: List[tuple] = []  # (score, seq, event_id, excerpt, owner) — min-heap on score
            seq = 0

            # Optional ANN fast path (§27 vector_index:, u5). vec0's KNN MATCH
            # replaces the paged scan only for NEW candidates; the FTS hits
            # already in `scored` are credited separately, below, because a
            # bounded window cannot be relied on to contain them. Anything that
            # comes back empty (unconfigured, library absent, no loadable-
            # extension support, vec0 never created, nothing above the floor)
            # falls through to the paged scan exactly as before.
            knn_results = []
            query_bytes = None
            if self.vector_index is not None and self.vector_index.is_enabled():
                try:
                    query_bytes = pack(q["embedding"])
                    knn_results = self.vector_index.retrieve_knn(query_bytes, limit * 2)
                except Exception as e:
                    logger.warning("vector_index KNN failed (%s); using the paged scan", e)
                    knn_results = []

            if knn_results:
                # (1) Every FTS hit gets the SAME `_vec_w * cos` the paged scan
                #     would have given it — same batch_cosine arithmetic on the
                #     same stored blob, same `> 0.1` floor, same ACL check —
                #     fetched by id instead of stumbled over mid-scan. Skipping
                #     this is not a rounding difference: an FTS hit just outside
                #     the KNN window loses its ENTIRE vector contribution and
                #     drops out of the top-k the paged path returns it in.
                vrows = self.store.get_observed_vectors_by_ids(list(scored))
                fids = [eid for eid in scored if eid in vrows]
                fsims = batch_cosine(q["embedding"], [vrows[eid]["embedding"] for eid in fids])
                for eid, sim in zip(fids, fsims):
                    if sim > 0.1 and access.can_read(access.DEFAULT_ACL, vrows[eid].get("owner"), principal):
                        scored[eid]["score"] += self._vec_w * sim

                # (2) New candidates compete for the same fixed-size heap the
                #     paged scan fills, on the same terms.
                seen = set()

                def _consider(eid, sim):
                    nonlocal seq
                    if sim <= 0.1 or eid in scored or eid in seen:
                        return
                    seen.add(eid)
                    contribution = self._vec_w * sim
                    if len(vec_heap) >= limit and contribution <= vec_heap[0][0]:
                        return  # can't displace the current floor; skip the event fetch
                    # Owner off the event, not observed_vectors: the row is
                    # fetched here anyway (for the excerpt) and the reducer
                    # copies event.owner into observed_vectors.owner in the same
                    # breath, so the two are the same value and the paged scan's
                    # ACL decision is reproduced exactly, one query cheaper.
                    ev = self.store.get_event(eid)
                    if not ev or not access.can_read(access.DEFAULT_ACL, ev["owner"], principal):
                        return
                    p = json.loads(ev["payload"]) if isinstance(ev["payload"], str) else (ev["payload"] or {})
                    entry = (contribution, seq, eid, p.get("excerpt", ""), ev["owner"])
                    seq += 1
                    if len(vec_heap) < limit:
                        heapq.heappush(vec_heap, entry)
                    else:
                        heapq.heapreplace(vec_heap, entry)

                # Window size: FTS puts at most `limit` ids into `scored`, and
                # every KNN row landing there is consumed by (1) rather than the
                # heap, so 2·limit rows still leave `limit` new candidates — the
                # exact heap capacity. ACL filtering is the one thing that can
                # prune below it (the 0.1 floor cannot: rows arrive similarity-
                # descending, so once it bites it bites for the whole tail), so
                # widen until the heap is full, the floor is crossed, or vec0 is
                # exhausted. Rows are re-fetched, not appended, because a wider k
                # returns a superset from the top — `seen` makes re-processing an
                # already-considered id a no-op regardless of tie ordering.
                k, pos = limit * 2, 0
                while True:
                    for eid, sim in knn_results[pos:]:
                        _consider(eid, sim)
                    pos = len(knn_results)
                    if (len(vec_heap) >= limit or len(knn_results) < k
                            or knn_results[-1][1] <= 0.1 or k >= KNN_MAX_K):
                        break
                    k = min(k * 2, KNN_MAX_K)
                    wider = self.vector_index.retrieve_knn(query_bytes, k)
                    if len(wider) <= pos:
                        break  # vec0 has nothing more to offer
                    knn_results, pos = wider, 0
            else:
                # Paged brute-force scan (§24.3) — the default, and the fallback
                # whenever the ANN path is unavailable or came back empty.
                for batch in self.store.iter_observed_vectors_paged(batch_size=1000):
                    osims = batch_cosine(q["embedding"], [v["embedding"] for v in batch])
                    for i, v in enumerate(batch):
                        if osims[i] <= 0.1:
                            continue
                        if not access.can_read(access.DEFAULT_ACL, v.get("owner"), principal):
                            continue
                        eid = v["event_id"]
                        contribution = self._vec_w * osims[i]
                        if eid in scored:
                            scored[eid]["score"] += contribution
                            continue
                        if len(vec_heap) >= limit and contribution <= vec_heap[0][0]:
                            continue  # can't displace the current floor; skip the event fetch
                        ev = self.store.get_event(eid)
                        p = json.loads(ev["payload"]) if ev and isinstance(ev["payload"], str) else (ev or {}).get("payload", {})
                        entry = (contribution, seq, eid, p.get("excerpt", ""), v.get("owner"))
                        seq += 1
                        if len(vec_heap) < limit:
                            heapq.heappush(vec_heap, entry)
                        else:
                            heapq.heapreplace(vec_heap, entry)
            for contribution, _seq, eid, excerpt, owner in vec_heap:
                scored[eid] = {"excerpt": excerpt, "score": contribution, "owner": owner}

            # Paged session-vector streaming, same bounded top-k treatment. Session
            # ids are namespaced "session:" so they never collide with event ids.
            sess_heap: List[tuple] = []  # (score, seq, session_id, summary, owner)
            seq = 0
            for batch in self.store.iter_session_vectors_paged(batch_size=1000):
                for s in batch:
                    if not s.get("embedding"):
                        continue
                    sim = cosine(q["embedding"], unpack(s["embedding"]))
                    if sim <= 0.15 or not access.can_read(access.DEFAULT_ACL, s.get("owner"), principal):
                        continue
                    entry = (sim * 0.5, seq, s["session_id"], s.get("summary", ""), s.get("owner"))
                    seq += 1
                    if len(sess_heap) < limit:
                        heapq.heappush(sess_heap, entry)
                    elif entry[0] > sess_heap[0][0]:
                        heapq.heapreplace(sess_heap, entry)
            for sim_score, _seq, session_id, summary, owner in sess_heap:
                scored["session:" + session_id] = {"excerpt": summary, "score": sim_score, "owner": owner}

            # Paged projection-vector streaming (§g5 projections). Similar bounded top-k
            # treatment to observed and session vectors. Projection ids are namespaced
            # "proj:<provider>:<external_id>" so they never collide with event or session ids.
            proj_heap: List[tuple] = []  # (score, seq, proj_id, excerpt, owner)
            seq = 0
            for batch in self.store.iter_projection_vectors_paged(batch_size=1000):
                psims = batch_cosine(q["embedding"], [v["embedding"] for v in batch])
                for i, v in enumerate(batch):
                    if psims[i] <= 0.15:
                        continue
                    if not access.can_read(access.DEFAULT_ACL, v.get("owner"), principal):
                        continue
                    proj_id = f"proj:{v['provider']}:{v['external_id']}"
                    entry = (psims[i] * 0.5, seq, proj_id, f"{v['provider']}:{v['external_id']}", v.get("owner"))
                    seq += 1
                    if len(proj_heap) < limit:
                        heapq.heappush(proj_heap, entry)
                    elif entry[0] > proj_heap[0][0]:
                        heapq.heapreplace(proj_heap, entry)
            for sim_score, _seq, proj_id, excerpt, owner in proj_heap:
                scored[proj_id] = {"excerpt": excerpt, "score": sim_score, "owner": owner}
        # Temporal channel (§18.6): a query naming a date/month/year reranks the
        # survivors by whether they OCCURRED then. Post-heap on ≤2·limit rows, so
        # the streaming top-k above is untouched; occurred_at is real because
        # capture stamps it (the occurred_at passthrough). "In May 2023" now
        # means May 2023 — before this, time in a query was just stopwords.
        # With now provided, also resolves relative expressions ("last week", "yesterday").
        win = _parse_time_window(query, now=now)
        tb = self._temporal_boost() if win else 0.0
        if tb > 0.0:
            lo, hi = win
            for eid, v in scored.items():
                if eid.startswith("session:"):
                    continue
                ev = self.store.get_event(eid) or {}
                occ = (ev.get("occurred_at") or "")[:10]
                if not occ:
                    continue
                v["score"] *= (1.0 + tb) if lo <= occ <= hi else max(0.0, 1.0 - tb * 0.5)
        out = [{"event_id": k, "excerpt": v["excerpt"], "score": v["score"]} for k, v in scored.items()]
        out.sort(key=lambda x: x["score"], reverse=True)
        return out[:limit]

    # -- read-and-answer (§18.4, I23) -------------------------------------

    def answer(self, query, *, read_budget=4000, purpose="*", principal=None, now=None) -> dict:
        principal = principal or self.active_principal
        q = self.query_understanding(query)
        t1 = self.search(query, limit=10, purpose=purpose, principal=principal, now=now)
        top = t1[0]["score"] if t1 else 0.0

        # Support gate (I8): ranking alone never says "no" — search() came back
        # non-empty on 30/30 unanswerable LongMemEval questions, which were then
        # answered at median confidence 0.600. Gate Tier 1 before the confident
        # path; see _support_gate and scripts/sweep_abstain.py.
        supported = self._support_gate(t1, q)
        if supported and self._confident(t1):
            self.store.log_retrieval(query, "*", top)
            return self._answer_from_beliefs(t1, tier=1)

        t2 = self.retrieve_raw(query, principal=principal, now=now)
        # Lexical grounding: a raw span only counts as support if it shares a query
        # token (guards against spurious vector hits → false answers).
        focus = set(q["tokens"])
        t2 = [c for c in t2 if any(w in (c["excerpt"] or "").lower() for w in focus)]

        if not t1 and not t2:
            self.store.log_retrieval(query, "*", 0.0)
            return {"answer": "", "abstain": True, "sources": [], "tier": 0, "confidence": 0.0,
                    "why": "no_support"}  # abstention (I8, B.3)

        if not supported:
            # Tier 1 refused. Drop it outright, or _read_and_extract's
            # `best or t1[0]["value"]` fallback re-admits the very belief the gate
            # just rejected. The raw tier is then the only support left, so it
            # answers to the same gate — its own filter (shares ANY query token)
            # is far too lenient to abstain on its own: 29/30 unanswerable
            # questions survive it.
            t1 = []
            if not self._support_gate(t2, q):
                self.store.log_retrieval(query, "*", 0.0)
                return {"answer": "", "abstain": True, "sources": [], "tier": 0, "confidence": 0.0,
                        "why": "low_support"}  # support exists but does not answer (I8, B.3)

        ans = self._read_and_extract(query, q, t1, t2, principal, read_budget)
        if ans.get("abstain") and not t1:
            self.store.log_retrieval(query, "*", 0.0)
            return {"answer": "", "abstain": True, "sources": [], "tier": 0, "confidence": 0.0,
                    "why": "no_support"}
        if top < self._miss_threshold and t2:
            self.store.log_miss(query, "*", top)
            for cand in t2[:2]:
                if not cand["event_id"].startswith("session:"):
                    self.store.enqueue_curation("extract", {"event_id": cand["event_id"]})
        return ans

    def _answer_from_beliefs(self, beliefs, *, tier):
        lead = beliefs[0]
        row = self.store.get_belief(lead["table"], lead["belief_id"]) or {}
        cal = self.calibrator.calibrate(row.get("confidence", lead["score"]),
                                        lead.get("source_type") or "session_transcript")
        text = "\n".join(self._render(b) for b in beliefs[:5])
        return {"answer": text, "abstain": False, "sources": [b["belief_id"] for b in beliefs[:5]],
                "tier": tier, "confidence": round(cal, 4), "confidence_summary": confidence_summary(row, cal),
                "derived": [b["belief_id"] for b in beliefs if b.get("source_type") == "inference"]}

    def _read_and_extract(self, query, q, t1, t2, principal, read_budget):
        focus = set(q["tokens"])
        best, best_score, budget = None, -1, read_budget
        for cand in t2:
            span = cand["excerpt"][: max(0, budget)]
            budget -= len(span)
            sc = sum(1 for w in focus if w in span.lower())
            if sc > best_score:
                best, best_score = span, sc
            if budget <= 0:
                break
        promoted = self._promote_from_span(best, focus, principal) if best else []
        answer = self._focus_sentence(best or (t1[0]["value"] if t1 else ""), focus)
        conf = 0.5 if best else (t1[0]["score"] if t1 else 0.0)
        conf = self.calibrator.calibrate(conf, "session_transcript")
        return {"answer": answer, "abstain": not answer, "tier": 2 if best else 1,
                "sources": [c["event_id"] for c in t2[:3]] + [b["belief_id"] for b in t1[:2]],
                "confidence": round(conf, 4), "promoted": promoted}

    def _promote_from_span(self, span, focus, principal) -> List[str]:
        """Write beliefs back from a raw span (§16.7). Returns promoted belief ids."""
        from .extraction import entity_token
        from .serialize import belief_id as bid_fn
        promoted = []
        for m in re.finditer(r"([A-Z][\w'-]+)\s+is\s+(?:a|an)\s+([^.,;\n]+)", span):
            subj, val = m.group(1), m.group(2).strip()
            ent = entity_token(subj)
            key = {"entity_id": ent, "predicate_canonical": "occupation", "attribute": "occupation",
                   "qualifiers_hash": "", "qualifiers": {}, "entity_name": subj,
                   "owner": principal, "domain": "user"}
            self._append("asserted", {"kind": "fact", "key": key, "body": val[:200], "confidence": 0.6,
                                      "source_event": "read_and_answer", "source_type": "session_transcript"},
                         principal)
            promoted.append(bid_fn("fact", key, ["read_and_answer"]))
        return promoted

    # -- context assembly (§18.5) -----------------------------------------

    def _expand_session_window(self, session_id: str, principal: str,
                               existing_excerpts: set, limit: int = 60) -> List[dict]:
        """Observed turns of one session that context does not already carry.

        ONE query per session, capped IN SQL: `type='observed'` and `LIMIT` are
        the store's job. r2 asked for every event the session ever held, built a
        dict per row, and then dropped all but the first `limit` observed ones in
        Python — on a session with thousands of turns that is the whole session
        materialised to produce sixty excerpts, twice per get_context call.

        The cap bounds rows FETCHED, not rows returned: an excerpt already in
        context (or repeated verbatim within the session) is dropped after the
        fetch, so a repetitive session can yield fewer than `limit`. That is what
        a defensive bound is for — it bounds the work; the caller's remaining
        char budget bounds the output. Ordered by seq; 'excerpt' and 'date' keys.
        """
        expanded: List[dict] = []
        if limit is not None and limit <= 0:
            return expanded
        events = self.store.get_events_by_session(session_id, since_seq=0,
                                                  types=("observed",), limit=limit)
        for ev in events:
            if not access.can_read(access.DEFAULT_ACL, ev.get("owner"), principal):
                continue
            p = json.loads(ev["payload"]) if isinstance(ev["payload"], str) else (ev["payload"] or {})
            excerpt = (p.get("excerpt") or "").strip()
            if not excerpt or excerpt in existing_excerpts:
                continue
            date = (ev.get("occurred_at") or "")[:16]
            expanded.append({"excerpt": excerpt, "date": date, "event_id": ev["event_id"]})
            existing_excerpts.add(excerpt)
        return expanded

    def get_context(self, hint, *, token_budget=1500, include_directives=True, purpose="*",
                    principal=None, epistemic=None, now=None) -> str:
        principal = principal or self.active_principal
        parts: List[str] = []
        if include_directives:
            for d in self.store.query_beliefs("notes", "always_inject=1 AND status='active'", (), 20):
                if d.get("body"):
                    parts.append(f"[DIRECTIVE] {d['body']}")
        for c in self.store.get_open_contradictions(5):
            parts.append(f"[CONTRADICTION] {c.get('detail','') or c.get('belief_a','')}")
        for c in self.store.query_beliefs("facts", "criticality!='normal' AND status='active'", (), 5):
            if self._readable(c, principal, purpose, None):
                parts.append(f"[CRITICAL] {c.get('attribute','')}: {c['value']}")
        for b in self.search(hint, limit=10, purpose=purpose, principal=principal, now=now):
            ann = epistemic.annotate(b) if epistemic else ""
            parts.append(self._render(b) + (f"  ({ann})" if ann else ""))
        ctx = "\n".join(_dedupe(parts))
        max_chars = token_budget * 4

        # Fill remaining budget with raw evidence grouped BY SESSION and headed
        # by the session's date (~4 chars/token). Orphan excerpts strip the two
        # things a reader needs most: WHEN it was said (temporal reasoning is
        # impossible without it) and what else was said in the same conversation.
        # Excerpts are appended whole or truncated at a sentence/newline/word
        # boundary — never cut mid-word (§18.5).
        used_chars = len(ctx)
        if used_chars < max_chars:
            remaining_chars = max_chars - used_chars
            groups: List[dict] = []          # insertion order = relevance order
            by_sid: Dict[str, dict] = {}
            seen_excerpts = set()

            # Phase 1: Top-ranked excerpts from retrieve_raw
            for raw in self.retrieve_raw(hint, limit=20, principal=principal, now=now):
                excerpt = (raw.get("excerpt") or "").strip()
                eid = raw.get("event_id") or ""
                if not excerpt and not eid.startswith("session:"):
                    continue
                if eid.startswith("session:"):
                    sid, date = eid.split(":", 1)[1], ""
                else:
                    ev = self.store.get_event(eid) or {}
                    sid = ev.get("session_id") or "(no session)"
                    date = (ev.get("occurred_at") or "")[:16]
                g = by_sid.get(sid)
                if g is None:
                    g = by_sid[sid] = {"sid": sid, "date": date, "excerpts": []}
                    groups.append(g)
                elif date and not g["date"]:
                    g["date"] = date
                if excerpt:
                    g["excerpts"].append(excerpt)
                    seen_excerpts.add(excerpt)

            # Fill context with top-ranked excerpts. A session gets exactly ONE
            # header line, and `emitted_headers` is where that fact lives: phase 2
            # reuses this session's header verbatim rather than rebuilding one from
            # whatever timestamp the turn it happens to be expanding carries.
            emitted_headers: Dict[str, str] = {}
            for g in groups:
                if not g["excerpts"]:
                    continue
                header = "[SESSION %s%s]" % (g["sid"], " @ " + g["date"] if g["date"] else "")
                block_open = False
                for excerpt in g["excerpts"]:
                    need = (0 if block_open else len(header) + 1) + len(excerpt) + 1
                    if remaining_chars - need <= 0:
                        budget = remaining_chars - (0 if block_open else len(header) + 1) - 1
                        piece = _truncate_at_boundary(excerpt, budget) if budget > 0 else ""
                        if piece:
                            if not block_open:
                                parts.append(header)
                                emitted_headers[g["sid"]] = header
                                block_open = True
                            parts.append(piece)
                            remaining_chars -= len(piece) + 1
                        break
                    if not block_open:
                        parts.append(header)
                        emitted_headers[g["sid"]] = header
                        remaining_chars -= len(header) + 1
                        block_open = True
                    parts.append(excerpt)
                    remaining_chars -= len(excerpt) + 1
                if remaining_chars <= 0:
                    break
            ctx = "\n".join(_dedupe(parts))

            # Phase 2: session-window expansion (r2) — the rest of the turns from
            # the sessions phase 1 already surfaced, so an excerpt is read in the
            # conversation it belongs to. Bounded on both axes, because both are
            # unbounded in the data: a query can group into as many sessions as
            # retrieve_raw returned, and a session can hold thousands of turns.
            enable_session_window = self.cfg.get("context.session_window", True) if self.cfg else True
            max_sessions = _clamp_cfg(self.cfg, "context.session_window_max_sessions", 5, 1, 100)
            max_events = _clamp_cfg(self.cfg, "context.session_window_max_events", 60, 1, 1000)
            if enable_session_window and remaining_chars > 0 and by_sid:
                sessions_expanded = 0
                for g in groups:
                    if remaining_chars <= 0 or sessions_expanded >= max_sessions:
                        break
                    sid = g["sid"]
                    if sid == "(no session)":
                        continue
                    # One query, capped in SQL (see _expand_session_window).
                    expanded = self._expand_session_window(sid, principal, seen_excerpts,
                                                           limit=max_events)
                    if not expanded:
                        continue
                    sessions_expanded += 1
                    # ONE header per session, keyed by sid. r2 rebuilt the header
                    # per expanded TURN from that turn's own occurred_at and then
                    # tested `header not in ctx` — an exact-substring test against a
                    # snapshot this loop never refreshes. Two turns of one session
                    # recorded a minute apart render two different header strings,
                    # so the second sails past the test, and the final _dedupe only
                    # collapses byte-identical lines: the block comes out headed
                    # twice, with disagreeing timestamps. Reusing phase 1's exact
                    # header string (or minting one and remembering it) makes the
                    # check depend on sid alone, which is the thing that is actually
                    # unique. `date` still falls back to the first expanded turn for
                    # a group phase 1 never dated.
                    header = emitted_headers.get(sid)
                    header_present = header is not None
                    if header is None:
                        date = g["date"] or (expanded[0].get("date") or "")
                        header = "[SESSION %s%s]" % (sid, " @ " + date if date else "")
                    # Append the expanded excerpts that weren't in the top-ranked list
                    for exp in expanded:
                        if remaining_chars <= 0:
                            break
                        excerpt = exp["excerpt"]
                        if excerpt in g["excerpts"]:
                            continue  # already included in phase 1
                        if not header_present:
                            need = len(header) + 1 + len(excerpt) + 1
                            if remaining_chars - need <= 0:
                                budget = remaining_chars - len(header) - 1 - 1
                                piece = _truncate_at_boundary(excerpt, budget) if budget > 0 else ""
                                if piece:
                                    parts.append(header)
                                    emitted_headers[sid] = header
                                    parts.append(piece)
                                    remaining_chars -= len(header) + len(piece) + 2
                                    header_present = True
                                break
                            parts.append(header)
                            emitted_headers[sid] = header
                            parts.append(excerpt)
                            remaining_chars -= len(header) + len(excerpt) + 2
                            header_present = True
                        else:
                            # Header already emitted (phase 1 or the line above).
                            need = len(excerpt) + 1
                            if remaining_chars - need <= 0:
                                budget = remaining_chars - 1
                                piece = _truncate_at_boundary(excerpt, budget) if budget > 0 else ""
                                if piece:
                                    parts.append(piece)
                                    remaining_chars -= len(piece) + 1
                                break
                            parts.append(excerpt)
                            remaining_chars -= len(excerpt) + 1
                ctx = "\n".join(_dedupe(parts))

        # §u2: one consolidated line per graph-seeded entity — the profile a reader
        # would otherwise rebuild from the fact rows above. Strictly leftover
        # budget and capped at 3: raw evidence above (phase 1 + session windows)
        # is what carries turn-level recall, so a digest is only ever bought with
        # space nothing else claimed (§r1 priority rule: evidence first).
        used_chars = len(ctx)
        if used_chars < max_chars:
            for e in self._graph_seeds(self._tokens(hint))[:3]:
                for d in self.store.query_beliefs(
                        "notes", "note_type='belief' AND subject=? AND status='active'",
                        ("digest:%s" % e,), 1):
                    if not d.get("body") or not self._readable(d, principal, purpose, None):
                        continue
                    line = "[DIGEST] %s" % d["body"]
                    if len(ctx) + len(line) + 1 >= max_chars:
                        continue
                    parts.append(line)
                    ctx = "\n".join(_dedupe(parts))

        # §r6: the topic-relevant standing note neither delivery path could carry.
        # The unconditional block above takes the FIRST 20 always_inject rows in
        # store order, not relevance order (real stores reach ~110 active norm
        # notes within one LongMemEval haystack), and search()'s LIKE channel
        # covers the facts table only — a note reaches Tier 1 by exact FTS token
        # or not at all, so "I always prefer window seats" is invisible to the
        # query "what seat should I book". This adds back the rows the query's own
        # focus tokens select. Additive only, by construction: every row it can
        # emit is one the unconditional block would already have delivered under a
        # larger cap, it runs AFTER the raw fill so raw evidence keeps first claim
        # on the budget (r1), it spends only leftover chars, and it never drops or
        # reorders a line already assembled.
        if include_directives and len(ctx) < max_chars:
            # Same focus tokens the abstention gate calls distinctive, matched as
            # substrings the way search()'s structured channel matches facts —
            # that is what lets "seat" reach a body that says "seats".
            focus = [t for t in self._tokens(hint) if len(t) > 3 and t not in _GENERIC]
            remaining_chars = max_chars - len(ctx)
            # Bodies already on a line of their own. An epistemic annotation is
            # appended to the [NOTE] render, so compare by prefix, not equality.
            emitted = [p.split(" ", 1)[1] for p in parts
                       if p.startswith("[DIRECTIVE] ") or p.startswith("[NOTE] ")]
            added = 0
            for d in (self.store.query_beliefs(
                        "notes", "always_inject=1 AND status='active'", (), 200) if focus else []):
                if added >= _TOPIC_NOTE_CAP:
                    break
                body = (d.get("body") or "").strip()
                if not body or not self._readable(d, principal, purpose, None):
                    continue
                if any(e.startswith(body) for e in emitted):
                    continue
                low = body.lower()
                if not any(t in low for t in focus):
                    continue
                line = "[DIRECTIVE] %s" % body
                if remaining_chars - len(line) - 1 <= 0:
                    break
                parts.append(line)
                emitted.append(body)
                remaining_chars -= len(line) + 1
                added += 1
            if added:
                ctx = "\n".join(_dedupe(parts))

        return ctx if len(ctx) <= max_chars else ctx[:max_chars] + "\n… (truncated)"

    def get_directives(self) -> str:
        ds = self.store.query_beliefs("notes", "always_inject=1 AND status='active'", (), 50)
        if not ds:
            return ""
        return "\n".join(["=== CHRONICLE DIRECTIVES ==="] + [f"- {d['body']}" for d in ds if d.get("body")])

    def static_block(self, principal: str) -> str:
        lines = []
        d = self.get_directives()
        if d:
            lines.append(d)
        crit = [c for c in self.store.query_beliefs("facts", "criticality='critical' AND status='active'", (), 5)
                if self._readable(c, principal, "*", None)]
        if crit:
            lines.append("=== CRITICAL ===")
            lines += [f"- {c.get('attribute','')}: {c['value']}" for c in crit]
        con = self.store.get_open_contradictions(5)
        if con:
            lines.append("=== OPEN CONTRADICTIONS ===")
            lines += [f"- {c.get('detail','')}" for c in con]
        # Standing user profile (§18.7): the durable facts an agent should never
        # have to retrieve — one line per attribute, latest active value (updates
        # supersede, so active IS latest), highest-confidence first. Costs a few
        # hundred chars; saves a retrieval round-trip on the most common asks.
        prof, seen = [], set()
        rows = [r for r in self.store.query_beliefs(
                    "facts", "entity_id='user' AND status='active'", (), 60)
                if self._readable(r, principal, "*", None)]
        for r in sorted(rows, key=lambda x: -(x.get("confidence") or 0)):
            attr = r.get("attribute") or ""
            if attr and attr not in seen and r.get("value"):
                seen.add(attr)
                prof.append(f"- {attr}: {r['value']}")
            if len(prof) >= 15:
                break
        if prof:
            lines.append("=== USER PROFILE ===")
            lines += prof
        return "\n".join(lines)

    # -- structured lookups (§18.3) ---------------------------------------

    def ask_about(self, entity_id, *, principal=None):
        principal = principal or self.active_principal
        out = []
        # §u2: the consolidation digest leads — it answers "what do we know about
        # this entity" in one line. The per-fact rows still follow verbatim; the
        # digest summarizes them, it never stands in for them.
        for d in self.store.query_beliefs(
                "notes", "note_type='belief' AND subject=? AND status='active'",
                ("digest:%s" % entity_id,), 1):
            if self._readable(d, principal, "*", None):
                out.append({"belief_id": d["belief_id"], "kind": "digest",
                            "digest_line": d.get("body", ""), "confidence": d.get("confidence")})
        rows = self.store.query_beliefs("facts", "entity_id=? AND status='active'", (entity_id,), 50)
        out.extend([self._render_fact(r) for r in rows if self._readable(r, principal, "*", None)])
        return out

    def around(self, entity_id, depth=1, *, principal=None):
        principal = principal or self.active_principal
        seen, frontier, out = {entity_id}, [entity_id], []
        for _ in range(depth):
            nxt = []
            for e in frontier:
                for r in self.store.query_beliefs("relationships",
                                                  "(source_id=? OR target_id=?) AND status='active'",
                                                  (e, e), 50):
                    if not self._readable(r, principal, "*", None):
                        continue
                    out.append({"source": r["source_id"], "predicate": r["predicate"], "target": r["target_id"]})
                    for nb in (r["source_id"], r["target_id"]):
                        if nb not in seen:
                            seen.add(nb)
                            nxt.append(nb)
            frontier = nxt
        return out

    def timeline(self, *, principal=None, limit=50):
        principal = principal or self.active_principal
        rows = self.store.query_beliefs("episodes", "status='active'", (), limit, order="occurred_at DESC")
        return [{"title": r["title"], "occurred_at": r["occurred_at"], "summary": r.get("summary")}
                for r in rows if self._readable(r, principal, "*", None)]

    def history(self, belief_id):
        chain, cur, guard = [], belief_id, 0
        while cur and guard < 100:
            found = self.store.find_belief(cur)
            if not found:
                break
            row = found[1]
            chain.append({"belief_id": cur, "value": row.get("value") or row.get("body"),
                          "status": row.get("status"), "valid_from": row.get("valid_from"),
                          "valid_until": row.get("valid_until")})
            cur = row.get("superseded_by")
            guard += 1
        return chain

    def as_of(self, world=None, knowledge=None) -> List[dict]:
        """Bitemporal query (§7.4): as-known-at `knowledge`, as-true-at `world`.

        Uses iter_events_since for memory-safe streaming (no 100k cap)."""
        stream = self.store.iter_events_since(0) if not knowledge else self.store.get_events_as_of(knowledge)
        facts = {}
        for ev in stream:
            if ev["type"] != "asserted":
                continue
            p = json.loads(ev["payload"]) if isinstance(ev["payload"], str) else ev["payload"]
            if p.get("kind") != "fact":
                continue
            k = p["key"]
            facts[(k.get("entity_id"), k.get("predicate_canonical"))] = {
                "value": p.get("body"), "valid_from": p.get("valid_from") or ev["occurred_at"]}
        out = []
        for (ent, pred), v in facts.items():
            if world and v["valid_from"] and v["valid_from"] > world:
                continue
            out.append({"entity_id": ent, "predicate": pred, "value": v["value"]})
        return out

    def changes_since(self, ts: str) -> List[dict]:
        rows = self.store.query_beliefs("facts", "created_at > ?", (ts,), 100, order="created_at")
        return [{"belief_id": r["belief_id"], "value": r["value"], "status": r["status"]} for r in rows]

    # -- helpers -----------------------------------------------------------

    def cfg_overfetch(self):
        return self.cfg.get("retrieval.overfetch", 4) if self.cfg else 4

    def _support_gate(self, items, q) -> bool:
        """Does `items` actually support answering `q`? (I8, §18.4)

        Pluggable via retrieval.abstain_gate — "score" (top fused score),
        "overlap" (shared content tokens), "focus" (coverage of the query's
        distinctive tokens). Applied to Tier 1, and to Tier 2 when Tier 1 was
        refused. Empty support is never support.

        "score" is the odd one: Tier-1 scores are RRF (≈ w/(k+rank), bounded near
        0.021) while Tier-2 scores carry a raw cosine term, so one threshold does
        not mean the same thing in both tiers — which is why the sweep caps its
        score grid at 0.03 rather than letting it exploit that.
        """
        view = [(_support_text(it), it.get("score") or 0.0) for it in items]
        if not view:
            return False
        if self._abstain_gate == "score":
            return view[0][1] >= self._score_threshold
        if self._abstain_gate == "overlap":
            qt = set(t for t in q["tokens"] if len(t) > 3)
            return any(len(qt & _content_tokens(txt)) >= self._overlap_min_tokens
                       for txt, _ in view[:3])
        qt = set(t for t in q["tokens"] if len(t) > 3 and t not in _GENERIC)
        if not qt:
            return True  # nothing distinctive to cover → nothing to fail on
        seen = set()
        for txt, _ in view[:5]:
            seen |= _content_tokens(txt)
        return len(qt & seen) / float(len(qt)) >= self._focus_coverage

    def _confident(self, t1):
        # RRF scores are small (≈ w/(k+rank)); scale the configured gate accordingly.
        return bool(t1) and t1[0]["score"] >= (self._fts_w + self._vec_w) / (self._rrf_k + 1) * 0.9

    def _vector_beliefs(self, query_emb, limit):
        rows = self.store.iter_memory_vectors()
        sims = batch_cosine(query_emb, [v["embedding"] for v in rows])
        scored = [(rows[i]["belief_id"], rows[i]["kind"], sims[i])
                  for i in range(len(rows)) if sims[i] > 0.1]
        scored.sort(key=lambda x: x[2], reverse=True)
        return scored[:limit]

    def _readable(self, row, principal, purpose, domain) -> bool:
        if row.get("status") not in ("active", "draft", None):
            return False
        if not access.can_read(row.get("read_acl"), row.get("owner"), principal):
            return False
        if domain and row.get("domain") and row["domain"] != domain:
            return False
        ps = row.get("purpose_scope")
        if ps and purpose and purpose != "*":
            try:
                scopes = json.loads(ps)
                if "*" not in scopes and purpose not in scopes:
                    return False
            except Exception:
                pass
        if row.get("info_label") == "secret" and purpose != "secret":
            return False
        return True

    def _render(self, b):
        if b["kind"] == "fact":
            tag = "DERIVED" if b.get("source_type") == "inference" else "FACT"
            return f"[{tag}] {b.get('attribute') or ''}: {b.get('value')} (conf {round(b.get('confidence') or 0, 2)})"
        if b["kind"] == "note":
            return f"[NOTE] {b.get('value')}"
        if b["kind"] == "episode":
            return f"[EPISODE] {b.get('value')}"
        return f"[{b['kind'].upper()}] {b.get('value')}"

    def _render_fact(self, r):
        return {"belief_id": r["belief_id"], "attribute": r["attribute"], "value": r["value"],
                "confidence": r["confidence"], "status": r["status"],
                "derived": json.loads(r.get("provenance") or "{}").get("source_type") == "inference"}

    def _focus_sentence(self, text, focus):
        if not text:
            return ""
        for sent in re.split(r"(?<=[.!?])\s+", text):
            if any(w in sent.lower() for w in focus):
                return sent.strip()
        return text.split("\n")[0][:200].strip()

    def _append(self, type_, payload, principal):
        from .serialize import event_id
        now = now_iso()
        eid = event_id(type_, payload, [], "curator", now)
        self.store.append_event({"event_id": eid, "type": type_, "payload": payload, "parents": [],
                                 "actor": "curator", "owner": principal, "trust_level": 2,
                                 "session_id": None, "branch_id": None, "occurred_at": now,
                                 "recorded_at": now, "prev_head": self.store.get_head_event_id(), "sig": None})


def _clamp(v, lo=0.0, hi=1.0):
    try:
        return max(lo, min(hi, float(v)))
    except (TypeError, ValueError):
        return lo


def _content_tokens(text):
    return set(w for w in re.findall(r"[A-Za-z0-9']+", (text or "").lower())
               if len(w) > 3 and w not in _STOP)


def _support_text(item):
    """The text a support item is judged on: a raw span's excerpt, or a belief's
    attribute + value (what _render would show a reader)."""
    if item.get("excerpt") is not None:
        return item["excerpt"]
    return "%s %s" % (item.get("attribute") or "", item.get("value") or "")


def _table_of_kind(kind):
    return KIND_TABLE.get(kind, "facts")


def _kind_of_table(table):
    rev = {"facts": "fact", "episodes": "episode", "notes": "note", "refs": "reference",
           "relationships": "relationship", "procedures": "procedure", "entities": "entity"}
    return rev.get(table, "fact")


def _truncate_at_boundary(text, max_len):
    """Truncate `text` to at most max_len chars without cutting mid-word: prefer
    the last sentence end, else the last newline, else the last space inside
    the window. Returns "" if none of those exist (nothing fits cleanly)."""
    window = text[:max_len]
    cut = max(window.rfind(". "), window.rfind("! "), window.rfind("? "), window.rfind("\n"))
    if cut == -1:
        cut = window.rfind(" ")
    return window[:cut + 1].rstrip() if cut != -1 else ""


def _dedupe(parts):
    seen, out = set(), []
    for p in parts:
        if p not in seen:
            seen.add(p)
            out.append(p)
    return out
