"""A map of what Chronicle holds and how to read it.

Built offline from the store and the federation config, written to a small
file, and placed in the system prompt by the provider (`system_prompt_block`).
It tells an agent what it can look up -- that a question about a past
purchase, document, trip or message is a search, not a guess -- without the
agent needing to know which source database holds the answer.

It is built from counts, date spans and sync times only. It quotes no row
content, and the prompt never waits on the database for it: the provider reads
the file, not the store.
"""
from __future__ import annotations

import datetime as _dt
import os
import re
import sqlite3
import tempfile
from pathlib import Path

DEFAULT_MAX_CHARS = 2500
DEFAULT_RELATIVE = ("commons", "data", "chronicle", "chronicle.cache.md")

_ISO_GLOB = "[12][0-9][0-9][0-9]-[01][0-9]-[0-3][0-9]*"
_DATEISH = re.compile(r"date|(^|_)days?($|_)|_at$|_on$")
_DESCRIPTIVE = re.compile(r"date|day")
_SEMANTIC_NOTE_BELOW = 0.95   # say how much is searchable by meaning below this


def resolve_path(hermes_home, cfg) -> str:
    """The map file: `cache_map.path` when set, else under `hermes_home`."""
    p = (cfg.get("cache_map.path", "") if cfg is not None else "") or ""
    if p:
        return os.path.expanduser(str(p))
    return str(Path(hermes_home or ".").joinpath(*DEFAULT_RELATIVE))


def _ro(path):
    return sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=10)


def _date_span(path, table, declared, override=None):
    """(first, last) ISO dates for a source table, or None.

    `override` names the one column to use; an empty string means the source
    has no meaningful date. Otherwise the first date-like column holding ISO
    values wins, preferring a *date*/*day* column over a bookkeeping *_at one,
    and declared content columns over the rest. Values that are not ISO dates
    (an RFC 2822 header, a free-text field) are ignored rather than compared
    as strings."""
    if override == "" or override is False:
        return None
    try:
        conn = _ro(path)
    except sqlite3.Error:
        return None
    try:
        cols = [r[1] for r in conn.execute(f'PRAGMA table_info("{table}")')]
        if override:
            ranked = [override] if override in cols else []
        else:
            ranked = [c for c in declared if c in cols and _DATEISH.search(c)]
            ranked += [c for c in cols if c not in ranked and _DATEISH.search(c)]
            ranked.sort(key=lambda c: 0 if _DESCRIPTIVE.search(c) else 1)
        for c in ranked:
            row = conn.execute(
                f'SELECT min(substr("{c}",1,10)), max(substr("{c}",1,10)) '
                f'FROM "{table}" WHERE "{c}" GLOB ?', (_ISO_GLOB,)).fetchone()
            if row and row[0]:
                return row[0], row[1]
    except sqlite3.Error:
        return None
    finally:
        conn.close()
    return None


def _month(d):
    return (d or "")[:7]


def build(chronicle_db, cfg, now=None) -> str:
    """The map text. Read-only against the store and every source database."""
    now = now or _dt.datetime.now(_dt.timezone.utc)
    fed = cfg.get("federation.local_dbs", []) or []
    meta_all = cfg.get("cache_map.sources", {}) or {}
    max_chars = int(cfg.get("cache_map.max_chars", DEFAULT_MAX_CHARS))

    c = _ro(chronicle_db)
    try:
        pointers = dict(c.execute("SELECT provider, count(*) FROM pointers GROUP BY provider"))
        # Records WITH a vector, not rows: a record's passage vectors
        # ("<id>#p<n>", engine/passages.py) share its table, and counting them
        # would report a source 100% searchable while most records have none.
        vectors = dict(c.execute(
            "SELECT v.provider, count(*) FROM projection_vectors v WHERE EXISTS "
            "(SELECT 1 FROM pointers p WHERE p.provider=v.provider "
            "AND p.external_id=v.external_id) GROUP BY v.provider"))
        synced = dict(c.execute("SELECT db_name, last_sync_at FROM federation_watermarks"))
        facts = c.execute("SELECT count(*) FROM facts WHERE status='active'").fetchone()[0]
        kinds = [r[0] for r in c.execute(
            "SELECT attribute FROM facts WHERE status='active' AND attribute IS NOT NULL "
            "GROUP BY attribute ORDER BY count(*) DESC LIMIT 7")]
        sessions, since = c.execute(
            "SELECT count(DISTINCT session_id), min(occurred_at) FROM events").fetchone()
    finally:
        c.close()

    out = [f"## What Chronicle holds (as of {now:%Y-%m-%d})", "",
           "Chronicle is long-term memory: what the user and you have said, what it "
           "has learned, and the user's connected records. All of it is searchable "
           "through one tool.", ""]

    for d in fed:
        name = (d or {}).get("name")
        n = pointers.get(name, 0) if name else 0
        if not n:
            continue
        meta = meta_all.get(name) or {}
        label = meta.get("label") or name
        unit = meta.get("unit") or "items"
        line = f"- {label}: {n:,} {unit}"
        span = _date_span(d.get("path"), d.get("table"), d.get("content_columns") or [],
                          meta.get("date_column"))
        if span:
            line += f", {_month(span[0])} to {_month(span[1])}"
        if synced.get(name):
            line += f" (updated {str(synced[name])[:10]})"
        if meta.get("about"):
            line += f". {str(meta['about']).rstrip('.')}."
        v = vectors.get(name, 0)
        if v and v / n < _SEMANTIC_NOTE_BELOW:
            line += f" {100 * v // n}% searchable by meaning so far; the rest by exact words."
        out.append(line)

    if facts:
        what = ", ".join(k.replace("_", " ") for k in kinds)
        out.append(f"- Remembered facts: {facts:,}" + (f", most often {what}." if what else "."))
    if sessions:
        out.append(f"- Conversations with you: {sessions:,} sessions"
                   + (f" since {str(since)[:10]}." if since else "."))

    out += ["", "How to use it:",
            "- For anything about the user's past or records -- people, places, trips, "
            "purchases, documents, messages, plans -- call chronicle_search with a plain "
            "question. It searches everything above at once; you never choose a source. "
            "Each result names its source in [brackets].",
            "- For a person, place or business, call chronicle_ask_about with its name: what is "
            "known about it and its most recent records -- messages, emails, calendar events, "
            "purchases -- linked by exact email, phone number, address or merchant record. If two "
            "share the name, both come back to choose from.",
            "- Search before saying you don't know something about the user's life. If "
            "nothing comes back, say so plainly; do not fill the gap with a guess.",
            "- Quote what a result says, with its date when it has one."]

    text, used = [], 0
    for line in out:                       # cut at a line, never mid-sentence
        if used + len(line) + 1 > max_chars:
            break
        text.append(line)
        used += len(line) + 1
    return "\n".join(text).strip() + "\n"


def write(path, text) -> None:
    """Replace the map file atomically, so a reader never sees half of it."""
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=".chronicle.cache.", dir=str(Path(path).parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(text)
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise
