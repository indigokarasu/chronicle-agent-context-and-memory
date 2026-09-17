"""
Chronicle — what an entity IS.

Memory is organised around the things it is about: a person, a place, a thing,
an event, an idea. The projection recorded none of that. Measured on a
production store's 1,488 entity rows:

  * 1,147 had an EMPTY type, and 1,003 were named by the id of a row in another
    store ("5734393e-cc34-5920-a7a8-09951cf2ce0c" is the people store's record
    for a person whose `name` fact Chronicle already holds);
  * 171 were pronouns ("This", "There", "Each one") and 65 were sentence
    fragments ("So any flow that needs a browser I hold but can't bridge to"),
    typed with whatever followed "is a" ("real managed challenge", "dead end
    for getting a usable key into my environment", "no");
  * the types that were not junk were free text with no taxonomy: "person",
    "organization", "animal", "nurse", "separate vendor with its own
    credential".

The extractor that produced the junk read the assistant's prose and tool output
as the user's words (engine/speaker.py fixed that); these rules are the second
half, so a pronoun or half a sentence cannot become an entity even when a person
does write "This is a problem".

WHAT THIS MODULE REFUSES TO GUESS. `kind_for` answers "" rather than inventing a
kind for a type it does not recognise, and `resolve_name` only ever replaces an
id with a name the log already asserts. A reader that needs to show everything
groups the unknowns under their own heading instead of being told a guess.
"""

from __future__ import annotations

import re

# The five kinds memory is browsed by, plus "" for "not classified".
PERSON, PLACE, THING, EVENT, CONCEPT = "person", "place", "thing", "event", "concept"
KINDS = (PERSON, PLACE, THING, EVENT, CONCEPT)

# Free-text `type` -> kind. Free text is what the extractor writes ("X is a Y"
# puts Y here verbatim), so this maps what has actually been seen plus the
# obvious neighbours, and nothing else.
_KIND_OF_TYPE = {}


def _fill(kind, words):
    for w in words.split():
        _KIND_OF_TYPE[w] = kind


_fill(PERSON, """person people human contact friend colleague coworker neighbour neighbor
    family relative spouse wife husband partner mother father mom dad parent sister brother
    sibling child son daughter aunt uncle cousin grandmother grandfather nephew niece
    doctor dentist therapist nurse teacher manager boss client patient lawyer accountant
    designer engineer developer researcher founder recruiter contractor plumber electrician
    barber stylist trainer author artist musician""")
_fill(PLACE, """place location city town village country state province region county
    neighbourhood neighborhood street address building office venue restaurant cafe bar
    hotel hostel airport station park museum gallery theater theatre library school
    university hospital clinic gym studio store shop market beach island mountain trail
    room apartment house home""")
_fill(THING, """thing object item organization organisation org company business corporation
    employer firm startup agency team group band brand product device gadget phone laptop
    computer camera car vehicle bike bicycle tool app service platform website book novel
    film movie show album song game animal pet dog cat bird fish plant food dish drink
    medication prescription account card""")
_fill(EVENT, """event meeting appointment call interview trip flight journey visit holiday
    vacation birthday anniversary wedding funeral conference convention party dinner lunch
    breakfast concert gig festival show race deadline launch release milestone incident
    outage surgery procedure""")
_fill(CONCEPT, """concept idea topic subject theme field discipline skill language practice
    habit routine ritual goal ambition plan project initiative preference taste value
    principle rule policy norm belief opinion diagnosis condition allergy diet hobby
    interest sport genre style method framework methodology""")

# Occupation suffixes, for the "X is a Y" typing where Y is a job. Deliberately
# narrow: these endings are occupations in ordinary English and almost nothing
# else ("pediatrician", "radiologist", "psychiatrist", "photographer"), where a
# bare "-ist" or "-er" would swallow "checklist" and "computer".
_PERSON_SUFFIXES = ("ician", "ologist", "iatrist", "ographer", "ometrist", "opath",
                    "therapist", "ographer")

# Predicates that say what their SUBJECT is, when the type does not.
_KIND_OF_PREDICATE = {
    "birthday": PERSON, "occupation": PERSON, "role": PERSON, "email": PERSON,
    "phone": PERSON, "pronouns": PERSON, "sibling": PERSON, "spouse": PERSON,
    "partner": PERSON, "child": PERSON, "parent": PERSON, "nickname": PERSON,
    # Only a person attends, is seen, or travels. `attended_event` is the most
    # common predicate in the production store (366 facts, the calendar import)
    # and was not here, so a contact whose only trace is a calendar entry stayed
    # unclassified.
    "attended_event": PERSON, "had_appointment": PERSON, "traveling_to": PERSON,
    "address": PLACE, "located_in": PLACE, "capital_of": PLACE,
    "occurred_at": EVENT, "attendees": EVENT,
}

_PARTICLES = frozenset("""of and the a an for to in on at by with from de van von del della
    da di du la le les el bin ibn y e &""".split())

# A pronoun or a bare determiner is never an entity, however confidently a
# sentence says "This is a problem".
_NOT_A_NAME = frozenset("""this that it they them these those he she we you i me us him her
    there here one both each either neither someone something anyone anything everyone
    everything nobody nothing all any some none other others such same""".split())

_TYPE_STOP = frozenset("""no yes none n/a na nil null true false ok okay done fine valid
    invalid real normal live stale mixed clean second third next last same other new old
    re fwd typo bug error issue problem reason result output input""".split())

_ID_LIKE = re.compile(r"""^(?:[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}
                        |b_[0-9a-f]{16,}|ev_[0-9a-f]{16,}|[0-9a-f]{24,})$""",
                      re.IGNORECASE | re.VERBOSE)
_SENTENCE_LEAD = re.compile(r"""^(?:so|but|and|or|then|because|since|if|when|while|although
                             |though|unless|per|via|let|lets|let's|i'?ll|i'?m|we'?ll|also
                             |however|therefore|thus|hence|meanwhile|actually|basically)\b""",
                            re.IGNORECASE | re.VERBOSE)
_MAX_NAME_WORDS, _MAX_NAME_CHARS = 6, 80
_MAX_TYPE_WORDS, _MAX_TYPE_CHARS = 3, 40

# What people put AFTER their name. A contact record carries these verbatim, and
# without them the name rule read "<name>, Ph.D." as a sentence (it ends in a
# full stop) and "<name> (she/her)" as a lower-case word carrying no capital --
# so several real contacts on the production store could not become entities at
# all. Both are stripped before the rule looks at the words; neither can make an
# implausible name plausible, because what is left still has to pass.
_PRONOUN_TAG = re.compile(r"\s*\((?:[a-z]+/)+[a-z]+\)\s*$")
_CREDENTIAL = re.compile(r"""[,\s]+(?:ph\.?\s?d|m\.?\s?d|d\.?\s?d\.?\s?s|m\.?b\.?a|m\.?s
                          |m\.?a|b\.?a|b\.?s|j\.?d|r\.?n|n\.?p|p\.?e|esq|cpa|mph|mfa
                          |m\.?h\.?c\.?i|jr|sr|ii|iii|iv)\.?$""",
                         re.IGNORECASE | re.VERBOSE)


def entity_token(name: str, etype: str = "") -> str:
    """The id an entity is addressed by: its name, normalised.

    THE id, not one of two: a fact's `entity_id` and the row describing that
    entity have to agree, or the same entity exists twice — which is exactly
    what a production store held, a hash-keyed row carrying the type and a
    token-keyed row carrying the facts. `etype` is accepted and ignored: an
    entity that turns out to be a company rather than a person is the same
    entity, and re-typing it must not mint a second id."""
    norm = re.sub(r"[^a-z0-9]+", "_", (name or "").strip().lower()).strip("_")
    return norm or "unknown"


def is_id_like(name) -> bool:
    """A key in some other store, not a name a reader can use."""
    return bool(_ID_LIKE.match(str(name or "").strip()))


def plausible_name(name) -> bool:
    """Whether `name` can be an entity's name at all.

    A name is a proper noun, not a sentence: every word that is not a particle
    carries a capital (so "Acme Fake Co", "NVIDIA", "E.K. Chung" and "iPhone"
    pass, "Rotating between them" and "dead end for getting a key" do not)."""
    n = str(name or "").strip()
    if not n or len(n) > _MAX_NAME_CHARS or is_id_like(n):
        return False
    if n.lower() in _NOT_A_NAME or _SENTENCE_LEAD.match(n):
        return False
    n = _PRONOUN_TAG.sub("", n).strip()
    while True:                       # "<name>, M.A., Ph.D." carries two
        shorter = _CREDENTIAL.sub("", n).strip()
        if shorter == n:
            break
        n = shorter
    if not any(ch.isalnum() for ch in n):
        return False                  # a credential on its own is not a name
    if n[-1] in ".!?,;:" or " | " in n or ": " in n:
        return False           # a sentence, or an importer's subject line
    words = n.split()
    if not (1 <= len(words) <= _MAX_NAME_WORDS):
        return False
    if words[0].lower() in _NOT_A_NAME:
        return False           # "This server", "Each one"
    significant = [w for w in words if w.lower().strip(".,'-") not in _PARTICLES]
    if not significant:
        return False
    for w in significant:
        core = w.strip("\"'()[[]-–—.,")
        if not core:
            continue
        if not any(ch.isupper() for ch in core) and not core.isdigit():
            return False
    return True


def plausible_type(etype) -> bool:
    """Whether a free-text type is a category rather than a clause."""
    t = str(etype or "").strip()
    if not t or len(t) > _MAX_TYPE_CHARS:
        return False
    words = t.lower().split()
    if not (1 <= len(words) <= _MAX_TYPE_WORDS):
        return False
    # A pronoun or a bare quantifier is no more a category than it is a name:
    # the production table holds rows typed "one", "second" and "no".
    if any(w in _TYPE_STOP or w in _NOT_A_NAME for w in words):
        return False
    return all(re.fullmatch(r"[a-z][a-z'&/-]*", w) for w in words)


def kind_for(etype="", predicates=()) -> str:
    """One of KINDS, or "" when nothing here recognises it.

    The type decides when it is recognisable; otherwise the predicates a subject
    carries can: a birthday and a phone number belong to a person."""
    words = str(etype or "").lower().replace("-", " ").split()
    for word in reversed(words):
        kind = _KIND_OF_TYPE.get(word.strip("'\"&/"))
        if kind:
            return kind
    for word in reversed(words):
        if word.strip("'\"&/").endswith(_PERSON_SUFFIXES):
            return PERSON
    for p in predicates:
        kind = _KIND_OF_PREDICATE.get(str(p or "").lower())
        if kind:
            return kind
    return ""


def resolve_name(current, asserted_name) -> str:
    """The name to display for an entity whose row is named by an id.

    Only ever the name the log already asserts for that entity (a `name` fact),
    never a guess, and never a replacement for a name a reader can already read.

    The bar here is lower than `plausible_name`'s on purpose: that one decides
    whether text may CREATE an entity, and is strict because the text is prose.
    This one only chooses between an id and a name another store asserts, where
    anything readable wins — a people store legitimately holds "Ramp 💳",
    "Laura schewel" and "katie@example.invalid"."""
    if not is_id_like(current):
        return str(current or "")
    nm = " ".join(str(asserted_name or "").split())[:_MAX_NAME_CHARS]
    return nm if nm and not is_id_like(nm) else str(current or "")
