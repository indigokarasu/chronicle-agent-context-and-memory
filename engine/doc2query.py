"""
Chronicle — doc2query: question-prediction embeddings (E2, §24.4).

Premise (Ladder 9): the embedding model is a general "is this the same
thing?" sensor. A stored fact's own text ("Acme Fake Co") and a question
asked about it ("where does Pat Testley work") are lexically and often
semantically distant, so retrieval built on content vectors alone under-
recalls question-shaped queries. doc2query closes that gap by generating,
at write time, the questions an item can answer and embedding THOSE
alongside the item's own content vector — replacing question-vs-answer
matching with question-vs-question matching.

Tier 1 (this module) is pure and offline: template generation driven off
the structured belief payload the reducer already holds at write time, no
LLM, no I/O, no randomness. Every public function accepts an optional
`callback` — the H1 host-model piggyback slot — tried FIRST; when absent,
or when it raises or returns nothing usable, the Tier-1 template output is
used and the caller never sees the difference. A callback can only ADD
question quality, never prevent question generation (nor fail a capture:
callback exceptions never propagate here — I12).

Storage lives in engine.store's `query_proxy_vectors` table: each row is a
generated question's embedding, linked back to the PARENT item's own
belief_id (or event_id, for the off-by-default excerpt path). Retrieval
(engine.retrieval._vector_proxies) resolves a proxy hit straight back to the
parent's own content and provenance — the question text itself is never
returned as an answer (see that module's docstring).
"""

from __future__ import annotations

from typing import Callable, Optional

# Volume bound (§E2 acceptance: "≤4 proxies per item"). Applied uniformly
# regardless of source (template or host-model callback) so a misbehaving
# callback can never blow the budget either.
MAX_PROXIES = 4

# ---------------------------------------------------------------------------
# THE MERGE RULE (§H2.1), documented here because it is the one place a host
# model's output and Chronicle's own output have to share a fixed budget.
#
#   host_first_template_fill
#
# The host's validated question set takes the leading slots, in the order the
# host returned them; the Tier-1 template set then FILLS whatever remains of
# MAX_PROXIES, in template order. Comparison for both dedupe and fill is
# case-insensitive on the stripped string.
#
# So the rule REPLACES when the host is generous (4 host questions leave no
# room for templates) and AUGMENTS when it is thrifty (1 host question keeps 3
# template slots). Neither side can be starved by the other beyond that.
#
# Why host-first rather than a quality score: there is no offline way to judge
# which of two questions is better, and inventing one would be a heuristic
# pretending to be a measurement. What IS known is provenance — the host saw
# the item's actual text, the templates saw only its relation — so the ordering
# encodes the one real difference. Why fill rather than replace outright: the
# templates are already computed, already deterministic, and free; discarding a
# usable slot buys nothing, and a host that returns one narrow question would
# otherwise silently NARROW an item's recall surface relative to no host at all.
# Regression direction matters more here than peak quality.
#
# Empty host set -> the template list, unchanged and in order. That identity is
# what keeps a default-configured store byte-identical (§H1 inertness).
MERGE_RULE = "host_first_template_fill"


def merge_questions(host, template) -> list:
    """Apply MERGE_RULE to a host question set and a Tier-1 template set.

    Total is hard-capped at MAX_PROXIES, so this is also the single place the
    volume bound is applied to host-derived proxies — a host that returns four
    questions for an item that already has four templates still yields four
    rows, never eight.
    """
    out: list = []
    seen: set = set()
    for source in (host or [], template or []):
        for q in source:
            if not isinstance(q, str):
                continue
            ql = q.strip()
            if not ql or ql.lower() in seen:
                continue
            seen.add(ql.lower())
            out.append(ql)
            if len(out) >= MAX_PROXIES:
                return out
    return out

# predicate/attribute -> question templates. "{name}" is substituted with the
# subject's display name (key["entity_name"], never the belief_id/entity_id —
# those are opaque hashes, not something a question should ever contain).
_FACT_TEMPLATES = {
    # §E2's own worked example gets both forms; everything else gets exactly
    # ONE distinctive question -- near-duplicate phrasings of the same
    # template ("what is X's email" / "what is X's email address") add proxy
    # VOLUME without adding distinct signal, and on a bag-of-words embedder
    # volume alone crowds a tight context budget (§ctx_eval regression fix).
    "works_at": ["where does {name} work", "what is {name}'s job"],
    "works_in": ["what industry does {name} work in"],
    "lives_in": ["where does {name} live"],
    "located_in": ["where is {name} located"],
    "address": ["what is {name}'s address"],
    "home_address": ["what is {name}'s home address"],
    "phone": ["what is {name}'s phone number"],
    "email": ["what is {name}'s email"],
    "birthday": ["when is {name}'s birthday"],
    "owns_property": ["what property does {name} own"],
}


def _fact_questions(key: dict, body: str) -> list:
    """Curated relation -> question forms only (§E2: 'relation -> question
    forms, e.g. works_at -> ...'). Deliberately NO catch-all fallback for
    attributes outside _FACT_TEMPLATES: a generic 'what is X's <attribute>'
    question shares almost nothing but stopwords + the subject's name across
    EVERY distinct attribute of the same entity, so on a bag-of-words
    embedder it cross-matches broadly and crowds out genuinely on-topic
    evidence under a tight context budget -- noise, not signal. Better to
    proxy fewer, sharper questions than to proxy every fact weakly."""
    name = key.get("entity_name") or key.get("name") or ""
    attribute = key.get("attribute") or key.get("predicate_canonical") or ""
    if not name or not attribute:
        return []
    templates = _FACT_TEMPLATES.get(attribute)
    if not templates:
        return []
    return [t.format(name=name) for t in templates]


def _note_questions(key: dict, body: str) -> list:
    subject = key.get("subject") or ""
    if not subject:
        return []
    return [f"what do you know about {subject}"]


def _episode_questions(key: dict, body: str) -> list:
    title = key.get("title") or ""
    if not title:
        return []
    return [f"what happened during {title}"]


def _procedure_questions(key: dict, body: str) -> list:
    name = key.get("name") or ""
    if not name:
        return []
    return [f"how do I {name}"]


def _reference_questions(key: dict, body: str) -> list:
    topic = key.get("topic") or ""
    if not topic:
        return []
    return [f"what do you know about {topic}"]


def _excerpt_questions(key: dict, body: str) -> list:
    """Tier-1 'simple transform' for raw observed excerpts (off by default,
    embeddings.doc2query.excerpts) -- no template intelligence, just a literal
    recast of the excerpt's own lead clause into a question shape, pending the
    host-model path doing this properly (H1)."""
    text = (body or "").strip()
    if not text:
        return []
    cut = len(text)
    for ch in (".", "!", "?", "\n"):
        idx = text.find(ch)
        if idx != -1:
            cut = min(cut, idx)
    lead = text[:cut].strip()[:120]
    if not lead:
        return []
    return [f"what happened: {lead}"]


_KIND_GENERATORS = {
    "fact": _fact_questions,
    "note": _note_questions,
    "episode": _episode_questions,
    "procedure": _procedure_questions,
    "reference": _reference_questions,
    "observed": _excerpt_questions,
}


def generate_questions(kind: str, key: Optional[dict], body: str,
                       callback: Optional[Callable] = None) -> list:
    """Return up to MAX_PROXIES question strings this item can answer.

    `callback(kind, key, body)`, when given, is tried FIRST — the H1 host-
    model slot. It must return a list of strings; anything falsy, wrong-typed,
    or an exception falls straight through to the Tier-1 template path below,
    so a callback can only improve generation, never suppress it or fail the
    write (I12).
    """
    key = key or {}
    if callback is not None:
        # The normalizing comprehension belongs INSIDE the try. A callback
        # returning non-strings (say [123]) satisfies `if result`, then
        # q.strip() raises AttributeError -- which, from out here, escapes
        # generate_questions and fails the write. The docstring promises the
        # opposite: "anything falsy, WRONG-TYPED, or an exception falls
        # straight through to the Tier-1 template path". H1 fills this slot
        # with output parsed from a host model's reply, so a wrong-typed
        # element is exactly the input this contract exists to absorb.
        try:
            result = callback(kind, key, body)
            out = [q.strip() for q in result if q and str(q).strip()] if result else []
        except Exception:
            out = []
        if out:
            return out[:MAX_PROXIES]
    gen = _KIND_GENERATORS.get(kind)
    if gen is None:
        return []
    try:
        raw = gen(key, body or "")
    except Exception:
        return []
    seen = set()
    out = []
    for q in raw:
        ql = (q or "").strip()
        if ql and ql.lower() not in seen:
            seen.add(ql.lower())
            out.append(ql)
        if len(out) >= MAX_PROXIES:
            break
    return out
