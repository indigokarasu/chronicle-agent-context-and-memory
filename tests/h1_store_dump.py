"""
H1 inertness probe — a deterministic, tree-agnostic dump of a Chronicle store.

Run this with cwd (and argv[1]) pointing at ANY Chronicle tree — the pre-H1 base
or the H1 tree — and it drives one identical end-to-end capture → process →
sync_turn flow at DEFAULT config, then prints a canonical dump of every row in
the store. Two trees that behave identically print byte-identical dumps.

That is the whole disabled-by-default regression argument (§H1): H1's claim is
not "the new code is off", it is "with defaults, the resulting DATABASE is what
it was before H1 existed". Only a diff against the actual pre-H1 tree can show
that, so this file is deliberately importable by both and depends on nothing H1
added — it calls `pre_llm_call` only through hasattr, because the base tree has
no such method.

Determinism: the CAPTURE clock is frozen (every engine module's
`now_iso`/`_iso_in` is replaced), the embedder is pinned to `hashing`, and rows
are sorted within each table, so the only thing that can move the output is a
behavior change.

The `uuid.uuid4` pin that used to sit beside the clock is GONE (Ladder 10 A4).
It was not a determinism aid, it was a blindfold: the four projection side
tables minted uuid4 row ids inside the reducer, so a full-log replay produced
a different projection every time, and pinning uuid4 here is precisely what
stopped this dump from showing it. Those ids — and `extractions.id`, the last
random id a default flow wrote — are now derived from content, so the flow has
no uuid4 in it and there is nothing left to pin.

The clock pin stays, and is a different kind of thing. It freezes the clock
that CAPTURE reads: `occurred_at`/`recorded_at` become part of the event log,
they feed `event_id` and therefore `belief_id`, and two trees probed minutes
apart would otherwise differ in every row for a reason that has nothing to do
with either tree. That is legitimate input control. It does mean this dump
cannot prove the reducer stopped inventing timestamps — with the clock frozen,
an invented `now_iso()` and the event's own `recorded_at` are the same string.
That property is proved instead, with nothing pinned at all, by
tests/test_replay_determinism.py.

Three legitimate differences are excluded rather than papered over, and each is
asserted separately by tests/test_host_model.py (or, for the third,
tests/test_a9_sweeps.py):
  * the host-model tables, which H1/H2 add and which must be EMPTY here;
  * meta.schema_version, which H1/H2 bump to carry those tables;
  * meta `sweep:*`, ladder-10 A9's sweep cursors and last-run reports.

The third needs its reason stated, because "a new row appeared" is normally
exactly what this probe exists to catch. These rows are not memory: they are the
maintenance bookkeeping that makes a sweep resumable and its partiality visible,
and their content is a fixed telemetry schema (cursor, processed, remaining,
bounded, budget, wrapped, total, at) that references no belief, event, session or
entity. They cannot carry content forward and they cannot change what a query
returns. tests/test_a9_sweeps.py::TestH1DumpExclusionIsNarrow asserts BOTH halves
directly — that the H1 fixture flow really does write such a row (so the
exclusion is exercised, not decorative) and that every excluded row is pure
telemetry with no identifier in it.

§H2 extends the exclusion list the same way H1 established: only with tables
that are EMPTY at defaults, and only alongside a test that asserts that
emptiness directly (tests/test_h2_host_drains.py::TestH2DisabledPathIsInert).
The exclusion is never allowed to cover a table with rows in it — which is why
H2's doc2query provenance mark lives in its own table instead of widening the
already-populated query_proxy_vectors.

§A0e needs the one thing that rule forbade — a COLUMN exclusion — and it is
worth being exact about why the carve-out below is NARROWER rather than a
loosening. A0e gives `session_index` a `model` column so a session vector's
geometry is recorded at all; it was the one embedding-bearing table with no
model, which is how 93% of the live store's session vectors ended up in an
abandoned model's geometry with nothing in the system that would ever find
them. `session_index` HAS a row after this flow (on_session_end → the
session_summarize job), so H2's answer — put it in a new table — does not help:
the new table would carry that row and could not be excluded either. Every way
of recording the model changes this dump.

So the COLUMN is excluded, under a rule with teeth:

  * only a column whose value is the ACTIVE embedder's canonical model tag, and
  * only alongside a test that asserts that value directly, derived from
    DELIBERATE_MODEL_COLUMNS below (tests/test_host_model.py
    ::test_deliberate_model_columns_carry_the_active_tag).

That is strictly MORE than byte-identity gives here: byte-identity could only
say the cell equals the base tree's cell, and the base tree has no such cell.
The companion test says the cell equals the canonical tag of the embedder that
actually ran. Every other cell of session_index — id, summary, embedding DIGEST,
owner, occurred_at — is still compared byte for byte, so a behavior change that
moved a summary or a vector still fails here.

Ladder-10 A3 adds a table (`maintenance_runs`, the maintenance scheduler's
watermarks) and deliberately does NOT extend the list with it. It would
qualify — it is empty at defaults, and that emptiness is asserted directly by
tests/test_maintenance_scheduler.py::TestInertAtDefaults — but excluding it
would trade an alarm for a promise. The base tree has no such table, so a
watermark written on the default path shows up here as a line the base dump
cannot have, and test_store_dump_is_byte_identical_to_the_base_tree fails on
the spot. An empty table costs the dump nothing (it renders no lines), so
leaving it inside the comparison is free. A test asserts it stays out of
H1_TABLES, so a future failure cannot be "fixed" by hiding the table.

Usage:  python3 tests/h1_store_dump.py <tree_dir>
"""

import hashlib
import json
import os
import shutil
import sys
import tempfile

FROZEN_NOW = "2026-01-02T03:04:05.00Z"
FROZEN_LATER = "2026-01-02T03:14:05.00Z"

# The host-model tables. Excluded from the dump because the base tree has no such
# tables to compare against; test_host_model.py (H1) and test_h2_host_drains.py
# (H2) assert they exist and are empty at defaults.
H1_TABLES = ("host_model_requests", "host_model_results",
             "host_model_proxies", "rerank_hints")

# (table, column) pairs excluded from the dump because they are DELIBERATE
# schema additions the base tree cannot have, and because their value is the
# active embedder's canonical model tag rather than anything the flow could
# vary. Read the module docstring before adding to this: a pair only earns its
# place if a test asserts the value directly, and test_host_model.py derives
# that assertion FROM this tuple so an unasserted addition cannot pass silently.
DELIBERATE_MODEL_COLUMNS = (("session_index", "model"),)
# Ladder-10 A9 sweep bookkeeping in `meta`. Kept as a literal rather than
# imported from engine.store, because this probe must run unchanged inside the
# pre-A9 base tree, where that constant does not exist.
SWEEP_META_PREFIX = "sweep:"

# The fixture turn set. Obviously fake people and companies, per the spec's
# fixture rule, and shaped to exercise the heuristic extractor's real branches:
# a first-person name + employer, an office location, and a directive.
TURNS = (
    ("My name is Pat Testley and I work at Acme Fake Co.", "Noted, Pat."),
    ("My office is in Fake City.", "Got it — Fake City."),
    ("Always use metric units when you answer me.", "Understood, metric from now on."),
)


def _freeze_clock():
    """Pin the CAPTURE clock — the one remaining source of run-to-run variance.

    now_iso/_iso_in are imported by VALUE (`from .store import now_iso`), so
    patching engine.store alone would leave capture.py and reducer.py on the
    real clock — and since occurred_at feeds event_id, which feeds belief_id,
    that alone would move nearly every row.

    uuid4 is deliberately NOT pinned any more; see this module's docstring.
    A default flow that still needs a uuid4 pin to produce a stable dump has a
    random id somewhere in its projection, which is the defect, not the test
    setup.
    """
    for module in list(sys.modules.values()):
        name = getattr(module, "__name__", "") or ""
        if not (name == "provider" or name == "context" or name.startswith("engine")):
            continue
        if hasattr(module, "now_iso"):
            setattr(module, "now_iso", lambda: FROZEN_NOW)
        if hasattr(module, "_iso_in"):
            setattr(module, "_iso_in", lambda *a, **kw: FROZEN_LATER)


def _norm(value):
    """Canonical, JSON-safe form of one column value. Blobs (embeddings) become
    a digest — their exact bytes are compared, without dumping them."""
    if isinstance(value, (bytes, bytearray)):
        return "blob:sha256:" + hashlib.sha256(bytes(value)).hexdigest()
    return value


def dump_store(store) -> str:
    conn = store._conn()
    tables = [r[0] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name").fetchall()]
    lines = []
    for table in tables:
        if table in H1_TABLES:
            continue
        columns = [r[1] for r in conn.execute("PRAGMA table_info(%s)" % table).fetchall()]
        if not columns:
            continue  # a virtual table's own name has no columns to read directly
        # Deliberate model-identity columns are dropped by NAME, so the
        # surviving cells keep the base tree's own order whether this tree put
        # the new column first, last or in the middle.
        skip = {i for i, c in enumerate(columns) if (table, c) in DELIBERATE_MODEL_COLUMNS}
        rendered = []
        for row in conn.execute("SELECT * FROM %s" % table).fetchall():
            cells = [_norm(row[i]) for i in range(len(columns)) if i not in skip]
            if table == "meta" and cells and cells[0] == "schema_version":
                continue  # 5 -> 6: a deliberate difference, asserted elsewhere
            if table == "meta" and cells and str(cells[0]).startswith(SWEEP_META_PREFIX):
                continue  # A9 sweep cursor/report: telemetry, asserted elsewhere
            rendered.append(json.dumps(cells, default=str, sort_keys=True))
        for line in sorted(rendered):
            lines.append(table + "\t" + line)
    return "\n".join(lines)


def run_flow(home: str) -> str:
    """One end-to-end flow at DEFAULT config, then the canonical dump."""
    # Import the engine BEFORE freezing: provider.py loads engine.core lazily
    # inside initialize(), so at import time sys.modules holds no engine module
    # for _freeze_clock to find, and the run would silently keep the real clock
    # (which moves every event_id, and with it every belief_id).
    import engine.core  # noqa: F401
    from provider import ChronicleMemoryProvider

    _freeze_clock()
    prov = ChronicleMemoryProvider()
    # embeddings.model is the ONLY override: a networked embedder would make the
    # run non-deterministic (and this must work offline). Everything else — and
    # host_model.piggyback in particular — is left at DEFAULTS.
    prov.initialize("s-h1-probe", hermes_home=home, principal_id="assistant",
                    config={"embeddings": {"model": "hashing"}})
    for user, assistant in TURNS:
        # The H1 attach hook, on the default path. The base tree has no such
        # method; the H1 tree has one that must return "" without touching the
        # store. Either way the flow is identical.
        if hasattr(prov, "pre_llm_call"):
            attached = prov.pre_llm_call()
            if attached != "":
                raise AssertionError("pre_llm_call attached %r at default config" % (attached,))
        prov.sync_turn(user, assistant, session_id="s-h1-probe")
        prov.core.process_pending()
    prov.on_session_end([])
    prov.core.process_pending()
    return dump_store(prov.core.store)


def main() -> int:
    tree = os.path.abspath(sys.argv[1] if len(sys.argv) > 1 else os.getcwd())
    sys.path.insert(0, tree)
    os.environ["CHRONICLE_EMBED_MODEL"] = "hashing"
    home = tempfile.mkdtemp(prefix="h1probe-")
    try:
        sys.stdout.write(run_flow(home))
    finally:
        shutil.rmtree(home, ignore_errors=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
