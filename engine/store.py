"""
Chronicle — Storage abstraction & SQLite backend (§24.2).

Single-node store: WAL mode, FTS5, brute-force vector, recursive-CTE graph.
"""

from __future__ import annotations

import json
import logging
import sqlite3
import threading
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger("chronicle.store")


class MemoryStore:
    """SQLite-backed storage for the Chronicle event log and belief store.

    Single-writer, many-readers via WAL mode. All writes go through begin/commit.
    """

    def __init__(self, db_path: str | Path):
        self.db_path = str(db_path)
        self._local = threading.local()
        self._write_lock = threading.Lock()
        self._init_db()

    def _conn(self) -> sqlite3.Connection:
        if not hasattr(self._local, "conn") or self._local.conn is None:
            conn = sqlite3.connect(self.db_path, timeout=30)
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA synchronous=NORMAL")
            conn.execute("PRAGMA foreign_keys=ON")
            conn.row_factory = sqlite3.Row
            self._local.conn = conn
        return self._local.conn

    @contextmanager
    def transaction(self):
        """Exclusive write transaction."""
        with self._write_lock:
            conn = self._conn()
            try:
                yield conn
                conn.commit()
            except Exception:
                conn.rollback()
                raise

    def _init_db(self):
        conn = self._conn()
        # Event log (§6)
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS events (
                event_id    TEXT PRIMARY KEY,
                seq         INTEGER NOT NULL UNIQUE,
                order_key   TEXT,
                type        TEXT NOT NULL,
                payload     TEXT NOT NULL,
                parents     TEXT NOT NULL DEFAULT '[]',
                actor       TEXT NOT NULL CHECK(actor IN ('user','agent','curator','system')),
                owner       TEXT NOT NULL,
                trust_level INTEGER NOT NULL,
                session_id  TEXT,
                branch_id   TEXT,
                occurred_at TEXT NOT NULL,
                recorded_at TEXT NOT NULL,
                prev_head   TEXT,
                sig         TEXT
            );
            CREATE INDEX IF NOT EXISTS idx_events_seq      ON events(seq);
            CREATE INDEX IF NOT EXISTS idx_events_recorded ON events(recorded_at);
            CREATE INDEX IF NOT EXISTS idx_events_type     ON events(type, seq);
            CREATE INDEX IF NOT EXISTS idx_events_session  ON events(session_id, seq);

            -- Meta
            CREATE TABLE IF NOT EXISTS meta (
                key   TEXT PRIMARY KEY,
                value TEXT NOT NULL
            );

            -- Sessions (§12.2)
            CREATE TABLE IF NOT EXISTS sessions (
                session_id          TEXT PRIMARY KEY,
                parent_session_id   TEXT,
                domain              TEXT,
                status              TEXT CHECK(status IN ('active','idle','ended','reaped')),
                started_at          TEXT,
                last_activity_at    TEXT,
                last_extracted_seq  INTEGER NOT NULL DEFAULT 0,
                branch_point_seq    INTEGER,
                ended_via           TEXT,
                ended_at            TEXT
            );

            -- Principals (§15)
            CREATE TABLE IF NOT EXISTS principals (
                principal_id        TEXT PRIMARY KEY,
                type                TEXT CHECK(type IN ('user','agent')),
                display             TEXT,
                default_visibility  TEXT CHECK(default_visibility IN ('shared','private')) DEFAULT 'shared',
                key_ref             TEXT,
                created_at          TEXT
            );

            -- Entities (§8.3)
            CREATE TABLE IF NOT EXISTS entities (
                belief_id           TEXT PRIMARY KEY,
                type                TEXT,
                name                TEXT,
                normalized_name     TEXT,
                aliases             TEXT DEFAULT '[]',
                domain              TEXT,
                owner               TEXT,
                read_acl            TEXT,
                merged_into         TEXT,
                external_ref        TEXT,
                external_provider   TEXT,
                cache_ttl           TEXT,
                fact_count          INTEGER DEFAULT 0,
                relationship_count  INTEGER DEFAULT 0,
                created_at          TEXT,
                last_seen_at        TEXT
            );
            CREATE INDEX IF NOT EXISTS idx_entities_name  ON entities(domain, normalized_name);
            CREATE INDEX IF NOT EXISTS idx_entities_owner ON entities(owner);
            CREATE INDEX IF NOT EXISTS idx_entities_ext   ON entities(external_provider, external_ref);

            -- Pointers (§14)
            CREATE TABLE IF NOT EXISTS pointers (
                id                  TEXT PRIMARY KEY,
                capability          TEXT,
                provider            TEXT,
                external_id         TEXT,
                cached_projection   TEXT,
                cache_ttl           TEXT,
                created_at          TEXT,
                UNIQUE(capability, provider, external_id)
            );

            -- Facts (§8.3)
            CREATE TABLE IF NOT EXISTS facts (
                belief_id           TEXT PRIMARY KEY,
                entity_id           TEXT NOT NULL,
                attribute           TEXT NOT NULL,
                predicate_canonical TEXT,
                value               TEXT NOT NULL,
                value_type          TEXT DEFAULT 'string',
                value_num           REAL,
                value_ts            TEXT,
                qualifiers          TEXT NOT NULL DEFAULT '{}',
                qualifiers_hash     TEXT NOT NULL DEFAULT '',
                pointer_id          TEXT,
                confirm_count       INTEGER DEFAULT 0,
                last_confirmed_at   TEXT,
                extractor_version   TEXT,
                domain              TEXT,
                owner               TEXT,
                read_acl            TEXT,
                status              TEXT DEFAULT 'active',
                salience            TEXT DEFAULT 'normal',
                criticality         TEXT DEFAULT 'normal',
                criticality_reason  TEXT,
                confidence          REAL DEFAULT 0.8 CHECK(confidence BETWEEN 0 AND 1),
                trust_level         INTEGER,
                valid_from          TEXT,
                valid_until         TEXT,
                superseded_by       TEXT,
                created_at          TEXT,
                last_seen_at        TEXT,
                fidelity            TEXT DEFAULT 'verbatim',
                utility             REAL DEFAULT 0,
                purpose_scope       TEXT NOT NULL DEFAULT '["*"]',
                consent             TEXT,
                provenance          TEXT NOT NULL,
                verification        TEXT DEFAULT '{"status":"unverified"}'
            );
            CREATE INDEX IF NOT EXISTS idx_facts_active     ON facts(entity_id, predicate_canonical) WHERE status='active';
            CREATE INDEX IF NOT EXISTS idx_facts_owner      ON facts(owner, domain);
            CREATE INDEX IF NOT EXISTS idx_facts_crit       ON facts(criticality) WHERE criticality!='normal';
            CREATE INDEX IF NOT EXISTS idx_facts_unverified ON facts((json_extract(verification,'$.status'))) WHERE json_extract(verification,'$.status')='unverified';

            -- Episodes (§8.3)
            CREATE TABLE IF NOT EXISTS episodes (
                belief_id       TEXT PRIMARY KEY,
                title           TEXT,
                summary         TEXT,
                participants    TEXT DEFAULT '[]',
                occurred_at     TEXT,
                session_ref     TEXT,
                derived_facts   TEXT DEFAULT '[]',
                pointer_id      TEXT,
                domain          TEXT,
                owner           TEXT,
                read_acl        TEXT,
                status          TEXT,
                salience        TEXT,
                criticality     TEXT DEFAULT 'normal',
                confidence      REAL,
                trust_level     INTEGER,
                valid_from      TEXT,
                valid_until     TEXT,
                created_at      TEXT,
                last_seen_at    TEXT,
                fidelity        TEXT,
                utility         REAL DEFAULT 0,
                purpose_scope   TEXT DEFAULT '["*"]',
                consent         TEXT,
                provenance      TEXT
            );
            CREATE INDEX IF NOT EXISTS idx_episodes_time ON episodes(occurred_at);

            -- Notes (§8.3)
            CREATE TABLE IF NOT EXISTS notes (
                belief_id       TEXT PRIMARY KEY,
                note_type       TEXT CHECK(note_type IN ('procedure','norm','belief')),
                subject         TEXT,
                body            TEXT,
                body_hash       TEXT,
                imperative      INTEGER DEFAULT 0,
                always_inject   INTEGER DEFAULT 0,
                risk_tier       TEXT DEFAULT 'low' CHECK(risk_tier IN ('low','high')),
                domain          TEXT,
                owner           TEXT,
                read_acl        TEXT,
                status          TEXT,
                salience        TEXT,
                criticality     TEXT DEFAULT 'normal',
                confidence      REAL,
                trust_level     INTEGER,
                valid_from      TEXT,
                valid_until     TEXT,
                created_at      TEXT,
                last_seen_at    TEXT,
                fidelity        TEXT,
                utility         REAL DEFAULT 0,
                purpose_scope   TEXT DEFAULT '["*"]',
                consent         TEXT,
                provenance      TEXT
            );
            CREATE INDEX IF NOT EXISTS idx_notes_directive ON notes(always_inject) WHERE always_inject=1;

            -- Refs (§8.3)
            CREATE TABLE IF NOT EXISTS refs (
                belief_id       TEXT PRIMARY KEY,
                topic           TEXT,
                retrieval_url   TEXT,
                retrieved_at    TEXT,
                ttl_days        INTEGER DEFAULT 30,
                cached_summary  TEXT,
                stale_after     TEXT,
                domain          TEXT,
                owner           TEXT,
                read_acl        TEXT,
                status          TEXT,
                trust_level     INTEGER,
                created_at      TEXT,
                purpose_scope   TEXT DEFAULT '["*"]',
                consent         TEXT,
                provenance      TEXT
            );
            CREATE INDEX IF NOT EXISTS idx_refs_stale ON refs(stale_after);

            -- Relationships (§8.3)
            CREATE TABLE IF NOT EXISTS relationships (
                belief_id       TEXT PRIMARY KEY,
                source_id       TEXT,
                predicate       TEXT,
                target_id       TEXT,
                external_ref    TEXT,
                domain          TEXT,
                owner           TEXT,
                read_acl        TEXT,
                status          TEXT,
                confidence      REAL,
                trust_level     INTEGER,
                valid_from      TEXT,
                valid_until     TEXT,
                created_at      TEXT,
                provenance      TEXT
            );
            CREATE INDEX IF NOT EXISTS idx_rel_source ON relationships(source_id) WHERE status='active';
            CREATE INDEX IF NOT EXISTS idx_rel_target ON relationships(target_id) WHERE status='active';

            -- Procedures (§8.3)
            CREATE TABLE IF NOT EXISTS procedures (
                belief_id       TEXT PRIMARY KEY,
                name            TEXT,
                params          TEXT,
                steps           TEXT,
                success_criteria TEXT,
                derived_from    TEXT DEFAULT '[]',
                domain          TEXT,
                owner           TEXT,
                read_acl        TEXT,
                status          TEXT,
                confidence      REAL,
                trust_level     INTEGER,
                created_at      TEXT,
                last_seen_at    TEXT,
                purpose_scope   TEXT DEFAULT '["*"]',
                consent         TEXT,
                provenance      TEXT
            );

            -- Predicates (§8.3)
            CREATE TABLE IF NOT EXISTS predicates (
                surface         TEXT PRIMARY KEY,
                canonical       TEXT NOT NULL,
                cardinality     TEXT NOT NULL DEFAULT 'single' CHECK(cardinality IN ('single','multi')),
                confidence      REAL,
                created_at      TEXT
            );

            -- Documents (§8.3)
            CREATE TABLE IF NOT EXISTS documents (
                id              TEXT PRIMARY KEY,
                type            TEXT,
                created_at      TEXT,
                agent           TEXT,
                abstract        TEXT,
                file_path       TEXT
            );

            -- Tombstones (§8.3)
            CREATE TABLE IF NOT EXISTS tombstones (
                content_hash    TEXT PRIMARY KEY,
                scope           TEXT,
                created_at      TEXT
            );

            -- Justifications (§9.1)
            CREATE TABLE IF NOT EXISTS justifications (
                belief_id       TEXT,
                support         TEXT,
                support_kind    TEXT CHECK(support_kind IN ('event','belief','assumption')),
                rule            TEXT,
                PRIMARY KEY(belief_id, support, rule)
            );
            CREATE INDEX IF NOT EXISTS idx_just_support ON justifications(support);

            -- Nogoods (§9.1)
            CREATE TABLE IF NOT EXISTS nogoods (
                nogood_id       TEXT PRIMARY KEY,
                assumptions     TEXT
            );

            -- Corrections (§9.1)
            CREATE TABLE IF NOT EXISTS corrections (
                id              TEXT PRIMARY KEY,
                belief_id       TEXT,
                reason          TEXT,
                correction_ref  TEXT,
                propagated      TEXT DEFAULT '[]',
                created_at      TEXT
            );

            -- Derivation rules (§9.1)
            CREATE TABLE IF NOT EXISTS derivation_rules (
                rule_id         TEXT PRIMARY KEY,
                name            TEXT,
                enabled         INTEGER DEFAULT 1,
                pattern         TEXT NOT NULL,
                guards          TEXT NOT NULL,
                conclusion      TEXT NOT NULL,
                scope           TEXT NOT NULL,
                materialize     TEXT DEFAULT 'high_value'
            );

            -- Curation jobs (§17)
            CREATE TABLE IF NOT EXISTS curation_jobs (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                task            TEXT CHECK(task IN (
                                    'extract','route','criticality','canonicalize',
                                    'consolidate','contradiction','identity','derive',
                                    'verify','decay','consistency','health','reextract',
                                    'journal_ingest','session_summarize')),
                payload         TEXT,
                depends_on      INTEGER REFERENCES curation_jobs(id),
                status          TEXT CHECK(status IN ('pending','running','done','failed')) DEFAULT 'pending',
                attempts        INTEGER DEFAULT 0,
                created_at      TEXT,
                started_at      TEXT,
                finished_at     TEXT,
                error           TEXT
            );
            CREATE INDEX IF NOT EXISTS idx_jobs_ready ON curation_jobs(status, id) WHERE status='pending';

            -- Extractions (§16)
            CREATE TABLE IF NOT EXISTS extractions (
                id              TEXT PRIMARY KEY,
                observed_event  TEXT,
                extractor_version TEXT,
                produced        TEXT,
                ambiguous       INTEGER DEFAULT 0,
                route           TEXT,
                created_at      TEXT,
                UNIQUE(observed_event, extractor_version)
            );

            -- Raw-content FTS (§8.6)
            CREATE VIRTUAL TABLE IF NOT EXISTS observed_fts USING fts5(
                excerpt, content='', contentless_delete=1
            );

            -- Raw vectors (§8.6)
            CREATE TABLE IF NOT EXISTS observed_vectors (
                event_id        TEXT PRIMARY KEY,
                embedding       BLOB,
                model           TEXT,
                owner           TEXT,
                created_at      TEXT
            );

            -- Session index (§8.6)
            CREATE TABLE IF NOT EXISTS session_index (
                session_id      TEXT PRIMARY KEY,
                summary         TEXT,
                embedding       BLOB,
                owner           TEXT,
                occurred_at     TEXT
            );

            -- Memory vectors (§24.4)
            CREATE TABLE IF NOT EXISTS memory_vectors (
                belief_id       TEXT,
                kind            TEXT,
                embedding       BLOB,
                model           TEXT,
                created_at      TEXT,
                PRIMARY KEY(belief_id, kind)
            );

            -- Sources (§10.2)
            CREATE TABLE IF NOT EXISTS sources (
                source_id       TEXT PRIMARY KEY,
                source_type     TEXT,
                trust_level     INTEGER,
                info_label      TEXT
            );

            -- Calibration (§10.5)
            CREATE TABLE IF NOT EXISTS calibration_obs (
                source_type     TEXT,
                predicted_bucket TEXT,
                n               INTEGER,
                correct         INTEGER,
                PRIMARY KEY(source_type, predicted_bucket)
            );

            -- Git mirror queue (§26)
            CREATE TABLE IF NOT EXISTS git_queue (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                event_id        TEXT NOT NULL,
                committed       INTEGER DEFAULT 0,
                committed_at    TEXT,
                git_commit      TEXT,
                created_at      TEXT
            );

            -- User epistemic model (§19)
            CREATE TABLE IF NOT EXISTS user_knowledge (
                belief_id       TEXT PRIMARY KEY,
                proposition     TEXT,
                about_belief    TEXT,
                state           TEXT CHECK(state IN ('told','stated_by_user','assumed_known')),
                last_communicated TEXT,
                times_communicated INTEGER DEFAULT 0,
                owner           TEXT,
                read_acl        TEXT,
                domain          TEXT,
                created_at      TEXT
            );

            -- Retrieval log (§22)
            CREATE TABLE IF NOT EXISTS retrieval_log (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                query           TEXT,
                domain          TEXT,
                top_score       REAL,
                resolved        INTEGER DEFAULT 0,
                created_at      TEXT
            );

            -- Search misses (§18.7)
            CREATE TABLE IF NOT EXISTS search_misses (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                query           TEXT,
                domain          TEXT,
                top_score       REAL,
                resolved        INTEGER DEFAULT 0,
                created_at      TEXT
            );

            -- Health runs (§21)
            CREATE TABLE IF NOT EXISTS health_runs (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                created_at      TEXT,
                results         TEXT
            );

            -- Issue fingerprints (§21)
            CREATE TABLE IF NOT EXISTS issue_fingerprints (
                fingerprint     TEXT PRIMARY KEY,
                pattern         TEXT,
                tier            TEXT,
                repair_action   TEXT,
                occurrences     INTEGER DEFAULT 0,
                last_seen       TEXT,
                auto_repair     INTEGER DEFAULT 0
            );

            -- Learning policies (§22)
            CREATE TABLE IF NOT EXISTS policies (
                version         TEXT PRIMARY KEY,
                kind            TEXT,
                params          TEXT,
                parent_version  TEXT,
                active          INTEGER DEFAULT 0
            );

            -- Eval baselines (§22)
            CREATE TABLE IF NOT EXISTS eval_baselines (
                capability      TEXT,
                domain          TEXT,
                metric          TEXT,
                baseline        REAL,
                PRIMARY KEY(capability, domain, metric)
            );

            -- Goals (§23)
            CREATE TABLE IF NOT EXISTS goals (
                id              TEXT PRIMARY KEY,
                goal            TEXT,
                status          TEXT DEFAULT 'active',
                created_at      TEXT,
                updated_at      TEXT
            );

            -- Reflections (§23)
            CREATE TABLE IF NOT EXISTS reflections (
                id              TEXT PRIMARY KEY,
                situation       TEXT,
                action          TEXT,
                outcome         TEXT,
                lesson          TEXT,
                applicability   TEXT,
                created_at      TEXT
            );

            -- Capability providers (§14)
            CREATE TABLE IF NOT EXISTS capability_providers (
                capability      TEXT PRIMARY KEY,
                provider        TEXT,
                declared_by     TEXT,
                precedence      INTEGER,
                status          TEXT CHECK(status IN ('active','unavailable')) DEFAULT 'active'
            );
        """)

        # Initialize meta
        conn.execute(
            "INSERT OR IGNORE INTO meta(key, value) VALUES('projection_seq', '0')")
        conn.execute(
            "INSERT OR IGNORE INTO meta(key, value) VALUES('head_event_id', '')")
        conn.commit()

    # -- Event log -----------------------------------------------------------

    def append_event(self, event: dict) -> str:
        """Append an event. Returns event_id. Idempotent (content-addressed)."""
        with self.transaction() as conn:
            # Check if already exists (idempotent)
            row = conn.execute(
                "SELECT event_id FROM events WHERE event_id=?",
                (event["event_id"],)
            ).fetchone()
            if row:
                return row["event_id"]

            # Assign seq
            row = conn.execute("SELECT COALESCE(MAX(seq), 0) + 1 FROM events").fetchone()
            seq = row[0]

            conn.execute(
                """INSERT INTO events
                   (event_id, seq, order_key, type, payload, parents, actor, owner,
                    trust_level, session_id, branch_id, occurred_at, recorded_at,
                    prev_head, sig)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (event["event_id"], seq, event.get("order_key"),
                 event["type"], json.dumps(event["payload"], ensure_ascii=False),
                 json.dumps(event.get("parents", []), ensure_ascii=False),
                 event["actor"], event["owner"], event.get("trust_level", 2),
                 event.get("session_id"), event.get("branch_id"),
                 event["occurred_at"], event["recorded_at"],
                 event.get("prev_head"), event.get("sig"))
            )

            # Update head
            conn.execute(
                "UPDATE meta SET value=? WHERE key='head_event_id'",
                (event["event_id"],)
            )

            # Git queue entry
            conn.execute(
                "INSERT INTO git_queue(event_id, created_at) VALUES(?, ?)",
                (event["event_id"], event["recorded_at"])
            )

        return event["event_id"]

    def get_event(self, event_id: str) -> Optional[dict]:
        conn = self._conn()
        row = conn.execute("SELECT * FROM events WHERE event_id=?", (event_id,)).fetchone()
        if row is None:
            return None
        return dict(row)

    def get_events_since(self, seq: int, limit: int = 1000) -> list[dict]:
        conn = self._conn()
        rows = conn.execute(
            "SELECT * FROM events WHERE seq > ? ORDER BY seq LIMIT ?",
            (seq, limit)
        ).fetchall()
        return [dict(r) for r in rows]

    def get_head_event_id(self) -> str:
        conn = self._conn()
        row = conn.execute("SELECT value FROM meta WHERE key='head_event_id'").fetchone()
        return row["value"] if row else ""

    def get_projection_seq(self) -> int:
        conn = self._conn()
        row = conn.execute("SELECT value FROM meta WHERE key='projection_seq'").fetchone()
        return int(row["value"]) if row else 0

    def set_projection_seq(self, seq: int):
        with self.transaction() as conn:
            conn.execute("UPDATE meta SET value=? WHERE key='projection_seq'", (str(seq),))

    def get_events_by_session(self, session_id: str) -> list[dict]:
        conn = self._conn()
        rows = conn.execute(
            "SELECT * FROM events WHERE session_id=? ORDER BY seq", (session_id,)
        ).fetchall()
        return [dict(r) for r in rows]

    def get_events_by_type(self, type_: str, since_seq: int = 0) -> list[dict]:
        conn = self._conn()
        rows = conn.execute(
            "SELECT * FROM events WHERE type=? AND seq > ? ORDER BY seq",
            (type_, since_seq)
        ).fetchall()
        return [dict(r) for r in rows]

    # -- FTS ----------------------------------------------------------------

    def fts_search(self, query: str, table: str = "observed_fts",
                   limit: int = 10) -> list[dict]:
        conn = self._conn()
        try:
            rows = conn.execute(
                f"SELECT * FROM {table} WHERE {table} MATCH ? LIMIT ?",
                (query, limit)
            ).fetchall()
            return [dict(r) for r in rows]
        except sqlite3.OperationalError:
            return []

    def fts_index(self, key: str, text: str, table: str = "observed_fts"):
        with self.transaction() as conn:
            conn.execute(
                f"INSERT OR REPLACE INTO {table}(rowid, excerpt) VALUES((SELECT COALESCE(MAX(rowid),0)+1 FROM {table}), ?)",
                (text,)
            )

    # -- Belief CRUD ---------------------------------------------------------

    def upsert_belief(self, table: str, belief: dict):
        """Upsert a belief row. Table = facts|episodes|notes|refs|relationships|procedures."""
        with self.transaction() as conn:
            # Build dynamic upsert
            cols = list(belief.keys())
            placeholders = ",".join(["?"] * len(cols))
            col_names = ",".join(cols)
            updates = ",".join(f"{c}=excluded.{c}" for c in cols if c != "belief_id")
            conn.execute(
                f"INSERT INTO {table}({col_names}) VALUES({placeholders}) "
                f"ON CONFLICT(belief_id) DO UPDATE SET {updates}",
                [belief[c] for c in cols]
            )

    def get_belief(self, table: str, belief_id: str) -> Optional[dict]:
        conn = self._conn()
        row = conn.execute(f"SELECT * FROM {table} WHERE belief_id=?", (belief_id,)).fetchone()
        return dict(row) if row else None

    def query_beliefs(self, table: str, where: str = "1=1",
                      params: tuple = (), limit: int = 50) -> list[dict]:
        conn = self._conn()
        rows = conn.execute(
            f"SELECT * FROM {table} WHERE {where} LIMIT ?", (*params, limit)
        ).fetchall()
        return [dict(r) for r in rows]

    # -- Justifications -----------------------------------------------------

    def add_justification(self, belief_id: str, support: str,
                          support_kind: str, rule: str = ""):
        with self.transaction() as conn:
            conn.execute(
                "INSERT OR IGNORE INTO justifications(belief_id, support, support_kind, rule) "
                "VALUES(?,?,?,?)",
                (belief_id, support, support_kind, rule)
            )

    def get_justifications(self, belief_id: str) -> list[dict]:
        conn = self._conn()
        rows = conn.execute(
            "SELECT * FROM justifications WHERE belief_id=?", (belief_id,)
        ).fetchall()
        return [dict(r) for r in rows]

    def get_dependents(self, support: str) -> list[dict]:
        """Find all beliefs that depend on a given support."""
        conn = self._conn()
        rows = conn.execute(
            "SELECT * FROM justifications WHERE support=?", (support,)
        ).fetchall()
        return [dict(r) for r in rows]

    # -- Sessions -----------------------------------------------------------

    def upsert_session(self, session: dict):
        with self.transaction() as conn:
            cols = list(session.keys())
            placeholders = ",".join(["?"] * len(cols))
            col_names = ",".join(cols)
            updates = ",".join(f"{c}=excluded.{c}" for c in cols if c != "session_id")
            conn.execute(
                f"INSERT INTO sessions({col_names}) VALUES({placeholders}) "
                f"ON CONFLICT(session_id) DO UPDATE SET {updates}",
                [session[c] for c in cols]
            )

    def get_session(self, session_id: str) -> Optional[dict]:
        conn = self._conn()
        row = conn.execute(
            "SELECT * FROM sessions WHERE session_id=?", (session_id,)
        ).fetchone()
        return dict(row) if row else None

    def get_stale_sessions(self, idle_threshold: str = "20m",
                           reap_threshold: str = "45m") -> list[dict]:
        """Get sessions that may need reaping."""
        conn = self._conn()
        rows = conn.execute(
            "SELECT * FROM sessions WHERE status IN ('active','idle')"
        ).fetchall()
        return [dict(r) for r in rows]

    # -- Curation jobs ------------------------------------------------------

    def enqueue_curation(self, task: str, payload: dict,
                         depends_on: Optional[int] = None) -> int:
        import datetime
        now = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")
        with self.transaction() as conn:
            cur = conn.execute(
                "INSERT INTO curation_jobs(task, payload, depends_on, created_at) VALUES(?,?,?,?)",
                (task, json.dumps(payload, ensure_ascii=False), depends_on, now)
            )
            return cur.lastrowid

    def claim_curation_job(self) -> Optional[dict]:
        import datetime
        now = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")
        with self.transaction() as conn:
            row = conn.execute(
                """SELECT * FROM curation_jobs
                   WHERE status='pending'
                   AND (depends_on IS NULL OR depends_on IN (
                       SELECT id FROM curation_jobs WHERE status='done'
                   ))
                   ORDER BY id LIMIT 1"""
            ).fetchone()
            if row is None:
                return None
            conn.execute(
                "UPDATE curation_jobs SET status='running', started_at=?, attempts=attempts+1 WHERE id=?",
                (now, row["id"])
            )
            return dict(row)

    def complete_curation_job(self, job_id: int, error: Optional[str] = None):
        import datetime
        now = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")
        with self.transaction() as conn:
            status = "failed" if error else "done"
            conn.execute(
                "UPDATE curation_jobs SET status=?, finished_at=?, error=? WHERE id=?",
                (status, now, error, job_id)
            )

    # -- Principals ---------------------------------------------------------

    def upsert_principal(self, principal: dict):
        with self.transaction() as conn:
            cols = list(principal.keys())
            placeholders = ",".join(["?"] * len(cols))
            col_names = ",".join(cols)
            updates = ",".join(f"{c}=excluded.{c}" for c in cols if c != "principal_id")
            conn.execute(
                f"INSERT INTO principals({col_names}) VALUES({placeholders}) "
                f"ON CONFLICT(principal_id) DO UPDATE SET {updates}",
                [principal[c] for c in cols]
            )

    def get_principal(self, principal_id: str) -> Optional[dict]:
        conn = self._conn()
        row = conn.execute(
            "SELECT * FROM principals WHERE principal_id=?", (principal_id,)
        ).fetchone()
        return dict(row) if row else None

    def get_principals_for_user(self, user_id: str) -> list[dict]:
        conn = self._conn()
        rows = conn.execute(
            "SELECT * FROM principals WHERE principal_id=? OR principal_id LIKE ?",
            (user_id, f"{user_id}:%")
        ).fetchall()
        return [dict(r) for r in rows]

    # -- Git queue ----------------------------------------------------------

    def get_unflushed_git_events(self, limit: int = 1000) -> list[dict]:
        conn = self._conn()
        rows = conn.execute(
            """SELECT gq.*, e.type, e.payload, e.actor, e.owner, e.occurred_at, e.recorded_at
               FROM git_queue gq
               JOIN events e ON gq.event_id = e.event_id
               WHERE gq.committed = 0
               ORDER BY gq.id LIMIT ?""",
            (limit,)
        ).fetchall()
        return [dict(r) for r in rows]

    def mark_git_flushed(self, ids: list[int], git_commit: str):
        with self.transaction() as conn:
            import datetime
            now = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")
            for i in ids:
                conn.execute(
                    "UPDATE git_queue SET committed=1, committed_at=?, git_commit=? WHERE id=?",
                    (now, git_commit, i)
                )

    # -- Tombstones --------------------------------------------------------

    def is_forbidden(self, content_hash: str) -> bool:
        conn = self._conn()
        row = conn.execute(
            "SELECT 1 FROM tombstones WHERE content_hash=?", (content_hash,)
        ).fetchone()
        return row is not None

    def add_tombstone(self, content_hash: str, scope: str = "*"):
        import datetime
        now = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")
        with self.transaction() as conn:
            conn.execute(
                "INSERT OR IGNORE INTO tombstones(content_hash, scope, created_at) VALUES(?,?,?)",
                (content_hash, scope, now)
            )

    # -- Derivation rules ---------------------------------------------------

    def get_derivation_rules(self, enabled_only: bool = True) -> list[dict]:
        conn = self._conn()
        q = "SELECT * FROM derivation_rules"
        if enabled_only:
            q += " WHERE enabled=1"
        rows = conn.execute(q).fetchall()
        return [dict(r) for r in rows]

    def upsert_derivation_rule(self, rule: dict):
        with self.transaction() as conn:
            cols = list(rule.keys())
            placeholders = ",".join(["?"] * len(cols))
            col_names = ",".join(cols)
            updates = ",".join(f"{c}=excluded.{c}" for c in cols if c != "rule_id")
            conn.execute(
                f"INSERT INTO derivation_rules({col_names}) VALUES({placeholders}) "
                f"ON CONFLICT(rule_id) DO UPDATE SET {updates}",
                [rule[c] for c in cols]
            )

    # -- Capability providers -----------------------------------------------

    def upsert_capability_provider(self, cap: dict):
        with self.transaction() as conn:
            conn.execute(
                """INSERT INTO capability_providers(capability, provider, declared_by, precedence, status)
                   VALUES(?,?,?,?,?)
                   ON CONFLICT(capability) DO UPDATE SET
                   provider=excluded.provider, status=excluded.status""",
                (cap["capability"], cap["provider"], cap.get("declared_by", ""),
                 cap.get("precedence", 0), cap.get("status", "active"))
            )

    def get_capability_providers(self) -> list[dict]:
        conn = self._conn()
        rows = conn.execute("SELECT * FROM capability_providers WHERE status='active'").fetchall()
        return [dict(r) for r in rows]

    # -- Vector search (brute-force) ----------------------------------------

    def add_vector(self, table: str, id_col: str, id_val: str,
                   embedding: bytes, model: str):
        import datetime
        now = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")
        with self.transaction() as conn:
            if table == "memory_vectors":
                conn.execute(
                    f"INSERT OR REPLACE INTO {table}({id_col}, kind, embedding, model, created_at) "
                    "VALUES(?,?,?,?,?)",
                    (id_val, "default", embedding, model, now)
                )
            else:
                conn.execute(
                    f"INSERT OR REPLACE INTO {table}({id_col}, embedding, model, created_at) "
                    "VALUES(?,?,?,?)",
                    (id_val, embedding, model, now)
                )

    def get_vectors(self, table: str, id_col: str) -> list[dict]:
        conn = self._conn()
        rows = conn.execute(f"SELECT * FROM {table}").fetchall()
        return [dict(r) for r in rows]

    # -- Stats --------------------------------------------------------------

    def count_rows(self, table: str, where: str = "1=1") -> int:
        conn = self._conn()
        row = conn.execute(f"SELECT COUNT(*) FROM {table} WHERE {where}").fetchone()
        return row[0] if row else 0
