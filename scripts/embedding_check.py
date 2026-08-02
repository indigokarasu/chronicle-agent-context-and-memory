#!/usr/bin/env python3
"""
Chronicle embedding diagnostic — does the currently-selected model actually
support embeddings?

Reads the embedding config (defaults + $HERMES_HOME/config.yaml `memory.embeddings`
if present), shows which local servers/models are visible, resolves the embedder
exactly as Chronicle does at runtime, then runs a STRICT live test embed.

Exit codes:  0 = real local model embeds OK   2 = offline hashing selected explicitly
             3 = a model is selected but failed a live embed   1 = diagnostic error
             4 = DEGRADED: no backend reachable (no vectors written, embeds queued)

Usage:  python3 scripts/embedding_check.py
        (installed:  python3 ~/.hermes/plugins/chronicle/scripts/embedding_check.py)
"""

from __future__ import annotations

import logging
import os
import sys
from pathlib import Path

logging.getLogger("chronicle").setLevel(logging.ERROR)  # this script prints its own result

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from engine.config import Config
from engine.embeddings import (
    get_embedder, OpenAICompatEmbedder, HashingEmbedder, DegradedEmbedder,
    _candidate_urls, _discover_embedding_models,
)


def _load_config() -> Config:
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


def main() -> int:
    cfg = _load_config()
    model = cfg.get("embeddings.model")
    dims = cfg.get("embeddings.dimensions")
    base = cfg.get("embeddings.base_url")
    key = cfg.get("embeddings.api_key")

    print("Chronicle embedding diagnostic")
    print(f"  configured model : {model!r}")
    print(f"  base_url         : {base or '(auto-detect)'}")
    print(f"  dimensions       : {dims}")
    print("  local servers:")
    any_server = False
    for url in _candidate_urls(base):
        try:
            models = _discover_embedding_models(url, key or "")
            any_server = True
            print(f"    {url}: reachable — models={models}")
        except Exception as e:
            print(f"    {url}: unreachable ({type(e).__name__})")
    if not any_server:
        print("    (no local OpenAI-compatible server responded)")

    emb = get_embedder(model, dims, base, key)
    print()

    if isinstance(emb, HashingEmbedder):
        print(f"RESULT: OFFLINE HASHING in use (dim {emb.dimensions}).")
        print("        Selected deliberately via embeddings.model / $CHRONICLE_EMBED_MODEL.")
        print("        FTS retrieval works; vector search is lexical, not semantic.")
        return 2

    if isinstance(emb, DegradedEmbedder):
        print(f"RESULT: DEGRADED — no embedding backend reachable (dim {emb.dimensions}).")
        print("        NO vectors are written; every embed is queued as a curation job")
        print("        and retried with backoff until a server appears. FTS retrieval works.")
        print("        Set embeddings.model / $CHRONICLE_EMBED_MODEL to 'hashing' if you want")
        print("        deterministic offline vectors instead of waiting.")
        return 4

    # A local model was selected (it already passed Chronicle's healthcheck).
    # Re-confirm with a strict live embed (bypasses the resilient fallback).
    try:
        v = emb._embed_raw("chronicle embedding self-test", timeout=getattr(emb, "timeout", 10))
        print(f"RESULT: LOCAL MODEL supports embeddings ✓")
        print(f"        model={emb.model!r}  endpoint={emb.base_url}  dim={len(v)}")
        return 0
    except Exception as e:
        print(f"RESULT: a model is selected ({emb.model!r} @ {emb.base_url}) but it FAILED a live embed:")
        print(f"        {e}")
        print("        Chronicle will degrade to offline hashing at runtime.")
        return 3


if __name__ == "__main__":
    sys.exit(main())
