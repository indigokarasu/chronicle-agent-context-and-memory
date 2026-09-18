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

from . import access
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
from .hostmodel import HostModelRegistry
from .learning import LearningLoop
from .localdb import register_local_dbs
from .reasoning import EpistemicModel, ReasoningLayer
from .reducer import Reducer
from .retrieval import RetrievalEngine
from .scheduler import Scheduler
from .store import MemoryStore, StoreClosed, now_iso
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

    def __init__(self, hermes_home: str, config: dict | None = None, embedder_probe=None):
        """`embedder_probe` (A11b): the object embeddings auto-detection uses to
        contact candidate endpoints. `None` means `embeddings.default_probe()`,
        i.e. the real network probe — so a core built with no embeddings config
        DOES open TCP connections to localhost:1234/:11434/:8080 inside this
        constructor, and which one answers decides which embedder this core
        holds. Pass `embeddings.NullProbe()` (or `StaticProbe({...})`) to make
        construction socket-free and machine-independent."""
        self.hermes_home = hermes_home
        self.embedder_probe = embedder_probe
        self.cfg = Config(config or {})
        # §15.8 (issue #5): install the declarative users/agents ACL topology
        # from `principals:` config into the access.can_read choke point. One
        # process-wide default (mirrors ChronicleCore._active) — every existing
        # access.can_read call site needs no change to be governed by it.
        access.configure_topology(self.cfg.get("principals"))
        self.has_memory_provider = False
        self.has_context_engine = False
        self._startup_recovered = False   # on_startup_recovery: once per process
        # The background drain (drain_in_background): off until a host asks.
        self._drain_in_background = False
        self._drain_kick = threading.Event()
        self._drain_thread: threading.Thread | None = None
        self._drain_thread_lock = threading.Lock()
        self.active_principal = "default"

        db_path = self.cfg.get("db_path") or str(Path(hermes_home) / "commons/db/chronicle/chronicle.db")
        db_path = db_path.replace("~/.hermes", str(Path(hermes_home))) if db_path.startswith("~/.hermes") \
            else str(Path(hermes_home) / "commons/db/chronicle/chronicle.db")
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)

        self.store = MemoryStore(db_path)
        self.embedder = get_embedder(self.cfg.get("embeddings.model"),
                                     self.cfg.get("embeddings.dimensions"),
                                     self.cfg.get("embeddings.base_url"),
                                     self.cfg.get("embeddings.api_key"),
                                     self.cfg.get("embeddings.max_input_tokens"),
                                     self.cfg.get("embeddings.overflow"),
                                     self.cfg.get("embeddings.task_prefixes"),
                                     self.cfg.get("embeddings.allow_remote"),
                                     probe=embedder_probe)
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
        # Host-model piggyback registry (§H1). Constructing it is free — the
        # constructor stores two references and touches neither SQLite nor
        # config — so it is safe on the default path, where host_model.piggyback
        # is False and not one of its methods is ever called.
        self.host_model = HostModelRegistry(self.store, self.cfg)
        self.tools = Tools(self)
        self.curation = CurationWorker(self)
        # §A12: `reaper.enabled` was declared and read by nothing, so the one
        # documented way to turn the reaper off did nothing. It is a real switch
        # now: disabled, the Reaper is still CONSTRUCTED (every caller of
        # core.reaper.* keeps working) but its sweep and startup recovery are
        # not driven from here.
        self.reaper_enabled = bool(self.cfg.get("reaper.enabled", True))
        self.reaper = Reaper(self.store, self.capture,
                             idle_threshold=self.cfg.get("reaper.idle_threshold", "20m"),
                             reap_threshold=self.cfg.get("reaper.reap_threshold", "45m"))
        # Maintenance cadence (§17.4). Constructing it is free — it stores three
        # references, parses no config and touches no SQLite until the first
        # hook call — and it owns NO thread: everything it does happens inside
        # a hook, bounded by maintenance.budget_ms.
        self.scheduler = Scheduler(self)

        self._seed()
        ChronicleCore._active = self
        logger.info("ChronicleCore initialized at %s (hash=%s)", db_path, _hash_name())

    def _seed(self):
        for surface, (canon, card) in PREDICATE_MAP.items():
            if self.store.get_predicate(surface) is None:
                self.store.upsert_predicate(surface, canon, card)
        self.derivation.seed_rules()

    @classmethod
    def get(cls, hermes_home: str, config: dict | None = None, embedder_probe=None) -> ChronicleCore:
        with cls._lock:
            if hermes_home not in cls._instances:
                if config is None:
                    config = cls._load_memory_config(hermes_home)
                cls._instances[hermes_home] = cls(hermes_home, config,
                                                  embedder_probe=embedder_probe)
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

    def close(self) -> dict:
        """Release everything this core owns. Idempotent; safe to call twice.

        A11b: the core is the OWNER of the store's lifetime — it is what
        constructs `MemoryStore` — so it is what closes it. Closing also
        de-registers this core from the process singleton table, because a
        cached core whose store is closed would hand every later
        `ChronicleCore.get()` caller a store that raises `StoreClosed`.

        Returns the store's own close report (see `MemoryStore.close`)."""
        report = self.store.close()
        with ChronicleCore._lock:
            for key, core in list(ChronicleCore._instances.items()):
                if core is self:
                    del ChronicleCore._instances[key]
            if ChronicleCore._active is self:
                ChronicleCore._active = None
        return report

    def __enter__(self) -> "ChronicleCore":
        return self

    def __exit__(self, exc_type, exc, tb) -> bool:
        self.close()
        return False

    def initialize(self, session_id: str, *, hermes_home: str | None = None, principal_id: str = "default", **kw) -> Scope:
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

    def set_active_principal(self, principal_id: str) -> None:
        self.active_principal = principal_id
        self.retrieval.active_principal = principal_id
        self.derivation.active_principal = principal_id   # explain() is a read surface (A1)
        self.capture.owner = principal_id

    def open_scope(self, session_id: str, principal_id: str) -> Scope:
        return Scope(self, session_id, principal_id)

    def switch_scope(self, new_session_id: str, parent_session_id: str = "", reset: bool = False, rewound: bool = False,
                     principal_id: str = "default") -> Scope:
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
        """Crash recovery (I13): once per PROCESS, and bounded.

        initialize() runs on every session start — every conversation and every
        cron agent run on a gateway — and this used to run all of it each time,
        ending in process_pending(): a synchronous drain of up to 1,000 queued
        jobs before the session could begin. The queue holds embed jobs, and on a
        CPU-throttled host whose embedding server times out that was minutes per
        session start (measured: 320 s and 830 s for one engine init against the
        production store).

        Recovery is bookkeeping about a previous process, so it happens once per
        core. The drain that follows is one ordinary turn's slice
        (curation.drain.per_turn); every later turn drains another, which is the
        path the rest of the queue already takes."""
        if self._startup_recovered:
            return
        self._startup_recovered = True
        # §A12: both `reaper.enabled` and `reaper.startup_recovery` gate this.
        if self.reaper_enabled and self.cfg.get("reaper.startup_recovery", True):
            self.reaper.startup_recovery()
        self._drain_slice()            # one turn's slice of crash-recovered extraction (I13)

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
        """on_turn_start: drain a bounded curation slice, then take ONE
        maintenance decision (§12.3, §17.4, §A7).

        The slice size is `curation.drain.per_turn` (default 16, the pre-A7
        hard-coded value) and its MIX is decided by the queue, not here: a turn
        asks for N jobs and `CurationWorker.drain` apportions them across task
        classes so an embed or maintenance flood cannot starve extraction
        (§A7). Passing no budget is deliberate — a caller that named one would
        be the second place the per-turn size is configured.

        ORDER MATTERS and is deliberate (§17.4). The drain runs FIRST, so a
        maintenance job scheduled by this call lands at the back of the queue
        and is picked up by a LATER turn's slice — a health run or a decay
        sweep never executes inside the same turn that decided to schedule it.
        The decision itself is bounded by maintenance.budget_ms and enqueues at
        most one job, so the cost this hook adds when nothing is due is a
        handful of integer comparisons (measured: well under 1ms, no SQLite at
        all). maintenance.budget_ms bounds the TICK only; the drain above is
        bounded by curation.drain.per_turn and by A7's per-class quotas."""
        self._drain_slice()
        self.scheduler.on_hook("turn")

    def drain_in_background(self) -> None:
        """Take the per-turn curation slice off the caller's thread from now on.

        A host calls this before initialize(): Hermes calls on_turn_start --
        and so tick() -- synchronously, before the model, so every job in the
        slice ran inside the user's turn. An embed job against the CPU-bound
        embedding server could hold that turn for the whole request timeout,
        and with that timeout raised so a long excerpt can embed at all, it
        would hold it for minutes. The jobs are the same, durable and claimed
        atomically; only the thread changes. One worker per core, woken by
        each tick; kicks that arrive while it drains are coalesced into one
        more pass."""
        self._drain_in_background = True

    def _drain_slice(self) -> None:
        if not self._drain_in_background:
            self.curation.drain()
            return
        with self._drain_thread_lock:
            if self._drain_thread is None or not self._drain_thread.is_alive():
                self._drain_thread = threading.Thread(target=self._drain_loop,
                                                      name="chronicle-curation", daemon=True)
                self._drain_thread.start()
        self._drain_kick.set()

    def _drain_loop(self) -> None:
        while True:
            self._drain_kick.wait()
            self._drain_kick.clear()
            try:
                self.curation.drain()
            except StoreClosed:
                return                 # the core was closed under us: nothing left to drain
            except Exception:          # noqa: BLE001 -- a bad job must not kill the worker
                logger.exception("Chronicle: background curation drain failed")

    def maintenance_status(self) -> dict:
        """Last run / next due, per maintenance schedule entry, plus the tasks
        that are deliberately NOT scheduled and why (§17.4). Read-only."""
        return self.scheduler.status()

    def flush_git(self) -> int:
        return self.gitmirror.flush()

    def identity_candidates(self, principal: str | None = None, status: str = "pending", kind: str = "", limit: int = 50) -> list[dict]:
        """The identity adjudication queue (§E7), ACL-filtered and named.

        ONE projection shared by every listing surface (the `chronicle_
        list_identity_candidates` tool and the provider's
        `list_identity_candidates`), so they cannot disagree about what a
        principal is allowed to see. A candidate naming an entity the principal
        cannot read (§15) is dropped, not redacted — its existence is itself a
        disclosure about that entity.

        Strictly read-only: listing a candidate never applies it. Nothing in
        Chronicle merges or splits an entity from these rows."""
        principal = principal or self.active_principal
        out = []
        for c in self.store.get_identity_candidates(status=status, kind=kind, limit=int(limit)):
            ents, names, visible = [c.get("entity_id") or ""], [], True
            if c.get("other_id"):
                ents.append(c["other_id"])
            for eid in ents:
                ent = self.store.get_belief("entities", eid)
                if not ent or not access.can_read(ent.get("read_acl"), ent.get("owner"), principal):
                    visible = False
                    break
                names.append(ent.get("name"))
            if not visible:
                continue
            out.append({"candidate_id": c["id"], "kind": c["kind"],
                        "entity_ids": ents, "entity_names": names,
                        "mention_ref": c.get("mention_ref") or None,
                        "similarity": c.get("similarity"), "status": c.get("status"),
                        "created_at": c.get("created_at")})
        return out

    def embedding_status(self) -> dict:
        """Report which embedding mode is live: a real local model (and whether it
        currently embeds), the deliberate offline hashing embedder, or DEGRADED —
        no backend, nothing vectored, embeds queued (§24.4). Does a strict live test
        embed against the endpoint; the two backend-less embedders have none to
        probe, so every endpoint field is read through getattr."""
        from .embeddings import DegradedEmbedder, HashingEmbedder
        e = self.embedder
        info = {"embedder": type(e).__name__, "model": getattr(e, "model", None),
                "endpoint": getattr(e, "base_url", None), "dimensions": getattr(e, "dimensions", None),
                # A7: pending work per task AND per fairness class. "embeds are
                # queued" was already reported; what it never said was whether
                # anything ELSE was queued behind them, which is the question an
                # operator staring at a stalled store actually has.
                "queue": self.store.pending_counts_by_task()}
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

    def get_materialized_profile(self, owner: str = "default") -> dict:
        """Retrieve the materialized profile summary for an owner."""
        raw = self.store.get_meta(f"profile_summary:{owner}", "")
        if not raw:
            return {"static": {}, "dynamic": {}}
        try:
            import json
            return json.loads(raw)
        except Exception:
            return {"static": {}, "dynamic": {}}

    def diagnostics(self) -> dict:
        """Comprehensive system diagnostics for agents and operators.

        Reports database stats, vector index configuration, pending background
        work, embedding mode, active principal, and component state in one place.
        """
        events_count = 0
        beliefs_count = 0
        pending_curation = 0
        try:
            events_count = self.store.count_rows("events")
            beliefs_count = self.store.count_rows("beliefs", "status='active'")
            pending_curation = self.store.count_rows("curation_jobs", "status='pending'")
        except Exception:
            pass

        vector_info = {}
        if hasattr(self, "vector_index") and self.vector_index:
            try:
                vector_info = {
                    "backend": getattr(self.vector_index, "backend", "unknown"),
                    "total_vectors": self.vector_index.count(),
                }
            except Exception as e:
                vector_info = {"backend": "error", "error": str(e)}

        return {
            "active_principal": self.active_principal,
            "hermes_home": self.hermes_home,
            "database": {
                "events_count": events_count,
                "active_beliefs_count": beliefs_count,
                "pending_curation_jobs": pending_curation,
            },
            "vector_index": vector_info,
            "embedding": self.embedding_status(),
        }


class Scope:
    def __init__(self, core, session_id, principal_id):
        self.core = core
        self.session_id = session_id
        self.principal_id = principal_id


def _hash_name():
    from .serialize import hash_name
    return hash_name()
