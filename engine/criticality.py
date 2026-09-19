"""
Chronicle — Criticality classification (§20.1).

Pure rules floor: safety / medical / legal / financial / boundary / identity /
security content is never lost to passive decay (I10). Learned refinement may
*raise* criticality but never lower it (§20.1) — enforced by callers.
"""

from __future__ import annotations

from .extraction import is_standing_instruction

# (criticality, category, keywords)
_RULES = [
    ("critical", "safety", ["allerg", "anaphyla", "epipen", "do not resuscitate", "suicid", "overdose"]),
    ("critical", "medical", ["medication", "dosage", "prescription", "diagnos", "blood type", "insulin"]),
    ("high", "legal", ["nda", "contract", "lawsuit", "liabilit", "confidential", "gdpr", "hipaa"]),
    ("high", "financial", ["account number", "routing", "ssn", "tax id", "salary", "bank", "wire transfer"]),
    ("high", "boundary", ["must not", "boundary", "off-limits"]),
    ("high", "identity", ["legal name", "passport", "date of birth", "national id", "license number"]),
    ("high", "security", ["password", "api key", "secret", "private key", "credential", "2fa", "mfa"]),
]

# A6: these used to sit in the "boundary" rule as plain substrings, so ANY text
# containing "don't " -- "I don't like cilantro", "I don't know the price" --
# was promoted to high criticality and thereby exempted from passive decay
# (I10). A boundary is a standing instruction, so the same imperative-shape test
# the extractor uses for norms gates them here.
_BOUNDARY_IMPERATIVE = ["never ", "do not ", "don't ", "always ask"]


def classify(text: str, kind: str = "fact", note_type: str = "") -> tuple[str, str]:
    """Return (criticality, reason). Directives/norms start at high (never-evict)."""
    t = (text or "").lower()
    best = ("normal", "")
    rank = {"normal": 0, "high": 1, "critical": 2}
    for crit, cat, kws in _RULES:
        if any(kw in t for kw in kws):
            if rank[crit] > rank[best[0]]:
                best = (crit, cat)
    if (rank[best[0]] < 1 and any(kw in t for kw in _BOUNDARY_IMPERATIVE)
            and is_standing_instruction(text)):
        best = ("high", "boundary")
    if note_type == "norm" and rank[best[0]] < 1:
        best = ("high", "directive")
    return best
