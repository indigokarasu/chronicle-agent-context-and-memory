"""
Chronicle — Host-model piggyback plumbing (Ladder 9, task H1).

Premise: the host agent ALREADY runs an LLM. Chronicle does not own one and must
never depend on one (I18) — but when a host model is in the loop anyway, the
enrichment work Chronicle would otherwise do heuristically can ride along on a
turn the host is paying for regardless. This module is the plumbing for that
ride: a bounded registry of pending enrichment requests, a ≤400-char renderer,
a strict parser/validator for the host's fenced-JSON reply, and an applier that
feeds validated results into the SAME write paths the heuristic uses.

DEFAULT OFF. `host_model.piggyback` is False in DEFAULTS and every entry point
here is only reached from a call site that checks it first. With defaults in
place nothing in this module runs, nothing is written, and the heuristic path is
byte-for-byte what it was before H1 landed (tests/test_host_model.py proves it
by dumping the whole store and diffing).

Three request kinds (§H1):
  extract_facts — "pull durable facts out of this turn"
  doc2query     — "what questions does this item answer" (E2's generation slot)
  rerank        — "reorder these candidates best-first" (E3's reranker slot)

§H2 drains all three. Each validated result now reaches a real consumer, and
each still lands in the `host_model_results` holding table on the way past, so
"are host replies well-formed, and how often?" stays answerable from SQL:

  extract_facts — capture.append("asserted", …), unchanged from H1.
  doc2query     — the item's proxy question set, merged with the Tier-1
                  templates under doc2query.MERGE_RULE and written through the
                  reducer's own delete-then-write path (Reducer.store_proxies).
                  The host set is persisted in host_model_proxies so it survives
                  the next regeneration.
  rerank        — bounded, expiring query->evidence hints in rerank_hints. A
                  rerank reply arrives a TURN LATE and therefore cannot reorder
                  the query that produced it; what it can do is inform the next
                  similar query, which is how retrieval consumes it.

Failure policy, everywhere: drop silently. A malformed, absent, oversized or
schema-violating reply expires the request and changes nothing else. The host is
untrusted input; a bad reply must cost exactly one wasted request slot.
"""

from __future__ import annotations

import json
import logging
import re
import uuid

from . import access
from .extraction import canonical_predicate, entity_token
from .serialize import qualifiers_hash
from .store import _iso_in, now_iso

logger = logging.getLogger("chronicle.hostmodel")

# The three enrichment kinds Chronicle can ask a host model for (§H1a).
REQUEST_KINDS = ("extract_facts", "doc2query", "rerank")

# Marker written into a belief's provenance JSON as `source` for anything that
# came back from the host model, so host-derived beliefs are separable from
# heuristic ones forever after (§H1c). Heuristic writes carry NO `source` key at
# all — that absence is what keeps the disabled path byte-identical.
PROVENANCE_SOURCE = "host_model"

# Recorded as extractor_version on host-derived facts. Distinct from
# "extractor-v1" (heuristic) and "extractor-v2-llm" (LLMExtractor) so a replay,
# an audit, or a re-extraction sweep can tell the three apart.
EXTRACTOR_VERSION = "host-model-v1"

# ---------------------------------------------------------------------------
# Bounds. Every one of these is a hard ceiling, not a suggestion: the reply side
# parses untrusted host output, and the request side is spending someone else's
# prompt budget.
# ---------------------------------------------------------------------------
# Queue cap: at most this many PENDING requests exist at once. A 33rd enqueue
# expires the OLDEST pending request rather than growing the queue or refusing
# the new work — enrichment is a best-effort side channel, and stale requests
# (whose source turn scrolled out of the host's context ages ago) are worth less
# than fresh ones. Configurable via host_model.max_pending, clamped [1, 256].
MAX_PENDING = 32
# A rendered request is glued into someone else's prompt. 400 chars is the spec
# ceiling and is enforced as a hard clamp on the returned string, not a target.
MAX_REQUEST_CHARS = 400
# The fenced JSON block itself may not exceed this. A host that dumps a 40KB
# "result" is malfunctioning, and parsing it would be the expensive way to find
# that out. Configurable via host_model.max_reply_chars, clamped [200, 20000].
MAX_REPLY_CHARS = 4000
# Only the head of a reply is scanned for a fence at all, so an enormous
# assistant turn cannot turn fence-detection into the turn's dominant cost.
MAX_SCAN_CHARS = 200000
# Per-kind result bounds (counts and per-field lengths) — see _validate_*.
MAX_FACTS = 8
MAX_QUESTIONS = 4
MAX_RERANK = 50
MAX_SUBJECT_CHARS = 120
MAX_ATTRIBUTE_CHARS = 60
MAX_VALUE_CHARS = 200
MAX_QUESTION_CHARS = 160

# §H2 rerank-hint bounds. Every one is a ceiling the config can only tighten.
# max_entries is the whole table's row cap (oldest-first eviction, enforced in
# MemoryStore.add_rerank_hints); ttl_days is the hard expiry stamped on each
# row; max_per_query bounds how many beliefs ONE verdict may hint at, so a
# 50-candidate rerank cannot spend the whole table on a single query.
RERANK_HINT_MAX_ENTRIES = 200
RERANK_HINT_TTL_DAYS = 30
RERANK_HINT_MAX_PER_QUERY = 8

_STATUSES = ("pending", "answered", "expired")

# ```json { ... } ``` — the ONLY accepted shape (§H1b). Non-greedy body with a
# required closing fence, so a nested object still matches (the inner `}`
# candidates fail the trailing `\s*```) while an unterminated fence does not.
_FENCE = re.compile(r"```json\s*(\{.*?\})\s*```", re.DOTALL | re.IGNORECASE)

# A host-proposed attribute must look like a predicate, not a sentence or a
# composite key. `.` and `attr_` are separately rejected by
# access.validate_subject_grounding at write time; this is the cheaper first cut.
_ATTRIBUTE_RX = re.compile(r"^[A-Za-z][A-Za-z0-9_ -]*$")

# Exact top-level key sets. Anything extra, missing, or misspelled is a reject —
# "reject anything extra" is the whole point of validating a model's output.
_TOP_KEYS = {
    "extract_facts": frozenset(("request_id", "kind", "facts")),
    "doc2query": frozenset(("request_id", "kind", "questions")),
    "rerank": frozenset(("request_id", "kind", "order")),
}
_FACT_KEYS = frozenset(("subject", "attribute", "value"))

_USER_SUBJECTS = ("user", "the user", "i", "me", "myself")


def _clamp(value, low, high, default):
    try:
        n = int(value)
    except (TypeError, ValueError):
        return default
    return max(low, min(high, n))


def _payload_of(request) -> dict:
    """A request row's payload as a dict, whatever shape it arrived in."""
    raw = request.get("payload") if isinstance(request, dict) else None
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, str) and raw:
        try:
            parsed = json.loads(raw)
        except ValueError:
            return {}
        return parsed if isinstance(parsed, dict) else {}
    return {}


# ---------------------------------------------------------------------------
# (a) The registry
# ---------------------------------------------------------------------------
class HostModelRegistry:
    """Bounded queue of enrichment requests Chronicle would like a host model to
    answer, plus the two tables behind it.

    Constructing one touches NOTHING — no SQL, no config read, no state. That is
    deliberate: ChronicleCore builds one unconditionally, so the constructor is
    on the default path and must stay inert. Every method that reaches SQLite is
    reached only from a caller that checked `enabled()` first (the sole
    exceptions are the read-only inspection helpers, which tests and a future
    provider listing use directly).
    """

    def __init__(self, store, cfg=None):
        self.store = store
        self.cfg = cfg

    # -- config --------------------------------------------------------------

    def enabled(self) -> bool:
        """host_model.piggyback. False by DEFAULT and on any config error."""
        if self.cfg is None:
            return False
        try:
            return bool(self.cfg.get("host_model.piggyback", False))
        except Exception:  # pragma: no cover - a broken cfg must not enable it
            return False

    def max_pending(self) -> int:
        raw = self.cfg.get("host_model.max_pending", MAX_PENDING) if self.cfg else MAX_PENDING
        return _clamp(raw, 1, 256, MAX_PENDING)

    def request_char_cap(self) -> int:
        """Never above MAX_REQUEST_CHARS — config can only make requests SMALLER."""
        raw = self.cfg.get("host_model.max_request_chars", MAX_REQUEST_CHARS) if self.cfg \
            else MAX_REQUEST_CHARS
        return _clamp(raw, 80, MAX_REQUEST_CHARS, MAX_REQUEST_CHARS)

    def reply_char_cap(self) -> int:
        raw = self.cfg.get("host_model.max_reply_chars", MAX_REPLY_CHARS) if self.cfg \
            else MAX_REPLY_CHARS
        return _clamp(raw, 200, 20000, MAX_REPLY_CHARS)

    # -- queue ---------------------------------------------------------------

    def enqueue(self, kind: str, payload: dict) -> str:
        """Register one unit of enrichment work; returns its request id.

        Over-cap enqueues expire the oldest PENDING request in the same
        transaction, so the queue length is an invariant rather than a hope.
        """
        if kind not in REQUEST_KINDS:
            raise ValueError("unknown host-model request kind: %r" % (kind,))
        rid = uuid.uuid4().hex[:12]
        now = now_iso()
        body = json.dumps(payload or {}, default=str, sort_keys=True)
        with self.store.transaction() as conn:
            conn.execute("INSERT INTO host_model_requests"
                         "(request_id, kind, payload, created_at, status, attached_at, resolved_at) "
                         "VALUES(?,?,?,?, 'pending', NULL, NULL)", (rid, kind, body, now))
            self._expire_overflow(conn, now)
        return rid

    def _expire_overflow(self, conn, now: str):
        """Oldest-expire down to the cap. Ordered by created_at then rowid, so
        requests enqueued inside the same millisecond still expire in insertion
        order instead of arbitrarily."""
        cap = self.max_pending()
        over = conn.execute("SELECT COUNT(*) FROM host_model_requests "
                            "WHERE status='pending'").fetchone()[0] - cap
        if over <= 0:
            return
        conn.execute(
            "UPDATE host_model_requests SET status='expired', resolved_at=? "
            "WHERE request_id IN (SELECT request_id FROM host_model_requests "
            "                     WHERE status='pending' "
            "                     ORDER BY created_at ASC, rowid ASC LIMIT ?)", (now, over))
        logger.debug("host-model queue over cap %d: expired %d oldest request(s)", cap, over)

    def get(self, request_id: str):
        if not request_id:
            return None
        row = self.store._conn().execute(
            "SELECT * FROM host_model_requests WHERE request_id=?", (request_id,)).fetchone()
        return dict(row) if row else None

    def next_pending(self):
        """The oldest pending request that has NOT yet been attached to a turn."""
        row = self.store._conn().execute(
            "SELECT * FROM host_model_requests WHERE status='pending' AND attached_at IS NULL "
            "ORDER BY created_at ASC, rowid ASC LIMIT 1").fetchone()
        return dict(row) if row else None

    def attached_request(self):
        """The one request currently in flight (attached, not yet resolved).

        Kept in the DB rather than on the provider instance on purpose: the
        provider is per-session and can be rebuilt between the attach turn and
        the reply turn, and an in-memory handle would silently lose the pairing.
        """
        row = self.store._conn().execute(
            "SELECT * FROM host_model_requests WHERE status='pending' AND attached_at IS NOT NULL "
            "ORDER BY attached_at DESC, rowid DESC LIMIT 1").fetchone()
        return dict(row) if row else None

    def list_requests(self, status=None, limit: int = 100):
        sql = "SELECT * FROM host_model_requests"
        params: list = []
        if status:
            sql += " WHERE status=?"
            params.append(status)
        sql += " ORDER BY created_at ASC, rowid ASC LIMIT ?"
        params.append(max(1, int(limit)))
        return [dict(r) for r in self.store._conn().execute(sql, tuple(params)).fetchall()]

    def counts(self) -> dict:
        out = {s: 0 for s in _STATUSES}
        for row in self.store._conn().execute(
                "SELECT status, COUNT(*) AS n FROM host_model_requests GROUP BY status").fetchall():
            out[row["status"]] = row["n"]
        return out

    def mark_attached(self, request_id: str):
        with self.store.transaction() as conn:
            conn.execute("UPDATE host_model_requests SET attached_at=? "
                         "WHERE request_id=? AND status='pending'", (now_iso(), request_id))

    def mark_answered(self, request_id: str):
        self._resolve(request_id, "answered")

    def mark_expired(self, request_id: str):
        self._resolve(request_id, "expired")

    def _resolve(self, request_id: str, status: str):
        if status not in _STATUSES:  # pragma: no cover - internal callers only
            raise ValueError(status)
        with self.store.transaction() as conn:
            conn.execute("UPDATE host_model_requests SET status=?, resolved_at=? "
                         "WHERE request_id=? AND status='pending'",
                         (status, now_iso(), request_id))

    # -- holding table for the not-yet-integrated kinds ----------------------

    def record_result(self, request_id: str, kind: str, result: dict):
        """Park a VALIDATED doc2query / rerank result.

        §H2 gave both kinds a real consumer (see _apply_doc2query /
        _apply_rerank), but the parking stayed: it is the only place that
        records what the host actually SAID, as opposed to what Chronicle did
        about it. Keeping both makes the piggyback measurable — reply
        well-formedness, per-kind volume, and drift between "answered" and
        "actually applied" (a doc2query answer for a belief that has since been
        retracted parks here and writes nothing) are all readable from SQL
        without instrumenting the write paths.
        """
        with self.store.transaction() as conn:
            conn.execute("INSERT OR REPLACE INTO host_model_results"
                         "(request_id, kind, result, created_at) VALUES(?,?,?,?)",
                         (request_id, kind, json.dumps(result, default=str, sort_keys=True),
                          now_iso()))

    def results(self, kind=None, limit: int = 100):
        sql = "SELECT * FROM host_model_results"
        params: list = []
        if kind:
            sql += " WHERE kind=?"
            params.append(kind)
        sql += " ORDER BY created_at ASC, rowid ASC LIMIT ?"
        params.append(max(1, int(limit)))
        return [dict(r) for r in self.store._conn().execute(sql, tuple(params)).fetchall()]


# ---------------------------------------------------------------------------
# (b) Rendering — the request side of the hook
# ---------------------------------------------------------------------------
def render_request(request, limit: int = MAX_REQUEST_CHARS) -> str:
    """Render ONE request as a compact instruction, hard-clamped to `limit`.

    The clamp is applied to the finished string, after the variable part has
    already been budgeted against the fixed part, so the ceiling holds even for
    a payload that is pure garbage. No literal triple-backtick appears in the
    rendering: the instruction describes the fenced block instead of showing
    one, so Chronicle's own request text can never be mistaken for a reply.
    """
    if not request:
        return ""
    limit = _clamp(limit, 80, MAX_REQUEST_CHARS, MAX_REQUEST_CHARS)
    kind = request.get("kind")
    rid = request.get("request_id") or ""
    payload = _payload_of(request)

    if kind == "extract_facts":
        shape = ('{"request_id":"%s","kind":"extract_facts",'
                 '"facts":[{"subject":"","attribute":"","value":""}]}' % rid)
        head = "[chronicle] Reply with a json fenced block %s - durable facts in: " % shape
        variable = str(payload.get("text") or "")
    elif kind == "doc2query":
        shape = '{"request_id":"%s","kind":"doc2query","questions":[""]}' % rid
        head = "[chronicle] Reply with a json fenced block %s - <=%d questions answered by: " % (
            shape, MAX_QUESTIONS)
        variable = str(payload.get("text") or "")
    elif kind == "rerank":
        shape = '{"request_id":"%s","kind":"rerank","order":[0]}' % rid
        head = "[chronicle] Reply with a json fenced block %s - best-first indices for %s: " % (
            shape, str(payload.get("query") or "")[:60])
        variable = " | ".join("%d:%s" % (i, str(c)[:60]) for i, c
                              in enumerate((payload.get("candidates") or [])[:MAX_RERANK]))
    else:  # pragma: no cover - enqueue() rejects unknown kinds
        return ""

    room = limit - len(head)
    if room <= 0:
        return head[:limit]
    return (head + variable[:room])[:limit]


# ---------------------------------------------------------------------------
# (b) Parsing + strict schema validation — the reply side of the hook
# ---------------------------------------------------------------------------
def parse_reply(text, request, max_reply_chars: int = MAX_REPLY_CHARS):
    """Extract and validate the host's answer to `request`.

    Returns the normalized result dict, or None for EVERY failure mode — no
    fence, malformed JSON, non-object, oversized block, wrong request id, wrong
    kind, extra keys, wrong types, out-of-range counts. Callers treat None as
    "expire the request and carry on"; nothing here ever raises.

    FIRST FENCE WINS. `_FENCE.search` takes the earliest ```json block in the
    scanned head and never looks further: a reply containing two fenced blocks
    is judged on the first one alone, so a second, well-formed block cannot
    rescue a malformed first (the whole reply is dropped), and cannot override
    a valid first either. That is deliberate — scanning on would let a host
    smuggle a second answer past the one it appeared to give — but it does mean
    a host that "thinks out loud" in an example fence before its real answer is
    read as answering with the example. The request_id check is what contains
    the damage: a stray fence almost never carries the live request id, so it
    is rejected as an answer to a different request rather than misapplied.
    """
    if not text or not request:
        return None
    kind = request.get("kind")
    if kind not in _TOP_KEYS:
        return None
    try:
        head = str(text)[:MAX_SCAN_CHARS]
        match = _FENCE.search(head)
        if match is None:
            return None
        block = match.group(1)
        if len(block) > max_reply_chars:
            return None                      # oversized: refuse to parse it at all
        obj = json.loads(block)
        if not isinstance(obj, dict):
            return None
        if frozenset(obj.keys()) != _TOP_KEYS[kind]:
            return None                      # missing OR extra top-level keys
        if obj.get("request_id") != request.get("request_id"):
            return None                      # answer to a different (or no) request
        if obj.get("kind") != kind:
            return None
        if kind == "extract_facts":
            return _validate_facts(obj)
        if kind == "doc2query":
            return _validate_questions(obj)
        return _validate_order(obj, request)
    except Exception as e:
        logger.debug("host-model reply dropped: %s", e)
        return None


def _is_int(v) -> bool:
    """bool is a subclass of int; an `order` of [true, false] is not an order."""
    return isinstance(v, int) and not isinstance(v, bool)


def _validate_facts(obj):
    facts = obj.get("facts")
    if not isinstance(facts, list) or not (1 <= len(facts) <= MAX_FACTS):
        return None
    out = []
    for item in facts:
        if not isinstance(item, dict) or frozenset(item.keys()) != _FACT_KEYS:
            return None
        subject, attribute, value = item["subject"], item["attribute"], item["value"]
        if not (isinstance(subject, str) and isinstance(attribute, str) and isinstance(value, str)):
            return None
        subject, attribute, value = subject.strip(), attribute.strip(), value.strip()
        if not (subject and attribute and value):
            return None
        if len(subject) > MAX_SUBJECT_CHARS or len(attribute) > MAX_ATTRIBUTE_CHARS \
                or len(value) > MAX_VALUE_CHARS:
            return None
        if not _ATTRIBUTE_RX.match(attribute):
            return None
        out.append({"subject": subject, "attribute": attribute, "value": value})
    return {"kind": "extract_facts", "facts": out}


def _validate_questions(obj):
    questions = obj.get("questions")
    if not isinstance(questions, list) or not (1 <= len(questions) <= MAX_QUESTIONS):
        return None
    out = []
    for q in questions:
        if not isinstance(q, str):
            return None
        q = q.strip()
        if not q or len(q) > MAX_QUESTION_CHARS:
            return None
        out.append(q)
    return {"kind": "doc2query", "questions": out}


def _validate_order(obj, request):
    order = obj.get("order")
    candidates = _payload_of(request).get("candidates")
    if not isinstance(candidates, list) or not candidates:
        return None                          # nothing to order against
    n = min(len(candidates), MAX_RERANK)
    if not isinstance(order, list) or not (1 <= len(order) <= n):
        return None
    seen = set()
    for i in order:
        if not _is_int(i) or not (0 <= i < n) or i in seen:
            return None                      # out of range, duplicated, or not an index
        seen.add(i)
    return {"kind": "rerank", "order": list(order)}


# ---------------------------------------------------------------------------
# (c) Applying validated results through the ordinary write paths
# ---------------------------------------------------------------------------
def apply_result(core, request, result, session_id: str = "", owner: str = "default") -> int:
    """Land a validated result. Returns how many durable writes it produced.

    extract_facts goes through `capture.append("asserted", …)` — the SAME call
    curation._emit_item makes for heuristic items, with the same actor, the same
    key shape, the same subject-grounding guard, the same reducer, the same
    embedding. The only difference is `provenance_source: host_model`, which the
    reducer folds into the belief's provenance JSON as `source`.

    doc2query and rerank (§H2) are parked in host_model_results FIRST and then
    drained. Parking first is deliberate: the drain can legitimately write
    nothing (an answer about a belief that no longer exists, a rerank whose
    request carried no candidate ids), and the record of what the host said must
    not depend on whether Chronicle could still use it. Both drains swallow
    their own failures — a side channel may not break the turn that carried it.
    """
    if not (core and request and result):
        return 0
    kind = result.get("kind")
    if kind == "extract_facts":
        return _apply_facts(core, request, result, session_id, owner)
    core.host_model.record_result(request.get("request_id"), kind, result)
    try:
        if kind == "doc2query":
            return _apply_doc2query(core, request, result)
        if kind == "rerank":
            return _apply_rerank(core, request, result, owner)
    except Exception as e:
        logger.debug("host-model %s drain skipped: %s", kind, e)
    return 0


# -- doc2query drain (§H2.1) -------------------------------------------------
def _apply_doc2query(core, request, result) -> int:
    """Write a host's questions as this item's doc2query proxies.

    Runs through Reducer.store_proxies — the exact call the Tier-1 template
    path makes — so the delete-before-regenerate rule (integration fix D) and
    the ≤MAX_PROXIES volume bound apply to host output by construction rather
    than by a parallel implementation that has to remember them.

    The TEMPLATE side of the merge is read back off the item's currently stored
    proxies, minus whatever a PREVIOUS host reply contributed to them. Reading
    the stored rows rather than re-deriving templates from the belief matters:
    the belief row does not carry the display-name/topic key the generators
    need, so re-deriving would quietly produce an empty template set and turn
    "augment" into "replace" for every second reply. Subtracting the prior host
    set is what keeps repeat replies from accreting — the merge always sees
    exactly (new host questions, templates).

    No embedder, or an unknown/retracted parent, writes nothing.
    """
    payload = _payload_of(request)
    belief_id = str(payload.get("belief_id") or "")
    questions = list(result.get("questions") or [])
    if not (belief_id and questions):
        return 0
    reducer = getattr(core, "reducer", None)
    if reducer is None or getattr(reducer, "embedder", None) is None:
        return 0

    kind = _proxy_kind(core, belief_id)
    if kind is None:
        return 0                              # parent gone: park only, write nothing

    prior_host = {q.strip().lower() for q in core.store.host_proxy_questions(belief_id)}
    templates = [r["question"] for r in core.store.query_proxy_rows(belief_id)
                 if str(r["question"] or "").strip().lower() not in prior_host]

    from .doc2query import merge_questions
    merged = merge_questions(questions, templates)
    core.store.set_host_proxy_questions(belief_id, questions, request.get("request_id") or "")
    return reducer.store_proxies(belief_id, kind, merged)


def _proxy_kind(core, belief_id):
    """The `kind` a proxy row for this parent must carry, or None if the parent
    no longer exists. A belief's own kind for beliefs; 'observed' for the raw
    excerpt tier, whose parents are events rather than beliefs.

    Resolved from the STORE, never from the request payload's declared `kind`.
    The payload is a description of the world one or more turns ago: a belief
    retracted or superseded between the request and the reply is gone from
    find_belief but still named in the payload, and trusting the declaration
    would write proxies keyed to a parent that no longer resolves — orphan rows
    scoring in every future search with nothing behind them. A live parent is
    the precondition, so the lookup has to be the source of truth."""
    found = core.store.find_belief(belief_id)
    if found:
        from .retrieval import _kind_of_table
        return _kind_of_table(found[0])
    return "observed" if core.store.get_event(belief_id) else None


# -- rerank drain (§H2.2) ----------------------------------------------------
def _apply_rerank(core, request, result, owner: str = "default") -> int:
    """Persist a host rerank verdict as query->evidence relevance hints.

    THE TIMING IS THE DESIGN CONSTRAINT (§H2.2). A reply lands one turn after
    the request, by which point the query that produced the candidate list has
    already been answered — so this cannot reorder its own query and must not
    pretend to. What survives is the judgement itself: "asked THIS, these
    beliefs were the relevant ones, in this order". Retrieval applies it when a
    similar query recurs (RetrievalEngine._hint_scores).

    Weighting is reciprocal rank in the host's order — 1.0, 0.5, 0.33, … — so
    the verdict's own confidence ordering is preserved and the tail is worth
    little. Candidates the host LEFT OUT get no row at all: an omission is not
    a judgement, and turning it into a penalty would let one late reply suppress
    evidence for every future similar query. Hints only ever add.

    Bounds, all enforced before this returns: at most max_per_query rows per
    verdict, a hard expires_at per row, and a whole-table cap with oldest-first
    eviction inside add_rerank_hints' transaction.

    `owner` (ladder-9 F4c) is `apply_result`'s own owner param -- the acting
    principal for the turn that carried this reply -- normalized through
    access.user_of() the same way RetrievalEngine._hint_scores normalizes the
    querying principal, so a hint is stored under, and only ever read back
    under, the OWNER a principal belongs to (not the bare agent-qualified
    principal string), matching how every other cross-owner isolation check
    in this codebase treats "owner".
    """
    payload = _payload_of(request)
    order = list(result.get("order") or [])
    ids = payload.get("candidate_ids")
    query_text = str(payload.get("query") or "")
    if not (order and isinstance(ids, list) and ids and query_text.strip()):
        return 0

    from .retrieval import hint_signature
    key, tokens = hint_signature(query_text)
    if not key:
        return 0                              # nothing distinctive to key on

    cfg = getattr(core, "cfg", None)
    per_query = _cfg_int(cfg, "host_model.rerank_hints.max_per_query",
                         RERANK_HINT_MAX_PER_QUERY, 1, MAX_RERANK)
    ttl_days = _cfg_int(cfg, "host_model.rerank_hints.ttl_days",
                        RERANK_HINT_TTL_DAYS, 1, 3650)
    max_entries = _cfg_int(cfg, "host_model.rerank_hints.max_entries",
                           RERANK_HINT_MAX_ENTRIES, 1, 10000)

    hints, seen = [], set()
    for position, idx in enumerate(order):
        if len(hints) >= per_query:
            break
        if not (0 <= idx < len(ids)):
            continue
        bid = str(ids[idx] or "")
        if not bid or bid in seen:
            continue
        seen.add(bid)
        hints.append((bid, 1.0 / (1.0 + position)))
    if not hints:
        return 0
    core.store.add_rerank_hints(key, query_text[:200], tokens, hints,
                                _iso_in(ttl_days * 86400.0), max_entries=max_entries,
                                owner=access.user_of(owner))
    return len(hints)


def _cfg_int(cfg, path, default, low, high) -> int:
    if cfg is None:
        return default
    try:
        return _clamp(cfg.get(path, default), low, high, default)
    except Exception:  # pragma: no cover - a broken cfg falls back to the ceiling
        return default


def _apply_facts(core, request, result, session_id: str, owner: str) -> int:
    payload = _payload_of(request)
    source_event = payload.get("source_event") or ""
    session_id = session_id or payload.get("session_id") or ""
    written = 0
    for fact in result.get("facts", []):
        subject = fact["subject"]
        canonical, _cardinality = canonical_predicate(fact["attribute"].replace("_", " "))
        if subject.lower() in _USER_SUBJECTS:
            entity_id, entity_name, source_type = "user", None, "user_direct"
        else:
            entity_id, entity_name, source_type = entity_token(subject), subject, "session_transcript"
        try:
            # Same invariant, same choke point, same "drop the item not the batch"
            # policy as curation._emit_item (§15.8).
            access.validate_subject_grounding(entity_id, canonical)
        except ValueError as e:
            logger.warning("chronicle: dropped host-model fact with bad subject grounding: %s", e)
            continue
        key = {"entity_id": entity_id, "predicate_canonical": canonical, "attribute": canonical,
               "qualifiers_hash": qualifiers_hash({}), "qualifiers": {},
               "owner": owner, "domain": _domain_for(source_type)}
        if entity_name:
            key["entity_name"] = entity_name
        body = {"kind": "fact", "key": key, "body": fact["value"],
                "domain": _domain_for(source_type),
                # No explicit confidence: the reducer falls back to
                # base_confidence(source_type), i.e. the operator's configured
                # confidence.base, rather than a number invented here.
                "source_event": source_event, "source_type": source_type, "status": "active",
                "extractor_version": EXTRACTOR_VERSION,
                "provenance_source": PROVENANCE_SOURCE}
        core.capture.append("asserted", body,
                            parents=[source_event] if source_event else None,
                            actor="curator", owner=owner,
                            session_id=session_id or None, trust_level=2)
        written += 1
    return written


def _domain_for(source_type: str) -> str:
    from .curation import domain_for
    return domain_for(source_type)
