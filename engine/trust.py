"""
Chronicle — Provenance, trust, calibration (§10).

Trust ceilings cap confidence (I6); calibration maps raw confidence to an
empirically-correct probability before it is surfaced to the agent (I8).
Calibration is a per-source_type isotonic-style fit over observed buckets, and
falls back to identity until `min_obs` samples exist.
"""

from __future__ import annotations

from .config import CONFIDENCE_BASE, TRUST_CEILING


def ceiling(trust_level: int) -> float:
    return TRUST_CEILING.get(trust_level, 0.75)


def base_confidence(source_type: str) -> float:
    return CONFIDENCE_BASE.get(source_type, 0.6)


def raw_confidence(source_type: str, confirm_count: int = 0, contradiction_count: int = 0) -> float:
    """raw = base(source_type) + 0.05·min(confirm,5) − 0.10·contradiction (§10.4)."""
    raw = base_confidence(source_type) + 0.05 * min(confirm_count, 5) - 0.10 * contradiction_count
    return max(0.0, min(1.0, raw))


def clamp_to_ceiling(confidence: float, trust_level: int, corroborated: bool = False) -> float:
    """Apply the trust ceiling (I6). Independent corroboration raises it one band."""
    lvl = trust_level
    if corroborated:
        lvl = min(trust_level + 1, 4)
    return min(confidence, ceiling(lvl))


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
