"""
Chronicle — Provenance, trust, calibration (§10).

Trust ceilings cap confidence (I6); calibration maps raw confidence to an
empirically-correct probability before it is surfaced to the agent (I8).
Calibration is a per-source_type isotonic-style fit over observed buckets, and
falls back to identity until `min_obs` samples exist.
"""

from __future__ import annotations

from .config import CONFIDENCE_BASE, TRUST_CEILING


# §A12 — THE CONFIG MUST WIN.
#
# `confidence.base.*` and `confidence.trust_ceiling.*` were declared in DEFAULTS
# and then ignored: every caller reached the module constants directly, so an
# operator who set `confidence: base: user_direct: 0.95` changed nothing, while
# hostmodel.py's comment told them their host facts used "the operator's
# configured confidence.base". Both functions now take an optional `cfg` and
# read it; `cfg=None` keeps the module constants, which is what the several
# `Reducer(store)`-with-no-config construction paths (and the direct unit tests)
# rely on. The lookup tolerates a YAML round trip turning the integer trust
# levels into strings.


def _table(cfg, path: str, fallback: dict) -> dict:
    """The configured table at `path`, or the module constant."""
    if cfg is None:
        return fallback
    try:
        val = cfg.get(path, None)
    except Exception:                     # a plain dict without .get semantics
        return fallback
    return val if isinstance(val, dict) and val else fallback


def ceiling(trust_level: int, cfg=None) -> float:
    table = _table(cfg, "confidence.trust_ceiling", TRUST_CEILING)
    # A YAML/JSON round trip turns the integer levels into strings, and the deep
    # merge then leaves BOTH forms in the table (int 2 from DEFAULTS, "2" from
    # the operator). The operator's form is the one they wrote, so it wins.
    if str(trust_level) in table:
        return _as_float(table[str(trust_level)], 0.75)
    if trust_level in table:
        return _as_float(table[trust_level], 0.75)
    return 0.75


def _as_float(val, default: float) -> float:
    try:
        return float(val)
    except (TypeError, ValueError):
        return default


def base_confidence(source_type: str, cfg=None) -> float:
    table = _table(cfg, "confidence.base", CONFIDENCE_BASE)
    return _as_float(table.get(source_type, 0.6), 0.6)


def raw_confidence(source_type: str, confirm_count: int = 0, contradiction_count: int = 0,
                   cfg=None) -> float:
    """raw = base(source_type) + 0.05·min(confirm,5) − 0.10·contradiction (§10.4)."""
    raw = base_confidence(source_type, cfg) + 0.05 * min(confirm_count, 5) \
        - 0.10 * contradiction_count
    return max(0.0, min(1.0, raw))


def clamp_to_ceiling(confidence: float, trust_level: int, corroborated: bool = False,
                     cfg=None) -> float:
    """Apply the trust ceiling (I6). Independent corroboration raises it one band."""
    lvl = trust_level
    if corroborated:
        lvl = min(trust_level + 1, 4)
    return min(confidence, ceiling(lvl, cfg))


def bucket_of(score: float) -> str:
    """Coarse decile bucket label for calibration tables."""
    b = int(max(0.0, min(0.999, score)) * 10)
    return f"{b/10:.1f}"


class Calibrator:
    """Isotonic-ish calibration per source_type (§10.5)."""

    def __init__(self, store, min_obs: int = 50):
        self.store = store
        self.min_obs = min_obs

    def calibrate(self, raw: float, source_type: str) -> float:
        obs = self.store.get_calibration_obs(source_type)
        total = sum(o["n"] for o in obs)
        if total < self.min_obs or not obs:
            return raw  # identity until enough evidence
        # Empirical correctness for the raw score's bucket, smoothed and
        # monotone-clamped against neighbouring buckets (pool-adjacent-violators lite).
        points = sorted(((float(o["predicted_bucket"]),
                          (o["correct"] + 1) / (o["n"] + 2)) for o in obs), key=lambda p: p[0])
        # Enforce monotonic non-decreasing empirical probability.
        mono = []
        last = 0.0
        for x, y in points:
            last = max(last, y)
            mono.append((x, last))
        b = float(bucket_of(raw))
        # Nearest bucket at or below b, else first.
        chosen = mono[0][1]
        for x, y in mono:
            if x <= b + 1e-9:
                chosen = y
            else:
                break
        return max(0.0, min(1.0, chosen))


def confidence_summary(belief: dict, calibrated: float) -> dict:
    """The calibrated surface returned to the agent (§10.4, I8)."""
    prov = belief.get("provenance") or "{}"
    import json
    try:
        sources = [json.loads(prov).get("source_type", "unknown")]
    except Exception:
        sources = ["unknown"]
    return {
        "score": round(calibrated, 4),
        "sources": sources,
        "user_confirmed": belief.get("confirm_count", 0) > 0,
        "ever_contradicted": belief.get("contradiction_count", 0) > 0,
        "last_confirmed_at": belief.get("last_confirmed_at"),
        "trust_level": belief.get("trust_level"),
    }
