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

import datetime as _dt
import functools
import hashlib
import heapq
import json
import logging
import math
import re
import unicodedata
from contextlib import contextmanager
from itertools import zip_longest
from time import monotonic as _time_monotonic

from . import access
from . import credentials as _cred
from . import speaker as _spk
from .config import DEFAULTS, check_abstain_gate
from . import embeddings as _embeddings
from .embeddings import (CONTEXT_BUDGET, batch_cosine, budget_chars, cosine,
                         estimate_tokens, pack, unpack, wrong_dim_indices)
from .federated import FederatedChannel
from .serialize import belief_id as compute_belief_id
from .store import KIND_TABLE, now_iso, word_tokens
from .substance import EVENT_PREDICATES as _EVENT_PREDICATES
from .trust import Calibrator, confidence_summary
from .vector_index import MAX_K as KNN_MAX_K
from .vector_index import VectorIndex

logger = logging.getLogger("chronicle.retrieval")


class _WrongDimWidth:
    """A stand-in for a blob whose LENGTH is the only thing anyone reads.

    `wrong_dim_indices` and `_note_wrong_dim_rows` ask a blob exactly two
    questions -- is it present, and how many bytes is it -- so the ID-ONLY
    complement query above can answer both from `length(embedding)` without
    ever loading the bytes. Allocating a real bytes object of that size to
    satisfy the type would re-introduce, in the DIAGNOSTIC, precisely the
    memory cost A5 removed from the scan."""

    __slots__ = ("_n",)

    def __init__(self, nbytes: int):
        self._n = int(nbytes)

    def __len__(self) -> int:
        return self._n

    def __bool__(self) -> bool:
        return self._n > 0


# A5: rows per page for every brute-force vector scan. This is THE bound: with
# a bounded top-k heap downstream, resident vector bytes during a query are
# `VECTOR_SCAN_PAGE * blob_width`, not `table_rows * blob_width`. At 1000 rows
# and production's 8192 B blobs that is ~8 MB per scan against the ~750 MB the
# materialising path paid at 108k rows. Raising it towards the row count walks
# the memory back to exactly that -- which is what
# tests/test_a5_streaming_candidates.py's "removing the bound" case asserts.
#
# If you came looking for `vector_index.bruteforce_ceiling` (config.py:114):
# it is declared and read by nothing — one of A12's ~70 dead keys. THIS is the
# bound on a brute-force scan, and it is a page size, not a row ceiling: a
# ceiling would have to either refuse to answer above it or silently truncate
# the corpus, and neither is a thing the read path may do.
VECTOR_SCAN_PAGE = 1000


def _tail_merged(pages, page_size):
    """Re-chunk a paged scan so no batch is short — unless the ENTIRE scan is
    one short batch, in which case it is passed through untouched.

    WHY THIS EXISTS (A5, measured — do not remove it as ceremony).
    `batch_cosine` is not shape-stable. It builds one `(n, d)` float32 matrix
    and hands `M @ q` to BLAS; on Accelerate (arm64, numpy 2.0.2) the gemv
    kernel — and with it the accumulation order inside each row's dot product
    — changes with the matrix shape. Scoring 4,000 unit vectors of d=768 one
    page at a time, against one 4,000-row call:

        page       1      2     16     32    100    128    256   1000
        differing  3220   3441   3441   3298   3285     25      0      0
        max |Δ|   2.2e-8 3.4e-8 3.4e-8 2.2e-8 2.2e-8 1.1e-8      0      0

    Two things follow, and the second is the one that bites:

    1. The crossover is a SHAPE threshold, not a row count — it moves with `d`
       (d=768 agrees from ~128 rows; d=128 needs ~1000; d=64 needs ~2000).
       Padding the matrix to a fixed minimum was tried and rejected on the
       numbers: it fixes d=768 and leaves d=96 wrong. The engine's real widths
       (768/1024/2048/3072) are all comfortably served by a 1000-row page —
       verified bit-identical to the single-matrix path for
       d ∈ {128,256,384,768,1024,2048,3072} × N ∈ {999,1000,1001,1500,2000,
       2049,3000,5001,12000} at page 1000: zero differing floats in all 63
       combinations. VECTOR_SCAN_PAGE must not be lowered towards the
       crossover without re-running that sweep.

    2. The LAST page of any scan is `rows % page` long — routinely a handful
       of rows, i.e. the one batch that is always under the crossover no
       matter how large the page is. That is what this function removes: the
       short tail is folded into its predecessor, so every batch handed to
       BLAS is at least `page_size` rows, or the scan is a single call that is
       byte-for-byte the one the materialising path made.

    Nothing downstream resolves 3e-8 (the floors are 0.1/0.15 and RRF is
    rank-based), and `tests/test_a5_streaming_candidates.py` shows the ranking
    holds even at page=1 where the scores do drift. But "ranking-identical" is
    A5's contract, so the contract is met exactly rather than approximately.

    Memory cost: at most two pages resident instead of one.
    """
    prev = None
    for batch in pages:
        if prev is None:
            prev = batch
        elif len(batch) < page_size:
            prev = prev + batch          # a short tail joins its predecessor
        else:
            yield prev
            prev = batch
    if prev:
        yield prev

_STOP = {"the", "a", "an", "is", "are", "what", "who", "where", "when", "how", "do", "does",
         "did", "my", "your", "of", "to", "in", "on", "for", "and", "or", "i", "me", "s",
         "was", "were", "it", "that", "this", "with", "about", "tell", "show", "name"}

# Message boundary inside one excerpt: the start of the next "role: …" line.
# THIRD copy of capture._MSG_START (embeddings._EMBED_MSG_START is the second),
# and it exists for the same reason that one does: retrieval sits BELOW capture
# in the layering and must not import upward. Kept byte-identical to the
# original by test_pref_pack.py::test_msg_start_matches_capture, which fails if
# the three ever drift apart.
_MSG_START = re.compile(r"\n(?=[^\s:][^:\n]{0,32}: )")

_MONTHS = {m: i + 1 for i, m in enumerate(
    ["january", "february", "march", "april", "may", "june", "july",
     "august", "september", "october", "november", "december"])}
_MONTH_RX = "(" + "|".join(m[:3] + r"[a-z]*" for m in _MONTHS) + ")"
_RX_ISO = re.compile(r"\b(20\d{2})[-/](\d{1,2})[-/](\d{1,2})\b")
_RX_MDY = re.compile(r"\b" + _MONTH_RX + r"\.?\s+(\d{1,2})(?:st|nd|rd|th)?,?\s+(20\d{2})\b", re.IGNORECASE)
_RX_DMY = re.compile(r"\b(\d{1,2})(?:st|nd|rd|th)?\s+(?:of\s+)?" + _MONTH_RX + r"\.?,?\s+(20\d{2})\b", re.IGNORECASE)
_RX_MY = re.compile(r"\b" + _MONTH_RX + r"\.?,?\s+(20\d{2})\b", re.IGNORECASE)
_RX_Y = re.compile(r"\b(?:in|during|of)\s+(20\d{2})\b", re.IGNORECASE)
# Relative time expressions: yesterday, today, last/this week/month/year, N days/weeks/months ago
# "N" accepts either digits ("3 weeks ago") or word-form number names ("three
# weeks ago", "a month ago", "an hour ago" is out of scope but "a"/"an" -> 1
# reads naturally for "a week ago" / "a month ago").
_WORD_NUMS = {
    "a": 1, "an": 1, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5,
    "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10, "eleven": 11,
    "twelve": 12,
}
_RX_YESTERDAY = re.compile(r"\byesterday\b", re.IGNORECASE)
_RX_TODAY = re.compile(r"\btoday\b", re.IGNORECASE)
_RX_LAST_WEEK = re.compile(r"\blast\s+week\b", re.IGNORECASE)
_RX_LAST_MONTH = re.compile(r"\blast\s+month\b", re.IGNORECASE)
_RX_LAST_YEAR = re.compile(r"\blast\s+year\b", re.IGNORECASE)
_RX_THIS_WEEK = re.compile(r"\bthis\s+week\b", re.IGNORECASE)
_RX_THIS_MONTH = re.compile(r"\bthis\s+month\b", re.IGNORECASE)
_NUM_WORD = r"(\d+|" + "|".join(sorted(_WORD_NUMS, key=len, reverse=True)) + r")"
_RX_N_DAYS_AGO = re.compile(r"\b" + _NUM_WORD + r"\s+days?\s+ago\b", re.IGNORECASE)
_RX_N_WEEKS_AGO = re.compile(r"\b" + _NUM_WORD + r"\s+weeks?\s+ago\b", re.IGNORECASE)
_RX_N_MONTHS_AGO = re.compile(r"\b" + _NUM_WORD + r"\s+months?\s+ago\b", re.IGNORECASE)


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

# -- The relevance gate for memory injected UNASKED ---------------------------
# get_context(relevance_gate=True) is what the provider's per-turn prefetch
# uses. Measured on the production store after automation sessions were already
# excluded: every turn got the full ~4,800-char block whether or not anything
# in memory was about the message -- "what's on my calendar this week" came
# back with an unrelated chat, a hotel confirmation and a list of contact
# names. Ranked retrieval always returns SOMETHING (FTS ORs every word of the
# message, and a vector channel has a nearest neighbour for any query), so for
# an injection nobody asked for, "ranked" is not "relevant".
#
# The rule: an injected item must share a content word with the message. The
# message's content words are its query tokens minus the filler below -- the
# usual English function words plus conversational filler ("thanks", "still",
# "check") that appears in every transcript and so ties anything to anything.
# A message with none ("thanks!", "ok do it") gets no injection at all.
# Deliberately lexical: an item related only by embedding similarity is left
# out of the unasked block and is still found the moment the agent searches.
# The explicit paths (the agent's own search tool, the context engine's
# rehydration, every benchmark) never set the flag and are unchanged.
_GATE_FILLER = frozenset({
    "able", "about", "above", "absolutely", "actually", "after", "again", "against",
    "ahead", "all", "already", "alright", "also", "always", "and", "another", "any",
    "anybody", "anyone", "anything", "anyway", "appreciate", "are", "ask", "asked",
    "awesome", "back", "bad", "basically", "because", "been", "before", "being",
    "below", "best", "better", "between", "big", "both", "but", "came", "can",
    "check", "cheers", "come", "continue", "cool", "could", "course", "definitely",
    "did", "does", "doing", "done", "down", "during", "each", "either", "else",
    "enough", "even", "ever", "every", "everyone", "everything", "exactly", "fair",
    "few", "find", "fine", "first", "fix", "for", "found", "from", "further",
    "gave", "get", "gets", "getting", "give", "goes", "going", "gone", "gonna",
    "good", "got", "gotcha", "great", "had", "has", "have", "having", "hello",
    "help", "her", "here", "hers", "herself", "hey", "him", "himself", "his", "hmm",
    "how", "instead", "into", "its", "itself", "just", "keep", "kept", "knew",
    "know", "last", "later", "let", "lets", "like", "little", "look", "lot", "lots",
    "made", "make", "many", "maybe", "mean", "might", "month", "more", "most",
    "much", "must", "myself", "need", "needed", "neither", "never", "new", "next",
    "nice", "nope", "nor", "not", "nothing", "now", "off", "okay", "old", "once",
    "one", "only", "other", "our", "ours", "ourselves", "out", "over", "own",
    "perfect", "please", "probably", "proceed", "put", "really", "remember",
    "remind", "right", "said", "same", "saw", "say", "see", "seen", "shall", "she",
    "should", "show", "some", "someone", "something", "soon", "sound", "sounds",
    "still", "stop", "stuff", "such", "sure", "take", "tell", "than", "thank",
    "thanks", "that", "the", "their", "theirs", "them", "themselves", "then",
    "there", "these", "they", "thing", "things", "think", "this", "those", "though",
    "thought", "through", "today", "told", "tomorrow", "tonight", "too", "took",
    "totally", "tried", "try", "two", "under", "understood", "until", "use", "used",
    "very", "wait", "wanna", "want", "wanted", "was", "way", "well", "went", "were",
    "what", "whatever", "when", "where", "which", "while", "who", "whom", "why",
    "will", "with", "wonderful", "worked", "works", "would", "wrong", "yeah",
    "year", "yep", "yes", "yesterday", "you", "your", "yours", "yourself",
    "yourselves", "yup",
})


@functools.lru_cache(maxsize=65536)
def _gate_stem(tok: str) -> str:
    """Fold the plural/possessive forms a message and a memory disagree on
    ("restaurants" / "restaurant", "Robin's" / "Robin")."""
    if len(tok) > 4 and tok.endswith("ies"):
        return tok[:-3] + "y"
    if len(tok) > 3 and tok.endswith("s") and not tok.endswith("ss"):
        return tok[:-1]
    return tok


# A URL's pieces ("https", "com", a path's year) are nobody's content words:
# pasted into a message, they matched half the store.
_URL_RX = re.compile(r"(?:https?://|www\.)\S+", re.IGNORECASE)


def _strip_urls(text: str) -> str:
    return _URL_RX.sub(" ", text or "")


def _is_content(t: str) -> bool:
    """A content word: three letters or more, not stop/generic/filler, and
    not a short number -- a year or a count matches every dated item."""
    return (len(t) >= 3 and t not in _STOP and t not in _GENERIC and t not in _GATE_FILLER
            and not (t.isdigit() and len(t) <= 4))


def _gate_words(text: str):
    """Lowercased word tokens outside URLs; a negated contraction ("don't") is
    no word at all, any other ("Robin's", "what's") is the part before the
    apostrophe."""
    for t in word_tokens(_strip_urls(text).lower()):
        if "'" in t:
            if t.endswith("n't"):
                continue
            t = t.split("'", 1)[0]
        yield t


def relevance_words(text: str) -> frozenset:
    """The message's content words (stemmed) for the injection relevance gate.
    Stop/filler words are tested BEFORE stemming -- stemmed, "this" is "thi"."""
    return frozenset(_gate_stem(t) for t in _gate_words(text) if _is_content(t))


# The most content words a gated (per-turn) search looks for. A scheduled
# job's prompt runs to hundreds: on the production store one 4,400-character
# cron prompt (210 content words, 234 prefix terms) took 42-84 s -- far past
# the host's 8 s prefetch timeout, and while that call was stuck the host
# skipped Chronicle for every turn, the user's included -- and matched nearly
# everything anyway.
_GATE_MAX_WORDS = 24


def gate_focus(text: str, limit: int = _GATE_MAX_WORDS) -> str:
    """`text` itself when it has at most `limit` content words; otherwise its
    `limit` most telling ones -- said most often, capitalised (a name), longest,
    then first -- joined by spaces, for the gated search to use in its place."""
    count: dict = {}
    first: dict = {}
    named: set = set()
    for i, raw in enumerate(word_tokens(_strip_urls(text))):
        t = raw.lower()
        if "'" in t:
            if t.endswith("n't"):
                continue
            t = t.split("'", 1)[0]
            raw = raw.split("'", 1)[0]
        if not _is_content(t):
            continue
        stem = _gate_stem(t)
        count[stem] = count.get(stem, 0) + 1
        first.setdefault(stem, (i, t))
        if i > 0 and raw[:1].isupper():
            named.add(stem)
    if len(count) <= limit:
        return text
    ranked = sorted(count, key=lambda w: (-(count[w] + (2 if w in named else 0)),
                                          -min(len(w), 12), first[w][0]))
    return " ".join(first[w][1] for w in ranked[:limit])


def relevance_fts_match(text: str) -> str:
    """The FTS5 expression for the injection gate: the message's content words
    -- as written and as `_gate_stem` folds them -- each a PREFIX term, OR'd.

    The ordinary query ORs every word of the message ("which", "did" and "I"
    included), so on the production store it ranked most of the transcript
    table on every turn (0.77 s a call); the gate then threw away everything
    that shared no content word. Asking FTS for exactly what the gate keeps is
    both faster and the same answer. Prefix terms stand in for the stemming
    the index does not do: "restaurant"* finds "restaurants". "" when the text
    has no content words (the gate then runs no retrieval at all)."""
    terms: set = set()
    for t in _gate_words(text):
        if _is_content(t):
            terms.add(t)
            terms.add(_gate_stem(t))
    return " OR ".join('"%s"*' % t for t in sorted(terms) if '"' not in t)


# What the agent wrote into its OWN memory (Hermes's memory tool, mirrored by
# provider.on_memory_write). Hermes's built-in memory already puts the current
# version of that memory into every system prompt; Chronicle's copies are older
# and include notes the agent has since removed. So the injection into a user's
# turn -- memory about the USER -- leaves them out: the agent's memory and the
# user's are kept distinct. Explicit search still finds them.
_AGENT_OWN_SOURCES = frozenset({"agent_memory_write"})

# retrieval.prefetch_min_similarity "auto": the cosine floor a ONE-word gate
# match must reach, per embedding model (canonical id), measured on the
# production store's real messages. A model not listed gets no floor.
_ONE_WORD_FLOOR = {"nomic-embed-text": 0.65}
# A gate embed is one request inside the user's turn: no retries, never trips
# the embedder's breaker, gives up after _GATE_EMBED_TIMEOUT, and all of one
# turn's together stop at _GATE_EMBED_BUDGET seconds. An item with no stored
# vector is embedded on the spot only when short (a CPU embedder took ~0.45 s
# for 300 characters), and at most _GATE_EMBED_ITEMS of them per turn.
_GATE_EMBED_TIMEOUT = 1.0
_GATE_EMBED_BUDGET = 1.5
_GATE_EMBED_ITEM_CHARS = 240
_GATE_EMBED_ITEMS = 3


def _folded_copy(ev) -> bool:
    """Is this observed event the copy the context engine wrote when it folded
    a message out of the live window (source_type context_eviction)?"""
    p = (ev or {}).get("payload")
    if isinstance(p, str):
        try:
            p = json.loads(p)
        except ValueError:
            return False
    return isinstance(p, dict) and p.get("source_type") == "context_eviction"


def _belief_source(row) -> str:
    """A belief row's provenance source_type ("" when unreadable)."""
    try:
        return (json.loads(row.get("provenance") or "{}") or {}).get("source_type") or ""
    except (ValueError, TypeError, AttributeError):
        return ""

# The widest page retrieve_raw's FTS channel will fetch while looking for
# `limit` rows it can use (see _retrieve_raw_inner).
_FTS_FETCH_MAX = 640


def _probe(w: str) -> str:
    """The letters every token matching `w` STARTS with: its first three (an
    equal stem, a plural or possessive of it, or a prefix relation between
    words of four letters or more all share them) -- two for a three-letter
    "-y" word, whose "-ies" plural shares only those ("fly" / "flies")."""
    return w[:2] if len(w) == 3 and w.endswith("y") else w[:3]


@functools.lru_cache(maxsize=512)
def _probe_rx(probes: tuple):
    """Tokens that start with one of `probes`, with word_tokens' boundaries: a
    token starts at a letter or digit not preceded by one, nor by one plus an
    apostrophe ("o'reilly" is ONE token, so "reilly" does not start inside it)."""
    alt = "|".join(re.escape(p) for p in sorted(probes, key=len, reverse=True))
    return re.compile(r"(?<![^\W_])(?<![^\W_]')(?:%s)[^\W_]*(?:'[^\W_]+)*" % alt)


_INFLECTIONS = ("s", "es", "ed", "d", "ing", "er", "ers")


def _inflects(a: str, b: str) -> bool:
    """Are two (stemmed) words one word inflected? Equal; or the longer is the
    shorter plus an ending ("book"/"booked", "work"/"worker"), with a doubled
    consonant ("plan"/"planned"), a dropped "e" ("make"/"making") or "y" as
    "i" ("happy"/"happier") -- between words of four letters or more. Any
    extension of up to three letters used to count, so "repo" matched
    "report", "rich" "Richard" and "access" "accessories"."""
    if a == b:
        return True
    s, lng = (a, b) if len(a) <= len(b) else (b, a)
    if len(s) < 4:
        return False
    if lng.startswith(s):
        suf = lng[len(s):]
        return suf in _INFLECTIONS or (len(suf) >= 3 and suf[0] == s[-1]
                                       and suf[1:] in ("ed", "ing", "er", "ers"))
    if s.endswith("e") and lng.startswith(s[:-1]):
        return lng[len(s) - 1:] in ("ing", "ed", "er", "ers")
    if s.endswith("y") and lng.startswith(s[:-1]):
        return lng[len(s) - 1:] in ("ied", "ies", "ier", "iest")
    return False


def shared_content_words(words: frozenset | set, text: str) -> set:
    """Which of `words` does `text` contain -- as written or inflected (see
    _inflects), outside URLs?

    Only the tokens that START with a word's probe letters are looked at,
    found by one compiled regex over the text -- measured on the production
    store, tokenising every word of every candidate excerpt in Python was
    1.5 s of a per-turn prefetch, and the candidates are exactly the excerpts
    FTS matched on these words, so a cheaper "does it contain them at all"
    test could not skip any of them. Every inflection of a word starts with
    its probe letters."""
    if not words:
        return set()
    low = unicodedata.normalize("NFC", _strip_urls(text)).replace("\u2019", "'").lower()
    found: set = set()
    for m in _probe_rx(tuple(sorted({_probe(w) for w in words}))).finditer(low):
        t = m.group(0)
        if "'" in t:
            if t.endswith("n't"):
                continue
            t = t.split("'", 1)[0]
        t = _gate_stem(t)
        if t in words:
            found.add(t)
            continue
        if len(t) >= 4:
            for w in words:
                if w not in found and _inflects(t, w):
                    found.add(w)
    return found


def shares_content_word(words: frozenset | set, text: str) -> bool:
    """Does `text` contain one of `words` (see shared_content_words)?"""
    return bool(shared_content_words(words, text))


def gate_needs(words: frozenset | set | None) -> int:
    """How many of the message's content words an item must share to go into
    the turn: one for a short message; two once it has more than three, where
    a single shared word is weak evidence -- on the production store "fire
    every hour" drew "SF Fire Credit Union" and "suite" every street address
    with a "Suite B"."""
    return 1 if len(words or ()) <= 3 else 2


# §r6: the most topic-gated standing notes get_context will append from leftover
# budget. Bounds the tail on a store where a broad focus token ("work") matches
# dozens of norm notes; the char budget is the other, harder stop.
_TOPIC_NOTE_CAP = 5

# A16: the marker a DRAFT belief carries into reader-facing output.
#
# A draft is by construction not confirmed truth -- it is the losing side of a
# `flag_for_review` contradiction (reducer._apply_conflict), a high-risk
# behaviour-changing norm parked for review (curation), or a user-domain
# inference the derivation layer refuses to assert (derivation.default_status).
# `_readable` has always admitted `status in ("active", "draft", None)` and the
# structured channel selects drafts explicitly, so all three reached search(),
# answer() and the Tier-1 context rendered as a plain `[FACT]`/`[NOTE]` --
# indistinguishable from a confirmed one.
#
# MARKED, not excluded, and the choice is from the code's own intent: three
# separate producers deliberately write drafts rather than dropping the value,
# and `_readable` deliberately admits them, so the information is meant to
# reach a reader; what was missing is the caveat, not the row. `[DRAFT]` leads
# the line in the same shape as the existing `[CRITICAL]` / `[CONTRADICTION]`
# tail annotations -- one bracketed word, cheap enough that budget accounting
# does not notice it. An operator who wants the other policy sets
# `retrieval.include_drafts` false (see `_include_drafts`), which drops them at
# the single `_readable` choke point rather than at each render site.
_DRAFT_TAG = "[DRAFT]"

# Identity sample per width-filtered channel. Tied to the only consumer that
# shows identities at all -- `vectors_skipped_wrong_dim_detail`, which is
# itself truncated to 20 -- so nothing downstream can tell the difference.
_WRONG_DIM_SAMPLE = 20

# A10: what the final trim says when it has to drop something. The old blind
# `ctx[:max_chars] + "\n… (truncated)"` named neither what was lost nor how
# much, and cut mid-word / mid-fact to get there.
_OVER_BUDGET_NOTE = "… ({} item{} dropped: over budget)"

# E12: how many raw candidates the precision gate measures session
# concentration over. Five is the head a reader's answer actually comes from
# (get_context's own raw fill spends most of a 1500-token budget on about that
# many excerpts), and it is short enough that one session holding 3+ of it is a
# real convergence rather than a long tail's noise. Not config-gated: it is the
# unit the measured threshold is expressed in, so moving it would silently
# change what context.precision_concentration means.
_PRECISION_HEAD = 5

# F1: the relative score difference below which two raw candidates are TIED as
# far as the precision gate and its packing are concerned.
#
# READ THIS BEFORE ATTRIBUTING ANYTHING TO EMBEDDER NOISE. The E12 firing
# shuffle that motivated F1 — the same six LongMemEval instances firing 4/6 on
# one run and 5/6 on the next, with no code change — was NOT float jitter. It
# was `query_understanding` joining a `set` into the text it embeds, so the
# query was a different word order in every process; see the comment there.
# Measured while chasing it, and recorded so nobody re-derives it: ollama/nomic
# returns bit-identical vectors for identical input (single and batched), and
# two stores built from one instance inside ONE process produce pools that
# agree to the last float. There is no measured per-build jitter in this
# pipeline at all.
#
# What this epsilon is for, then, is the ties that are REAL — candidates whose
# scores genuinely agree to a thousandth, of which the fixtures and the corpus
# have plenty (the dominant test fixture's ranks 5-7 are three such). A gate
# that reads a rank boundary has to answer "who is in the head" for those, and
# any answer drawn from their arrival order or from which of them happened to
# sort fifth is an answer to a question the scores did not ask. So: 1e-3
# relative, two orders BELOW the separations the gate is meant to read (the
# leader's relative margin over the runner-up runs 0.02-0.16 on the six), so it
# can never merge two candidates retrieval genuinely ranked apart. Not
# config-gated, for the same reason `_PRECISION_HEAD` is not: it is the unit the
# stability claim is expressed in.
_PRECISION_TIE_EPS = 1e-3

# E9 (§18.2): query routing via prototype centroids. A fixed built-in phrase
# bank per question kind, embedded once per process (module-level cache below)
# and compared to the incoming query by nearest centroid. "factual" is both a
# kind in its own right AND the fallback everything else collapses to (no
# embedder, routing disabled, embed failure, or the query is simply closest to
# it) -- so the factual path is never anything other than today's behavior.
_ROUTE_KINDS = ("aggregation", "temporal", "preference", "factual")


def _rank_key(id_field):
    """A15: THE tie relation for a ranked candidate list — score DESCENDING,
    then the candidate's own id ASCENDING.

    Not a new relation. It is the secondary key `_precision_order` already
    breaks its bucket ties on, lifted out so `retrieve_raw`, `search` and the
    E3 reranker order equal scores the SAME way the precision gate and its
    tie-aware head do. Two definitions of "tied" that disagree is exactly the
    bug F1 fixed inside the gate; this stops the gate and the ranking it reads
    from re-acquiring it.

    HOW FAR THE ID'S STABILITY GOES, exactly (A15b — A15 said this too widely
    and it cost a day). `serialize.event_id` hashes
    (type, payload, parents, actor, **occurred_at**), so:

      * REPLAY of one log — truncate_projection + rebuild, a restore, a second
        process reading the same store — keeps every id, because it keeps every
        `occurred_at`. This is the property the tie-break is chosen for and it
        holds: measured, one store queried under 8 hash seeds returns
        byte-identical `get_context` output.
      * RE-RECORDING the same turns — a fixture or a benchmark harness that
        calls `capture.observe` again — does NOT. `occurred_at` defaults to
        `now_iso()`, a millisecond wall-clock reading, so every id moves and
        this key becomes a fresh random permutation of each tied bucket. A15
        wrote "the same recorded turn keeps the same id across store rebuilds";
        that is true of the first kind of rebuild and false of the second.

    The consequence is a measurement hazard, not a retrieval one: any harness
    that re-records its own store and then measures something order-sensitive
    is drawing from a distribution rather than repeating an experiment. Such a
    harness must stamp `occurred_at` itself — `test_precision_packing`'s
    FREEZE_PREAMBLE and `test_token_margins`'s `_stamp` are the two in this
    tree, and the second one's class docstring carries the measurement (five
    distinct byte counts from 40 builds at ONE fixed PYTHONHASHSEED).

    Why an id and not "whatever order the pool arrived in": `retrieve_raw`
    fills `scored` from an FTS pass, then drains a heap whose internal array
    order is an implementation detail, then may add ANN, session, projection
    and doc2query tiers; `search` fills `ranked` across six channels. Python's
    sort is stable, so a bare `key=score` hands every tie to that filling
    order — which A5's paged scan can change by re-batching the same rows, and
    which the CHANGELOG (F5) already records shuffling ranks 4 and 5 on v560
    against one unchanged store.

    NOT a change for a pool with no ties: sorting is total, so a strict score
    ordering is untouched, and every score comparison downstream (the
    confidence gate, abstention, MMR relevance) reads the same numbers.

    `id_field` is "event_id" for the raw tier and "belief_id" for Tier 1.
    Coerced through str() and defaulted to "" so a malformed row cannot raise
    a TypeError out of the one sort every query passes through.
    """
    return lambda c: (-c["score"], str(c.get(id_field) or ""))

# Words generic enough to appear across every question kind (articles, copulas,
# pronouns, the ambiguous "what"/"which") -- left in they dilute the bag-of-
# hashed-tokens signal the offline embedder produces for short queries, without
# discriminating anything. This is deliberately NOT engine._STOP: that list
# drops "how"/"when"/"who"/"where" too, which are exactly the words this
# classifier depends on.
_ROUTE_STOP = {
    "a", "an", "the", "i", "my", "me", "is", "are", "was", "were", "do", "does",
    "did", "this", "that", "it", "of", "to", "in", "on", "for", "and", "or", "s",
    "with", "about", "you", "your", "please", "there", "what", "which", "one",
}

_ROUTE_PHRASES = {
    "aggregation": [
        "how many times",
        "how many messages",
        "count the total number",
        "total number of occurrences",
        "how much altogether",
        "how frequently does this happen",
        "how many days",
        "tally the visits",
    ],
    "temporal": [
        "when did this happen",
        "when was this",
        "when did I do this",
        "when will this occur",
        "when is this scheduled",
        "what date did this happen",
        "what time did this occur",
        "how long ago was this",
    ],
    "preference": [
        "what do I prefer",
        "please recommend something",
        "which do I like better",
        "my favorite",
        "suggest something I would enjoy",
        "what should I choose",
        "recommend the best option",
        "what do I usually like",
    ],
    "factual": [
        "who is this person",
        "who is this",
        "where does this person live",
        "where is this located",
        "where do they work",
        "phone number",
        "this persons job",
        "my name",
    ],
}

# Phrase-bank centroids, built ONCE PER PROCESS per (embedder model, dims) --
# not per RetrievalEngine instance, so many short-lived engines sharing one
# embedder (tests, per-query construction) never re-embed the bank. A key whose
# embedder never resolves (BoomEmbedder-style permanent failure) caches an
# empty dict rather than retrying every call.
_ROUTE_CENTROID_CACHE: dict = {}


def _route_tokens(text: str) -> str:
    """Filtered token string an embed call sees for routing (bank AND query):
    lowercased, _ROUTE_STOP dropped, order-preserved. Applying the SAME filter
    on both sides is what lets "when did I go kayaking in Sacramento" match a
    bank of "when did this happen" -- shared noise words never get in the way
    of the one or two content words that actually mark the question kind."""
    return " ".join(t for t in word_tokens((text or "").lower())
                    if t not in _ROUTE_STOP)


def _mean_normalize(vecs: list) -> "list | None":
    if not vecs:
        return None
    dims = len(vecs[0])
    acc = [0.0] * dims
    n = 0
    for v in vecs:
        if len(v) != dims:
            continue
        for i, x in enumerate(v):
            acc[i] += x
        n += 1
    if n == 0:
        return None
    acc = [x / n for x in acc]
    norm = math.sqrt(sum(x * x for x in acc))
    return [x / norm for x in acc] if norm > 1e-12 else acc


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


def _clamp_cfg_float(cfg, key, default, lo, hi):
    """_clamp_cfg's float companion, for knobs that live on a similarity scale.

    _clamp_cfg coerces with int(), which silently floors a fractional knob to
    0 -- a 0.20 similarity margin becomes 0, i.e. the feature turns itself off
    while still reading as configured. Same fallback/clamp contract otherwise."""
    raw = cfg.get(key, default) if cfg else default
    try:
        val = float(raw)
    except (TypeError, ValueError):
        val = float(default)
    if val != val:                      # NaN: every comparison is False
        val = float(default)
    return max(lo, min(hi, val))


class RetrievalEngine:
    # §L9 E8: how far past the natural score-order cutoff MMR selection will
    # reach for a diversity substitute (see _mmr_select's ELIGIBILITY WINDOW
    # docstring for why this is bounded rather than open over the whole
    # fused candidate pool). Not config-gated -- an implementation detail of
    # the selection window, not a caller-facing relevance/diversity dial
    # like retrieval.mmr_lambda.
    _MMR_POOL_OVERFETCH = 1.5

    def __init__(self, store, cfg=None, embedder=None, derivation=None, active_principal="default",
                 vector_index=None):
        self.store = store
        self.cfg = cfg
        self.embedder = embedder
        self.derivation = derivation
        self.active_principal = active_principal
        # E12: the last get_context decision (route + precision flag), so an
        # eval can attribute an answer to the packing that produced it. Defined
        # here so it is readable before any context has been assembled.
        self.last_context_debug: dict = {}
        # A0c: identities of stored vectors this query had to SKIP because their
        # blob width does not match the active embedder's. Keyed by row identity
        # (not counted per scan) so the number a caller sees is "how many rows of
        # your memory were invisible to this query", not "how many times some
        # scan loop tripped over them" -- the same row is scanned by several
        # channels within one query.
        self._wrong_dim_seen: dict = {}
        # (channel, table) -> EXACT count, for the width-filtered channels whose
        # identities are only sampled. Assignment (never +=) keeps a channel read
        # twice in one query idempotent, exactly as the identity dict did.
        self._wrong_dim_counts: dict = {}
        self._wrong_dim_depth = 0
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
        # §L9 E8: MMR diversity/relevance trade-off for search()'s Tier-1
        # candidate SELECTION. 1.0 = pure relevance (today's score-order
        # top-N); 0.0 = pure diversity. Clamped to [0, 1] like the other
        # retrieval dials above -- a bad config value cannot invert the trade.
        self._mmr_lambda = _clamp(
            cfg.get("retrieval.mmr_lambda", d["mmr_lambda"]) if cfg else d["mmr_lambda"])
        self._overlap_min_tokens = int(_clamp(
            cfg.get("retrieval.overlap_min_tokens", d["overlap_min_tokens"]) if cfg
            else d["overlap_min_tokens"], 1, 64))
        # Federated query channel (§g3): bounded, read-only reads of the SQLite
        # databases declared in federation.local_dbs. Built once — each provider
        # caches its introspected schema, so a warm channel costs one statement
        # per searched table. None unless explicitly enabled, so an unconfigured
        # Chronicle never opens an external file.
        self.federated = None
        if cfg is not None and cfg.get("retrieval.federated_channel", False):
            self.federated = FederatedChannel(cfg)

    # -- query understanding (§18.2) --------------------------------------

    def _tokens(self, query: str) -> list[str]:
        return query_tokens(query)

    def _focus_tokens(self, query: str) -> list[str]:
        """The query's distinctive tokens — the same set the abstention gate
        calls focus (§18.4): long enough to discriminate, and not generic."""
        return [t for t in self._tokens(query) if len(t) > 3 and t not in _GENERIC]

    def query_understanding(self, query: str, *, embed: bool = True) -> dict:
        # F1: THE EXPANSION IS AN ORDERED LIST, NOT A SET, because a few lines
        # below it is `" ".join(...)`-ed into the text handed to the embedder.
        #
        # A set's iteration order over strings is a function of PYTHONHASHSEED,
        # which CPython randomises per process. So this built a different
        # PERMUTATION of the same words on every invocation, and a semantic
        # embedder is word-order sensitive: the same question produced a
        # different query vector in every process, hence a different top-20, a
        # different top-5, and — measured — a different E12 gate decision on
        # the same store. That is the whole "E12 fires on 4 of 6 today and 5 of
        # 6 tomorrow" defect: the six motivating LongMemEval instances re-probed
        # with real nomic moved their leading raw score by up to 6.5% relative
        # between processes and reshuffled which sessions held the head, while
        # ollama itself returned bit-identical vectors for identical input and
        # two stores built in ONE process produced identical pools down to the
        # last float. The randomness was never in the embedder or the store; it
        # was in the query text this line composes.
        #
        # It went unseen because every offline gate runs the hashing embedder,
        # which is a bag of hashed tokens and therefore order-INVARIANT — the
        # one embedder that cannot observe the bug. So: the query's own tokens
        # in the order they were asked (which is also the better text to hand a
        # word-order-sensitive model than a shuffle of it), deduped, then any
        # predicate synonyms in a stable order.
        tokens = self._tokens(query)
        expansions: list[str] = []
        seen: set = set()
        for t in tokens:
            if t not in seen:
                seen.add(t)
                expansions.append(t)
        for t in tokens:
            for syn in sorted(self.store.predicate_synonyms(t)):
                if syn not in seen:
                    seen.add(syn)
                    expansions.append(syn)
        emb = None
        if embed and self.embedder is not None:
            # embed_query() is the E1 query-side path (prepends "search_query: "
            # for prefix models). Duck-typed embedders that predate E1 expose
            # only embed(); calling the missing method would raise, get swallowed
            # below, and silently drop the ENTIRE vector channel -- fusion, the
            # E3 reranker and MMR all degrade to lexical-only with no signal that
            # anything broke. Same defensive resolution E1 used for
            # embedder_model_tag()'s duck-typed resolution. A non-conforming embedder
            # has no prefixing to begin with, so falling back to embed() cannot
            # mix a bare query against prefixed documents.
            embed_query = getattr(self.embedder, "embed_query", None)
            if not callable(embed_query):
                embed_query = self.embedder.embed
            try:
                emb = embed_query(" ".join(expansions) or query)
            except Exception:
                emb = None  # vector channel drops out; FTS + structured still answer
        return {"raw": query, "tokens": tokens, "expanded": list(expansions), "embedding": emb}

    # -- query routing (E9, §18.2) ------------------------------------------

    def _route_centroids(self):
        """The phrase-bank centroids for THIS engine's embedder, computed once
        per process (module-level cache keyed by model+dims -- see
        _ROUTE_CENTROID_CACHE) and reused by every subsequent classify_route
        call, in this engine or any other sharing the same embedder config.
        None if there is no embedder or nothing could be embedded (degraded /
        always-raises embedders included -- callers treat that exactly like
        "no embedder", i.e. default route)."""
        if self.embedder is None:
            return None
        key = (getattr(self.embedder, "model", None), getattr(self.embedder, "dimensions", None))
        if key in _ROUTE_CENTROID_CACHE:
            return _ROUTE_CENTROID_CACHE[key] or None
        centroids = {}
        for kind, phrases in _ROUTE_PHRASES.items():
            vecs = []
            for p in phrases:
                try:
                    v = self.embedder.embed(_route_tokens(p))
                except Exception:
                    continue
                if v:
                    vecs.append(v)
            mv = _mean_normalize(vecs)
            if mv is not None:
                centroids[kind] = mv
        _ROUTE_CENTROID_CACHE[key] = centroids
        return centroids or None

    def classify_route(self, query: str, *, now=None) -> dict:
        """Classify `query` by nearest prototype centroid (E9, §18.2): one of
        "aggregation", "temporal", "preference", "factual". Config-gated by
        retrieval.query_routing (default on). Degrades to {"route": "factual"}
        -- today's behavior, unchanged -- whenever routing is disabled, no
        embedder is wired, the bank can't be embedded, or the query itself
        fails to embed; the routing signal is advisory, never a hard
        dependency (I18). Returns the debug field a caller inspects the
        decision through: {"route", "scores", "enabled"}.
        """
        enabled = bool(self.cfg.get("retrieval.query_routing", True)) if self.cfg else True
        if not enabled:
            return {"route": "factual", "scores": {}, "enabled": False}
        centroids = self._route_centroids()
        if not centroids:
            return {"route": "factual", "scores": {}, "enabled": True}
        try:
            q_emb = self.embedder.embed(_route_tokens(query))
        except Exception:
            q_emb = None
        if not q_emb:
            return {"route": "factual", "scores": {}, "enabled": True}
        scores = {kind: cosine(q_emb, vec) for kind, vec in centroids.items()}
        route = max((k for k in _ROUTE_KINDS if k in scores), key=lambda k: scores[k],
                    default="factual")
        # MARGIN GATE. A bare argmax over four centroids is not a calibrated
        # classifier, and its failure mode here is degenerate rather than
        # merely noisy: a query sharing no token with ANY prototype bank scores
        # 0.0 against all four, and max() then returns whichever kind sorts
        # first in _ROUTE_KINDS -- "aggregation". That is not a classification
        # at all, it is tuple order. It is also the common case: 45 of 60 real
        # LongMemEval questions took that path, "What is my ethnicity?" among
        # them, and each then paid the aggregation route's per-session excerpt
        # cap, which DOES drop evidence a factual query would have kept.
        # Measured: 86.2% -> 82.8% on ctx_eval@4000, outside the integration
        # tolerance, while routing disabled scored exactly the 86.2% baseline.
        #
        # So leaving the default route requires BEATING it by a margin, not
        # merely tying it: `factual` IS the default path, so a non-factual
        # route must earn the departure, and a no-signal all-zero query can
        # never earn it. Genuine route queries clear the margin by a wide band
        # (measured +0.22..+0.55 across the acceptance set), so this discards
        # the ambiguous middle without touching confident classifications.
        # Scores are reported UNCHANGED in the debug field either way, so the
        # raw geometry stays inspectable (§E9 "expose the chosen route").
        #
        # F5: the margin is PER KIND, defaulting to the global knob. One
        # threshold for four routes assumes the four separate equally well, and
        # measurement says they do not: over 250 real LongMemEval questions the
        # `preference` centroid is the argmax on 15/15 preference questions and
        # never leads `factual` by more than 0.138, so 0.20 makes that route --
        # and the E12 guard that depends on it -- dead code, while the
        # aggregation route (which the 0.20 figure was actually calibrated
        # against) still fires. `retrieval.query_routing_margins` overrides the
        # global value for named kinds only; an unlisted kind is unchanged.
        if route != "factual":
            default_margin = _clamp_cfg_float(
                self.cfg, "retrieval.query_routing_margin", 0.20, 0.0, 1.0)
            per_kind = (self.cfg.get("retrieval.query_routing_margins", None) if self.cfg else None)
            margin = default_margin
            if isinstance(per_kind, dict) and route in per_kind:
                try:
                    margin = float(per_kind[route])
                except (TypeError, ValueError):
                    margin = default_margin
                if margin != margin:            # NaN: every comparison is False
                    margin = default_margin
                margin = max(0.0, min(1.0, margin))
            if scores.get(route, 0.0) - scores.get("factual", 0.0) < margin:
                route = "factual"
        return {"route": route, "scores": scores, "enabled": True}

    @staticmethod
    def _raw_route(scores):
        """F2X: the route the RAW geometry names, with no margin snap-back --
        i.e. `classify_route`'s own argmax line, before the gate that sends an
        unconvincing winner back to `factual`.

        Deliberately the same expression (same `_ROUTE_KINDS` restriction, same
        `max` tie-break, same "factual" default for an empty `scores`), because
        two definitions of "argmax" that disagree on a tie would be a silent
        behavior fork. Empty `scores` -- routing disabled, no embedder, an
        unembeddable bank or query -- yields "factual", which is what
        `classify_route` returns for exactly those cases, so a caller that
        gates on this cannot change what a routing-less tree does.

        Reads `scores` and nothing else, so a change to how the MARGIN is
        applied (per-kind margins, a different default) cannot move it.
        """
        return max((k for k in _ROUTE_KINDS if k in scores), key=lambda k: scores[k],
                   default="factual")

    # -- Tier 1 (§18.1) ----------------------------------------------------

    # -- wrong-dimension read diagnostics (A0c) -----------------------------

    @contextmanager
    def _query_diagnostics(self):
        """Scope one TOP-LEVEL query's wrong-dimension accounting.

        Depth-counted because answer() calls search() and retrieve_raw(), each
        of which opens this too: only the outermost entry clears the set, so
        one answer() reports one number over all of its channels instead of the
        last channel's. The set survives after the outermost exit so the caller
        can read it (see `last_wrong_dim_skipped`)."""
        if self._wrong_dim_depth == 0:
            self._wrong_dim_seen = {}
            self._wrong_dim_counts = {}
        self._wrong_dim_depth += 1
        try:
            yield self._wrong_dim_seen
        finally:
            self._wrong_dim_depth = max(0, self._wrong_dim_depth - 1)

    def last_wrong_dim_skipped(self) -> int:
        """Distinct stored vectors the most recent top-level query could not
        score because their width does not match the active embedder.

        Two sources, because the identities behind this number stopped being
        affordable to hold. A width-filtered channel contributes an EXACT
        `COUNT(*)` (`_wrong_dim_counts`) and keeps only a 20-row identity
        sample; a channel that scans rows itself still contributes distinct
        identities (`_wrong_dim_seen`), which its own paging already bounds.
        Channels of the first kind are excluded from the identity tally so
        their sample cannot be added on top of their count."""
        counted_channels = {ch for ch, _table in self._wrong_dim_counts}
        identity_only = sum(1 for ch, _ident in self._wrong_dim_seen
                            if ch not in counted_channels)
        return sum(self._wrong_dim_counts.values()) + identity_only

    def _note_wrong_dim_table(self, query_emb, table, id_col, channel,
                              extra_where: str = "", extra_params=()):
        """The ID-ONLY complement of a width-filtered scan (A0 x A5).

        THE CANCELLATION THIS EXISTS FOR. A0c made a present-but-incomparable
        vector LOUD on read: `_note_wrong_dim_rows` recorded its identity per
        query and `batch_cosine` raised the process-wide counter and the
        one-shot WARNING. A5 then pushed `length(embedding) = ?` into SQL so a
        scan stops hauling ~88% of production's vector bytes into Python to be
        scored 0.0 and thrown away. Each is a measured fix; composed naively
        they ANNIHILATE, because the rows A0 reports are exactly the rows A5's
        predicate removes -- the scan never sees them, so nothing is counted,
        the WARNING never fires, and an 88%-mismatched store reads clean again.
        A5 named this hazard in `iter_memory_vectors_paged`'s docstring and left
        the call to A0; this is that call.

        The resolution is to ask the COMPLEMENTARY question, exactly as A7's
        census does for the heal: the scan keeps `width=` and scores only
        comparable rows, and the diagnostic runs one ID-ONLY query for the rows
        the scan deliberately skipped --
            SELECT <id>, length(embedding) FROM <table>
             WHERE embedding IS NOT NULL AND length(embedding) != ?
        -- inside the SAME `_query_diagnostics` scope, so one top-level query
        still reports one number over every channel.

        WHY IDENTITY AND NOT COUNT(*). A0 dedupes across tiers: `answer()` runs
        `search()` and `retrieve_raw()`, and `query_proxy_vectors` is read twice
        per query (beliefs then excerpts). Summed COUNT(*)s would double-count;
        `_wrong_dim_seen` is keyed by (channel, id), so identities are idempotent
        and the reported number stays the number of DISTINCT unreadable vectors.

        NO BLOBS ARE READ. `length(embedding)` is answerable from
        `idx_{ov,mv,qpv}_model_width` (store._VECTOR_CENSUS_INDEX_DDLS), and the
        width sentinel below carries only that integer, so this is strictly
        cheaper than the pre-A5 code it replaces -- which materialised every one
        of those blobs.

        A scan that is NOT width-filtered must not call this: it still sees the
        rows itself and `_note_wrong_dim_rows` still reports them, and calling
        both would be correct but redundant. Passing `width=None` to re-enable
        the old path is the one thing that silently reverts A5, so it is never
        done here."""
        if not query_emb:
            return
        want = len(query_emb) * 4
        # COUNT first, identities second and BOUNDED. The pre-bound code asked
        # for every wrong-width identity and built one object per row, once per
        # channel, five to six times per top-level query, and held them until
        # the next one -- on an 88%-mismatched production store that is ~93k
        # rows a channel, i.e. A5's bound undone by the diagnostic that A5's
        # own docstring asked for. The number stays exact because it now comes
        # from SQL rather than from len() of the identities.
        total = self.store.wrong_dim_vector_count(table, id_col, want,
                                                  extra_where, extra_params)
        if not total:
            return
        pairs = self.store.wrong_dim_vector_ids(table, id_col, want,
                                                extra_where, extra_params,
                                                limit=_WRONG_DIM_SAMPLE)
        if not pairs:
            return
        # The process-wide counter and the once-per-process WARNING used to be
        # raised by batch_cosine seeing the blob. It no longer does, so they are
        # raised here -- through the MODULE, not a from-import, so the A0c
        # mutation guard (which patches embeddings.note_wrong_dim) still turns
        # the whole signal off and keeps proving that this file is what makes it
        # loud. tests/test_wrong_dim_read_refusal.py is that guard.
        _embeddings.note_wrong_dim(total, "%s (%s)" % (table, channel))
        # The count goes through `_note_wrong_dim_rows` rather than straight into
        # `_wrong_dim_counts`, so this channel still reports through the ONE
        # choke point tests/test_wrong_dim_read_refusal.py's mutation guard
        # patches. A count recorded beside that guard rather than behind it
        # would be a third reporting path the guard does not cover, and the
        # guard exists precisely to prove there is no such path.
        self._note_wrong_dim_rows(
            query_emb, [{id_col: ident, "embedding": _WrongDimWidth(nbytes)}
                        for ident, nbytes in pairs],
            id_col, channel, table=table, exact_count=total)

    def _note_wrong_dim_rows(self, query_emb, rows, id_key, channel,
                             table=None, exact_count=None):
        """Record which of `rows` are present-but-incomparable, by identity.

        Cheap: one length comparison per row, over blobs the scan already holds.
        The per-scan COUNT (and the once-per-process WARNING) is raised inside
        embeddings.batch_cosine / cosine; this adds the per-query, per-row
        identity a caller can act on."""
        if not query_emb or not rows:
            return
        if exact_count is not None:
            # A width-filtered channel: `rows` is a bounded SAMPLE, so its length
            # is not the answer. Assignment, never +=, so the same channel read
            # twice in one query stays idempotent exactly as the identity dict is.
            self._wrong_dim_counts[(channel, table)] = exact_count
        for i in wrong_dim_indices(len(query_emb), [r.get("embedding") for r in rows]):
            ident = rows[i].get(id_key)
            if ident is not None:
                self._wrong_dim_seen[(channel, ident)] = len(rows[i]["embedding"]) // 4

    def search(self, query, *, limit=10, domain=None, purpose="*", principal=None, now=None,
               fts_match=None, lexical_only=False):
        """Fused FTS + vector + graph + structured search (§18). Thin wrapper:
        the body is `_search_inner`; this opens the A0c wrong-dimension scope so
        one top-level query reports one number across every channel."""
        with self._query_diagnostics():
            return self._search_inner(query, limit=limit, domain=domain, purpose=purpose,
                                      principal=principal, now=now, fts_match=fts_match,
                                      lexical_only=lexical_only)

    def _search_inner(self, query, *, limit=10, domain=None, purpose="*", principal=None, now=None,
                      fts_match=None, lexical_only=False):
        principal = principal or self.active_principal
        q = self.query_understanding(query, embed=not lexical_only)
        if fts_match is not None:
            # The injection gate's search: the structured channel scans facts
            # once per token (an unindexable LIKE) and the graph channel seeds
            # entities by token, so both take the message's content words only
            # -- "which" is not worth a scan of the facts table, or an entity.
            q = dict(q, tokens=[t for t in q["tokens"] if relevance_words(t)])
        ranked: dict[str, dict] = {}
        # R12: entities carry no vector of their own (names are not semantic
        # content, §R12), so a purely SEMANTIC entity match can only ever surface
        # through its digest note's embedding. Collected here and merged into the
        # graph channel's seed list below, so a query that means an entity —
        # without naming it or any of its relationships — still reaches that
        # entity's facts. Vector-only: an FTS/structured hit on a digest's text
        # is a literal string match, which is exactly what the digest choke point
        # below already excludes (§u2) and must keep excluding.
        digest_seed_ids: list[str] = []

        def add(bid, table, rank, channel):
            row = self.store.get_belief(table, bid)
            if not row or not self._readable(row, principal, purpose, domain):
                return
            # §u2: a consolidation digest restates facts that are already indexed,
            # so letting it compete here would push its own sources down the
            # ranking and answer with a summary where a verbatim value exists.
            # One choke point covers every channel (fts, vector, graph).
            if table == "notes" and str(row.get("subject") or "").startswith("digest:"):
                if channel == "vector":
                    eid = str(row.get("subject"))[len("digest:"):]
                    ent = eid and self.store.get_belief("entities", eid)
                    if ent and not ent.get("merged_into") and eid not in digest_seed_ids:
                        digest_seed_ids.append(eid)
                return
            # vector_proxy (E2 doc2query) is deliberately weighted BELOW a
            # direct content-vector hit: it is a synthetic, templated signal,
            # not primary evidence, and RRF is rank- not score-based, so an
            # un-discounted proxy hit at its OWN rank #1 would earn the same
            # boost as a genuine strong content match — letting proxy COUNT
            # crowd a tight context budget rather than match quality deciding
            # it (measured: ctx_eval recall@1500 regressed until this discount
            # + the best-per-belief reduction in _vector_proxies).
            w = {"fts": self._fts_w, "vector": self._vec_w, "vector_proxy": self._vec_w * 0.5,
                 "graph": self._graph_w()}.get(channel, 0.3)
            entry = ranked.setdefault(bid, {"row": row, "table": table, "score": 0.0, "why": set()})
            entry["score"] += w / (self._rrf_k + rank)
            entry["why"].add(channel)

        of = self.cfg_overfetch()
        for i, r in enumerate(self.store.fts_search_beliefs(
                query, limit=limit * of, **({"match": fts_match} if fts_match is not None else {}))):
            add(r["belief_id"], _table_of_kind(r["kind"]), i + 1, "fts")
        if q["embedding"] is not None:
            for i, (bid, kind, _s) in enumerate(self._vector_beliefs(q["embedding"], limit * of)):
                add(bid, _table_of_kind(kind), i + 1, "vector")
            # E2 doc2query: a question-shaped query can match a generated
            # question proxy even when it shares nothing with the belief's own
            # content vector (e.g. "where does Pat Testley work" vs. the fact's
            # stored value "Acme Fake Co"). add() re-fetches the PARENT belief
            # by belief_id exactly like any other vector hit, so the proxy's
            # question text never appears in output — only the belief's own
            # content and provenance do (§E2 "never surfaces the proxy text").
            for i, (bid, kind, _s) in enumerate(self._vector_proxies(q["embedding"], limit * of)):
                add(bid, _table_of_kind(kind), i + 1, "vector_proxy")
        # Structured channel: substring hits on a fact's value/attribute/
        # predicate — one unindexable `LIKE '%tok%'` scan per token, which A5
        # names as a hot spot. MEASURED at 100k facts, 6-token query, before
        # changing anything: 20-25 ms when the tokens match, 143-155 ms when
        # none of them do (six complete scans). Two result-identical
        # restructures were built and measured against that, and BOTH were
        # rejected on the numbers:
        #   - one combined scan with per-token buckets and early exit when all
        #     buckets fill: 97 ms in the nothing-matches case (better) but
        #     217 ms in the common case (10x WORSE) — a per-token `LIMIT` stops
        #     its own scan after N hits, and that early exit is worth far more
        #     than cutting six scans to one;
        #   - narrowing `SELECT *` to `SELECT belief_id`: 24.4 vs 25.5 ms and
        #     147 vs 143 ms — noise. SQLite already skips undecoded columns;
        #     the cost is the LIKE itself.
        # No index can serve a leading `%` (a partial index on `status` reorders
        # rows under LIMIT, which WOULD change results), so the only real fix is
        # the audit's own: back this channel with `belief_fts` (or a trigram FTS
        # mirror). Both change WHICH rows match, so they belong to a
        # behaviour-changing task, not to A5's ranking-identical optimisation.
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
        #
        # R12: digest_seed_ids (populated above, vector channel only) are merged
        # in as additional seeds — the SEMANTIC route to an entity, alongside the
        # lexical one _graph_seeds already does. Same overall cap, so a query that
        # both names an entity and semantically matches another's digest still
        # bounds the fan-out at 6.
        nodes = self._graph_seeds(q["tokens"])
        for eid in digest_seed_ids:
            if len(nodes) >= 6:
                break
            if eid not in nodes:
                nodes.append(eid)
        hop: list[str] = []
        for e in nodes[:3]:
            for r in self.store.query_beliefs(
                    "relationships", "(source_id=? OR target_id=?) AND status='active'", (e, e), 8):
                for nb in (r.get("source_id"), r.get("target_id")):
                    if nb and nb not in nodes and nb not in hop:
                        hop.append(nb)
        for rank, e in enumerate(nodes[:6] + hop[:6]):
            for f in self.store.query_beliefs("facts", "entity_id=? AND status='active'", (e,), 8):
                add(f["belief_id"], "facts", rank + 1, "graph")

        # §H2.2 host-model rerank hints: a prior host verdict on THIS query (or
        # a sufficiently similar one) votes here, as one more channel. Modelled
        # as a channel rather than a post-hoc score patch on purpose — the whole
        # ranking downstream (MMR selection, the E3 reranker's min-max envelope,
        # the confidence and abstention gates) is calibrated on the RRF scale,
        # and a contribution shaped like `w/(rrf_k + rank)` is the only kind
        # that composes with it without special-casing anything.
        #
        # RE-WEIGHTS ONLY; never introduces a candidate. A hint that names a
        # belief no channel surfaced is silently ignored, so a stale or
        # adversarial verdict cannot inject evidence a real query did not find —
        # it can only reorder what retrieval already believed was in play.
        for bid, weight in self._hint_scores(query, principal).items():
            entry = ranked.get(bid)
            if entry is None:
                continue
            entry["score"] += self._hint_w() * weight / (self._rrf_k + 1)
            entry["why"].add("host_hint")

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

        # §L9 E8: greedy MMR SELECTION -- decides which `limit` candidates make
        # the cut so near-duplicate hits stop crowding out distinct evidence
        # (get_context's Tier-1 block is exactly this list, capped at 10).
        # Selection only: the sort immediately below is unchanged from before
        # this task, so the ORDER a caller sees -- get_context's §L8
        # evidence-forward contract chief among them -- is untouched; MMR only
        # changes which items survive the [:limit] cut when there are more
        # candidates than room. No embedder / no query vector (offline FTS-only
        # mode, or an embed() failure) -> exactly today's score-order top-N.
        #
        # A15: ordered BEFORE selection, not only after it. `ranked` is a dict
        # filled across six channels (fts, vector, vector_proxy, structured,
        # graph, host_hint), and MMR reads `out` as given: its eligibility
        # window is `sorted(..., key=score)[:window]` (stable, so ties fall to
        # the fill order) and its greedy argmax keeps the FIRST candidate on a
        # tie. Both therefore inherited whichever channel happened to insert a
        # tied belief first. One sort here fixes the input to selection, the
        # window, the argmax and the returned order at once.
        out.sort(key=_rank_key("belief_id"))
        if self.embedder is not None and q["embedding"] is not None and len(out) > limit:
            keep = set(self._mmr_select(out, limit, self._mmr_lambda))
            out = [c for c in out if c["belief_id"] in keep]
        out.sort(key=_rank_key("belief_id"))
        out = self._rerank(out, q["embedding"])
        out = out[:limit]
        self._offer_rerank(query, out)
        return out

    # -- §H2.2 host-model rerank hints -------------------------------------

    def _hint_w(self):
        """Channel weight for a host rerank hint, clamped [0, 2].

        Default 1.0 = fts_weight + vec_weight, i.e. one top-ranked hint is
        worth about what a candidate would earn by leading BOTH retrieval
        channels at once. That is deliberately assertive but still bounded: the
        hint is an explicit judgement by a model that saw this exact query and
        these exact candidates, which is strictly more information than either
        channel has — and it still cannot manufacture a candidate, only move
        one. 0 is the off-switch."""
        return _clamp_cfg_float(self.cfg, "host_model.rerank_hints.weight", 1.0, 0.0, 2.0)

    def _hint_scores(self, query, principal=None) -> dict:
        """belief_id -> effective hint weight for this query. {} is the normal
        answer: the table is empty unless host_model.piggyback is on AND a host
        actually returned a rerank verdict.

        Two match modes, cheapest first. An EXACT signature match (same
        distinctive token set) applies the stored reciprocal-rank weight
        undiminished. Otherwise every live hint is scored by Jaccard overlap of
        token sets and anything at or above host_model.rerank_hints.similarity
        applies its weight SCALED BY that overlap — so a near-miss query gets a
        proportionally weaker nudge, and a barely-related one gets nothing. The
        scan is affordable precisely because the store is capped
        (host_model.rerank_hints.max_entries, default 200 rows).

        Age decays linearly to zero across the row's own TTL, so a hint fades
        rather than falling off a cliff on its expiry date, and an expired row
        is never read at all (the store filters on expires_at).

        Owner-scoped (ladder-9 F4c): only hints stored under the QUERYING
        principal's owner (access.user_of(principal)) are ever looked at, so a
        rerank verdict recorded for one owner cannot reorder, even by a little,
        a different owner's textually similar query -- store-global rerank
        hints were an ordering-only but real cross-owner leak.

        Sandbox-scoped (ladder-10 A1): owner-scoping alone cannot close the
        sandbox case, because a sandboxed agent shares its owner with exactly
        the siblings it must not reach. A hint authored by a sandboxed
        principal is therefore skipped for every OTHER principal (its own
        queries still use it -- a sandbox denies INBOUND reads, not its own).
        """
        if self.cfg is not None and not self.cfg.get("host_model.rerank_hints.enabled", True):
            return {}
        key, toks = hint_signature(query)
        if not key:
            return {}
        principal = principal or self.active_principal
        owner = access.user_of(principal)
        try:
            rows = self.store.live_rerank_hints(now_iso(), owner=owner, limit=_clamp_cfg(
                self.cfg, "host_model.rerank_hints.max_entries", 200, 1, 10000))
        except Exception as e:  # a hint lookup may never fail a search
            logger.debug("rerank hints unavailable (%s)", e)
            return {}
        if not rows:
            return {}
        floor = _clamp_cfg_float(self.cfg, "host_model.rerank_hints.similarity", 0.6, 0.0, 1.0)
        mine = set(toks)
        topo = access.active_topology()
        out: dict = {}
        for row in rows:
            # A1: owner-scoping (F4c) cannot see the sandbox, because a
            # sandboxed agent shares its OWNER with the very siblings it must
            # not reach. A sandbox denies inbound reads absolutely, and a hint
            # that re-weights someone else's ranking is an inbound read of the
            # sandbox's verdict, so it is dropped here — by principal, at the
            # same topology the can_read choke point consults.
            author = row.get("principal") or ""
            if topo is not None and author != principal and topo.is_sandboxed(author):
                continue
            if row["query_key"] == key:
                overlap = 1.0
            else:
                try:
                    theirs = set(json.loads(row["tokens"] or "[]"))
                except ValueError:
                    continue
                union = mine | theirs
                overlap = (len(mine & theirs) / float(len(union))) if union else 0.0
                if overlap < floor:
                    continue
            w = float(row["weight"] or 0.0) * overlap * _hint_freshness(row)
            if w > out.get(row["belief_id"], 0.0):
                out[row["belief_id"]] = w
        return out

    def _offer_rerank(self, query, candidates):
        """§H2.2: register this query's top candidates as rerank work a host
        model could do. Gated on host_model.piggyback — a plain dict lookup, so
        the default read path reaches no SQL here and search() stays read-only
        exactly as before.

        `candidate_ids` rides alongside the rendered `candidates` text because
        the reply is a list of INDICES: without the parallel id list a returned
        order names positions in a list that no longer exists anywhere, which
        is precisely why H1's parked rerank results had nothing to bind to."""
        if self.cfg is None or not self.cfg.get("host_model.piggyback", False):
            return
        if len(candidates) < 2:
            return                      # nothing to reorder; not worth a slot
        try:
            from .hostmodel import MAX_RERANK, HostModelRegistry
            cap = min(MAX_RERANK, _clamp_cfg(
                self.cfg, "host_model.rerank_hints.max_per_query", 8, 1, MAX_RERANK))
            head = candidates[:cap]
            HostModelRegistry(self.store, self.cfg).enqueue("rerank", {
                "query": str(query)[:200],
                "candidates": [str(c.get("value") or "")[:80] for c in head],
                "candidate_ids": [c["belief_id"] for c in head]})
        except Exception as e:
            logger.debug("rerank host-model offer not enqueued (%s)", e)

    def _rerank(self, candidates, query_emb):
        """E3: kill the identity passthrough. After FTS+vector+graph fusion,
        re-score the top `retrieval.rerank_top_k` candidates by
        cosine(query embedding, candidate embedding) blended with their
        fusion score -- `retrieval.rerank_blend` * cosine +
        (1 - blend) * normalized_fusion -- and re-order before packing.

        THE TWO SCALES MUST BE MADE COMMENSURATE FIRST. The incoming score is
        RRF (Σ w/(rrf_k + rank), ≈ 0.002–0.025); cosine is in [0, 1]. Blending
        them raw is not a blend at all -- at the default 0.5 the cosine term
        outweighs the fusion term by ~50:1, which is a pure cosine re-sort that
        also sinks every vectorless candidate to the bottom by construction.
        That is measurable damage, not a theoretical worry: it cost 8 points of
        belief turn-recall@1 on LongMemEval-s (37.0 → 29.0) with the raw tier
        unchanged.

        Normalization is MIN-MAX over the re-scored set (`f = (s - lo) /
        (hi - lo)`), not rank-based. Rank normalization would throw away the
        one thing RRF magnitude actually encodes -- how many channels agreed
        and how strongly -- and space every candidate an equal 1/K apart, so a
        cosine wobble of 1/K could flip any adjacent pair. Min-max keeps the
        shape: where fusion has a decisive leader the gap stays decisive and
        cosine cannot overturn it; where fusion is a near-tie (the common RRF
        case, and exactly where the fused ranking is least informative) the
        candidates land within a hair of each other and cosine breaks the tie.

        A candidate with NO stored vector keeps its normalized fusion score,
        untouched: `sim` is imputed as `f`, so its blended score is
        `blend*f + (1-blend)*f == f`. Nothing is subtracted for the missing
        vector, so the reranker is structurally unable to sink a candidate
        merely for lacking one -- a vectorless candidate leading on fusion
        (f = 1.0) cannot be displaced at all, since the best any rival can
        reach is `blend*1 + (1-blend)*f_rival < 1`.

        Scores are then mapped back onto the original [lo, hi] envelope. The
        reranker is a RE-ORDERING, not a re-scoring: `score` is consumed
        downstream on the RRF scale (`_confident`, `_support_gate`'s "score"
        mode, `answer`'s miss threshold), and the top score stays exactly `hi`
        so none of those gates can shift underneath this change.

        `candidates` must already be sorted by fusion score descending: only
        the head (the top-K by fusion score) is re-scored, the tail is
        returned untouched and in place, so a candidate that was never in
        contention for the top slots is never given a shot at outranking one
        that was. No query embedding (embedder absent/degraded, §I18) is a
        complete no-op: identity fallback, fusion order passes through
        exactly as before.
        """
        if query_emb is None or not candidates:
            return candidates
        top_k = _clamp_cfg(self.cfg, "retrieval.rerank_top_k", 50, 1, 500)
        blend = self._rerank_blend()
        head, tail = candidates[:top_k], candidates[top_k:]
        fused = [c["score"] for c in head]
        lo, hi = min(fused), max(fused)
        span = hi - lo
        if span <= 0.0:
            # Every candidate fused to the same score: there is no spread to
            # normalize against, and any constant we imputed would either sink
            # every vectored candidate below every vectorless one or the
            # reverse. Leave the set alone.
            return candidates
        vecs = self.store.get_memory_vectors_by_ids([c["belief_id"] for c in head])
        blended = []
        for c in head:
            f = (c["score"] - lo) / span
            v = vecs.get(c["belief_id"])
            if v is None:
                blended.append(f)  # no vector → sim imputed as f → score is f
                continue
            sim = cosine(query_emb, unpack(v["embedding"]))
            sim = 0.0 if sim < 0.0 else (1.0 if sim > 1.0 else sim)
            blended.append(blend * sim + (1.0 - blend) * f)
        blo, bhi = min(blended), max(blended)
        if bhi - blo <= 0.0:
            return candidates  # blend separates nothing → keep fusion order
        for c, b in zip(head, blended):
            c["score"] = lo + (b - blo) / (bhi - blo) * span
        # A15: the blend can tie two candidates that the fusion score
        # separated, and a stable `key=score` sort would then order them by
        # their OLD scores — an ordering the new scores no longer support.
        # Same relation as everywhere else (`_rank_key`).
        head.sort(key=_rank_key("belief_id"))
        return head + tail

    def _rerank_blend(self):
        try:
            b = float(self.cfg.get("retrieval.rerank_blend", 0.5)) if self.cfg else 0.5
        except (TypeError, ValueError):
            b = 0.5
        return max(0.0, min(1.0, b))

    def _mmr_select(self, candidates, k, lam):
        """Greedy MMR (§L9 E8) over the candidates that actually carry a
        vector, with vector-less candidates (entities: §R12 -- "names are not
        semantic content", so entities carry no vector of their own by
        design, not by omission) filling only whatever slots the vectored,
        diversity-ranked pool didn't need.

        Splitting this way (rather than letting a vector-less candidate enter
        the SAME argmax race, exempt from the similarity penalty everyone
        else pays) matters: a candidate with no vector can never be scored
        for redundancy, so if it competed directly it would look artificially
        "maximally diverse" against every already-picked item purely for
        lacking data -- not because it truly is distinct. Measured regression
        (ctx_eval instance #4, s_ctx100.json): a bare `[ENTITY] IKEA` stub
        (no vector) leapfrogged the actual answer-bearing `[EPISODE]` (which
        DOES have a vector, and paid the redundancy tax for legitimately
        overlapping an earlier IKEA-topic pick) into the last Tier-1 slot,
        even though the episode outscored it before either was penalized.
        Reserving the vectored pool's own `k` slots first, and only spilling
        into vector-less candidates for genuine leftover room, removes that
        loophole while still never excluding vector-less items outright.

        Returns the selected belief_ids in no particular order -- the caller
        re-sorts by score (selection only, §L8 ordering untouched).

        ELIGIBILITY WINDOW: only the top `_MMR_POOL_OVERFETCH * k` candidates
        by raw fusion score are even considered for the argmax race below.
        Second measured regression (ctx_eval instance "94f70d80" IKEA-
        bookshelf, s_ctx100.json, budget=1500), found AFTER the vector-less
        fix above landed and still failing with it in place: `search()` feeds
        _mmr_select the full fused pool (43 candidates for that query, not
        just the natural top-10), because it must -- an item crowded out of
        the naive top-k is by definition ranked below it. But an *unbounded*
        pool lets MMR reach arbitrarily deep for "diversity": a rank-17
        candidate (an off-topic roleplay excerpt, score 0.0057) beat the
        rank-9 answer-bearing episode (score 0.0065, penalized for
        legitimately overlapping an earlier same-topic pick) into the last
        slot, purely because rank-17 had zero similarity to anything already
        selected. Both carry vectors, so the vector-less split doesn't apply
        here -- the bug is that "maximally dissimilar" and "plausible
        candidate" are not the same thing once the pool reaches deep enough
        into the tail, and fused (~RRF-shaped) scores decay too fast for
        min-max normalization to keep that tail meaningfully separated from
        genuine near-cutoff contenders. A near-duplicate cluster crowding out
        distinct evidence -- what this task fixes -- clusters at the TOP of
        the ranking (they scored well BECAUSE they resemble each other and
        the query); the items worth rescuing sit just below the natural
        cutoff, not arbitrarily far down. Capped empirically against the
        full ctx_eval + oracle harnesses: 1.5x recovers the IKEA instance
        without dropping any acceptance-test candidate (the near-duplicate
        fixture's distinct1/distinct2 sit at ranks 5-6 of 8 for k=5, well
        inside the window either way).
        """
        if k <= 0 or not candidates:
            return []
        if len(candidates) <= k:
            return [c["belief_id"] for c in candidates]
        window = max(k, int(round(k * self._MMR_POOL_OVERFETCH)))
        if len(candidates) > window:
            candidates = sorted(candidates, key=lambda c: c["score"], reverse=True)[:window]
        vecs = self._candidate_vectors(candidates)
        vectored = [c for c in candidates if c["belief_id"] in vecs]
        unvectored = [c for c in candidates if c["belief_id"] not in vecs]

        selected_ids = self._mmr_greedy(vectored, min(k, len(vectored)), lam, vecs)
        remaining = k - len(selected_ids)
        if remaining > 0 and unvectored:
            top_unvectored = sorted(unvectored, key=lambda c: c["score"], reverse=True)
            selected_ids += [c["belief_id"] for c in top_unvectored[:remaining]]
        return selected_ids

    @staticmethod
    def _mmr_greedy(pool, k, lam, vecs):
        """The actual greedy-MMR loop (§L9 E8):
        argmax  lam * relevance(c) - (1 - lam) * max_similarity_to_selected(c)
        run k times over `pool`, where every item in `pool` is guaranteed to
        have an entry in `vecs` (§_mmr_select splits vectored/vector-less
        candidates before calling this). `relevance` is each candidate's
        fused RRF score, min-max normalized across `pool` to [0, 1] so it
        sits on the same scale as cosine similarity -- RRF scores are tiny
        (~w/(k+rank)) and would otherwise be swamped by the similarity term
        regardless of `lam`."""
        if k <= 0 or not pool:
            return []
        scores = [c["score"] for c in pool]
        lo, spread = min(scores), (max(scores) - min(scores))

        def relevance(c):
            return (c["score"] - lo) / spread if spread > 0 else 1.0

        remaining_pool = list(pool)
        selected_ids: list = []
        selected_vecs: list = []
        while remaining_pool and len(selected_ids) < k:
            best_idx, best_val = 0, None
            for i, c in enumerate(remaining_pool):
                v = vecs[c["belief_id"]]
                max_sim = max((cosine(v, sv) for sv in selected_vecs), default=0.0)
                val = lam * relevance(c) - (1 - lam) * max_sim
                if best_val is None or val > best_val:
                    best_val, best_idx = val, i
            chosen = remaining_pool.pop(best_idx)
            selected_ids.append(chosen["belief_id"])
            selected_vecs.append(vecs[chosen["belief_id"]])
        return selected_ids

    def _candidate_vectors(self, candidates):
        """belief_id -> unpacked embedding for a small candidate set (§L9 E8
        MMR), via a targeted by-id lookup rather than a full-table scan."""
        rows = self.store.get_memory_vectors_by_ids([c["belief_id"] for c in candidates])
        return {bid: unpack(r["embedding"]) for bid, r in rows.items() if r.get("embedding")}

    # -- Tier 2 (§18.1) — raw layer (recall floor) ------------------------

    def _graph_seeds(self, tokens, cap=6) -> list[str]:
        """Query tokens → entity nodes (§18.8). Names match entities directly;
        predicates ("wife", "sister") reach entities through relationships.
        Shared with get_context so the digest surface seeds on exactly the same
        entities the graph channel does, rather than a second guess at it."""
        nodes: list[str] = []
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

    def _abstain_distance(self):
        """Geometric abstention (E10) threshold, coerced like the sibling
        numeric config knobs (_graph_w, _temporal_boost): float() with a safe
        fallback on garbage. Unlike those, the "off" value is None (not a
        clamped numeric default) -- a bad config value must degrade to
        feature-off, not raise TypeError out of answer() at query time."""
        raw = self.cfg.get("retrieval.abstain_distance") if self.cfg else None
        if raw is None:
            return None
        try:
            return float(raw)
        except (TypeError, ValueError):
            return None

    def retrieve_raw(self, query, *, limit=20, principal=None, now=None, exclude_automation=False,
                     fts_match=None, lexical_only=False):
        """Raw observed/session/projection tier. Wrapper for the A0c scope; the
        body is `_retrieve_raw_inner`.

        `exclude_automation`: leave out everything from an automation session
        (a scheduled job's own run). Set by the callers that inject memory into
        the user's conversation unasked — the provider's per-turn prefetch and
        the context engine's rehydration — and left off for an explicit search,
        where the agent may be asking about its own work. On the production
        store 7,817 of 7,924 indexed sessions were cron runs, and the per-turn
        block was serving their tool JSON and operational narratives as memory
        about the user."""
        with self._query_diagnostics():
            return self._retrieve_raw_inner(query, limit=limit, principal=principal, now=now,
                                            exclude_automation=exclude_automation,
                                            fts_match=fts_match, lexical_only=lexical_only)

    @staticmethod
    def _from_automation(ev: dict | None) -> bool:
        """Whether an event was written by automation (engine/speaker): an
        automation session, or a turn whose user side capture recorded as
        automation -- a subagent, a background review, a non-primary agent, a
        bot author. The session prefix alone misses those: on the production
        store cron prompts sat in sessions with no `cron_` prefix."""
        if not ev:
            return False
        raw = ev.get("payload")
        try:
            p = json.loads(raw) if isinstance(raw, str) else (raw or {})
        except ValueError:
            p = {}
        if ((p.get("attribution") or {}).get("user_side") == _spk.AUTOMATION):
            return True
        sid = ev.get("session_id") or p.get("source_ref") or ""
        return _spk.is_automation_session(sid)

    def _reader_excerpt(self, ev, stored):
        """What a reader is handed for observed event `ev`: its excerpt with the
        host framing taken out (speaker.reader_text) -- an earlier compaction's
        handoff, a system note, Chronicle's own <memory-context> injection. The
        stored text still carries them byte-for-byte, because the event id is a
        hash of it; spans mark them, and extraction has always skipped them, but
        recall used to serve them back as conversation.

        `stored` is the text the channel already holds (the FTS row, the payload
        excerpt) and is returned AS IS whenever nothing in the event is framing,
        so every excerpt without framing is byte-identical to before. None means
        the event was nothing but framing: the caller leaves it out."""
        if not ev:
            return stored
        raw = ev.get("payload")
        try:
            p = json.loads(raw) if isinstance(raw, str) else (raw or {})
        except ValueError:
            return stored
        base = p.get("excerpt") or ""
        text = _spk.reader_text(p, actor=ev.get("actor") or "")
        if text == base:
            return stored
        return text if text.strip() else None

    def _retrieve_raw_inner(self, query, *, limit=20, principal=None, now=None,
                            exclude_automation=False, fts_match=None, lexical_only=False):
        principal = principal or self.active_principal
        q = self.query_understanding(query, embed=not lexical_only)
        scored: dict[str, dict] = {}
        # Fetched in widening pages and cut at `limit` ADMITTED rows, so rows
        # left out below (automation, nothing but host framing) do not cost a
        # real one its place -- however many of them rank first. With nothing
        # left out it is one fetch and exactly the first `limit` rows, as before.
        fetch = 2 * limit
        while True:
            # The two narrowing arguments only when they narrow: an explicit
            # search calls the store exactly as it always has.
            narrow = {}
            if fts_match is not None:
                narrow["match"] = fts_match
            if exclude_automation:
                narrow["exclude_session_prefixes"] = _spk.AUTOMATION_SESSION_PREFIXES
            fts_rows = self.store.fts_search_observed(query, limit=fetch, **narrow)
            scored = {}
            admitted = 0
            for i, r in enumerate(fts_rows):
                if admitted >= limit:
                    break
                ev = self.store.get_event(r["event_id"])
                if exclude_automation and self._from_automation(ev):
                    continue
                if ev and access.can_read(access.DEFAULT_ACL, ev["owner"], principal):
                    excerpt = self._reader_excerpt(ev, r["excerpt"])
                    if excerpt is None:
                        continue            # nothing but host framing
                    admitted += 1
                    scored.setdefault(r["event_id"], {"excerpt": excerpt, "score": 0.0,
                                                      "owner": ev["owner"]})["score"] += self._fts_w / (self._rrf_k + i + 1)
            if admitted >= limit or len(fts_rows) < fetch or fetch >= _FTS_FETCH_MAX:
                break
            fetch *= 4
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
            vec_heap: list[tuple] = []  # (score, seq, event_id, excerpt, owner) — min-heap on score
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
                self._note_wrong_dim_rows(q["embedding"], list(vrows.values()), "event_id", "raw")
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
                self._note_wrong_dim_table(q["embedding"], "observed_vectors",
                                           "event_id", "raw")
                for batch in self.store.iter_observed_vectors_paged(
                        batch_size=VECTOR_SCAN_PAGE, width=len(q["embedding"]) * 4):
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
                        if exclude_automation and self._from_automation(ev):
                            continue
                        p = json.loads(ev["payload"]) if ev and isinstance(ev["payload"], str) else (ev or {}).get("payload", {})
                        # Judged BEFORE it takes a top-k slot: an event that is
                        # nothing but host framing would otherwise displace a
                        # real turn and then be dropped, leaving the slot empty.
                        excerpt = self._reader_excerpt(ev, p.get("excerpt", ""))
                        if excerpt is None:
                            continue
                        entry = (contribution, seq, eid, excerpt, v.get("owner"))
                        seq += 1
                        if len(vec_heap) < limit:
                            heapq.heappush(vec_heap, entry)
                        else:
                            heapq.heapreplace(vec_heap, entry)
            for contribution, _seq, eid, excerpt, owner in vec_heap:
                scored[eid] = {"excerpt": excerpt, "score": contribution, "owner": owner}

            # Paged session-vector streaming, same bounded top-k treatment. Session
            # ids are namespaced "session:" so they never collide with event ids.
            sess_heap: list[tuple] = []  # (score, seq, session_id, summary, owner)
            seq = 0
            self._note_wrong_dim_table(q["embedding"], "session_index",
                                       "session_id", "session")
            for batch in self.store.iter_session_vectors_paged(
                    batch_size=VECTOR_SCAN_PAGE, width=len(q["embedding"]) * 4):
                for s in batch:
                    if not s.get("embedding"):
                        continue
                    if exclude_automation and _spk.is_automation_session(s.get("session_id")):
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
            proj_heap: list[tuple] = []  # (score, seq, proj_id, excerpt, owner)
            seq = 0
            self._note_wrong_dim_table(q["embedding"], "projection_vectors",
                                       "external_id", "projection")
            for batch in self.store.iter_projection_vectors_paged(
                    batch_size=VECTOR_SCAN_PAGE, width=len(q["embedding"]) * 4):
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

            # §H2.4 doc2query EXCERPT tier. A question-shaped query can match a
            # question generated from a raw span even when it shares nothing
            # with the span's own text — the same question->question trick E2
            # does for beliefs, applied where the parent is an event.
            #
            # Discounted by the same 0.5 the belief tier applies to
            # vector_proxy: a generated question is a synthetic signal, not
            # primary evidence, and here it competes directly against real
            # cosine contributions on an absolute (non-RRF) scale, where an
            # un-discounted proxy would simply outrank the span's own vector.
            # Bounded to `limit` parents, so the raw tier's streaming top-k
            # discipline still holds: at most `limit` entries can be added.
            if self.cfg is not None and self.cfg.get("embeddings.doc2query.excerpts", False):
                for eid, sim in self._observed_proxies(q["embedding"], limit):
                    contribution = self._vec_w * 0.5 * sim
                    if eid in scored:
                        scored[eid]["score"] += contribution
                        continue
                    ev = self.store.get_event(eid)
                    if not ev or not access.can_read(access.DEFAULT_ACL, ev["owner"], principal):
                        continue
                    p = json.loads(ev["payload"]) if isinstance(ev["payload"], str) \
                        else (ev["payload"] or {})
                    excerpt = self._reader_excerpt(ev, p.get("excerpt", ""))
                    if excerpt is None:
                        continue        # nothing but host framing
                    scored[eid] = {"excerpt": excerpt, "score": contribution,
                                   "owner": ev["owner"]}
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
        # A15: `scored` is a dict filled by the FTS pass, then a heap drain,
        # then optionally the ANN/session/projection/doc2query tiers, and a
        # bare `key=score` sort is STABLE — so equal-scoring candidates came
        # back in that filling order, i.e. in an implementation detail. Ordered
        # on the same (score desc, id asc) relation the precision gate breaks
        # its own ties with; see `_rank_key`.
        out.sort(key=_rank_key("event_id"))
        return out[:limit]

    # -- read-and-answer (§18.4, I23) -------------------------------------

    def answer(self, query, *, read_budget=4000, purpose="*", principal=None, now=None) -> dict:
        """Answer `query` (§18). Wrapper: opens the A0c wrong-dimension scope
        over BOTH tiers and stamps the per-query count into the debug field.

        `vectors_skipped_wrong_dim` counts DISTINCT stored vectors this query
        could not score because their blob width does not match the active
        embedder -- memory that was silently invisible before A0c. Non-zero
        means part of the store was written by a different embedding model;
        health's `vectors_wrong_dim` has the store-wide total and
        scripts/migrate_vectors.py is the fix."""
        with self._query_diagnostics() as seen:
            ans = self._answer_inner(query, read_budget=read_budget, purpose=purpose,
                                     principal=principal, now=now)
            dbg = ans.get("debug")
            dbg = dict(dbg) if isinstance(dbg, dict) else {}
            # NOT len(seen): `seen` is a bounded identity SAMPLE for the
            # width-filtered channels. The number is exact and comes from
            # `last_wrong_dim_skipped`.
            dbg["vectors_skipped_wrong_dim"] = self.last_wrong_dim_skipped()
            if seen:
                dbg["vectors_skipped_wrong_dim_detail"] = sorted(
                    ("%s:%s" % (ch, ident)) for ch, ident in seen)[:20]
            ans["debug"] = dbg
            return ans

    def _answer_inner(self, query, *, read_budget=4000, purpose="*", principal=None, now=None) -> dict:
        principal = principal or self.active_principal
        q = self.query_understanding(query)
        # E9 (§18.2): classification is read-only and never changes answer()'s
        # own behavior (routing only steers get_context's evidence assembly) --
        # it is exposed here purely as a debug field so a caller can see which
        # route a query took without having to call classify_route separately.
        route_info = self.classify_route(query, now=now)
        t1 = self.search(query, limit=10, purpose=purpose, principal=principal, now=now)
        top = t1[0]["score"] if t1 else 0.0

        # Geometric abstention (E10): abstain when the TRUE cosine distance
        # (1 - cosine similarity) between the query embedding and the top
        # candidate's OWN stored embedding exceeds retrieval.abstain_distance.
        # This is deliberately not `top` (the RRF fusion score computed above) —
        # RRF sums w/(k+rank) across the fts/vector/graph/structured channels
        # and is bounded near 0.02-0.05; it has no relationship to cosine
        # distance's [0, 2] geometric scale, so thresholding it would make the
        # config value meaningless. Inert (never abstains) when the threshold
        # is unset (default None), when there is no embedder (q["embedding"] is
        # None), or when the top candidate has no vector of its own to compare
        # against (fts/structured/graph-only hit, or embedding pruned).
        #
        # Coverage note (ladder-9 integration): the enabled path is unit-tested
        # against this branch, but there is no end-to-end test that drives a
        # threshold through answer() and asserts the abstention text a CALLER
        # sees. The default is None, so the untested surface is opt-in only;
        # add that test before recommending the knob to anyone.
        abstain_dist = self._abstain_distance()
        if abstain_dist is not None and t1 and q["embedding"]:
            best = t1[0]
            cand_blob = self.store.get_memory_vector(best["belief_id"], best["kind"])
            cand_emb = unpack(cand_blob) if cand_blob else []
            if cand_emb:
                distance = 1.0 - cosine(q["embedding"], cand_emb)
                if distance > abstain_dist:
                    self.store.log_retrieval(query, "*", top)
                    return {"answer": "", "abstain": True, "sources": [], "tier": 1, "confidence": 0.0,
                            "why": "no sufficiently close memory"}

        # Support gate (I8): ranking alone never says "no" — search() came back
        # non-empty on 30/30 unanswerable LongMemEval questions, which were then
        # answered at median confidence 0.600. Gate Tier 1 before the confident
        # path; see _support_gate and scripts/sweep_abstain.py.
        # A16, reconciled with upstream 7b83049. A belief may be READABLE
        # (`include_drafts`, default true, rendered `[DRAFT]`) and still be
        # unfit to back a CONFIDENT answer. Two questions, two keys -- see
        # config.confident_answer_from_drafts for why one key cannot serve both.
        # `status` is already on the candidate row (`_readable` reads it), so
        # the common path costs no query; `get_belief` is only a fallback for a
        # row that somehow lacks it, rather than upstream's per-candidate fetch.
        if not (self.cfg and bool(self.cfg.get("retrieval.confident_answer_from_drafts", False))):
            t1_active = []
            for _c in t1:
                _st = _c.get("status")
                if _st is None:
                    _st = (self.store.get_belief(_c["table"], _c["belief_id"]) or {}).get("status")
                if _st != "draft":
                    t1_active.append(_c)
        else:
            t1_active = t1
        supported = self._support_gate(t1_active, q)
        if supported and self._confident(t1_active):
            self.store.log_retrieval(query, "*", top)
            ans = self._answer_from_beliefs(t1_active, tier=1)
            ans["debug"] = route_info
            return ans

        t2 = self.retrieve_raw(query, principal=principal, now=now)
        # Lexical grounding: a raw span only counts as support if it shares a query
        # token (guards against spurious vector hits → false answers).
        focus = set(q["tokens"])
        t2 = [c for c in t2 if any(w in (c["excerpt"] or "").lower() for w in focus)]

        if not t1 and not t2:
            self.store.log_retrieval(query, "*", 0.0)
            return {"answer": "", "abstain": True, "sources": [], "tier": 0, "confidence": 0.0,
                    "why": "no_support", "debug": route_info}  # abstention (I8, B.3)

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
                        "why": "low_support", "debug": route_info}  # support exists but does not answer (I8, B.3)

        ans = self._read_and_extract(query, q, t1, t2, principal, read_budget)
        if ans.get("abstain") and not t1:
            self.store.log_retrieval(query, "*", 0.0)
            return {"answer": "", "abstain": True, "sources": [], "tier": 0, "confidence": 0.0,
                    "why": "no_support", "debug": route_info}
        if top < self._miss_threshold and t2:
            self.store.log_miss(query, "*", top)
            for cand in t2[:2]:
                if not cand["event_id"].startswith("session:"):
                    self.store.enqueue_curation("extract", {"event_id": cand["event_id"]})
        ans["debug"] = route_info
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

    def _promote_from_span(self, span, focus, principal) -> list[str]:
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

    def _pref_pack_fill(self, groups, parts, emitted_headers, seen_excerpts,
                        remaining_chars, *, principal, route, keep=None, live_session=None):
        """F5 preference packing's fill: every USER turn first, assistant halves last.

        Replaces BOTH of get_context's normal fill phases on the preference
        route, and has to, for one reason: the ordinary phase-1 loop is a
        single streaming pass that spends a group's whole share before it looks
        at the next group. That is right when the budget is 48 000 chars and
        wrong at 6 000, because the thing being rationed here is not "how much
        of session 1" but "did the user's own words from session 7 arrive at
        all" -- F3 measured a gold session at header rank 7 whose evidence turn
        never appeared, and another whose block carried 1 of its 7 user turns.

        Two passes, therefore, over ALL groups in relevance order: every
        group's user turns first, then every group's assistant halves with
        whatever survives. Lines accumulate in per-session buffers rather than
        straight into `parts` so a deferred assistant half lands back under its
        OWN session header instead of under whichever block happens to have
        been emitted last -- the one way a flat two-pass fill can silently
        mis-attribute a turn.

        The session-window widening happens up front, before any of it is
        packed, and head-splits the same way: a user turn the ranked top-20
        never surfaced is exactly what this route is short of, and it is ~200
        chars. Returns the unspent budget; mutates `parts`, `emitted_headers`
        and `seen_excerpts` in place, as the phases it stands in for do.
        """
        enable_window = self.cfg.get("context.session_window", True) if self.cfg else True
        max_sessions = _clamp_cfg(self.cfg, "context.session_window_max_sessions", 5, 1, 100)
        max_events = _clamp_cfg(self.cfg, "context.session_window_max_events", 60, 1, 1000)
        if enable_window:
            sessions_expanded = 0
            for g in groups:
                if sessions_expanded >= max_sessions:
                    break
                if g["sid"] == "(no session)":
                    continue
                expanded = self._expand_session_window(
                    g["sid"], principal, seen_excerpts, limit=max_events,
                    only_folded=bool(live_session) and g["sid"] == live_session)
                if keep is not None:
                    # the injection relevance gate (get_context passes it): given
                    # the row, the text to carry, or None to leave the turn out
                    expanded = [dict(x, excerpt=said) for x in expanded
                                for said in (keep(x),) if said is not None]
                if not expanded:
                    continue
                sessions_expanded += 1
                for exp in expanded:
                    excerpt = exp["excerpt"]
                    # E9 temporal route's per-excerpt date prefix cannot apply
                    # here (a query is one route, not two), but the branch is
                    # kept symmetrical with phase 2 so the two do not drift.
                    if route == "temporal" and exp.get("date"):
                        excerpt = "[{}] {}".format(exp["date"], excerpt)
                    head, tail = _split_lead_message(excerpt)
                    if head and head not in g["excerpts"]:
                        g["excerpts"].append(head)
                    if tail and tail not in g["tails"]:
                        g["tails"].append(tail)
                    seen_excerpts.add(excerpt)

        bufs: dict[str, list] = {}
        for key in ("excerpts", "tails"):
            for g in groups:
                if remaining_chars <= 0:
                    break
                sid = g["sid"]
                header = emitted_headers.get(sid) or "[SESSION {}{}]".format(
                    sid, " @ " + g["date"] if g["date"] else "")
                buf = bufs.get(sid)
                for excerpt in (g.get(key) or []):
                    if not excerpt:
                        continue
                    lead = 0 if buf is not None else len(header) + 1
                    if remaining_chars - (lead + len(excerpt) + 1) <= 0:
                        budget = remaining_chars - lead - 1
                        piece = _truncate_at_boundary(excerpt, budget) if budget > 0 else ""
                        if piece and _is_bare_role_prefix(piece):
                            piece = ""      # a role label with no turn behind it
                        if piece:
                            if buf is None:
                                buf = bufs[sid] = [header]
                                emitted_headers[sid] = header
                                remaining_chars -= len(header) + 1
                            buf.append(piece)
                            remaining_chars -= len(piece) + 1
                        break
                    if buf is None:
                        buf = bufs[sid] = [header]
                        emitted_headers[sid] = header
                        remaining_chars -= len(header) + 1
                    buf.append(excerpt)
                    remaining_chars -= len(excerpt) + 1
            if remaining_chars <= 0:
                break
        for g in groups:
            parts.extend(bufs.get(g["sid"]) or [])
        return remaining_chars

    def _expand_session_window(self, session_id: str, principal: str,
                               existing_excerpts: set, limit: int = 60,
                               around_seq=None, rank_order=None,
                               existing_event_ids=None, only_folded=False) -> list[dict]:
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

        E12 `around_seq` (+ optional `rank_order`, event ids in retrieval-score
        order): fetch the window CENTRED on that turn and return it in the order
        precision packing needs instead of the session's first `limit` turns in
        seq order. Only precision packing passes them, and the order matters
        there because that path spends a small budget on one session, so what it
        drops is decided here.

        THE ORDER IS AN INTERLEAVE of two streams, nearest-turn and best-ranked,
        because each alone loses a different half of the measured set:
          * by distance alone, a gold session whose evidence ranked 5th but sat
            one turn away is delivered (that turn is second) — but a session
            whose evidence ranked FIRST three turns away is not, because three
            long neighbours eat the budget first;
          * by rank alone, the reverse: relevance order spent an entire 1500-token
            budget on the four excerpts above an adjacent answer turn.
        Alternating gives each stream every other slot, so the evidence arrives
        within a couple of lines whichever shape it has — and neither ordering
        can starve the other. This also makes packing robust to which of two
        near-tied candidates happened to lead: the loser is the other stream's
        first pick. `None` (every other caller) reproduces exactly the query and
        ordering that were always here.

        F1 `existing_event_ids`: the ids the caller ALREADY packed. The excerpt
        set alone is a weak identity for "context already carries this turn" —
        it is exact string equality on text the caller may have decorated (the
        temporal route prefixes `[date] `), truncated at a budget boundary, or
        re-whitespaced, and any of those makes the leader's own turn read as
        new and get re-emitted immediately below itself. It is also the test the
        interleave's first-slot argument above depends on: the leader has to be
        filtered out here, or it occupies slot one of BOTH streams and the first
        pair of the interleave is spent re-printing it. An event id is the
        turn's actual identity, so it survives every one of those rewrites.
        Additive: excerpt-equality still applies, this is a second, stricter
        gate, and `None` (every caller that tracks no ids) behaves as before.
        """
        expanded: list[dict] = []
        if limit is not None and limit <= 0:
            return expanded
        since = 0
        if around_seq is not None and limit:
            # seq > since_seq is exclusive, so this window is
            # [around_seq - limit//2, around_seq + limit//2] give or take one.
            since = max(0, int(around_seq) - limit // 2 - 1)
        events = self.store.get_events_by_session(session_id, since_seq=since,
                                                  types=("observed",), limit=limit)
        for ev in events:
            if not access.can_read(access.DEFAULT_ACL, ev.get("owner"), principal):
                continue
            if existing_event_ids is not None and ev["event_id"] in existing_event_ids:
                continue
            p = json.loads(ev["payload"]) if isinstance(ev["payload"], str) else (ev["payload"] or {})
            if only_folded and p.get("source_type") != "context_eviction":
                continue                     # the live session: its window already has it
            excerpt = (self._reader_excerpt(ev, p.get("excerpt") or "") or "").strip()
            if not excerpt or excerpt in existing_excerpts:
                continue
            date = (ev.get("occurred_at") or "")[:16]
            expanded.append({"excerpt": excerpt, "date": date, "event_id": ev["event_id"],
                             "seq": ev.get("seq"), "payload": p, "actor": ev.get("actor") or ""})
            existing_excerpts.add(excerpt)
            if existing_event_ids is not None:
                existing_event_ids.add(ev["event_id"])
        if around_seq is not None:
            # Ordered AFTER the filter, not before, so the leading item — which
            # the caller already packed, and which is therefore filtered out
            # here — cannot occupy the first slot of both streams and waste the
            # first pair of the interleave on itself.
            by_dist = sorted(expanded, key=lambda e: (abs((e.get("seq") or 0) - int(around_seq)),
                                                      e.get("seq") or 0))
            rank_pos = {eid: i for i, eid in enumerate(rank_order or [])}
            by_rank = sorted((e for e in expanded if e["event_id"] in rank_pos),
                             key=lambda e: rank_pos[e["event_id"]])
            expanded, taken = [], set()
            for pair in zip_longest(by_dist, by_rank):
                for e in pair:
                    if e is not None and e["event_id"] not in taken:
                        taken.add(e["event_id"])
                        expanded.append(e)
        return expanded

    @staticmethod
    def _precision_tie_buckets(candidates):
        """F1: each candidate's TIE BUCKET — its score as a fraction of the
        pool's best, snapped to the `_PRECISION_TIE_EPS` grid. `None` when
        nothing in the pool scored, which has no relative grid to speak of.

        One function, because the ordering and the head boundary must agree on
        what "tied" means. When they disagreed (ordering by bucket, boundary by
        a raw-score epsilon around the fifth item) the head was decided by which
        member of a bucket happened to sort fifth: the raw scores inside one
        bucket are not sorted, so the "edge" score could be the smallest or the
        largest of the tie, and the head came out 5 long or 7 long from the same
        pool. Bucket equality is an equivalence relation — reflexive, symmetric,
        transitive — so a head extended over it cannot chain down the tail
        either, and it is a function of the SCORES alone: nothing about the id
        tiebreak can reach it.
        """
        ref = 0.0
        for c in candidates:
            s = float(c.get("score") or 0.0)
            if s > ref:
                ref = s
        if ref <= 0.0:
            return None
        return [round(float(c.get("score") or 0.0) / ref / _PRECISION_TIE_EPS)
                for c in candidates]

    @staticmethod
    def _precision_order(candidates):
        """F1: the candidate order the precision gate and its packing read.

        `retrieve_raw` sorts by raw float score and nothing else, so candidates
        that scored the SAME come back in whatever order `scored`'s dict
        happened to be filled in — an FTS pass followed by a heap drain, i.e. an
        implementation detail. Everything downstream then inherits it: which
        item is the leader (and the gate refuses outright when the leader and
        the crowd disagree), which items fall inside the head, which turns the
        rank stream of the packing interleave picks first.

        So order on a QUANTIZED score instead (`_precision_tie_buckets`), and
        break bucket ties by event id — which is a content hash of the event
        (type, payload, actor, occurred_at), so the same recorded turn keeps the
        same id across a replay of one log, where insertion order does not.
        (A15b: across a RE-RECORDING of the same turns it does not, because
        `occurred_at` is hashed too — `_rank_key` has the whole statement.)

        The grid has edges, and a score sitting on one would cross it if scores
        ever moved; what this buys is that the ORDERING and the HEAD BOUNDARY
        share that edge (both read `_precision_tie_buckets`), so they can never
        disagree about which candidates are tied.

        A15: the id half of this relation is now `_rank_key`, and `retrieve_raw`
        / `search` / `_rerank` break their own ties with it — so the pool this
        gate is handed no longer arrives in one order and get re-read in
        another. The BUCKET half stays here: quantizing is what the gate needs
        and what user-visible ranking must not have.

        NOT a change to user-visible ranking: `retrieve_raw` and `search` keep
        returning what they always returned. This ordering is applied only
        where the gate and precision packing consume the pool, and precision
        packing emits exactly one phase-1 line, so on the queries the gate
        refuses (every query in a tree without an embedder, and every query
        that does not converge) nothing downstream sees it at all.
        """
        buckets = RetrievalEngine._precision_tie_buckets(candidates)
        if buckets is None:
            # No positive score to normalise against: there is no meaningful
            # relative grid, and the gate refuses this pool anyway. Sort by id
            # alone so the result is still deterministic.
            return sorted(candidates, key=lambda c: str(c.get("event_id") or ""))
        order = sorted(range(len(candidates)),
                       key=lambda i: (-buckets[i], str(candidates[i].get("event_id") or "")))
        return [candidates[i] for i in order]

    @staticmethod
    def _precision_head(ordered):
        """F1: the head the modal share is measured over — TIE-AWARE.

        A fixed `[:5]` cut is the gate's most order-sensitive line: it converts
        a rank into a fifth of the modal share, and `context.precision_concentration`
        (0.60) sits between 3/5 and 4/5, so a single candidate moving across the
        cut can decide the query. When the two candidates either side of it hold
        the same score, that decision has no basis in the scores at all —
        measured on this suite's own dominant fixture, whose ranks 5, 6 and 7
        are three bulk turns agreeing to better than a thousandth: whichever of
        them sorted fifth became the boundary, and the head came out 5 long or 7
        long from a pool that was identical every time.

        Extending the head over the tie makes the boundary unable to express
        that choice: every member of the boundary's bucket is counted, so the
        share is a function of the scores and of nothing else.

        Note what this does NOT claim. The extended share is not systematically
        lower (or higher) than the fixed cut's — on a head of four evidence
        turns plus a tied {evidence, other} pair, the lottery returns 5/5 = 1.00
        or 4/5 = 0.80 depending on the draw and the extension returns 5/6 = 0.83
        for both, which is below one and above the other. The claim is only that
        it returns ONE number. Some queries near the threshold will therefore
        settle on the refusing side, and settling is the point —
        `context.precision_concentration` is a measured threshold, and a
        measurement it can be compared against has to be repeatable first.

        A pool shorter than `_PRECISION_HEAD` still returns short and is still
        refused by the caller; the extension itself is bounded by the pool.

        `ordered` must be in `_precision_order` order — the boundary is drawn
        on the SAME buckets that ordering used, which is what stops the two from
        disagreeing about who is tied with whom.
        """
        head = list(ordered[:_PRECISION_HEAD])
        if len(head) < _PRECISION_HEAD:
            return head
        buckets = RetrievalEngine._precision_tie_buckets(ordered)
        if buckets is None:
            return head
        edge = buckets[_PRECISION_HEAD - 1]
        for i in range(_PRECISION_HEAD, len(ordered)):
            # `ordered` is bucket-descending, so the first candidate in a lower
            # bucket ends the run: nothing behind it can be in the edge's.
            if buckets[i] != edge:
                break
            head.append(ordered[i])
        return head

    def _precision_decision(self, candidates):
        """E12: has retrieval CONVERGED ON ONE SESSION for this query?

        Returns None (no convergence -> full budget, today's behavior) or
        {"sid", "event_id", "seq", "concentration", "margin"} naming the session
        to deliver and the item inside it that leads.

        THE SIGNAL IS SESSION CONCENTRATION OF THE HEAD, not the leader's score
        margin. Measured, and this is the whole point of the E12 fix: on the six
        LongMemEval single-session-user questions this feature exists for (real
        nomic), the leader's relative margin over the runner-up is 0.02-0.16 --
        indistinguishable from the crowded multi-evidence questions, whose
        margins run to 0.46 on the ctx_eval corpus. A margin gate set high
        enough to be safe on the second set never fires on the first, and set
        low enough to fire on the first it drops evidence on the second (-6.9 to
        -12.1 ctx_eval points, measured). Margin is simply not the variable that
        separates them.

        What does separate them is WHERE the head comes from. The top five raw
        candidates of a single-evidence question pile into one session (modal
        share 0.8-1.0 on four of the six); the multi-evidence ones spread
        across the haystack (0.2-0.4 for twenty of the thirty factual ctx_eval
        queries, and 0.8 only once). That is the same fact the question type states:
        the answer lives in ONE session, and a converged retrieval says so by
        putting its whole head there.

        So dominance here is a property of the head, not of one row: the modal
        session must hold at least `context.precision_concentration` of the top
        `_PRECISION_HEAD` candidates. `context.precision_margin` is a SECONDARY
        tightening dial on top (default 0.0 = no extra requirement) -- see the
        config comment for why a non-zero default would be measurably wrong.

        CONSERVATIVE BY CONSTRUCTION -- every ambiguity resolves to None:
          * a pool that cannot even fill the head: concentration over fewer than
            `_PRECISION_HEAD` candidates is an artifact of a short pool, not a
            measurement of where retrieval converged;
          * a pool that only knows ONE session: "converged on one session" is a
            statement about a choice between sessions, and a pool with no
            alternative never made one. (This is not a corner case: it is every
            small or single-session store, where cutting the budget would be
            decided by the store's shape rather than by the query's evidence.)
          * a non-positive leading score, or a modal share below the threshold;
          * a leader outside the modal session — the crowd and the best hit
            disagree about where the answer is. (This also covers a leader the
            store cannot resolve to a session at all, including a `proj:`
            projection pointer: no session means it can never be the modal
            one.)
          * a leader that is a `session:<id>` summary row or has no excerpt: a
            summary is a POINTER to a body of evidence rather than evidence, so
            it can raise its session's concentration but can never lead the
            context that session gets.

        F1: `candidates` is expected in `_precision_order` order (get_context
        hands it down that way), and the head boundary is TIE-AWARE — see
        `_precision_head`. Both exist so that this decision is a function of the
        evidence and not of the embedding service's last significant digit.
        A caller that passes raw `retrieve_raw` order still gets a correct
        answer: the ordering is re-applied here, so the two entry points cannot
        disagree.

        F1 also drops a `principal` parameter nothing read. There is no ACL
        re-check here for the same reason there is no status re-check:
        `retrieve_raw` cleared every candidate in this pool for the calling
        principal before returning it. That was the whole content of the
        parameter — an argument, not an input — and an argument belongs in the
        docstring, where it is true, rather than in a signature that implies
        the code consults it.
        """
        ordered = self._precision_order(candidates)
        head = self._precision_head(ordered)
        if len(head) < _PRECISION_HEAD:
            return None
        if float(head[0].get("score") or 0.0) <= 0.0:
            return None
        # Session of each head candidate. A `session:<id>` row belongs to the
        # session it summarises; a projection pointer belongs to none, and
        # counts only against the concentration.
        sids, events = [], []
        for c in head:
            eid = c.get("event_id") or ""
            if eid.startswith("session:"):
                sids.append(eid.split(":", 1)[1])
                events.append({})
            elif eid.startswith("proj:") or not eid:
                sids.append(None)
                events.append({})
            else:
                ev = self.store.get_event(eid) or {}
                sids.append(ev.get("session_id"))
                events.append(ev)
        counts: dict = {}
        for s in sids:
            if s:
                counts[s] = counts.get(s, 0) + 1
        if not counts:
            return None
        # Was there anything to converge AWAY from? Read over the whole pool,
        # not the head: a head that is one session because the store only has
        # one session measures the store, not the query.
        pool_sessions = set()
        for c in candidates:
            eid = c.get("event_id") or ""
            if eid.startswith("session:"):
                pool_sessions.add(eid.split(":", 1)[1])
            elif eid and not eid.startswith("proj:"):
                s = (self.store.get_event(eid) or {}).get("session_id")
                if s:
                    pool_sessions.add(s)
        if len(pool_sessions) < 2:
            return None
        # max() over a dict is order-dependent on ties; break them by the
        # `_precision_order` position the candidates arrived in, which is the
        # only ordering here that means anything (and, since F1, the only one
        # that means the same thing twice).
        best = max(counts.values())
        modal = next(s for s in sids if s and counts[s] == best)
        concentration = best / float(len(head))
        if concentration < self._precision_concentration():
            return None
        # THE LEADER MUST AGREE WITH THE CROWD. A head whose best hit sits
        # OUTSIDE the session the rest of the head converged on is two competing
        # claims on the answer, not one — and it is measurably the failure case:
        # on the ctx_eval corpus, requiring this drops the firing set from 10
        # queries to 5 and the evidence losses from 4 to 1, while every one of
        # the motivating single-session questions keeps firing (their leader is
        # always inside their modal session). It also makes "evidence first"
        # unambiguous: the item that leads the packed context is the same item
        # that led the ranking.
        if sids[0] != modal:
            return None
        top = head[0]
        eid = top.get("event_id") or ""
        # A `session:<id>` summary row CAN carry its own session's id into
        # `sids`, so it can reach here as the "leader" of the modal session
        # while being a pointer rather than a turn; an excerpt-less row cannot
        # lead a context either. (A `proj:` pointer or an id the store cannot
        # resolve never gets this far: its `sids` entry is None, which the
        # leader-agrees test above already refused. On why no ACL re-check
        # happens here, see the docstring's last paragraph.)
        if eid.startswith(("session:", "proj:")) or not (top.get("excerpt") or "").strip():
            return None
        ev = events[0]
        s0 = float(head[0].get("score") or 0.0)
        s1 = float(head[1].get("score") or 0.0)
        # Floored at zero (F1). The head is ordered by QUANTIZED score, so two
        # candidates inside one `_PRECISION_TIE_EPS` bucket are ordered by id —
        # and then the runner-up's RAW score can be a hair above the leader's,
        # making this difference negative. A negative lead is not a measurement,
        # it is the sign of the noise the bucket exists to ignore: the honest
        # reading of "the leader's lead over a candidate it is tied with" is
        # none. Left unfloored it would also be a silent gate flip, because the
        # default `context.precision_margin` is 0.0 and `margin < 0.0` is the
        # one way that default can refuse anything.
        margin = max(0.0, (s0 - s1) / s0) if s0 > 0 else 0.0
        if margin < self._precision_margin():
            return None
        # F2X SUPERSEDE-CHAIN VETO. Last, so the cheap refusals above spend no
        # lookups: only a pool that would otherwise be CUT pays for this.
        if self._head_has_live_update(head):
            return None
        return {"sid": modal, "event_id": eid, "seq": ev.get("seq"),
                "concentration": concentration, "margin": margin}

    def _head_has_live_update(self, head):
        """F2X: does the store already know of a LATER value for something the
        head asserts? If so the precision cut must not happen.

        WHY THIS IS A SAFETY CONDITION AND NOT A TUNING DIAL. Precision packing
        does two things at once: it drops every session but the modal one, and
        it skips the ranked-belief block entirely. That block is the ONLY place
        E4's `[history: A (date) -> B (date)]` annotation is ever rendered
        (get_context's tier-1 loop). So when a fact in the packed evidence has a
        recorded supersede candidate, the cut removes BOTH channels that could
        tell a reader an update exists: the annotation, and the session the
        newer value was said in. What reaches the reader is the pre-update value
        alone, presented as the only value there is.

        Measured, on the instance this exists for (LongMemEval 07741c44, "Where
        do I initially keep my old sneakers?", real nomic): the cut delivered
        5,904 chars from the ORIGINAL session with no reference anywhere to the
        later change, and a reader that answered correctly at full budget
        answered "I don't know". The question's whole semantics ("initially")
        turn on a contrast with a state the cut had deleted.

        SCOPE IS THE MEASURED HEAD, NOT THE LEADER ALONE. The obvious version of
        this veto -- resolve the LEADING candidate's beliefs -- was implemented
        and measured first, and it does not fire on 07741c44: the leader's only
        derived belief has no chain, while the head's fifth member's does. That
        is not a near miss to be papered over, it is the correct scope showing
        itself. The gate's claim is about the HEAD ("the modal session holds at
        least `precision_concentration` of the top candidates"), so the veto has
        to read the same pool the claim was made over; a veto that inspects less
        than the gate inspects can be confidently wrong about the very pool the
        gate just approved.

        HONEST ABOUT WHAT THE SIGNAL IS. This asks "does the store hold a live
        update edge touching this head", not "is THAT edge the answer to THIS
        query". On 07741c44 the edge that trips it is a conversational reword
        ("great idea" -> "excellent idea") in the same session pair as the
        sneaker update, not the sneaker fact itself. The rule is still the right
        rule -- a head carrying recorded updates is a head whose session was
        revisited, which is exactly when deleting the other sessions is unsafe
        -- but it is a COARSE detector, and it is refusing to cut rather than
        claiming to have understood the update.

        FALSE-POSITIVE COST, MEASURED. Zero on both gate corpora: E4's default
        `curation.supersede_similarity` (0.82) is dormant under the hashing
        embedder the recall/ctx_eval harnesses run, so no edge exists there to
        trip on, and none of the 5 ctx_eval instances that precision-pack is
        touched. Zero on the population E12 exists for: all six LongMemEval
        single-session-user questions, re-probed under real nomic, have no live
        chain anywhere in their head (`f2xwork/chainscope.py`).

        Conservative in the same direction as every other test in
        `_precision_decision`: the answer to "is this ambiguous?" is None, and
        None is the full-budget path that predates E12 entirely.
        """
        for c in head:
            eid = c.get("event_id") or ""
            # A `session:` summary or `proj:` pointer is not an event and has no
            # justified beliefs to look up; `get_dependents` on either would
            # simply return nothing, so this skip is cost, not semantics.
            if not eid or eid.startswith(("session:", "proj:")):
                continue
            for j in self.store.get_dependents(eid):
                if j.get("support_kind") != "event":
                    continue
                # `get_supersede_chain` returns [] for a belief with no edges --
                # including every non-fact belief and every store where E4 never
                # fired -- so this is one indexed lookup on the common path.
                if len(self.store.get_supersede_chain(j["belief_id"])) > 1:
                    return True
        return False

    def _precision_concentration(self):
        """Minimum share of the top-`_PRECISION_HEAD` raw candidates that must
        come from one session before get_context cuts to the precision budget.
        See config's context.precision_concentration for the measured basis;
        1.0 demands unanimity, and anything at or below 1/`_PRECISION_HEAD` is
        met by every pool (the off-switch for the conservatism, not the
        feature)."""
        return _clamp_cfg_float(self.cfg, "context.precision_concentration", 0.60, 0.0, 1.0)

    def _precision_margin(self):
        """SECONDARY condition: extra lead the leading candidate must hold over
        the runner-up, on top of session concentration. Default 0.0 (no extra
        requirement) because measurement says a margin floor high enough to
        matter excludes exactly the questions this feature is for -- see the
        config comment. Raising it tightens the gate; 1.0 makes it inert."""
        return _clamp_cfg_float(self.cfg, "context.precision_margin", 0.0, 0.0, 1.0)

    def get_context(self, hint, *, token_budget=1500, include_directives=True, purpose="*",
                    principal=None, epistemic=None, now=None, exclude_automation=False,
                    relevance_gate=False, live_session=None) -> str:
        """Assemble a reader-facing context block (§18). Wrapper for the A0c
        wrong-dimension scope; the body is `_get_context_inner`, and the count
        lands in `last_context_debug["vectors_skipped_wrong_dim"]`."""
        with self._query_diagnostics():
            out = self._get_context_inner(hint, token_budget=token_budget,
                                          include_directives=include_directives, purpose=purpose,
                                          principal=principal, epistemic=epistemic, now=now,
                                          exclude_automation=exclude_automation,
                                          relevance_gate=relevance_gate, live_session=live_session)
            if relevance_gate:
                # Put into a turn unasked: never a credential's value (the
                # agent's own search still finds the message that held it).
                out = _cred.redact(out)
            if isinstance(self.last_context_debug, dict):
                # exact count, not the bounded identity sample -- see answer()
                self.last_context_debug["vectors_skipped_wrong_dim"] = \
                    self.last_wrong_dim_skipped()
            return out

    def _get_context_inner(self, hint, *, token_budget=1500, include_directives=True, purpose="*",
                           principal=None, epistemic=None, now=None, exclude_automation=False,
                           relevance_gate=False, live_session=None) -> str:
        """Assemble a reader-facing context block for `hint` (§18).

        §L8 r1 priority rule, enforced STRUCTURALLY, not by convention: raw
        evidence — Tier-1 ranked beliefs (facts/notes/episodes most relevant to
        the hint) and Tier-2 raw session excerpts — is written FIRST and claims
        the budget before anything else is even attempted. Directives, open
        contradictions, critical facts, entity digests, and federated rows are
        a CAPPED TAIL assembled only from whatever budget the evidence left
        over.

        The ordering is load-bearing, not cosmetic (measured, L8 diagnosis): a
        judged reader (gpt-4o) given the OLD directive-first ordering abstained
        on 30/30 questions even when the answer was present later in the SAME
        12k-token context — a document that leads with ~20 unrelated
        [DIRECTIVE] lines reads as "this is a list of reminders", and evidence
        buried after it goes unused even though it is technically present. The
        same reader given a short slice containing only the evidence answered
        correctly. So this is a fix to what a reader encounters first, not
        (only) to the byte budget.

        The byte budget matters too, though: the old unconditional directive
        block was also never itself checked against token_budget, so a big
        enough directive set could exhaust max_chars before evidence was even
        attempted, and the final blind ctx[:max_chars] truncation could then
        cut evidence entirely rather than the noise that crowded it out.
        Directives are therefore also capped by COUNT (context.max_directives,
        default 5 — the old block took the first 20 always_inject rows in
        store order, uncapped in config), and directives + open contradictions
        + critical facts combined may never claim more than ~15% of max_chars,
        however much is left over.

        A10 -- THE BUDGET IS NOW HONEST, in three ways it was not:

        1. ONE estimator. `max_chars` was `token_budget * 4` while every
           consumer of this output (context.py's compress()/rehydration, the
           checkpoint digest cap, every test that checks a budget) counted
           tokens as `estimate_tokens`. So `get_context(1500)` returned up
           to 6000 chars and the caller that asked for 1500 then hard-cut it.
           Both sides now go through `budget_chars`/`estimate_tokens`
           (engine.embeddings), exact inverses of ONE estimate -- see the
           measured basis note there. The emitted block therefore satisfies
           `estimate_tokens(ctx) <= token_budget`, which is what the
           parameter has always claimed and never guaranteed.

           A10b: this site converts under the CONTEXT_BUDGET margin, i.e.
           NO headroom. A10 shipped one estimator but priced a safety margin
           into it (chars/3), so a 12k-token caller was handed ~36 000 chars
           where ~48 000 fit -- the budget was honest about its own units and
           still a third short of what was asked for. The margin that a hard
           model boundary genuinely needs now lives at that boundary
           (EMBED_INPUT), not in every caller's evidence budget.

        2. THE TIER-1 BLOCK IS BUDGETED. It was explicitly "unbudgeted here"
           (limit=10 was the only bound), so ten long belief renders could
           exhaust and overrun the budget before the raw fill was reached --
           and the blind final cut then bisected whichever belief straddled
           the boundary. It now stops at the first line that does not fit,
           which is also what makes (3) unreachable in practice.

        3. THE FINAL CUT DROPS WHOLE UNITS. `ctx[:max_chars]` bisected a
           belief line or an excerpt mid-word and said only "(truncated)",
           naming neither what was lost nor how much. `_fit_units` drops
           whole rendered lines from the tail and REPORTS THE COUNT, so a
           reader is never handed half a fact rendered as if it were a fact.

        `last_context_debug["token_budget"]` / `["used_tokens"]` are computed
        with that same estimator, so the numbers a caller reads describe the
        bytes it was actually handed.
        """
        principal = principal or self.active_principal
        # A10: one estimator. `budget_chars` is `estimate_tokens`'s exact
        # inverse, so `len(ctx) <= max_chars` IS `estimate_tokens(ctx) <=
        # token_budget` -- there is no second ratio left to disagree with it.
        budget_tokens = max(0, int(token_budget))
        max_chars = budget_chars(budget_tokens, margin=CONTEXT_BUDGET)
        max_directives = _clamp_cfg(self.cfg, "context.max_directives", 5, 0, 500)
        parts: list[str] = []

        # The injection relevance gate (see `_GATE_FILLER`). None = off, and
        # then every helper below is the identity: explicit callers are
        # byte-for-byte what they were. On, every evidence line and every tail
        # line must share a content word with `hint`; a hint with no content
        # words gets nothing, and the retrieval work is not even started.
        if relevance_gate:
            hint = gate_focus(hint)          # a long prompt: its most telling words
        gate = relevance_words(hint) if relevance_gate else None
        gate_drop = {"beliefs": 0, "excerpts": 0, "tail": 0}

        # (Its own name: `need` is reused below for character budgets, and a
        # closure reads the variable, not the value it had here.)
        gate_need = gate_needs(gate) if gate is not None else 0

        floor = self._one_word_floor() if gate is not None else None
        query_vec: list = []                 # embedded on first need, at most once
        embeds = {"deadline": None, "items": 0, "made": {}}   # made: this turn's, by item

        def _embed(text, as_query):
            """One gate request, inside this turn's shared time budget."""
            now = _time_monotonic()
            if embeds["deadline"] is None:
                embeds["deadline"] = now + _GATE_EMBED_BUDGET
            left = embeds["deadline"] - now
            if left <= 0.05:
                return None
            return self._gate_vector(text, as_query, min(_GATE_EMBED_TIMEOUT, left))

        def _close_enough(ref, word, text):
            """A ONE-word match: kept when the item is near the message in
            meaning (see retrieval.prefetch_min_similarity) -- its stored vector,
            or, for a short item with none of this model, its text embedded now
            (a few per turn). With no floor (an unmeasured model) the word rule
            stands; with one, a match nothing can vouch for -- the embedder busy
            or down, a long item never embedded -- is left out: on the
            production store 71 of 75 one-word matches were coincidences, and
            a busy embedder used to let every one of them back in."""
            if floor is None:
                return True
            if not query_vec:
                query_vec.append(_embed(hint, True))
            q = query_vec[0]
            vec = self._gate_stored_vector(ref) if q else None
            key = ref if ref and ref[1] else text
            if q and (not vec or len(vec) != len(q)):
                vec = embeds["made"].get(key)
                if vec is None and len(text) <= _GATE_EMBED_ITEM_CHARS and embeds["items"] < _GATE_EMBED_ITEMS:
                    embeds["items"] += 1
                    vec = embeds["made"][key] = _embed(text, False)
            if not vec or len(vec) != len(q or ()):
                gate_drop.setdefault("one_word", []).append(
                    {"word": word, "similarity": None, "kept": False, "text": text[:80],
                     "why": "no vector" if q else "no query vector"})
                return False
            sim = cosine(q, vec)
            gate_drop.setdefault("one_word", []).append(
                {"word": word, "similarity": round(sim, 3), "kept": sim >= floor, "text": text[:80]})
            return sim >= floor

        def _relevant(text, kind, ref=None):
            if gate is None:
                return True
            shared = shared_content_words(gate, text)
            if len(shared) >= gate_need and (len(shared) > 1 or _close_enough(ref, next(iter(shared)), text)):
                return True
            gate_drop[kind] += 1
            return False

        metas: dict = {}

        def _said(row):
            """A raw row's text as the gated injection carries it, or None to
            leave it out. What was SAID: not a tool's output (a file read that
            mentions "calendar" is not about the user's calendar), not the
            agent's own memory (see _AGENT_OWN_SOURCES), and not the unlabelled
            opening of a later chunk of a long turn -- it starts mid-message,
            and on the production store 473 of the 651 interactive transcript
            events were such chunks, stored without spans that could say whose
            words they are."""
            eid = row.get("event_id")
            if isinstance(row.get("payload"), dict):     # the session window already read it
                p = row["payload"]
                meta = {"payload": p, "actor": row.get("actor") or "",
                        "source_type": p.get("source_type") or "", "chunk_index": p.get("chunk_index")}
            else:
                if eid not in metas:
                    metas[eid] = self._event_meta(eid)
                meta = metas[eid]
            if meta.get("source_type") in _AGENT_OWN_SOURCES:
                gate_drop["excerpts"] += 1
                return None
            later_chunk = (meta.get("source_type") == "session_transcript"
                           and (meta.get("chunk_index") or 0) > 0)
            if meta.get("payload") is not None:
                # From the event itself: its spans are what say which lines are
                # a tool's (an evicted tool result has no label to go by) and
                # which "User:" lines are really the user.
                said = _spk.reader_text(meta["payload"], actor=meta.get("actor") or "",
                                        drop_tools=True, drop_unlabeled=later_chunk)
            else:
                said = _spk.strip_framing(row.get("excerpt") or "", drop_tools=True,
                                          drop_unlabeled=later_chunk)
            if not said.strip() or not _relevant(_users_part(said, meta), "excerpts", ("event", eid)):
                return None
            return said

        def _users_part(said, meta):
            """What the USER said in an excerpt: the gate asks it, not the
            assistant's replies. A briefing or a status report shares a word
            with almost anything, and on the production store such replies
            filled the block for a question they had nothing to do with. The
            excerpt is still shown whole -- the reply is context for what the
            user said. An unlabelled excerpt is one message, whoever wrote it."""
            lead = _spk.HUMAN if (meta.get("actor") or "") == "user" else _spk.UNKNOWN
            return _spk.human_text(_spk.parse_labeled(said, _spk.HUMAN, lead))

        # The gate keeps only rows that share a content word, so FTS is asked
        # for exactly those (relevance_fts_match); None = the ordinary query.
        fts_match = relevance_fts_match(hint) if gate else None
        # ...and it runs no embedding at all. Measured on the production store
        # with the embedder live: the same three gated blocks, line for line,
        # with and without the vector channels -- the gate keeps only items that
        # share a content word, and FTS already finds those -- at 7.4 / 4.1 /
        # 1.1 s with vectors and 2.0 / 2.5 / 0.2 s without. The query embed is a
        # request to a CPU-bound server inside the user's turn.
        lexical = gate is not None

        def _raw(limit):
            rows = self.retrieve_raw(hint, limit=limit, principal=principal, now=now,
                                     exclude_automation=exclude_automation, fts_match=fts_match,
                                     lexical_only=lexical)
            if gate is None:
                return rows
            kept = []
            for r in rows:
                said = _said(r)
                if said is None:
                    continue
                if said is not r.get("excerpt"):
                    r = dict(r, excerpt=said)
                if (r.get("event_id") or "").startswith("session:"):
                    # A session-channel row's excerpt is the WHOLE session: one
                    # matching turn would carry every unrelated one with it. It
                    # nominates the session; the session window below then
                    # contributes that session's turns one by one, each gated.
                    r = dict(r, excerpt="")
                kept.append(r)
            return kept

        if gate is not None and not gate:
            self.last_context_debug = {
                "route": None, "precision": False, "pref_pack": False, "breadth_floor": None,
                "token_budget": budget_tokens, "used_tokens": 0,
                "relevance_gate": {"words": [], **gate_drop}}
            return self._emit("", max_chars, budget_tokens)

        # E9 (§18.2): route the hint through nearest-centroid classification.
        # "factual" (no embedder, routing disabled, or simply the nearest
        # match) takes none of the branches below and reproduces today's
        # get_context byte-for-byte -- the acceptance bar for this task.
        # The gated per-turn path is LEXICAL (see `lexical` below): routing
        # embeds the message to find its nearest centroid, so it is skipped and
        # the default route taken -- the per-turn block is short and plain.
        route_info = ({"route": "factual", "scores": {}} if gate is not None
                      else self.classify_route(hint, now=now))
        route = route_info["route"]

        # -- E12 PRECISION PACKING (§issue-8) ---------------------------------
        # Measured (stratified-250, real nomic, judged gpt-4o reader): on
        # single-evidence factual questions, contexts that make the reader
        # ABSTAIN at a 12k budget are answered correctly when cut to ~1k of the
        # SAME items' head — evidence position unchanged. The reader's
        # abstention tracks context VOLUME, not evidence quality. So when
        # Chronicle can tell which item answers the question, it should deliver
        # that item and stop.
        #
        # "Can tell" is two independent signals, both required:
        #   1. the query is the KIND this holds for — a factual question (E9
        #      route). Aggregation/temporal/preference questions are answered by
        #      surveying many items; cutting to one is the wrong move there by
        #      construction, so those routes never take this path.
        #
        #      F2X TRUE-ARGMAX GATE: `route == "factual"` alone is NOT that
        #      condition. E9's margin gate sends any winner that fails to beat
        #      factual by `retrieval.query_routing_margin` back to "factual", so
        #      the string conflates "factual is the nearest centroid" with
        #      "nothing else was convincing enough, so factual by default". The
        #      first is the signal E12 was measured on; the second is the
        #      absence of a signal, and reading it as the first is how a
        #      multi-session cost comparison got cut to one session and answered
        #      confidently where the full context had correctly abstained
        #      (LongMemEval 09ba9854, real nomic: preference 0.448 was the true
        #      argmax, factual 0.373 the lowest of the four, and the margin
        #      default handed it to E12 anyway; 47,992 chars -> 5,997, and a
        #      reader that had said "I don't know" produced a fare breakdown).
        #      So require the RAW geometry to name factual too (`_raw_route`).
        #      This is strictly a narrowing of E12 and touches E9 not at all:
        #      the route string, the margin, and every other consumer of it are
        #      unchanged, and a tree with no routing signal at all (empty
        #      `scores`) is byte-identical to today because `_raw_route` returns
        #      "factual" for it.
        #   2. retrieval CONVERGED ON ONE SESSION — the modal session of the
        #      top-5 raw candidates holds at least context.precision_concentration
        #      of them (_precision_decision). That, not the leader's score
        #      margin, is what separates single-evidence questions from crowded
        #      ones in measurement. It is a signal only a vector channel
        #      produces: with no embedder the head is FTS rank order, where
        #      "which session did retrieval converge on" is not a question the
        #      scores can answer. No embedder is therefore not a degraded gate —
        #      it is no gate, i.e. full budget, byte-identical to today (I18).
        #
        # The probe is the SAME retrieve_raw call the raw fill below makes
        # (limit=20, no per-session cap — guaranteed by the factual route), so
        # deciding this costs no extra retrieval: the rows are handed down to
        # phase 1 rather than fetched twice.
        precision_on = self.cfg.get("context.precision_packing", True) if self.cfg else True
        precision = None
        raw_probe = None
        # F1: the same pool in the jitter-stable order the gate reads (see
        # `_precision_order`). Kept alongside `raw_probe` rather than replacing
        # it, because it must not reach the full-budget path: phase 1 below
        # iterates `raw_probe` in retrieve_raw's own order on every query the
        # gate refuses, which is what keeps those contexts byte-identical to a
        # tree without this feature. It is consumed ONLY when precision fires,
        # where phase 1 emits a single line and the order feeds the packing
        # interleave's rank stream.
        precision_order = None
        if (precision_on and route == "factual"
                and self._raw_route(route_info.get("scores") or {}) == "factual"
                and self.embedder is not None and gate is None):
            raw_probe = _raw(20)
            precision_order = self._precision_order(raw_probe)
            precision = self._precision_decision(precision_order)
        if precision:
            # Never MORE than the caller asked for: precision packing is a
            # reduction, so a caller who already asked for less than the
            # precision budget keeps their own tighter budget.
            budget_tokens = min(budget_tokens,
                                _clamp_cfg(self.cfg, "context.precision_budget", 1500, 1, 1000000))
            max_chars = budget_chars(budget_tokens, margin=CONTEXT_BUDGET)

        # -- F5 PREFERENCE PACKING --------------------------------------------
        # The preference route's mirror of E12, and it exists because the two
        # routes fail for opposite reasons. E12 cuts a factual question to ONE
        # session because one item answers it. A preference question is not
        # answered by any item in memory at all: the memory holds the user's
        # stated taste and the answer has to be built on it, so what the reader
        # needs is EVERY first-person thing this user said, not one turn.
        #
        # Measured (F3 §4c, eight real 12k-budget contexts): 73-91% of a packed
        # preference context is ASSISTANT prose, and only the user's half of an
        # excerpt can carry a preference. The worst case is the one E12 already
        # cut to 1500 tokens -- 5 471 of its 5 994 chars were a generic recipe
        # list, delivering 3 of the gold session's 9 user turns. Dropping the
        # assistant halves fits all 9 in ~1 223 chars.
        #
        # So this cuts the budget and then spends it on user turns first,
        # assistant halves last -- measured after the change, the packed
        # contexts are 94-95% user text where they were 6-17%.
        #
        # Unlike E12 it needs no CONVERGENCE gate, and the reason is budget
        # arithmetic rather than confidence: `context.preference_budget` is set
        # so that EVERY session in the group list fits complete, so a session
        # does not have to win a ranking to be represented and nothing is
        # dropped to make room. That is load-bearing here in a way it is not
        # for E12, because `retrieve_raw`'s ordering of near-tied candidates is
        # not stable run to run (measured on v560 too, sequentially: the same
        # instance's answer session came back at header rank 4, then 5). A
        # budget that holds only the first few groups would hand that
        # instability the decision -- measured at 1 500 tokens, the same
        # instance delivered 7 of the answer session's 7 user turns on one run
        # and a bare header on the next. See config.py for the counting.
        #
        # It does need the OTHER half of E12's precondition, and for a reason
        # the F3 design did not anticipate. This branch trades the tier-1
        # ranked beliefs away for a denser raw fill; if the raw fill is EMPTY
        # that is not a trade, it is a context with nothing in it. Precision
        # packing can never hit that (a convergence decision presupposes rows);
        # this can, on any store whose raw tier does not match the query --
        # caught by the shipped E9 test store, where `retrieve_raw` returns 0
        # rows for "recommend something I would like" and the only thing the
        # reader ever got was the belief tier. So the same top-20 probe E12
        # makes decides this too, and an empty one leaves the route on the
        # full-budget path with its beliefs intact. Same call, reused by phase
        # 1 below: deciding it costs no extra retrieval.
        pref_pack = bool(
            route == "preference"
            and (self.cfg.get("context.preference_packing", True) if self.cfg else True))
        if pref_pack:
            raw_probe = _raw(20)
            pref_pack = bool(raw_probe)
        if pref_pack:
            budget_tokens = min(budget_tokens,
                                _clamp_cfg(self.cfg, "context.preference_budget", 3000, 1, 1000000))
            max_chars = budget_chars(budget_tokens, margin=CONTEXT_BUDGET)

        # The decision, exposed for evals to attribute an answer to (§E12
        # "expose the decision in the debug field"): route + precision flag,
        # refreshed on EVERY get_context call so it always describes the last
        # context this engine handed out, never a stale earlier one.
        self.last_context_debug = {
            "route": route,
            "precision": bool(precision),
            "pref_pack": pref_pack,
            "precision_concentration": (precision or {}).get("concentration"),
            "precision_margin": (precision or {}).get("margin"),
            "precision_session": (precision or {}).get("sid"),
            "precision_event_id": (precision or {}).get("event_id"),
            # A18: the breadth floor's decision, filled in by the raw fill
            # below when it applies. None means "no per-session ceiling was in
            # force" -- the factual and preference routes always, and any
            # breadth route whose candidates grouped into a single session or
            # whose floor is configured off.
            "breadth_floor": None,
            # A10: the budget this call actually enforced, in the SAME unit
            # `estimate_tokens` counts in -- it used to be `max_chars // 4`,
            # a third estimator, reporting 2000 for a 1500-token request.
            "token_budget": budget_tokens,
            "used_tokens": 0,          # rewritten at every return point below
        }
        if gate is not None:
            # the same dict object, so the counts below land here as they grow
            self.last_context_debug["relevance_gate"] = gate_drop
            gate_drop["words"] = sorted(gate)

        # -- EVIDENCE FIRST (r1) ---------------------------------------------
        # Tier-1: ranked beliefs fused across fts/vector/structured/graph
        # channels — the "top facts/episodes most relevant to the hint" half
        # of the evidence-first block. Unbudgeted here exactly as before
        # (limit=10 bounds it); the char budget starts biting at the raw fill
        # immediately below and every capped-tail section after it.
        #
        # E12: precision packing delivers the dominant item and its neighbors
        # and NOTHING else, so this block is skipped outright when it fires —
        # nine more ranked beliefs are exactly the volume the measurement says
        # makes a reader abstain, and this is the one block that spends budget
        # without being checked against it.
        #
        # F5: preference packing skips it for the same reason plus one of its
        # own -- on this corpus the ten rendered beliefs are `is_a`/`cousin`
        # -grade noise (measured: 57-78 active facts per haystack over ~8
        # attributes, none preference-shaped), so they are pure volume in front
        # of a reader whose whole job is to notice what the user likes.
        tier1_chars = 0
        for b in ([] if precision or pref_pack else
                  self.search(hint, limit=10, purpose=purpose, principal=principal, now=now,
                              fts_match=fts_match, lexical_only=lexical)):
            if gate is not None:
                if b.get("source_type") in _AGENT_OWN_SOURCES:
                    gate_drop["beliefs"] += 1
                    continue
                if not _relevant(self._gate_text(b), "beliefs", ("belief", b.get("belief_id"), b.get("kind"))):
                    continue
            ann = epistemic.annotate(b, principal) if epistemic else ""
            line = self._render(b) + (f"  ({ann})" if ann else "")
            # Ladder 9 E4 (§issue-8): a matched fact with recorded supersede
            # candidates gets its chain appended, oldest-first with dates, so a
            # reader can apply "latest wins" without a second lookup. Additive
            # only -- never changes which belief matched or its own rendering;
            # a fact with no chain (get_supersede_chain returns [] whenever the
            # belief has no candidate edges, including every store where E4
            # never fired) costs one indexed lookup and renders unchanged.
            if b["kind"] == "fact":
                chain = self.store.get_supersede_chain(b["belief_id"])
                if len(chain) > 1:
                    # ACL re-check (§18's every-path contract): a chain point can
                    # be a DIFFERENT belief than the one `search()` already
                    # cleared for this principal (that's the whole point -- it
                    # may be an older or still-draft fact this search wouldn't
                    # itself have surfaced), so it gets its own `_readable` pass
                    # rather than inheriting the matched belief's clearance.
                    visible = []
                    for c in chain:
                        row = self.store.get_belief("facts", c["belief_id"])
                        if row and self._readable(row, principal, purpose, None):
                            # A16: a chain point may be a DRAFT (this loop's
                            # own comment says so), and the chain renders bare
                            # `value (date)`, so carry the status down to
                            # `_chain_point` rather than re-reading the row.
                            visible.append(dict(c, status=row.get("status")))
                    if len(visible) > 1:
                        line += "  [history: " + " -> ".join(
                            self._chain_point(c) for c in visible) + "]"
            # A10: the tier-1 block is BUDGETED. It used to be the one block
            # that "spends budget without being checked against it" (its own
            # comment), so a handful of long belief renders could push `ctx`
            # past `max_chars` before the raw fill even ran, and the blind
            # final cut then sliced whichever line straddled the boundary.
            # Whole-unit: a line that does not fit is not shortened, it ends
            # the block -- ranked order means everything after it is weaker,
            # and the raw fill below re-checks the budget itself.
            if tier1_chars + len(line) + 1 > max_chars:
                break
            parts.append(line)
            tier1_chars += len(line) + 1
        ctx = "\n".join(_dedupe(parts))

        # Fill remaining budget with raw evidence grouped BY SESSION and headed
        # by the session's date (chars/token per engine.embeddings, A10). Orphan
        # excerpts strip the two
        # things a reader needs most: WHEN it was said (temporal reasoning is
        # impossible without it) and what else was said in the same conversation.
        # Excerpts are appended whole or truncated at a sentence/newline/word
        # boundary — never cut mid-word (§18.5).
        used_chars = len(ctx)
        if used_chars < max_chars:
            remaining_chars = max_chars - used_chars
            groups: list[dict] = []          # insertion order = relevance order
            by_sid: dict[str, dict] = {}
            seen_excerpts = set()
            # F1: the identity half of "context already carries this turn". See
            # `_expand_session_window`'s `existing_event_ids`.
            seen_event_ids: set = set()

            # E9 route: aggregation/counting questions ("how many...") are
            # answered by counting occurrences across MANY sessions, so a
            # ranked top-20 that happens to be dominated by one heavily-
            # matching session starves the others of any representation at
            # all. Widen the candidate pool and cap how many excerpts any one
            # session can claim in it -- purely additive/redistributive: no
            # excerpt phase 1 would otherwise have included is dropped, only
            # a heavy session's SURPLUS is redirected to make room for
            # others. factual (the default) keeps limit=20, no cap, i.e.
            # today's behavior exactly.
            raw_limit = 20
            per_session_cap = None
            if route == "aggregation":
                raw_limit = _clamp_cfg(self.cfg, "retrieval.query_routing_aggregation_limit", 40, 1, 200)
                per_session_cap = _clamp_cfg(
                    self.cfg, "retrieval.query_routing_aggregation_session_cap", 3, 1, 100)

            # Phase 1: Top-ranked excerpts from retrieve_raw.
            # `raw_probe` is the identical call already made above for the E12
            # dominance decision or (F5) the preference-packing eligibility
            # check — same hint, same limit=20. Only the factual and preference
            # routes set it, and both leave raw_limit at 20 and per_session_cap
            # at None, so the reused rows are exactly the rows this call would
            # have fetched. None whenever neither feature is eligible, and then
            # this is exactly the call that was always here.
            for raw in (raw_probe if raw_probe is not None else _raw(raw_limit)):
                excerpt = (raw.get("excerpt") or "").strip()
                eid = raw.get("event_id") or ""
                if not excerpt and not eid.startswith("session:"):
                    continue
                if eid.startswith("session:"):
                    sid, date, ev = eid.split(":", 1)[1], "", None
                else:
                    ev = self.store.get_event(eid) or {}
                    sid = ev.get("session_id") or "(no session)"
                    date = (ev.get("occurred_at") or "")[:16]
                if live_session and sid == live_session and not _folded_copy(ev):
                    # Per-turn recall of the conversation in progress: the model
                    # already has these turns -- except what a compaction folded
                    # out of its window (the context engine's eviction copies).
                    gate_drop["live_session"] = gate_drop.get("live_session", 0) + 1
                    continue
                # E12: "the dominant evidence item FIRST, its immediate session
                # neighbors for grounding, and nothing else". Phase 1 therefore
                # contributes exactly one line here — the leading item — and the
                # session-window expansion below supplies the neighbors, nearest
                # first. The rest of this session's ranked excerpts are not
                # dropped, they are re-ordered: the expansion returns every turn
                # phase 1 did not already carry.
                #
                # Ordering them by DISTANCE rather than by rank is load-bearing,
                # measured: on the motivating question "Where do I take yoga
                # classes?" the evidence turn sat one turn from the leader but
                # fifth by score, and relevance order spent the whole 1500-token
                # budget on the four excerpts above it — a packed context of the
                # right session that did not contain the answer. Nearest-first
                # puts that turn second.
                if precision and (raw.get("event_id") or "") != precision["event_id"]:
                    continue
                g = by_sid.get(sid)
                if g is None:
                    g = by_sid[sid] = {"sid": sid, "date": date, "excerpts": [], "tails": []}
                    groups.append(g)
                elif date and not g["date"]:
                    g["date"] = date
                if excerpt:
                    if per_session_cap is not None and len(g["excerpts"]) >= per_session_cap:
                        continue  # E9 aggregation route: session already at its cap
                    # E9 temporal route: every excerpt carries its OWN date, not
                    # just the one-per-session header -- "dates always shown"
                    # (§18.2). Uses the SAME occurred_at this loop already
                    # fetched for the group header, so it costs nothing extra.
                    if route == "temporal" and date:
                        excerpt = "[{}] {}".format(date, excerpt)
                    # F5 preference packing: the excerpt splits into the user's
                    # own message and the assistant's reply, and only the first
                    # is packed now. `seen_excerpts` still records the WHOLE
                    # excerpt, so the session-window expansion below does not
                    # re-offer this turn as if it were missing.
                    if pref_pack:
                        head, tail = _split_lead_message(excerpt)
                        if head:
                            g["excerpts"].append(head)
                        if tail:
                            g["tails"].append(tail)
                        seen_excerpts.add(excerpt)
                        continue
                    g["excerpts"].append(excerpt)
                    seen_excerpts.add(excerpt)
                    if eid and not eid.startswith(("session:", "proj:")):
                        seen_event_ids.add(eid)

            # E9 temporal route: chronological ordering emphasis (§18.2) --
            # excerpts within a session block are relevance-ordered by
            # default; for a "when did..." question a reader wants them in
            # the order they actually occurred. Sorting the (already date-
            # prefixed) strings is a chronological sort because occurred_at
            # is ISO-8601. Groups themselves (i.e. which session gets how much
            # of the budget) stay in relevance order -- only the excerpts
            # inside one block reorder, so this can move which excerpt gets
            # truncated at a group's own boundary, never which group does.
            if route == "temporal":
                for g in groups:
                    g["excerpts"].sort()

            # Fill context with top-ranked excerpts. A session gets exactly ONE
            # header line, and `emitted_headers` is where that fact lives: phase 2
            # reuses this session's header verbatim rather than rebuilding one from
            # whatever timestamp the turn it happens to be expanding carries.
            #
            # F5: preference packing needs every group's user turns weighed
            # against every other group's BEFORE anything is emitted, so it
            # cannot use this single streaming pass. It runs its own fill
            # below, after phase 2, and this loop and phase 2 both stand down.
            # -- A18 BREADTH FLOOR -------------------------------------
            # The fill below is a STREAMING pass: it spends the whole budget
            # on group 1 before it looks at group 2. That is right when the
            # budget holds every group and wrong when it does not, and which
            # of the two obtains is a function of the budget -- measured over
            # the 58-instance ctx_eval corpus (scripts/ctx_eval_probe.py,
            # scripts/a18_ab.py):
            #
            #   budget | aggregation route      | multi-gold instances
            #    1 500 |  1.6 sessions, top  99% |  1.6 sessions, top 100%
            #    4 000 |  4.1 sessions, top  56% |  3.6 sessions, top  58%
            #   12 000 | 12.2 sessions, top  19% | 11.4 sessions, top  19%
            #
            # ("top" = share of the raw-evidence fill claimed by the largest
            # single session, median.) At 1 500 tokens the median fill is ONE
            # session at ~100% of it -- 13 of 28 aggregation-route instances
            # emit a single session header -- while the budget is 99.9%
            # saturated; 13 of 33 multi-gold instances carry NO gold session,
            # 12 of them with <=2 sessions emitted. At 12 000 the effect is
            # gone. So the packer does not have a breadth bug, it has a
            # tight-budget breadth/depth PRIORITY fixed at "depth, always" --
            # and an aggregation question ("how many plants did I acquire
            # last month") cannot be answered out of the one session that
            # happened to match hardest.
            #
            # E9's aggregation route already caps how many EXCERPTS one
            # session may contribute here (query_routing_aggregation_session_
            # cap, default 3). That cap is denominated in items and an excerpt
            # runs to capture.max_excerpt_chars = 4 000, so three of them walk
            # straight through a 6 000-char budget. This is the same cap in
            # the unit that is actually scarce.
            #
            # THE RESERVATION. Group i of the first N gets `remaining //
            # (N - i)` chars: the first session may claim a third of the fill,
            # the second half of what is then left, the Nth and everything
            # after it all of it. So no session can spend the budget before
            # the next has been offered its share, and nothing is reserved and
            # then wasted -- a group that takes less than its share hands the
            # surplus straight to the next divisor. N = 1 is arithmetically
            # the pre-A18 fill (`remaining // 1`), which is why the knob's
            # floor is 1 rather than 0.
            #
            # It rations phase 1 ONLY. Phase 2 -- the session-window expansion
            # -- is pure depth, and it runs after every group has already been
            # offered its share, so what it spends is by construction what
            # breadth did not need. (Measured the other way too: rationing
            # phase 2 as well left a 12 000-char budget 2 700 chars unspent on
            # a store with one long session and three short ones.)
            #
            # OFF on the factual route BY CONSTRUCTION (see `breadth_routes`):
            # a factual question is answered by one session and E12 precision
            # packing depends on concentrating there. The preference route is
            # excluded too -- `_pref_pack_fill` already weighs every group
            # against every other before emitting anything, which is this same
            # idea carried further, and running both would ration twice.
            breadth_routes = ((self.cfg.get("context.breadth_floor_routes", None) if self.cfg
                               else None) or ["aggregation", "temporal"])
            breadth_n = None
            if (not precision and not pref_pack
                    and route in breadth_routes
                    and (self.cfg.get("context.breadth_floor", True) if self.cfg else True)):
                # Only groups with something to emit count toward the floor:
                # reserving a share for a group that contributes nothing is how
                # a floor turns into budget held back and never spent.
                filled = sum(1 for g in groups if g["excerpts"])
                n = min(filled, _clamp_cfg(
                    self.cfg, "context.breadth_floor_sessions", 5, 1, 100))
                if n > 1:
                    breadth_n = n
                    # The decision, in the field evals already read (§E12
                    # "expose the decision"), so a moved instance is
                    # attributable to this and not to the estimator or the
                    # route. `share_chars` is the FIRST group's share; later
                    # groups' shares are recomputed from what is actually left.
                    self.last_context_debug["breadth_floor"] = {
                        "route": route, "sessions": n, "groups": filled,
                        "share_chars": remaining_chars // n}

            emitted_headers: dict[str, str] = {}
            offered = 0
            for g in ([] if pref_pack else groups):
                if not g["excerpts"]:
                    continue
                header = "[SESSION {}{}]".format(g["sid"], " @ " + g["date"] if g["date"] else "")
                block_open = False
                # This group's share of what is left. `room` IS
                # `remaining_chars` whenever no floor applies (`// 1`) -- same
                # value, decremented on exactly the same lines -- so every
                # route the floor does not cover takes byte-for-byte the path
                # it took before A18.
                room = (remaining_chars if breadth_n is None
                        else remaining_chars // max(1, breadth_n - offered))
                offered += 1
                for excerpt in g["excerpts"]:
                    need = (0 if block_open else len(header) + 1) + len(excerpt) + 1
                    if room - need <= 0:
                        budget = room - (0 if block_open else len(header) + 1) - 1
                        piece = _truncate_at_boundary(excerpt, budget) if budget > 0 else ""
                        if piece:
                            if not block_open:
                                parts.append(header)
                                emitted_headers[g["sid"]] = header
                                block_open = True
                                # A10: charge the header. This branch appended
                                # it and then decremented by the PIECE only, so
                                # the session-window expansion below (and the
                                # noise tail after it) ran with `len(header)+1`
                                # of budget that had already been spent -- the
                                # emitted block came out over `max_chars` and
                                # the blind final cut hid it by slicing. Found
                                # by asserting the final trim never has to drop
                                # anything; the other three truncating branches
                                # (`_pref_pack_fill` and both phase-2 arms)
                                # already charged it correctly.
                                remaining_chars -= len(header) + 1
                                room -= len(header) + 1
                            parts.append(piece)
                            remaining_chars -= len(piece) + 1
                            room -= len(piece) + 1
                        break
                    if not block_open:
                        parts.append(header)
                        emitted_headers[g["sid"]] = header
                        remaining_chars -= len(header) + 1
                        room -= len(header) + 1
                        block_open = True
                    parts.append(excerpt)
                    remaining_chars -= len(excerpt) + 1
                    room -= len(excerpt) + 1
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
            if enable_session_window and remaining_chars > 0 and by_sid and not pref_pack:
                sessions_expanded = 0
                for g in groups:
                    if remaining_chars <= 0 or sessions_expanded >= max_sessions:
                        break
                    sid = g["sid"]
                    if sid == "(no session)":
                        continue
                    # One query, capped in SQL (see _expand_session_window).
                    expanded = self._expand_session_window(
                        sid, principal, seen_excerpts, limit=max_events,
                        only_folded=bool(live_session) and sid == live_session,
                        # E12: grounding means the turns AROUND the evidence,
                        # interleaved with this session's other ranked hits.
                        around_seq=precision["seq"] if precision else None,
                        rank_order=[r.get("event_id") for r in (precision_order or [])]
                        if precision else None,
                        # F1: precision-path only, deliberately. The nit this
                        # fixes is the LEADER dedupe — precision packing prints
                        # one phase-1 line and then asks this call for the rest
                        # of that session, so a leader the excerpt test misses
                        # is re-printed as its own first neighbour. On the
                        # full-budget path the same argument does not license
                        # the change: `retrieve_raw` can hand phase 1 an FTS
                        # snippet rather than the payload excerpt, so id-dedupe
                        # would drop turns excerpt-dedupe kept, and that path's
                        # acceptance bar is byte-identity with a tree that has
                        # no E12 in it at all.
                        existing_event_ids=seen_event_ids if precision else None)
                    if gate is not None:
                        expanded = [dict(x, excerpt=said) for x in expanded
                                    for said in (_said(x),) if said is not None]
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
                        header = "[SESSION {}{}]".format(sid, " @ " + date if date else "")
                    # A18 does not ration this phase, and that is the point of
                    # putting the floor in phase 1: by the time the first
                    # session EXPANDS here, every group phase 1 could reach has
                    # already been offered its share, so whatever budget is
                    # still unspent is budget breadth did not need. Rationing
                    # it again would only leave it unspent -- measured on a
                    # store with one long session and three short ones, a
                    # ceiling here too delivered 8 722 chars of a 12 000-char
                    # budget (the short sessions had nothing left to spend
                    # their shares on, and the long one was not allowed to).
                    # Append the expanded excerpts that weren't in the top-ranked list
                    for exp in expanded:
                        if remaining_chars <= 0:
                            break
                        excerpt = exp["excerpt"]
                        # E9 temporal route: same per-excerpt date prefix phase 1
                        # applies, and applied BEFORE the containment check below
                        # so an excerpt phase 1 already dated-and-included isn't
                        # re-added bare (§18.2, "dates always shown").
                        if route == "temporal" and exp.get("date"):
                            excerpt = "[{}] {}".format(exp["date"], excerpt)
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

            # F5 preference packing's own fill, standing in for both phases
            # above: it widens each group with the rest of its session's turns
            # and then spends the budget user-turns-first across ALL groups.
            if pref_pack:
                remaining_chars = self._pref_pack_fill(
                    groups, parts, emitted_headers, seen_excerpts, remaining_chars,
                    principal=principal, route=route,
                    keep=None if gate is None else _said, live_session=live_session)
                ctx = "\n".join(_dedupe(parts))

        # E12: everything below this line is the "and nothing else" precision
        # packing excludes — the bounded noise tail of directives /
        # contradictions / critical facts, entity digests, the federated
        # channel and the topic-gated standing notes. Each is defensible under a
        # full budget and each is volume the reader does not need when one item
        # already answers the question, which is precisely what the L8 diagnosis
        # measured: a reader that abstained on 30/30 with the evidence PRESENT
        # answered from the short slice that held only the evidence.
        #
        # F5: preference packing returns here for the same reason and one more.
        # What used to sit below this line for the preference route was E9's
        # "include preference-tier beliefs" addendum. It is GONE, not moved --
        # see the note above _pref_pack_fill's callers and §item-4 of the F5
        # commit: it re-stated, in a lossy `attribute: value` line, a
        # preference whose original sentence this route now packs verbatim, and
        # it selected those lines with no relevance term and no ORDER BY, i.e.
        # in rowid order. Measured over 250 real questions: it fired 0 times,
        # and in the one probed haystack that had a preference-shaped belief at
        # all the row it would have injected (`favorite_exercise = "hundred,
        # which really helps me engage my core..."`) was unrelated to the
        # question. Preference-tier beliefs now reach the reader the only way
        # that is actually relevant to the query: as the user's own words, from
        # the sessions retrieval ranked for THIS question.
        if precision or pref_pack:
            return self._emit(ctx, max_chars, budget_tokens)

        # -- BOUNDED NOISE TAIL (§L8) ------------------------------------------
        # Directives, open contradictions, and critical facts, in that order —
        # leftover budget only, and never more than ~15% of max_chars combined
        # regardless of how much is actually left over. The count caps
        # (max_directives, 3, 5) stop a single category from eating the whole
        # 15%; the shared char ceiling stops the three of them together from
        # doing it. Evidence above already claimed everything it could use —
        # this section only ever spends what it didn't.
        noise_cap_chars = int(max_chars * 0.15)
        noise_spent = 0

        def _fits(line: str) -> bool:
            # Reads `ctx`/`noise_spent` fresh on every call (closure over the
            # enclosing scope, not a captured value) — callers must re-join
            # `ctx` after each append, or this check goes stale mid-loop and
            # can under-count how much a whole run of appends actually costs.
            need = len(line) + 1
            if noise_spent + need > noise_cap_chars:
                return False
            if len(ctx) + need > max_chars:
                return False
            return True

        if include_directives and max_directives > 0:
            for d in self.directive_rows(principal, max_directives, purpose):
                body = d.get("body")
                if not body:
                    continue
                # Gated: a standing directive already reaches every turn through
                # the system prompt (static_block); repeated here only when it
                # is about this message and not already on the page as a [NOTE].
                if gate is not None and (body in ctx or not _relevant(body, "tail",
                                                                     ("belief", d.get("belief_id"), "note"))):
                    continue
                line = f"[DIRECTIVE] {body}"
                if not _fits(line):
                    break
                parts.append(line)
                noise_spent += len(line) + 1
                ctx = "\n".join(_dedupe(parts))

        for c in self.open_contradictions(3, principal):
            line = f"[CONTRADICTION] {c.get('detail','') or c.get('belief_a','')}"
            if gate is not None and not _relevant(line, "tail"):
                continue
            if not _fits(line):
                break
            parts.append(line)
            noise_spent += len(line) + 1
            ctx = "\n".join(_dedupe(parts))

        for c in self.store.query_beliefs("facts", "criticality!='normal' AND status='active'", (), 5):
            if not self._readable(c, principal, purpose, None):
                continue
            line = f"[CRITICAL] {c.get('attribute','')}: {c['value']}"
            if gate is not None and not _relevant(line, "tail", ("belief", c.get("belief_id"), "fact")):
                continue
            if not _fits(line):
                break
            parts.append(line)
            noise_spent += len(line) + 1
            ctx = "\n".join(_dedupe(parts))

        # §u2: one consolidated line per graph-seeded entity — the profile a reader
        # would otherwise rebuild from the fact rows above. Strictly leftover
        # budget and capped at 3: raw evidence above (phase 1 + session windows)
        # is what carries turn-level recall, so a digest is only ever bought with
        # space nothing else claimed (§r1 priority rule: evidence first).
        used_chars = len(ctx)
        if used_chars < max_chars:
            seed_tokens = self._tokens(hint) if gate is None else [
                t for t in self._tokens(hint) if shares_content_word(gate, t)]
            for e in self._graph_seeds(seed_tokens)[:3]:
                for d in self.store.query_beliefs(
                        "notes", "note_type='belief' AND subject=? AND status='active'",
                        (f"digest:{e}",), 1):
                    if not d.get("body") or not self._readable(d, principal, purpose, None):
                        continue
                    line = "[DIGEST] {}".format(d["body"])
                    if len(ctx) + len(line) + 1 >= max_chars:
                        continue
                    parts.append(line)
                    ctx = "\n".join(_dedupe(parts))

        # §g3: the federated channel, out of leftover budget only.
        # Everything above is Chronicle's own evidence — session excerpts carry
        # turn-level recall — and an external projection is a pointer into
        # somebody else's record, so it may never displace one (r1 priority
        # rule). Under a tight budget this loop emits nothing at all, which is
        # the correct outcome, not a degraded one. Each line carries its
        # pointer (<table>:<row_id>) so a reader can trace the claim back to a
        # row; nothing here is written, linked, or promoted to a fact (I20).
        if self.federated is not None and len(ctx) < max_chars:
            focus = self._focus_tokens(hint)
            if focus:
                remaining_chars = max_chars - len(ctx)
                added = 0
                for hit in self.federated.query(focus, principal, self.active_principal):
                    line = "[FEDERATED %s] %s" % (hit["provider"], hit["block"])
                    if gate is not None and not _relevant(line, "tail"):
                        continue
                    if remaining_chars - len(line) - 1 <= 0:
                        break
                    parts.append(line)
                    remaining_chars -= len(line) + 1
                    added += 1
                if added:
                    ctx = "\n".join(_dedupe(parts))

        # §r6: the topic-relevant standing note neither delivery path could carry.
        # The unconditional block above takes the FIRST max_directives always_inject
        # rows in store order, not relevance order (real stores reach ~110 active
        # norm notes within one LongMemEval haystack), and search()'s LIKE channel
        # covers the facts table only — a note reaches Tier 1 by exact FTS token
        # or not at all, so "I always prefer window seats" is invisible to the
        # query "what seat should I book". This adds back the rows the query's own
        # focus tokens select. Additive only, by construction: every row it can
        # emit is one the unconditional block would already have delivered under a
        # larger cap, it runs AFTER the raw fill so raw evidence keeps first claim
        # on the budget (r1), it never drops or reorders a line already assembled —
        # and (§L8) it spends from the SAME noise_spent/noise_cap_chars ledger as
        # the unconditional directive block, so a broad focus token that matches
        # dozens of norm notes can't reopen the crowding problem the count cap
        # above just closed.
        if include_directives and len(ctx) < max_chars:
            # Same focus tokens the abstention gate calls distinctive, matched as
            # substrings the way search()'s structured channel matches facts —
            # that is what lets "seat" reach a body that says "seats".
            focus = self._focus_tokens(hint)
            # Bodies already on a line of their own. An epistemic annotation is
            # appended to the [NOTE] render, so compare by prefix, not equality.
            # A16: a drafted note renders `[DRAFT] [NOTE] body`, so strip the
            # marker before the prefix test — otherwise a body already on the
            # page as a draft reads as absent and gets re-added below as a bare
            # `[DIRECTIVE]`, i.e. the same claim twice, once marked and once not.
            emitted = []
            for p_ in parts:
                line = p_[len(_DRAFT_TAG) + 1:] if p_.startswith(_DRAFT_TAG + " ") else p_
                if line.startswith(("[DIRECTIVE] ", "[NOTE] ")):
                    emitted.append(line.split(" ", 1)[1])
            added = 0
            for d in (self.directive_rows(principal, 200, purpose) if focus else []):
                if added >= _TOPIC_NOTE_CAP:
                    break
                body = (d.get("body") or "").strip()
                if not body:
                    continue
                if any(e.startswith(body) for e in emitted):
                    continue
                low = body.lower()
                if not any(t in low for t in focus):
                    continue
                if gate is not None and not _relevant(body, "tail", ("belief", d.get("belief_id"), "note")):
                    continue
                line = f"[DIRECTIVE] {body}"
                if not _fits(line):
                    break
                parts.append(line)
                emitted.append(body)
                noise_spent += len(line) + 1
                ctx = "\n".join(_dedupe(parts))
                added += 1

        return self._emit(ctx, max_chars, budget_tokens)

    def _emit(self, ctx, max_chars, budget_tokens) -> str:
        """The ONE exit from get_context: fit, then report what was emitted.

        A10. Two things used to be wrong at this line and both were reported
        as if they were right:

          * the cut was `ctx[:max_chars]`, a blind slice through whatever
            line straddled the boundary, labelled "(truncated)" with no count
            and no indication that a rendered fact had been left half-said;
          * `last_context_debug["token_budget"]` was `max_chars // 4` -- a
            THIRD ratio, neither the `* 4` this function budgeted with nor the
            `/ 3` every consumer measured with -- and there was no "used"
            figure at all, so nothing ever compared the claim to the bytes.
            `used_chars`/`budget_chars` (A10b) report the same decision in
            chars, so a caller can check the delivered size against the
            enforced one without knowing the estimator at all.

        Now the trim drops whole units (`_fit_units`) and both numbers come
        out of the same estimator the budget was built from, so
        `used_tokens <= token_budget` holds exactly, not within a fudge
        factor. `dropped_units` is 0 on every path where each section checked
        the budget before appending, which is now all of them.
        """
        text, dropped = _fit_units(ctx, max_chars)
        debug = self.last_context_debug
        if isinstance(debug, dict):
            debug["token_budget"] = budget_tokens
            debug["used_tokens"] = estimate_tokens(text, margin=CONTEXT_BUDGET)
            debug["used_chars"] = len(text)
            # A10b: the char budget this call actually enforced, so the margin
            # in force is visible to a caller (and to a test) as a number,
            # not inferred from the estimator's current constant.
            debug["budget_chars"] = max_chars
            debug["dropped_units"] = dropped
        return text

    # -- ACL-filtered read surfaces (A1) -----------------------------------
    #
    # THE one place each of these store reads lives. Before A1 the directive
    # block, get_directives() (→ static_block → provider.system_prompt_block →
    # every system prompt), chronicle_list_directives and every contradiction
    # listing queried the store directly and rendered whatever came back — so a
    # directive authored by a SANDBOXED agent, or by another user, reached a
    # principal that access.can_read denies. Routing all of them through these
    # two methods puts them on the same choke point the retrieval channels
    # already use, and leaves exactly one place a future surface has to reuse.

    def directive_rows(self, principal=None, limit: int = 50, purpose: str = "*") -> list:
        """Active always-inject notes THIS principal may read (§15, A1)."""
        principal = principal or self.active_principal
        return [d for d in self.store.query_beliefs(
                    "notes", "always_inject=1 AND status='active'", (), limit)
                if self._readable(d, principal, purpose, None)]

    def open_contradictions(self, limit: int = 50, principal=None) -> list:
        """Open contradictions BOTH of whose sides this principal may read (A1).

        A contradiction row is a disclosure in itself — it names two belief ids
        and spells the conflict out in `detail` — so one unreadable side drops
        the whole row (core.py:232-234: existence is a disclosure). The SQL
        limit is deliberately NOT widened to compensate: over-fetching to
        backfill a restricted principal's listing would make the row count
        itself report on rows it may not see."""
        principal = principal or self.active_principal
        return [c for c in self.store.get_open_contradictions(limit)
                if self._ref_readable(c.get("belief_a"), principal)
                and self._ref_readable(c.get("belief_b"), principal)]

    def get_directives(self, principal=None, include_agent_own: bool = True) -> str:
        ds = self.directive_rows(principal, 50)
        if not include_agent_own:
            ds = [d for d in ds if _belief_source(d) not in _AGENT_OWN_SOURCES]
        if not ds:
            return ""
        return "\n".join(["=== CHRONICLE DIRECTIVES ==="] + [f"- {d['body']}" for d in ds if d.get("body")])

    def static_block(self, principal: str, include_agent_own: bool = True) -> str:
        """The block for every system prompt. `include_agent_own=False` leaves
        out the notes the agent wrote with its own memory tool: a host that
        injects the agent's memory file itself (Hermes' built-in memory) has
        the CURRENT version -- on the production store Chronicle's copies were
        older and one was cut off mid-sentence."""
        lines = []
        d = self.get_directives(principal, include_agent_own=include_agent_own)
        if d:
            lines.append(d)
        # In every system prompt, so only what must never be acted against:
        # safety (an allergy, anaphylaxis, a DNR). "Critical" also covers
        # medical facts, so they never decay -- on the production store that
        # put a prescription refill, a lab visit and a past procedure into every
        # agent's prompt, cron jobs included ("Quest Diagnostics" is critical by
        # its name). They still surface when a message is about them.
        crit = [c for c in self.store.query_beliefs(
                    "facts", "criticality='critical' AND criticality_reason='safety' AND status='active'", (), 5)
                if self._readable(c, principal, "*", None)]
        if crit:
            lines.append("=== CRITICAL ===")
            lines += [f"- {c.get('attribute','')}: {c['value']}" for c in crit]
        con = self.open_contradictions(5, principal)
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
            # Who the user is, not what happened to them: an event ("attended
            # a birthday", "purchased ...") is not a standing attribute.
            if (r.get("predicate_canonical") or attr) in _EVENT_PREDICATES or attr in _EVENT_PREDICATES:
                continue
            if attr and attr not in seen and r.get("value"):
                seen.add(attr)
                prof.append(f"- {attr}: {r['value']}")
            if len(prof) >= 15:
                break
        if prof:
            lines.append("=== USER PROFILE ===")
            lines += prof
        return "\n".join(lines)

    # -- answer-support verification (E11, ladder-9 issue #8) --------------

    def _support_threshold(self):
        try:
            st = float(self.cfg.get("retrieval.support_threshold",
                                    DEFAULTS["retrieval"]["support_threshold"])) if self.cfg \
                else DEFAULTS["retrieval"]["support_threshold"]
        except (TypeError, ValueError):
            st = DEFAULTS["retrieval"]["support_threshold"]
        return max(0.0, min(1.0, st))

    def _resolve_evidence_vectors(self, evidence_refs) -> list:
        """Evidence refs -> stored vectors, via the store's EXISTING vector
        accessors only (no new SQL surface). Refs are belief_id / event_id
        strings -- the same two id shapes search()/answer() already hand
        back as `sources` -- so both channels are checked:

        - memory_vectors (facts/notes/episodes, keyed belief_id+kind):
          get_memory_vectors_by_ids(), the batch-by-id accessor E3's reranker
          and E8's MMR selection share. E11 was written against a base where
          it did not exist yet and filtered a full iter_memory_vectors() scan
          instead; that returns the same vectors, but it reads EVERY row in
          the store to answer a bounded handful of refs.
        - observed_vectors (raw session excerpts, keyed event_id):
          get_observed_vectors_by_ids() is an existing batch-by-id accessor
          built for exactly this lookup.

        Both channels are now by-id, so a verify_answer call costs O(refs)
        rather than O(store).

        A ref that names nothing with a stored vector is silently skipped
        (§E11 spec) -- not an error, and never treated as "no support".
        """
        refs = [str(r) for r in (evidence_refs or []) if r]
        if not refs:
            return []
        vecs = []
        for row in self.store.get_memory_vectors_by_ids(refs).values():
            if row.get("embedding"):
                vecs.append(unpack(row["embedding"]))
        for row in self.store.get_observed_vectors_by_ids(refs).values():
            if row.get("embedding"):
                vecs.append(unpack(row["embedding"]))
        return vecs

    def verify_answer(self, answer_text: str, evidence_refs=None) -> dict:
        """Answer-support verification (E11): support = max cosine(answer
        embedding, evidence embeddings); supported = support >=
        retrieval.support_threshold (default 0.55).

        Read-only -- zero side effects: only ever calls the embedder's pure
        embed() and the store's existing SELECT-only vector accessors, never
        a write path. Intended for host-LLM mode to flag likely
        hallucinations before an answer reaches the user, not for Chronicle's
        own retrieval/abstention (that gate is I8, unrelated).

        Missing embedder (None, or a degraded backend that raises on embed),
        or no evidence_ref resolving to a stored vector -> {"support": None,
        "supported": None} -- Python None, i.e. the spec's "null". "can't
        check" must never be indistinguishable from "checked and failed".

        The answer embeds DOCUMENT-side (E1). It is scored against stored
        memory/observed vectors, which are written through embed_document(),
        so a bare embed() would compare an unprefixed answer against
        "search_document: "-prefixed evidence on a prefix model -- depressing
        every support score for a reason that has nothing to do with whether
        the answer is supported. Hashing mode never prefixes, so this is
        invisible to the offline gates and only bites a real deployment.
        """
        if self.embedder is None:
            return {"support": None, "supported": None}
        try:
            embed_document = getattr(self.embedder, "embed_document", None)
            if not callable(embed_document):
                embed_document = self.embedder.embed
            answer_emb = embed_document(answer_text or "")
        except Exception:
            return {"support": None, "supported": None}  # degraded/unavailable embedder
        if not answer_emb:
            return {"support": None, "supported": None}

        evidence_vecs = self._resolve_evidence_vectors(evidence_refs)
        if not evidence_vecs:
            return {"support": None, "supported": None}  # no ref resolved to a vector

        support = max(cosine(answer_emb, v) for v in evidence_vecs)
        return {"support": support, "supported": support >= self._support_threshold()}

    # -- structured lookups (§18.3) ---------------------------------------

    def ask_about(self, entity_id, *, principal=None):
        principal = principal or self.active_principal
        out = []
        # §u2: the consolidation digest leads — it answers "what do we know about
        # this entity" in one line. The per-fact rows still follow verbatim; the
        # digest summarizes them, it never stands in for them.
        for d in self.store.query_beliefs(
                "notes", "note_type='belief' AND subject=? AND status='active'",
                (f"digest:{entity_id}",), 1):
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

    def history(self, belief_id, *, principal=None):
        """Supersession chain, ACL-filtered at every link (A1).

        An unreadable link ends the walk exactly the way a MISSING one does —
        same empty-or-short chain, no error, no marker. Belief ids are content
        hashes that leak into contradiction rows and tool output, so "you have
        to know the id" was never the access control; refusing loudly here
        would turn a guessed id into an existence oracle."""
        principal = principal or self.active_principal
        chain, cur, guard = [], belief_id, 0
        while cur and guard < 100:
            found = self.store.find_belief(cur)
            if not found:
                break
            row = found[1]
            if not self._readable_unstatused(row, principal):
                break
            chain.append({"belief_id": cur, "value": row.get("value") or row.get("body"),
                          "status": row.get("status"), "valid_from": row.get("valid_from"),
                          "valid_until": row.get("valid_until")})
            cur = row.get("superseded_by")
            guard += 1
        return chain

    def as_of(self, world=None, knowledge=None, *, principal=None) -> list[dict]:
        """Bitemporal query (§7.4): as-known-at `knowledge`, as-true-at `world`.

        Uses iter_events_since for memory-safe streaming (no 100k cap).

        ACL-filtered twice, because a reconstructed fact has two owners to
        answer to (A1): the EVENT it was asserted by (events carry an owner and
        no read_acl — that is what stops a sandboxed agent's or another user's
        assertions from being replayed into this listing), and, when the belief
        the event minted still exists, that row's own read_acl (which is what
        an owner_only belief is recorded in — the event log never carries it).
        Both go through access.can_read; neither restates its rules."""
        principal = principal or self.active_principal
        stream = self.store.iter_events_since(0) if not knowledge else self.store.get_events_as_of(knowledge)
        facts = {}
        for ev in stream:
            if ev["type"] != "asserted":
                continue
            if not access.can_read(None, ev.get("owner"), principal):
                continue
            p = json.loads(ev["payload"]) if isinstance(ev["payload"], str) else ev["payload"]
            if p.get("kind") != "fact":
                continue
            k = p["key"]
            facts[(k.get("entity_id"), k.get("predicate_canonical"))] = {
                "value": p.get("body"), "valid_from": p.get("valid_from") or ev["occurred_at"],
                "belief_id": compute_belief_id(
                    "fact", k, [p.get("source_event") or ev["event_id"]])}
        out = []
        for (ent, pred), v in facts.items():
            if world and v["valid_from"] and v["valid_from"] > world:
                continue
            found = self.store.find_belief(v["belief_id"])
            if found and not self._readable_unstatused(found[1], principal):
                continue
            out.append({"entity_id": ent, "predicate": pred, "value": v["value"]})
        return out

    def changes_since(self, ts: str, *, principal=None) -> list[dict]:
        principal = principal or self.active_principal
        rows = self.store.query_beliefs("facts", "created_at > ?", (ts,), 100, order="created_at")
        return [{"belief_id": r["belief_id"], "value": r["value"], "status": r["status"]}
                for r in rows if self._readable_unstatused(r, principal)]

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
            qt = {t for t in q["tokens"] if len(t) > 3}
            return any(len(qt & _content_tokens(txt)) >= self._overlap_min_tokens
                       for txt, _ in view[:3])
        qt = {t for t in q["tokens"] if len(t) > 3 and t not in _GENERIC}
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
        """Top-`limit` (belief_id, kind, cosine) over memory_vectors — STREAMED
        (A5).

        What this replaced: `iter_memory_vectors()` — `SELECT * FROM
        memory_vectors` into a list of dicts — on every single `search()`.
        Measured at production shape (108,581 rows, mostly 8192 B blobs) that
        is ~750 MB of resident Python and ~0.7 s per query, nearly all of it
        scored 0.0 by `batch_cosine`'s width guard (A0) and thrown away. It was
        the single largest runtime cost in the engine.

        The replacement is the shape `nearest_memory_vectors` and
        `retrieve_raw`'s observed scan already use: page by rowid, score each
        page with the same vectorised `batch_cosine`, keep a bounded min-heap
        of the best `limit`. Resident vector bytes are `VECTOR_SCAN_PAGE *
        width`, independent of table size.

        RANKING IS BYTE-IDENTICAL, and that is a requirement, not a hope:
        - the scan order is unchanged (rowid order is what the un-ORDERed
          `SELECT *` already returned), and the heap key carries `-pos` so
          equal cosines break the same way the old stable `sort` broke them —
          first row seen wins;
        - `batch_cosine` is bit-identical under paging ONLY once the short
          final page is merged away. The first draft of this function assumed
          per-row independence made paging free; it does not — Accelerate
          picks a different gemv kernel for small `n`, and a 3e-8 drift showed
          up the moment the differential test swept page sizes. `_tail_merged`
          (see its docstring for the measured table) is what makes the claim
          true rather than plausible;
        - the `length(embedding) = ?` prefilter restates in SQL the rule
          `batch_cosine` already applies in Python — a wrong-width blob scores
          a hard 0.0, and 0.0 never clears the `> 0.1` floor below. Wrong-width
          rows are therefore invisible to this function before AND after, and
          `tests/test_a5_streaming_candidates.py` pins that equivalence rather
          than trusting it.
        """
        limit = int(limit)
        if limit <= 0 or query_emb is None or len(query_emb) == 0:
            return []
        self._note_wrong_dim_table(query_emb, "memory_vectors", "belief_id", "belief")
        heap: list = []          # min-heap of (sim, -pos, belief_id, kind), len <= limit
        pos = 0
        for batch in _tail_merged(self.store.iter_memory_vectors_paged(
                batch_size=VECTOR_SCAN_PAGE, width=len(query_emb) * 4), VECTOR_SCAN_PAGE):
            sims = batch_cosine(query_emb, [v["embedding"] for v in batch])
            for row, sim in zip(batch, sims):
                here, pos = pos, pos + 1
                if sim <= 0.1:
                    continue
                entry = (sim, -here, row["belief_id"], row["kind"])
                if len(heap) < limit:
                    heapq.heappush(heap, entry)
                elif entry > heap[0]:
                    heapq.heapreplace(heap, entry)
        return [(bid, kind, sim) for sim, _neg, bid, kind in sorted(heap, reverse=True)]

    def _vector_proxies(self, query_emb, limit):
        """E2 doc2query: brute-force scan of query_proxy_vectors, same shape
        as _vector_beliefs — (belief_id, kind, sim) — so a proxy hit merges
        into the same 'vector' channel in search()'s RRF fusion as a direct
        content-vector hit. `kind` here is the PARENT's own belief kind.

        kind='observed' rows are SKIPPED (§H2.4). Those are the raw excerpt
        tier's proxies: their "belief_id" is an event id, and until H2 they were
        carried all the way to add(), mapped through _table_of_kind's "facts"
        default, looked up as a fact, and dropped. Excluding them here is not
        merely tidier — every one of them occupied a slot in the `limit`-capped
        result below, so with the excerpt flag on, real belief proxies were
        being displaced by rows that could never resolve. They are credited in
        the raw channel instead, by _observed_proxies.

        Reduced to (at most) ONE row per belief_id — its best-matching proxy —
        before returning. A belief with several proxies must not out-rank one
        with a single, stronger direct-content hit purely by having more shots
        on goal: search()'s RRF sums a fresh 1/(k+rank) contribution per add()
        call, so returning every matching proxy un-deduped would let proxy
        COUNT, not match quality, decide the ranking (measured regression:
        ctx_eval recall@1500 dropped ~12pt before this reduction).

        A5: STREAMED, and the kind filter is SQL's now rather than a Python
        list comprehension over a full copy of the table — this reader and
        _observed_proxies split `query_proxy_vectors` between them and each
        used to materialise the whole thing to keep its own half.

        The best-per-belief reduction keeps a dict of SCORES (never blobs), so
        what survives a page is O(distinct beliefs above the floor) of small
        ints and strings — bounded by the belief count, not by the ~150 MB of
        blob this table holds at production size. It is deliberately not capped
        to `limit` as well: a bounded candidate set can evict a belief's FIRST
        qualifying row, and first-row order is exactly what breaks ties in the
        ordering below, so capping it would be a rare, silent ranking change.
        The blob bound is the one that mattered here."""
        limit = int(limit)
        if limit <= 0 or query_emb is None or len(query_emb) == 0:
            return []
        self._note_wrong_dim_table(query_emb, "query_proxy_vectors", "belief_id",
                                   # MUST match store.iter_query_proxy_vectors_paged's
                                   # exclude_kind predicate exactly: this call reports the
                                   # COMPLEMENT of that scan, and a bare `kind != ?` here
                                   # drops NULL-kind rows the COALESCE'd scan keeps -- so a
                                   # NULL-kind wrong-width row would be neither scored nor
                                   # counted, and the store would read cleaner than it is.
                                   "proxy", "COALESCE(kind, '') != ?", ("observed",))
        best: dict = {}          # belief_id -> [best_sim, kind_of_best, first_pos]
        pos = 0
        for batch in _tail_merged(self.store.iter_query_proxy_vectors_paged(
                batch_size=VECTOR_SCAN_PAGE, width=len(query_emb) * 4,
                exclude_kind="observed"), VECTOR_SCAN_PAGE):
            sims = batch_cosine(query_emb, [v["embedding"] for v in batch])
            for row, sim in zip(batch, sims):
                here, pos = pos, pos + 1
                if sim <= 0.1:
                    continue
                cur = best.get(row["belief_id"])
                if cur is None:
                    best[row["belief_id"]] = [sim, row["kind"], here]
                elif sim > cur[0]:
                    cur[0], cur[1] = sim, row["kind"]
        # (sim desc, first_pos asc) is precisely what a stable sort by sim over
        # a first-seen-ordered dict used to produce.
        ranked = sorted(best.items(), key=lambda kv: (kv[1][0], -kv[1][2]), reverse=True)
        return [(bid, v[1], v[0]) for bid, v in ranked[:limit]]

    def _observed_proxies(self, query_emb, limit):
        """§H2.4: the raw-tier half of _vector_proxies — doc2query proxies whose
        parent is an EVENT, returned as (event_id, sim) best-per-event.

        This is the resolution path `embeddings.doc2query.excerpts` was missing.
        The flag has always written kind='observed' rows keyed by event_id; what
        did not exist was any reader that treats an event id as an event id.
        retrieve_raw does, so the credit is applied there, in the tier where the
        parent actually lives.

        Off by default and cheap when off: the whole method is skipped unless
        the flag is set, so a default store never pays for the scan (and the
        scan would find nothing, since the flag is also what writes the rows).
        Same best-per-parent reduction as the belief tier, for the same measured
        reason — several proxies on one parent must not out-vote one strong
        direct match purely by count.

        A5: streamed, kind filtered in SQL, same bounded-blob and exact-order
        contract as _vector_proxies."""
        limit = int(limit)
        if limit <= 0 or query_emb is None or len(query_emb) == 0:
            return []
        self._note_wrong_dim_table(query_emb, "query_proxy_vectors", "belief_id",
                                   "excerpt_proxy", "kind = ?", ("observed",))
        best: dict = {}          # event_id -> [best_sim, first_pos]
        pos = 0
        for batch in _tail_merged(self.store.iter_query_proxy_vectors_paged(
                batch_size=VECTOR_SCAN_PAGE, width=len(query_emb) * 4,
                kind="observed"), VECTOR_SCAN_PAGE):
            sims = batch_cosine(query_emb, [v["embedding"] for v in batch])
            for row, sim in zip(batch, sims):
                here, pos = pos, pos + 1
                if sim <= 0.1:
                    continue
                eid = row["belief_id"]        # an EVENT id in this table's excerpt role
                cur = best.get(eid)
                if cur is None:
                    best[eid] = [sim, here]
                elif sim > cur[0]:
                    cur[0] = sim
        ranked = sorted(best.items(), key=lambda kv: (kv[1][0], -kv[1][1]), reverse=True)
        return [(eid, v[0]) for eid, v in ranked[:limit]]

    def _readable(self, row, principal, purpose, domain) -> bool:
        status = row.get("status")
        if status not in ("active", "draft", None):
            return False
        # A16: drafts are readable and MARKED by default (see `_render` /
        # `_include_drafts`); `retrieval.include_drafts=false` drops them here,
        # at the one choke point every channel already passes through.
        if status == "draft" and not self._include_drafts():
            return False
        if not access.can_read(row.get("read_acl"), row.get("owner"), principal):
            return False
        return self._readable_envelope(row, purpose, domain)

    def _readable_envelope(self, row, purpose, domain) -> bool:
        """The non-ACL half of _readable (domain / purpose_scope / info_label).

        Split out so the audit-shaped paths (A1: history/as_of/changes_since)
        can call the ACL choke point WITHOUT also inheriting _readable's
        status gate, which would silently change what a bitemporal or
        supersession-chain query returns. Nothing else about the rule moves:
        access.can_read stays the one place the ACL decision is made."""
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
        return not (row.get("info_label") == "secret" and purpose != "secret")

    def _readable_unstatused(self, row, principal, purpose="*", domain=None) -> bool:
        """_readable for rows whose STATUS must not gate visibility (A1).

        history()/as_of()/changes_since() exist precisely to surface
        superseded and retracted rows, so the status gate cannot apply there —
        but the ACL must. Same choke point (access.can_read), same envelope,
        one policy difference, stated once."""
        if not access.can_read(row.get("read_acl"), row.get("owner"), principal):
            return False
        return self._readable_envelope(row, purpose, domain)

    def _ref_readable(self, ref, principal) -> bool:
        """May `principal` see the thing a bare id points at? (A1)

        Contradiction rows carry belief ids on both sides, and one side may be
        an EVENT id (reducer._on_contradicted stores `conflicting_event`
        there). Both resolve to an owner, so both go through the same choke
        point. An id that resolves to neither names no content and gates on
        nothing — refusing it would only turn the listing into an existence
        oracle in the other direction."""
        ref = (ref or "").strip()
        if not ref:
            return True
        found = self.store.find_belief(ref)
        if found:
            return self._readable_unstatused(found[1], principal)
        ev = self.store.get_event(ref)
        if ev:
            return access.can_read(None, ev.get("owner"), principal)
        return True

    def _event_meta(self, event_id: str | None) -> dict:
        """An observed event's payload, actor, source_type and chunk_index ({}
        for a session or projection row, or an event that is not there)."""
        if not event_id or event_id.startswith(("session:", "proj:")):
            return {}
        ev = self.store.get_event(event_id)
        if not ev:
            return {}
        raw = ev.get("payload")
        try:
            p = json.loads(raw) if isinstance(raw, str) else (raw or {})
        except ValueError:
            return {}
        return {"payload": p, "actor": ev.get("actor") or "",
                "source_type": p.get("source_type") or "", "chunk_index": p.get("chunk_index")}

    def _one_word_floor(self):
        """retrieval.prefetch_min_similarity resolved: a float, or None (off --
        also for an embedder the gate cannot ask, such as hashing)."""
        if getattr(self.embedder, "_embed_raw_batch", None) is None:
            return None
        v = self.cfg.get("retrieval.prefetch_min_similarity", "auto") if self.cfg else "auto"
        if v == "auto":
            v = _ONE_WORD_FLOOR.get(_embeddings.canonical_model_id(getattr(self.embedder, "model", "")))
        try:
            return float(v) if v is not None else None
        except (TypeError, ValueError):
            return None

    def _gate_vector(self, text, as_query, timeout):
        """A vector for the one-word check, or None. One request with a short
        timeout: this runs inside the user's turn, so it neither retries nor
        trips the embedder's breaker (that would stop background embedding
        too), and it is skipped while the breaker is already open."""
        emb = self.embedder
        raw = getattr(emb, "_embed_raw_batch", None)
        if raw is None or getattr(emb, "_open_until", 0.0) > _time_monotonic():
            return None
        prefix = ""
        if getattr(emb, "use_task_prefixes", False):
            prefix = "search_query: " if as_query else "search_document: "
        try:
            vec = raw([prefix + (text or "")[:2000]], timeout)[0]
        except Exception as e:  # noqa: BLE001 -- no vector: the lexical rule alone
            logger.debug("gate embed skipped: %s", e)
            return None
        return vec or None

    def _gate_stored_vector(self, ref):
        """The stored vector for ("belief", id, kind) or ("event", id), when it
        was made by the embedder in use; else None."""
        if not ref or not ref[1]:
            return None
        if ref[0] == "belief":
            row = self.store._conn().execute(
                "SELECT embedding, model FROM memory_vectors WHERE belief_id=? AND kind=?",
                (ref[1], ref[2] or "")).fetchone()
        else:
            row = self.store._conn().execute(
                "SELECT embedding, model FROM observed_vectors WHERE event_id=?", (ref[1],)).fetchone()
        if not row or row[1] != _embeddings.embedder_model_tag(self.embedder):
            return None
        return unpack(row[0])

    def _gate_text(self, b) -> str:
        """What the injection relevance gate reads for a ranked belief: its
        attribute and value, plus the NAME of the entity a fact is about -- a
        fact renders as `attribute: value`, so "what does Robin like" would
        otherwise never match Robin's own facts."""
        text = "{} {}".format(b.get("attribute") or "", b.get("value") or "")
        eid = b.get("entity_id")
        if eid and eid != "user":
            ent = self.store.get_belief("entities", eid) or {}
            text += " {} {}".format(ent.get("name") or "", ent.get("aliases") or "")
        return text

    def _render(self, b):
        """The ONE reader-facing render of a ranked belief (A16).

        Every packing path that puts a belief in front of a reader comes
        through here -- get_context's Tier-1 block and answer()'s
        `_answer_from_beliefs` text -- so the draft marker goes here and
        nowhere else. Precision packing and preference packing skip the
        Tier-1 block entirely and emit only raw session excerpts, which are
        verbatim transcript turns and carry no belief status at all, so those
        two paths cannot leak an unmarked draft by construction; the raw-fill
        path shares this function with them.
        """
        prefix = _DRAFT_TAG + " " if b.get("status") == "draft" else ""
        if b["kind"] == "fact":
            tag = "DERIVED" if b.get("source_type") == "inference" else "FACT"
            return (f"{prefix}[{tag}] {b.get('attribute') or ''}: {b.get('value')} "
                    f"(conf {round(b.get('confidence') or 0, 2)})")
        if b["kind"] == "note":
            return f"{prefix}[NOTE] {b.get('value')}"
        if b["kind"] == "episode":
            return f"{prefix}[EPISODE] {b.get('value')}"
        return f"{prefix}[{b['kind'].upper()}] {b.get('value')}"

    @staticmethod
    def _chain_point(c) -> str:
        """One `value (date)` point of a rendered supersession chain (A16).

        Marked when the point is a draft: `latest wins` is the rule a reader
        applies to this chain, and a chain whose LAST point is an unconfirmed
        draft says the opposite of what an unmarked one says."""
        mark = _DRAFT_TAG + " " if c.get("status") == "draft" else ""
        return "{}{} ({})".format(mark, c["value"], (c["created_at"] or "")[:10])

    def _include_drafts(self) -> bool:
        """A16: may a DRAFT belief reach a reader at all? Default yes, MARKED.

        The audit offered mark-or-exclude; the code's intent settles it.
        `_readable` has always admitted drafts, the structured channel selects
        them by name, the supersession-chain walk exists partly to surface
        them, and three separate producers write a draft precisely so a value
        is NOT lost while it waits for review. Excluding by default would
        silently delete the losing side of every flagged contradiction and
        every high-risk norm from the reader's view -- a bigger honesty
        problem than the one A16 names, in the other direction. So: included
        and labelled, with this key as the off-switch for a deployment that
        wants only confirmed truth in front of its reader.

        Read at the SINGLE `_readable` choke point, so turning it off drops
        drafts from every channel (fts, vector, structured, graph), every
        packing path and every tool surface at once -- not at each render
        site, where the next new surface would forget it."""
        if not self.cfg:
            return True
        try:
            return bool(self.cfg.get("retrieval.include_drafts", True))
        except Exception:
            return True

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
    return {w for w in word_tokens((text or "").lower())
               if len(w) > 3 and w not in _STOP}


def _support_text(item):
    """The text a support item is judged on: a raw span's excerpt, or a belief's
    attribute + value (what _render would show a reader)."""
    if item.get("excerpt") is not None:
        return item["excerpt"]
    return "{} {}".format(item.get("attribute") or "", item.get("value") or "")


def _hint_freshness(row) -> float:
    """Linear decay of a §H2 rerank hint across its own lifetime: 1.0 the moment
    it is written, 0.0 at expires_at. Derived from the row's OWN timestamps
    rather than a configured half-life, so re-tuning the TTL cannot leave old
    rows decaying on a schedule nobody remembers setting. Unparseable stamps
    decay to nothing rather than to full strength — a hint whose age cannot be
    established is the one least worth trusting."""
    try:
        created = _parse_iso(row["created_at"])
        expires = _parse_iso(row["expires_at"])
        now = _parse_iso(now_iso())
    except Exception:
        return 0.0
    if None in (created, expires, now) or expires <= created:
        return 0.0
    frac = (now - created).total_seconds() / (expires - created).total_seconds()
    return max(0.0, min(1.0, 1.0 - frac))


def _parse_iso(ts):
    try:
        return _dt.datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
    except (ValueError, AttributeError):
        return None


def query_tokens(query: str) -> list:
    """A query's content tokens. The ONE definition — RetrievalEngine._tokens
    delegates here, and engine.hostmodel's rerank drain calls it directly, so
    the key a hint is FILED under and the key it is LOOKED UP by cannot drift
    apart across two modules."""
    return [t for t in word_tokens((query or "").lower())
            if t not in _STOP and len(t) > 1]


def hint_signature(query: str) -> tuple[str, list]:
    """(key, tokens) identifying a query for §H2 rerank-hint purposes.

    The key is a hash of the query's DISTINCTIVE tokens, sorted and deduped —
    so "Where does Pat Testley work?" and "pat testley work where" file and
    match identically, while "where does Sam Vimes work" does not. Sorting is
    what makes it a set signature rather than a phrase signature; word order
    carries no retrieval meaning here and treating it as if it did would make
    the exact-key path miss almost every genuine repeat.

    Returns ("", []) when the query has nothing distinctive left after the stop
    and generic filters — a query that is all stopwords must not file a hint
    keyed on emptiness, which would then match every other such query.
    """
    toks = sorted({t for t in query_tokens(query) if len(t) > 3 and t not in _GENERIC})
    if not toks:
        return "", []
    return hashlib.sha1(" ".join(toks).encode("utf-8")).hexdigest()[:16], toks


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


def _fit_units(text, max_chars):
    """Trim `text` to `max_chars` by dropping WHOLE lines from the tail (A10).

    The unit of context assembly is a rendered line: a belief with its
    confidence and supersession chain, a `[SESSION ...]` header, one excerpt
    already boundary-truncated by `_truncate_at_boundary`. The old final cut
    was `ctx[:max_chars]`, which bisects whichever of those straddles the
    boundary -- a fact whose value stops mid-word, a confidence that lost its
    closing paren -- and reports it as the bare word "(truncated)". Half a
    fact rendered in the same shape as a whole one is exactly the honesty
    defect this file keeps closing everywhere else.

    So: drop whole lines from the END (ranked order, so the tail is the
    weakest evidence) until what is left PLUS its own drop notice fits, and
    say how many went. The notice is counted against `max_chars` too -- a
    report that itself overruns the budget would be one more wrong number.

    Returns `(fitted_text, n_dropped)`. `n_dropped == 0` means the text was
    already inside the budget and is returned byte-identical, which is the
    normal case: every section of `get_context` now checks the budget before
    it appends, so this is a guard, not the mechanism.
    """
    if len(text) <= max_chars:
        return text, 0
    units = text.split("\n")
    for keep in range(len(units) - 1, -1, -1):
        dropped = len(units) - keep
        note = _OVER_BUDGET_NOTE.format(dropped, "" if dropped == 1 else "s")
        # `keep` body lines cost their own chars plus `keep` newline
        # separators (keep-1 between them, one before the notice).
        if sum(len(u) for u in units[:keep]) + keep + len(note) <= max_chars:
            return "\n".join(units[:keep] + [note]), dropped
    # Not even the notice fits. Emitting it anyway would overrun the budget to
    # announce that the budget was overrun.
    return "", len(units)


def _is_bare_role_prefix(piece: str) -> bool:
    """True when `piece` is a role label and nothing else ("User:").

    A boundary truncation can leave exactly that, and it costs a session header
    plus a line to say nothing at all — measured: an answer session that
    arrived as `[SESSION answer_92d5f7cd @ …]` followed by `User:`. Generic in
    the same way `_split_lead_message` is: it recognises the role prefix by
    shape, not by the literal words "User"/"Assistant"."""
    m = re.match(r"[^\s:][^:\n]{0,32}:", piece or "")
    return bool(m) and not piece[m.end():].strip()


def _split_lead_message(excerpt: str):
    """Split one excerpt into (leading message, remainder) at the first
    role-line boundary. F5 preference packing keeps the heads and defers the
    remainders, because on this route only the USER's own half of an excerpt
    can carry a preference and the ingest format leads with it.

    Deliberately generic: it keeps the FIRST message of a multi-message
    excerpt whatever the roles are called, rather than special-casing the
    literal strings "User:"/"Assistant:". A single-message excerpt returns
    (excerpt, "") -- i.e. nothing is lost, it is simply all head."""
    m = _MSG_START.search(excerpt or "")
    if not m:
        return (excerpt or ""), ""
    return excerpt[:m.start()].rstrip(), excerpt[m.start():].strip("\n")


def _dedupe(parts):
    seen, out = set(), []
    for p in parts:
        if p not in seen:
            seen.add(p)
            out.append(p)
    return out
