#!/usr/bin/env python3
"""
Acceptance — t2: no silent hash fallback, deferred embed jobs (§24.4, §17.3).

  (1) model 'auto', no backend → DEGRADED: 0 vectors, embed jobs pending, no raise.
  (2) $CHRONICLE_EMBED_MODEL=hashing → today's offline behaviour, vectors written.
  (3) the LME recall harness under that env → turn union@1 within 3 pts of 65.0%.
  (4) a store created on the OLD schema still opens, captures and drains — the
      migration is the whole point: CREATE TABLE IF NOT EXISTS would leave it
      with a curation_jobs that rejects task='embed' inside the capture txn (I12)
      and has no run_after for the claim query.
  (5) the queued embeds actually drain against a server that appears later —
      "retried" has to mean written, not just re-tried.

Run:  python3 tests/exercise/accept_t2.py
"""

import json
import os
import re
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))

from engine.core import ChronicleCore
from engine.embeddings import DegradedEmbedder, HashingEmbedder
from engine.store import SCHEMA_VERSION, now_iso

DEAD_ENDPOINT = "http://127.0.0.1:9"        # discard port: refuses instantly, never serves
HARNESS = os.environ.get("CHRONICLE_LME_HARNESS", "/private/tmp/claude-501/"
                         "-Users-evaluser-temp/3d6d860f-71ee-406d-9aef-b68dfd0642d1/"
                         "scratchpad/lme_recall.py")
ORACLE = os.environ.get("CHRONICLE_LME_ORACLE", "/private/tmp/claude-501/"
                        "-Users-evaluser-temp/3d6d860f-71ee-406d-9aef-b68dfd0642d1/"
                        "scratchpad/oracle.json")
BASELINE_UNION_AT_1 = 65.0
TOLERANCE = 3.0

# curation_jobs exactly as it shipped BEFORE this task: no run_after, no 'embed'.
_LEGACY_JOBS = """CREATE TABLE curation_jobs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    task TEXT CHECK(task IN ('extract','route','criticality','canonicalize','consolidate',
        'contradiction','identity','derive','verify','decay','consistency','health','reextract',
        'journal_ingest','session_summarize')),
    payload TEXT, depends_on INTEGER REFERENCES curation_jobs(id),
    status TEXT CHECK(status IN ('pending','running','done','failed')) DEFAULT 'pending',
    attempts INTEGER DEFAULT 0, created_at TEXT, started_at TEXT, finished_at TEXT, error TEXT);"""


def _ingest(core, n=5):
    for i in range(n):
        core.capture.append("observed",
                            {"source_type": "session_transcript",
                             "excerpt": f"User: turn {i}, my dentist is Dr Alvarez in Boulder.\n"
                                        f"Assistant: noted, appointment number {i}."},
                            actor="user", session_id="s1", trust_level=2)


def _fail(check, msg):
    print(f"FAIL: {check} — {msg}")
    return False


def check1_degraded():
    """auto + no backend: nothing vectored, everything queued, nothing raised."""
    home = tempfile.mkdtemp(prefix="t2_auto_")
    env = os.environ.pop("CHRONICLE_EMBED_MODEL", None)   # (1) is about config 'auto'
    try:
        core = ChronicleCore(home, {"embeddings": {"model": "auto", "base_url": DEAD_ENDPOINT}})
        if not isinstance(core.embedder, DegradedEmbedder):
            return _fail("check1", f"expected DegradedEmbedder, got {type(core.embedder).__name__}")
        _ingest(core)
        core.process_pending()

        vectors = core.store.vector_count()
        pending = core.store.get_curation_jobs("task='embed' AND status='pending'")
        deferred = [j for j in pending if (j["run_after"] or "") > now_iso()]
        print(f"  vectors={vectors}  pending embed jobs={len(pending)}  deferred={len(deferred)}")
        if vectors != 0:
            return _fail("check1", f"degraded mode wrote {vectors} vectors")
        if not pending:
            return _fail("check1", "no embed jobs were queued for retry")
        if not deferred:
            return _fail("check1", "queued embed jobs were not deferred (run_after unset/past)")
        status = core.embedding_status()
        if status["mode"] != "degraded":
            return _fail("check1", f"embedding_status says {status['mode']!r}")
        print("PASS: check1 — auto + no server = DEGRADED "
              "(0 vectors, %d embed jobs deferred, no exception)" % len(pending))
        return True
    finally:
        if env is not None:
            os.environ["CHRONICLE_EMBED_MODEL"] = env
        shutil.rmtree(home, ignore_errors=True)


def check2_hashing_env():
    """$CHRONICLE_EMBED_MODEL=hashing forces the unchanged offline path."""
    home = tempfile.mkdtemp(prefix="t2_hash_")
    env = os.environ.get("CHRONICLE_EMBED_MODEL")
    os.environ["CHRONICLE_EMBED_MODEL"] = "hashing"
    try:
        core = ChronicleCore(home, {"embeddings": {"model": "auto", "base_url": DEAD_ENDPOINT}})
        if not isinstance(core.embedder, HashingEmbedder):
            return _fail("check2", f"env override ignored: got {type(core.embedder).__name__}")
        _ingest(core)
        core.process_pending()
        vectors = core.store.vector_count()
        queued = core.store.count_rows("curation_jobs", "task='embed'")
        print(f"  vectors={vectors}  embed jobs={queued}")
        if vectors <= 0:
            return _fail("check2", "hashing mode wrote no vectors")
        if queued:
            return _fail("check2", f"hashing mode queued {queued} embed jobs (should embed inline)")
        print(f"PASS: check2 — CHRONICLE_EMBED_MODEL=hashing writes vectors inline ({vectors})")
        return True
    finally:
        if env is None:
            os.environ.pop("CHRONICLE_EMBED_MODEL", None)
        else:
            os.environ["CHRONICLE_EMBED_MODEL"] = env
        shutil.rmtree(home, ignore_errors=True)


def _union_at_1(out):
    """First % on the `union` row of the TURN-LEVEL table."""
    block = out.split("TURN-LEVEL RECALL@k", 1)[-1].split("UNION SESSION RECALL", 1)[0]
    for line in block.splitlines():
        if line.strip().startswith("union"):
            return float(re.findall(r"([\d.]+)%", line)[0])
    return None


def check3_harness():
    """Recall must be unchanged from baseline when the eval pins hashing."""
    if not (Path(HARNESS).exists() and Path(ORACLE).exists()):
        print(f"SKIP: check3 — harness/oracle not found ({HARNESS}, {ORACLE})")
        return True
    env = dict(os.environ, CHRONICLE_DIR=str(ROOT), CHRONICLE_EMBED_MODEL="hashing")
    p = subprocess.run([sys.executable, HARNESS, ORACLE], env=env,
                       capture_output=True, timeout=1800)
    out = p.stdout.decode("utf-8", "replace")
    if p.returncode != 0:
        print(out[-2000:])
        return _fail("check3", f"harness exited {p.returncode}")
    for line in out.splitlines():
        if line.strip().startswith(("tier", "belief", "raw", "union")) or "RECALL@k" in line \
                or "correctly abstained" in line or "instances in" in line:
            print("  " + line.strip())
    got = _union_at_1(out)
    if got is None:
        return _fail("check3", "could not parse the TURN-LEVEL union row")
    delta = abs(got - BASELINE_UNION_AT_1)
    if delta > TOLERANCE:
        return _fail("check3", f"turn union@1 {got:.1f}% vs baseline {BASELINE_UNION_AT_1}% "
                               f"(delta {delta:.1f} > {TOLERANCE})")
    print(f"PASS: check3 — turn union@1 {got:.1f}% (baseline {BASELINE_UNION_AT_1}%, "
          f"delta {delta:.1f} ≤ {TOLERANCE})")
    return True


def _legacy_home(prefix):
    """A store on the pre-t2 schema: real hash vectors, OLD curation_jobs, a job row.

    Seeded with the hashing embedder because that IS the population this task
    exists for — the dbs that silently accumulated hash vectors are the old ones.
    Returns (home, db_path)."""
    home = tempfile.mkdtemp(prefix=prefix)
    core = ChronicleCore(home, {"embeddings": {"model": "hashing"}})
    db = Path(core.store.db_path)
    core.capture.append("observed", {"source_type": "session_transcript",
                                     "excerpt": "User: seed row, I live in Boulder.\n"
                                                "Assistant: ok."}, actor="user")
    core.process_pending()
    assert core.store.vector_count() > 0, "fixture should hold hash vectors"
    conn = sqlite3.connect(str(db))
    conn.executescript("DROP TABLE curation_jobs;\n" + _LEGACY_JOBS +
                       "\nINSERT INTO curation_jobs(task,payload,status,created_at) "
                       "VALUES('health','{}','done','x');")
    conn.commit()
    conn.close()
    return home, db


def check4_migration():
    """An old db must migrate on open: capture, drain and requeue all work."""
    home, db = _legacy_home("t2_legacy_")
    hashed_home, hashed = _legacy_home("t2_hashed_")
    env = os.environ.pop("CHRONICLE_EMBED_MODEL", None)
    try:
        legacy = sqlite3.connect(str(db))
        sql = legacy.execute("SELECT sql FROM sqlite_master WHERE name='curation_jobs'").fetchone()[0]
        legacy.close()
        if "run_after" in sql or "'embed'" in sql:
            return _fail("check4", "fixture is not actually on the legacy schema")

        core = ChronicleCore(home, {"embeddings": {"model": "auto", "base_url": DEAD_ENDPOINT}})
        version = core.store.get_meta("schema_version")
        _ingest(core)                    # would raise IntegrityError without the rebuild
        core.process_pending()           # would raise 'no such column: run_after' without the ALTER
        pending = core.store.get_curation_jobs("task='embed' AND status='pending'")
        kept = core.store.count_rows("curation_jobs", "task='health'")
        print(f"  schema_version={version} (current={SCHEMA_VERSION})  "
              f"pending embed jobs={len(pending)}  legacy rows kept={kept}")
        # Pinned to the CURRENT SCHEMA_VERSION, not the literal "2" this check was
        # written against: _migrate stamps whatever the code is at, so every later
        # schema bump (u2 took it to 3 for the 'digest' task) would fail an opened
        # legacy db here for a reason that has nothing to do with t2's migration.
        if version != str(SCHEMA_VERSION):
            return _fail("check4", f"meta.schema_version is {version!r}, "
                                   f"expected {str(SCHEMA_VERSION)!r}")
        if not pending:
            return _fail("check4", "no embed jobs queued after migration")
        if kept != 1:
            return _fail("check4", "the rebuild lost pre-existing job rows")

        # And the requeue script must run on exactly this kind of db.
        dry = subprocess.run([sys.executable, str(ROOT / "scripts/requeue_hash_vectors.py"),
                              str(hashed), "--dry-run"], stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        run = subprocess.run([sys.executable, str(ROOT / "scripts/requeue_hash_vectors.py"),
                              str(hashed)], stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        again = subprocess.run([sys.executable, str(ROOT / "scripts/requeue_hash_vectors.py"),
                                str(hashed)], stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        for label, p in (("dry-run", dry), ("run", run), ("rerun", again)):
            if p.returncode != 0:
                print(p.stdout.decode())
                return _fail("check4", f"requeue_hash_vectors.py ({label}) exited {p.returncode}")
        conn = sqlite3.connect(str(hashed))
        left = conn.execute("SELECT COUNT(*) FROM observed_vectors").fetchone()[0]
        jobs = conn.execute("SELECT COUNT(*) FROM curation_jobs WHERE task='embed'").fetchone()[0]
        conn.close()
        first = [l for l in run.stdout.decode().splitlines() if "queued" in l]
        print(f"  requeue: {first[0].strip() if first else '?'}  vectors_left={left}  embed_jobs={jobs}")
        if left:
            return _fail("check4", f"{left} hash vectors survived the requeue")
        if jobs < 1:
            return _fail("check4", "requeue enqueued no embed jobs")
        print("PASS: check4 — legacy schema migrates in place; capture, drain and requeue all work")
        return True
    finally:
        if env is not None:
            os.environ["CHRONICLE_EMBED_MODEL"] = env
        shutil.rmtree(home, ignore_errors=True)
        shutil.rmtree(hashed_home, ignore_errors=True)


class _FakeEmbedServer(BaseHTTPRequestHandler):
    """Minimal OpenAI-compatible embeddings endpoint (stdlib only)."""
    DIM = 8

    def log_message(self, *a):
        pass

    def _send(self, obj):
        body = json.dumps(obj).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):                                    # /v1/models
        self._send({"data": [{"id": "fake-embed-model"}]})

    def do_POST(self):                                   # /v1/embeddings
        raw = self.rfile.read(int(self.headers.get("Content-Length", 0)) or 0)
        text = json.loads(raw or b"{}").get("input", "")
        self._send({"data": [{"embedding": [float((sum(map(ord, str(text))) + i) % 7) / 7.0
                                            for i in range(self.DIM)]}]})


def check5_recovery():
    """A deferred job must actually FILL IN once a backend appears — otherwise
    'retried later' is a queue that never drains."""
    home = tempfile.mkdtemp(prefix="t2_recover_")
    env = os.environ.pop("CHRONICLE_EMBED_MODEL", None)
    srv = HTTPServer(("127.0.0.1", 0), _FakeEmbedServer)
    serving = False
    try:
        url = f"http://127.0.0.1:{srv.server_address[1]}/v1"          # nothing serving it yet
        core = ChronicleCore(home, {"embeddings": {"model": "auto", "base_url": url}})
        _ingest(core, 3)
        core.process_pending()
        queued = core.store.count_rows("curation_jobs", "task='embed' AND status='pending'")
        if core.store.vector_count() or not queued:
            return _fail("check5", "expected 0 vectors and a queued backlog before recovery")

        threading.Thread(target=srv.serve_forever, daemon=True).start()
        serving = True
        with core.store.transaction() as conn:                        # the backoff comes due
            conn.execute("UPDATE curation_jobs SET run_after=NULL WHERE task='embed'")
        core.embedder._next_probe = 0.0                               # skip the recheck window
        core.process_pending()

        vectors = core.store.vector_count()
        left = core.store.count_rows("curation_jobs", "task='embed' AND status='pending'")
        row = core.store.iter_observed_vectors()[0]
        print(f"  after recovery: vectors={vectors}  still pending={left}  "
              f"model={row['model']!r}  bytes={len(row['embedding'])}")
        if vectors != queued or left:
            return _fail("check5", f"backlog did not drain ({vectors}/{queued}, {left} left)")
        if row["model"] != "fake-embed-model" or len(row["embedding"]) != _FakeEmbedServer.DIM * 4:
            return _fail("check5", f"vector not written by the real model: {row['model']!r}")
        with core.store.transaction() as conn:                        # replay must not double-write
            conn.execute("UPDATE curation_jobs SET status='pending', run_after=NULL WHERE task='embed'")
        core.process_pending()
        if core.store.vector_count() != vectors:
            return _fail("check5", "replaying the jobs changed the vector count (not idempotent)")
        print(f"PASS: check5 — queued embeds drain against a server that appears later ({vectors})")
        return True
    finally:
        if serving:
            srv.shutdown()          # blocks unless serve_forever actually started
        srv.server_close()
        if env is not None:
            os.environ["CHRONICLE_EMBED_MODEL"] = env
        shutil.rmtree(home, ignore_errors=True)


def main():
    ok = True
    for fn in (check1_degraded, check2_hashing_env, check4_migration, check5_recovery,
               check3_harness):
        ChronicleCore._instances.clear()
        try:
            ok = fn() and ok
        except Exception as e:
            import traceback
            traceback.print_exc()
            ok = _fail(fn.__name__, f"raised {type(e).__name__}: {e}") and ok
    print("\nRESULT: " + ("ALL CHECKS PASS" if ok else "FAILURES ABOVE"))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
