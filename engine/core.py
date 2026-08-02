"""
Chronicle — Core singleton (§11).

`ChronicleCore` owns all shared state (log, store, retrieval, scoring, curation,
capability registry, principals/ACL) and is a process-singleton keyed by
hermes_home. Both plugins obtain the same instance and record their presence so
each can pick its mode (§13.4). Cooperation between the plugins is an
optimization, never a correctness dependency (either runs alone).
"""

from __future__ import annotations

import logging
import threading
from pathlib import Path

from .capture import CaptureEngine, Reaper
from .config import Config
from .curation import CurationWorker
from .derivation import DerivationEngine
from .embeddings import get_embedder
from .extraction import PREDICATE_MAP, make_extractor
from .federation import CapabilityRegistry
from .forgetting import ForgettingEngine
from .gitmirror import GitMirror
from .health import HealthEngine
from .learning import LearningLoop
from .localdb import register_local_dbs
from .reasoning import EpistemicModel, ReasoningLayer
from .reducer import Reducer
from .retrieval import RetrievalEngine
from .store import MemoryStore, now_iso
from .tools import Tools
from .vector_index import VectorIndex

logger = logging.getLogger("chronicle.core")


class ChronicleCore:
    _instances = {}
    _active = None        # most-recently-created core (for slash-command handlers)
    _lock = threading.Lock()

    @classmethod
    def active(cls):
        """The live core for the current process (typically the only one)."""
        return cls._active or (next(iter(cls._instances.values())) if cls._instances else None)

    def __init__(self, hermes_home: str, config: dict | None = None):
        self.hermes_home = hermes_home
        self.cfg = Config(config or {})
        self.has_memory_provider = False
        self.has_context_engine = False
        self.active_principal = "default"

        db_path = self.cfg.get("db_path") or str(Path(hermes_home) / "commons/db/chronicle/chronicle.db")
        db_path = db_path.replace("~/.hermes", str(Path(hermes_home))) if db_path.startswith("~/.hermes") \
            else str(Path(hermes_home) / "commons/db/chronicle/chronicle.db")
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)

        self.store = MemoryStore(db_path)
        self.embedder = get_embedder(self.cfg.get("embeddings.model"),
                                     self.cfg.get("embeddings.dimensions"),
                                     self.cfg.get("embeddings.base_url"),
                                     self.cfg.get("embeddings.api_key"))
        # Optional ANN index (§27 vector_index:, u5) -- ONE instance, shared by
        # the store (add/delete/prune on write) and retrieval (KNN on read); see
        # vector_index.py and RetrievalEngine.__init__ for why sharing matters.
        # Dimensions come from the ACTIVE embedder, not a separate config knob,
        # so the vec0 column always matches what's actually being written.
        self.vector_index = VectorIndex(self.store, self.cfg, embedder=self.embedder)
        self.store.vector_index = self.vector_index
        self.reducer = Reducer(self.store, self.embedder, self.cfg)
        self.store.reducer = self.reducer                       # inline reduce on append (I7)
        self.capture = CaptureEngine(self.store, self.reducer,
                                     extractor_version=self.cfg.get("extraction.version", "extractor-v1"),
                                     cfg=self.cfg)
        self.extractor = make_extractor(self.cfg)
        self.derivation = DerivationEngine(self.store, self.cfg, self.capture.append)
        self.federation = CapabilityRegistry(self.store, self.cfg)
        self.retrieval = RetrievalEngine(self.store, self.cfg, self.embedder, self.derivation,
                                         vector_index=self.vector_index)
        self.forgetting = ForgettingEngine(self.store, self.cfg, self.capture.append)
        self.health = HealthEngine(self)
        self.learning = LearningLoop(self)
        self.epistemic = EpistemicModel(self.store, self.cfg)
        self.reasoning = ReasoningLayer(self)
        self.gitmirror = GitMirror(self.store, self.cfg)
        self.tools = Tools(self)
        self.curation = CurationWorker(self)
        self.reaper = Reaper(self.store, self.capture,
                             idle_threshold=self.cfg.get("reaper.idle_threshold", "20m"),
                             reap_threshold=self.cfg.get("reaper.reap_threshold", "45m"))

        self._seed()
        ChronicleCore._active = self
        logger.info("ChronicleCore initialized at %s (hash=%s)", db_path, _hash_name())

    def _seed(self):
        for surface, (canon, card) in PREDICATE_MAP.items():
            if self.store.get_predicate(surface) is None:
                self.store.upsert_predicate(surface, canon, card)
        self.derivation.seed_rules()

    @classmethod
    def get(cls, hermes_home: str, config=None) -> ChronicleCore:
        with cls._lock:
            if hermes_home not in cls._instances:
                if config is None:
                    config = cls._load_memory_config(hermes_home)
                cls._instances[hermes_home] = cls(hermes_home, config)
            return cls._instances[hermes_home]

    @staticmethod
    def _load_memory_config(hermes_home: str) -> dict:
        """The host's initialize_all() does not hand Chronicle a config dict, so
        load the ``memory:`` section from ``<hermes_home>/config.yaml`` ourselves.
        This is what makes embeddings/retrieval settings (e.g. a hosted embeddings
        endpoint) actually take effect at runtime, matching embedding_check.py."""
        try:
            import yaml
            p = Path(hermes_home) / "config.yaml"
            if p.exists():
                raw = yaml.safe_load(p.read_text()) or {}
                mem = raw.get("memory")
                if isinstance(mem, dict):
                    return mem
        except Exception as e:
            logger.warning("Chronicle: could not load memory config from %s/config.yaml: %s",
                           hermes_home, e)
        return {}

    # -- lifecycle ---------------------------------------------------------

    def initialize(self, session_id, *, hermes_home=None, principal_id="default", **kw):
        self.set_active_principal(principal_id)
        self.store.upsert_principal({"principal_id": principal_id, "type": "agent", "display": principal_id,
                                     "default_visibility": "shared", "created_at": now_iso()})
        # Register configured agents/principals (§27 principals.agents).
        for ag in self.cfg.get("principals.agents", []) or []:
            if self.store.get_principal(ag["id"]) is None:
                self.store.upsert_principal({"principal_id": ag["id"], "type": "agent", "display": ag["id"],
                                             "default_visibility": ag.get("default_visibility", "shared"),
                                             "created_at": now_iso()})
        self.on_startup_recovery()
        self.start_sources()
        self.bind_capabilities()
        return self.open_scope(session_id, principal_id)

    def set_active_principal(self, principal_id):
        self.active_principal = principal_id
        self.retrieval.active_principal = principal_id
        self.capture.owner = principal_id

    def open_scope(self, session_id, principal_id):
        return Scope(self, session_id, principal_id)

    def switch_scope(self, new_session_id, parent_session_id="", reset=False, rewound=False,
                     principal_id="default"):
        if rewound:
            # Mark the abandoned branch: events after the rewind point are not promoted (I16).
            old = self.store.get_session(new_session_id)
            if old:
                self.store.upsert_session({"session_id": new_session_id,
                                           "branch_point_seq": old.get("last_extracted_seq") or self.store.max_seq()})
        if parent_session_id:
            self.store.upsert_session({"session_id": new_session_id, "parent_session_id": parent_session_id,
                                       "status": "active", "started_at": now_iso(),
                                       "last_activity_at": now_iso()})
        return Scope(self, new_session_id, principal_id)

    def local_ok(self) -> bool:
        try:
            self.store.count_rows("events")
            return True
        except Exception:
            return False

    def on_startup_recovery(self):
        self.reaper.startup_recovery()
        self.process_pending()         # drain crash-recovered extraction (I13)

    def start_sources(self):
        if self.cfg.get("sources.ocas_journals.enabled") in (True, "auto"):
            self.store.enqueue_curation("journal_ingest", {})

    def bind_capabilities(self):
        self.federation.bind()
        register_local_dbs(self.federation, self.cfg)

    def abandon_after(self, session_id, branch_point_seq):
        """Mark a session's post-rewind observed events as abandoned (I16)."""
        self.store.upsert_session({"session_id": session_id, "branch_point_seq": branch_point_seq})

    def set_agent_privacy(self, agent, private=True):
        self.store.upsert_principal({"principal_id": agent,
                                     "default_visibility": "private" if private else "shared"})

    # -- work pumps --------------------------------------------------------

    def process_pending(self, max_jobs=1000) -> int:
        return self.curation.drain(max_jobs)

    def tick(self):
        """on_turn_start: drain a bounded curation slice + decay tick (§12.3)."""
        self.curation.drain(max_jobs=16)

    def flush_git(self) -> int:
        return self.gitmirror.flush()

    def embedding_status(self) -> dict:
        """Report which embedding mode is live: a real local model (and whether it
        currently embeds), the deliberate offline hashing embedder, or DEGRADED —
        no backend, nothing vectored, embeds queued (§24.4). Does a strict live test
        embed against the endpoint; the two backend-less embedders have none to
        probe, so every endpoint field is read through getattr."""
        from .embeddings import DegradedEmbedder, HashingEmbedder
        e = self.embedder
        info = {"embedder": type(e).__name__, "model": getattr(e, "model", None),
                "endpoint": getattr(e, "base_url", None), "dimensions": getattr(e, "dimensions", None)}
        if isinstance(e, HashingEmbedder):
            info.update(mode="offline_hashing", supports_embeddings=False,
                        detail="Offline hashing embedder selected explicitly (embeddings.model / "
                               "$CHRONICLE_EMBED_MODEL). Vectors are lexical, not semantic.")
            return info
        if isinstance(e, DegradedEmbedder) and e.live is None:
            info.update(mode="degraded", supports_embeddings=False,
                        pending_embeds=self.store.count_rows("curation_jobs",
                                                             "task='embed' AND status='pending'"),
                        detail=f"No embedding backend reachable for {e.requested_model!r}. NO vectors "
                               "are being written; each one is queued as an embed job and retried with "
                               "backoff. FTS retrieval still works.")
            return info
        e = getattr(e, "live", None) or e                 # a recovered DegradedEmbedder proxies one
        try:
            v = e._embed_raw("chronicle embedding self-test", timeout=getattr(e, "timeout", 10))
            info.update(mode="local_model", supports_embeddings=True, dimensions=len(v),
                        detail=f"Live test embed OK ({len(v)}-dim) from {e.base_url} model {e.model!r}.")
        except Exception as ex:
            info.update(mode="local_model_failing", supports_embeddings=False,
                        detail=f"Selected endpoint {getattr(e, 'base_url', None)} failed a live embed: "
                               f"{ex}. Vectors for this round are queued, never hashed.")
        return info


class Scope:
    def __init__(self, core, session_id, principal_id):
        self.core = core
        self.session_id = session_id
        self.principal_id = principal_id


def _hash_name():
    from .serialize import HASH_NAME
    return HASH_NAME
