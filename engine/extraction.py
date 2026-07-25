"""
Chronicle — Extraction (§16): recall-oriented, versioned, replayable (I9).

A pluggable `Extractor` turns an `observed` excerpt into routed items (facts,
entities, signals, episodes). The raw tier (§18) covers whatever extraction
misses, so extraction is tuned for recall + common-case speed and `skip` is safe
(skipped content stays raw-indexed — affects store cleanliness, never recall,
I23). A real deployment swaps `HeuristicExtractor` for a local model behind the
same interface; the curation worker, routing, and idempotency are unchanged.
"""

from __future__ import annotations

import re
from typing import List

from .serialize import qualifiers_hash

# Surface predicate → (canonical, cardinality). Seeded; canonicalize curation
# (§17) induces more over time.
PREDICATE_MAP = {
    "name": ("name", "single"), "called": ("name", "single"),
    "work at": ("works_at", "single"), "works at": ("works_at", "single"),
    "employed at": ("works_at", "single"), "employer": ("works_at", "single"),
    "work for": ("works_at", "single"), "works for": ("works_at", "single"),
    "work in": ("works_in", "single"), "works in": ("works_in", "single"),
    "office is in": ("works_in", "single"), "office in": ("works_in", "single"),
    "live in": ("lives_in", "single"), "lives in": ("lives_in", "single"),
    "based in": ("lives_in", "single"),
    "email": ("email", "single"), "phone": ("phone", "single"),
    "birthday": ("birthday", "single"), "born": ("birthday", "single"),
    "sister": ("sibling", "multi"), "brother": ("sibling", "multi"),
    "likes": ("likes", "multi"), "prefers": ("prefers", "multi"),
    "located in": ("located_in", "single"), "is in": ("located_in", "single"),
}

_EMAIL = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")
_FIRST_PERSON = re.compile(r"\b(i|my|i'm|im|me)\b", re.I)


class ExtractionResult:
    def __init__(self, items: List[dict], ambiguous: bool = False, route: str = "promote"):
        self.items = items
        self.ambiguous = ambiguous
        self.route = route


class Extractor:
    version = "extractor-v1"

    def extract(self, excerpt: str, *, source_event: str, owner: str = "default",
                domain: str = "user", session_id: str = "") -> ExtractionResult:
        raise NotImplementedError


def canonical_predicate(surface: str):
    s = surface.strip().lower()
    if s in PREDICATE_MAP:
        return PREDICATE_MAP[s]
    return (re.sub(r"\s+", "_", s), "single")


def entity_token(name: str, etype: str = "") -> str:
    norm = re.sub(r"[^a-z0-9]+", "_", (name or "").strip().lower()).strip("_")
    return norm or "unknown"


class HeuristicExtractor(Extractor):
    """Deterministic pattern extractor. Emits entity-grounded facts, directives,
    relationships, and episodes. No model/network — fully replayable (I9)."""

    version = "extractor-v1"

    def extract(self, excerpt, *, source_event, owner="default", domain="user", session_id=""):
        items: List[dict] = []
        ambiguous = False
        text = _strip_roles(excerpt)
        for line in re.split(r"[\n.!?]+", text):
            line = line.strip()
            if not line:
                continue
            low = line.lower()

            # Directives / norms → always-inject note (§16.2)
            m = re.search(r"\b(always|never|don'?t|do not|remember to|must(?:\s+not)?)\b\s+(.*)", low)
            if m and len(line) > 8:
                items.append(_note_item(line, "norm", owner, domain, source_event, risk="low"))
                continue

            # First-person facts: "my X is Y", "I work at Y", "I live in Y", "I'm Y"
            fp = self._first_person_fact(line, low, owner, domain, source_event)
            if fp:
                items.extend(fp)
                continue

            # email anywhere
            em = _EMAIL.search(line)
            if em and _FIRST_PERSON.search(line):
                items.append(_fact_item("user", "email", em.group(0), owner, domain, source_event, "user_direct"))
                continue

            # "X is a/an Y" entity typing
            m = re.match(r"([A-Z][\w .'-]+?)\s+is\s+(?:a|an)\s+([\w ]+)", line)
            if m:
                ent = entity_token(m.group(1))
                items.append(_entity_item(m.group(1).strip(), m.group(2).strip(), owner, domain, source_event))
                items.append(_fact_item(ent, "is_a", m.group(2).strip(), owner, domain, source_event,
                                        "session_transcript", entity_name=m.group(1).strip()))
                continue

        # An episodic summary of the turn (multi-granularity, §16.0)
        if len(text) > 60:
            items.append({"type": "asserted", "kind": "episode",
                          "key": {"title": text[:48], "session_ref": session_id},
                          "body": text[:400], "confidence": 0.6, "source_event": source_event,
                          "source_type": "session_transcript", "route": "promote"})
        route = "promote" if items else "skip"
        return ExtractionResult(items, ambiguous, route)

    def _first_person_fact(self, line, low, owner, domain, source_event):
        out = []
        # name — match the trigger on the lowercased line, capture from the original
        m = re.search(r"\b(?:my name is|i'?m|i am|call me)\s+([a-z][\w'-]+(?:\s+[a-z][\w'-]+)?)", low)
        if m:
            cand = line[m.start(1):m.end(1)].strip()
            # Keep only the leading run of capitalized words ("the operator and" → "the operator").
            kept = []
            for w in cand.split():
                if w[:1].isupper():
                    kept.append(w)
                else:
                    break
            name = " ".join(kept)
            if name:  # a real name is capitalized (rejects "I'm happy")
                out.append(_fact_item("user", "name", name, owner, domain, source_event, "user_direct"))
                return out
        # "my office is in X" → works_in (before the generic my-X-is-Y)
        m = re.search(r"\bmy office is (?:in|at)\s+(.+)", low)
        if m:
            out.append(_fact_item("user", "works_in", _clean_value(line[m.start(1):]),
                                  owner, domain, source_event, "user_direct"))
            return out
        # "I work at/in/for X", "I live in X"
        m = re.search(r"\bi\s+(work at|work in|work for|works at|works in|live in|lives in)\s+(.+)", low)
        if m:
            surface = m.group(1)
            canon, _ = canonical_predicate(surface)
            val = _clean_value(line[m.start(2):])
            out.append(_fact_item("user", canon, val, owner, domain, source_event, "user_direct"))
            if canon == "works_at":
                out.append(_entity_item(val, "organization", owner, domain, source_event))
            return out
        # generic "my <attr> is <value>"
        m = re.search(r"\bmy\s+([a-z ]+?)\s+(?:is|are|=)\s+(.+)", low)
        if m and "name" not in m.group(1) and "office" not in m.group(1):
            canon, _ = canonical_predicate(m.group(1).strip())
            out.append(_fact_item("user", canon, _clean_value(line[m.start(2):]),
                                  owner, domain, source_event, "user_direct"))
            return out
        return out


# -- item builders --------------------------------------------------------

def _fact_item(entity_id, predicate, value, owner, domain, source_event, source_type,
               entity_name=None, qualifiers=None):
    qualifiers = qualifiers or {}
    key = {"entity_id": entity_id, "predicate_canonical": predicate,
           "attribute": predicate, "qualifiers_hash": qualifiers_hash(qualifiers),
           "qualifiers": qualifiers, "owner": owner, "domain": domain}
    if entity_name:
        key["entity_name"] = entity_name
    return {"type": "asserted", "kind": "fact", "key": key, "body": value,
            "confidence": 0.85, "source_event": source_event, "source_type": source_type,
            "route": "promote"}


def _entity_item(name, etype, owner, domain, source_event):
    tok = entity_token(name, etype)
    key = {"entity_type": etype, "type": etype, "name": name, "normalized_name": name.lower(),
           "owner": owner, "domain": domain}
    return {"type": "asserted", "kind": "entity", "key": key, "body": name,
            "confidence": 0.7, "source_event": source_event, "source_type": "session_transcript",
            "route": "promote", "_entity_id": tok}


def _note_item(body, note_type, owner, domain, source_event, risk="low"):
    return {"type": "asserted", "kind": "note",
            "key": {"note_type": note_type, "subject": "directive", "risk_tier": risk},
            "body": body, "confidence": 0.8, "source_event": source_event,
            "source_type": "user_direct", "route": "promote",
            "signal_type": "directive"}


def _strip_roles(excerpt: str) -> str:
    return re.sub(r"^(User|Assistant|system|user|assistant):\s*", "", excerpt or "", flags=re.M)


def _clean_value(s: str) -> str:
    s = s.strip().strip(".,;:!?").strip()
    s = re.sub(r"^(the|a|an)\s+", "", s, flags=re.I)
    return s[:200]
