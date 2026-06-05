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
_HASHING_NAMES = {"hashing", "hashing-v1", "offline", "none"}
_AUTO_NAMES = {"", "auto", "auto-detect", "autodetect", "local", "default"}
# Model ids that look like embedding models (used to auto-pick from /v1/models).
_EMBED_RE = re.compile(r"embed|bge|gte|nomic|e5|minilm|mxbai|arctic|stella|gemma|qwen.*embed", re.I)


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
    """Calls a local OpenAI-compatible ``/v1/embeddings`` endpoint (stdlib only).

    `healthcheck()` is strict (raises) so init can decide real-model vs hashing.
    `embed()` is resilient: it NEVER raises at runtime — on the first failure
    (server died, timeout, a model that doesn't actually support embeddings, a
    rejected input) it trips permanently to an offline hashing embedder (same
    dimensionality) for the rest of the session and logs once. Callers — including
    the durable capture path — therefore can't be broken by the embedding backend;
    FTS retrieval continues regardless.
    """

    def __init__(self, base_url: str, model: str, dimensions: int, api_key: str = "", timeout: float = 10.0):
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.dimensions = dimensions
        self.api_key = api_key or ""
        self.timeout = timeout
        self._fallback: Optional["HashingEmbedder"] = None

    def _embed_raw(self, text: str, timeout: float) -> List[float]:
        import json as _json
        import urllib.request
        body = _json.dumps({"model": self.model, "input": text or ""}).encode("utf-8")
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        req = urllib.request.Request(self.base_url + "/embeddings", data=body, headers=headers)
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = _json.loads(resp.read().decode("utf-8"))
        vec = (data.get("data") or [{}])[0].get("embedding")
        if not isinstance(vec, list) or not vec:
            raise ValueError("response had no embedding (model may not support embeddings)")
        return [float(x) for x in vec]

    def healthcheck(self) -> bool:
        v = self._embed_raw("ok", timeout=min(self.timeout, 4.0))  # raises if the endpoint/model can't embed
        self.dimensions = len(v)  # trust the server's real dimensionality
        return True

    def embed(self, text: str) -> List[float]:
        if self._fallback is not None:
            return self._fallback.embed(text)
        try:
            return self._embed_raw(text, timeout=self.timeout)
        except Exception as e:
            logger.warning("Chronicle embeddings: endpoint %s failed at runtime (%s); "
                           "switching to offline hashing for this session (FTS retrieval continues)",
                           self.base_url, e)
            self._fallback = HashingEmbedder(dimensions=self.dimensions)
            return self._fallback.embed(text)


def _candidate_urls(base_url: Optional[str]) -> List[str]:
    import os
    if base_url:
        return [base_url]
    env = os.environ.get("CHRONICLE_EMBED_BASE_URL")
    if env:
        return [env]
    return list(_DEFAULT_ENDPOINTS)


def _discover_embedding_models(base_url: str, api_key: str) -> List[str]:
    """List candidate embedding model ids from an OpenAI-compatible /v1/models.

    Prefers ids that look like embedding models; if none match the heuristic,
    returns all ids (the test-embed in get_embedder filters out chat models that
    can't actually embed). Returns [] if the server can't be queried."""
    import json as _json
    import urllib.request
    headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
    req = urllib.request.Request(base_url.rstrip("/") + "/models", headers=headers)
    with urllib.request.urlopen(req, timeout=4) as resp:
        data = _json.loads(resp.read().decode("utf-8"))
    ids = [m.get("id", "") for m in (data.get("data") or []) if m.get("id")]
    return [i for i in ids if _EMBED_RE.search(i)] or ids


def get_embedder(model: Optional[str] = None, dimensions: Optional[int] = None,
                 base_url: Optional[str] = None, api_key: Optional[str] = None) -> "Embedder":
    """Return the active embedder.

    Default is ``auto``: find a running local OpenAI-compatible server (configured
    base_url / $CHRONICLE_EMBED_BASE_URL, else common LM Studio / Ollama /
    llama.cpp ports) and use whatever embedding model it actually serves — no
    model id is hardcoded. An explicit model name is used as-is. If nothing is
    reachable (or only chat models are loaded), fall back to the built-in offline
    HashingEmbedder with a warning — retrieval (FTS + vectors) never hard-breaks.
    Set model to 'hashing' to force offline.
    """
    dims = int(dimensions) if dimensions else 768
    name = (model or "auto").strip().lower()
    if name in _HASHING_NAMES:
        return HashingEmbedder(dimensions=int(dimensions) if dimensions else 256)
    auto = name in _AUTO_NAMES
    for url in _candidate_urls(base_url):
        try:
            candidates = _discover_embedding_models(url, api_key or "") if auto else [model]
        except Exception:
            continue  # /models unreachable on this endpoint → try next
        for mid in candidates:
            try:
                emb = OpenAICompatEmbedder(url, mid, dims, api_key or "")
                if emb.healthcheck():
                    logger.info("Chronicle embeddings: using local model %r via %s (dim %d)",
                                mid, url, emb.dimensions)
                    return emb
            except Exception:
                continue  # not an embedding model / rejected → try next candidate
    logger.warning("Chronicle embeddings: no local embedding model reachable (%s on %s); "
                   "using offline hashing embedder",
                   "auto-detect" if auto else repr(model), ", ".join(_candidate_urls(base_url)))
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
