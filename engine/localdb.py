"""
Chronicle — Local SQLite database provider (§14.1).

Generic read-only provider for any declared SQLite database. Supports arbitrary
schemas: introspects sqlite_master and PRAGMA table_info, exposes tables as
read-only data sources. Identity is never inferred (all external rows are
candidates for review). External attributes are cached as beliefs-about, never
copied into facts (I20).

Config federation.local_dbs declares available DBs:
    federation:
      local_dbs:
        - name: "people"          # provider name for this DB
          path: "/path/to/db.db"  # SQLite file (uri mode=ro enforced)
          read_only: true         # always true; included for explicitness

Pointers use external_id = "table:pk_value", capability = "declared_name".
"""

from __future__ import annotations

import logging
import sqlite3
from pathlib import Path

from .access import can_read
from .federation import CapabilityProvider

logger = logging.getLogger("chronicle.localdb")


class LocalDBProvider(CapabilityProvider):
    """Read-only provider for a declared SQLite database file."""

    def __init__(self, name: str, db_path: str):
        self.name = name
        self.capability = name
        self.db_path = str(db_path)
        self._conn = None
        self._schema = None
        self._manifest = None

    def is_available(self) -> bool:
        """True iff the file exists and is readable (ACL always checks access.can_read)."""
        try:
            path = Path(self.db_path)
            return path.exists() and path.is_file()
        except Exception:
            return False

    def _get_conn(self) -> sqlite3.Connection | None:
        """Lazy connection in read-only URI mode. Returns None if unavailable."""
        if not self.is_available():
            return None
        if self._conn is None:
            try:
                uri = f"file:{self.db_path}?mode=ro"
                self._conn = sqlite3.connect(uri, uri=True, timeout=5)
                self._conn.row_factory = sqlite3.Row
            except Exception as e:
                logger.warning("LocalDBProvider(%s) failed to open %s: %s", self.name, self.db_path, e)
                return None
        return self._conn

    def manifest(self) -> dict:
        """Return schema manifest: {tables: {name, columns: [name, type, pk], pk, rowcount}}."""
        if self._manifest is not None:
            return self._manifest

        if not self.is_available():
            return {"tables": {}}

        try:
            conn = self._get_conn()
            if not conn:
                return {"tables": {}}

            tables = {}
            rows = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
            ).fetchall()

            for row in rows:
                table_name = row["name"]
                # Get column info
                cols = conn.execute(f"PRAGMA table_info({table_name})").fetchall()
                columns = [{"name": c["name"], "type": c["type"], "pk": c["pk"]} for c in cols]
                pk_col = next((c["name"] for c in columns if c["pk"]), None)

                # Get row count
                count_row = conn.execute(f"SELECT COUNT(*) as cnt FROM {table_name}").fetchone()
                rowcount = count_row["cnt"] if count_row else 0

                tables[table_name] = {
                    "name": table_name,
                    "columns": columns,
                    "pk": pk_col,
                    "rowcount": rowcount,
                }

            self._manifest = {"tables": tables}
            return self._manifest
        except Exception as e:
            logger.warning("LocalDBProvider(%s).manifest() failed: %s", self.name, e)
            return {"tables": {}}

    def iter_rows(
        self,
        table: str,
        since_rowid: int = 0,
        limit: int = 1000,
        owner: str = "_user",
        principal: str = "_user",
    ) -> list[dict]:
        """Iterate rows from a table, optionally filtered by ACL.

        Returns a list of dicts (one per row). External attributes are not copied
        into facts; only pointers+projections are created.
        """
        if not self.is_available():
            return []

        # ACL check: deny cross-user reads
        if not can_read("user_agents", owner, principal):
            return []

        try:
            conn = self._get_conn()
            if not conn:
                return []

            manifest = self.manifest()
            if table not in manifest["tables"]:
                logger.warning("LocalDBProvider(%s).iter_rows: table %r not found", self.name, table)
                return []

            query = f"SELECT * FROM {table} WHERE rowid > ? LIMIT ?"
            rows = conn.execute(query, (since_rowid, limit)).fetchall()
            return [dict(r) for r in rows]
        except Exception as e:
            logger.warning("LocalDBProvider(%s).iter_rows(%s) failed: %s", self.name, table, e)
            return []

    def get_row(
        self, table: str, pk_value, owner: str = "_user", principal: str = "_user"
    ) -> dict | None:
        """Get a single row by primary key.

        Returns a dict or None if not found. ACL checked (via can_read).
        """
        if not self.is_available():
            return None

        # ACL check
        if not can_read("user_agents", owner, principal):
            return None

        try:
            conn = self._get_conn()
            if not conn:
                return None

            manifest = self.manifest()
            if table not in manifest["tables"]:
                return None

            pk_col = manifest["tables"][table]["pk"]
            if not pk_col:
                logger.warning(
                    "LocalDBProvider(%s).get_row: table %r has no primary key", self.name, table
                )
                return None

            query = f"SELECT * FROM {table} WHERE {pk_col} = ? LIMIT 1"
            row = conn.execute(query, (pk_value,)).fetchone()
            return dict(row) if row else None
        except Exception as e:
            logger.warning(
                "LocalDBProvider(%s).get_row(%s, %r) failed: %s", self.name, table, pk_value, e
            )
            return None

    def render_projection(self, table: str, row: dict) -> str:
        """Render a row as a short text projection (~400 chars, skipping binary/null).

        Format: "table: col=val; col=val; ..." Capped to keep cached_projection compact.
        """
        if not row or not isinstance(row, dict):
            return f"{table}: (empty)"

        try:
            manifest = self.manifest()
            if table not in manifest["tables"]:
                return f"{table}: (unknown)"

            cols = manifest["tables"][table].get("columns", [])
            col_types = {c["name"]: c["type"] for c in cols}

            parts = []
            for key, val in row.items():
                # Skip binary and null
                if val is None:
                    continue
                col_type = col_types.get(key, "").upper()
                if "BLOB" in col_type or "BINARY" in col_type:
                    continue

                # Coerce to string
                try:
                    if isinstance(val, bytes):
                        val = val.decode("utf-8", errors="replace")
                    else:
                        val = str(val)
                except Exception:
                    val = "(unprintable)"

                # Truncate if too long
                if len(val) > 100:
                    val = val[:97] + "..."

                parts.append(f"{key}={val}")

                # Stop if projection is getting too long (target ~400 chars)
                if sum(len(p) for p in parts) > 350:
                    parts.append("...")
                    break

            return f"{table}: " + "; ".join(parts) if parts else f"{table}: (empty)"
        except Exception as e:
            logger.warning("LocalDBProvider(%s).render_projection(%s) failed: %s", self.name, table, e)
            return f"{table}: (projection error)"

    # -- federation interface (§14) ------------------------------------------

    def resolve(self, ref) -> dict:
        """Resolve an external_id pointer (for federation.resolve).

        external_id format: "table:pk_value"
        Returns a dict with cached projection + table metadata.
        """
        if not isinstance(ref, str) or ":" not in ref:
            return {}

        parts = ref.split(":", 1)
        if len(parts) != 2:
            return {}

        table, pk_str = parts
        # Try to coerce pk_str to int if the table's PK is numeric
        manifest = self.manifest()
        pk_col = None
        if table in manifest["tables"]:
            pk_col = manifest["tables"][table]["pk"]

        try:
            if pk_col:
                # Try int first
                try:
                    pk_value = int(pk_str)
                except ValueError:
                    pk_value = pk_str
            else:
                pk_value = pk_str
        except Exception:
            return {}

        row = self.get_row(table, pk_value)
        if not row:
            return {}

        projection = self.render_projection(table, row)
        return {
            "provider": self.name,
            "table": table,
            "pk_value": pk_value,
            "cached_projection": projection,
            "columns": {k: v for k, v in row.items()},
        }

    def query(self, params) -> list[dict]:
        """Generic query interface (for future federation.query calls).

        Not yet implemented; returns empty list.
        """
        return []


def register_local_dbs(federation, cfg):
    """Register all local_dbs from config.federation.local_dbs with the registry.

    Called by ChronicleCore at init.
    """
    local_dbs = cfg.get("federation.local_dbs", [])
    if not local_dbs:
        return

    for db_config in local_dbs:
        if not isinstance(db_config, dict):
            logger.warning("local_dbs entry is not a dict: %s", db_config)
            continue

        name = db_config.get("name")
        path = db_config.get("path")

        if not name or not path:
            logger.warning("local_dbs entry missing name or path: %s", db_config)
            continue

        # Expand ~ if needed
        path = str(Path(path).expanduser())

        provider = LocalDBProvider(name, path)
        federation.register(provider, declared_by="config", precedence=20)
        logger.info(
            "LocalDBProvider(%s) registered for %s (available=%s)",
            name,
            path,
            provider.is_available(),
        )
