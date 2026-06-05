"""
Chronicle — Serialization & content addressing (§5).

Canonical JSON (CJSON) + content hashing for content-addressed events and
beliefs. The hash is the contract (I2): identical canonical content yields an
identical id, so events dedup and the log is tamper-evident.

Hash: the spec mandates BLAKE3-256 (§5.2). We use the `blake3` package when
available and fall back to BLAKE2b-256 otherwise (documented, deterministic).
Either way the property that matters — a deterministic 256-bit content address —
holds; set CHRONICLE_REQUIRE_BLAKE3=1 to make a missing blake3 a hard error for
cross-system interop.
"""

from __future__ import annotations

import hashlib
import os
from typing import Any

try:  # pragma: no cover - depends on environment
    from blake3 import blake3 as _blake3  # type: ignore
    _HASH_NAME = "blake3-256"
except Exception:  # pragma: no cover
    _blake3 = None
    if os.environ.get("CHRONICLE_REQUIRE_BLAKE3") == "1":
        raise
    _HASH_NAME = "blake2b-256"


HASH_NAME = _HASH_NAME


def cjson_dumps(obj: Any) -> str:
    """Serialize to Canonical JSON (CJSON) — §5.1.

    UTF-8, keys sorted by code point, no insignificant whitespace, mandatory
    escapes only, non-ASCII raw. Integers decimal (no leading zeros / '+' / -0).
    Non-integer numbers are FORBIDDEN in hashed content — encode reals as
    fixed-scale decimal strings per field before hashing.
    """
    return _cjson_encode(obj)


def _cjson_encode(obj: Any) -> str:
    if obj is None:
        return "null"
    if isinstance(obj, bool):
        return "true" if obj else "false"
    if isinstance(obj, int):
        if obj == 0:
            return "0"
        return str(obj)  # Python int str has no leading zeros / '+', and "-0" is impossible
    if isinstance(obj, float):
        # §5.1: non-integer numbers forbidden in hashed content.
        raise ValueError(
            "CJSON forbids non-integer numbers in hashed content; "
            "encode reals as fixed-scale decimal strings per field"
        )
    if isinstance(obj, str):
        return _cjson_str(obj)
    if isinstance(obj, (list, tuple)):
        return "[" + ",".join(_cjson_encode(v) for v in obj) + "]"
    if isinstance(obj, dict):
        pairs = []
        for k in sorted(obj.keys()):
            if not isinstance(k, str):
                raise TypeError(f"CJSON object keys must be strings, got {type(k).__name__}")
            pairs.append(f"{_cjson_str(k)}:{_cjson_encode(obj[k])}")
        return "{" + ",".join(pairs) + "}"
    raise TypeError(f"CJSON cannot serialize {type(obj).__name__}")


_ESCAPES = {
    '"': '\\"', "\\": "\\\\", "\b": "\\b", "\f": "\\f",
    "\n": "\\n", "\r": "\\r", "\t": "\\t",
}


def _cjson_str(s: str) -> str:
    parts = ['"']
    for ch in s:
        esc = _ESCAPES.get(ch)
        if esc is not None:
            parts.append(esc)
        elif ord(ch) < 0x20:
            parts.append(f"\\u{ord(ch):04x}")
        else:
            parts.append(ch)
    parts.append('"')
    return "".join(parts)


def content_hash(data: bytes) -> str:
    """256-bit content hash, lowercase hex (64 chars). BLAKE3 if available."""
    if _blake3 is not None:  # pragma: no cover
        return _blake3(data).hexdigest()[:64]
    return hashlib.blake2b(data, digest_size=32).hexdigest()


def hash_str(s: str) -> str:
    return content_hash(s.encode("utf-8"))


def decimalize(obj: Any, scale: int = 6) -> Any:
    """Recursively encode reals as fixed-scale decimal strings (§5.1) so hashed
    content never contains a non-integer number. Applied before CJSON in id
    computation; the stored payload keeps its native numbers."""
    if isinstance(obj, bool):
        return obj
    if isinstance(obj, float):
        if obj == int(obj):
            return int(obj)
        return f"{obj:.{scale}f}"
    if isinstance(obj, dict):
        return {k: decimalize(v, scale) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [decimalize(v, scale) for v in obj]
    return obj


def event_id(type_: str, payload: dict, parents, actor: str, occurred_at: str) -> str:
    """event_id = 'ev_' + hash(CJSON({type, payload, parents(sorted), actor, occurred_at})) — §5.3."""
    obj = {
        "type": type_,
        "payload": decimalize(payload),
        "parents": sorted(parents or []),
        "actor": actor,
        "occurred_at": occurred_at,
    }
    return "ev_" + content_hash(cjson_dumps(obj).encode("utf-8"))


def belief_id(kind: str, key: dict, supports) -> str:
    """belief_id = 'b_' + hash(CJSON({kind, key, supports(sorted)})) — §5.3."""
    obj = {"kind": kind, "key": decimalize(key), "supports": sorted(supports or [])}
    return "b_" + content_hash(cjson_dumps(obj).encode("utf-8"))


def qualifiers_hash(qualifiers: dict) -> str:
    """Stable hash of a qualifiers map for natural-key disambiguation (§8.2)."""
    if not qualifiers:
        return ""
    return content_hash(cjson_dumps(qualifiers).encode("utf-8"))[:16]
