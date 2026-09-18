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

from . import entities as ents
from . import speaker as spk
from .embeddings import RemoteEndpointRefused, check_endpoint
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

_EMAIL = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]*[\w-]")
_URL = re.compile(r"\bhttps?://[^\s<>\"')]+")
_FIRST_PERSON = re.compile(r"\b(i|my|i'm|im|me)\b", re.IGNORECASE)

# -- sentence splitting (A6) ----------------------------------------------
# The old splitter was `re.split(r"[\n.!?]+", text)`, which cut inside every
# email address, URL, decimal and abbreviation -- `_EMAIL` could never match a
# real address, so the advertised `email` predicate was unreachable. A sentence
# boundary is terminal punctuation followed by WHITESPACE and an opening
# capital/quote/digit; `pat.testley@example.com`, `v1.5` and `3.5%` have no
# whitespace after the dot and so are never cut.
_SENT_BOUNDARY = re.compile(r"(?<=[.!?])[ \t]+(?=[\"'“‘(\[]?[A-Z0-9])")
# Abbreviations that end in a period mid-sentence. Deliberately short: an
# over-long list under-splits, which costs precision but never breaks a token.
_ABBREV = frozenset("""mr mrs ms dr prof sr jr st vs etc inc ltd corp dept fig
approx al no vol pp est u.s u.k e.g i.e a.m p.m ph.d""".split())
_LAST_WORD = re.compile(r"([\w.]+)[.!?]$")


def _ends_with_abbrev(chunk: str) -> bool:
    m = _LAST_WORD.search(chunk.strip())
    return bool(m) and m.group(1).lower().strip(".") in _ABBREV


def split_sentences(text: str) -> list:
    """Split into sentences without destroying emails / URLs / decimals."""
    out = []
    for para in (text or "").split("\n"):
        para = para.strip()
        if not para:
            continue
        start = 0
        for m in _SENT_BOUNDARY.finditer(para):
            head = para[start:m.start()]
            if _ends_with_abbrev(head):
                continue
            piece = head.strip()
            if piece:
                out.append(piece)
            start = m.end()
        tail = para[start:].strip()
        if tail:
            out.append(tail)
    return out


# -- directive (norm) shape (A6) ------------------------------------------
# A norm is an always-inject, never-evict, pinned note (reducer.py:923). The old
# gate was `\b(always|never|don'?t|do not|remember to|must)\b` ANYWHERE in the
# line, so "They always make me laugh" and "I never knew there were so many
# cruise ships" became standing directives -- 690 norms over 9 800 real user
# turns, which is the mechanism behind the L8 "~110 active norm notes" flood and
# the reason max_directives had to be capped at 5. A norm now requires
# IMPERATIVE / standing-instruction shape.
_POLITE_PREFIX = re.compile(
    r"^(?:ok(?:ay)?|hey|hi|so|and|also|oh|well|right|sure|thanks|thank you|please|pls|quick note|note)\b[,:\s]+")
_NORM_LEAD = re.compile(
    r"^(?:please\s+|pls\s+|just\s+|kindly\s+)?"
    r"(?:always|never|don'?t|do\s+not|remember\s+to|remember\s+that|make\s+sure|be\s+sure\s+to|"
    r"from\s+now\s+on|going\s+forward|in\s+(?:the\s+)?future|avoid\s+\w+ing|stop\s+\w+ing|"
    r"no\s+more\s+\w|refer\s+to\s+me|address\s+me|call\s+me\s+by)\b")
_NORM_SECOND_PERSON = re.compile(
    r"^(?:please\s+)?you\s+(?:should|must|need\s+to|have\s+to|are\s+to|always|never)\b")
_NORM_REQUEST = re.compile(
    r"\bi\s+(?:want|need|'?d\s+like|would\s+like|expect)\s+you\s+to\b")
# "Don't they have enough talent" / "Never mind" are not instructions.
_NORM_REFUSE = re.compile(
    r"^(?:don'?t|do\s+not)\s+(?:they|he|she|it|we|i|you\s+(?:think|know|agree|find))\b"
    r"|^never\s+mind\b"
    # An imperative takes a BASE verb: "always ask ...". A gerund or a stative
    # participle after always/never is an adverbial fragment, not an instruction
    # ("always taking care of me", "always focused on what they want").
    r"|^(?:always|never)\s+(?:\w+ing|been|had|wanted|thought|felt|focused|based|"
    r"interested|fascinated|worried|excited|concerned|surprised|impressed|amazed|"
    r"struck|drawn|meant|supposed|able|going\s+to)\b")


def is_standing_instruction(text: str) -> bool:
    """True only for imperative / standing-instruction shape (§16.2).

    Shared with criticality.py so the "boundary" rule cannot promote an ordinary
    first-person sentence containing the word "don't" to never-evict.
    """
    line = (text or "").strip()
    if not line or line.endswith("?"):
        return False                       # a question is never an instruction
    low = _POLITE_PREFIX.sub("", line.lower()).strip()
    if not low or _NORM_REFUSE.search(low):
        return False
    return bool(_NORM_LEAD.match(low) or _NORM_SECOND_PERSON.match(low)
                or _NORM_REQUEST.search(low))


# -- first-person preference (A6) -----------------------------------------
# F3 §5.4 asked for these patterns; F3's own measurement is why they are fenced.
# A bare `\bi (like|love|prefer)\b` fires overwhelmingly on politeness toward
# the assistant's own suggestions ("I like that idea", "I love how you explained
# that"), which is not a durable fact about the user. The object therefore has
# to be a THING, not a pointer back at the conversation.
_PREF_POS = re.compile(
    r"^i\s+(?:really\s+|absolutely\s+|generally\s+|usually\s+|honestly\s+|mostly\s+|only\s+|"
    r"always\s+|typically\s+|normally\s+)?"
    r"(like|love|prefer|enjoy|hate|dislike|adore)\s+(.+)")
_PREF_NEG = re.compile(
    r"^i\s+(?:really\s+|honestly\s+)?(?:don'?t|do\s+not)\s+(?:like|enjoy|care\s+for)\s+(.+)")
_PREF_STAND = re.compile(r"^i\s+can'?t\s+stand\s+(.+)")
_FAVORITE = re.compile(r"\bmy\s+favou?rite\s+([a-z][a-z ]{1,22}?)\s+(?:is|are)\s+(.+)")
# "I never drink coffee after 3pm" is a habit, not a directive to the assistant.
# The adverb stays IN the value so the polarity survives the round trip.
_HABIT = re.compile(
    r"^i\s+((?:always|never|usually|typically|generally|normally|rarely|seldom)\s+.+)")
# Past-tense / stative verbs after the adverb make it a recollection, not a habit.
_HABIT_REFUSE = re.compile(
    r"^(?:always|never|usually|typically|generally|normally|rarely|seldom)\s+"
    r"(?:knew|realiz|realis|thought|wanted|felt|wondered|assumed|believed|had|was|were|"
    r"did|saw|heard|found|liked|loved|hated|used\s+to|been|understood|expected|meant)")
_PREF_SURFACE = {"like": "likes", "love": "likes", "adore": "likes", "enjoy": "likes",
                 "prefer": "prefers", "hate": "dislikes", "dislike": "dislikes"}
# Deictic heads: the object points at the conversation, not at the world.
_DEICTIC = frozenset("""that this it these those your you both either neither them
they him her us what how where when why everything anything nothing all
option options idea ideas suggestion suggestions approach answer response
plan one ones way sound thought""".split())
_META_REF = re.compile(r"\b(?:you|your|yours)\b")
_HYPOTHETICAL = re.compile(
    r"\bif\s+i\b|\bwould\s+(?:be|have|like|love|prefer)\b|\bwish\s+i\b|\bimagine\b|"
    r"\bsuppose\b|\bhypothetical|\bwhat\s+if\b|\bmaybe\s+i\b|\bi\s+might\b")


def _is_conversational_object(value: str) -> bool:
    """Refuse preference objects that point at the assistant or the exchange."""
    v = (value or "").strip().lower().lstrip("\"'“‘")
    if not v:
        return True
    toks = re.findall(r"[a-z']+", v)
    if not toks or toks[0] in _DEICTIC:
        return True
    if _META_REF.search(" ".join(toks[:6])):
        return True
    return len(v) < 3


class ExtractionResult:
    def __init__(self, items: list[dict], ambiguous: bool = False, route: str = "promote"):
        self.items = items
        self.ambiguous = ambiguous
        self.route = route


class Extractor:
    version = "extractor-v1"

    def extract(self, excerpt: str, *, source_event: str, owner: str = "default",
                domain: str = "user", session_id: str = "", lines=None) -> ExtractionResult:
        """`lines` is `[(text, speaker)]` from engine/speaker.attribute_lines: who
        said each line. The curation worker always passes it. Without it the
        excerpt's own `role:` labels are read and unlabelled text is the user's,
        which is only right for a caller handing over the user's own words."""
        raise NotImplementedError


def canonical_predicate(surface: str):
    s = surface.strip().lower()
    if s in PREDICATE_MAP:
        return PREDICATE_MAP[s]
    return (re.sub(r"\s+", "_", s), "single")


# An entity's id lives with the rest of what an entity is (engine/entities.py);
# re-exported here because hostmodel, derivation and the tools import it from
# this module.
entity_token = ents.entity_token


# -- relation / possession patterns (A6) ----------------------------------
_REL_PRED = {
    "wife": "spouse", "husband": "spouse", "partner": "spouse", "spouse": "spouse",
    "fiance": "spouse", "fiancee": "spouse", "fiancé": "spouse", "fiancée": "spouse",
    "sister": "sibling", "brother": "sibling", "sibling": "sibling",
    "son": "child", "daughter": "child", "child": "child", "kid": "child",
    "mother": "mother", "mom": "mother", "mum": "mother",
    "father": "father", "dad": "father",
    "manager": "manager", "boss": "manager",
    "colleague": "colleague", "coworker": "colleague", "friend": "friend",
    "doctor": "doctor", "therapist": "therapist", "landlord": "landlord",
    "dog": "pet", "cat": "pet", "puppy": "pet", "kitten": "pet",
}
_PERSON_REL = frozenset(v for v in _REL_PRED.values() if v != "pet")
_REL_WORDS = "|".join(sorted(_REL_PRED, key=len, reverse=True))
_NAME = r"[A-Z][\w'’.-]*(?:\s+[A-Z][\w'’.-]*){0,2}"
# "My wife Robin Placeholder is a pediatrician." -> spouse + occupation(Robin)
_MY_REL_NAME = re.compile(r"\b[Mm]y\s+((?i:%s))\s+(%s)\b" % (_REL_WORDS, _NAME))
# "Sam Vimes is my manager at Acme Fake Co." -> role(Sam) + manager(user)
_NAME_IS_MY_REL = re.compile(r"^(%s)\s+is\s+my\s+((?i:%s))\b" % (_NAME, _REL_WORDS))
# Predicates that can follow a grounded name.
_TAIL_IS_A = re.compile(r"^(?:is|was)\s+(?:a|an)\s+([a-z][\w -]{2,40})")
_TAIL_PLACE = re.compile(r"^(?:lives|works|is\s+based)\s+in\s+(.+)")
_PET_NAMED = re.compile(
    r"\b[WwIi]e?\s+(?:just\s+)?(?:adopted|got|have|own|rescued)\s+an?\s+"
    r"(dog|cat|puppy|kitten|rabbit|bird|hamster|horse|parrot)\s+(?:named|called)\s+(%s)" % _NAME)
_ALLERGY = re.compile(r"\bi(?:'m|\s+am)\s+allergic\s+to\s+(.+)|\bi\s+have\s+an?\s+(\w+)\s+allergy\b")
# A medication claim needs a dose: "I take the bus" must never become medication.
_MEDICATION = re.compile(
    r"\bi\s+(?:take|'m\s+taking|am\s+taking|'m\s+on|am\s+on)\s+"
    r"([a-z][\w-]{2,30}(?:\s+[a-z][\w-]+){0,2}\s+\d+\s*(?:mg|mcg|g|ml|iu|units)\b)", re.IGNORECASE)
_DIET = re.compile(
    r"\bi(?:'m|\s+am)\s+(?:a\s+|an\s+)?(vegetarian|vegan|pescatarian|"
    r"gluten[- ]free|dairy[- ]free|lactose\s+intolerant|teetotal(?:er)?)\b")
_MOVED_TO = re.compile(r"\b[Ii]\s+(?:just\s+|recently\s+)?moved\s+to\s+(%s)" % _NAME)
_NEW_JOB = re.compile(
    r"\b[Ii]\s+(?:just\s+|recently\s+)?(?:started|took|accepted|began|joined)\s+"
    r"(?:a\s+)?(?:new\s+)?(?:job|role|position|working|work)?\s*(?:at|with)\s+(%s)" % _NAME)
_DEVICE = re.compile(
    r"\b[Ii]\s+(?:use|have|own|bought|got)\s+an?\s+((?:\d{4}\s+)?[A-Z][\w-]*"
    r"(?:\s+(?:Pro|Air|Max|Mini|Plus|Ultra|SE|XL|[A-Z][\w-]*)){0,2})\b")
_GOAL = re.compile(
    r"\bi(?:'m|\s+am)\s+(?:training\s+for|saving\s+(?:up\s+)?for|learning\s+to)\s+(.+)"
    r"|\bmy\s+goal\s+is\s+(?:to\s+)?(.+)")
# The `i'm <X>` name form: a real name is capitalised AND is not a state word.
_NAME_EXPLICIT = re.compile(r"\b(?:my name is|name'?s|call me)\s+(.+)")
_NAME_IMPLICIT = re.compile(r"^i'?\s*(?:'m|m|am)\s+(.+)")
_NOT_A_NAME = frozenset("""a an the vegetarian vegan pescatarian allergic sorry sure fine
good great ok okay tired happy sad busy back here there ready done curious interested
looking trying working thinking going hoping planning wondering afraid glad excited
new old still not just in on at from with about doing feeling training learning using
currently actually really so very pretty quite kind sort gonna afraid free open able
sick well better worse late early home away single married divorced retired unemployed
self-employed pregnant confused lost bored stuck grateful thankful""".split())
_NAME_TAIL_VERB = re.compile(
    r"^(?:is|are|was|were|to|for|about|with|at|in|on|and|but|because|that|which|who|"
    r"has|have|had|will|would|can|could|should|does|did|from|of|by)\b")
_THIRD_PERSON_SUBJ = re.compile(
    r"^(?:my|your|our|his|her|their|the|a|an|this|that|these|those)\s", re.IGNORECASE)
_MAX_FACTS_PER_SENTENCE = 8


class HeuristicExtractor(Extractor):
    """Deterministic pattern extractor. Emits entity-grounded facts, directives,
    relationships, and episodes. No model/network — fully replayable (I9).

    A6: the floor's job is high-precision capture of durable first-person facts
    and correct classification of directives vs. preferences vs. chatter. Every
    pattern here is regex-only and refuses questions, hypotheticals, third-person
    statements and politeness toward the assistant's own suggestions.
    """

    version = "extractor-v1"

    def extract(self, excerpt, *, source_event, owner="default", domain="user", session_id="",
                lines=None):
        items: list[dict] = []
        ambiguous = False
        seen: set = set()
        lines = _role_lines(excerpt) if lines is None else lines

        def add(item):
            key = item.get("key") or {}
            sig = (item.get("kind"), key.get("entity_id"), key.get("predicate_canonical"),
                   key.get("name"), key.get("note_type"), (item.get("body") or "").lower())
            if sig in seen:
                return False
            seen.add(sig)
            items.append(item)
            return True

        # Emails and URLs are matched on the UNSPLIT text (A6): they contain the
        # very characters a sentence splitter cuts on.
        for line, who in lines:
            if who != spk.HUMAN:
                continue
            em = _EMAIL.search(line)
            if em and _FIRST_PERSON.search(line):
                add(_fact_item("user", "email", em.group(0), owner, domain, source_event,
                               "user_direct"))

        for raw_line, who in lines:
            # Only the user's own words say anything about the user. The
            # assistant's "I ...", its suggestions and its advice ("Remember to
            # taste as you go"), tool output, a scheduled job's prompt and the
            # host's control frames are none of them facts, preferences or
            # standing instructions the user gave. The same goes for "X is a Y":
            # typed from assistant prose and tool output it produced entities such
            # as "known cosmetic bug" and "valid result".
            if who != spk.HUMAN:
                continue
            for line in split_sentences(raw_line):
                if not line:
                    continue
                low = line.lower()

                # Directives / norms → always-inject note (§16.2). Imperative
                # shape only; a first-person preference is a FACT, not a norm.
                if len(line) > 8 and is_standing_instruction(line):
                    add(_note_item(line, "norm", owner, domain, source_event, risk="low"))
                    continue

                before = len(items)
                for it in self._sentence_facts(line, low, owner, domain, source_event):
                    if len(items) - before >= _MAX_FACTS_PER_SENTENCE:
                        break
                    add(it)
                if len(items) > before:
                    continue

                # "X is a/an Y" entity typing — a real proper-noun subject only
                # ("My wife Robin ..." is handled by the relation patterns).
                m = re.match(r"([A-Z][\w .'-]+?)\s+is\s+(?:a|an)\s+([\w ]+)", line)
                if m and not _THIRD_PERSON_SUBJ.match(m.group(1)):
                    subject, etype = m.group(1).strip(), m.group(2).strip()
                    # "This is a real managed challenge" is a sentence, not an
                    # entity of type "real managed challenge" (engine/entities.py).
                    if ents.plausible_name(subject) and ents.plausible_type(etype):
                        tok = entity_token(subject)
                        add(_entity_item(subject, etype, owner, domain, source_event))
                        add(_fact_item(tok, "is_a", etype, owner, domain, source_event,
                                       "session_transcript", entity_name=subject))

        # An episodic summary of the turn with tiered abstraction levels -- of
        # what the USER said in it. It was built from the whole turn, so the
        # assistant's reply ("Great, I will remember that ...", its code, its
        # plan) became part of an episode about the user; on the production
        # store 24 of the 32 active transcript episodes carried it.
        said = "\n".join(t for t, who in lines if who == spk.HUMAN).strip()
        if len(said) > 60:
            abstract_level = said[:60] + "..."
            gist_level = said[:200] + "..." if len(said) > 200 else said
            items.append({"type": "asserted", "kind": "episode",
                          "key": {"title": said[:48], "session_ref": session_id},
                          "body": said[:400], "confidence": 0.6, "source_event": source_event,
                          "source_type": "session_transcript", "route": "promote",
                          "abstract": abstract_level, "gist": gist_level, "verbatim": said})
        route = "promote" if items else "skip"
        return ExtractionResult(items, ambiguous, route)

    # -- per-sentence extraction ------------------------------------------

    def _sentence_facts(self, line, low, owner, domain, source_event):
        """Every independent pattern that fires on this sentence (A6).

        The old `_first_person_fact` returned after the FIRST match, so "My name
        is Pat Testley and I work at Acme Fake Co." yielded only the name.
        """
        out: list = []
        if line.endswith("?"):
            return out                          # a question asserts nothing
        hypothetical = bool(_HYPOTHETICAL.search(low))
        grounded = False                        # a relation pattern owns this line

        # -- relations, with the subject grounded on the NAME -----------------
        m = _NAME_IS_MY_REL.search(line)
        if m:
            name, rel = m.group(1).strip(), m.group(2).strip().lower()
            tok = entity_token(name)
            if ents.plausible_name(name):
                out.append(_entity_item(name, "person", owner, domain, source_event))
            out.append(_fact_item(tok, "role", rel, owner, domain, source_event,
                                  "session_transcript", entity_name=name))
            out.append(_fact_item("user", _REL_PRED[rel], name, owner, domain, source_event,
                                  "user_direct"))
            grounded = True
        else:
            m = _MY_REL_NAME.search(line)
            if m:
                rel, name = m.group(1).strip().lower(), m.group(2).strip()
                pred = _REL_PRED[rel]
                tok = entity_token(name)
                if ents.plausible_name(name):
                    out.append(_entity_item(name, "person" if pred in _PERSON_REL else "animal",
                                            owner, domain, source_event))
                out.append(_fact_item("user", pred, name, owner, domain, source_event,
                                      "user_direct"))
                tail = line[m.end():].strip().lstrip(",").strip()
                t = _TAIL_IS_A.match(tail)
                if t:
                    out.append(_fact_item(
                        tok, "occupation" if pred in _PERSON_REL else "is_a",
                        _clean_value(t.group(1)), owner, domain, source_event,
                        "session_transcript", entity_name=name))
                else:
                    t = _TAIL_PLACE.match(tail)
                    if t:
                        canon = "works_in" if tail.lower().startswith("works") else "lives_in"
                        out.append(_fact_item(tok, canon, _clean_value(t.group(1)), owner,
                                              domain, source_event, "session_transcript",
                                              entity_name=name))
                grounded = True

        m = _PET_NAMED.search(line)
        if m:
            name = m.group(2).strip()
            if ents.plausible_name(name):
                out.append(_entity_item(name, "animal", owner, domain, source_event))
            out.append(_fact_item("user", "pet", name, owner, domain, source_event, "user_direct"))
            grounded = True

        # -- identity ---------------------------------------------------------
        name = self._name_from(line, low)
        if name:
            out.append(_fact_item("user", "name", name, owner, domain, source_event, "user_direct"))

        # -- health (never lost to decay, §20.1) ------------------------------
        m = _ALLERGY.search(low)
        if m and not hypothetical:
            val = m.group(1) if m.group(1) else m.group(2)
            span = m.start(1) if m.group(1) else m.start(2)
            out.append(_fact_item("user", "allergy",
                                  _clean_value(_trim_clause(line[span:span + len(val)])),
                                  owner, domain, source_event, "user_direct"))
        m = _MEDICATION.search(line)
        if m and not hypothetical:
            out.append(_fact_item("user", "medication", _clean_value(m.group(1)), owner, domain,
                                  source_event, "user_direct"))
        m = _DIET.search(low)
        if m:
            out.append(_fact_item("user", "diet", m.group(1), owner, domain, source_event,
                                  "user_direct"))

        # -- work and place ---------------------------------------------------
        m = re.search(r"\bmy office is (?:in|at)\s+(.+)", low)
        if m:
            out.append(_fact_item("user", "works_in", _clean_value(_trim_clause(line[m.start(1):])),
                                  owner, domain, source_event, "user_direct"))
        m = _NEW_JOB.search(line)
        if m and not hypothetical:
            val = _clean_value(m.group(1))
            out.append(_fact_item("user", "works_at", val, owner, domain, source_event,
                                  "user_direct"))
            if ents.plausible_name(val):
                out.append(_entity_item(val, "organization", owner, domain, source_event))
        else:
            m = re.search(r"\bi\s+(work at|work in|work for|works at|works in|live in|lives in)\s+(.+)",
                          low)
            if m and not hypothetical:
                canon, _ = canonical_predicate(m.group(1))
                val = _clean_value(_trim_clause(line[m.start(2):]))
                out.append(_fact_item("user", canon, val, owner, domain, source_event,
                                      "user_direct"))
                if canon == "works_at" and ents.plausible_name(val):
                    out.append(_entity_item(val, "organization", owner, domain, source_event))
        m = _MOVED_TO.search(line)
        if m and not hypothetical:
            out.append(_fact_item("user", "lives_in", _clean_value(m.group(1)), owner, domain,
                                  source_event, "user_direct"))

        # -- possessions and goals -------------------------------------------
        m = _DEVICE.search(line)
        if m and not hypothetical and not _PET_NAMED.search(line):
            out.append(_fact_item("user", "device", _clean_value(m.group(1)), owner, domain,
                                  source_event, "user_direct"))
        m = _GOAL.search(low)
        if m and not hypothetical:
            val = m.group(1) if m.group(1) else m.group(2)
            span = m.start(1) if m.group(1) else m.start(2)
            val = _clean_value(_trim_clause(line[span:span + len(val)]))
            if not _is_conversational_object(val):
                out.append(_fact_item("user", "goal", val, owner, domain, source_event,
                                      "user_direct"))

        # -- preferences (F3 §5.4, fenced by F3's own precision finding) -------
        out.extend(self._preferences(line, low, owner, domain, source_event, hypothetical))

        # -- generic "my <attr> is <value>" -----------------------------------
        if not grounded:
            m = re.search(r"\bmy\s+([a-z]+(?:\s+[a-z]+)?)\s+(?:is|are|=)\s+(.+)", low)
            if m and "name" not in m.group(1) and "office" not in m.group(1) \
                    and "favorite" not in m.group(1) and "favourite" not in m.group(1) \
                    and not any(c.isupper() for c in line[m.start(1):m.end(1)]):
                canon, _ = canonical_predicate(m.group(1).strip())
                out.append(_fact_item("user", canon, _clean_value(_trim_clause(line[m.start(2):])),
                                      owner, domain, source_event, "user_direct"))
        return out

    def _preferences(self, line, low, owner, domain, source_event, hypothetical):
        out: list = []
        if hypothetical:
            return out
        for rx, surface in ((_PREF_POS, None), (_PREF_NEG, "dislike"), (_PREF_STAND, "dislike")):
            m = rx.match(low)
            if not m:
                continue
            if surface is None:
                surface, val_i = m.group(1), 2
            else:
                val_i = 1
            val = _clean_value(_trim_clause(line[m.start(val_i):]))
            if _is_conversational_object(val):
                return out                      # politeness toward a suggestion
            out.append(_fact_item("user", _PREF_SURFACE[surface], val, owner, domain,
                                  source_event, "user_direct"))
            return out
        m = _FAVORITE.search(low)
        if m:
            val = _clean_value(_trim_clause(line[m.start(2):]))
            if not _is_conversational_object(val):
                out.append(_fact_item("user", "favorite_" + re.sub(r"\s+", "_", m.group(1).strip()),
                                      val, owner, domain, source_event, "user_direct"))
            return out
        m = _HABIT.match(low)
        if m and not _HABIT_REFUSE.match(m.group(1)):
            val = _clean_value(_trim_clause(line[m.start(1):]))
            # The object test looks past the leading adverb.
            tail = val.split(" ", 1)[1] if " " in val else ""
            toks = tail.split()
            # "I never do that." is about the exchange, not a habit: a habit
            # needs a real predicate, not a two-word pointer.
            if (len(toks) >= 3 and toks[-1].strip(".,").lower() not in _DEICTIC
                    and not _is_conversational_object(tail)):
                out.append(_fact_item("user", "habit", val, owner, domain, source_event,
                                      "user_direct"))
        return out

    def _name_from(self, line, low):
        """A name, or "" — the `I'm <X>` form refuses states and adjectives."""
        m = _NAME_EXPLICIT.search(low)
        implicit = False
        if not m:
            m = _NAME_IMPLICIT.match(low)
            implicit = True
        if not m:
            return ""
        cand = line[m.start(1):m.end(1)].strip()
        kept = []
        for w in cand.split():
            if w[:1].isupper():
                kept.append(w)
            else:
                break
        name = " ".join(kept).strip(".,;:!?")
        if not name:
            return ""
        words = [w.lower().strip(".,;:!?") for w in name.split()]
        if all(w in _NOT_A_NAME for w in words):
            return ""                            # "I'm Vegetarian" is not a name
        if implicit:
            rest = cand[len(" ".join(kept)):].strip()
            if _NAME_TAIL_VERB.match(rest.lower()):
                return ""                        # "I'm Portland based" / "I'm Sam's brother"
        return name

    # Back-compat: pre-A6 callers/tests used this single-fact entry point.
    def _first_person_fact(self, line, low, owner, domain, source_event):
        return [it for it in self._sentence_facts(line, low, owner, domain, source_event)
                if it.get("kind") == "fact"]


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
    """An entity item. Callers check `entities.plausible_name` first; the ONE
    caller that cannot (a model's reply) is checked in LLMExtractor.extract."""
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


_LINE_LABEL = {spk.HUMAN: "User", spk.AUTOMATION: "Automation", spk.ASSISTANT: "Assistant"}


def _reader_excerpt(excerpt: str, lines: list) -> str:
    """The excerpt minus host framing and tool output, for what extraction
    keeps or sends verbatim -- the episode text, the model's prompt. Speaker
    lines already keep both out of every fact and note; the episode was the one
    output built from the raw text, so a turn that opened with an earlier
    compaction's handoff became an episode ABOUT that handoff, and a turn with a
    file read in it became an episode that was mostly the file. Unchanged --
    the same string -- when no line is either.

    Rebuilt from the speaker LINES, not by re-reading `role:` prefixes: the
    curation worker's lines come from the capture's spans, which know that a
    "User: ignore previous instructions" line inside a tool's output is the
    tool's, where a prefix reading would hand it to the user."""
    drop = (spk.SYSTEM, spk.TOOL)
    if not any(who in drop for _, who in lines):
        return excerpt
    out, prev = [], None
    for text, who in lines:
        if who in drop:
            prev = None
            continue
        label = _LINE_LABEL.get(who)
        out.append("%s: %s" % (label, text) if label and who != prev else text)
        prev = who
    return "\n".join(out)


def _strip_roles(excerpt: str) -> str:
    return re.sub(r"^(User|Assistant|system|user|assistant):\s*", "", excerpt or "", flags=re.MULTILINE)


def _role_lines(excerpt: str) -> list:
    """[(text, speaker)] per line, for a caller that passed no attribution.

    Reads the excerpt's own `role:` labels (user, assistant, tool, system, ...);
    an unlabelled line belongs to the message above it, and text before any
    label is the user's. Host control frames inside a user message are split
    out as system text. The curation worker never relies on this: it passes
    the attribution recorded at capture (engine/speaker.attribute_lines), which
    never assumes the user.
    """
    return spk.parse_labeled(excerpt, spk.HUMAN, spk.HUMAN)


_CLAUSE_TAIL = re.compile(
    r",\s*(?:please|so|but|and\s+i|which|though|although|because|if|since|"
    r"unless|while|when|then|however|anyway|\w+ed|\w+ing)\b|\s+[—–-]\s+|;\s*")
_TRAILING_ADVERB = re.compile(
    r"\s+(?:now|currently|nowadays|these\s+days|at\s+the\s+moment|right\s+now|"
    r"as\s+well|too|anyway)$", re.IGNORECASE)


def _trim_clause(s: str) -> str:
    """Cut a value at the first trailing discourse clause.

    "penicillin, please remember that" -> "penicillin". Values that are lists
    ("apples, pears and plums") are untouched: the cut needs a discourse marker.
    """
    m = _CLAUSE_TAIL.search(s or "")
    out = (s[:m.start()] if m else s).strip()
    return _TRAILING_ADVERB.sub("", out).strip()


def _clean_value(s: str) -> str:
    s = s.strip().strip(".,;:!?").strip()
    s = re.sub(r"^(the|a|an)\s+", "", s, flags=re.IGNORECASE)
    return s[:200]


_LLM_PROMPT = """Extract durable memory items from this conversation excerpt. Reply with ONLY a JSON object, no prose:
{"facts": [{"subject": "user"|"<Entity Name>", "attribute": "<snake_case_predicate>", "value": "<value>"}],
 "entities": [{"name": "<Name>", "type": "<person|org|place|thing>"}],
 "directives": ["<standing instruction the user gave, verbatim-ish>"],
 "episode": "<one-sentence summary of what happened>"|null}
Rules: only durable facts (identity, relationships, preferences, dates, places, work) — no small talk; attribute names snake_case; omit anything uncertain; empty lists are fine.

EXCERPT:
"""


class LLMExtractor(Extractor):
    """Model-backed extraction behind the same interface (§16's intended swap).

    Calls an OpenAI-compatible /chat/completions per excerpt and maps the JSON
    reply onto the exact item shapes the heuristic emits, so the curation worker,
    routing, and idempotency are untouched. On ANY failure — endpoint down, bad
    JSON, timeout — it answers with the heuristic's result instead: capture must
    never depend on a model being up (I18), and the raw tier still floors recall
    either way. Opt-in via extraction.backend: llm; the write path stays
    LLM-free unless explicitly chosen.
    """

    version = "extractor-v2-llm"

    def __init__(self, base_url, model, api_key="", timeout=30, fallback=None, allow_remote=False):
        self.base_url = (base_url or "").rstrip("/")
        self.model = model or ""
        self.api_key = api_key or ""
        self.timeout = float(timeout or 30)
        self.fallback = fallback or HeuristicExtractor()
        # A2: this extractor posts the RAW EXCERPT (up to 4000 chars of the
        # user's own transcript) in the prompt body -- the single most
        # memory-bearing request in the tree. The on-host check therefore runs
        # in __init__, once, before an object that can make that POST exists;
        # DNS happens here and never in extract(). RemoteEndpointRefused
        # propagates to make_extractor, which returns the heuristic instead.
        self.endpoint_kind = check_endpoint(self.base_url, allow_remote, purpose="extraction",
                                            config_key="extraction.llm.allow_remote")
        self.allow_remote = bool(allow_remote)

    def _chat(self, prompt):
        import json as _json
        import urllib.request
        body = _json.dumps({"model": self.model, "temperature": 0,
                            "messages": [{"role": "user", "content": prompt}]}).encode("utf-8")
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = "Bearer " + self.api_key
        req = urllib.request.Request(self.base_url + "/chat/completions", data=body, headers=headers)
        with urllib.request.urlopen(req, timeout=self.timeout) as resp:
            data = _json.loads(resp.read().decode("utf-8"))
        return data["choices"][0]["message"]["content"]

    def extract(self, excerpt, *, source_event, owner="default", domain="user", session_id="",
                lines=None):
        if not (self.base_url and self.model):
            return self.fallback.extract(excerpt, source_event=source_event, owner=owner,
                                         domain=domain, session_id=session_id, lines=lines)
        lines = _role_lines(excerpt) if lines is None else lines
        # A model cannot be trusted to tell who said what, so anything it says
        # about the user, and any instruction it reports, must be found in the
        # user's own words (engine/speaker.py).
        said = _grounding_text(spk.human_text(lines))
        try:
            import json as _json
            reply = self._chat(_LLM_PROMPT + _reader_excerpt(excerpt, lines)[:4000])
            m = re.search(r"\{.*\}", reply, re.DOTALL)      # tolerate fenced/prefixed replies
            parsed = _json.loads(m.group(0) if m else reply)
            items: list[dict] = []
            for f in (parsed.get("facts") or [])[:20]:
                subj = str(f.get("subject") or "").strip()
                attr = re.sub(r"[^a-z0-9_]", "_", str(f.get("attribute") or "").strip().lower())[:60]
                val = _clean_value(str(f.get("value") or ""))
                if not (subj and attr and val):
                    continue
                canon, _card = canonical_predicate(attr.replace("_", " "))
                if subj.lower() in ("user", "the user", "i", "me"):
                    if _grounding_text(val) not in said:
                        continue
                    items.append(_fact_item("user", canon, val, owner, domain, source_event, "user_direct"))
                else:
                    items.append(_fact_item(entity_token(subj), canon, val, owner, domain,
                                            source_event, "session_transcript", entity_name=subj))
            for e in (parsed.get("entities") or [])[:10]:
                name, etype = str(e.get("name") or "").strip(), str(e.get("type") or "thing").strip()
                if ents.plausible_name(name) and ents.plausible_type(etype):
                    items.append(_entity_item(name, etype, owner, domain, source_event))
            for d in (parsed.get("directives") or [])[:5]:
                if str(d).strip() and _grounding_text(d) in said:
                    items.append(_note_item(str(d).strip()[:400], "norm", owner, domain, source_event))
            ep = parsed.get("episode")
            if ep and str(ep).strip():
                items.append({"type": "asserted", "kind": "episode",
                              "key": {"title": str(ep)[:48], "session_ref": session_id},
                              "body": str(ep)[:400], "confidence": 0.6, "source_event": source_event,
                              "source_type": "session_transcript", "route": "promote"})
            return ExtractionResult(items, False, "promote" if items else "skip")
        except Exception:
            return self.fallback.extract(excerpt, source_event=source_event, owner=owner,
                                         domain=domain, session_id=session_id, lines=lines)


def _grounding_text(s) -> str:
    """Lower-cased, whitespace-collapsed, for a substring test that ignores
    line wrapping and case but nothing else."""
    return " ".join(str(s or "").lower().split())


def make_extractor(cfg):
    """extraction.backend selector: heuristic (default) or llm-with-fallback.

    A2: an `extraction.llm.base_url` that is not on this host (or its private
    network) is REFUSED unless `extraction.llm.allow_remote: true`, and the
    result is the plain heuristic extractor — the same thing the LLM backend
    already falls back to on any failure, so capture is unaffected and no
    excerpt is sent. The refusal logs one WARNING per process."""
    if cfg and cfg.get("extraction.backend", "heuristic") == "llm":
        try:
            return LLMExtractor(cfg.get("extraction.llm.base_url"),
                                cfg.get("extraction.llm.model"),
                                cfg.get("extraction.llm.api_key") or "",
                                cfg.get("extraction.llm.timeout", 30),
                                allow_remote=bool(cfg.get("extraction.llm.allow_remote", False)))
        except RemoteEndpointRefused:
            return HeuristicExtractor()   # check_endpoint already logged why
    return HeuristicExtractor()
