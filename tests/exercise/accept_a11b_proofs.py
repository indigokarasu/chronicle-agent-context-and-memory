"""A11b acceptance proofs, printed as raw numbers rather than asserted.

Run: /usr/bin/python3 tests/exercise/accept_a11b_proofs.py

Two claims that are easier to believe as a before/after than as a green test:

  1. ZERO-SOCKET CONSTRUCTION. The same `ChronicleCore(...)` construction is
     performed under a socket sentinel that counts every socket creation,
     connect and name resolution — once with the default (network) probe, once
     with an injected probe — under two different fake listener worlds.
  2. WAL SIDECAR RELEASE. Directory listing beside the database file before
     `close()`, after `close()`, and after a reopen + close.

Nothing here touches a real network: the sentinel denies the socket layer.
"""

import os
import shutil
import socket
import sys
import tempfile
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from engine import embeddings as E          # noqa: E402
from engine.core import ChronicleCore       # noqa: E402
from engine.store import MemoryStore        # noqa: E402

AUTO_CFG = {"embeddings": {"model": "auto"}}
OLLAMA_WORLD = {"http://localhost:11434/v1": {"models": ["nomic-embed-text"], "dimensions": 768}}
LMSTUDIO_WORLD = {"http://localhost:1234/v1": {"models": ["text-embedding-qwen3"],
                                               "dimensions": 1024}}


class Sentinel:
    """Counts (and denies) every socket operation attempted inside it."""

    def __init__(self):
        self.ops = []
        self._patches = []

    def _deny(self, label):
        def _boom(*a, **kw):
            self.ops.append(label)
            raise OSError("denied by the A11b sentinel: %s" % label)
        return _boom

    def __enter__(self):
        me = self

        class _Socket(socket.socket):
            def __init__(self, family=socket.AF_INET, *a, **kw):
                if family in (socket.AF_INET, socket.AF_INET6):
                    me.ops.append("socket()")
                    raise OSError("denied by the A11b sentinel: socket()")
                super().__init__(family, *a, **kw)

        for target, name, repl in ((socket, "socket", _Socket),
                                   (socket, "create_connection", self._deny("create_connection")),
                                   (socket, "getaddrinfo", self._deny("getaddrinfo")),
                                   (E, "_getaddrinfo", self._deny("engine._getaddrinfo"))):
            p = mock.patch.object(target, name, repl)
            p.start()
            self._patches.append(p)
        return self

    def __exit__(self, *exc):
        for p in reversed(self._patches):
            p.stop()
        return False


def identity(emb):
    return "%s model_tag=%s dims=%s url=%s" % (type(emb).__name__, emb.model_tag(),
                                               emb.dimensions, getattr(emb, "base_url", None))


def build(probe, world):
    E._HOST_KIND_CACHE.clear()
    E._REMOTE_REFUSED_WARNED.clear()
    E.set_default_probe(E.StaticProbe(world) if world else None)
    home = tempfile.mkdtemp(prefix="a11b-proof-")
    sentinel = Sentinel()
    try:
        with sentinel:
            core = ChronicleCore(home, AUTO_CFG, embedder_probe=probe)
        out = (len(sentinel.ops), sorted(set(sentinel.ops)), identity(core.embedder))
        core.close()
        return out
    finally:
        shutil.rmtree(home, ignore_errors=True)
        E.set_default_probe(None)


def proof_zero_socket():
    print("=" * 78)
    print("PROOF 1 — socket operations during ChronicleCore(embeddings.model=auto)")
    print("=" * 78)

    print("\n(a) DEFAULT probe, real NetworkProbe — what a plain construction does today")
    n, kinds, ident = build(None, None)
    print("  %-24s socket_ops=%-3d %-40s %s"
          % ("real machine", n, ",".join(kinds) or "(none)", ident))

    print("\n(b) DEFAULT probe, two simulated listener worlds — the reproducibility defect")
    seen = []
    for wname, world in (("world=ollama-on-11434", OLLAMA_WORLD),
                         ("world=lmstudio-on-1234", LMSTUDIO_WORLD)):
        n, kinds, ident = build(None, world)
        seen.append(ident)
        print("  %-24s socket_ops=%-3d %-40s %s"
              % (wname, n, ",".join(kinds) or "(none)", ident))
    print("  deterministic across worlds: %s   <- the defect" % (seen[0] == seen[1]))

    print("\n(c) INJECTED probe (NullProbe), same two worlds — the fix")
    injected = E.NullProbe()
    seen = []
    for wname, world in (("world=ollama-on-11434", OLLAMA_WORLD),
                         ("world=lmstudio-on-1234", LMSTUDIO_WORLD)):
        n, kinds, ident = build(injected, world)
        seen.append(ident)
        print("  %-24s socket_ops=%-3d %-40s %s"
              % (wname, n, ",".join(kinds) or "(none)", ident))
    print("  deterministic across worlds: %s" % (seen[0] == seen[1]))


def proof_sidecars():
    print()
    print("=" * 78)
    print("PROOF 2 — WAL sidecars beside the database")
    print("=" * 78)
    d = tempfile.mkdtemp(prefix="a11b-wal-")
    try:
        path = os.path.join(d, "chronicle.db")
        store = MemoryStore(path)
        store.upsert_predicate("works_at", "employment", "single")
        print("  after open + write : %s" % sorted(os.listdir(d)))
        report = store.close()
        print("  after close()      : %s" % sorted(os.listdir(d)))
        print("  close report       : %s" % report)
        try:
            store.count_rows("events")
            print("  use-after-close    : NO ERROR (defect)")
        except Exception as e:
            print("  use-after-close    : %s: %s" % (type(e).__name__, str(e).split(";")[0]))
        print("  double close()     : %s" % store.close())
        again = MemoryStore(path)
        print("  reopened, rows kept: works_at=%r" % (again.get_predicate("works_at") is not None,))
        again.close()
        print("  after 2nd close    : %s" % sorted(os.listdir(d)))
    finally:
        shutil.rmtree(d, ignore_errors=True)


if __name__ == "__main__":
    os.environ.pop("CHRONICLE_EMBED_BASE_URL", None)
    os.environ.pop("CHRONICLE_EMBED_MODEL", None)
    proof_zero_socket()
    proof_sidecars()
