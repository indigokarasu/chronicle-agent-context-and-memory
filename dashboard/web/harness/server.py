"""Local harness for the Chronicle dashboard plugin UI.

The real dashboard is OAuth-gated, so this serves the built bundles and the
plugin's own API functions against a Chronicle database on disk, behind a
minimal stand-in for the Hermes plugin SDK (harness/index.html).

Read-only by construction: the Atlas reads with `mode=ro`, and the one write
endpoint (POST /enqueue-extractions) is answered with a refusal here instead of
being called. Standard library only.

    python3 dashboard/web/harness/server.py --db /path/to/chronicle.db [--port 8790]
"""

import argparse
import importlib.util
import json
import os
import sys
import tempfile
import types
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

HERE = Path(__file__).resolve().parent
DASH = HERE.parent.parent            # dashboard/
DIST = DASH / "dist"


def _load(name, path):
    """Load a dashboard module by path with a no-op fastapi stub, as the tests do."""
    if "fastapi" not in sys.modules:
        stub = types.ModuleType("fastapi")

        class _Router:
            def get(self, *a, **k):
                return lambda fn: fn

            def post(self, *a, **k):
                return lambda fn: fn

        stub.APIRouter = _Router
        stub.Query = lambda default=None, **k: default
        sys.modules["fastapi"] = stub
    spec = importlib.util.spec_from_file_location(name, str(path))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", required=True)
    ap.add_argument("--port", type=int, default=8790)
    args = ap.parse_args()
    db = Path(args.db).resolve()

    # plugin_api locates the store under $HERMES_HOME; point one at --db.
    home = Path(tempfile.mkdtemp(prefix="chr-harness-"))
    (home / "commons" / "db" / "chronicle").mkdir(parents=True)
    (home / "commons" / "db" / "chronicle" / "chronicle.db").symlink_to(db)
    os.environ["HERMES_HOME"] = str(home)

    atlas = _load("harness_atlas", DASH / "atlas_api.py")
    api = _load("harness_plugin_api", DASH / "plugin_api.py")

    def q1(qs, key, default, cast=str):
        v = qs.get(key, [default])[0]
        try:
            return cast(v)
        except (TypeError, ValueError):
            return default

    routes = {
        "/status": lambda qs: api.get_status(),
        "/recent": lambda qs: api.get_recent(q1(qs, "limit", 12, int)),
        "/atlas/summary": lambda qs: atlas.summary(db),
        "/atlas/events": lambda qs: atlas.events_chunk(db, q1(qs, "after_seq", 0, int), q1(qs, "limit", 50000, int)),
        "/atlas/event": lambda qs: atlas.event_detail(db, q1(qs, "seq", 0, int)),
        "/atlas/session": lambda qs: atlas.session_detail(db, q1(qs, "id", "")),
        "/atlas/belief": lambda qs: atlas.belief_detail(db, q1(qs, "id", "")),
        "/atlas/contradictions": lambda qs: atlas.contradictions(db, q1(qs, "limit", 100, int), q1(qs, "offset", 0, int)),
        "/atlas/histories": lambda qs: atlas.fact_histories(db, q1(qs, "limit", 100, int)),
        "/atlas/duplicates": lambda qs: atlas.duplicate_notes(db, q1(qs, "limit", 50, int)),
        "/atlas/lanes": lambda qs: {"cron_names": atlas.cron_job_names(home)},
    }
    prefix = "/api/plugins/chronicle"

    class Handler(BaseHTTPRequestHandler):
        def _send(self, code, body, ctype):
            data = body if isinstance(body, bytes) else body.encode("utf-8")
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(data)

        def log_message(self, fmt, *a):
            sys.stderr.write("harness: " + (fmt % a) + "\n")

        def do_GET(self):
            u = urlparse(self.path)
            if u.path in ("/", "/index.html"):
                return self._send(200, (HERE / "index.html").read_bytes(), "text/html; charset=utf-8")
            if u.path.startswith("/dashboard-plugins/chronicle/dist/"):
                f = (DIST / u.path.rsplit("/", 1)[1]).resolve()
                if f.parent == DIST.resolve() and f.suffix == ".js" and f.exists():
                    return self._send(200, f.read_bytes(), "application/javascript")
                return self._send(404, "not found", "text/plain")
            if u.path.startswith(prefix):
                fn = routes.get(u.path[len(prefix):])
                if fn is None:
                    return self._send(404, json.dumps({"detail": "Not Found"}), "application/json")
                try:
                    return self._send(200, json.dumps(fn(parse_qs(u.query))), "application/json")
                except Exception as e:
                    return self._send(500, json.dumps({"detail": str(e)}), "application/json")
            return self._send(404, "not found", "text/plain")

        def do_POST(self):
            return self._send(200, json.dumps({"ok": False, "error": "the harness is read-only"}), "application/json")

    print("Chronicle dashboard harness on http://127.0.0.1:%d  (db: %s)" % (args.port, db), flush=True)
    ThreadingHTTPServer(("127.0.0.1", args.port), Handler).serve_forever()


if __name__ == "__main__":
    main()
