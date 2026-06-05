"""
Chronicle — Embeddings (§24.4, §27 embeddings:).

A pluggable Embedder interface plus a deterministic, dependency-free default
(feature hashing) so the vector retrieval tier is exercisable offline and in CI
without a model or network. A real deployment swaps in `embeddinggemma-300m`
behind the same interface; nothing else changes.

Vectors serialize to a compact little-endian float32 blob (no numpy needed).
"""

from __future__ import annotations

import logging
import math
import re
import struct
from typing import List, Optional, Protocol

logger = logging.getLogger("chronicle.embeddings")

_TOKEN = re.compile(r"[a-z0-9]+")
_HASHING_NAMES = {"", "hashing", "hashing-v1", "offline", "none"}


class Embedder(Protocol):
    model: str
    dimensions: int

    def embed(self, text: str) -> List[float]: ...


class HashingEmbedder:
    """Deterministic bag-of-tokens feature-hashing embedder.

    Not semantically strong, but stable and offline: the same text always maps
    to the same L2-normalized vector, lexically-overlapping texts land near each
    other, and unrelated texts are near-orthogonal. Good enough to drive RRF
    fusion, the dual-tier path, and property tests.
    """

    def __init__(self, dimensions: int = 256, model: str = "hashing-v1"):
        self.dimensions = dimensions
        self.model = model

    def embed(self, text: str) -> List[float]:
        vec = [0.0] * self.dimensions
        toks = _TOKEN.findall((text or "").lower())
        for tok in toks:
            # Two independent hashes: bucket index + sign (mitigates collisions).
            h = _stable_hash(tok)
            idx = h % self.dimensions
            sign = 1.0 if (h >> 32) & 1 else -1.0
            vec[idx] += sign
            # A light bigram signal sharpens near-duplicate detection.
        norm = math.sqrt(sum(v * v for v in vec))
        if norm > 0:
            vec = [v / norm for v in vec]
        return vec


# Local embedding servers probed when no explicit base_url is configured.
# OpenAI-compatible /v1/embeddings (LM Studio, Ollama ≥0.1.39, llama.cpp, …).
_DEFAULT_ENDPOINTS = [
    "http://localhost:1234/v1",    # LM Studio
    "http://localhost:11434/v1",   # Ollama (OpenAI-compatible)
    "http://127.0.0.1:8080/v1",    # llama.cpp server
]


class OpenAICompatEmbedder:
    """Calls a local OpenAI-compatible ``/v1/embeddings`` endpoint (stdlib only)."""

    def __init__(self, base_url: str, model: str, dimensions: int, api_key: str = ""):
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.dimensions = dimensions
        self.api_key = api_key or ""

    def embed(self, text: str) -> List[float]:
        import json as _json
        import urllib.request
        body = _json.dumps({"model": self.model, "input": text or ""}).encode("utf-8")
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        req = urllib.request.Request(self.base_url + "/embeddings", data=body, headers=headers)
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = _json.loads(resp.read().decode("utf-8"))
        vec = data["data"][0]["embedding"]
        if not isinstance(vec, list) or not vec:
            raise ValueError("empty embedding")
        return [float(x) for x in vec]

    def healthcheck(self) -> bool:
        v = self.embed("ok")
        if self.dimensions != len(v):
            self.dimensions = len(v)  # trust the server's real dimensionality
        return True


def _candidate_urls(base_url: Optional[str]) -> List[str]:
    import os
    if base_url:
        return [base_url]
    env = os.environ.get("CHRONICLE_EMBED_BASE_URL")
    if env:
        return [env]
    return list(_DEFAULT_ENDPOINTS)


def get_embedder(model: Optional[str] = None, dimensions: Optional[int] = None,
                 base_url: Optional[str] = None, api_key: Optional[str] = None) -> "Embedder":
    """Return the active embedder.

    Default assumption is a **local model** (e.g. embeddinggemma-300m) served over
    an OpenAI-compatible ``/v1/embeddings`` endpoint. We auto-detect a running
    local server (configured base_url / $CHRONICLE_EMBED_BASE_URL, else common
    LM Studio / Ollama / llama.cpp ports). If none is reachable we fall back to
    the built-in offline HashingEmbedder with a warning — so retrieval (FTS +
    vectors) never hard-breaks and the box still works without a model running.
    """
    dims = int(dimensions) if dimensions else 768
    name = (model or "").strip().lower()
    if name in _HASHING_NAMES:
        return HashingEmbedder(dimensions=int(dimensions) if dimensions else 256)
    for url in _candidate_urls(base_url):
        try:
            emb = OpenAICompatEmbedder(url, model, dims, api_key or "")
            if emb.healthcheck():
                logger.info("Chronicle embeddings: local model %r via %s (dim %d)", model, url, emb.dimensions)
                return emb
        except Exception:
            continue  # connection refused / model not loaded → try next / fall back
    logger.warning("Chronicle embeddings: local model %r unreachable on %s; "
                   "using offline hashing embedder (set embeddings.base_url or start the server)",
                   model, ", ".join(_candidate_urls(base_url)))
    return HashingEmbedder(dimensions=dims)


def _stable_hash(s: str) -> int:
    # FNV-1a 64-bit — deterministic across processes (unlike hash()).
    h = 0xcbf29ce484222325
    for b in s.encode("utf-8"):
        h ^= b
        h = (h * 0x100000001b3) & 0xFFFFFFFFFFFFFFFF
    return h


def pack(vec: List[float]) -> bytes:
    return struct.pack(f"<{len(vec)}f", *vec)


def unpack(blob: Optional[bytes]) -> List[float]:
    if not blob:
        return []
    n = len(blob) // 4
    return list(struct.unpack(f"<{n}f", blob))


def cosine(a: List[float], b: List[float]) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    # Vectors are pre-normalized; dot ≈ cosine. Clamp for safety.
    return max(-1.0, min(1.0, dot))
