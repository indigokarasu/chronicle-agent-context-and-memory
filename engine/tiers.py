"""
Chronicle — what may be summarised, and what may only be pointed at.

Compaction has one lossy step: a span too big for the budget is cut and gets an
id that restores it. Cutting by length alone is indifferent to what it cuts, so
the thing a reader cannot reconstruct -- a port number, a path, a container id,
the exact command that failed -- is as likely to go as the prose around it,
while the store still holds every byte.

This module says which is which, by shape and deterministically:

  INVOLATILE  an exact literal: an IP, a path, a URL, an id, a timestamp, a
              number with a unit, a quoted string, a command line. Never
              paraphrased, never truncated: kept byte-exact, or (a secret)
              replaced by its pointer -- engine/credentials.py decides that,
              not this module.
  CRITICAL    load-bearing prose: a decision, a standing directive, the
              request in hand. May be distilled, must survive in some form.
  CONTEXT     background. Folded and summarised freely.
  POINTER     nothing is kept inline; the fold id stands in for it.

Only the involatile tier is this module's business to detect -- it is the one
a rule can get right, and the one whose loss is silent. The critical/context
boundary is a judgement call and stays with the caller (the context engine's
salience score), which is why there is no model call anywhere in here.

`shorten_keeping_literals(text, cap)` is the point of it: the same budget,
spent on the literals first and the prose second.
"""

from __future__ import annotations

import re

from . import credentials as _cred

INVOLATILE = "involatile"
CRITICAL = "critical"
CONTEXT = "context"
POINTER = "pointer"

# Each pattern names one kind of exact literal. Order matters only for
# reporting: the spans are merged before use.
_LITERALS = (
    ("url", re.compile(r"\b(?:https?|ftp|ssh|git)://[^\s'\"<>）)]+")),
    ("ipv4", re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}(?::\d{1,5})?\b")),
    ("ipv6", re.compile(r"\b(?:[0-9a-f]{1,4}:){2,7}[0-9a-f]{1,4}\b", re.I)),
    # A path with at least two segments, or any ~/… or ./… form.
    ("path", re.compile(r"(?:(?<=\s)|^|(?<=[\"'(=]))(?:~|\.{1,2})?/[\w.@+-]+(?:/[\w.@+-]+)+/?")),
    ("winpath", re.compile(r"\b[A-Za-z]:\\[\w\\.@+-]+")),
    # uuid, git sha, hex blob, chronicle/hermes ids, container ids
    ("id", re.compile(r"\b(?:[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}"
                      r"|[0-9a-f]{7,64}|(?:b_|ev_|fold_|vault_|proc_|cron_)[0-9a-zA-Z_]{6,})\b")),
    ("timestamp", re.compile(r"\b\d{4}-\d{2}-\d{2}(?:[T ]\d{2}:\d{2}(?::\d{2})?(?:\.\d+)?Z?"
                             r"(?:[+-]\d{2}:?\d{2})?)?\b")),
    ("clock", re.compile(r"\b\d{1,2}:\d{2}(?::\d{2})?\s?(?:am|pm)?\b", re.I)),
    # a number that means something: with a unit, a percentage, or money
    ("measure", re.compile(r"(?<![\w.])(?:[$£€]\s?\d[\d,]*(?:\.\d+)?"
                           r"|\d[\d,]*(?:\.\d+)?\s?(?:%|ms|s|sec|secs|m|min|mins|h|hr|hrs|d|days?"
                           r"|[KMGT]?B|[KMGT]i?B|kb|mb|gb|tb|px|rpm|rps|qps|x))(?![\w.])", re.I)),
    ("exit", re.compile(r"\b(?:exit(?:\s+code)?|status|errno|HTTP)\s+\d{1,3}\b", re.I)),
    # A bare number that a word makes exact: port 8688, pid 344953, line 412.
    ("counted", re.compile(r"\b(?:port|pid|ppid|line|lines|row|rows|col|column|chunk|page|issue|pr|run|build"
                           r"|attempt|retry|version|v|step|turn|seq|id)\s*#?\s*\d+\b", re.I)),
    ("quoted", re.compile(r"[\"“]([^\"”\n]{3,120})[\"”]|'([^'\n]{3,120})'")),
    ("flag", re.compile(r"(?<!\w)--?[A-Za-z][\w-]{1,30}(?:=[\w./:+-]+)?")),
    ("env", re.compile(r"\b[A-Z][A-Z0-9_]{3,40}=[^\s]+")),
)

# A command written into prose ("I ran docker compose up -d --force-recreate dn"):
# a known binary and the arguments after it, to the end of the clause.
_INLINE_COMMAND = re.compile(
    r"\b(?:sudo\s+)?(?:git|docker(?:\s+compose)?|systemctl|journalctl|curl|wget|ssh|scp|rsync|python3?|pip3?"
    r"|npm|pnpm|yarn|node|psql|sqlite3|grep|rg|awk|sed|tar|find|kill|pkill|chmod|chown|mkdir|rm|cp|mv"
    r"|tail|head|make|cargo|brew|apt(?:-get)?|launchctl|crontab)"
    r"(?:\s+(?!and\b|the\b|then\b|so\b|but\b|which\b|that\b)[\w./:=@+~-]+){1,12}")


# A line that IS a command: a shell prompt, or a known verb at its head.
_COMMAND_LINE = re.compile(
    r"^\s*(?:[$#>]\s+\S.*"
    r"|(?:sudo\s+)?(?:git|docker|systemctl|journalctl|curl|wget|ssh|scp|rsync|python3?|pip3?|npm|pnpm|yarn"
    r"|node|psql|sqlite3|grep|rg|awk|sed|tar|find|kill|pkill|chmod|chown|mkdir|rm|cp|mv|ls|cat|tail|head"
    r"|make|cargo|go|brew|apt|apt-get|launchctl|crontab)\b.*)$", re.M)

_DECISION = re.compile(
    r"\b(?:decided|decision|we(?:'ll| will)|going to|chose|choosing|agreed|plan is|instead of|"
    r"root cause|because|so that|therefore|conclusion|turns out)\b", re.I)


def involatile_spans(text: str) -> list:
    """`[(start, end, kind)]` of every exact literal in `text`, merged and in
    order. A credential's value is a literal too, and the only one that must
    not be kept: engine/credentials.py masks it before anything here runs."""
    text = text or ""
    found = []
    for kind, rx in _LITERALS:
        for m in rx.finditer(text):
            found.append((m.start(), m.end(), kind))
    for rx, kind in ((_COMMAND_LINE, "command"), (_INLINE_COMMAND, "command")):
        for m in rx.finditer(text):
            if m.group().strip():
                found.append((m.start(), m.end(), kind))
    if not found:
        return []
    # A literal does not own the punctuation that ends the sentence around it.
    trimmed = []
    for a, b, kind in found:
        while b - 1 > a and text[b - 1] in ".,;:!?" and not (kind == "quoted" and text[b - 1] in "\"'"):
            b -= 1
        trimmed.append((a, b, kind))
    found = sorted(trimmed)
    merged = [found[0]]
    for a, b, kind in found[1:]:
        pa, pb, pkind = merged[-1]
        if a <= pb:                          # overlapping literals become one span
            merged[-1] = (pa, max(pb, b), pkind if pb - pa >= b - a else kind)
        else:
            merged.append((a, b, kind))
    return merged


def literals(text: str) -> list:
    """The exact literals of `text`, as strings, in order."""
    return [text[a:b] for a, b, _k in involatile_spans(text)]


def classify(text: str, *, required: bool = False, directive: bool = False) -> str:
    """The tier of one unit. `required` marks what the caller already knows it
    must keep (the newest request, a pinned span); `directive` marks a standing
    instruction. Everything else is involatile if it carries exact literals,
    else context -- the critical/context judgement above that belongs to the
    caller's own score, not to a regex."""
    text = text or ""
    if not text.strip():
        return POINTER
    if required or directive:
        return CRITICAL
    if involatile_spans(text):
        return INVOLATILE
    if _DECISION.search(text):
        return CRITICAL
    return CONTEXT


def shorten_keeping_literals(text: str, cap: int) -> str:
    """`text` cut to about `cap` characters, spending the budget on the exact
    literals first and the prose second.

    The head of the text is kept (it says what the span is about), then every
    literal that still fits, in order, joined by " … " where prose was dropped.
    Returns the text unchanged when it already fits. A cut that cannot even
    hold the literals keeps as many as fit -- and the caller's fold id still
    restores the whole thing.
    """
    text = text or ""
    if cap <= 0 or len(text) <= cap:
        return text
    spans = involatile_spans(text)
    if not spans:
        return text[:cap]
    head_room = max(0, min(cap // 3, spans[0][0]))
    out, used, last_end = [], 0, 0
    if head_room:
        head = text[:head_room]               # keep its trailing space: the literal follows it
        out.append(head)
        used, last_end = len(head), head_room
    for a, b, _kind in spans:
        piece = text[a:b]
        need = len(piece) + (3 if out else 0)
        if used + need > cap:
            break
        if out and a > last_end:
            gap = text[last_end:a]
            joiner = gap if len(gap) <= 3 and gap.strip("".join(" \t,;:")) == "" else " … "
            out.append(joiner)
            used += len(joiner)
        out.append(piece)
        used += len(piece)
        last_end = b
    if last_end < len(text) and out:
        out.append(" …")
    return "".join(out) if out else text[:cap]


def masked_and_shortened(text: str, cap: int) -> str:
    """What compaction should write for a span it cannot keep whole: no
    credential values, and the exact literals ahead of the prose."""
    return shorten_keeping_literals(_cred.redact(text or ""), cap)
