"""
Chronicle — a credential is not a memory.

Users hand the agent logins to use: "Login: <name> password: <value> for
<site>", "Soulseek data: Username: … Password: …". On a production store the
extractor turned both of those messages into EPISODES -- beliefs, which the
per-turn recall puts into later prompts unasked and the dashboard shows. The
message itself stays in the transcript (explicit search still finds it for
the agent that was given it); what this module stops is a belief carrying the
value, and a turn's unasked recall repeating it.

Detection is by shape, two kinds:

  * a LABELLED value -- password / passcode / PIN / API key / token / secret /
    private key / auth code / OTP, then ":", "=" or "is", then a value that
    looks like one (6+ characters with a digit, a symbol or mixed case; for a
    PIN or code, 4+ digits). "The full password is not in the log" names no
    value and is left alone;
  * a KEY-SHAPED token on its own (sk-…, ghp_…, github_pat_…, xox?-…, AKIA…,
    AIza…).

It errs toward leaving text alone: a false positive drops a real memory, and
the transcript still holds anything this misses.
"""

from __future__ import annotations

import re

_LABEL = (r"pass(?:word|wd|phrase|code)?|pwd|pin|api[ _-]?key|secret|(?:access[ _-]?|auth[ _-]?)?token"
          r"|access[ _-]?key|private[ _-]?key|auth(?:entication)?[ _-]?code|otp|2fa[ _-]?code")
_LABELLED = re.compile(r"(?i)\b(%s)\b\s*(?:[:=]|\bis\b)\s*[\"'`]?([^\s\"'`]+)" % _LABEL)
_KEY_SHAPED = re.compile(r"\b(?:sk-[A-Za-z0-9_-]{16,}|ghp_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,}"
                         r"|xox[abprs]-[A-Za-z0-9-]{10,}|AKIA[0-9A-Z]{16}|AIza[0-9A-Za-z_-]{30,})")
_NUMERIC_LABELS = ("pin", "otp", "code")
REDACTED = "[redacted]"


def _looks_secret(label: str, value: str) -> bool:
    v = value.strip(".,;:!?)]}")
    if label.lower().endswith(_NUMERIC_LABELS) and v.isdigit():
        return len(v) >= 4
    if len(v) < 6:
        return False
    return (any(c.isdigit() for c in v) or any(not c.isalnum() for c in v)
            or (any(c.isupper() for c in v[1:]) and any(c.islower() for c in v)))


def spans(text: str) -> list:
    """(start, end) of every credential value in `text`, in order."""
    text = text or ""
    out = [(m.start(2), m.start(2) + len(m.group(2).rstrip(".,;:!?)]}")))
           for m in _LABELLED.finditer(text) if _looks_secret(m.group(1), m.group(2))]
    out += [(m.start(), m.end()) for m in _KEY_SHAPED.finditer(text)]
    return sorted(set(out))


def contains_secret(text: str) -> bool:
    return bool(spans(text))


def redact(text: str) -> str:
    """`text` with every credential value replaced by [redacted]."""
    found = spans(text)
    if not found:
        return text
    out, at = [], 0
    for a, b in found:
        if a < at:
            continue
        out.append(text[at:a])
        out.append(REDACTED)
        at = b
    out.append(text[at:])
    return "".join(out)
