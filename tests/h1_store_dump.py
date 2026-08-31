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

Determinism: the clock is frozen (every engine module's `now_iso`/`_iso_in` is
replaced), the embedder is pinned to `hashing`, and rows are sorted within each
table, so the only thing that can move the output is a behavior change.

Two legitimate differences are excluded rather than papered over, and each is
asserted separately by tests/test_host_model.py:
  * the host-model tables, which H1/H2 add and which must be EMPTY here;
  * meta.schema_version, which H1/H2 bump to carry those tables.

§H2 extends the exclusion list the same way H1 established: only with tables
that are EMPTY at defaults, and only alongside a test that asserts that
emptiness directly (tests/test_h2_host_drains.py::TestH2DisabledPathIsInert).
The exclusion is never allowed to cover a table with rows in it, and never a
COLUMN — which is why H2's doc2query provenance mark lives in its own table
instead of widening the already-populated query_proxy_vectors.

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

# The fixture turn set. Obviously fake people and companies, per the spec's
# fixture rule, and shaped to exercise the heuristic extractor's real branches:
# a first-person name + employer, an office location, and a directive.
TURNS = (
    ("My name is Pat Testley and I work at Acme Fake Co.", "Noted, Pat."),
    ("My office is in Fake City.", "Got it — Fake City."),
    ("Always use metric units when you answer me.", "Understood, metric from now on."),
)


def _freeze_clock():
    """Pin the two sources of run-to-run variance: the clock and uuid4.

    now_iso/_iso_in are imported by VALUE (`from .store import now_iso`), so
    patching engine.store alone would leave capture.py and reducer.py on the
    real clock — and since occurred_at feeds event_id, which feeds belief_id,
    that alone would move nearly every row. uuid4 backs surrogate row ids
    (extractions.id, rescue document_id) that are random by design.
    """
    import uuid

    counter = [0]

    def _fake_uuid4():
        counter[0] += 1
        return uuid.UUID(int=counter[0])

    uuid.uuid4 = _fake_uuid4
    for module in list(sys.modules.values()):
        name = getattr(module, "__name__", "") or ""
        if not (name == "provider" or name == "context" or name.startswith("engine")):
            continue
        if hasattr(module, "now_iso"):
            setattr(module, "now_iso", lambda: FROZEN_NOW)
        if hasattr(module, "_iso_in"):
            setattr(module, "_iso_in", lambda *a, **kw: FROZEN_LATER)
        if hasattr(module, "uuid4"):
            setattr(module, "uuid4", _fake_uuid4)


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
        rendered = []
        for row in conn.execute("SELECT * FROM %s" % table).fetchall():
            cells = [_norm(row[i]) for i in range(len(columns))]
            if table == "meta" and cells and cells[0] == "schema_version":
                continue  # 5 -> 6: the ONE deliberate difference, asserted elsewhere
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
