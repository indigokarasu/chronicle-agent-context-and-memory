"""
Chronicle — Embeddings (§24.4, §27 embeddings:).

A pluggable Embedder interface plus a deterministic, dependency-free default
(feature hashing) so the vector retrieval tier is exercisable offline and in CI
without a model or network. A real deployment swaps in `embeddinggemma-300m`
behind the same interface; nothing else changes.

Vectors serialize to a compact little-endian float32 blob (no numpy needed).
"""

from __future__ import annotations

import math
import re
import struct
from typing import List, Optional, Protocol

_TOKEN = re.compile(r"[a-z0-9]+")


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
