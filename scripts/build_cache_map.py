"""Build the Chronicle map file (see engine/cache_map.py).

    build_cache_map.py --config CONFIG.yaml --db CHRONICLE.db [--home HERMES_HOME] [--print]

Read-only against the store and every source database; the only write is the
map file itself, which is replaced atomically.
"""
import argparse
import os
import sys

import yaml

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from engine import cache_map          # noqa: E402
from engine.config import Config      # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", required=True, help="host config.yaml (reads its `memory` section)")
    ap.add_argument("--db", required=True, help="the chronicle.db the live provider uses")
    ap.add_argument("--home", default=os.environ.get("HERMES_HOME", ""))
    ap.add_argument("--print", action="store_true", help="also print the map")
    a = ap.parse_args()
    with open(a.config) as f:
        mem = (yaml.safe_load(f) or {}).get("memory") or {}
    cfg = Config(mem)
    if not cfg.get("cache_map.enabled", True):
        print("cache_map disabled; nothing written")
        return 0
    text = cache_map.build(a.db, cfg)
    path = cache_map.resolve_path(a.home, cfg)
    cache_map.write(path, text)
    print(f"wrote {path} ({len(text)} chars)")
    if a.print:
        print(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
