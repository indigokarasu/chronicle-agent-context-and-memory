"""Build the Chronicle map file (see engine/cache_map.py).

    build_cache_map.py [--config CONFIG.yaml] [--db CHRONICLE.db] [--home HERMES_HOME] [--print]

Left out, the home is the active Hermes home, the config is its config.yaml and
the store is the one that home's runtime uses (see engine/paths.py).

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
from engine.paths import readable_db_path, resolve_home   # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default=None,
                    help="host config.yaml (reads its `memory` section); default: the home's")
    ap.add_argument("--db", default=None,
                    help="the chronicle.db the live provider uses; default: the home's store")
    ap.add_argument("--home", default="", help="the Hermes home; default: the active one")
    ap.add_argument("--print", action="store_true", help="also print the map")
    a = ap.parse_args()
    home = resolve_home(a.home or None)
    config_path = a.config or os.path.join(home, "config.yaml")
    mem = {}
    # A config that was named must exist. The home's own may be absent (a fresh
    # install has none yet), and the defaults then apply.
    if a.config or os.path.exists(config_path):
        with open(config_path) as f:
            mem = (yaml.safe_load(f) or {}).get("memory") or {}
    cfg = Config(mem)
    if not cfg.get("cache_map.enabled", True):
        print("cache_map disabled; nothing written")
        return 0
    db = a.db or readable_db_path(cfg.get("db_path"), home)
    if not os.path.isfile(db):
        print(f"no database at {db}", file=sys.stderr)
        return 2
    text = cache_map.build(db, cfg)
    path = cache_map.resolve_path(home, cfg)
    cache_map.write(path, text)
    print(f"wrote {path} ({len(text)} chars)")
    if a.print:
        print(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
