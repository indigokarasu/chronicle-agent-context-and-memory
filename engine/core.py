"""
Chronicle — Core singleton (§11).

Process-singleton that owns the shared state: store, reducer, capture, retrieval.
Both plugins obtain the same instance.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional

logger = logging.getLogger("chronicle.core")


class ChronicleCore:
    """Shared core for both Chronicle plugins.

    Process-singleton keyed by hermes_home.
    """

    _instances: dict[str, "ChronicleCore"] = {}

    def __init__(self, hermes_home: str):
        from .store import MemoryStore
        from .reducer import Reducer
        from .capture import CaptureEngine, Reaper
        from .retrieval import RetrievalEngine

        self.hermes_home = hermes_home
        self.has_memory_provider = False
        self.has_context_engine = False

        # Initialize store
        db_path = Path(hermes_home) / "commons" / "db" / "chronicle" / "chronicle.db"
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self.store = MemoryStore(db_path)

        # Initialize subsystems
        self.reducer = Reducer(self.store)
        self.capture = CaptureEngine(self.store, self.reducer)
        self.retrieval = RetrievalEngine(self.store)
        self.reaper = Reaper(self.store, self.capture)

        # Active principal
        self.active_principal = "default"

        logger.info(f"ChronicleCore initialized at {db_path}")

    @classmethod
    def get(cls, hermes_home: str) -> "ChronicleCore":
        """Get or create the singleton for a given hermes_home."""
        if hermes_home not in cls._instances:
            cls._instances[hermes_home] = cls(hermes_home)
        return cls._instances[hermes_home]

    def initialize(self, session_id: str, *,
                   hermes_home: str,
                   principal_id: str = "default",
                   **kwargs):
        """Initialize for a session."""
        self.active_principal = principal_id
        self.retrieval.active_principal = principal_id
        self.capture.owner = principal_id

        # Startup recovery
        self.reaper.startup_recovery()

        # Ensure principal exists
        self.store.upsert_principal({
            "principal_id": principal_id,
            "type": "agent",
            "display": principal_id,
            "default_visibility": "shared",
            "created_at": self.capture._now(),
        })

        # Open scope
        self.open_scope(session_id, principal_id)

    def open_scope(self, session_id: str, principal_id: str) -> "Scope":
        """Open a session scope."""
        return Scope(self, session_id, principal_id)

    def switch_scope(self, new_session_id: str, parent_session_id: str = "",
                     reset: bool = False, rewound: bool = False,
                     principal_id: str = "default") -> "Scope":
        """Switch to a new session scope."""
        if reset:
            # Fresh scope
            pass
        return Scope(self, new_session_id, principal_id)

    def local_ok(self) -> bool:
        """Check if the local store is functional (no network)."""
        try:
            self.store.count_rows("events")
            return True
        except Exception:
            return False

    def on_startup_recovery(self):
        """Run startup recovery."""
        self.reaper.startup_recovery()

    def start_sources(self):
        """Start input sources (hooks always present)."""
        pass

    def bind_capabilities(self):
        """Bind capability providers."""
        pass


class Scope:
    """Per-session scope."""

    def __init__(self, core: ChronicleCore, session_id: str, principal_id: str):
        self.core = core
        self.session_id = session_id
        self.principal_id = principal_id
