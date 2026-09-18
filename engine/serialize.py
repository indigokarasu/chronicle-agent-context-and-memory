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

A11b: that environment variable is read WHERE IT IS USED, not at import time.
The import-time read made the module's behaviour a function of whichever import
happened to run first, so anything wanting to control it — a test harness, a
host that reads its own config before configuring Chronicle — had to win a race
against the import graph. Now `hash_name()` / `content_hash()` consult the
environment on each call: set it late, unset it, set it per-subprocess, and the
answer follows. The `blake3` *import* is still attempted only once and cached
(importing is expensive and its result cannot change mid-process); only the
policy question "is a missing blake3 fatal?" is re-asked.
"""

from __future__ import annotations

import hashlib
import os
from typing import Any, Callable, Optional, Tuple

#: Name of the environment variable that turns a missing `blake3` into an error.
REQUIRE_BLAKE3_ENV = "CHRONICLE_REQUIRE_BLAKE3"

BLAKE3_NAME = "blake3-256"
BLAKE2B_NAME = "blake2b-256"

# Cached result of the one-shot `import blake3`. `None` = not attempted yet.
_IMPORT_ATTEMPTED = False
_BLAKE3: Optional[Callable] = None
_BLAKE3_ERROR: Optional[BaseException] = None


class Blake3Required(RuntimeError):
    """CHRONICLE_REQUIRE_BLAKE3=1 but the `blake3` package is not importable."""


def _load_blake3() -> Tuple[Optional[Callable], Optional[BaseException]]:
    """Attempt `import blake3` at most once per process; cache either outcome."""
    global _IMPORT_ATTEMPTED, _BLAKE3, _BLAKE3_ERROR
    if not _IMPORT_ATTEMPTED:
        try:  # pragma: no cover - depends on environment
            from blake3 import blake3 as _b3  # type: ignore
            _BLAKE3, _BLAKE3_ERROR = _b3, None
        except Exception as exc:  # pragma: no cover - depends on environment
            _BLAKE3, _BLAKE3_ERROR = None, exc
        _IMPORT_ATTEMPTED = True
    return _BLAKE3, _BLAKE3_ERROR


def require_blake3() -> bool:
    """Is a missing `blake3` a hard error? Read from the environment NOW."""
    return os.environ.get(REQUIRE_BLAKE3_ENV) == "1"


def _hasher() -> Tuple[Optional[Callable], str]:
    """(blake3 callable or None, hash name), enforcing the requirement now."""
    b3, err = _load_blake3()
    if b3 is None and require_blake3():
        raise Blake3Required(
            "%s=1 but the blake3 package is not importable (%s); install blake3 or unset "
            "%s to fall back to %s" % (REQUIRE_BLAKE3_ENV, err, REQUIRE_BLAKE3_ENV, BLAKE2B_NAME)
        )
    return (b3, BLAKE3_NAME if b3 is not None else BLAKE2B_NAME)


def hash_name() -> str:
    """Name of the active 256-bit content hash. Raises if blake3 is required
    and absent — the same condition the import-time check used to raise on,
    now raised at the moment someone actually depends on the answer."""
    return _hasher()[1]


def reset_hash_probe() -> None:
    """Forget the cached `import blake3` outcome (tests only)."""
    global _IMPORT_ATTEMPTED, _BLAKE3, _BLAKE3_ERROR
    _IMPORT_ATTEMPTED = False
    _BLAKE3 = None
    _BLAKE3_ERROR = None


def __getattr__(name: str) -> Any:
    """`HASH_NAME` stays readable as a module attribute (PEP 562) so existing
    `serialize.HASH_NAME` call sites keep working — but reading it now calls
    `hash_name()`, so it reflects the environment at READ time rather than at
    import time. `from .serialize import HASH_NAME` still snapshots, which is
    why `engine/__init__.py` and `core.py` go through the function instead."""
    if name == "HASH_NAME":
        return hash_name()
    raise AttributeError("module %r has no attribute %r" % (__name__, name))


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


def _cjson_str_py(s: str) -> str:
    """The CJSON string rule, spelled out: the seven short escapes, any other
    control character as lowercase \\u00xx, everything else raw."""
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


# The standard library's JSON string encoder applies exactly that rule, in C
# when available (checked over every code point: identical). Per character in
# Python it was 12 s of a 17 s compaction on the production box -- every event
# id and span id hashes the full text.
try:
    from json.encoder import encode_basestring as _cjson_str
except ImportError:  # pragma: no cover
    _cjson_str = _cjson_str_py


def content_hash(data: bytes) -> str:
    """256-bit content hash, lowercase hex (64 chars). BLAKE3 if available."""
    b3, _name = _hasher()
    if b3 is not None:  # pragma: no cover
        return b3(data).hexdigest()[:64]
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


def projection_row_id(prefix: str, key: dict) -> str:
    """`'<prefix>_' + hash(CJSON(key))` — belief_id's §5.3 construction applied
    to a row of a projection SIDE table (Ladder 10 A4).

    The four side tables the reducer writes (`contradictions`, `corrections`,
    `supersede_candidates`, `identity_candidates`) used to mint `uuid4()` row
    ids, which made `truncate_projection()` + `rebuild()` produce a projection
    that was *equivalent* but never *byte-identical* — and left nothing stable
    for another table to reference a row by, since the id changed on every
    rebuild. Deriving the id from the row's own content fixes both: the same
    event log yields the same id, in this process, in the next one, and in a
    different store built from the same log.

    `key` must contain only values the EVENT LOG determines (ids, predicates,
    the triggering event_id) — never a wall-clock reading and never a float
    whose exact bits depend on the embedder, or the id stops being a function
    of the log. `decimalize` is applied for the same reason it is applied to a
    belief key: a float must never reach the hash at full binary precision.
    """
    return prefix + "_" + content_hash(cjson_dumps(decimalize(key)).encode("utf-8"))


def qualifiers_hash(qualifiers: dict) -> str:
    """Stable hash of a qualifiers map for natural-key disambiguation (§8.2)."""
    if not qualifiers:
        return ""
    return content_hash(cjson_dumps(qualifiers).encode("utf-8"))[:16]
