"""Chronicle engine modules."""

from .capture import CaptureEngine, Reaper
from .config import Config
from .core import ChronicleCore, Scope
from .curation import CurationWorker
from .derivation import DerivationEngine
from .extraction import HeuristicExtractor
from .reducer import Reducer
from .retrieval import RetrievalEngine
from .serialize import belief_id, cjson_dumps, content_hash, event_id, hash_name
from .store import MemoryStore



def __getattr__(name):
    """`engine.HASH_NAME` is resolved on ACCESS, not on package import (A11b).

    Binding it at import time re-created the defect one level up: whether
    CHRONICLE_REQUIRE_BLAKE3 was honoured would depend on whether `import
    engine` happened before or after the variable was set."""
    if name == "HASH_NAME":
        return hash_name()
    raise AttributeError("module %r has no attribute %r" % (__name__, name))


__all__ = [
    "HASH_NAME",
    "CaptureEngine",
    "ChronicleCore",
    "Config",
    "CurationWorker",
    "DerivationEngine",
    "HeuristicExtractor",
    "MemoryStore",
    "Reaper",
    "Reducer",
    "RetrievalEngine",
    "Scope",
    "belief_id",
    "cjson_dumps",
    "content_hash",
    "event_id",
    "hash_name",
]
