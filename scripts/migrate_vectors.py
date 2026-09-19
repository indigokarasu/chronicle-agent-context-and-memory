#!/usr/bin/env python3
"""
Chronicle — bulk re-embed every non-canonical vector in a store (§24.4, A0d).

WHAT THIS IS FOR. The health heal (engine/health.py) is a TRICKLE: bounded to a
few hundred requeues per run so a daily self-repair can never stall the box. It
is the right tool for drift. It is the wrong tool for a wholesale model change,
where most of the corpus is in the wrong geometry at once — on the live store,
88% of ~193k vectors were written by a 2048-dim model while the configured
embedder is 768-dim, which the heal alone would take the better part of a year
to work through. This does the same corpus in one bounded, resumable pass.

WHAT IT DOES. Every row of every embedding-bearing table — observed_vectors,
memory_vectors, session_index, projection_vectors and query_proxy_vectors — is
classified exactly the way the heal classifies it:

    ok       tag == the active embedder's canonical tag AND width == dims*4
    retag    same canonical model id, same E1 prefix marker, right width, but a
             stale NAME (a gguf path, an ollama ":latest" tag, a bare pin).
             Metadata only: an UPDATE, never an embed.
    reembed  a different model, a different prefix geometry, a NULL/unknown tag,
             or a wrong width. Only a real embed can fix it.

RE-TAG rows are fixed with one UPDATE per (tag, width) group. RE-EMBED rows are
re-embedded from the SAME source text the writer vectorised — the belief's own
content column, the event's excerpt, the proxy's generated question, the session
row's own `summary`, and for a projection the text its embed job recorded (§g5a
renders that text from an external database and persists it nowhere else, so the
job payload is the only honest record of what those bytes mean) — through the
configured embedder, with the document-side task prefix and the configured
max_input_tokens/overflow clamp, and written back with the canonical model tag.

session_index carried NO model column before A0e, so on a store that has not yet
been upgraded its rows report a NULL tag. --dry-run says so rather than skipping
the table: NULL is "unknown geometry", which classifies re-embed, not "fine".

SAFETY PROPERTIES, all of which the tests pin:
  * A row is only ever written after a successful embed of the right width. A
    row that fails to embed is left EXACTLY as it was — never blanked, never
    written short, never re-tagged to look healthy. Garbage in the store is
    worse than a known-bad row you can find again.
  * Resumable. Work is walked in rowid order per table, and a repaired row no
    longer matches the "needs work" predicate, so a re-run picks up where an
    interrupted one stopped and a completed run is a no-op. Rows that failed are
    simply retried on the next run.
  * Batched commits with a long busy_timeout: a live gateway holds brief write
    locks, and a migration must out-wait them rather than fail.
  * A backend that goes away is FATAL, not skipped: the run stops, prints a
    resumable summary and exits non-zero, rather than walking the whole corpus
    turning transient failures into a report that says "done".

Usage:
    python3 scripts/migrate_vectors.py <db> [--dry-run] [--batch N]
                                            [--endpoint URL] [--model NAME]
                                            [--expect-dims N] [--tables T[,T...]]

    --dry-run     classify only, report counts by (tag, dims) -> action. Opens
                  the database READ-ONLY.
    --batch N     rows per embed + commit batch (default 64, clamped [1, 512]).
    --endpoint    OpenAI-compatible base URL, overriding config/auto-detection.
    --model       model id, overriding config. Use the id the ENDPOINT answers
                  to; the stored tag is canonicalized from it either way.
    --expect-dims the width the endpoint is EXPECTED to answer with, for this run
                  only. See the width guard below; the run is still refused if the
                  endpoint answers a different width.
    --tables      comma-separated table(s) to repair FIRST (e.g.
                  `--tables memory_vectors`, so belief recall recovers soonest).
                  A priority order, not a filter: every table is still processed,
                  so "converged" keeps covering all of them.

THE WIDTH GUARD. The active width is whatever the endpoint answered the probe
with (`healthcheck()` adopts it). Where something STATES what that width should
be -- a declared `embeddings.dimensions`, or embeddings.KNOWN_MODEL_DIMENSIONS for
the resolved canonical model -- and the endpoint contradicts it, this REFUSES:
exit 1, nothing written, not even the database opened, and a message naming
expected vs reported. A server answering 384 for a 768-dim model name would
otherwise have every row re-embedded at 384 under the canonical tag. An unknown
model with nothing declared has no expectation and is never refused.

Exit codes: 0 = converged (or dry-run)   1 = usage / db / config error, incl. a
                                             refused width contradiction
            2 = stopped early: endpoint failure, or rows left unrepaired
"""

from __future__ import annotations

import argparse
import contextlib
import logging
import os
import sqlite3
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from engine.config import Config
from engine.embeddings import (
    VECTOR_TABLES,
    EmbeddingsUnavailable,
    embedder_model_tag,
    expected_blob_len,
    get_embedder,
    is_usable_model_tag,
    pack,
    split_model_tag,
    width_contradiction,
)
from engine.reducer import (
    belief_vector_text,
    observed_vector_text,
    projection_vector_text,
    session_vector_text,
)
from engine.store import MemoryStore

logger = logging.getLogger("chronicle.migrate_vectors")

# Source text comes from reducer.belief_vector_text / observed_vector_text /
# session_vector_text / projection_vector_text -- THE authority on what text a
# stored vector was made of, derived from reducer.vector_text() itself. This
# tool used to import a hand-maintained kind->column map from HealthEngine
# instead; that map said `procedure` -> `procedures.name` while the reducer
# embedded `body`, so every tool-written procedure longer than 40 characters was
# re-embedded from a truncation and stamped canonical. There is no second map
# here now, and there must never be one again:
# tests/test_belief_text_authority.py asserts this module resolves text through
# the same function objects the heal and the requeue script use, and
# tests/test_a0e_session_projection_vectors.py extends that to the two tables
# A0e added.

# The tables this tool SCANS -- bound from embeddings.VECTOR_TABLES, never
# re-typed, so the tool and the heal cannot disagree about what "every vector"
# means (A0e: three hand-typed copies of this list each covered three of the
# five tables). Everything else that holds a BLOB is DISCOVERED and reported as
# not-scanned rather than silently folded into a convergence claim (see
# unscanned_vector_tables / the summary below).
_TABLES = VECTOR_TABLES

def _table_order(requested) -> tuple:
    """The order the re-embed passes walk the tables in.

    `requested` is a subset given as a priority list (`--tables`): those tables go
    first, in the order named, and every table NOT named follows in the default
    order. Nothing is ever dropped -- the exit code and the "converged" claim are
    statements about all of `_TABLES`, and letting a flag narrow that would make a
    clean exit mean less than it says. Unknown names raise ValueError."""
    if not requested:
        return tuple(_TABLES)
    if isinstance(requested, str):
        requested = [t.strip() for t in requested.split(",") if t.strip()]
    bad = [t for t in requested if t not in _TABLES]
    if bad:
        raise ValueError("unknown table(s): %s (known: %s)"
                         % (", ".join(bad), ", ".join(_TABLES)))
    seen, order = set(), []
    for t in list(requested) + list(_TABLES):
        if t not in seen:
            seen.add(t)
            order.append(t)
    return tuple(order)


_DEFAULT_BATCH = 64
_MIN_BATCH, _MAX_BATCH = 1, 512
# A live gateway holds brief write locks; out-wait them instead of failing.
_BUSY_TIMEOUT_MS = 60000
# Consecutive per-row embed failures that mean "the endpoint is gone", not "this
# one row is odd". One flaky row must not abort a 193k-row migration; five in a
# row is not a flaky row.
_ABORT_AFTER_CONSECUTIVE = 5


# --------------------------------------------------------------------------
# config / embedder
# --------------------------------------------------------------------------
def load_config() -> Config:
    """Chronicle's own config resolution: DEFAULTS + $HERMES_HOME/config.yaml's
    `memory:` block, exactly like scripts/embedding_check.py. Never a raw-YAML
    read that bypasses the defaults."""
    overrides = {}
    home = Path(os.environ.get("HERMES_HOME", str(Path.home() / ".hermes")))
    cfg_path = home / "config.yaml"
    if cfg_path.exists():
        try:
            import yaml
            raw = yaml.safe_load(cfg_path.read_text()) or {}
            mem = raw.get("memory")
            if isinstance(mem, dict):
                overrides = mem
        except Exception as e:
            print(f"(could not read {cfg_path}: {e})")
    return Config(overrides)


def build_embedder(cfg: Config, endpoint=None, model=None):
    """The configured embedder, with CLI overrides applied.

    max_input_tokens / overflow come from config so a migration clamps input
    exactly the way the live write path does -- a migration that sent over-cap
    text would reproduce the nemotron->nomic 500 incident at 193k-row scale."""
    return get_embedder(
        model or cfg.get("embeddings.model"),
        cfg.get("embeddings.dimensions"),
        endpoint or cfg.get("embeddings.base_url"),
        cfg.get("embeddings.api_key"),
        cfg.get("embeddings.max_input_tokens"),
        cfg.get("embeddings.overflow"),
        cfg.get("embeddings.task_prefixes"),
        # A2: a migration re-embeds real memory content, so it obeys the same
        # on-host guard as the live write path. An off-host endpoint (config or
        # --endpoint) yields a DegradedEmbedder here, exactly as it would in
        # ChronicleCore -- a migration must not be the way memory leaves the host.
        cfg.get("embeddings.allow_remote"),
    )


# --------------------------------------------------------------------------
# classification
# --------------------------------------------------------------------------
def classify(tag, blob_len, active_tag, expect_len) -> str:
    """"ok" | "retag" | "reembed" for one (tag, width) pair.

    Identical rule to HealthEngine._classify_tag; kept as a free function here
    so the tool can classify a store it has no HealthEngine for (a --dry-run
    against a read-only copy, say)."""
    active_id, active_marked = split_model_tag(active_tag)
    cid, marked = split_model_tag(tag)
    if cid != active_id:
        return "reembed"
    if expect_len and blob_len is not None and blob_len != expect_len:
        return "reembed"
    if expect_len and blob_len is None:
        return "reembed"          # NULL blob: nothing to compare, must re-embed
    if marked != active_marked:
        return "reembed"
    return "ok" if tag == active_tag else "retag"


def survey(conn, active_tag, expect_len) -> dict:
    """table -> list of (tag, blob_len, count, action).

    One grouped aggregate per table: exact counts over the whole store without
    materializing a single blob."""
    out = {}
    for table in _TABLES:
        rows = []
        try:
            cur = conn.execute(
                "SELECT model, length(embedding), COUNT(*) FROM %s "
                "GROUP BY model, length(embedding) ORDER BY 3 DESC" % table)
        except sqlite3.Error:
            # No `model` column yet -- session_index on any store this tool has
            # not already been run against, and --dry-run opens READ-ONLY so it
            # cannot migrate one into existence. Reporting the table as empty
            # here would under-report exactly the rows the tool exists for
            # (6,753 of them on the live store) on the very first command an
            # operator runs, so its rows are surveyed with a NULL tag -- which is
            # what the migration will find once the column lands.
            try:
                cur = conn.execute(
                    "SELECT NULL, length(embedding), COUNT(*) FROM %s "
                    "GROUP BY length(embedding) ORDER BY 3 DESC" % table)
            except sqlite3.Error:
                out[table] = rows  # table genuinely absent on an old store
                continue
        for tag, blen, cnt in cur.fetchall():
            rows.append((tag, blen, cnt, classify(tag, blen, active_tag, expect_len)))
        out[table] = rows
    return out


def unscanned_vector_tables(conn) -> list:
    """Every vector-bearing table in this store that `_TABLES` does NOT cover.

    DISCOVERED, not listed: any table with a BLOB column is a table that can hold
    an embedding, so a vector store added later cannot quietly fall outside this
    tool's honesty the way `session_index` and `projection_vectors` did (the tool
    printed "converged: 100% of vectors carry the canonical tag and width" over a
    store with wrong-width rows in both). SQLite's own FTS shadow tables carry
    BLOBs too, so they are excluded by name prefix — they hold no embeddings.

    A0e brought those two INTO `_TABLES`, so they now drop out of this list
    automatically — that is the point of discovering rather than listing: closing
    the coverage gap and shrinking the disclaimer are ONE edit, and cannot get
    out of step. What remains is `entity_centroids.sum_vec`, which is an
    accumulated SUM of mention vectors rather than an embedding of any
    recoverable text; it is still listed here (honesty), still never repaired by
    this tool, and carries its own `model` + `dims` so it refuses to mix
    geometries on its own. See embeddings.VECTOR_TABLES.

    Returns [(table, rows, distinct_widths, is_embedding_col)] sorted by name;
    `distinct_widths` is the set of `length(blob)` values present, which is what
    makes "there is something here I did not check" concrete rather than a
    disclaimer. `is_embedding_col` is False when the BLOB column is not named like
    an embedding — the table is still listed, but its widths are never judged
    against the embedder's."""
    out = []
    try:
        tables = [r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name").fetchall()]
    except sqlite3.Error:
        return out
    for table in tables:
        if table in _TABLES or table.startswith("sqlite_"):
            continue
        try:
            cols = conn.execute('PRAGMA table_info("%s")' % table.replace('"', '""')).fetchall()
        except sqlite3.Error:
            continue
        # FTS5 shadow tables (…_data / _docsize / _idx / _content / _config).
        if any(table.endswith(sfx) for sfx in
               ("_data", "_docsize", "_idx", "_content", "_config")):
            continue
        blobs = [c[1] for c in cols if str(c[2] or "").upper().startswith("BLOB")]
        if not blobs:
            continue
        # Prefer a column that NAMES itself an embedding (`embedding`, `sum_vec`).
        # A BLOB that is not one -- a signature, a compressed payload -- has no
        # "expected width", and comparing it against the embedder's would turn an
        # honest listing into a false alarm.
        named = [c for c in blobs
                 if c == "embedding" or "vec" in c.lower() or "embed" in c.lower()]
        col = named[0] if named else blobs[0]
        try:
            rows = conn.execute('SELECT COUNT(*) FROM "%s"' % table).fetchone()[0]
            widths = sorted(
                r[0] for r in conn.execute(
                    'SELECT DISTINCT length("%s") FROM "%s"' % (col, table)).fetchall()
                if r[0] is not None)
        except sqlite3.Error:
            continue
        out.append((table, rows, widths, bool(named)))
    return out


def print_unscanned(unscanned, expect_len, prefix=""):
    """State plainly what this tool did not look at. An honest tool reports the
    boundary of its own scan; the alternative is a convergence claim that covers
    tables nobody checked."""
    if not unscanned:
        return
    print(f"{prefix}NOT SCANNED by this tool (vector-bearing tables outside "
          f"{', '.join(_TABLES)}):")
    stale = False
    for table, rows, widths, is_emb in unscanned:
        note = ""
        if is_emb and expect_len and rows and any(w != expect_len for w in widths):
            note = ("  <-- holds %s-byte blobs; expected %d"
                    % ("/".join(str(w) for w in widths), expect_len))
            stale = True
        print(f"{prefix}  {table:<24} {rows:>9} rows  widths={widths or '-'}{note}")
    if stale:
        # Said out loud rather than folded into the exit code. The exit code is
        # this tool's verdict on the work it can DO, and a re-run can never clear
        # a table it does not scan -- an exit 2 that no amount of re-running fixes
        # is the "never converges" shape of D4, not honesty. The honest form is a
        # named, specific line the operator can act on.
        print(f"{prefix}  ^ these rows are OUTSIDE this tool's scan and are NOT repaired by "
              f"it. A clean exit below covers {', '.join(_TABLES)} only.")


def _ellipsize(tag, width):
    """Truncation must be VISIBLE: a silently clipped gguf path reads as a
    different (and shorter) model name than the one actually stored.

    A NULL tag renders as `(no model recorded)`, not the bare `None` a str()
    would give: on this report `None` reads like a model literally named that,
    and the distinction between "written by an unknown model" and "written by
    something calling itself None" is the whole reason the column exists."""
    if tag is None:
        return "(no model recorded)"
    t = str(tag)
    return t if len(t) <= width else t[:width - 3] + "..."


def _dims_label(blob_len):
    if blob_len is None:
        return "(null)"
    return str(blob_len // 4) if blob_len % 4 == 0 else "%db" % blob_len


def print_survey(plan, active_tag, expect_len, prefix=""):
    totals = {"ok": 0, "retag": 0, "reembed": 0}
    print(f"{prefix}active tag       : {active_tag}")
    print(f"{prefix}expected width   : {expect_len // 4 if expect_len else '?'} dims "
          f"({expect_len or '?'} bytes)")
    for table in _TABLES:
        rows = plan.get(table) or []
        if not rows:
            print(f"{prefix}{table}: (empty)")
            continue
        print(f"{prefix}{table}:")
        print(f"{prefix}  {'tag':<62} {'dims':>8} {'rows':>9}  action")
        for tag, blen, cnt, action in rows:
            totals[action] += cnt
            print(f"{prefix}  {_ellipsize(tag, 62):<62} {_dims_label(blen):>8} {cnt:>9}  {action}")
    total = sum(totals.values())
    print(f"{prefix}TOTAL: {total} vectors — ok {totals['ok']}, "
          f"retag {totals['retag']}, re-embed {totals['reembed']}")
    return totals


# --------------------------------------------------------------------------
# source text — resolved ONLY through the reducer's authority. There are no
# local text helpers here on purpose: a second way to answer "what text was this
# vector made of" is how the procedure-truncation defect happened.
# --------------------------------------------------------------------------
# --------------------------------------------------------------------------
# the run
# --------------------------------------------------------------------------
class _Aborted(RuntimeError):
    """The backend went away. Stop, report, exit non-zero — never keep walking."""


class Migrator:
    def __init__(self, store, embedder, batch=_DEFAULT_BATCH, verbose=True, order=None):
        self.store = store
        self.emb = embedder
        self.batch = max(_MIN_BATCH, min(_MAX_BATCH, int(batch)))
        self.verbose = verbose
        # Which table is repaired FIRST is an operator choice (A0g): belief recall
        # is what a user notices, so `--tables memory_vectors` puts memory_vectors
        # ahead of the rest. It is an ORDER, never a subset -- every table is still
        # walked, so "converged" keeps meaning the same thing -- and each table's
        # walk is an independent rowid cursor over its own "needs work" predicate,
        # so re-ordering cannot affect resumability: an interrupted run resumes from
        # whatever is left, in whatever order it is then given.
        self.order = _table_order(order)
        self.active_tag = embedder_model_tag(embedder)
        self.expect_len = expected_blob_len(embedder)
        self.retagged = 0
        self.reembedded = 0
        self.failed = 0
        self.failed_ids: list = []
        self._consecutive = 0
        self._t0 = time.time()

    # -- helpers ---------------------------------------------------------
    def _say(self, msg):
        if self.verbose:
            print(msg, flush=True)

    def _embed_many(self, texts):
        """Vectors for `texts`, or None per text that could not be embedded.

        Tries the batch endpoint first (one round trip per batch instead of one
        per row — the difference between hours and days on a 193k-row store),
        then falls back to per-row embeds so ONE bad row cannot cost its whole
        batch. Both paths go through the embedder's document-side prefix and the
        configured input clamp."""
        batch_fn = getattr(self.emb, "embed_batch", None)
        if callable(batch_fn):
            try:
                vecs = batch_fn(list(texts), chunk=len(texts))
                if len(vecs) == len(texts):
                    return list(vecs)
            except EmbeddingsUnavailable:
                raise
            except Exception as e:
                logger.debug("batch embed failed (%s); falling back to per-row", e)
        out = []
        for t in texts:
            try:
                out.append(self.emb.embed_document(t))
            except EmbeddingsUnavailable:
                raise
            except Exception as e:
                logger.debug("embed failed (%s)", e)
                out.append(None)
        return out

    def _usable(self, vec):
        """A vector may only be written if it embedded AND has the right width.
        A width surprise means the endpoint is not the model we think it is;
        writing it would put fresh garbage in the store under a canonical tag."""
        if not vec:
            return False
        return not (self.expect_len and len(vec) * 4 != self.expect_len)

    def _note_failure(self, ident):
        self.failed += 1
        self.failed_ids.append(ident)
        self._consecutive += 1
        if self._consecutive >= _ABORT_AFTER_CONSECUTIVE:
            raise _Aborted("%d consecutive embed failures — the endpoint looks unavailable"
                           % self._consecutive)

    def _count_unrecoverable(self, ident):
        """A row whose source text the store cannot reconstruct.

        Counted as failed and left untouched, but it does NOT advance
        `_consecutive`: unrecoverable rows are a property of the store, not
        evidence that the endpoint died, and a run of them must not be mistaken
        for an outage and abort a migration that is otherwise working."""
        self.failed += 1
        self.failed_ids.append(ident)

    @contextlib.contextmanager
    def _counted_batch(self):
        """A write batch whose success count is only BANKED if it commits.

        `reembedded` used to be incremented per row inside the transaction. When
        `_note_failure` raised `_Aborted` later in that same batch the
        transaction rolled back — correctly, the store stays consistent — but the
        counter kept the rows it had just un-written, so the summary reported
        "re-embedded: 9" over a store where nothing had been repaired (D6). The
        count now lives in a local list that is added to `self.reembedded` only
        after the `with` block commits; on any exception it is discarded with the
        rows it described."""
        written: list = []
        with self.store.transaction():
            yield written
        self.reembedded += len(written)

    # -- pass 1: re-tag ---------------------------------------------------
    def retag(self, plan):
        for table in _TABLES:
            for tag, blen, cnt, action in (plan.get(table) or []):
                if action != "retag":
                    continue
                # `model IS ?`, not `model = ?`: SQL equality against NULL is
                # NULL, so a `= ?` predicate silently selects no row for a
                # NULL-tagged group and the UPDATE reports success having changed
                # nothing. Same NULL-safety bug the re-embed walk had (D4).
                with self.store.transaction() as conn:
                    if blen is None:
                        cur = conn.execute(
                            "UPDATE %s SET model=? WHERE model IS ? AND embedding IS NULL"
                            % table, (self.active_tag, tag))
                    else:
                        cur = conn.execute(
                            "UPDATE %s SET model=? WHERE model IS ? AND length(embedding)=?"
                            % table, (self.active_tag, tag, blen))
                    # rowcount, not the survey's `cnt`: report what the UPDATE
                    # actually changed. The two differ whenever the store moved
                    # under a concurrent writer between survey and retag, and the
                    # honest number is the one the database returned.
                    changed = cur.rowcount if cur.rowcount is not None and cur.rowcount >= 0 else cnt
                self.retagged += changed
                self._say(f"  retag  {table}: {changed} rows  {tag!r} -> {self.active_tag!r}")

    # -- pass 2: re-embed --------------------------------------------------
    def _needs_work_sql(self, table, id_cols):
        cols = ", ".join(id_cols)
        # `model IS NOT ?`, never `model != ?`. In SQL, `NULL != 'x'` is NULL,
        # not true, so a `!=` predicate NEVER selects a NULL-tagged row -- while
        # `classify()` happily calls that same row 'reembed' (canonical_model_id
        # (None) is 'auto', which is not the active id). The tool therefore
        # surveyed work it could not reach: two consecutive runs both printed
        # "failed: 0 / remaining non-canonical: 1" and exited 2 forever, and the
        # NULL-tagged row was never repaired. `IS NOT` is the NULL-safe form and
        # behaves identically for every non-NULL tag. (The heal's own predicate
        # was already `model IS ?` and did repair the row -- the two disagreed.)
        if self.expect_len:
            pred = ("(model IS NOT ? OR length(embedding) IS NULL OR length(embedding) != ?)")
            params = (self.active_tag, self.expect_len)
        else:
            pred = "model IS NOT ?"
            params = (self.active_tag,)
        sql = (f"SELECT rowid, {cols} FROM {table} WHERE rowid > ? AND {pred} "
               f"ORDER BY rowid LIMIT ?")
        return sql, params

    def _walk(self, table, id_cols):
        """Yield batches of rows still needing an embed, in rowid order.

        The rowid cursor is what makes this both RESUMABLE and non-looping: a
        repaired row drops out of the predicate, and a row that FAILED stays
        behind the cursor rather than being handed back forever."""
        try:
            sql, params = self._needs_work_sql(table, id_cols)
            conn = self.store._conn()
            cursor = 0
            while True:
                rows = conn.execute(sql, (cursor, *params, self.batch)).fetchall()
                if not rows:
                    return
                cursor = rows[-1][0]
                yield rows
        except sqlite3.Error as e:
            logger.debug("scan skipped for %s (%s)", table, e)
            return

    def reembed_observed(self):
        conn = self.store._conn()
        for rows in self._walk("observed_vectors", ["event_id", "owner"]):
            items = [(r[1], r[2]) + observed_vector_text(conn, r[1]) for r in rows]
            live = [(eid, owner, text) for eid, owner, text, ok in items if ok and text]
            for eid, _o, _text, ok in items:
                if not ok:
                    # No recoverable source text. Left UNTOUCHED on purpose: a
                    # wrong-geometry vector we can find again beats a deleted
                    # one we cannot.
                    self._count_unrecoverable("observed:" + str(eid))
            if not live:
                continue
            vecs = self._embed_many([t for _e, _o, t in live])
            with self._counted_batch() as batch:
                for (eid, owner, _t), vec in zip(live, vecs):
                    if not self._usable(vec):
                        self._note_failure("observed:" + str(eid))
                        continue
                    self._consecutive = 0
                    self.store.add_observed_vector(eid, pack(vec), self.active_tag,
                                                   owner or "default")
                    batch.append(1)
            self._progress("observed_vectors")

    def reembed_memory(self):
        conn = self.store._conn()
        for rows in self._walk("memory_vectors", ["belief_id", "kind"]):
            # belief_vector_text, never a local map: `recoverable` False means the
            # store cannot reconstruct what this row was embedded from (a
            # pre-schema-12 procedure whose source event is gone, say), and the
            # row is then left exactly as it is and counted, never re-embedded
            # from a near-miss such as the 40-char `procedures.name`.
            items = [(r[1], r[2]) + belief_vector_text(conn, r[2], r[1]) for r in rows]
            live = [(b, k, t) for b, k, t, ok in items if ok and t]
            for bid, kind, _t, ok in items:
                if not ok:
                    self._count_unrecoverable(f"{kind}:{bid}")
            if not live:
                continue
            vecs = self._embed_many([t for _b, _k, t in live])
            with self._counted_batch() as batch:
                for (bid, kind, _t), vec in zip(live, vecs):
                    if not self._usable(vec):
                        self._note_failure(f"{kind}:{bid}")
                        continue
                    self._consecutive = 0
                    self.store.add_memory_vector(bid, kind, pack(vec), self.active_tag)
                    batch.append(1)
            self._progress("memory_vectors")

    def reembed_proxies(self):
        """doc2query proxies re-embed from their STORED question text.

        Unlike the health heal, which drops them (the embed-job queue is keyed
        (target, kind) and cannot express a variable-length proxy set), this
        tool has the question in hand and can rebuild each row in place — so a
        migration keeps the doc2query tier instead of blanking it and waiting
        for every parent belief to be rewritten."""
        for rows in self._walk("query_proxy_vectors", ["belief_id", "proxy_idx", "kind", "question"]):
            live = [(r[1], r[2], r[3], r[4]) for r in rows if r[4]]
            for r in rows:
                if not r[4]:
                    self._count_unrecoverable(f"proxy:{r[1]}#{r[2]}")
            if not live:
                continue
            vecs = self._embed_many([q for _b, _i, _k, q in live])
            with self._counted_batch() as batch:
                for (bid, idx, kind, q), vec in zip(live, vecs):
                    if not self._usable(vec):
                        self._note_failure(f"proxy:{bid}#{idx}")
                        continue
                    self._consecutive = 0
                    self.store.add_query_proxy_vector(bid, idx, kind, q, pack(vec),
                                                      self.active_tag)
                    batch.append(1)
            self._progress("query_proxy_vectors")

    def reembed_sessions(self):
        """Session summaries re-embed from the row's OWN `summary` column (A0e).

        The text is right there, so this is the same shape as observed_vectors —
        and it is resolved through reducer.session_vector_text rather than read
        out of the SELECT directly, so this tool and the heal cannot drift about
        what a session vector is made of. The write is an UPDATE of
        (embedding, model) only, so a migration can never rewrite a summary, an
        owner or an occurred_at while repairing a vector.

        A row whose summary is empty has nothing to re-embed FROM: it is left
        untouched and counted, never blanked (`recoverable` False, the A0fix
        refusal contract). Those do not advance `_consecutive` — an unrecoverable
        row is a property of the store, not evidence the endpoint died."""
        conn = self.store._conn()
        for rows in self._walk("session_index", ["session_id"]):
            items = [(r[1],) + session_vector_text(conn, r[1]) for r in rows]
            live = [(sid, text) for sid, text, ok in items if ok and text]
            for sid, _text, ok in items:
                if not ok and not self._empty_session_row(conn, sid):
                    self._count_unrecoverable("session:" + str(sid))
            if not live:
                continue
            vecs = self._embed_many([t for _s, t in live])
            with self._counted_batch() as batch:
                for (sid, _t), vec in zip(live, vecs):
                    if not self._usable(vec):
                        self._note_failure("session:" + str(sid))
                        continue
                    self._consecutive = 0
                    self.store.update_session_vector(sid, pack(vec), self.active_tag)
                    batch.append(1)
            self._progress("session_index")

    @staticmethod
    def _empty_session_row(conn, sid) -> bool:
        """A session of nothing but host framing: no summary AND no vector.
        There is nothing to re-embed and no bytes a query could match, so it is
        not a vector in the wrong geometry -- the health census leaves it out
        for the same reason (HealthEngine._CENSUS_FILTER), and counting it here
        made every migration of such a store end "unsuccessful" forever."""
        row = conn.execute("SELECT COALESCE(summary, ''), COALESCE(length(embedding), 0) "
                           "FROM session_index WHERE session_id=?", (sid,)).fetchone()
        return bool(row) and not row[0] and not row[1]

    def reembed_projections(self):
        """Projections re-embed from the text their EMBED JOB recorded (A0e).

        This is the only channel whose source text the store does not otherwise
        hold: §g5a has the caller render it out of an external database and pass
        it to enqueue_projection_embed, so nothing in Chronicle can reconstruct
        it. Re-rendering a guess would silently change what the vector means, so
        a projection whose job payload is gone is left EXACTLY as it is and
        counted as unrecoverable — findable, and honest about being
        unrepairable."""
        conn = self.store._conn()
        for rows in self._walk("projection_vectors", ["provider", "external_id", "owner"]):
            items = []
            for r in rows:
                provider, external_id, owner = r[1], r[2], r[3]
                text, ok = projection_vector_text(conn, provider, external_id)
                if ok and text:
                    items.append((provider, external_id, owner, text))
                else:
                    self._count_unrecoverable("proj:%s:%s" % (provider, external_id))
            if not items:
                continue
            vecs = self._embed_many([t for _p, _e, _o, t in items])
            with self._counted_batch() as batch:
                for (provider, external_id, owner, _t), vec in zip(items, vecs):
                    if not self._usable(vec):
                        self._note_failure("proj:%s:%s" % (provider, external_id))
                        continue
                    self._consecutive = 0
                    self.store.add_projection_vector(provider, external_id, pack(vec),
                                                     self.active_tag, owner or "default")
                    batch.append(1)
            self._progress("projection_vectors")

    def _progress(self, table):
        el = time.time() - self._t0
        rate = self.reembedded / el if el > 0 else 0.0
        self._say(f"  ...{table}: re-embedded {self.reembedded}, retagged {self.retagged}, "
                  f"failed {self.failed}  ({el:.1f}s, {rate:.1f}/s)")

    _REEMBED = {
        "observed_vectors": "reembed_observed",
        "memory_vectors": "reembed_memory",
        "session_index": "reembed_sessions",
        "projection_vectors": "reembed_projections",
        "query_proxy_vectors": "reembed_proxies",
    }

    def run(self, plan):
        # Re-tagging stays first whatever the order: it is metadata only, needs no
        # endpoint, and converges in one pass, so an interrupted run should always
        # have banked it.
        self.retag(plan)
        for table in self.order:
            getattr(self, self._REEMBED[table])()


# --------------------------------------------------------------------------
# entry point
# --------------------------------------------------------------------------
def migrate(db_path, dry_run=False, batch=_DEFAULT_BATCH, endpoint=None, model=None,
            cfg=None, embedder=None, verbose=True, expect_dims=None, tables=None) -> int:
    path = Path(db_path).expanduser()
    if not path.exists():
        print(f"ERROR: no database at {path}")
        return 1

    cfg = cfg if cfg is not None else load_config()
    emb = embedder if embedder is not None else build_embedder(cfg, endpoint, model)
    active_tag = embedder_model_tag(emb)
    expect_len = expected_blob_len(emb)
    if not is_usable_model_tag(active_tag):
        print(f"ERROR: the configured embedder resolved to {active_tag!r}, which names no "
              f"geometry. Nothing is migrated: converging a store onto a backend that cannot "
              f"embed would rewrite it into an unusable state. Start the endpoint (or pass "
              f"--endpoint/--model) and re-run.")
        return 1

    # WIDTH GUARD (A0g). `expect_len` above is the width the ENDPOINT answered the
    # probe with, because healthcheck() adopts it. That is the right number when
    # nothing states what it should be -- and the wrong one to rewrite a store
    # against when something does. A server answering 384 for a 768-dim model name
    # (the wrong model behind the right name, a truncating proxy, a bad config)
    # would otherwise be adopted here and every row re-embedded at 384 under the
    # canonical tag. Refuse BEFORE MemoryStore opens the database, so a refusal
    # leaves the file, its -wal and its -shm byte-identical.
    contradiction = width_contradiction(emb, cfg, expect_dims)
    if contradiction:
        reported = int(getattr(emb, "dimensions", 0) or 0)
        print(f"REFUSED: {contradiction}.")
        print(f"Nothing was written. Re-embedding this store against that endpoint would "
              f"rewrite every vector in it into a {reported}-dimension geometry and stamp it "
              f"{active_tag!r} -- the tag that declares a vector correct -- leaving nothing in "
              f"the store to say the old vectors were ever a different width.")
        print(f"If the endpoint is serving a different model than the name claims, fix the "
              f"endpoint and re-run. If {reported} dimensions is genuinely intended (a new "
              f"model, or a deliberately truncated Matryoshka geometry), state it: set "
              f"embeddings.dimensions: {reported} in config, or re-run with "
              f"--expect-dims {reported}.")
        return 1

    if dry_run:
        conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
        try:
            plan = survey(conn, active_tag, expect_len)
            unscanned = unscanned_vector_tables(conn)
        finally:
            conn.close()
        print_survey(plan, active_tag, expect_len, prefix="[dry-run] ")
        print_unscanned(unscanned, expect_len, prefix="[dry-run] ")
        return 0

    store = MemoryStore(str(path))
    try:
        # Out-wait a live gateway's brief write locks rather than failing.
        store._conn().execute("PRAGMA busy_timeout=%d" % _BUSY_TIMEOUT_MS)
        plan = survey(store._conn(), active_tag, expect_len)
        unscanned = unscanned_vector_tables(store._conn())
        totals = print_survey(plan, active_tag, expect_len)
        print_unscanned(unscanned, expect_len, prefix="")
        # `nothing to do` is a claim about the tables this tool scans, and it says
        # so. It used to be an unqualified statement made over a store that could
        # hold wrong-width rows in session_index / projection_vectors (D5) --
        # which A0e then brought into `_TABLES`, so the named scope grew and the
        # NOT-SCANNED list shrank in the same edit.
        if not totals["retag"] and not totals["reembed"]:
            print("nothing to do — every vector in %s is already canonical"
                  % ", ".join(_TABLES))
            return 0

        m = Migrator(store, emb, batch=batch, verbose=verbose, order=tables)
        aborted = None
        try:
            m.run(plan)
        except (_Aborted, EmbeddingsUnavailable) as e:
            aborted = e

        after = survey(store._conn(), active_tag, expect_len)
        remaining = sum(c for table in _TABLES for _t, _b, c, a in (after.get(table) or [])
                        if a != "ok")
        print(f"\nre-tagged  : {m.retagged}")
        print(f"re-embedded: {m.reembedded}")
        print(f"failed     : {m.failed}")
        if m.failed_ids:
            print("  first failures: " + ", ".join(str(i) for i in m.failed_ids[:10]))
        print(f"remaining non-canonical: {remaining}")
        if aborted is not None:
            print(f"\nSTOPPED: {aborted}")
            print("The store is CONSISTENT — only successfully embedded rows were written. "
                  "Fix the endpoint and re-run this command; it resumes from what is left.")
            return 2
        if remaining:
            print("\nSome rows could not be repaired (no recoverable source text, or an embed "
                  "that kept failing). They were left untouched, not blanked. Re-run to retry.")
            return 2
        # SCOPED convergence. The claim covers exactly the tables that were
        # scanned and names them; anything else vector-bearing was listed above
        # as NOT SCANNED. Printing an unqualified "100% of vectors" over a store
        # this tool never fully looked at is the dishonesty D5 found.
        print("\nconverged: 100%% of vectors in %s carry the canonical tag and width"
              % ", ".join(_TABLES))
        return 0
    finally:
        # A11b: MemoryStore owns an explicit lifetime. close() checkpoints the
        # WAL, returns to journal_mode=DELETE and removes the -wal/-shm residue;
        # `finally: pass` skipped all of it, so every run of this tool -- the one
        # pointed at the PRODUCTION store -- left sidecars on disk. Guarded so a
        # failing close can never mask the return code or exception above it.
        try:
            store.close()
        except Exception as e:
            print("warning: store close failed: %s" % e)


def main() -> int:
    ap = argparse.ArgumentParser(
        prog="migrate_vectors.py",
        description="Bulk re-embed every non-canonical vector in a Chronicle store.")
    ap.add_argument("db", help="path to chronicle.db")
    ap.add_argument("--dry-run", action="store_true",
                    help="classify only; report counts by (tag, dims) -> action")
    ap.add_argument("--batch", type=int, default=_DEFAULT_BATCH,
                    help="rows per embed + commit batch (default %d)" % _DEFAULT_BATCH)
    ap.add_argument("--endpoint", default=None, help="OpenAI-compatible base URL override")
    ap.add_argument("--model", default=None, help="model id override")
    ap.add_argument("--expect-dims", type=int, default=None, dest="expect_dims",
                    help="the vector width this endpoint is EXPECTED to answer with, "
                         "overriding config/known-dimensions for this run. Use it when a "
                         "new or deliberately truncated geometry is intended; the run is "
                         "still refused if the endpoint answers anything else.")
    ap.add_argument("--tables", default=None,
                    help="comma-separated table(s) to repair FIRST, e.g. "
                         "--tables memory_vectors (belief recall recovers soonest). "
                         "Every table is still processed; this only re-orders them.")
    args = ap.parse_args()
    try:
        return migrate(args.db, dry_run=args.dry_run, batch=args.batch,
                       endpoint=args.endpoint, model=args.model,
                       expect_dims=args.expect_dims, tables=args.tables)
    except ValueError as e:
        print("ERROR: %s" % e)
        return 1


if __name__ == "__main__":
    sys.exit(main())
