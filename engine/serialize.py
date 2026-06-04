"""
Chronicle — Serialization & content addressing (§5).

Canonical JSON (CJSON) + BLAKE2b hashing for content-addressed events and beliefs.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any


def cjson_dumps(obj: Any) -> str:
    """Serialize to Canonical JSON (CJSON).

    Rules:
    - UTF-8, no BOM
    - Object keys sorted by Unicode code point
    - No insignificant whitespace
    - Only mandatory string escapes; non-ASCII emitted as raw UTF-8
    - Integers: decimal, no leading zeros, no '+', no '-0'
    - Non-integer numbers: encoded as fixed-scale decimal strings
    - Booleans/null: literal
    - Array order preserved
    """
    return _cjson_encode(obj, 0)


def _cjson_encode(obj: Any, _indent: int) -> str:
    if obj is None:
        return "null"
    if isinstance(obj, bool):
        return "true" if obj else "false"
    if isinstance(obj, int):
        if obj == 0:
            return "0"
        if obj < 0:
            return f"-{abs(obj)}"
        s = str(obj)
        if s.startswith(("0", "+")):
            raise ValueError(f"Invalid integer format: {s}")
        return s
    if isinstance(obj, float):
        # Encode as fixed-scale decimal string to avoid floating-point non-determinism
        return f"{obj:.10f}".rstrip("0").rstrip(".")
    if isinstance(obj, str):
        return _cjson_str(obj)
    if isinstance(obj, list):
        items = ",".join(_cjson_encode(v, _indent) for v in obj)
        return f"[{items}]"
    if isinstance(obj, dict):
        keys = sorted(obj.keys())
        pairs = []
        for k in keys:
            v = obj[k]
            pairs.append(f"{_cjson_str(k)}:{_cjson_encode(v, _indent)}")
        return "{" + ",".join(pairs) + "}"
    raise TypeError(f"CJSON cannot serialize {type(obj).__name__}")


def _cjson_str(s: str) -> str:
    """Encode a string with only mandatory JSON escapes."""
    parts = ['"']
    for ch in s:
        if ch == '"':
            parts.append('\\"')
        elif ch == "\\":
            parts.append("\\\\")
        elif ch == "\b":
            parts.append("\\b")
        elif ch == "\f":
            parts.append("\\f")
        elif ch == "\n":
            parts.append("\\n")
        elif ch == "\r":
            parts.append("\\r")
        elif ch == "\t":
            parts.append("\\t")
        elif ord(ch) < 0x20:
            parts.append(f"\\u{ord(ch):04x}")
        else:
            parts.append(ch)
    parts.append('"')
    return "".join(parts)


def content_hash(data: bytes) -> str:
    """BLAKE2b-256 hash, lowercase hex (64 chars)."""
    return hashlib.blake2b(data, digest_size=32).hexdigest()


def event_id(type_: str, payload: dict, parents: list[str],
             actor: str, occurred_at: str) -> str:
    """Compute event_id = 'ev_' + hash(CJSON({type, payload, parents, actor, occurred_at}))."""
    parents_sorted = sorted(parents)
    obj = {"type": type_, "payload": payload, "parents": parents_sorted,
           "actor": actor, "occurred_at": occurred_at}
    h = content_hash(cjson_dumps(obj).encode("utf-8"))
    return f"ev_{h}"


def belief_id(kind: str, key: dict, supports: list[str]) -> str:
    """Compute belief_id = 'b_' + hash(CJSON({kind, key, supports}))."""
    supports_sorted = sorted(supports)
    obj = {"kind": kind, "key": key, "supports": supports_sorted}
    h = content_hash(cjson_dumps(obj).encode("utf-8"))
    return f"b_{h}"
