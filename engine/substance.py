"""
Chronicle — what a fact has to SAY to be a memory.

`entities.py` decides what an entity IS. This decides whether a fact about one
says anything: a memory must record WHAT happened, not that something did.

The rule is the owner's, in his words: "an email that says 'something happened'
but doesn't say what happened is just noise". It was measured on a production store,
where an importer had been asking a model "is there anything in this email worth
recording?" once per message and writing whatever came back. 272 facts arrived
that way and 159 of them were the email's SUBJECT LINE, recorded as things the
user had done:

    purchased        Delivered 1 item: Clothing
    purchased        Your order has shipped!
    appointment_at   New Message                      (eleven of these)
    appointment_at   You have a new balance
    appointment_at   New After Visit Summary Available
    attended_event   Your Fakevendor password has been updated

None of them says what was bought, what the message said, what the balance is,
or what the summary contains. Beside them, from the same importer, sit facts
that do:

    health_event     Placebocil 40mg prescription refill ordered via
                     Acme Fake Pharmacy on 2026-08-28.
    dined_at         Your reservation confirmation for Fake Izakaya
    purchased        Advance refund issued for Acme Fake Dental Powder

WHY THIS LIVES IN CHRONICLE AND NOT IN THE IMPORTER. The importer can be fixed,
and should be; but the next importer cannot be, because it has not been written
yet. Chronicle is what accepts a belief, so Chronicle is where "this is not a
memory" has to be decided — the same reason `entities.plausible_name` is applied
in the fold and not left to whatever wrote the entity.

WHAT IT REFUSES TO DECIDE. Only predicates that assert an EVENT (`purchased`,
`attended_event`, `had_appointment` …) are in scope. A fact whose predicate is
an attribute — `phone`, `birthday`, `occupation`, `name` — has a value that is
the attribute, and "does it say what happened" is not a question about it. And
where the answer is genuinely unclear the value is KEPT: at a write boundary a
false refusal loses a real memory silently, which is worse than a row someone
can retract later.
"""

from __future__ import annotations

import re
import unicodedata

# Predicates that assert something HAPPENED. The read model groups exactly these
# as events (dashboard/tapestry_api.py imports this set rather than keeping a
# second copy of it).
EVENT_PREDICATES = {
    "attended_event": "attended",
    "had_appointment": "appointment",
    "appointment_at": "appointment",
    "scheduled_mandatory_appointment": "appointment",
    "dined_at": "meal",
    "traveling_to": "travel",
    "purchased": "purchase",
    "health_event": "health",
    "account_security_event": "account",
    "received_contractor_estimate": "estimate",
    "received_paid_project_invitation": "invitation",
    "life_event": "life event",
}

# Bidi isolates: Gmail wraps subject fragments in them, and they hide the text
# from every pattern below unless they come off first.
_BIDI = dict.fromkeys(map(ord, "⁦⁧⁨⁩‎‏‪‫‬"), None)

# A composed sentence is long. Below this, the value is short enough to be a
# subject line and has to earn its place.
_COMPOSED_WORDS = 12

# Words that carry no referent even when a subject line capitalises them.
_SCAFFOLDING = frozenset("""a an the your you my our we us it its this that new now today
    tomorrow and or for from with to of on at in is are was were has have been be
    i he she they them their there here""".split())

_QUOTED = re.compile(r"[\"“”']([^\"“”']{4,})[\"“”']")
_WORD = re.compile(r"[A-Za-z][\w'&-]*")
# An explicit date. A bare digit is deliberately not enough — see _names_a_thing.
_DATE = re.compile(r"\b(?:\d{4}-\d{2}-\d{2}|\d{1,2}[/-]\d{1,2}[/-]\d{2,4}"
                   r"|jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)\w*\b", re.I)


def normalise(value: object) -> str:
    """The text a rule should look at: bidi marks gone, unicode folded."""
    return unicodedata.normalize("NFKC", str(value or "").translate(_BIDI)).strip()


def _significant(text: str) -> list:
    return [w for w in _WORD.findall(text) if w.lower().strip(".,") not in _SCAFFOLDING]


def _is_title_cased(words: list) -> bool:
    """A subject line is Title Cased; a sentence someone wrote is not.

    Two significant words is enough ("New Message"), and the threshold is a
    proportion so one lower-case preposition does not rescue a heading."""
    if len(words) < 2:
        return False
    return sum(1 for w in words if w[0].isupper()) / len(words) >= 0.8


def _names_a_thing(text: str) -> bool:
    """A referent strong enough to outrank the Title Case test.

    A quoted title or an explicit date names something no matter how the rest is
    capitalised — "Appointment with Pat Testley — 2025-03-10 — 3195 California
    Street" is Title Cased and is still a fact. A bare digit is NOT enough:
    "Delivered 1 item: Clothing" counts an item without naming one."""
    return bool(_QUOTED.search(text) or _DATE.search(text))


def _names_anything(text: str, words: list) -> bool:
    """Is there any specific referent at all?

    The first word does not count on its own: every sentence capitalises it."""
    if _names_a_thing(text):
        return True
    return any(w[0].isupper() for w in words[1:])


def states_what_happened(value: object, predicate: str = "") -> bool:
    """Whether this value says WHAT happened, rather than that something did.

    Answers True for any predicate that is not an event predicate: the question
    does not apply to `phone` or `birthday`. Answers True when it cannot tell."""
    if predicate and predicate not in EVENT_PREDICATES:
        return True
    text = normalise(value)
    if not text:
        return False
    words = _significant(text)
    if len(words) >= _COMPOSED_WORDS:
        return True                      # a composed sentence, not a heading
    if _names_a_thing(text):
        return True                      # a quoted title or a date outranks the shape
    if _is_title_cased(words):
        return False                     # a subject line
    return _names_anything(text, words)


def refusal(value: object, predicate: str = "") -> str:
    """Why this value is not a memory, for a log line. "" when it is one."""
    if states_what_happened(value, predicate):
        return ""
    text = normalise(value)
    if not text:
        return "empty value"
    if _is_title_cased(_significant(text)):
        return "a subject line, not a fact: %r" % text[:80]
    return "says something happened but not what: %r" % text[:80]
