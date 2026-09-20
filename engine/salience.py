"""
Chronicle — one importance model for recall and for compaction.

Both sides scored the same thing and did it separately: the per-turn recall
gate decided whether an item is about THIS message (content words, their
inflections, how many must be shared), and the context engine decided whether
a turn is worth keeping (recency, focus match, salience and criticality
keywords). The two never agreed by construction -- nothing made them -- so a
rule fixed on one side (URLs are not content words; a short number is not
either) had to be remembered on the other.

This module is that single source of truth. It is a pure extraction: every
function below was moved here verbatim from engine/retrieval.py (the gate) and
context.py (the keep score), and both callers now import from here. Behaviour
is unchanged by construction -- see tests/test_salience_parity.py, which pins
the two entry points against the values the old code produced.

The vocabulary, smallest to largest:

  * `relevance_words(text)` -- the content words of a message,
  * `shared_content_words(words, text)` / `gate_needs(words)` -- what an item
    must share with it, and how much of it,
  * `keep_score(text, focus, recency, weights)` -- how much a unit is worth
    keeping, in [0, 1],
  * `Unit` / `rank(units, focus, weights)` -- the same score over turns,
    episodes or memories, so a caller can order any of them the same way.
"""

from __future__ import annotations

import functools
import re
import unicodedata
from dataclasses import dataclass, field
from typing import Any, Sequence

from . import tiers as _tiers
from .store import word_tokens

_STOP = {"the", "a", "an", "is", "are", "what", "who", "where", "when", "how", "do", "does",
         "did", "my", "your", "of", "to", "in", "on", "for", "and", "or", "i", "me", "s",
         "was", "were", "it", "that", "this", "with", "about", "tell", "show", "name"}

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


# retrieval.prefetch_min_similarity "auto": the cosine floor a ONE-word gate
# match must reach, per embedding model (canonical id), measured on the
# production store's real messages. A model not listed gets no floor.
_ONE_WORD_FLOOR = {"nomic-embed-text": 0.65}
# A gate embed is one request inside the user's turn: no retries, never trips
# the embedder's breaker, gives up after _GATE_EMBED_TIMEOUT, and all of one
# turn's together stop at _GATE_EMBED_BUDGET seconds. An item with no stored
# vector is embedded on the spot only when short (a CPU embedder took ~0.45 s
# for 300 characters), and at most _GATE_EMBED_ITEMS of them per turn.
# ...and a match on two or three shared words (retrieval.prefetch_min_similarity_few),
# measured the same way on 300 real messages: the plainly unrelated scored
# 0.49-0.65 (a security alert's generic words, a pasted script), the related
# 0.59-0.90; four or more shared words were all related.
_FEW_WORDS_FLOOR = {"nomic-embed-text": 0.60}
_FEW_WORDS = 3

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


# -- What a unit is worth keeping (moved from context.ChronicleContextEngine) --
# Read by the context engine's keep/evict decision and by anything that wants
# to rank units the same way. The weights are the host-visible ones
# (context_engine.keep_weights in engine/config.py).

_SALIENCE_RX = re.compile(r"\b(important|remember|critical|must)\b", re.IGNORECASE)
_CRITICALITY_RX = re.compile(r"\b(critical|must|urgent|important)\b", re.IGNORECASE)


def focus_facets(focus) -> list:
    """The strings a unit may match to earn the relevance bump: every topic,
    the task, and every focus entity's name (§R8's one-hit-scores rule)."""
    if not isinstance(focus, dict):
        return []
    facets = list(focus.get("topics") or [])
    if focus.get("task"):
        facets.append(focus["task"])
    return facets + list(focus.get("entities") or [])


def keep_score(text: str, focus, recency: float = 1.0, weights: dict | None = None) -> float:
    """How much this text is worth keeping, in [0, 1] (R3 + R8).

    Dimensions: recency (position, 0.0 oldest to 1.0 newest), relevance (any
    focus facet appears), salience (high-value keywords), criticality
    (urgent/must-do), and -- when the host asks for it -- involatile: the span
    carries exact literals (a port, a path, an id, the command that failed)
    that no summary can reconstruct. That last weight is 0.0 by default, so
    the score is what it always was until someone turns it on; its cost (the
    shape scan in engine/tiers.py) is only paid when it is non-zero.

    Pinning is deliberately NOT a dimension: a pinned span never reaches a
    score, it is hard-protected before that.
    """
    w = weights or {}
    content = (text or "").lower()
    score = recency * w.get("recency", 0.20)
    if any(f and f.lower() in content for f in focus_facets(focus)):
        score += w.get("relevance", 0.35)
    if _SALIENCE_RX.search(content):
        score += w.get("salience", 0.20)
    if _CRITICALITY_RX.search(content):
        score += w.get("criticality", 0.20)
    involatile = w.get("involatile", 0.0)
    if involatile and _tiers.involatile_spans(text or ""):
        score += involatile
    return min(1.0, score)


@dataclass
class Unit:
    """Anything importance can be asked about: a turn, an episode, a memory.

    `text` is what the rules read. `recency` is its position in whatever
    sequence it belongs to (0.0 oldest, 1.0 newest). `ref` is the caller's own
    handle -- a message index, a belief id -- carried through untouched.
    """

    text: str
    recency: float = 1.0
    kind: str = "turn"
    ref: Any = None
    meta: dict = field(default_factory=dict)


def score_unit(unit: Unit, focus, weights: dict | None = None) -> float:
    return keep_score(unit.text, focus, unit.recency, weights)


def rank(units: Sequence[Unit], focus, weights: dict | None = None) -> list:
    """`units` best first, as (score, unit). A tie keeps the given order."""
    scored = [(score_unit(u, focus, weights), i, u) for i, u in enumerate(units)]
    scored.sort(key=lambda t: (-t[0], t[1]))
    return [(s, u) for s, _i, u in scored]


def is_relevant(words, text: str, need: int | None = None) -> bool:
    """Does `text` share enough of a message's content words to be about it?
    The gate's own rule, for callers that want it as one question."""
    if not words:
        return False
    return len(shared_content_words(words, text)) >= (gate_needs(words) if need is None else need)
