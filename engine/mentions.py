"""Cross-source identity: which records involve which entity.

Answers "is this the same entity?" with identifiers, never with names. A record
(an email, a message thread, a calendar event) is linked to an entity only when
a hard identifier in it matches exactly ONE entity: an email address, a phone
number, or an id the entity already owns. A shared name is a coincidence, not
an identity: two different people can carry one name, and that match is left
to review (link_candidates), never applied here.

An identifier that matches two or more entities links neither. It is evidence
that those entities may be one, and it is reported as a duplicate candidate.

Configuration (`mentions` in the memory config):

  mentions:
    self: [addresses and numbers belonging to the store's owner]  # never a mention
    entity_sources:            # where entities' identifiers live
      - path: ...; table: ...; id_column: id
        keys: {email: [col, ...], phone: [col, ...], grn: [col, ...]}
        extra: [{table: ..., fk: contact_id, kind: email|phone, column: value}]
    record_sources:            # records to scan; ids must match their pointers
      - provider: mail; path: ...; table: ...; id_column: id; where: "<sql>"
        fields: {sender: email, recipient: email}

The result is a rebuildable index (`entity_mentions`), not beliefs: it is
derived entirely from the sources and can be dropped and rebuilt at any time.
"""
from __future__ import annotations

import re
import sqlite3
from collections import defaultdict
from datetime import datetime, timezone

EMAIL_RE = re.compile(r"[A-Za-z0-9._%+'-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
PHONE_RE = re.compile(r"\+?\d[\d\s().-]{6,}\d")
STREET_RE = re.compile(
    r"\b(\d{1,6}[a-z]?)\s+((?:[a-z0-9'.-]+\s+){0,4}?)"
    r"(st|street|ave|avenue|blvd|boulevard|rd|road|dr|drive|way|ln|lane|pl|place|ct|court|"
    r"pkwy|parkway|hwy|highway|ter|terrace|cir|circle|sq|square|aly|alley|plz|plaza)\b")
SUFFIX = {"street": "st", "avenue": "ave", "boulevard": "blvd", "road": "rd", "drive": "dr",
          "lane": "ln", "place": "pl", "court": "ct", "parkway": "pkwy", "highway": "hwy",
          "terrace": "ter", "circle": "cir", "square": "sq", "alley": "aly", "plaza": "plz"}
URL_HOST_RE = re.compile(r"(?:https?://)?(?:www\.)?([a-z0-9.-]+\.[a-z]{2,})", re.I)

MENTIONS_DDL = """
CREATE TABLE IF NOT EXISTS entity_mentions (
    entity_id TEXT NOT NULL, external_ref TEXT NOT NULL, provider TEXT NOT NULL,
    role TEXT NOT NULL, method TEXT NOT NULL, key TEXT, created_at TEXT,
    PRIMARY KEY (entity_id, external_ref, role));
CREATE INDEX IF NOT EXISTS idx_mentions_ref ON entity_mentions(external_ref);
CREATE INDEX IF NOT EXISTS idx_mentions_provider ON entity_mentions(provider);
"""


def emails(text) -> set:
    return {m.lower().strip(".") for m in EMAIL_RE.findall(str(text or ""))}


def phone_key(text):
    """A comparable key for one phone number: its digits, with a leading US
    country code removed so +1 415 555 0100 and (415) 555-0100 meet."""
    d = re.sub(r"\D", "", str(text or ""))
    if len(d) == 11 and d.startswith("1"):
        d = d[1:]
    return d if len(d) >= 7 else None


def phones(text) -> set:
    return {k for k in (phone_key(m) for m in PHONE_RE.findall(str(text or ""))) if k}


def addresses(text) -> set:
    """Street-address keys: house number + street + normalized suffix. City-free
    by design (records rarely agree on how they write the city); a building that
    houses several places is caught later as an identifier shared by several."""
    out = set()
    for num, street, suf in STREET_RE.findall(str(text or "").lower()):
        street = re.sub(r"\s+", " ", re.sub(r"[^a-z0-9 ]", "", street)).strip()
        if street:
            out.add("%s %s %s" % (num, street, SUFFIX.get(suf, suf)))
    return out


def domains(text) -> set:
    return {m.lower().strip(".") for m in URL_HOST_RE.findall(str(text or ""))}


def keys_of(value, kind) -> set:
    """Typed identifier keys in one field value."""
    if kind == "email":
        return {"e:" + e for e in emails(value)}
    if kind == "phone":
        return {"p:" + p for p in phones(value)}
    if kind == "handle":                      # a phone number or an address
        return keys_of(value, "email") | keys_of(value, "phone")
    if kind == "address":
        return {"a:" + a for a in addresses(value)}
    if kind == "domain":
        return {"w:" + d for d in domains(value)}
    if kind == "grn":
        v = str(value or "").strip()
        return {"g:" + v} if v else set()
    if kind == "id":
        v = str(value or "").strip()
        return {"i:" + v} if v else set()
    raise ValueError("unknown identifier kind %r" % kind)


def _ro(path):
    return sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=10)


def _q(name):
    return '"%s"' % str(name).replace('"', '""')


class Resolver:
    def __init__(self, cfg):
        ident = (cfg.get("mentions", {}) if hasattr(cfg, "get") else {}) or {}
        self.entity_sources = ident.get("entity_sources") or []
        self.record_sources = ident.get("record_sources") or []
        self.link_sources = ident.get("link_sources") or []
        self.self_keys = set()
        for v in ident.get("self") or []:
            self.self_keys |= keys_of(v, "handle")
        self.key_to_entities = defaultdict(set)
        self.entity_count = 0

    # -- entities --------------------------------------------------------------
    def load_entities(self):
        """key -> {entity ids}. Every entity also owns the key 'i:<its id>'."""
        for src in self.entity_sources:
            conn = _ro(src["path"])
            try:
                idc = src.get("id_column", "id")
                cols = {kind: list(c) for kind, c in (src.get("keys") or {}).items()}
                wanted = [idc] + [c for cs in cols.values() for c in cs]
                sql = "SELECT %s FROM %s" % (", ".join(_q(c) for c in wanted), _q(src["table"]))
                for row in conn.execute(sql):
                    eid = src.get("id_prefix", "") + str(row[0])
                    self.entity_count += 1
                    self.key_to_entities["i:" + eid].add(eid)
                    i = 1
                    for kind, cs in cols.items():
                        for _c in cs:
                            for k in keys_of(row[i], kind):
                                if k not in self.self_keys:
                                    self.key_to_entities[k].add(eid)
                            i += 1
                for ex in src.get("extra") or []:
                    sql = "SELECT %s, %s FROM %s" % (_q(ex["fk"]), _q(ex["column"]), _q(ex["table"]))
                    for fk, val in conn.execute(sql):
                        for k in keys_of(val, ex["kind"]):
                            if k not in self.self_keys:
                                self.key_to_entities[k].add(src.get("id_prefix", "") + str(fk))
            finally:
                conn.close()
        return self

    @staticmethod
    def _store(eid):
        """The store an entity id comes from ('' for unprefixed ids)."""
        return eid.split(":", 1)[0] if ":" in eid else ""

    def duplicates(self):
        """Identifiers shared by several entities of ONE store: possible duplicates
        within it, as (key, sorted entity ids)."""
        return sorted((k, sorted(e)) for k, e in self.key_to_entities.items()
                      if len(e) > 1 and not k.startswith("i:")
                      and len({self._store(x) for x in e}) == 1)

    def same_as(self, now):
        """Exactly two entities from two DIFFERENT stores sharing an identifier are
        one thing held twice (a merchant and a venue at one address): link each to
        the other. More than two is a shared building or brand -- nothing linked."""
        rows = []
        for k, ents in self.key_to_entities.items():
            if k.startswith("i:") or len(ents) != 2:
                continue
            a, b = sorted(ents)
            sa, sb = self._store(a), self._store(b)
            if sa and sb and sa != sb:
                m = self.METHOD[k.split(":", 1)[0]]
                rows.append((a, b, sb, "same_as", m, k, now))
                rows.append((b, a, sa, "same_as", m, k, now))
        return rows

    # -- records ---------------------------------------------------------------
    def scan(self, src):
        """Yield (entity_id, external_ref, role, method, key) for one record source,
        and count identifiers that matched several entities (ambiguous)."""
        provider, idc = src["provider"], src.get("id_column", "id")
        fields = src.get("fields") or {}
        conn = _ro(src["path"])
        self.ambiguous = 0
        try:
            sql = "SELECT %s, %s FROM %s" % (_q(idc), ", ".join(_q(f) for f in fields), _q(src["table"]))
            if src.get("where"):
                sql += " WHERE " + src["where"]
            for row in conn.execute(sql):
                ref = "%s:%s" % (provider, row[0])
                seen = set()
                for i, (field, kind) in enumerate(fields.items(), start=1):
                    for k in keys_of(row[i], kind):
                        if k in self.self_keys:
                            continue
                        ents = self.key_to_entities.get(k)
                        if not ents:
                            continue
                        # One entity, or exactly two from two different stores (one
                        # thing held twice, see same_as): link. Anything else is shared
                        # by several things and links none of them.
                        stores = {self._store(x) for x in ents}
                        if len(ents) > 1 and not (len(ents) == 2 and len(stores) == 2 and "" not in stores):
                            self.ambiguous += 1
                            continue
                        for eid in sorted(ents):
                            if (eid, field) in seen:
                                continue
                            seen.add((eid, field))
                            yield eid, ref, field, k.split(":", 1)[0], k
        finally:
            conn.close()

    METHOD = {"e": "email", "p": "phone", "g": "grn", "i": "id", "a": "address", "w": "domain"}

    def rows_for(self, src, now):
        return [(e, r, src["provider"], role, self.METHOD[m], k, now) for e, r, role, m, k in self.scan(src)]

    def linked(self, src, now):
        """Pairs a domain store already decided (its own resolution, trusted as
        given): `sql` returns (entity suffix, record id, method)."""
        conn = _ro(src["path"])
        try:
            for alias, path in (src.get("attach") or {}).items():
                conn.execute("ATTACH DATABASE ? AS %s" % _q(alias), ("file:%s?mode=ro" % path,))
            return [(src.get("entity_prefix", "") + str(e), "%s:%s" % (src["provider"], r),
                     src["provider"], src.get("role", "link"), str(m), None, now)
                    for e, r, m in conn.execute(src["sql"])]
        finally:
            conn.close()

    def rebuild_all(self, chron_conn, dry_run=False) -> dict:
        """Every configured source, grouped by provider, each provider replaced
        atomically. Idempotent. Returns {provider: (links, ambiguous identifier hits)}."""
        now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        by_provider, ambiguous = defaultdict(list), defaultdict(int)
        for src in self.record_sources:
            by_provider[src["provider"]] += self.rows_for(src, now)
            ambiguous[src["provider"]] += self.ambiguous
        for src in self.link_sources:
            by_provider[src["provider"]] += self.linked(src, now)
        for row in self.same_as(now):
            by_provider[row[2]].append(row)
        if not dry_run:
            with chron_conn:
                for prov, rows in by_provider.items():
                    chron_conn.execute("DELETE FROM entity_mentions WHERE provider=?", (prov,))
                    chron_conn.executemany("INSERT OR IGNORE INTO entity_mentions VALUES (?,?,?,?,?,?,?)", rows)
        return {p: (len(r), ambiguous[p]) for p, r in by_provider.items()}


def ensure_schema(conn):
    conn.executescript(MENTIONS_DDL)
