"""Chronicle — Error codes (§32)."""

from __future__ import annotations


class ChronicleError(Exception):
    code = "E_STORE"

    def __init__(self, message: str = "", **detail):
        super().__init__(message or self.code)
        self.detail = detail


class E_SCHEMA(ChronicleError):
    code = "E_SCHEMA"  # payload/input failed validation


class E_NOT_FOUND(ChronicleError):
    code = "E_NOT_FOUND"


class E_FORBIDDEN_CONTENT(ChronicleError):
    code = "E_FORBIDDEN_CONTENT"  # write matches a tombstone


class E_TRUST_CEILING(ChronicleError):
    code = "E_TRUST_CEILING"


class E_INFO_LABEL(ChronicleError):
    code = "E_INFO_LABEL"


class E_PURPOSE(ChronicleError):
    code = "E_PURPOSE"


class E_CONFLICT(ChronicleError):
    code = "E_CONFLICT"


class E_BUDGET(ChronicleError):
    code = "E_BUDGET"


class E_EVICT_UNSAFE(ChronicleError):
    code = "E_EVICT_UNSAFE"  # engine asked to evict a non-durable span (I17)


class E_RISK_REVIEW(ChronicleError):
    code = "E_RISK_REVIEW"


class E_LEARN_BOUND(ChronicleError):
    code = "E_LEARN_BOUND"  # delta cap / mutation-surface exceeded (I19)


class E_AUTHORITY_UNAVAILABLE(ChronicleError):
    code = "E_AUTHORITY_UNAVAILABLE"  # federated call with no active provider


class E_ACCESS_DENIED(ChronicleError):
    code = "E_ACCESS_DENIED"  # read of explicitly-restricted memory (§15.3)


class E_READ_BUDGET(ChronicleError):
    code = "E_READ_BUDGET"


class E_DERIVATION_GUARD(ChronicleError):
    code = "E_DERIVATION_GUARD"  # rule asked to fire with guards unmet (I24)


class E_STORE(ChronicleError):
    code = "E_STORE"
