"""
Chronicle — Criticality classification (§20.1).

Pure rules floor: safety / medical / legal / financial / boundary / identity /
security content is never lost to passive decay (I10). Learned refinement may
*raise* criticality but never lower it (§20.1) — enforced by callers.
"""

from __future__ import annotations

from typing import Tuple

# (criticality, category, keywords)
_RULES = [
    ("critical", "safety", ["allerg", "anaphyla", "epipen", "do not resuscitate", "suicid", "overdose"]),
    ("critical", "medical", ["medication", "dosage", "prescription", "diagnos", "blood type", "insulin"]),
    ("high", "legal", ["nda", "contract", "lawsuit", "liabilit", "confidential", "gdpr", "hipaa"]),
    ("high", "financial", ["account number", "routing", "ssn", "tax id", "salary", "bank", "wire transfer"]),
    ("high", "boundary", ["never ", "do not ", "don't ", "must not", "always ask", "boundary", "off-limits"]),
    ("high", "identity", ["legal name", "passport", "date of birth", "national id", "license number"]),
    ("high", "security", ["password", "api key", "secret", "private key", "credential", "2fa", "mfa"]),
]


def classify(text: str, kind: str = "fact", note_type: str = "") -> Tuple[str, str]:
    """Return (criticality, reason). Directives/norms start at high (never-evict)."""
    t = (text or "").lower()
    best = ("normal", "")
    rank = {"normal": 0, "high": 1, "critical": 2}
    for crit, cat, kws in _RULES:
        if any(kw in t for kw in kws):
            if rank[crit] > rank[best[0]]:
                best = (crit, cat)
    if note_type == "norm" and rank[best[0]] < 1:
        best = ("high", "directive")
    return best
