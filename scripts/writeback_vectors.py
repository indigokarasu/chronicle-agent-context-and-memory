#!/usr/bin/env python3
"""
Chronicle — carry recomputed vectors from a migrated COPY back into the LIVE
store (§24.4, A0 chain review Step 8.3 W1-W8).

WHAT THIS IS FOR. Production holds ~216k vectors, 88% of them embedded by an
abandoned 2048-dim model while the configured embedder is 768-dim. The VPS can
re-embed at ~0.5 rows/s (days of wall clock behind a live agent); a fast host
does ~13/s (hours). So the corpus is repaired OFF the box:

    1. snapshot the live store with the SQLite online backup API
    2. BUILD A MANIFEST from that pristine copy (this tool, --build-manifest)
    3. migrate the COPY on the fast host (scripts/migrate_vectors.py)
    4. write ONLY the recomputed vector rows back into the live store (this tool)

Step 4 runs while the live gateway keeps serving AND WRITING. Everything below
exists because "the live store moved under us" is the normal case, not the
exception.

WHAT IT WRITES. `embedding` and `model`, on rows that already exist, and
nothing else. Never a row's text, owner, occurred_at or created_at; never a new
row; never a deleted one.

--------------------------------------------------------------------------
THE MANIFEST, AND WHY IT IS A HARD REQUIREMENT
--------------------------------------------------------------------------
W2 is a compare-and-swap against the row as it stood AT SNAPSHOT TIME. After
the migration that pre-image is gone — the copy now holds the NEW vector, and
the live row is the only other copy of anything, which is precisely what we are
not allowed to trust. So the pre-image has to be recorded BEFORE the migration
runs.

Design chosen: this tool records it itself, from the pristine copy, in a
`--build-manifest` pass that runs between step 1 and step 3 above. The copy is
byte-identical to the snapshot of live at that instant, so "the copy's state
before migration" IS "live's state at snapshot time" — no cooperation from
migrate_vectors is needed, and the manifest cannot drift from the thing it
describes because it is read out of it.

    python3 scripts/writeback_vectors.py live.db copy.db --build-manifest m.jsonl

The manifest is JSONL: a header line, then one record per vector row:

    {"t": table, "k": [natural key...], "m": model-or-null,
     "h": sha256(embedding)-or-null, "b": len(embedding)-or-null,
     "x": sha256(authority text)-or-null, "n": len(authority text),
     "r": recoverable}

`m`/`h` are the W2 pre-image. `x`/`n` pin the source text as it stood at
snapshot time, which is what makes "the copy's text is still the copy's text"
checkable rather than assumed. The header carries per-table row counts, so a
manifest built from a DIFFERENT copy is caught before a single row is written.

A run without `--manifest` REFUSES (exit 1). A manifest whose header does not
bind to this copy REFUSES. A copy row with no manifest entry REFUSES the whole
run — a gap means the manifest is not this copy's, and a row we cannot CAS is a
row we must not write. None of these degrade into "skip W2 for that row": a
silently skipped CAS is exactly the failure W2 exists to prevent. That refusal
is deliberately over-determined: four independent sites reject a missing
manifest, and _wb/wb_mutations.py has to disable all four before a run without
one will start.

The index is loaded ONE TABLE AT A TIME and dropped again. It has to be in
memory (it is consulted per row inside a write transaction), and all 216k
production rows at once measured ~500 MB of RSS — too much to put behind a live
agent on a box with an OOM history. Per table the peak is the largest table's
index: ~570 bytes a row, so ~52 MB for memory_vectors' 95.5k, and the manifest
file is simply re-read for the next table.

--------------------------------------------------------------------------
THE PER-ROW CONTRACT (W1-W8). Every check runs INSIDE the same
`BEGIN IMMEDIATE` transaction as the write, so nothing can slip between the
test and the UPDATE.
--------------------------------------------------------------------------
W1  UPDATE ... WHERE <natural key>. Never INSERT, never INSERT OR REPLACE.
    A row retracted / forgotten / delete_observed_vector'd on live after the
    snapshot MUST stay deleted; REPLACE would resurrect forgotten content —
    a data-protection failure, not a merge conflict. rowcount 0 is counted
    `skipped-missing` and is a NORMAL outcome.
    Natural keys: memory_vectors (belief_id, kind) · observed_vectors event_id ·
    session_index session_id · projection_vectors (provider, external_id) ·
    query_proxy_vectors (belief_id, proxy_idx).
W2  Compare-and-swap on the pre-image: live (model, sha256(embedding)) must
    equal the manifest's snapshot values. Otherwise skip, `skipped-changed`:
    the live path has rewritten that row since the snapshot and now owns it.
W3  Source text unchanged: the reducer-authority text recomputed ON LIVE
    (reducer.belief_vector_text / observed_vector_text / session_vector_text /
    projection_vector_text; proxies use the stored `question`) must hash equal
    to the text the copy embedded. Otherwise skip, `skipped-text`. Active
    sessions fail this legitimately — their summary keeps growing.
W4  No pending or claimed `embed` job for that target in live curation_jobs.
    Otherwise skip, `skipped-job`. REQUIRED: curation._task_embed's "already
    current" test is TAG + WIDTH ONLY, so stamping canonical+width over a row
    whose re-embed job is queued turns that job into a permanent no-op and
    leaves a stale vector marked correct — a D3-class outcome created by the
    write-back itself.
W5  New blob length == the live gateway's active width and new tag == the live
    active tag, byte-exact. A violation is not a skip: it means the copy was
    migrated onto a different geometry than the one live is serving, so the
    run REFUSES (exit 1) and writes nothing.
W6  N1 at-risk exception. For rows whose authority text exceeds 8000 chars,
    W2 is SKIPPED (W1/W3/W4/W5 all still apply).

    WHAT IT WAS FOR. store.enqueue_embed_job used to clamp its payload to
    text[:8000], and curation._task_embed embedded that payload for
    belief/observed kinds — so under `chunk_mean` a live heal of such a row
    wrote the vector of the FIRST 8000 CHARACTERS and stamped it canonical +
    right width, after which the tag+width "already current" test made the
    truncation permanent. Without W6, any heal activity during the write-back
    window did exactly that for exactly these rows.

    WHAT CHANGED, and it is stated rather than left as a stale justification:
    ladder-10 A0g DELETED that clamp outright, with no replacement — its N1 fix
    makes `_task_embed` re-resolve the text through the reducer's authority for
    every kind, so the job payload is a dedup key and an audit record, and the
    EMBEDDER's own clamp is the single authority on length. A live heal on a
    v5.7.0 engine therefore no longer truncates, and the wrong-vector half of
    the rationale above describes engine behaviour that is gone.

    W6 STAYS, for two reasons that survive the fix. (1) The threshold still
    describes a real operational window: a write-back runs against a LIVE store
    that may still be serving an older build, or that healed these rows before
    the upgrade, and those truncated vectors are on disk now. (2) Overwriting
    an at-risk row whose text is UNCHANGED is correct either way — same text
    means same vector, so the bypass either repairs a truncation or replaces a
    vector with an identical one. It is belt-and-braces for the window rather
    than a necessity, which is a weaker claim than the one above and the honest
    one to make.
W7  Only rows whose (model, embedding) actually CHANGED on the copy are
    candidates. Unrecoverable rows the migration left alone stay untouched on
    live too, exactly as they are on the copy.
W8  Batches <= 500 rows · busy_timeout >= 5s · fully resumable through a
    persisted cursor, with a write-ahead `inflight` record so a crash between
    the commit and the cursor write is reconciled instead of redone · a report
    of applied / skipped-changed / skipped-text / skipped-job / skipped-missing
    / refused. `refused` counts the two per-row refusals that are not skips: a
    copy row whose embedding is NULL (a metadata-only retag — carrying it back
    would BLANK a live vector to gain a tag), and a copy row whose own source
    text no longer hashes to what the manifest recorded, which unbinds the
    vector from the text it was made of.

NOT A MemoryStore. The live database is opened as a plain sqlite3 connection,
because constructing a MemoryStore runs `_migrate` and would ALTER the schema of
a 2.9 GB production store as a side effect of a read-mostly tool. This tool
never changes a live schema; if the live store predates a column it needs
(session_index.model), it says so and refuses.

Usage:
    writeback_vectors.py <live.db> <copy.db> --build-manifest <out.jsonl>
    writeback_vectors.py <live.db> <migrated_copy.db> --manifest <m.jsonl>
                         [--dry-run] [--batch N] [--tables T ...] [--limit N]
                         [--state PATH] [--expect-tag TAG] [--expect-width N]

    --dry-run       opens the LIVE db READ-ONLY and writes nothing at all (no
                    UPDATE, no state file). Reports exactly what a real run
                    would apply and skip.
    --batch N       rows per transaction (default 500, hard cap 500).
    --tables        restrict to some of the five vector tables.
    --limit N       stop after N candidate rows (a bounded trial run).
    --expect-tag / --expect-width
                    the live gateway's active geometry. When omitted, it is
                    resolved from the live config the same way migrate_vectors
                    resolves it (which probes the local endpoint).

Exit codes: 0 = everything applied (or dry-run clean)
            1 = REFUSAL — nothing written
            2 = completed with rows skipped or left for a later pass
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sqlite3
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from engine.config import Config
from engine.embeddings import (
    VECTOR_TABLES,
    embedder_model_tag,
    expected_blob_len,
    get_embedder,
    is_usable_model_tag,
)
from engine.reducer import (
    belief_vector_text,
    observed_vector_text,
    projection_vector_text,
    session_vector_text,
)

MANIFEST_KIND = "chronicle-writeback-manifest"
MANIFEST_VERSION = 1

# Bound from embeddings.VECTOR_TABLES, never re-typed: three hand-typed copies
# of this list is how session_index and projection_vectors fell out of A0's
# coverage in the first place (A0e/D5).
_TABLES = VECTOR_TABLES

# W8: batches <= 500 rows. The cap is the contract, not a tunable.
_DEFAULT_BATCH = 500
_MIN_BATCH, _MAX_BATCH = 1, 500
# W8: >= 5s. A live gateway holds brief write locks; out-wait them.
_BUSY_TIMEOUT_MS = 30000

# W6's at-risk threshold. This WAS store.enqueue_embed_job's
# `(text or "")[:8000]`, re-stated here and pinned by a test that read the
# literal back out of engine/store.py so the two could not drift.
#
# Ladder-10 A0g removed that clamp from the engine entirely (see the W6 note in
# the module docstring), so there is no longer a literal to track. The number
# stays as the boundary of the rows an OLDER engine may already have truncated
# on disk, which is what the exception is actually about, and the drift test
# now pins the post-A0g invariant instead: that enqueue_embed_job applies no
# independent clamp at all. A test that greps for deleted code proves nothing;
# one that pins "the clamp is gone" is its successor.
_JOB_PAYLOAD_CLAMP = 8000

# W4: "pending or claimed". `running` is a job a worker has claimed and may be
# embedding right now.
_LIVE_JOB_STATUSES = ("pending", "running")
# Needles per W4 query. One scan of curation_jobs per chunk, well inside every
# SQLite build's expression-depth and bound-parameter limits.
_JOB_NEEDLE_CHUNK = 100

# The natural key of each vector table, in the order this tool writes them.
_KEYS = {
    "observed_vectors": ("event_id",),
    "memory_vectors": ("belief_id", "kind"),
    "session_index": ("session_id",),
    "projection_vectors": ("provider", "external_id"),
    "query_proxy_vectors": ("belief_id", "proxy_idx"),
}


class Refused(RuntimeError):
    """A condition under which this tool must not write at all. Always exit 1,
    always before (or instead of) a write — never a partially applied run."""


# --------------------------------------------------------------------------
# hashing / small helpers
# --------------------------------------------------------------------------
def sha_blob(blob):
    """sha256 DIGEST of an embedding, or None for a NULL one. `None` is a
    distinct pre-image from "a blob that happens to hash to the empty digest".

    Raw 32-byte digests, not hex: the manifest index holds two per row and is
    held in memory for a whole table, so the hex form costs ~100 bytes a row for
    nothing. Hex is used only in the manifest FILE, where a human reads it."""
    if blob is None:
        return None
    if isinstance(blob, memoryview):
        blob = blob.tobytes()
    return hashlib.sha256(bytes(blob)).digest()


def sha_text(text):
    return hashlib.sha256((text or "").encode("utf-8")).digest()


def _hex(digest):
    return None if digest is None else digest.hex()


def _unhex(value):
    return None if value is None else bytes.fromhex(value)


def _job_target_id(table, key):
    """The `target_id` an embed job would carry for this row (W4).

    Mirrors the enqueue sites: observed -> event_id, belief kinds -> belief_id,
    session -> session_id, projection -> the namespaced `proj:provider:id`.

    query_proxy_vectors has NO job of its own — the embed queue is keyed
    (target, kind) and cannot express a variable-length proxy set — so a proxy
    is matched against its PARENT belief's target. That is deliberately
    conservative: a queued re-embed of the parent cannot be nullified by writing
    the proxy row, but a parent being actively rewritten is a parent whose
    proxies are about to be regenerated, and skipping is free (the row is
    retried by a later pass) while a wrong write is not."""
    if table == "projection_vectors":
        return "proj:%s:%s" % (key[0], key[1])
    return str(key[0])


def _authority_text(conn, table, key):
    """`(text, recoverable)` — THE text this row's vector is made of, resolved
    through the reducer's four accessors by object.

    There is no kind->column map here and there must never be one: a second
    answer to "what text was this vector made of" is exactly the defect A0fix
    removed (`procedure` -> `procedures.name`, a 40-char truncation, stamped
    canonical). tests/test_writeback_vectors.py asserts this module binds the
    same function objects the heal and migrate_vectors bind."""
    if table == "observed_vectors":
        return observed_vector_text(conn, key[0])
    if table == "memory_vectors":
        return belief_vector_text(conn, key[1], key[0])
    if table == "session_index":
        return session_vector_text(conn, key[0])
    if table == "projection_vectors":
        return projection_vector_text(conn, key[0], key[1])
    if table == "query_proxy_vectors":
        # The proxy's own stored question IS its source text (§E2): doc2query
        # generated it, the writer embedded it verbatim, and it is persisted
        # right here. There is no reducer accessor because there is nothing to
        # reconstruct.
        try:
            row = conn.execute(
                "SELECT question FROM query_proxy_vectors WHERE belief_id=? AND proxy_idx=?",
                (key[0], key[1])).fetchone()
        except sqlite3.Error:
            return "", False
        if row is None:
            return "", False
        return (row[0] or ""), bool(row[0])
    return "", False


def _open_ro(path):
    """Read-only connection. `mode=ro` is enforced by SQLite itself, so
    --dry-run cannot write the live store even through a coding mistake."""
    conn = sqlite3.connect("file:%s?mode=ro" % Path(path).as_posix(), uri=True,
                           isolation_level=None)
    conn.execute("PRAGMA busy_timeout=%d" % _BUSY_TIMEOUT_MS)
    return conn


def _open_rw(path):
    """Read-write connection with autocommit off at the Python layer
    (`isolation_level=None`), so every transaction here is an EXPLICIT
    `BEGIN IMMEDIATE` and nothing is ever written outside one."""
    conn = sqlite3.connect(str(path), timeout=_BUSY_TIMEOUT_MS / 1000.0,
                           isolation_level=None)
    conn.execute("PRAGMA busy_timeout=%d" % _BUSY_TIMEOUT_MS)
    return conn


def _has_table(conn, table):
    try:
        return conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
                            (table,)).fetchone() is not None
    except sqlite3.Error:
        return False


def _cols(conn, table):
    try:
        return [r[1] for r in conn.execute('PRAGMA table_info("%s")' % table).fetchall()]
    except sqlite3.Error:
        return []


def _where(table):
    return " AND ".join("%s=?" % c for c in _KEYS[table])


# --------------------------------------------------------------------------
# manifest
# --------------------------------------------------------------------------
def _row_counts(conn, tables):
    out = {}
    for t in tables:
        if not _has_table(conn, t):
            continue
        try:
            out[t] = conn.execute('SELECT COUNT(*) FROM "%s"' % t).fetchone()[0]
        except sqlite3.Error:
            continue
    return out


def build_manifest(copy_db, out_path, tables=None, live_db=None, verbose=True):
    """Record the pre-migration state of a PRISTINE copy: one line per vector
    row, (model, sha256(embedding)) plus the authority text's hash and length.

    Run this between the `.backup` and the migration. Running it on an ALREADY
    MIGRATED copy would record the post-migration vectors as the pre-image and
    turn W2 into a tautology, so the header records the copy's own tag
    histogram; a write-back whose manifest pre-image equals the copy's current
    state for every row simply finds no work (W7) rather than writing blind."""
    tables = list(tables or _TABLES)
    src = Path(copy_db).expanduser()
    if not src.exists():
        raise Refused("no database at %s" % src)
    conn = _open_ro(src)
    try:
        counts = _row_counts(conn, tables)
        header = {
            "_manifest": MANIFEST_KIND,
            "version": MANIFEST_VERSION,
            "created_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "copy_db": str(src),
            "live_db": str(live_db or ""),
            "tables": tables,
            "row_counts": counts,
            "job_payload_clamp": _JOB_PAYLOAD_CLAMP,
        }
        tmp = Path(str(out_path) + ".partial")
        n = 0
        with open(tmp, "w") as fh:
            fh.write(json.dumps(header, sort_keys=True) + "\n")
            for table in tables:
                if table not in counts:
                    continue
                keys = _KEYS[table]
                sql = 'SELECT %s, model, embedding FROM "%s" ORDER BY rowid' % (
                    ", ".join(keys), table)
                cur = conn.execute(sql)
                while True:
                    rows = cur.fetchmany(256)
                    if not rows:
                        break
                    for r in rows:
                        key = list(r[:len(keys)])
                        model, blob = r[len(keys)], r[len(keys) + 1]
                        text, recoverable = _authority_text(conn, table, key)
                        fh.write(json.dumps({
                            "t": table, "k": key,
                            "m": model, "h": _hex(sha_blob(blob)),
                            "b": (None if blob is None else len(blob)),
                            "x": _hex(sha_text(text)) if recoverable else None,
                            "n": len(text or ""), "r": bool(recoverable),
                        }, sort_keys=True) + "\n")
                        n += 1
                if verbose:
                    print("  manifest %-22s %8d rows" % (table, counts.get(table, 0)),
                          flush=True)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(str(tmp), str(out_path))
        if verbose:
            print("manifest: %d rows -> %s" % (n, out_path))
        return n
    finally:
        conn.close()


# A manifest record, held in memory as a 5-tuple rather than a dict: the index
# covers one whole table at a time and a dict per row costs ~230 bytes for five
# fields. Field order is fixed here and nowhere else.
_M, _H, _B, _X, _N = 0, 1, 2, 3, 4


def manifest_header(path):
    """Just the header line. Read before anything else so a run that is about to
    be refused for the wrong manifest is refused before 60 MB is parsed."""
    p = Path(path).expanduser() if path is not None else None
    if p is None or not p.exists():
        raise Refused(
            "no manifest at %s. W2 compares the live row against its PRE-MIGRATION "
            "(model, sha256(embedding)), which exists nowhere else once the copy is "
            "migrated. Build it from the pristine copy BEFORE migrating: "
            "writeback_vectors.py <live.db> <copy.db> --build-manifest %s"
            % (p, p))
    with open(p) as fh:
        first = fh.readline().strip()
    try:
        header = json.loads(first or "{}")
    except ValueError:
        header = None
    if not isinstance(header, dict) or header.get("_manifest") != MANIFEST_KIND:
        raise Refused(
            "%s is not a Chronicle write-back manifest (no %r header). Refusing "
            "rather than guessing at a pre-image." % (p, MANIFEST_KIND))
    return header


def load_manifest(path, tables):
    """`{key-tuple: (model, blob-digest, blob-len, text-digest, text-len)}` for
    the named tables.

    ONE TABLE AT A TIME is how this is called. The index has to be consulted per
    row inside a write transaction, so it cannot live on disk — but holding all
    216k production rows at once cost ~500 MB of RSS on a box that runs a live
    agent and has an OOM history. Per table the peak is the largest table
    (memory_vectors, ~95k), and the file is simply re-read for the next one."""
    p = Path(path).expanduser()
    want = set(tables)
    index = {}
    with open(p) as fh:
        for lineno, line in enumerate(fh, 1):
            line = line.strip()
            if not line:
                continue
            if lineno == 1:
                continue                      # the header, read by manifest_header
            try:
                rec = json.loads(line)
            except ValueError as e:
                raise Refused("manifest %s line %d is not JSON (%s)" % (p, lineno, e))
            if rec.get("t") not in want:
                continue
            index[tuple(rec.get("k") or ())] = (
                rec.get("m"), _unhex(rec.get("h")), rec.get("b"),
                _unhex(rec.get("x")), int(rec.get("n") or 0))
    return index


# --------------------------------------------------------------------------
# the live geometry (W5)
# --------------------------------------------------------------------------
def load_config():
    """Chronicle's own config resolution (DEFAULTS + $HERMES_HOME/config.yaml's
    `memory:` block), identical to scripts/migrate_vectors.load_config. Never a
    raw-YAML read that bypasses the defaults — that is how enrich_embeddings.py
    died on a missing `base_url` while reporting success."""
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
            print("(could not read %s: %s)" % (cfg_path, e))
    return Config(overrides)


def resolve_live_geometry(expect_tag=None, expect_width=None, cfg=None, embedder=None):
    """`(tag, width)` the LIVE gateway is stamping right now.

    Explicit `--expect-tag/--expect-width` win, so an operator can pin the pair
    they verified against rows written since deploy (8.6 step 0) instead of
    trusting a probe. Otherwise the configured embedder answers, through the
    same A0 choke point every write site uses — a duck-typed embedder cannot
    smuggle a non-canonical tag in here.

    A tag that names no geometry ('degraded', 'auto') is a REFUSAL: stamping it
    over a live row would label a vector with something that is not a model."""
    if expect_tag is not None and expect_width is not None:
        tag, width = str(expect_tag), int(expect_width)
    else:
        if embedder is None:
            cfg = cfg if cfg is not None else load_config()
            embedder = get_embedder(
                cfg.get("embeddings.model"),
                cfg.get("embeddings.dimensions"),
                cfg.get("embeddings.base_url"),
                cfg.get("embeddings.api_key"),
                cfg.get("embeddings.max_input_tokens"),
                cfg.get("embeddings.overflow"),
                cfg.get("embeddings.task_prefixes"),
                cfg.get("embeddings.allow_remote"),
            )
        tag = embedder_model_tag(embedder)
        width = expected_blob_len(embedder)
        if expect_tag is not None:
            tag = str(expect_tag)
        if expect_width is not None:
            width = int(expect_width)
    if not is_usable_model_tag(tag):
        raise Refused(
            "the live embedder resolved to %r, which names no geometry. Nothing is "
            "written: a write-back stamps a tag onto rows it did not embed, and a "
            "non-geometry tag would mark them permanently unrepairable. Start the "
            "gateway, or pass --expect-tag/--expect-width for the geometry you "
            "verified on live." % tag)
    if not width or width <= 0:
        raise Refused(
            "the live embedder does not report a width. W5 refuses to write a blob "
            "whose length it cannot check; pass --expect-width.")
    return tag, width


# --------------------------------------------------------------------------
# resumable state (W8)
# --------------------------------------------------------------------------
class State:
    """Cursor + counters + a write-ahead `inflight` record, on durable disk.

    THE CRASH THIS SHAPE EXISTS FOR. The cursor cannot live in the same
    transaction as the write (it is a different file) and it must not live in
    the live database (this tool does not add tables to a 2.9 GB production
    store). So there is a window between COMMIT and the cursor write. A bare
    cursor would make a SIGKILL in that window re-process the batch, and the
    re-processed rows would fail W2 against their own new values and be counted
    `skipped-changed` — a run that silently reports its own successful writes as
    conflicts. Instead the batch's intended (key -> new sha) map is written
    BEFORE the commit and cleared after it; on resume each inflight row is
    reconciled against live: already holding the new value == applied, anything
    else == retry. The write itself is idempotent either way, because W2 is a
    compare-and-swap, not a blind write."""

    def __init__(self, path):
        self.path = Path(path)
        self.data = {"cursor": {}, "counts": {}, "inflight": None, "manifest_sha": None}
        if self.path.exists():
            try:
                self.data.update(json.loads(self.path.read_text()) or {})
            except (ValueError, OSError):
                raise Refused(
                    "state file %s exists but is unreadable. Refusing: a resume that "
                    "cannot read its cursor would re-walk rows it already decided on. "
                    "Move it aside to start a fresh pass." % self.path)

    def bind(self, manifest_sha):
        prior = self.data.get("manifest_sha")
        if prior and prior != manifest_sha:
            raise Refused(
                "state file %s was written for a DIFFERENT manifest (%s != %s). "
                "A cursor only means anything against the work-set it was counted "
                "over." % (self.path, prior[:12], manifest_sha[:12]))
        self.data["manifest_sha"] = manifest_sha

    def cursor(self, table):
        return int(self.data["cursor"].get(table, 0) or 0)

    def save(self):
        tmp = Path(str(self.path) + ".partial")
        with open(tmp, "w") as fh:
            fh.write(json.dumps(self.data, sort_keys=True))
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(str(tmp), str(self.path))


# --------------------------------------------------------------------------
# the write-back
# --------------------------------------------------------------------------
_COUNTERS = ("applied", "applied-at-risk", "skipped-changed", "skipped-text",
             "skipped-job", "skipped-missing", "refused", "unchanged")


class WriteBack:
    def __init__(self, live_conn, copy_conn, manifest_path, active_tag, expect_len,
                 batch=_DEFAULT_BATCH, tables=None, limit=None, dry_run=False,
                 state=None, verbose=True):
        self.live = live_conn
        self.copy = copy_conn
        # The path, not a loaded index: run() loads ONE table at a time and drops
        # it again, which is what keeps peak RSS proportional to the largest
        # table rather than to the whole store.
        self.manifest_path = manifest_path
        self.manifest = {}
        self.active_tag = active_tag
        self.expect_len = int(expect_len)
        self.batch = max(_MIN_BATCH, min(_MAX_BATCH, int(batch)))
        self.tables = [t for t in _TABLES if t in (tables or _TABLES)]
        self.limit = limit
        self.dry_run = bool(dry_run)
        self.state = state
        self.verbose = verbose
        self.counts = dict((k, 0) for k in _COUNTERS)
        self.skipped_names = dict((k, []) for k in _COUNTERS)
        self.seen = 0
        self._banked = dict((state.data.get("totals") or {})) if state is not None else {}
        self._t0 = time.time()

    def _say(self, msg):
        if self.verbose:
            print(msg, flush=True)

    def _note(self, bucket, ident):
        self.counts[bucket] += 1
        if len(self.skipped_names[bucket]) < 10:
            self.skipped_names[bucket].append(ident)

    # -- W4 -------------------------------------------------------------
    def _queued_targets(self, targets):
        """The subset of `targets` that has a pending or claimed `embed` job.

        ONE scan of curation_jobs per batch, restricted to the batch's own
        needles, rather than one scan per row: the needle is the canonical json
        rendering of the target_id key, the same `instr` form
        reducer.projection_vector_text uses, so it cannot match a job that
        merely mentions the id inside its text. Read INSIDE the write
        transaction, where no other writer can enqueue or claim a job, so the
        answer cannot go stale between the test and the UPDATE."""
        if not targets:
            return set()
        needles = [json.dumps({"target_id": t}, sort_keys=True)[1:-1] for t in targets]
        status_ph = ",".join("?" * len(_LIVE_JOB_STATUSES))
        rows = []
        # Chunked so the OR-list stays far below SQLITE_MAX_EXPR_DEPTH and the
        # bound-parameter limit on an old SQLite. A refusal here would stop a
        # correct run; a chunk boundary costs one extra scan.
        for i in range(0, len(needles), _JOB_NEEDLE_CHUNK):
            chunk = needles[i:i + _JOB_NEEDLE_CHUNK]
            ors = " OR ".join("instr(payload, ?)>0" for _ in chunk)
            sql = ("SELECT payload FROM curation_jobs WHERE task='embed' AND status IN (%s) "
                   "AND (%s)" % (status_ph, ors))
            try:
                rows.extend(self.live.execute(
                    sql, tuple(_LIVE_JOB_STATUSES) + tuple(chunk)).fetchall())
            except sqlite3.Error as e:
                # No curation_jobs table at all, or a query this SQLite cannot
                # run. W4 cannot be evaluated, and an un-evaluated guard is not a
                # passed guard.
                raise Refused(
                    "live curation_jobs could not be queried (%s); W4 (no pending "
                    "embed job for the target) cannot be checked and this tool will "
                    "not write without it." % e)
        hit = set()
        want = set(targets)
        for (raw,) in rows:
            if isinstance(raw, (bytes, bytearray)):
                raw = raw.decode("utf-8", "replace")
            try:
                payload = json.loads(raw or "{}")
            except (ValueError, TypeError):
                continue
            if isinstance(payload, dict) and payload.get("target_id") in want:
                hit.add(payload["target_id"])
        return hit

    # -- the candidate walk (W7) ----------------------------------------
    def _candidates(self, table):
        """Yield `(rowid, key, new_model, new_blob, rec)` for rows the migration
        CHANGED on the copy, in rowid order from the persisted cursor.

        The copy is frozen for the whole write-back, so its rowids are stable
        and a rowid cursor is an exact resume point. Blobs are streamed in
        batch-sized chunks: materialising 216k x 3072 bytes would be 660 MB."""
        keys = _KEYS[table]
        cursor = self.state.cursor(table) if self.state else 0
        sql = ('SELECT rowid, %s, model, embedding FROM "%s" WHERE rowid > ? '
               'ORDER BY rowid LIMIT ?' % (", ".join(keys), table))
        while True:
            rows = self.copy.execute(sql, (cursor, self.batch)).fetchall()
            if not rows:
                return
            cursor = rows[-1][0]
            out = []
            for r in rows:
                rowid = r[0]
                key = tuple(r[1:1 + len(keys)])
                model, blob = r[1 + len(keys)], r[2 + len(keys)]
                rec = self.manifest.get(key)
                if rec is None:
                    # Cannot happen against the copy this manifest was built
                    # from; preflight has already refused the run if it does.
                    raise Refused(
                        "copy row %s %r has no manifest entry — this manifest was not "
                        "built from this copy." % (table, key))
                if model == rec[_M] and sha_blob(blob) == rec[_H]:
                    self.counts["unchanged"] += 1      # W7: migration left it alone
                    continue
                out.append((rowid, key, model, blob, rec))
            yield cursor, out

    # -- one batch, one BEGIN IMMEDIATE ---------------------------------
    def _apply_batch(self, table, items):
        """Every W-check and the UPDATE for one batch, inside ONE transaction."""
        where = _where(table)
        targets = sorted(set(_job_target_id(table, it[1]) for it in items))
        applied_rows = []
        self.live.execute("BEGIN IMMEDIATE" if not self.dry_run else "BEGIN")
        try:
            queued = self._queued_targets(targets)
            for rowid, key, new_model, new_blob, rec in items:
                ident = "%s:%s" % (table, "/".join(str(k) for k in key))
                # ---- W5, part 1: a NULL embedding is a PER-ROW refusal, not a
                # geometry failure. The migration's retag pass legitimately
                # rewrites `model` on a row whose embedding IS NULL (it is
                # metadata-only), and carrying that back would blank a live
                # vector to gain a tag. Refuse the row, keep going.
                if new_blob is None:
                    self._note("refused", ident + " (NULL embedding on the copy)")
                    continue
                # ---- W5, part 2: geometry, byte-exact. NOT a skip: a violation
                # means the copy was migrated onto a geometry live is not
                # serving, and the whole run must stop. Preflight normally
                # catches this before a single transaction opens.
                if new_model != self.active_tag or len(new_blob) != self.expect_len:
                    raise Refused(
                        "W5: %s carries tag %r / %d bytes on the copy; live is serving "
                        "%r / %d bytes. The copy was migrated onto a different geometry "
                        "than the live gateway."
                        % (ident, new_model, len(new_blob),
                           self.active_tag, self.expect_len))
                # ---- the copy's own source text must still be the text the
                # manifest recorded. This is what BINDS the vector we are about
                # to carry to a text: without it, "the live text still hashes to
                # x" only says live did not move, not that the copy's vector was
                # made of x.
                copy_text, copy_ok = _authority_text(self.copy, table, key)
                if not copy_ok or sha_text(copy_text) != rec[_X]:
                    self._note("refused", ident + " (copy text moved under the manifest)")
                    continue
                # ---- live pre-image, read inside the transaction
                row = self.live.execute(
                    'SELECT model, embedding FROM "%s" WHERE %s' % (table, where),
                    key).fetchone()
                if row is None:
                    # W1: retracted / forgotten / deleted on live after the
                    # snapshot. It stays deleted.
                    self._note("skipped-missing", ident)
                    continue
                live_model, live_blob = row[0], row[1]
                # ---- W4
                if _job_target_id(table, key) in queued:
                    self._note("skipped-job", ident)
                    continue
                # ---- W3 + W6: the authority text, recomputed ON LIVE
                live_text, recoverable = _authority_text(self.live, table, key)
                if not recoverable or sha_text(live_text) != rec[_X]:
                    self._note("skipped-text", ident)
                    continue
                at_risk = (len(live_text or "") > _JOB_PAYLOAD_CLAMP or
                           rec[_N] > _JOB_PAYLOAD_CLAMP)
                # ---- W2, unless W6 exempts the row
                if not at_risk:
                    if live_model != rec[_M] or sha_blob(live_blob) != rec[_H]:
                        self._note("skipped-changed", ident)
                        continue
                if self.dry_run:
                    self.counts["applied"] += 1
                    if at_risk:
                        self.counts["applied-at-risk"] += 1
                    continue
                # ---- W1: UPDATE on the natural key. `model IS ?` (not `=`) so a
                # NULL-tagged pre-image is matched rather than silently missed,
                # and the CAS is restated in SQL as well as in Python.
                cur = self.live.execute(
                    'UPDATE "%s" SET embedding=?, model=? WHERE %s AND model IS ?'
                    % (table, where),
                    (new_blob, self.active_tag) + tuple(key) + (live_model,))
                if not cur.rowcount:
                    self._note("skipped-changed", ident)
                    continue
                applied_rows.append({"k": list(key), "h": _hex(sha_blob(new_blob))})
                self.counts["applied"] += 1
                if at_risk:
                    self.counts["applied-at-risk"] += 1
            if self.dry_run:
                self.live.execute("ROLLBACK")
            else:
                # W8 write-ahead: the intent is on disk BEFORE the commit, so a
                # crash in the commit window is reconciled, never redone.
                if self.state is not None:
                    self.state.data["inflight"] = {
                        "table": table, "applied": applied_rows,
                        "cursor_after": items[-1][0] if items else None}
                    self.state.save()
                self.live.execute("COMMIT")
        except Exception:
            try:
                self.live.execute("ROLLBACK")
            except sqlite3.Error:
                pass
            raise
        return applied_rows

    def _reconcile_inflight(self):
        """Settle a batch that was interrupted between COMMIT and the cursor
        write. Each row is asked of LIVE: does it already hold the value that
        batch intended? Then it committed and counts applied; otherwise the
        batch rolled back and the row is simply left to the normal walk (the
        cursor was never advanced past it)."""
        flight = (self.state.data.get("inflight") if self.state else None) or None
        if not flight:
            return
        table = flight.get("table")
        applied = flight.get("applied") or []
        settled = 0
        if table in _KEYS:
            where = _where(table)
            for entry in applied:
                key = tuple(entry.get("k") or ())
                want_sha = entry.get("h")
                if not key:
                    continue
                try:
                    row = self.live.execute(
                        'SELECT model, embedding FROM "%s" WHERE %s' % (table, where),
                        key).fetchone()
                except sqlite3.Error:
                    row = None
                if row is not None and row[0] == self.active_tag and \
                        _hex(sha_blob(row[1])) == want_sha:
                    self.counts["applied"] += 1
                    settled += 1
        if settled:
            self._say("  resume: %d row(s) from the interrupted batch had already "
                      "committed; counted applied, not rewritten." % settled)
            if flight.get("cursor_after") is not None:
                self.state.data["cursor"][table] = flight["cursor_after"]
        self.state.data["inflight"] = None
        self.state.save()

    def run(self):
        if self.state is not None and not self.dry_run:
            self._reconcile_inflight()
        for table in self.tables:
            if not _has_table(self.live, table):
                self._say("  %s: absent on live — skipped" % table)
                continue
            if not _has_table(self.copy, table):
                continue
            self.manifest = load_manifest(self.manifest_path, [table])
            for cursor_after, items in self._candidates(table):
                if items:
                    self.seen += len(items)
                    self._apply_batch(table, items)
                if self.state is not None and not self.dry_run:
                    self.state.data["cursor"][table] = cursor_after
                    self.state.data["counts"] = dict(self.counts)
                    # Cumulative across resumes, so a run interrupted five times
                    # can still answer "how many rows did the write-back apply",
                    # which is the number the post-write-back health plateau
                    # (8.6 step 8) is checked against.
                    self.state.data["totals"] = dict(
                        (k, self._banked.get(k, 0) + self.counts[k]) for k in _COUNTERS)
                    self.state.data["inflight"] = None
                    self.state.save()
                if items:
                    self._progress(table)
                if self.limit and self.seen >= self.limit:
                    self._say("  --limit %d reached; stopping. Re-run to continue."
                              % self.limit)
                    self.manifest = {}
                    return
            self.manifest = {}

    def _progress(self, table):
        el = time.time() - self._t0
        self._say("  ...%s: applied %d, skipped %d, refused %d  (%.1fs)"
                  % (table, self.counts["applied"],
                     sum(self.counts[k] for k in _COUNTERS if k.startswith("skipped")),
                     self.counts["refused"], el))


# --------------------------------------------------------------------------
# preflight (nothing is written until all of this passes)
# --------------------------------------------------------------------------
def preflight(live, copy, header, manifest_path, tables, active_tag, expect_len,
              verbose=True):
    """Everything that must hold before the first UPDATE.

    Checked here rather than per row because these are all properties of the
    PAIR of databases: a failure means the operator handed this tool the wrong
    copy, the wrong manifest or the wrong geometry, and there is then no row for
    which writing would be correct. One pass per table over key + model +
    length(embedding) — never a blob.

    EVERY table is checked before ANY is written, and every problem found is
    reported together: an operator who has to re-run to discover the second
    reason is an operator who re-runs against production. The manifest is loaded
    one table at a time and dropped again, so this costs the largest table's
    index, not the whole store's.

    Nothing is written until this returns."""
    problems = []

    # (1) the live schema can hold what this tool stamps. session_index.model is
    #     an A0e addition; a live store that predates it has nowhere to record a
    #     geometry, and this tool does not ALTER a production schema to make room.
    for t in tables:
        if not _has_table(live, t):
            continue
        cols = _cols(live, t)
        if "model" not in cols:
            problems.append(
                "live %s has no `model` column (pre-A0e schema). A write-back cannot "
                "stamp a geometry it has nowhere to record, and this tool does not "
                "ALTER a live schema. Let the engine upgrade the store, then re-run."
                % t)
        if "embedding" not in cols:
            problems.append("live %s has no `embedding` column." % t)

    # (2) the manifest describes THIS copy. The migration only ever UPDATEs, so
    #     a changed row count means a different database.
    counts_now = _row_counts(copy, tables)
    counts_then = header.get("row_counts") or {}
    for t in tables:
        if t in counts_now and t in counts_then and counts_now[t] != counts_then[t]:
            problems.append(
                "%s holds %d rows on the copy but the manifest recorded %d — this "
                "manifest was built from a different database."
                % (t, counts_now[t], counts_then[t]))
        if t in counts_now and t not in counts_then:
            problems.append("%s is present on the copy but absent from the manifest." % t)

    # (3) no copy row is missing a pre-image, and every row the migration CHANGED
    #     carries the geometry live is serving (W5, store-wide).
    gaps, gap_names = 0, []
    w5, w5_names = 0, []
    changed = 0
    total = 0
    for t in tables:
        if t not in counts_now:
            continue
        manifest = load_manifest(manifest_path, [t])
        keys = _KEYS[t]
        cur = copy.execute('SELECT %s, model, length(embedding) FROM "%s"'
                           % (", ".join(keys), t))
        while True:
            rows = cur.fetchmany(1000)
            if not rows:
                break
            for r in rows:
                total += 1
                key = tuple(r[:len(keys)])
                model, blen = r[len(keys)], r[len(keys) + 1]
                rec = manifest.get(key)
                ident = "%s:%s" % (t, "/".join(str(x) for x in key))
                if rec is None:
                    gaps += 1
                    if len(gap_names) < 5:
                        gap_names.append(ident)
                    continue
                if model == rec[_M] and blen == rec[_B]:
                    continue          # W7: untouched by the migration
                changed += 1
                if blen is None:
                    continue          # a metadata-only retag of a NULL vector:
                                      # refused per row, not a geometry failure
                if model != active_tag or blen != expect_len:
                    w5 += 1
                    if len(w5_names) < 5:
                        w5_names.append("%s (%r/%s)" % (ident, model, blen))
        manifest = None
    if gaps:
        problems.append(
            "%d copy row(s) have no manifest entry (e.g. %s). W2 has no pre-image for "
            "them, and a row this tool cannot compare-and-swap is a row it must not "
            "write." % (gaps, ", ".join(gap_names)))
    if w5:
        problems.append(
            "W5: %d row(s) changed by the migration do not carry the live geometry "
            "%r / %d bytes (e.g. %s). The copy was migrated onto a different model or "
            "width than the gateway is serving; a same-width different model passes "
            "every tag check, so this refusal is the last cheap guard before %d rows "
            "of live memory are overwritten."
            % (w5, active_tag, expect_len, ", ".join(w5_names), changed))
    if verbose:
        print("copy: %d row(s) changed by the migration, %d unchanged"
              % (changed, total - changed))
    if problems:
        raise Refused("preflight failed:\n  - " + "\n  - ".join(problems))
    return changed


def live_survey(live, tables):
    """What live is holding right now, per (tag, width). Printed, never acted
    on: it is the number an operator checks the active tag against (8.6 step 0),
    and a tool that only printed its own verdict would be asking to be trusted."""
    out = []
    for t in tables:
        if not _has_table(live, t):
            continue
        try:
            rows = live.execute(
                'SELECT model, length(embedding), COUNT(*) FROM "%s" GROUP BY 1,2 '
                'ORDER BY 3 DESC' % t).fetchall()
        except sqlite3.Error:
            continue
        for model, blen, cnt in rows:
            out.append((t, model, blen, cnt))
    return out


# --------------------------------------------------------------------------
# entry point
# --------------------------------------------------------------------------
def writeback(live_db, copy_db, manifest_path=None, dry_run=False,
              batch=_DEFAULT_BATCH, tables=None, limit=None, state_path=None,
              expect_tag=None, expect_width=None, cfg=None, embedder=None,
              verbose=True):
    live_path, copy_path = Path(live_db).expanduser(), Path(copy_db).expanduser()
    live = copy = None
    progress = {}
    try:
        if not live_path.exists():
            raise Refused("no live database at %s" % live_path)
        if not copy_path.exists():
            raise Refused("no migrated copy at %s" % copy_path)
        tables = [t for t in _TABLES if t in (tables or _TABLES)]
        if not tables:
            raise Refused("--tables selected nothing; valid tables: %s"
                          % ", ".join(_TABLES))
        if manifest_path is None:
            raise Refused(
                "--manifest is required. W2 compares each live row against its "
                "PRE-MIGRATION (model, sha256(embedding)); without that record "
                "there is no compare-and-swap, only a blind overwrite of whatever "
                "the live agent has written since the snapshot. Build it from the "
                "pristine copy BEFORE migrating (--build-manifest).")
        active_tag, expect_len = resolve_live_geometry(
            expect_tag, expect_width, cfg=cfg, embedder=embedder)
        header = manifest_header(manifest_path)
        manifest_sha = hashlib.sha256(
            Path(manifest_path).expanduser().read_bytes()).hexdigest()

        live = _open_ro(live_path) if dry_run else _open_rw(live_path)
        copy = _open_ro(copy_path)

        print("live db        : %s" % live_path)
        print("migrated copy  : %s" % copy_path)
        print("manifest       : %s  (%d rows, built %s)"
              % (manifest_path, sum((header.get("row_counts") or {}).values()),
                 header.get("created_at")))
        print("active tag     : %s" % active_tag)
        print("expected width : %d dims (%d bytes)" % (expect_len // 4, expect_len))
        print("mode           : %s" % ("DRY RUN (live opened read-only, nothing written)"
                                       if dry_run else "WRITE"))
        for t, model, blen, cnt in live_survey(live, tables):
            print("  live %-22s %-42r %6s bytes  %8d rows"
                  % (t, model, blen, cnt))

        preflight(live, copy, header, manifest_path, tables, active_tag, expect_len,
                  verbose=verbose)

        state = None
        if not dry_run:
            state = State(state_path or (str(manifest_path) + ".state.json"))
            state.bind(manifest_sha)

        wb = WriteBack(live, copy, manifest_path, active_tag, expect_len, batch=batch,
                       tables=tables, limit=limit, dry_run=dry_run, state=state,
                       verbose=verbose)
        progress["wb"] = wb
        wb.run()

        print("\napplied        : %d  (of which N1 at-risk, W2 bypassed per W6: %d)"
              % (wb.counts["applied"], wb.counts["applied-at-risk"]))
        for bucket in ("skipped-changed", "skipped-text", "skipped-job",
                       "skipped-missing", "refused"):
            names = wb.skipped_names[bucket]
            print("%-15s: %d%s" % (bucket, wb.counts[bucket],
                                   ("   e.g. " + ", ".join(names)) if names else ""))
        print("unchanged on copy (nothing to carry back): %d" % wb.counts["unchanged"])
        skipped = sum(wb.counts[k] for k in _COUNTERS if k.startswith("skipped"))
        if skipped:
            print(
                "\nSkipped rows were LEFT AS THEY ARE on live — never overwritten, never "
                "blanked. `skipped-changed`/`skipped-text` mean the live path now owns "
                "those rows; `skipped-job` means a queued re-embed does. They converge "
                "through normal heal, except any at-risk row (> %d chars), which needs a "
                "targeted pass after A0g." % _JOB_PAYLOAD_CLAMP)
            return 2
        if wb.counts["refused"]:
            return 2
        if limit and wb.seen >= limit:
            return 2
        print("\ncomplete: every row the migration changed on the copy is either applied "
              "or accounted for.")
        return 0
    except Refused as e:
        print("\nREFUSED: %s" % e)
        wb = progress.get("wb")
        done = wb.counts["applied"] if wb is not None else 0
        if done:
            # Honesty over reassurance: a refusal raised mid-run rolls back the
            # batch it was raised in, but earlier batches are committed and are
            # NOT undone. Every one of them passed W1-W7 and is a correct row;
            # the cursor records where to resume once the cause is fixed.
            print("%d row(s) were applied by earlier batches and are correct and "
                  "committed; the batch this was raised in rolled back. The state "
                  "file holds the resume point." % done)
        else:
            print("Nothing was written to the live store.")
        return 1
    finally:
        for c in (live, copy):
            if c is not None:
                try:
                    c.close()
                except sqlite3.Error:
                    pass


def main(argv=None):
    ap = argparse.ArgumentParser(
        prog="writeback_vectors.py",
        description="Carry recomputed vectors from a migrated copy back into a live "
                    "Chronicle store (W1-W8).")
    ap.add_argument("live_db", help="the LIVE chronicle.db (written in place)")
    ap.add_argument("copy_db", help="the migrated COPY (read-only)")
    ap.add_argument("--build-manifest", default=None, metavar="PATH",
                    help="record the copy's PRE-MIGRATION state to PATH and exit. "
                         "Run this on the pristine copy, before migrating it.")
    ap.add_argument("--manifest", default=None, metavar="PATH",
                    help="the snapshot manifest built by --build-manifest")
    ap.add_argument("--state", default=None, metavar="PATH",
                    help="resume cursor (default: <manifest>.state.json)")
    ap.add_argument("--dry-run", action="store_true",
                    help="open the live db READ-ONLY and write nothing")
    ap.add_argument("--batch", type=int, default=_DEFAULT_BATCH,
                    help="rows per transaction (default %d, hard cap %d)"
                         % (_DEFAULT_BATCH, _MAX_BATCH))
    ap.add_argument("--tables", nargs="+", default=None, choices=list(_TABLES),
                    help="restrict to these vector tables")
    ap.add_argument("--limit", type=int, default=None,
                    help="stop after N candidate rows (a bounded trial run)")
    ap.add_argument("--expect-tag", default=None,
                    help="the live gateway's active model tag (skips the probe)")
    ap.add_argument("--expect-width", type=int, default=None,
                    help="the live gateway's active blob width in bytes")
    args = ap.parse_args(argv)

    if args.build_manifest:
        try:
            build_manifest(args.copy_db, args.build_manifest, tables=args.tables,
                           live_db=args.live_db)
        except Refused as e:
            print("REFUSED: %s" % e)
            return 1
        return 0
    return writeback(args.live_db, args.copy_db, manifest_path=args.manifest,
                     dry_run=args.dry_run, batch=args.batch, tables=args.tables,
                     limit=args.limit, state_path=args.state,
                     expect_tag=args.expect_tag, expect_width=args.expect_width)


if __name__ == "__main__":
    sys.exit(main())
