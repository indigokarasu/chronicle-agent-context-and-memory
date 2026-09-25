"""
Chronicle — Local SQLite database provider (§14.1).

Generic read-only provider for any declared SQLite database. Supports arbitrary
schemas: introspects sqlite_master and PRAGMA table_info, exposes tables as
read-only data sources. Nothing here knows the name of any particular
deployment's database — every table, column and key is discovered at runtime.

Identity is never inferred (an external row is a *candidate* for adjudication,
never an automatic link to a Chronicle entity). External attributes are never
copied into facts: callers get a pointer + a rendered projection, and whatever
Chronicle chooses to believe *about* the row stays a Chronicle belief (I20).

Config federation.local_dbs declares available DBs:
    federation:
      local_dbs:
        - name: "somedb"          # provider name / capability for this DB
          path: "/path/to/db.db"  # SQLite file (uri mode=ro enforced)
          read_only: true         # required; a false value is refused
          read_acl: "user_agents" # optional; default DEFAULT_ACL (§15)

Pointers use external_id = "table:pk_value", capability = "declared_name" — the
same shape `resolve()` accepts, so a projection rendered by the federated
channel names a row that can be read back.

Safety notes for anyone editing the SQL below:
  * Every interpolated identifier goes through `quote_ident`. Table and column
    names come from a foreign database and may be reserved words (`order`),
    contain spaces, or contain quotes.
  * Every connection is opened `mode=ro` through a file: URI, and a missing file
    raises instead of silently creating an empty database.
  * Every connection is closed in a `finally`, and per-table work is wrapped
    per table, so one unreadable table cannot abort (or leak) the whole DB.
"""

from __future__ import annotations

import logging
import os
import sqlite3
from pathlib import Path
from typing import Any, Dict, List, Optional

from .federation import CapabilityProvider
from .access import DEFAULT_ACL, can_read

logger = logging.getLogger("chronicle.localdb")

# Bounds for the generic search path (§g3). Deliberately small: a federated read
# happens on the retrieval hot path against a database Chronicle does not own and
# cannot index, so the cost must be bounded by construction rather than by luck.
MAX_TABLES = 5
MAX_ROWS_PER_TABLE = 5
MAX_TEXT_COLUMNS = 12
MAX_TOKENS = 5
MAX_PROJECTION_CHARS = 350
MAX_VALUE_CHARS = 100
# Keys per IN-list in `lookup`: under SQLite's default variable limit (999 on
# older builds) with room to spare.
LOOKUP_CHUNK = 500
# Bounds for a folder-shaped container (§F10d, engine/passages.py). A query's
# focus tokens are matched against DECLARED path values, so the matcher must
# see them all up front (one bounded DISTINCT scan, not a table scan per
# candidate); the name list on a resulting card is capped separately so one
# huge folder cannot fill a caller's whole budget with filenames.
MAX_DISTINCT_VALUES = 2000
MAX_FOLDER_NAMES = 8

_LIKE_ESCAPE = "\\"


def quote_ident(name) -> str:
    """Quote an identifier for interpolation into SQL.

    SQLite identifier quoting is `"` with `""` as the embedded-quote escape. Used
    for EVERY table/column name reaching a statement: these names come from a
    foreign schema, so `order`, `group by`, and `we"ird` are all live cases.
    """
    return '"' + str(name).replace('"', '""') + '"'


def _like_escape(token) -> str:
    t = str(token)
    for ch in (_LIKE_ESCAPE, "%", "_"):
        t = t.replace(ch, _LIKE_ESCAPE + ch)
    return t


def like_pattern(token) -> str:
    """`%token%` with LIKE metacharacters escaped (paired with ESCAPE '\\')."""
    return "%" + _like_escape(token) + "%"


def like_prefix(token) -> str:
    """`token%` with LIKE metacharacters escaped (paired with ESCAPE '\\') --
    a PREFIX match, not a substring match. Used for a folder-shaped container
    read (`LocalDBProvider.folder_card`): a query for "Taxes/2026" must not
    also pull in an unrelated "Home/Old Taxes/2026" that merely contains it."""
    return _like_escape(token) + "%"


def is_text_column(decl_type) -> bool:
    """True for columns worth matching a text token against.

    SQLite type affinity rules: anything whose declared type contains CHAR, CLOB
    or TEXT has TEXT affinity. An empty declared type (a column declared with no
    type at all) is included because such columns overwhelmingly hold text in
    practice. Explicit BLOB columns are excluded — matching a token against
    binary is noise at best.
    """
    t = str(decl_type or "").upper()
    if not t:
        return True
    if "BLOB" in t:
        return False
    return ("CHAR" in t) or ("CLOB" in t) or ("TEXT" in t)


class LocalDBProvider(CapabilityProvider):
    """Read-only provider for a declared SQLite database file."""

    def __init__(self, name: str, db_path: str, read_acl: str = DEFAULT_ACL, table=None):
        self.name = name
        # The declared table (or view), when the entry names one: then it is
        # the whole searchable surface, and other tables in the file -- which
        # may belong to another application -- are never scanned.
        self.table = table or None
        self.capability = name
        self.db_path = str(db_path)
        self.read_acl = read_acl or DEFAULT_ACL
        self._schema = None            # {table: [{"name","type","pk"}]}
        self._manifest = None

    # -- connection --------------------------------------------------------

    def abspath(self) -> str:
        return str(Path(self.db_path).expanduser().resolve())

    def _connect(self) -> sqlite3.Connection:
        """Open a READ-ONLY connection, or raise.

        `mode=ro` is what makes "read only" true rather than merely intended: a
        plain sqlite3.connect() on a path that does not exist CREATES an empty
        database, which both hides a misconfiguration and writes to a filesystem
        location Chronicle was only ever asked to read. The explicit isfile()
        check turns that into an error a caller can log with the bad path in it,
        instead of sqlite's generic "unable to open database file".
        """
        path = self.abspath()
        if not os.path.isfile(path):
            raise sqlite3.OperationalError(
                "local db %r: no such file: %s" % (self.name, path))
        conn = sqlite3.connect(Path(path).as_uri() + "?mode=ro", uri=True, timeout=5)
        conn.row_factory = sqlite3.Row
        return conn

    def is_available(self) -> bool:
        """True iff the declared file exists (ACL is a separate check, per read)."""
        try:
            return os.path.isfile(self.abspath())
        except Exception:
            return False

    # -- introspection -----------------------------------------------------

    def schema(self) -> Dict[str, List[Dict]]:
        """{table: [{"name","type","pk"}]} for every ordinary table.

        Column metadata only — no COUNT(*), because this runs on the read path
        and counting an unindexed foreign table is unbounded work. `manifest()`
        keeps the counts for callers that actually want them.
        """
        if self._schema is not None:
            return self._schema
        try:
            conn = self._connect()
        except Exception as e:
            # Not cached: a database that is absent now may be present later,
            # and an empty schema must never harden into a permanent answer.
            logger.warning("localdb %s: cannot open %s: %s", self.name, self.db_path, e)
            return {}
        schema: Dict[str, List[Dict]] = {}
        try:
            try:
                rows = conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table' "
                    "AND name NOT LIKE 'sqlite\\_%' ESCAPE '\\' ORDER BY name").fetchall()
            except Exception as e:
                logger.warning("localdb %s: schema listing failed: %s", self.name, e)
                return {}
            if self.table:
                rows = conn.execute(
                    "SELECT name FROM sqlite_master WHERE type IN ('table', 'view') AND name=?",
                    (self.table,)).fetchall()
            for r in rows:
                table = r["name"]
                try:
                    cols = conn.execute(
                        "PRAGMA table_info(%s)" % quote_ident(table)).fetchall()
                except Exception as e:
                    # Scoped per table: an unreadable table costs that table only.
                    logger.warning("localdb %s: table %r skipped: %s", self.name, table, e)
                    continue
                schema[table] = [{"name": c["name"], "type": c["type"], "pk": c["pk"]}
                                 for c in cols]
        finally:
            conn.close()
        self._schema = schema
        return schema

    def manifest(self) -> Dict:
        """{tables: {name: {name, columns, pk, rowcount}}} (§14.1 manifest shape)."""
        if self._manifest is not None:
            return self._manifest
        schema = self.schema()
        if not schema:
            return {"tables": {}}
        try:
            conn = self._connect()
        except Exception as e:
            logger.warning("localdb %s: manifest failed: %s", self.name, e)
            return {"tables": {}}
        tables: Dict[str, Dict] = {}
        try:
            for table, columns in schema.items():
                pk_col = next((c["name"] for c in columns if c["pk"]), None)
                rowcount = 0
                try:
                    row = conn.execute(
                        "SELECT COUNT(*) AS cnt FROM %s" % quote_ident(table)).fetchone()
                    rowcount = row["cnt"] if row else 0
                except Exception as e:
                    logger.warning("localdb %s: count(%s) failed: %s", self.name, table, e)
                tables[table] = {"name": table, "columns": columns,
                                 "pk": pk_col, "rowcount": rowcount}
        finally:
            conn.close()
        self._manifest = {"tables": tables}
        return self._manifest

    def single_pk(self, table: str) -> Optional[str]:
        """The column name of a single-column primary key, else None.

        Composite keys return None: "table:pk_value" cannot address them, and a
        pointer that cannot address a row is worse than no pointer.
        """
        cols = self.schema().get(table) or []
        pks = [c["name"] for c in cols if c["pk"]]
        return pks[0] if len(pks) == 1 else None

    # -- reads -------------------------------------------------------------

    def iter_rows(self, table: str, since_rowid: int = 0, limit: int = 1000,
                  owner: str = "_user", principal: str = "_user") -> List[Dict]:
        """Rows from `table` after `since_rowid` (ACL-checked). Never raises."""
        if not can_read(self.read_acl, owner, principal):
            return []
        if table not in self.schema():
            logger.warning("localdb %s: iter_rows: table %r not found", self.name, table)
            return []
        try:
            conn = self._connect()
        except Exception as e:
            logger.warning("localdb %s: iter_rows(%s) failed: %s", self.name, table, e)
            return []
        try:
            q = quote_ident(table)
            try:
                rows = conn.execute(
                    "SELECT * FROM %s WHERE _rowid_ > ? LIMIT ?" % q,
                    (since_rowid, limit)).fetchall()
            except sqlite3.OperationalError:
                # WITHOUT ROWID table: no _rowid_ cursor exists. Degrade to a
                # plain bounded scan rather than dropping the table entirely.
                rows = conn.execute(
                    "SELECT * FROM %s LIMIT ?" % q, (limit,)).fetchall()
            return [dict(r) for r in rows]
        except Exception as e:
            logger.warning("localdb %s: iter_rows(%s) failed: %s", self.name, table, e)
            return []
        finally:
            conn.close()

    def get_row(self, table: str, pk_value, owner: str = "_user",
                principal: str = "_user") -> Optional[Dict]:
        """One row by primary key (ACL-checked). Never raises."""
        if not can_read(self.read_acl, owner, principal):
            return None
        if table not in self.schema():
            return None
        pk_col = self.single_pk(table)
        if not pk_col:
            logger.warning("localdb %s: get_row: %r has no single-column pk", self.name, table)
            return None
        try:
            conn = self._connect()
        except Exception as e:
            logger.warning("localdb %s: get_row(%s) failed: %s", self.name, table, e)
            return None
        try:
            row = conn.execute(
                "SELECT * FROM %s WHERE %s = ? LIMIT 1" % (quote_ident(table),
                                                           quote_ident(pk_col)),
                (pk_value,)).fetchone()
            return dict(row) if row else None
        except Exception as e:
            logger.warning("localdb %s: get_row(%s, %r) failed: %s",
                           self.name, table, pk_value, e)
            return None
        finally:
            conn.close()

    def lookup(self, table: str, key_column: str, keys, columns,
               owner: str = "_user", principal: str = "_user") -> Dict[str, Dict]:
        """{str(key): {column: value}} for the rows whose `key_column` is in
        `keys` -- one bounded IN-list statement per LOOKUP_CHUNK keys.

        The read that asks a source for a few columns of rows the caller already
        knows by id (a container key, a passage's text) at query time, instead
        of copying those columns into every cached projection. Keys come back
        as strings because callers hold ids from JSON while the source returns
        whatever its column affinity gives. The table and every column are
        checked against the introspected schema before any SQL is built, so a
        config naming a column that is not there reads nothing and says so.
        ACL-checked. Never raises."""
        out: Dict[str, Dict] = {}
        keys = [k for k in (keys or []) if k is not None]
        columns = [str(c) for c in (columns or []) if str(c)]
        if not keys or not columns:
            return out
        if not can_read(self.read_acl, owner, principal):
            return out
        known = set(c["name"] for c in (self.schema().get(table) or []))
        if not known:
            logger.warning("localdb %s: lookup: table %r not found", self.name, table)
            return out
        absent = [c for c in [key_column] + columns if c not in known]
        if absent:
            logger.warning("localdb %s: lookup: %r has no column(s) %s",
                           self.name, table, ", ".join(sorted(set(absent))))
            return out
        try:
            conn = self._connect()
        except Exception as e:
            logger.warning("localdb %s: lookup(%s) failed to open: %s", self.name, table, e)
            return out
        cols_sql = ", ".join(quote_ident(c) for c in [key_column] + columns)
        try:
            for i in range(0, len(keys), LOOKUP_CHUNK):
                part = keys[i:i + LOOKUP_CHUNK]
                sql = "SELECT %s FROM %s WHERE %s IN (%s)" % (
                    cols_sql, quote_ident(table), quote_ident(key_column),
                    ",".join("?" * len(part)))
                for r in conn.execute(sql, part).fetchall():
                    row = dict(zip([key_column] + columns, tuple(r)))
                    k = row.pop(key_column)
                    if k is not None:
                        out.setdefault(str(k), row)
            return out
        except Exception as e:
            logger.warning("localdb %s: lookup(%s) failed: %s", self.name, table, e)
            return out
        finally:
            conn.close()

    def distinct_values(self, table: str, column: str, limit: int = MAX_DISTINCT_VALUES,
                        owner: str = "_user", principal: str = "_user") -> List[str]:
        """Up to `limit` distinct non-empty values of one column, sorted.

        What a folder-path matcher needs before it can ask "does any declared
        folder match the query": the set of folders that exist at all. One
        bounded statement, schema-checked and ACL-checked like every other
        read here. Never raises."""
        out: List[str] = []
        if not can_read(self.read_acl, owner, principal):
            return out
        known = set(c["name"] for c in (self.schema().get(table) or []))
        if column not in known:
            logger.warning("localdb %s: distinct_values: %r has no column %r",
                           self.name, table, column)
            return out
        try:
            conn = self._connect()
        except Exception as e:
            logger.warning("localdb %s: distinct_values(%s) failed to open: %s",
                           self.name, table, e)
            return out
        try:
            c = quote_ident(column)
            rows = conn.execute(
                "SELECT DISTINCT %s AS v FROM %s WHERE %s IS NOT NULL AND %s <> '' "
                "ORDER BY v LIMIT ?" % (c, quote_ident(table), c, c),
                (int(limit),)).fetchall()
            return [r["v"] for r in rows if r["v"] is not None]
        except Exception as e:
            logger.warning("localdb %s: distinct_values(%s) failed: %s", self.name, table, e)
            return out
        finally:
            conn.close()

    def folder_card(self, table: str, column: str, folder_path: str, separator: str,
                    name_column: str = "", owner: str = "_user", principal: str = "_user",
                    max_names: int = MAX_FOLDER_NAMES) -> Optional[Dict]:
        """{path, file_count, names} for the rows filed at `folder_path` or
        nested under it -- `folder_path` itself, or any value that starts with
        `folder_path + separator` -- so a card for a shallow folder already
        counts everything in its subfolders instead of needing one card per
        level. One COUNT and one capped, ordered SELECT (name_column="" skips
        the second query and returns no names). Schema-checked, ACL-checked,
        never raises."""
        if not folder_path:
            return None
        if not can_read(self.read_acl, owner, principal):
            return None
        known = set(c["name"] for c in (self.schema().get(table) or []))
        if column not in known or (name_column and name_column not in known):
            logger.warning("localdb %s: folder_card: %r missing column(s)", self.name, table)
            return None
        try:
            conn = self._connect()
        except Exception as e:
            logger.warning("localdb %s: folder_card(%s) failed to open: %s", self.name, table, e)
            return None
        try:
            q, c = quote_ident(table), quote_ident(column)
            where = "(%s = ? OR %s LIKE ? ESCAPE '%s')" % (c, c, _LIKE_ESCAPE)
            params = [folder_path, like_prefix(folder_path + separator)]
            row = conn.execute("SELECT COUNT(*) AS n FROM %s WHERE %s" % (q, where),
                               params).fetchone()
            file_count = row["n"] if row else 0
            names: List[str] = []
            if name_column and file_count:
                nc = quote_ident(name_column)
                rows = conn.execute(
                    "SELECT %s AS v FROM %s WHERE %s ORDER BY %s LIMIT ?" %
                    (nc, q, where, nc), params + [int(max_names)]).fetchall()
                names = [str(r["v"]) for r in rows if r["v"] not in (None, "")]
            return {"path": folder_path, "file_count": file_count, "names": names}
        except Exception as e:
            logger.warning("localdb %s: folder_card(%s) failed: %s", self.name, table, e)
            return None
        finally:
            conn.close()

    def search(self, tokens, owner: str = "_user", principal: str = "_user",
               max_tables: int = MAX_TABLES, max_rows: int = MAX_ROWS_PER_TABLE) -> List[Dict]:
        """Rows where ANY text column LIKE ANY token — generic, bounded, read-only.

        One statement per table, at most `max_tables` tables, at most `max_rows`
        rows each. Returns pointer-shaped dicts:

            {provider, table, row_id, external_id, projection}

        `external_id` is "table:pk" when the table has a single-column primary
        key (so `resolve()` can read the row back) and "table:rowid=N" otherwise.
        Both are provenance: a projection with no row identity names a database,
        not a fact, and cannot be adjudicated or re-read.

        No result is ever linked to a Chronicle entity here — see
        `identity_candidate()`; matching text is a reason to *ask*, never a
        reason to merge.
        """
        out: List[Dict] = []
        toks = [t for t in (tokens or []) if str(t).strip()][:MAX_TOKENS]
        if not toks:
            return out
        if not can_read(self.read_acl, owner, principal):
            return out
        schema = self.schema()
        if not schema:
            return out
        try:
            conn = self._connect()
        except Exception as e:
            logger.warning("localdb %s: search failed to open: %s", self.name, e)
            return out
        try:
            for table in list(schema.keys())[:max_tables]:
                try:
                    out.extend(self._search_table(conn, table, toks, max_rows))
                except Exception as e:
                    # Per table. A reserved-word name, a dropped table, a
                    # corrupt page: that table yields nothing and the rest of
                    # the database is still searched.
                    logger.warning("localdb %s: search(%s) failed: %s", self.name, table, e)
                    continue
        finally:
            conn.close()
        return out

    def _search_table(self, conn, table: str, tokens: List[str], max_rows: int) -> List[Dict]:
        columns = self.schema().get(table) or []
        text_cols = [c["name"] for c in columns if is_text_column(c["type"])][:MAX_TEXT_COLUMNS]
        if not text_cols:
            return []

        # F1: ask for the MOST SPECIFIC token first, not `tokens` order.
        #
        # The old query OR'd every (column, token) pair into one WHERE and cut
        # the result at `max_rows` with no ORDER BY, so a short generic word
        # riding alongside a proper noun in the same query (a merchant name
        # plus "last", from "last week") could fill the whole row cap with
        # rows the generic word alone matched -- a 4-letter substring turns up
        # inside ordinary words ("elastic", "blast") across a table of any
        # size -- before the row the proper noun actually named was ever
        # reached. Measured: a table where the specific match sorts after the
        # generic one by rowid returned zero of the rows the query was about.
        #
        # Fix: one bounded subquery PER TOKEN (still all `text_cols`, still
        # LIMIT `max_rows` each — the per-table cost bound is unchanged, and
        # this stays ONE statement: a UNION ALL, one round trip), longest
        # token first. Deduped and re-capped at `max_rows` in Python below, so
        # a row every subquery would have found on its own only ever costs one
        # slot, and the slots go to the longer (more specific) token's rows
        # first when the cap is tight.
        deduped_tokens = list(dict.fromkeys(str(t) for t in tokens if str(t).strip()))
        if not deduped_tokens:
            return []
        ordered_tokens = sorted(deduped_tokens, key=len, reverse=True)[:MAX_TOKENS]

        clause = " OR ".join("%s LIKE ? ESCAPE '%s'" % (quote_ident(c), _LIKE_ESCAPE)
                             for c in text_cols)
        quoted_table = quote_ident(table)
        pri_alias = self._priority_alias(columns)

        def _union(select_cols: str):
            parts: List[str] = []
            params: List[str] = []
            for priority, tok in enumerate(ordered_tokens):
                # Each branch's LIMIT must bind to that branch alone, not the
                # whole compound SELECT -- SQLite gives a bare
                # `SELECT ... LIMIT n UNION ALL SELECT ...` to the compound,
                # so the per-token cap is applied inside a FROM subquery instead.
                parts.append("SELECT * FROM (SELECT %d AS %s, %s FROM %s WHERE %s LIMIT %d)"
                             % (priority, quote_ident(pri_alias), select_cols,
                                quoted_table, clause, int(max_rows)))
                params.extend(like_pattern(tok) for _ in text_cols)
            sql = " UNION ALL ".join(parts) + " ORDER BY %s" % quote_ident(pri_alias)
            return sql, params

        pk_col = self.single_pk(table)
        rid_alias = None
        if pk_col is None:
            # No addressable declared key, so ask for the implicit rowid in the
            # SAME statement (still one query per table). Aliased, because for
            # an `INTEGER PRIMARY KEY` table sqlite reports a bare `rowid`
            # under the pk's own name; and the alias is made unique against
            # the real columns so `*` can never shadow it.
            rid_alias = self._rowid_alias(columns)
            sql, params = _union("_rowid_ AS %s,*" % quote_ident(rid_alias))
            try:
                rows = conn.execute(sql, params).fetchall()
            except sqlite3.OperationalError:
                # WITHOUT ROWID table: there is no implicit rowid to project.
                rid_alias = None
                sql, params = _union("*")
                rows = conn.execute(sql, params).fetchall()
        else:
            sql, params = _union("*")
            rows = conn.execute(sql, params).fetchall()

        results = []
        seen_keys: set = set()
        for r in rows:
            row = dict(r)
            row.pop(pri_alias, None)
            row_id = None
            external_id = None
            if rid_alias is not None:
                row_id = row.pop(rid_alias, None)
                if row_id is not None:
                    # Kept visibly distinct from a pk so nobody feeds it to get_row().
                    external_id = "%s:rowid=%s" % (table, row_id)
            elif pk_col is not None and row.get(pk_col) is not None:
                row_id = row[pk_col]
                external_id = "%s:%s" % (table, row_id)
            # The same row can satisfy more than one token's subquery; kept
            # once, under the HIGHER-priority (earlier, more specific) token
            # it first appeared under, since ORDER BY above already sorted by
            # priority. A row with no addressable identity (composite/no key)
            # is deduped on its own content instead of `id(row)` -- a fresh
            # dict per fetched row would otherwise never compare equal to
            # itself across branches, and two such rows would silently cost
            # two of `max_rows`' slots for what is provenance-wise one row.
            key = external_id if external_id is not None else tuple(sorted(row.items()))
            if key in seen_keys:
                continue
            seen_keys.add(key)
            results.append({"provider": self.name, "table": table, "row_id": row_id,
                            "external_id": external_id,
                            "projection": self.project_row(table, row)})
            if len(results) >= max_rows:
                break
        return results

    @staticmethod
    def _priority_alias(columns: List[Dict]) -> str:
        names = set(c["name"] for c in columns)
        alias = "_chronicle_priority"
        while alias in names:
            alias += "_"
        return alias

    @staticmethod
    def _rowid_alias(columns: List[Dict]) -> str:
        names = set(c["name"] for c in columns)
        alias = "_chronicle_rowid"
        while alias in names:
            alias += "_"
        return alias

    # -- projection --------------------------------------------------------

    def project_row(self, table: str, row: Dict) -> str:
        """`col=val; col=val` — a compact, bounded rendering of one external row.

        A projection is a CACHE of what the authority currently says, not a
        Chronicle fact: nothing here is written to facts/entities (I20). NULLs
        and BLOB columns are dropped, values are truncated, and the whole line
        is capped so one wide row cannot eat a context budget.
        """
        if not row or not isinstance(row, dict):
            return ""
        col_types = {c["name"]: c["type"] for c in (self.schema().get(table) or [])}
        parts: List[str] = []
        used = 0
        for key, val in row.items():
            if val is None:
                continue
            if isinstance(val, (bytes, bytearray)):
                continue                           # binary never enters a projection
            if "BLOB" in str(col_types.get(key, "") or "").upper():
                continue
            text = " ".join(str(val).split())      # projections stay single-line
            if len(text) > MAX_VALUE_CHARS:
                text = text[:MAX_VALUE_CHARS - 3] + "..."
            piece = "%s=%s" % (key, text)
            if used + len(piece) > MAX_PROJECTION_CHARS:
                parts.append("...")
                break
            parts.append(piece)
            used += len(piece) + 2
        return "; ".join(parts)

    def render_projection(self, table: str, row: Dict) -> str:
        """`table: col=val; ...` (§14.1 cached_projection rendering)."""
        body = self.project_row(table, row)
        return "%s: %s" % (table, body) if body else "%s: (empty)" % table

    # -- identity (adjudicated, never inferred) ----------------------------

    def identity_candidate(self, hit: Dict) -> Dict:
        """A search hit turned into a REVIEW CANDIDATE, not a link.

        `entity_id` is None by construction and there is no code path in this
        module that fills it: matching an external row to a Chronicle entity is
        an adjudication, and an adjudication is somebody's decision. Name or
        embedding similarity is evidence for a reviewer, never an edge.
        """
        return {"provider": self.name, "capability": self.capability,
                "table": hit.get("table"), "row_id": hit.get("row_id"),
                "external_id": hit.get("external_id"),
                "cached_projection": hit.get("projection"),
                "entity_id": None, "status": "pending_review"}

    # -- federation interface (§14) ----------------------------------------

    def resolve(self, ref) -> Dict:
        """Resolve external_id "table:pk_value" to a cached projection."""
        if not isinstance(ref, str) or ":" not in ref:
            return {}
        schema = self.schema()
        # Longest known table name first: a table whose own name contains ':'
        # would otherwise be split in the wrong place.
        table = next((t for t in sorted(schema, key=len, reverse=True)
                      if ref.startswith(t + ":")), None)
        if table is None:
            return {}
        pk_str = ref[len(table) + 1:]
        pk_value: Any = pk_str
        pk_col = self.single_pk(table)
        if pk_col:
            declared = next((c["type"] for c in schema[table]
                             if c["name"] == pk_col), "")
            if "INT" in str(declared or "").upper():
                try:
                    pk_value = int(pk_str)
                except ValueError:
                    return {}
        row = self.get_row(table, pk_value)
        if not row:
            return {}
        return {"provider": self.name, "table": table, "pk_value": pk_value,
                "cached_projection": self.render_projection(table, row),
                "columns": dict(row)}

    def query(self, params) -> List[dict]:
        """Federation query entry point: {tokens: [...]} runs the generic search."""
        if isinstance(params, dict):
            return self.search(params.get("tokens") or [],
                               owner=params.get("owner", "_user"),
                               principal=params.get("principal", "_user"))
        return []


def providers_from_config(cfg) -> List[LocalDBProvider]:
    """Build a provider per valid `federation.local_dbs` entry (order preserved)."""
    out: List[LocalDBProvider] = []
    entries = (cfg.get("federation.local_dbs", []) if cfg else []) or []
    if not isinstance(entries, (list, tuple)):
        logger.warning("federation.local_dbs is not a list: %r", type(entries).__name__)
        return out
    for entry in entries:
        if not isinstance(entry, dict):
            logger.warning("federation.local_dbs entry is not a mapping: %r", entry)
            continue
        name, path = entry.get("name"), entry.get("path")
        if not name or not path:
            logger.warning("federation.local_dbs entry missing name or path: %r", entry)
            continue
        # read_only is a declaration, not a switch: this module has no write
        # path. An entry that asks for anything else is a misunderstanding worth
        # refusing loudly rather than silently downgrading to read-only.
        if not entry.get("read_only", True):
            logger.warning("federation.local_dbs %r declares read_only=false; refused", name)
            continue
        out.append(LocalDBProvider(str(name), str(Path(str(path)).expanduser()),
                                   read_acl=entry.get("read_acl") or DEFAULT_ACL,
                                   table=entry.get("table") or None))
    return out


def register_local_dbs(federation, cfg):
    """Register every configured local DB with the capability registry (§14.2)."""
    for provider in providers_from_config(cfg):
        federation.register(provider, declared_by="config", precedence=20)
        logger.info("LocalDBProvider(%s) registered for %s (available=%s)",
                    provider.name, provider.db_path, provider.is_available())
