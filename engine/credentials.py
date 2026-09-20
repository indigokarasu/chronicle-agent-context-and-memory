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

# THE SENTINEL IS HERMES', NOT OURS. The host already had one and Chronicle had
# invented a second: `agent/redact.py` masks to «redacted-secret»,
# «redacted:ghp_…» (prefix matched, vendor label kept) and
# «redacted-vault-secret», and its own "already masked?" guards test
# `value.startswith("«redacted")` and `"***" in value`. `[redacted]` matched
# neither, so a host redaction pass did not recognise Chronicle's output as
# masked and could mask it again.
#
# The SHAPE is load-bearing, and the reason is in Hermes' own docstring for
# _mask_token_nonreusable: "an agent once wrote a truncated-looking mask back
# into a config file", corrupting the stored credential (issue #35519). So the
# replacement must not be mistakable for a usable value. That is why the
# pointer goes INSIDE the sentinel rather than standing where the value stood:
# `«redacted:vault_ab12cd34ef56»` says which item to resolve and cannot be
# pasted back over the real one. The guillemets also keep masking idempotent
# for free -- a bare `vault_ab12cd34ef56` passes _looks_secret (letters,
# digits, six characters) and the next fold would re-mask our own pointer.
REDACTED = "«redacted-secret»"
SENTINEL = "«redacted:%s»"
_MARKER = "«redacted"

# WHAT A READER CAN DO ABOUT THE VALUE THAT IS GONE (Phase E).
#
# `[redacted]` is a dead end: an agent that finds it asks the user to type the
# secret again, which is how a secret gets into a transcript twice. A pointer
# says WHERE the value lives instead.
#
# Hermes has exactly two places a secret legitimately lives, both read from
# its source rather than invented (the spec was explicit that the form
# `secrets/<NAME>` was illustrative and must not be copied):
#
#   * the VAULT (agent/vault_store.py) -- encrypted, profile-scoped, kinds
#     login/payment/address, referenced by an opaque `vault_<12 hex>` id and
#     resolved server-side by resolve_secret();
#   * the profile `.env` -- provider API keys are environment variables, NOT
#     vault items (agent/credential_persistence.py).
#
# This module reads NEITHER. It cannot: the vault exists so that values never
# reach a tool result, and guessing which vault item a masked string was would
# be inventing a reference. All it does is KEEP THE POINTER THE TEXT WAS
# ALREADY CARRYING -- the env-var name the value was assigned to, the vault id
# quoted beside it, or the provider prefix the key itself announces. Nothing
# here reveals any part of a secret: an env-var name is not secret, a vault id
# is designed to be shown, and `sk-` is a vendor's public prefix.
_ENV_NAME = re.compile(r"\b([A-Z][A-Z0-9]*(?:_[A-Z0-9]+)+)\s*[:=]\s*[\"\'`]?$")
_VAULT_REF = re.compile(r"\bvault_[0-9a-f]{12}\b")
_KEY_PREFIX = re.compile(r"^(sk-|ghp_|github_pat_|xox[abprs]-|AKIA|AIza)")
_POINTER_LOOKBEHIND = 80


def _looks_secret(label: str, value: str) -> bool:
    # `[redacted` and not REDACTED: with `credentials.pointers` on the marker
    # is `[redacted env:NAME]`, so testing the whole bare marker let a second
    # pass re-mask its own output and append a second pointer. Masking has to
    # be idempotent -- the fold re-runs over beliefs it has already masked.
    if value.startswith(_MARKER):
        return False                     # already masked
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


def pointer_for(text: str, a: int, b: int) -> str:
    """Where the value at text[a:b] can be fetched from, or "".

    Read off the text itself, never from the vault or the environment -- see
    the note above _ENV_NAME. Order is by how specific the pointer is: a vault
    id names one item, an env-var name names one variable, a provider prefix
    only says what KIND of credential it was."""
    before = (text or "")[max(0, a - _POINTER_LOOKBEHIND):a]
    vault = _VAULT_REF.findall(before)
    if vault:
        return vault[-1]
    env = _ENV_NAME.search(before)
    if env:
        return "env:" + env.group(1)
    prefix = _KEY_PREFIX.match((text or "")[a:b])
    if prefix:
        # Hermes' own form for this case, ellipsis included: the vendor label
        # says what KIND of credential it was and the ellipsis says the rest
        # is gone. A pointer label is complete and carries no ellipsis.
        return prefix.group(1) + "\u2026"
    return ""


def redact(text: str, pointer: bool = True) -> str:
    """`text` with every credential value replaced by Hermes' sentinel.

    With `pointer` (on by default, `credentials.pointers`), the sentinel's
    label is where the value can be fetched from when the text said so --
    `«redacted:env:OPENROUTER_API_KEY»`, `«redacted:vault_ab12cd34ef56»`.
    Without it, or with nothing in the text to point at, the label is the
    vendor prefix (`«redacted:ghp_…»`) or absent (`«redacted-secret»`).

    The label is INSIDE the sentinel, never in place of the value: a bare
    pointer reads as a usable string and an agent that round-trips a config
    writes it back over the real credential -- Hermes issue #35519, and the
    reason its own masks are non-reusable by construction."""
    found = spans(text)
    if not found:
        return text
    out, at = [], 0
    for a, b in found:
        if a < at:
            continue
        out.append(text[at:a])
        ref = pointer_for(text, a, b) if pointer else ""
        out.append(SENTINEL % ref if ref else REDACTED)
        at = b
    out.append(text[at:])
    return "".join(out)
