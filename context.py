"""
Chronicle — Context Engine plugin (Hermes context-engine slot).

Working memory: owns the live window. Compression is memory-aware (§13): rescue
critical spans, score, evict ONLY spans that are durable events (I17), re-retrieve
long-term memory toward the focus topic, and emit a `compressed` audit event.
Directives / always_inject spans are never evicted. Standalone (no provider) it
degrades to a competent token+recency+salience compressor (§13.4).
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
import threading
import time
from contextlib import nullcontext
from pathlib import Path
from typing import Any

try:  # real Hermes base when present …
    from agent.context_engine import ContextEngine  # type: ignore
except Exception:  # … else a local stand-in (plugin-package or top-level)
    try:
        from ._base import ContextEngine
    except Exception:  # pragma: no cover
        from _base import ContextEngine

try:  # real per-span token accounting (§27 embeddings.max_input_tokens) …
    from .engine.embeddings import COMPRESSION_BUDGET, budget_chars, estimate_tokens  # type: ignore
except Exception:  # … else top-level layout (plugin-package vs. flat checkout)
    try:
        from engine.embeddings import COMPRESSION_BUDGET, budget_chars, estimate_tokens
    except Exception:  # pragma: no cover
        # A10b: this branch keeps NO chars/token number of its own. A10's
        # fallback mirrored `_CHARS_PER_TOKEN = 3` here, which is the exact
        # shape of the defect this file keeps closing -- a second ratio, locally
        # reasonable, that nothing ever compares against the first, and that
        # silently goes stale the moment the real one is restated (as it just
        # was). There is no honest chars/token constant to keep in a module that
        # cannot import the estimator, so this keeps none: the import still
        # SUCCEEDS, because the degraded mode a checkout without
        # engine.embeddings can still offer is `_heuristic` (message-count
        # compression, which counts no tokens at all), and any path that would
        # instead have budgeted against a private ratio now fails loudly.
        COMPRESSION_BUDGET = None

        def _no_estimator(*_args, **_kwargs):
            raise RuntimeError(
                "engine.embeddings is unavailable: token budgeting requires the one "
                "shared estimator (chronicle A10b). The supported degraded mode is "
                "the heuristic, token-free compressor, not a second chars/token ratio.")

        estimate_tokens = budget_chars = _no_estimator

try:  # one rule for the TEXT of a message, shared with capture …
    from .engine.speaker import message_text  # type: ignore
except Exception:  # … else top-level layout (plugin-package vs. flat checkout)
    try:
        from engine.speaker import message_text
    except Exception:  # pragma: no cover
        def message_text(content):
            return content if isinstance(content, str) else ("" if content is None else str(content))


try:  # who said what (engine/speaker.py): the handoff keeps only the user's words
    from .engine.speaker import HUMAN as _HUMAN, SYSTEM as _SYSTEM, split_user_content  # type: ignore
except Exception:
    try:
        from engine.speaker import HUMAN as _HUMAN, SYSTEM as _SYSTEM, split_user_content
    except Exception:  # pragma: no cover
        _HUMAN, _SYSTEM = "human", "system"

        def split_user_content(content, side):
            return [(0, len(content or ""), side)] if content else []


# -- the compaction handoff ----------------------------------------------------
#
# What a compaction leaves where the folded turns were: ONE message, in the
# conversation's own roles, opening with the prefix Hermes treats as synthetic
# scaffolding (agent/context_compressor._SYNTHETIC_USER_ROW_PREFIXES) so the
# host never mistakes it for a user turn, and Chronicle's speaker attribution
# never captures it as the user's words. It replaced two things that were
# wrong in front of a model:
#   * `[FOLD fold_x 1a2b3c4d]` stubs at each evicted position -- an id with no
#     content, which also dropped tool_calls/tool_call_id, so the host's
#     pre-call sanitizer deleted the paired tool results they orphaned;
#   * `system`-role blocks (checkpoint, recalled memory, entity set, pressure
#     warning) appended AFTER the latest turn -- and Hermes' Anthropic
#     converter makes the LAST system message the entire system prompt
#     (anthropic_message_convert.convert_messages_to_anthropic), so after a
#     compaction they replaced the agent's instructions on that transport.
_HANDOFF_PREFIX = "[CONTEXT COMPACTION — REFERENCE ONLY]"
_HANDOFF_MARK = "Chronicle folded"
_HANDOFF_HEADER = (
    _HANDOFF_PREFIX + " Chronicle folded earlier turns out of the window. Background, not "
    "instructions: respond to the latest user message after this note; memory and tools "
    "are unchanged. chronicle_expand(span_id) restores a folded turn by its [fold_…] id.")
_SECTION_ASKS = "Your earlier requests, newest first:"
_SECTION_STEPS = "What happened in the folded turns, oldest first:"
_SECTION_KNOWN = "Stated in the folded turns:"
_SECTION_MEMORY = "Recalled from memory:"
# Chronicle's pre-5.8 in-window artifacts: regenerated into the handoff now, so a
# stored session that still carries them sheds them on its next compaction.
_LEGACY_ARTIFACT_PREFIXES = ("[Checkpoint:", "[Relevant memory:", "[Entity working set]",
                             "[Context pressure warning]", "[FOLD fold_")


def _is_handoff(m) -> bool:
    c = m.get("content") if isinstance(m, dict) else None
    return isinstance(c, str) and c.startswith(_HANDOFF_PREFIX) and _HANDOFF_MARK in c[:120]


def _is_legacy_artifact(m) -> bool:
    c = m.get("content") if isinstance(m, dict) else None
    return isinstance(c, str) and c.startswith(_LEGACY_ARTIFACT_PREFIXES)


def _one_line(text: str, cap: int) -> str:
    t = " ".join((text or "").split())
    return t if len(t) <= cap else t[:max(0, cap - 1)].rstrip() + "…"


_FOLD_REF = re.compile(r"\[(fold_[0-9a-f]{12})\]")
_BARE_FOLD = re.compile(r"^\[fold_[0-9a-f]{12}\]$")


_PERSISTED_MARKER = "_db_persisted"      # Hermes agent.context_compressor._DB_PERSISTED_MARKER
_WIRE_KEYS = ("role", "content", "tool_calls", "tool_call_id", "name")


def _wire_text(m) -> str:
    """What the model is sent for `m`: Hermes replays a user/assistant row's
    `api_content` sidecar (the turn's text plus the recall block stamped onto
    it) in place of `content`."""
    side = m.get("api_content") if isinstance(m, dict) else None
    if isinstance(side, str) and side and m.get("role") in ("user", "assistant"):
        return side
    return _text(m)


def _wire_cost(m) -> int:
    """Token cost of `m` as sent: its wire text and its tool-call arguments."""
    return estimate_tokens(_wire_text(m), margin=COMPRESSION_BUDGET) + _calls_cost(m)


def _without_sidecar(m):
    """`m` without its api_content sidecar (a copy only when it has one)."""
    if isinstance(m, dict) and "api_content" in m:
        m = dict(m)
        m.pop("api_content", None)
    return m


def _unmarked(m):
    """`m` without the host's persistence marker (a copy only when it has one)."""
    if isinstance(m, dict) and _PERSISTED_MARKER in m:
        m = dict(m)
        m.pop(_PERSISTED_MARKER, None)
    return m


def _same_on_wire(a, b) -> bool:
    """The same message as the model sees it. The host stamps bookkeeping
    keys onto its dicts (the persistence marker after a commit, sidecars on a
    resume), and a settled prefix must not stop matching over one."""
    if a is b:
        return True
    if not (isinstance(a, dict) and isinstance(b, dict)):
        return a == b
    return all(a.get(k) == b.get(k) for k in _WIRE_KEYS)


def _tool_units(pairs: list) -> list:
    """Group `(idx, msg)` pairs into units that must be kept or folded together:
    an assistant message that calls tools plus the tool results answering it,
    and every other message on its own. Folding half a unit orphans the other
    half, and the host's pre-call sanitizer then deletes the result or fakes it."""
    units, i = [], 0
    while i < len(pairs):
        m = pairs[i][1]
        unit = [pairs[i]]
        ids = set()
        if m.get("role") == "assistant":
            for tc in m.get("tool_calls") or []:
                if isinstance(tc, dict) and tc.get("id"):
                    ids.add(tc["id"])
        j = i + 1
        while ids and j < len(pairs) and pairs[j][1].get("role") == "tool" \
                and pairs[j][1].get("tool_call_id") in ids:
            unit.append(pairs[j])
            j += 1
        units.append(unit)
        i = j
    return units


def _calls_cost(m) -> int:
    """Tokens a message's tool_calls add on the wire (0 without any)."""
    calls = m.get("tool_calls") if isinstance(m, dict) else None
    if not calls:
        return 0
    try:
        return estimate_tokens(json.dumps(calls, default=str), margin=COMPRESSION_BUDGET)
    except (TypeError, ValueError):
        return 0


def _text(m) -> str:
    """A message's text for compaction. Content may be a list of parts (a photo
    and its caption); read as a string it crashed compress() with
    `'list' object has no attribute 'strip'`."""
    return message_text(m.get("content")) if isinstance(m, dict) else ""


try:  # content-addressed span ids for FOLD-tier tombstones (§5.2, R4) …
    from .engine.serialize import hash_str  # type: ignore
except Exception:  # … else top-level layout (plugin-package vs. flat checkout)
    try:
        from engine.serialize import hash_str
    except Exception:  # pragma: no cover
        import hashlib as _hashlib

        def hash_str(s):
            """Fallback content hash if engine.serialize is unavailable: still
            deterministic and content-only (no timestamp), which is all a
            tombstone span_id/digest needs."""
            return _hashlib.blake2b((s or "").encode("utf-8"), digest_size=32).hexdigest()

try:  # deterministic, no-model extraction for the checkpoint digest (§R7) …
    from .engine.extraction import HeuristicExtractor  # type: ignore
except Exception:  # … else top-level layout (plugin-package vs. flat checkout)
    try:
        from engine.extraction import HeuristicExtractor
    except Exception:  # pragma: no cover
        HeuristicExtractor = None  # type: ignore

logger = logging.getLogger("chronicle.context_engine")

# §R7: the checkpoint digest is ALWAYS built with the deterministic, regex-only
# HeuristicExtractor -- never engine.extraction.make_extractor(cfg), which would
# hand back the model-backed LLMExtractor if extraction.backend is "llm".
# compress() is on the hot request path; a digest that could silently start
# making network calls is exactly the surprise this ladder keeps fixing. One
# shared, stateless instance: HeuristicExtractor carries no per-call state.
_DIGEST_EXTRACTOR = HeuristicExtractor() if HeuristicExtractor is not None else None

_NEVER_EVICT_KW = ["always", "never", "must not", "do not", "don't", "[directive]"]

_SALIENCE_RX = re.compile(r"\b(important|remember|critical|must)\b", re.IGNORECASE)
_CRITICALITY_RX = re.compile(r"\b(critical|must|urgent|important)\b", re.IGNORECASE)

# Structured focus (§R8). An entity NAME in focus.entities resolves to at most
# this many candidate entity belief_ids (same substring-on-normalized_name rule
# retrieval._graph_seeds uses) -- bounded so a short common name cannot fan out
# into an unbounded scan of the entities table.
_ENTITY_RESOLVE_CAP = 6


def _default_hermes_home() -> str:
    """Real path a caller-omitted hermes_home resolves to (on_session_start's
    default, and compress()'s lazy-init default -- R1).

    "~/.hermes" is a display convention, not a filesystem path: nothing
    downstream (ChronicleCore.get / ChronicleCore.__init__) expands `~`, so
    the literal string was being handed straight to `Path(hermes_home) / ...`
    and silently resolving *relative to the process's cwd* -- a real,
    persistent SQLite store at ./~/.hermes/... wherever the host happened to
    be running from, not the user's actual home. Computed fresh on every call
    (not baked into a parameter default) so it tracks Path.home() rather than
    whatever HOME was set to at import time -- same convention as
    provider.py's `hermes_home or str(Path.home() / ".hermes")`.
    """
    return str(Path.home() / ".hermes")


# Lazy re-init policy. An init failure is a moment, not a verdict: on 2026-08-02
# a concurrent migration held the SQLite write lock for one session start, and
# the heuristic fallback stayed latched for the rest of the process — the
# memory-aware half of the plugin was gone until someone restarted the host.
# So a failed init only decides THIS call; the next compress() retries, with
# exponential backoff and a hard budget per rolling hour so a genuinely broken
# store cannot turn every compression into a core rebuild.
_RETRY_BASE_SEC = 1.0            # delay after the 1st consecutive failure
_RETRY_MAX_SEC = 300.0           # backoff ceiling
_RETRY_MAX_PER_HOUR = 12         # attempts allowed in any rolling hour
_RETRY_WINDOW_SEC = 3600.0


class ChronicleContextEngine(ContextEngine):
    name = "chronicle"

    def __init__(self):
        super().__init__()
        self.core = None
        self._session_id = ""
        self._principal_id = "default"
        self._host_context = {}      # platform, for who is on the user side (engine/speaker.py)
        self.threshold_percent = 0.75
        self.protect_first_n = 3
        self.protect_last_n = 6
        self.max_messages = None     # the host's hygiene_hard_message_limit, when it has one
        # Focus (§R8): self.focus is the structured {topics, entities, task}
        # form; self.focus_topic is the pre-R8 single-string form, kept for any
        # caller that still reads it directly and mirrored from self.focus
        # whenever chronicle_focus sets one (see handle_tool_call).
        self.focus_topic = None
        self.focus = None
        # Two-watermark hysteresis (§R2, context_engine.{high,low}_watermark_percent):
        # HIGH decides a compression pass is due; LOW is the target fraction of
        # the window compress() evicts DOWN TO. Defaults here match config.py's
        # DEFAULTS and are overridden from live config once self.core exists.
        self.high_watermark_percent = 0.75
        self.low_watermark_percent = 0.55
        # The host's own `compression:` settings, read once (see _host_compression).
        self._host_compression_cache: dict | None = None
        # Stable cut-point geometry (§R5): the exact list of messages compress()
        # committed to on its most recent pass (system/head/kept-middle/tail --
        # NOT the ephemeral memory injection, which is always regenerated). As
        # long as the next call's `messages` still starts with this prefix,
        # compress() treats it as SETTLED: never rescored, reordered, or
        # re-evicted. Keeps consecutive outputs a stable, append-only-growing
        # prefix instead of a reshuffled window on every pass.
        self._locked_prefix: list[dict[str, Any]] = []
        # Required class attributes the host expects a context engine to maintain.
        self.last_prompt_tokens = 0
        self.last_completion_tokens = 0
        self.last_total_tokens = 0
        self.threshold_tokens = 0
        self.context_length = 0
        self.compression_count = 0
        # -- pinned message tracking (R3: span-level protection by ID) ------
        self._pinned_content_hashes = set()  # sha256 hashes of pinned message content
        # Messages already handed to capture.rescue() this conversation (I14),
        # by hash. rescue() gives each rescued span a fresh document_id and the
        # event id includes the call's time, so nothing downstream dedupes a
        # repeat: every compaction pass re-captured every important message in
        # the window as a brand-new event. Measured: 60 rescued observations
        # and 30 rescued notes PER PASS on a sixty-message conversation.
        self._rescued_hashes = set()
        # Rolling checkpoint digest (§R7): deterministic, no-model lines built
        # from extraction artifacts over every span compress() has folded out
        # of the window this session. Oldest-first so the cap can trim the
        # front. Reset per session in on_session_start.
        self._checkpoint_lines: list[str] = []
        # The compaction handoff (see _HANDOFF_PREFIX): folded user requests and
        # one line per folded step, oldest first, accumulated over the session.
        self._handoff_asks: list[str] = []
        self._handoff_steps: list[str] = []
        self.last_pass = ""             # "extend" | "rebase", for the last compress()
        # -- pressure warning state (§R9) ----------------------------------
        # Emit an advisory span once per high-watermark crossing so the agent
        # can pin/save before compress() forcibly evicts. Latched ONLY when the
        # warning is actually delivered inside a compress() return value (see
        # the handoff that carries it) -- never on intent alone.
        self._pressure_warning_injected = False  # latched only on actual delivery
        # -- preflight deferral (host contract) ----------------------------
        # Right after a compaction the host's ROUGH whole-context estimate is
        # stale, and acting on it compacts a request that already fits. Set by
        # every compaction, cleared by the next real usage figure.
        self._awaiting_real_usage = False
        self._provider_reports_usage = False
        # Tool-output trim hysteresis: below this many tokens, no trim. A trim
        # rewrites earlier messages and so breaks the provider's prompt cache;
        # after one, the context must regrow before the next.
        self._prune_rearm_tokens = 0
        # -- init resilience state (see _RETRY_* above) ---------------------
        # INVARIANT: `self.core is None` <=> the heuristic fallback is active.
        # Nothing may attach a core it did not finish initializing.
        self._init_started = False       # on_session_start has run at least once
        self._init_args = None           # replayed by a lazy retry
        self._consecutive_failures = 0   # drives the backoff; 0 once healthy
        self._init_attempts = 0          # total, all time
        self._attempt_times = []         # rolling-hour window, for the budget
        self._recoveries = 0             # successful re-inits after a failure
        self._recovered_after = 0        # failures the last recovery came back from
        self._last_error = ""            # last init error, kept after recovery
        self._retry_lock = threading.Lock()

    # -- one copy per agent ---------------------------------------------------
    # The host gives every agent its OWN copy of the registered engine
    # (hermes-agent agent_init._select_context_engine: `copy.deepcopy(candidate)`)
    # so a child's update_model() cannot move the parent's budget. A plain
    # deepcopy of this object fails on `_retry_lock` — "cannot pickle
    # '_thread.lock' object" — and the host then falls back to its BUILT-IN
    # compressor for that agent, with a warning nobody reads. On the production
    # gateway that happened 38 times in one day: Chronicle was configured as the
    # context engine and never once compressed a conversation, while the built-in
    # compressor it fell back to was pointed at a provider with no API key, so
    # the user saw "Shortening the conversation history failed".
    #
    # What a copy must SHARE and what it must OWN:
    #   core         SHARED. It is the process-wide ChronicleCore singleton
    #                (ChronicleCore.get), holding the store, its connections and
    #                the vector index. Copying it would duplicate all of that per
    #                agent — the shape of the June leak that grew the gateway by
    #                ~850 MB/min when this engine was last active.
    #   _retry_lock  FRESH. A lock belongs to one object; a copy gets its own.
    #   the rest     COPIED. Session id, budget counters, the locked prefix,
    #                pinned hashes, the rolling digest: per-agent state, which is
    #                exactly what the host is copying to keep separate.
    # A settled prefix over this share of the target budget is rebased (see
    # compress() step 0), so the window stays bounded over a long session.
    _REBASE_AT = 0.6
    _FOLD_BATCH = 64            # messages archived per transaction

    _SHARED_ON_COPY = ("core",)
    _FRESH_ON_COPY = {"_retry_lock": threading.Lock}

    def __deepcopy__(self, memo):
        import copy as _copy
        cls = type(self)
        new = cls.__new__(cls)
        memo[id(self)] = new
        for key, value in self.__dict__.items():
            if key in self._SHARED_ON_COPY:
                setattr(new, key, value)
            elif key in self._FRESH_ON_COPY:
                setattr(new, key, self._FRESH_ON_COPY[key]())
            else:
                setattr(new, key, _copy.deepcopy(value, memo))
        return new

    # lifecycle
    def on_session_start(self, session_id, *, hermes_home=None, principal_id="default", config=None, **kw):
        # None (not passed / explicitly cleared) resolves to the real home
        # directory here, at call time -- see _default_hermes_home().
        hermes_home = hermes_home or _default_hermes_home()
        self._session_id = session_id
        self._principal_id = principal_id
        self._host_context = {k: str(kw[k]) for k in ("agent_context", "platform") if kw.get(k)}
        self._init_args = {"hermes_home": hermes_home, "config": config}
        self._init_started = True
        self._locked_prefix = []  # §R5: a new session starts with nothing settled
        self._checkpoint_lines = []  # §R7: the rolling digest is scoped to THIS session
        self._handoff_asks, self._handoff_steps = [], []   # the handoff too
        self._pressure_warning_injected = False  # §R9: re-arm for the new session
        self._rescued_hashes = set()  # I14: rescue once per message per conversation
        self._prune_rearm_tokens = 0  # the tool-output trim cycle starts fresh
        self._try_init()
        # One greppable line per session start. Which half of the plugin is live
        # is exactly what went unnoticed for a whole process life on 2026-08-02,
        # so it gets stated every time rather than only when it changes.
        self.log_context_status()

    def _try_init(self) -> bool:
        """One init attempt. Returns True iff the real engine is live afterwards.

        Never raises: standalone degradation must not crash the host.
        """
        args = self._init_args or {"hermes_home": _default_hermes_home(), "config": None}
        self._init_attempts += 1
        self._attempt_times.append(time.time())
        try:
            try:
                from .engine.core import ChronicleCore
            except Exception:
                from engine.core import ChronicleCore
            core = ChronicleCore.get(args["hermes_home"], args["config"])
            core.has_context_engine = True
            if core.cfg.get("curation.drain.background", True):
                core.drain_in_background()     # see provider.initialize
            with self._init_lock_budget(core):
                core.initialize(self._session_id, hermes_home=args["hermes_home"],
                                principal_id=self._principal_id)
        except Exception as e:
            # Drop the core even though ChronicleCore.get() may have handed back a
            # perfectly good WARM singleton: the lock is just as likely to fire
            # INSIDE initialize(), and keeping a half-initialized core attached
            # would report "real engine" while every compress() re-raised
            # OperationalError into the host. `core is None` is the fallback flag.
            was_fallback = self.core is None and self._consecutive_failures > 0
            self.core = None
            self._consecutive_failures += 1
            self._last_error = "%s: %s" % (type(e).__name__, e)
            if not was_fallback:  # log the transition, not every attempt
                logger.warning("Chronicle context engine: init failed, serving heuristic "
                               "fallback until re-init succeeds: %s", e)
            else:
                logger.debug("Chronicle context engine: re-init attempt %d failed: %s",
                             self._consecutive_failures, e)
            return False
        if self._consecutive_failures:
            self._recoveries += 1
            self._recovered_after = self._consecutive_failures
            logger.warning("Chronicle context engine: re-initialized after %d failed "
                           "attempt(s); memory-aware compression active again",
                           self._consecutive_failures)
        self._consecutive_failures = 0
        self.core = core
        self._apply_policy()           # the core's config exists now
        return True

    @staticmethod
    def _init_lock_budget(core):
        """Bound how long initialize() waits on the SQLite write lock.

        The store owns the timeout; a core without one (a stub, a test double)
        just runs unbounded, exactly as before.
        """
        store = getattr(core, "store", None)
        ctx = getattr(store, "init_busy_timeout", None)
        return ctx() if callable(ctx) else nullcontext()

    def _retry_delay(self) -> float:
        """Exponential backoff on consecutive failures, capped at _RETRY_MAX_SEC."""
        n = max(0, min(self._consecutive_failures - 1, 16))
        return min(_RETRY_MAX_SEC, _RETRY_BASE_SEC * (2 ** n))

    def _retry_due_in(self, now=None):
        """Seconds until the next re-init attempt is allowed.

        0.0 = due now, None = not applicable (healthy, never started, or the
        hourly budget is spent).
        """
        if self.core is not None or not self._init_started:
            return None
        now = time.time() if now is None else now
        window = [t for t in self._attempt_times if now - t < _RETRY_WINDOW_SEC]
        self._attempt_times = window
        if len(window) >= _RETRY_MAX_PER_HOUR:
            return None
        if not window:
            return 0.0
        return max(0.0, self._retry_delay() - (now - window[-1]))

    def _maybe_retry_init(self):
        """Re-init if one is due. Serialized: concurrent compress() calls must
        not each build their own core while the first one is still trying."""
        if self._retry_due_in() != 0.0:
            return
        if not self._retry_lock.acquire(False):
            return  # another thread is already on it; this call falls back
        try:
            if self._retry_due_in() == 0.0:
                self._try_init()
        finally:
            self._retry_lock.release()

    def _lazy_init_if_never_started(self):
        """compress() reached with no explicit on_session_start (a bare
        standalone instance, or a host that skipped the lifecycle hook):
        give it the SAME real init on_session_start would have run, with
        on_session_start's own defaults (R1). Without this, skipping
        on_session_start is a PERMANENT downgrade to the lossy _heuristic()
        path with no durability precondition and no audit event -- the
        fail-forever latch this ladder removes, just triggered by "never
        started" rather than "started, then failed". Once this first
        attempt has run, any further failures fall through to the same
        throttled _maybe_retry_init() path on subsequent calls.

        Serialized through the same `_retry_lock` `_maybe_retry_init` uses:
        non-blocking acquire, so concurrent first-touch compress() calls
        can't each race past the `_init_started` check and build their own
        core -- one thread does the real init, the rest fall back to
        _heuristic() for just this call and pick up the now-live core on
        their next one.
        """
        if not self._retry_lock.acquire(False):
            return  # another thread is already performing the first init
        try:
            if self._init_started:
                return  # lost the race; the other thread already handled it
            self._init_args = self._init_args or {"hermes_home": _default_hermes_home(), "config": None}
            self._init_started = True
            self._try_init()
        finally:
            self._retry_lock.release()

    def on_session_end(self, session_id, messages):
        if self.core:
            self.core.capture.finalize_session(session_id, "clean_exit")

    def on_session_reset(self):
        """`/new` or `/reset`: forget everything that belonged to the old conversation.

        The host's default only zeroes the token counters. This engine also
        keeps per-conversation state, and every piece of it describes messages
        that no longer exist after a reset:

          _locked_prefix   the cut-point geometry compress() committed to (§R5).
                           Left in place, the NEW conversation's messages are
                           compared against the OLD one's prefix;
          _checkpoint_lines the rolling digest of what was folded out (§R7) —
                           a summary of a conversation the user just discarded;
          _pinned_content_hashes  spans the user pinned in that conversation;
          _rescued_hashes  what compress() already rescued (I14) — a new
                           conversation that repeats a message must rescue it;
          focus            what that conversation was about (chronicle_focus);
          _pressure_warning_injected  latched for a crossing that is over.

        The same things on_session_start clears, for the same reason. The
        core is NOT touched — it is the process-wide store, not conversation
        state — and nothing is written: the host calls on_session_end for the
        boundary, and that is where the old session is finalized."""
        super().on_session_reset()
        self._locked_prefix = []
        self._checkpoint_lines = []
        self._handoff_asks, self._handoff_steps = [], []
        self._pinned_content_hashes = set()
        self._rescued_hashes = set()
        self._pressure_warning_injected = False
        self.focus = None
        self.focus_topic = None
        self._awaiting_real_usage = False
        self._provider_reports_usage = False
        self._prune_rearm_tokens = 0

    def update_model(self, model, context_length, base_url="", api_key="", provider="", api_mode=""):
        self.context_length = context_length
        # HIGH watermark (§R2): the fraction of the window that decides a
        # compression pass is due. Computed here and again once the core exists
        # (_apply_policy), so threshold_tokens (read directly by get_status()/
        # the host) can never disagree with what should_compress() tests.
        self._apply_policy()

    def _host_compression(self) -> dict:
        """The host's own `compression:` settings ({} outside Hermes).

        The host never hands its compaction policy to a plugin engine
        (hermes-agent agent_init: "External engines own compaction policy -- the
        host threshold ... never reaches the plugin"), so an engine that is to
        honour the operator's settings has to read them. Before this, Chronicle
        compacted at 75% of the window and down to 55% whatever the operator
        configured -- on the production profile `threshold: 0.5, target_ratio:
        0.15, protect_last_n: 20`, which Hermes' own compressor lands at ~10-15%
        of the window."""
        if self._host_compression_cache is None:
            try:
                from hermes_cli.config import load_config
                c = (load_config() or {}).get("compression") or {}
                self._host_compression_cache = dict(c) if isinstance(c, dict) else {}
            except Exception:
                self._host_compression_cache = {}
        return self._host_compression_cache

    def _apply_policy(self) -> None:
        """Resolve the watermarks and protected head/tail, in this order: what
        Chronicle's own config STATES (context_engine.*), then the host's
        `compression:` settings, then Chronicle's defaults.

        HIGH is the host's `threshold`. LOW -- what a pass compacts DOWN to --
        is twice `threshold * target_ratio`: Hermes' compressor keeps a verbatim
        tail of `threshold * target_ratio` of the window plus a summary, and
        Chronicle's handoff and kept middle stand where that summary stands.
        Recomputed whenever the model or the core changes: the host calls
        update_model() BEFORE on_session_start(), so the core's config did not
        exist yet the first time, and nothing ever re-read it."""
        cfg = self.core.cfg if self.core else None

        def frac(v):
            try:
                v = float(v)
            except (TypeError, ValueError):
                return None
            return v if 0.0 < v < 1.0 else None

        def count(v, lo):
            try:
                v = int(v)
            except (TypeError, ValueError):
                return None
            return v if v >= lo else None

        host = self._host_compression()
        stated_high = frac(cfg.explicit("context_engine.high_watermark_percent")) if cfg else None
        stated_low = frac(cfg.explicit("context_engine.low_watermark_percent")) if cfg else None
        host_high, host_ratio = frac(host.get("threshold")), frac(host.get("target_ratio"))
        default_high = frac(cfg.get("context_engine.high_watermark_percent", 0.75)) if cfg else None
        default_low = frac(cfg.get("context_engine.low_watermark_percent", 0.55)) if cfg else None
        high = stated_high or host_high or default_high or self.high_watermark_percent
        if stated_low:
            low = stated_low
        elif host_high and host_ratio:
            low = max(0.05, 2 * high * host_ratio)
        else:
            low = default_low or self.low_watermark_percent
        self.high_watermark_percent = high
        self.low_watermark_percent = min(low, 0.9 * high)
        first, last = count(host.get("protect_first_n"), 0), count(host.get("protect_last_n"), 1)
        if first is not None:
            self.protect_first_n = first
        if last is not None:
            self.protect_last_n = last
        # The gateway also compacts on message COUNT (hygiene_hard_message_limit),
        # whatever the tokens -- and when that compaction makes no progress it
        # cuts the model's input to the newest `limit` messages, head and all,
        # with no handoff. So a pass over the count folds down under it too.
        self.max_messages = count(host.get("hygiene_hard_message_limit"), 20)
        self.threshold_percent = high
        self.threshold_tokens = int(self.context_length * high) if self.context_length > 0 else 0

    def update_from_response(self, usage):
        if (usage or {}).get("prompt_tokens"):
            # The provider has now measured the request we sent after the
            # compaction: the estimate no longer has to be second-guessed.
            self._awaiting_real_usage = False
            self._provider_reports_usage = True
        self.last_prompt_tokens = usage.get("prompt_tokens", 0)
        self.last_completion_tokens = usage.get("completion_tokens", 0)
        self.last_total_tokens = usage.get("total_tokens", 0)
        # Re-arm the pressure warning once we drop back below the high watermark
        # (§R9), so a later crossing can warn again.
        if not self.is_under_pressure():
            self._pressure_warning_injected = False

    def is_under_pressure(self, prompt_tokens=None) -> bool:
        """Context window at or above the high watermark (§R9).

        True once prompt tokens cross the high watermark -- compression will
        run soon or is in progress. Enables proactive signaling to the agent.
        """
        pt = prompt_tokens if prompt_tokens is not None else self.last_prompt_tokens
        if self.context_length <= 0:
            return False
        return pt >= self.threshold_tokens

    def should_compress(self, prompt_tokens=None) -> bool:
        pt = prompt_tokens if prompt_tokens is not None else self.last_prompt_tokens
        if self.context_length <= 0:
            return False
        return pt > self.threshold_tokens

    # compression (§13.2)
    def compress(self, messages, current_tokens=None, focus_topic=None, focus=None,
                 force=False, **kwargs) -> list[dict[str, Any]]:
        # Structured focus (§R8): `focus` (dict or string) wins if given, then
        # the pre-R8 `focus_topic` string kwarg, then whatever chronicle_focus
        # last set. _normalize_focus turns any of those into one shape so the
        # rest of compress() never branches on which one it got.
        raw_focus = focus if focus is not None else (
            focus_topic if focus_topic is not None else self.focus)
        focus = self._normalize_focus(raw_focus)
        if self.core is None:
            if self._init_started:
                self._maybe_retry_init()   # a busy moment at start-up must not be permanent
            else:
                self._lazy_init_if_never_started()  # never-started fail-forever latch (R1)
        if not self.core:
            return self._heuristic(messages)

        original = messages
        budget = self._target_budget()
        # 0) EXTEND or REBASE. Normally a pass only folds what arrived since the
        # last one: everything already settled -- earlier handoffs included --
        # is reproduced byte for byte (§R5), so the provider's prompt cache
        # keeps the whole prefix. But a settled prefix only ever grows, and
        # once it is most of the budget there is nothing left to keep new turns
        # in. Then (and on a first pass, and after a restart, when this engine
        # copy has no settled prefix) the pass REBASES: every earlier handoff
        # and pre-5.8 artifact comes out, everything after the protected head is
        # fresh again, and ONE consolidated handoff replaces them -- one cache
        # break, which is what Hermes' own compressor pays on every compaction.
        locked_len = self._match_locked_prefix(messages)
        used_locked = sum(self._msg_cost(m) for m in messages[:locked_len])
        # Over the host's message limit, the pass also folds down to half of it.
        over_count = bool(self.max_messages) and len(messages) >= self.max_messages
        count_cap = (max(self.protect_first_n + self.protect_last_n + 2, self.max_messages // 2)
                     if over_count else None)
        rebase = (locked_len == 0 or used_locked > self._REBASE_AT * budget
                  or (count_cap is not None and locked_len > self._REBASE_AT * count_cap))
        if rebase:
            prior = [m for m in messages if _is_handoff(m)]
            if prior and not (self._handoff_asks or self._handoff_steps or self._checkpoint_lines):
                for h in prior:                      # a restart must not lose earlier folds
                    self._adopt_handoff(h.get("content") or "")
            messages = [m for m in messages if not (_is_handoff(m) or _is_legacy_artifact(m))]
            locked_len, used_locked = 0, 0
        n_asks, n_steps = len(self._handoff_asks), len(self._handoff_steps)
        known_before = list(self._checkpoint_lines)
        self.last_pass = "rebase" if rebase else "extend"

        # Pressure warning (§R9): a compaction runs AT the high watermark, so the
        # warning cannot come before it; it rides in the handoff instead, as
        # advice for the next one, and is latched only once delivered.
        warn_pending = self.is_under_pressure() and not self._pressure_warning_injected

        # 1) rescue critical/high-salience spans → durable beliefs (I14) —
        # once per message per conversation, not once per compaction pass —
        # and only when nothing else has captured them. With the memory
        # provider live on this same core, every turn was already captured by
        # sync_turn when it ended and will be extracted from that capture;
        # rescue made a second copy and a second extraction of it. Measured on
        # the production store: rescue drafted 19,089 notes and not one of them
        # survived the attribution cleanup. Standalone (no provider), rescue is
        # the only thing that makes these spans durable, so it still runs.
        fresh = [] if self._provider_captures() else [
            m for m in messages if self._rescue_key(m) not in self._rescued_hashes]
        if fresh:
            self.core.capture.rescue(fresh, session_id=self._session_id,
                                     speaker_context=self._host_context)
            self._rescued_hashes.update(self._rescue_key(m) for m in fresh)

        # 1.5) stable cut-point geometry (§R5): the settled prefix found in step
        # 0 is reproduced verbatim, never rescored or reordered, so only what
        # the host appended since is fresh territory.
        locked = list(messages[:locked_len])
        fresh = messages[locked_len:]
        is_first_pass = locked_len == 0

        if is_first_pass:
            body_only = [m for m in fresh if m.get("role") != "system"]
            if len(body_only) <= self.protect_first_n + self.protect_last_n:
                return original

        # Index-tag `fresh` so the decided subset can be re-emitted in its
        # ORIGINAL relative order at the end (§R5: no "system hoist").
        fresh_indexed = list(enumerate(fresh))
        fresh_system = [(i, m) for i, m in fresh_indexed if m.get("role") == "system"]
        units = _tool_units([(i, m) for i, m in fresh_indexed if m.get("role") != "system"])

        # Head and tail are counted in MESSAGES but cut on UNIT boundaries, so a
        # protected tool result never loses the call it answers (or vice versa).
        head_units, rest = [], units
        if is_first_pass:
            n = 0
            while rest and n < self.protect_first_n:
                n += len(rest[0])
                head_units.append(rest[0])
                rest = rest[1:]
        tail_units, n = [], 0
        while rest and n < self.protect_last_n:
            n += len(rest[-1])
            tail_units.insert(0, rest[-1])
            rest = rest[:-1]
        middle_units = rest
        if is_first_pass:
            # The head is kept for how the conversation started, not for the
            # bulk of a tool's output: one 43 KB result in it cost a third of
            # the budget on every call. Longer results are shortened, archived.
            cap = max(500, budget // 20)
            head_units = [[(i, self._cap_tool_result(m, cap)) for i, m in u] for u in head_units]
        head = [p for u in head_units for p in u]
        tail = [p for u in tail_units for p in u]

        # 2) two-watermark hysteresis (§R2): admit best-scoring evictable
        # units, by REAL token cost, only while there is room under the LOW
        # watermark, after reserving room for the handoff that will stand in
        # for whatever is folded.
        fresh_budget = max(0, budget - used_locked)
        needs_fold = over_count or used_locked + sum(self._msg_cost(m) for _i, m in fresh_indexed) > budget
        reserve = self._handoff_reserve(budget) if needs_fold else 0

        # The protected spans themselves may not fit: then the newest turn
        # wins, then the rest of the tail newest first, then the head -- whole
        # tool units or none of one -- and a span shortened to fit says so and
        # stays recoverable.
        fitted, used_req, dropped_req = self._fit_required(
            fresh_system, head_units, tail_units, max(0, fresh_budget - reserve))
        fitted_content = dict(fitted)
        fresh_system = [(i, fitted_content[i]) for i, _m in fresh_system if i in fitted_content]
        head = [(i, fitted_content[i]) for i, _m in head if i in fitted_content]
        tail = [(i, fitted_content[i]) for i, _m in tail if i in fitted_content]
        never_units = [u for u in middle_units if any(self._never_evict(m) for _i, m in u)]
        never_flat = [p for u in never_units for p in u]
        never_budget = max(0, fresh_budget - used_req - reserve)
        fitted_never, used_never, dropped_never = self._fit_within_budget(never_flat, never_budget)
        kept_never = dict(fitted_never)

        used = used_locked + used_req + used_never
        room = budget - reserve
        total = len(middle_units)
        scored = []
        for pos, u in enumerate(middle_units):
            if u in never_units:
                continue
            recency = pos / max(1, total - 1) if total > 1 else 1.0
            score = max(self._keep_score(m, focus, recency) for _i, m in u)
            scored.append((score, pos))
        scored.sort(key=lambda pair: pair[0], reverse=True)  # best first; ties keep order
        kept_units = set()
        n_kept = len(locked) + len(fresh_system) + len(head) + len(tail) + len(kept_never) + 1
        for _score, pos in scored:
            cost = sum(self._msg_cost(m) for _i, m in middle_units[pos])
            size = len(middle_units[pos])
            if used + cost <= room and (count_cap is None or n_kept + size <= count_cap):
                kept_units.add(pos)
                used += cost
                n_kept += size

        # 3) fold every unit that did not fit -- durable first (I17), then a
        # `folded` event per message (R4, recoverable with chronicle_expand) --
        # and describe it for the handoff. Required spans dropped for budget
        # are folded the same way.
        durable_evicted, evicted_span_ids = [], []
        folded_units = [middle_units[pos] for pos in range(total)
                        if pos not in kept_units and middle_units[pos] not in never_units]
        dropped_units = _tool_units(sorted(list(dropped_req) + list(dropped_never),
                                           key=lambda pair: pair[0]))
        # Noted in conversation order: the handoff lists requests newest first.
        # Written in batches of ~64 messages, each one transaction: a commit per
        # archived message was most of a large pass's time.
        batches, size = [[]], 0
        for u in sorted(folded_units + dropped_units, key=lambda unit: unit[0][0]):
            if size >= self._FOLD_BATCH:
                batches.append([])
                size = 0
            batches[-1].append(u)
            size += len(u)
        for batch in batches:
            with self.core.store.transaction():
                for u in batch:
                    ids = []
                    for _i, m in u:
                        if not _text(m):         # a bare call: nothing to restore
                            ids.append(None)
                            durable_evicted.append(m)
                            continue
                        chunk_ids = self._ensure_durable(m)
                        span_id, _digest, _stub = self._fold(m, chunk_ids)
                        ids.append(span_id)
                        durable_evicted.append(m)
                    evicted_span_ids.extend(i for i in ids if i)
                    self._note_folded_unit([m for _i, m in u], ids)

        kept_middle = [p for pos, u in enumerate(middle_units) if pos in kept_units for p in u]
        kept_middle += [(i, kept_never[i]) for i, _m in never_flat if i in kept_never]
        decided = sorted(fresh_system + head + kept_middle + tail, key=lambda pair: pair[0])
        settled = [m for _idx, m in decided]
        result = locked + settled

        # 4) the handoff: the folded requests, steps and stated facts, plus
        # memory re-retrieved toward the focus (§R8), in whatever room is left.
        # The checkpoint digest (§R7) is fed only the USER's words: a regex
        # extractor handed an assistant's or a tool's text reads it as the user.
        self._update_checkpoint_digest(
            [{"role": "user", "content": t} for t in self._human_texts(durable_evicted)])
        extra = [t for t in [self._host_memory_text(kwargs.get("memory_context"))] if t]
        if focus["topics"] or focus["entities"] or focus["task"]:
            inject_budget = self._reinject_budget(max(0, budget - used) // 3)
            if inject_budget > 0:
                spans, _ = self._rehydrate_working_set(focus, inject_budget, 0)
                extra += [sp.get("content") or "" for sp in spans]
        if rebase:
            asks, steps, known = self._handoff_asks, self._handoff_steps, self._checkpoint_lines
        else:
            asks, steps = self._handoff_asks[n_asks:], self._handoff_steps[n_steps:]
            known = [line for line in self._checkpoint_lines if line not in known_before]
        # An "[episode]" digest line is a user request restated -- the handoff
        # already quotes every folded request -- so only facts, entities and
        # directives go under "Stated".
        known = [line for line in known if not line.startswith("[episode] ")]
        handoff = None
        if asks or steps or known or extra:
            warn = None
            if warn_pending:
                warn = ("The window was at %d%% of the model's context when this compaction "
                        "ran; pin anything that must stay verbatim with chronicle_pin_context."
                        % int(100 * (current_tokens or self.last_prompt_tokens)
                              / max(1, self.context_length)))
            text = self._render_handoff(max(0, budget - used), asks, steps, known, extra, warn)
            if text:
                handoff = text
                used += self._msg_cost({"content": text})
                if warn and warn in text:
                    self._pressure_warning_injected = True

        # 5) audit event (§R6/R4)
        kept_span_ids = [self._span_id(m) for m in result]
        self.core.capture.append("compressed", {
            "session_id": self._session_id,
            "evicted_spans": evicted_span_ids, "kept_spans": kept_span_ids,
            "folded_spans": evicted_span_ids, "folded_in_window": 0,
            "evicted_count": len(evicted_span_ids), "retained": len(kept_span_ids),
            "summary_ref": "", "budget_tokens": budget, "used_tokens": used,
            "handoff_chars": len(handoff or ""), "mode": self.last_pass},
            actor="system", session_id=self._session_id)

        self.compression_count += 1
        logger.info("chronicle compaction: session=%s mode=%s messages %d->%d folded=%d "
                    "used=%d/%d tokens handoff=%d chars",
                    self._session_id, self.last_pass, len(original), len(result) + (handoff is not None),
                    len(evicted_span_ids), used, budget, len(handoff or ""))
        self._awaiting_real_usage = True
        self._prune_rearm_tokens = 0     # a compaction starts the trim cycle again
        if handoff is not None:
            # Where the folded turns were: after the protected head on a rebase,
            # at the end of the settled prefix when extending.
            pos = self._handoff_position(result, head) if rebase else len(locked)
            result = result[:pos] + [{"role": self._handoff_role(result, pos),
                                      "content": handoff}] + result[pos:]
        # Hermes' persistence marker must not leave a compaction: the host's
        # invariant is that no assembled message carries it (a leaked one makes
        # a rotation flush skip the row), its own compressor sweeps it off its
        # output, and it stamps the committed rows itself afterwards. (Its
        # child-session insert writes every row today, so this is the
        # invariant kept, not a loss observed.)
        result = [_unmarked(m) for m in result]
        # §R5: lock in everything just decided, the handoff with it -- the next
        # pass extends this output byte for byte, or rebases it whole.
        self._locked_prefix = result
        return result

    # -- handoff state ------------------------------------------------------

    @staticmethod
    def _handoff_position(result, head) -> int:
        """Where the handoff goes on a rebase: right after the protected head
        -- where the folded turns were -- or, when the head itself had to be
        folded for budget, after the leading system messages, ahead of every
        turn that was kept."""
        if head:
            last = head[-1][1]
            for i, m in enumerate(result):
                if m is last:
                    return i + 1
        i = 0
        while i < len(result) and result[i].get("role") == "system":
            i += 1
        return i

    @staticmethod
    def _handoff_role(result, pos) -> str:
        """The handoff's role at `pos`: "user" when it opens the conversation
        (Anthropic requires it) or follows the assistant; "assistant" after a
        user turn. Tool rows answer the assistant's call, so they count as the
        assistant's side."""
        prev = next((m.get("role") for m in reversed(result[:pos])
                     if m.get("role") in ("user", "assistant", "tool")), None)
        return "assistant" if prev == "user" else "user"

    def _msg_cost(self, m) -> int:
        """Token cost of a message as sent: its text AND its tool-call
        arguments, which _text() alone leaves out."""
        return _wire_cost(m)

    def _handoff_reserve(self, budget: int) -> int:
        """Room kept back for the handoff before the scored middle is admitted:
        a fifth of the target, and at least the header plus a few lines -- but
        never more than half the target, nor more than 6000 tokens."""
        floor = self._msg_cost({"content": _HANDOFF_HEADER}) + 64
        return min(budget // 2, 6000, max(floor, int(budget * 0.2)))

    @staticmethod
    def _host_memory_text(memory_context) -> str:
        """What the host's other memory providers said before this compaction
        (`on_pre_compress`), for the handoff -- run through the host's own
        redaction and size cap when it is there, capped here when not."""
        text = (memory_context or "").strip() if isinstance(memory_context, str) else ""
        if not text:
            return ""
        try:
            from agent.context_engine import sanitize_memory_context
            return sanitize_memory_context(text)
        except Exception:
            return text[:2000]

    @staticmethod
    def _human_texts(msgs) -> list:
        """The user's own words in `msgs`: user-role text minus host framing."""
        out = []
        for m in msgs:
            if m.get("role") != "user":
                continue
            c = _text(m)
            said = "".join(c[a:b] for a, b, w in split_user_content(c, _HUMAN) if w == _HUMAN).strip()
            if said:
                out.append(said)
        return out

    def _note_folded_unit(self, msgs, span_ids) -> None:
        """Record one folded unit for the handoff: a user request verbatim
        (its framing removed), or one line saying what the step did."""
        # The unit is named by a span that has content to restore -- a call
        # with no text of its own hashes like every other one -- preferring
        # the first result, which is what a later chronicle_expand wants.
        named = [sid for m, sid in zip(msgs, span_ids) if sid and _text(m)]
        results = [sid for m, sid in zip(msgs, span_ids) if sid and _text(m) and m.get("role") == "tool"]
        pick = (results or named or list(span_ids) or [None])[0]
        ref = "[%s]" % pick if pick else ""
        if len(msgs) == 1 and msgs[0].get("role") == "user":
            said = self._human_texts(msgs)
            if said:
                self._handoff_asks.append("%s %s" % (ref, said[0]))
            return
        first = msgs[0]
        if first.get("role") == "assistant" and first.get("tool_calls"):
            calls = []
            for tc in first.get("tool_calls") or []:
                fn = (tc.get("function") or {}) if isinstance(tc, dict) else {}
                calls.append("%s(%s)" % (fn.get("name") or "tool", _one_line(fn.get("arguments") or "", 70)))
            said = _one_line(_text(first), 120)
            results = [_one_line(_text(r), 110) for r in msgs[1:]]
            line = "called " + ", ".join(calls)
            if said:
                line = _one_line(said, 120) + " — " + line
            if results:
                line += " → " + " | ".join(r for r in results if r)
            self._handoff_steps.append("%s %s" % (ref, _one_line(line, 360)))
            return
        role = first.get("role") or "?"
        body = _one_line(_text(first), 220)
        if body:
            self._handoff_steps.append("%s %s: %s" % (ref, role, body))

    def _render_handoff(self, room: int, asks_in: list, steps_in: list, known_in: list,
                        extra: list, warn) -> str:
        """The handoff text within `room` tokens: the header always; then the
        user's folded requests (newest first), the steps (the most recent that
        fit, shown oldest first), the stated facts, memory recalled for the
        focus, and last the ids of whatever there was no room to show.

        Entries are deduplicated (identical turns fold to the same id), and each
        section gets a share of the room -- requests half, steps three tenths,
        facts a fifth -- before any may spend what another left unused: a greedy
        fill let a run of long requests crowd out every stated fact. Recalled
        memory keeps up to a third of the room. "" when not even the header
        fits."""
        header = _HANDOFF_HEADER + ("\n" + warn if warn else "")
        if self._msg_cost({"content": header}) > room:
            return ""

        def dedupe(lines):
            seen, out = set(), []
            for line in reversed(lines):             # keep the most recent occurrence
                if line not in seen:
                    seen.add(line)
                    out.append(line)
            return list(reversed(out))

        spec = (("asks", _SECTION_ASKS, 0.5, True, True),     # key, title, share, shorten, newest first
                ("steps", _SECTION_STEPS, 0.3, False, False),
                ("known", _SECTION_KNOWN, 0.2, False, False))
        pools = {k: dedupe(v) for k, v in (("asks", asks_in), ("steps", steps_in), ("known", known_in))}
        shown = {k: [e for e in pools[k] if not _BARE_FOLD.match(e)] for k in pools}
        chosen = {k: [] for k in pools}          # oldest first, like the pools
        memory = [b for b in extra if b]
        ids = {k: [] for k in pools}             # ids of what is not shown, newest first

        def render(with_memory=None):
            parts = [header]
            for key, title, _share, _shorten, newest_first in spec:
                lines = ["- " + e for e in chosen[key]]
                if newest_first:
                    lines.reverse()
                if ids[key]:
                    lines.append("- older, not shown: " + " ".join("[%s]" % i for i in ids[key]))
                if lines:
                    parts.append("\n".join([title] + lines))
            for block in (memory if with_memory is None else with_memory):
                parts.append("\n".join([_SECTION_MEMORY, block]))
            return "\n\n".join(parts)

        def cost(**kw):
            return self._msg_cost({"content": render(**kw)})

        # Recalled memory first claims up to a third of the room.
        kept_memory = []
        for block in memory:
            if cost(with_memory=kept_memory + [block]) <= self._msg_cost({"content": header}) + room // 3:
                kept_memory.append(block)
        memory_cost = cost(with_memory=kept_memory) - cost(with_memory=[])
        entry_room = room - memory_cost
        base = cost(with_memory=[])

        def fill(key, cap, shorten):
            pool = shown[key]
            start = len(pool) - len(chosen[key])
            for line in reversed(pool[:start]):
                for width in ((1200, 240, 90) if shorten else (400,)):
                    before = cost(with_memory=[])
                    chosen[key].insert(0, _one_line(line, width))
                    delta = cost(with_memory=[]) - before
                    if delta <= cap:
                        cap -= delta
                        break
                    chosen[key].pop(0)
                else:
                    break
            return cap

        def fill_all(avail):
            for key in chosen:
                chosen[key] = []
            left = sum(fill(key, int(avail * share), shorten) for key, _t, share, shorten, _n in spec)
            for key, _t, _share, shorten, _n in spec:
                left = fill(key, left, shorten)

        avail = max(0, entry_room - base)
        fill_all(avail)
        if any(len(chosen[k]) < len(shown[k]) for k in chosen):
            fill_all(int(avail * 0.88))          # something is left out: keep room to name it
        memory[:] = kept_memory

        # Last, name by id as many of the rest as still fit, newest first.
        for key, *_ in spec:
            shown_ids = {m.group(1) for e in chosen[key] for m in [_FOLD_REF.match(e)] if m}
            rest = []
            for e in reversed(pools[key]):
                m = _FOLD_REF.match(e)
                if m and m.group(1) not in shown_ids and m.group(1) not in rest:
                    rest.append(m.group(1))
            for fid in rest:
                ids[key].append(fid)
                if cost() > room:
                    ids[key].pop()
                    break
            ids[key].reverse()                   # rendered oldest first
        return render()

    def _adopt_handoff(self, text: str) -> None:
        """Carry a handoff this engine copy did not write back into its state
        (a restarted process, a fresh per-agent copy), so the next one keeps it."""
        found = {"asks": [], "steps": [], "known": [], None: []}
        older = {"asks": [], "steps": [], "known": [], None: []}
        section = None
        for line in (text or "").splitlines():
            if line == _SECTION_ASKS:
                section = "asks"
            elif line == _SECTION_STEPS:
                section = "steps"
            elif line == _SECTION_KNOWN:
                section = "known"
            elif line == _SECTION_MEMORY:
                section = None                     # regenerated per pass, not carried
            elif line.startswith("- older, not shown:"):
                # Kept as bare ids: never shown as entries, but still named.
                older[section] = ["[%s]" % i for i in re.findall(r"fold_[0-9a-f]{12}", line)]
            elif line.startswith("- ") and section is not None:
                found[section].append(line[2:])
        # Stored oldest first: the older ids, then the entries (asks are
        # rendered newest first).
        self._handoff_asks.extend(older["asks"] + list(reversed(found["asks"])))
        self._handoff_steps.extend(older["steps"] + found["steps"])
        self._checkpoint_lines.extend(found["known"])

    def _match_locked_prefix(self, messages) -> int:
        """How many of the leading `messages` are identical, in order, to the
        settled prefix compress() locked in last pass (§R5).

        That many messages are guaranteed untouched this pass -- not rescored,
        reordered, or re-evicted -- so compress() only grows a stable prefix
        instead of reshuffling it. Falls back to 0 (whole window is fresh)
        whenever the input no longer starts with what was locked: a new
        session, the first pass, or a host-side history edit.
        """
        locked = self._locked_prefix
        n = min(len(locked), len(messages))
        k = 0
        while k < n and _same_on_wire(messages[k], locked[k]):
            k += 1
        return k

    def _provider_captures(self) -> bool:
        """Is the memory provider live on this same core? Then every turn is
        captured by its sync_turn and extracted from that capture, and anything
        this engine writes is a second copy. Read at call time: a process where
        the provider has not started yet (a subagent, standalone use) keeps the
        engine's own capture, which is the safe side to err on."""
        return bool(self.core is not None and getattr(self.core, "has_memory_provider", False))

    @staticmethod
    def _rescue_key(m) -> str:
        """Identity of a message for rescue: who said it and what they said.
        A hash, so a long conversation costs 64 bytes a message, not its text."""
        role = str(m.get("role") or "")
        content = m.get("content")
        if not isinstance(content, str):
            content = json.dumps(content, sort_keys=True, default=str)
        return hashlib.sha256(("%s\x00%s" % (role, content)).encode("utf-8")).hexdigest()

    def _keep_score(self, m, focus, recency_position=1.0):
        """Unified scorer (R3 + R8): the one place a keep/evict score is computed,
        reading the one weight set (context_engine.keep_weights — see config.py).

        `focus` is the normalized {topics, entities, task} dict (§R8): a span
        earns the relevance bump if it mentions ANY facet -- any topic, the
        task, or any focus entity's name -- the same one-hit-scores rule the
        pre-R8 single-string focus used, checked against every facet.

        Dimensions:
        - recency: position-based score (0.0=old, 1.0=recent), NOT a constant.
          Defaults to 1.0 so a bare _keep_score(m, focus) call (no position
          context) still scores the recency baseline, not zero.
        - relevance: any focus facet match
        - salience: high-value keywords
        - criticality: urgent/must-do signals

        Pinning is deliberately NOT a dimension: a pinned span is hard-protected
        in _never_evict() and never reaches this method.

        Returns score in [0.0, 1.0].
        """
        w = self.core.cfg.get("context_engine.keep_weights", {}) if self.core else {}
        content = _text(m).lower()

        # Base score from recency (newer messages score higher)
        score = recency_position * w.get("recency", 0.20)

        # Relevance: any focus facet (topic, task, or entity name) matches
        focus = focus if isinstance(focus, dict) else self._normalize_focus(focus)
        facets = list(focus.get("topics") or [])
        if focus.get("task"):
            facets.append(focus["task"])
        facets += list(focus.get("entities") or [])
        if any(f and f.lower() in content for f in facets):
            score += w.get("relevance", 0.35)

        # Salience: pre-compiled keyword match
        if _SALIENCE_RX.search(content):
            score += w.get("salience", 0.20)

        # Criticality: pre-compiled keyword match
        if _CRITICALITY_RX.search(content):
            score += w.get("criticality", 0.20)

        return min(1.0, score)  # Clamp to [0.0, 1.0]

    @staticmethod
    def _normalize_focus(focus) -> dict:
        """Any pre-R8 or R8 focus shape -> {"topics": [...], "entities": [...],
        "task": str|None} (§R8).

        None -> empty focus. A bare string (the entire pre-R8 call shape)
        becomes the `task` facet: what get_context used to be queried with and
        what _keep_score's old `focus.lower() in content` check tested. A dict
        may give topics/entities as a list OR a single string; unknown/empty
        input degrades to the empty focus rather than raising.
        """
        empty = {"topics": [], "entities": [], "task": None}
        if not focus:
            return empty
        if isinstance(focus, str):
            s = focus.strip()
            return {"topics": [], "entities": [], "task": s} if s else empty
        if isinstance(focus, dict):
            def _as_list(v):
                if not v:
                    return []
                items = v if isinstance(v, (list, tuple, set)) else [v]
                return [str(x).strip() for x in items if str(x).strip()]
            topics = _as_list(focus.get("topics") if focus.get("topics") is not None else focus.get("topic"))
            entities = _as_list(focus.get("entities") if focus.get("entities") is not None else focus.get("entity"))
            task = focus.get("task")
            task = task.strip() if isinstance(task, str) and task.strip() else None
            return {"topics": topics, "entities": entities, "task": task}
        s = str(focus).strip()  # defensive: some other truthy type
        return {"topics": [], "entities": [], "task": s} if s else empty

    def _rehydrate_working_set(self, focus, inject_budget, used):
        """§R8 working-set rehydration: re-retrieve per facet instead of one
        query against a flattened focus string, and join focus entities'
        digests directly rather than hoping free-text search surfaces them.

        `inject_budget` is split evenly across whichever facets are present
        (each topic, the task, and -- as one shared slot -- the focus
        entities), so one facet cannot starve the others. A facet is never
        handed more than what's still `remaining`, so the running total only
        shrinks toward zero. Returns (injected_spans, updated_used).
        """
        injected: list[dict] = []
        hints, seen = [], set()
        for topic in focus["topics"]:
            if topic not in seen:
                hints.append(topic)
                seen.add(topic)
        if focus["task"] and focus["task"] not in seen:
            hints.append(focus["task"])
            seen.add(focus["task"])
        entity_ids = self._resolve_entity_ids(focus["entities"]) if focus["entities"] else []

        n_slots = len(hints) + (1 if entity_ids else 0)
        if n_slots == 0:
            return injected, used
        share = max(1, inject_budget // n_slots)
        remaining = inject_budget

        for hint in hints:
            if remaining <= 0:
                break
            facet_budget = min(share, remaining)
            # A10: budget the WRAPPER too. `get_context` now honours its
            # token_budget under the shared estimator, but this span is the
            # context PLUS a `[Relevant memory: …]` header, and the old code
            # asked for `facet_budget` tokens of context, added the header on
            # top, and then hard-cut the result at `remaining * 3` chars --
            # mid-word, through whatever evidence line the slice landed in.
            # Paying for the header up front means the assembled span fits by
            # construction and nothing is ever bisected.
            header = f"[Relevant memory: {hint}]\n"
            body_budget = facet_budget - estimate_tokens(header, margin=COMPRESSION_BUDGET)
            if body_budget <= 0:
                continue
            ctx = self.core.retrieval.get_context(hint, token_budget=body_budget,
                                                  include_directives=False, principal=self._principal_id,
                                                  exclude_automation=True)
            if not ctx:
                continue
            content = header + ctx
            cost = estimate_tokens(content, margin=COMPRESSION_BUDGET)
            if cost > remaining:
                # Whole-unit: a span that does not fit is omitted, not sliced.
                # `facet_budget <= remaining` and the header is already paid
                # for, so this is a guard against an estimator edge, not the
                # normal path.
                continue
            injected.append({"role": "system", "content": content})
            used += cost
            remaining -= cost

        if entity_ids and remaining > 0:
            facet_budget = min(share, remaining)
            lines = self._entity_digest_lines(entity_ids, facet_budget)
            if lines:
                # A10: same treatment -- `_entity_digest_lines` budgets the
                # LINES, the header is extra, so pay for it here and drop a
                # trailing whole line rather than slicing the last digest in
                # half. `lines` is already ordered by entity relevance.
                header = "[Entity working set]\n"
                while lines and estimate_tokens(header + "\n".join(lines), margin=COMPRESSION_BUDGET) > remaining:
                    lines.pop()
                if lines:
                    content = header + "\n".join(lines)
                    injected.append({"role": "system", "content": content})
                    used += estimate_tokens(content, margin=COMPRESSION_BUDGET)

        return injected, used

    def _resolve_entity_ids(self, names) -> list[str]:
        """Focus entity names -> candidate entity belief_ids (§R8).

        Same substring-on-normalized_name rule retrieval._graph_seeds uses, so
        an entity resolved here is the same node the graph channel would seed
        retrieval on. Best-effort: a name matching nothing is dropped, and any
        store error degrades to "no match" rather than failing compress().
        """
        ids: list[str] = []
        if not self.core:
            return ids
        for name in names:
            if len(ids) >= _ENTITY_RESOLVE_CAP:
                break
            norm = (name or "").strip().lower()
            if len(norm) < 2:
                continue
            try:
                rows = self.core.store.query_beliefs(
                    "entities", "normalized_name LIKE ? AND merged_into IS NULL", (f"%{norm}%",), 3)
            except Exception:
                rows = []
            for r in rows:
                bid = r.get("belief_id")
                if bid and bid not in ids:
                    ids.append(bid)
        return ids

    def _entity_digest_lines(self, entity_ids, token_budget) -> list[str]:
        """Focus entities' consolidated digests (§u2), one line each, joining
        the working set directly (§R8). An entity too new/thin to have earned a
        digest yet falls back to its top few facts, so a fresh entity in focus
        still rehydrates SOMETHING rather than silently contributing nothing.
        """
        lines: list[str] = []
        # A10: through the shared inverse, not a hand-written `* 3`;
        # A10b: under this subsystem's own named margin.
        line_budget_chars = budget_chars(token_budget, margin=COMPRESSION_BUDGET)
        used_chars = 0
        for eid in entity_ids:
            try:
                items = self.core.retrieval.ask_about(eid, principal=self._principal_id)
            except Exception:
                items = []
            digest = next((it for it in items if it.get("kind") == "digest" and it.get("digest_line")), None)
            if digest:
                line = "- " + digest["digest_line"]
            else:
                facts = [it for it in items if it.get("kind") != "digest" and it.get("value")][:3]
                if not facts:
                    continue
                rendered = "; ".join(f"{f.get('attribute')}={f.get('value')}" for f in facts if f.get("attribute"))
                if not rendered:
                    continue
                # (A1) The facts above came back ACL-filtered from ask_about;
                # the entity row's display NAME is a separate store read, so it
                # goes through the same choke point rather than riding in on
                # them. An unreadable (or missing) entity renders as its id.
                entity_row = self.core.store.get_belief("entities", eid) or {}
                if entity_row and not self.core.retrieval._readable(
                        entity_row, self._principal_id, "*", None):
                    entity_row = {}
                line = "- {}: {}".format(entity_row.get("name") or eid, rendered)
            if used_chars + len(line) + 1 > line_budget_chars:
                break
            lines.append(line)
            used_chars += len(line) + 1
        return lines

    def _cfg_percent(self, name, default):
        """Read context_engine.<name> (a watermark fraction) from live config.

        Falls back to `default` with no core (standalone/pre-init) or if the
        key is absent, so callers never see None or crash on a bare instance.
        """
        if not self.core:
            return default
        return self.core.cfg.get(f"context_engine.{name}", default)

    def _target_budget(self) -> int:
        """Token budget compress() must not exceed (§R2: LOW watermark).

        A fraction of the model's actual context window, not a constant that
        has nothing to do with which model is configured. If the window size
        is unknown (context_length never set -- standalone use before the
        first update_model call) fall back to context.default_token_budget,
        the same knob get_context already honors, so the target is never
        unbounded.
        """
        low = self.low_watermark_percent
        if self.context_length > 0:
            return max(1, int(self.context_length * low))
        cfg_default = self.core.cfg.get("context.default_token_budget", 1500)
        return max(1, int(cfg_default))

    def _reinject_budget(self, remaining_tokens: int) -> int:
        """Cap the re-retrieved memory injection (§R2).

        Previously a bare `token_budget=500` unrelated to
        context.default_token_budget and to whatever room the rest of the
        pass actually left. Both bounds apply: never more than the config
        default, never more than what's left under the target budget.
        """
        cfg_default = self.core.cfg.get("context.default_token_budget", 1500)
        return max(0, min(int(remaining_tokens), int(cfg_default)))

    @staticmethod
    def _fit_within_budget(items, budget):
        """Fit `items` -- an ordered list of `(idx, msg)` pairs, highest
        priority first -- into `budget` tokens total (§R2: the
        compress()-output-<=-budget guarantee, for the required-but-fresh
        system/head/tail/never-evict set compress() does not otherwise evict
        this pass).

        Earlier entries get first claim; once it's spent, an entry with SOME
        room left is shortened, but an entry with NO room left is no longer
        clipped-to-empty and kept in place -- it is reported back in `dropped`
        (full, untouched content) so the caller can make it durable (I17)
        before omitting it. A protected span is shortened-but-present or
        durably-archived-and-absent; never blanked-but-present (§R5). Entries
        that already fit come back with the same msg object unchanged.

        Returns (kept, used, dropped): `kept` and `dropped` are both lists of
        `(idx, msg)` pairs, so the caller can re-associate survivors and
        casualties back with whichever bucket each `idx` came from.
        """
        kept, dropped, used = [], [], 0
        for idx, m in items:
            content = _text(m)
            cost = _wire_cost(m)
            remaining = budget - used
            if cost <= remaining:
                kept.append((idx, m))
                used += cost
                continue
            bare = _without_sidecar(m)
            if bare is not m and _wire_cost(bare) <= remaining:
                # What goes first is the recall block stamped onto that turn
                # (Hermes' api_content sidecar), not the user's own words.
                kept.append((idx, bare))
                used += _wire_cost(bare)
                continue
            if remaining <= 0:
                dropped.append((idx, m))
                continue
            # A10: the shared inverse of estimate_tokens, so this cannot
            # drift from the estimator the loop above counts with. The SHORTEN
            # (rather than drop) policy here is deliberate and unchanged --
            # §R5 requires a protected span to be shortened-but-present or
            # durably archived, never blanked-but-present, and
            # test_compression_fidelity asserts these bytes.
            clipped = content[:budget_chars(max(0, remaining - _calls_cost(m)),
                                            margin=COMPRESSION_BUDGET)]
            # A shortened message loses its sidecar too: replayed, the sidecar
            # would send the whole original again.
            kept.append((idx, _without_sidecar(dict(m, content=clipped)) if clipped != content else m))
            used += estimate_tokens(clipped, margin=COMPRESSION_BUDGET) + _calls_cost(m)
        return kept, used, dropped

    def _fit_required(self, system, head_units, tail_units, budget):
        """Fit the spans compress() must not score away -- system messages,
        the protected head and tail -- into `budget`, most important first:
        system, the newest unit, the rest of the tail newest first, then the
        head. A tool unit is kept whole (shortened if need be) or dropped
        whole, so no call loses its result. A span shortened to fit is made
        durable and folded first, and ends with the id that restores it.
        Returns (kept, used, dropped) as _fit_within_budget does."""
        kept, dropped, used = [], [], 0
        for unit in [[p] for p in system] + list(reversed(tail_units)) + list(head_units):
            got, cost, lost = self._fit_within_budget(unit, budget - used)
            if lost:
                dropped.extend(unit)
                continue
            used += cost
            for (idx, m), (_i, orig) in zip(got, unit):
                if m is not orig:
                    m = self._mark_clipped(orig, m)
                kept.append((idx, m))
        return kept, used, dropped

    def _cap_tool_result(self, m, cap: int):
        """A tool result over `cap` tokens, shortened (archived first, ending
        with the id that restores it); anything else unchanged."""
        if m.get("role") != "tool" or self._msg_cost(m) <= cap:
            return m
        text = _text(m)
        clipped = dict(m, content=text[:budget_chars(cap, margin=COMPRESSION_BUDGET)])
        return self._mark_clipped(m, clipped)

    def _mark_clipped(self, orig, clipped):
        """A span shortened for budget: archive the whole of it, and end the
        shortened copy with the id that restores it (same length)."""
        span_id, _digest, _stub = self._fold(orig, self._ensure_durable(orig))
        note = " …[shortened; chronicle_expand(\"%s\") restores it]" % span_id
        text = clipped.get("content") or ""
        clipped = _without_sidecar(clipped)
        if len(text) <= len(note):
            return clipped
        return dict(clipped, content=text[:len(text) - len(note)] + note)

    def _compute_content_hash(self, m) -> str:
        """sha256 of a message's content, for span-level pinning (R3).

        Computed every time, never cached ON the message. It used to be stored
        as `m["_content_hash"]`, i.e. written into the host's own message dicts:
        a private key riding along in whatever the host sends the model, and a
        stale-cache hazard — when the host rewrites a message's content in place
        (its own tool-result pruning does) the stored hash no longer matched, so
        a pinned span could lose its protection. A hash of a message costs
        microseconds."""
        content = m.get("content") if isinstance(m, dict) else None
        text = content if isinstance(content, str) else ("" if content is None else
                                                         json.dumps(content, sort_keys=True, default=str))
        return hashlib.sha256(text.encode("utf-8")).hexdigest()

    def _is_pinned(self, m) -> bool:
        """Check if message is pinned by content hash (R3: span-level protection)."""
        return self._compute_content_hash(m) in self._pinned_content_hashes

    def _never_evict(self, m) -> bool:
        """R3: never evict the USER's directives (never/always/must keywords in
        their own words) or a pinned span. The keywords used to be matched in
        any message -- an assistant's "you must restart", a log line saying
        "never" -- so ordinary tool output was pinned in the window."""
        if self._is_pinned(m):
            return True
        said = " ".join(self._human_texts([m])).lower()
        return bool(said) and any(k in said for k in _NEVER_EVICT_KW)

    @staticmethod
    def _span_id(m) -> str:
        """Content-addressed id for a span (§R6), independent of storage.

        Identity is (role, content): the same text from the same speaker gets
        the same id every time, on every pass. That makes kept_spans/
        evicted_spans in the `compressed` audit payload useful for replay -- a
        reader can match a span id back to a message by recomputing this hash.
        """
        try:
            from .engine.serialize import cjson_dumps, hash_str
        except ImportError:
            from engine.serialize import cjson_dumps, hash_str
        key = {"role": m.get("role") or "", "content": m.get("content") or ""}
        return "sp_" + hash_str(cjson_dumps(key))

    def _ensure_durable(self, m) -> list[str]:
        """I17: a span is evicted only if it is (or is first made) a durable event.

        Chunks large spans using the capture chunker so durability is byte-complete
        before eviction (R11), never lossy truncation. Returns the ordered list of
        durable `observed` event ids the span was written as (R4: what a `folded`
        tombstone points back at so chronicle_expand can rehydrate the exact
        bytes). Each chunk is stamped with the span's content-addressed id (§R6).
        """
        span_id = self._span_id(m)
        content = _text(m)
        if len(content) < 1:
            return []
        # Import the chunker from capture (same as observe() uses)
        try:
            from .engine import speaker as spk
            from .engine.capture import _split_excerpt
        except ImportError:
            from engine import speaker as spk
            from engine.capture import _split_excerpt

        # Who wrote this message (engine/speaker.py). The actor is `user` only for
        # a person's own words; a cron prompt or a host control frame in a `user`
        # row is `system`. (CHECK constraint: 'user','agent','curator','system'.)
        role = m.get("role", "system")
        side = spk.user_side(agent_context=self._host_context.get("agent_context", ""),
                             platform=self._host_context.get("platform", ""),
                             session_id=self._session_id)
        who = spk.role_speaker(role, side)
        if who in (spk.HUMAN, spk.AUTOMATION):
            spans = spk.split_user_content(content, who)
        else:
            spans = [(0, len(content), who)]
        if who == spk.HUMAN:
            actor = "user" if spk.has_human([(content[a:b], w) for a, b, w in spans]) else "system"
        elif who in (spk.AUTOMATION, spk.SYSTEM, spk.UNKNOWN):
            actor = "system"
        else:
            actor = "agent"

        # Chunk the content to store it durably without loss
        cap = self.core.capture._excerpt_cap()
        chunks = _split_excerpt(content, cap)
        per_chunk = spk.chunk_spans(spans, chunks)

        # Store each chunk as a separate durable event, just like observe() does
        chunk_ids = []
        for i, chunk in enumerate(chunks):
            payload = {
                "source_type": "context_eviction",
                "excerpt": chunk,
                "source_ref": self._session_id,
                "span_id": span_id,
                "chunk_index": i,
                "chunk_count": len(chunks),
                "speakers": per_chunk[i],
                "attribution": {"user_side": side, "role": str(role)},
            }
            if self._provider_captures():
                # Durable (recall, chronicle_expand) but NOT extracted again: the
                # provider captured this turn when it ended and extraction runs
                # from that capture. Re-extracting evictions produced 4,955 notes
                # on the production store, every one retracted. Carried in the
                # event, so a rebuild makes the same decision (I3).
                payload["extract"] = False
            eid = self.core.capture.append("observed", payload,
                                           actor=actor, session_id=self._session_id)
            chunk_ids.append(eid)
        return chunk_ids

    def _fold(self, m, chunk_ids):
        """R4 (FOLD tier): register a reversible eviction and build the one-line
        tombstone stub that stands in for `m` at its old position.

        span_id/digest are a content hash of `m`, not derived from any event id
        or timestamp — identical input must produce an identical stub on every
        call so compress() stays deterministic (replay_determinism). The
        `folded` event is the durable pointer from that span_id back to the
        ordered `chunk_ids` _ensure_durable just wrote; chronicle_expand(span_id)
        re-reads it to rehydrate. Returns (span_id, digest, stub_message).
        """
        content = _text(m)
        role = m.get("role", "system")
        digest = hash_str(content)
        span_id = "fold_" + digest[:12]
        if self.core:
            self.core.capture.append("folded", {
                "span_id": span_id, "digest": digest, "role": role,
                "char_count": len(content), "chunk_ids": chunk_ids,
                "chunk_count": len(chunk_ids)},
                actor="system", session_id=self._session_id)
        stub = {"role": role, "content": f"[FOLD {span_id} {digest[:8]}]"}
        return span_id, digest, stub

    def _find_fold_record(self, span_id):
        """Look up the `folded` event a span_id points at, scoped to the live
        session (R4). Most recent first: span_id is content-addressed, so any
        matching record reconstructs identical bytes."""
        if not self.core or not span_id:
            return None
        events = self.core.store.get_events_by_session(self._session_id, types=["folded"])
        for ev in reversed(events):
            payload = ev.get("payload")
            payload = json.loads(payload) if isinstance(payload, str) else (payload or {})
            if payload.get("span_id") == span_id:
                return payload
        return None

    def chronicle_expand(self, span_id):
        """Rehydrate a FOLDED (evicted) span back to its original content (R4),
        by span_id from a `[FOLD span_id digest]` tombstone stub.

        Reassembles the durable chunk events in order (R11) and checks the
        result against the stored digest, so a caller can tell a genuine
        rehydration from a store that's missing a chunk.
        """
        if not span_id:
            return {"error": "span_id is required"}
        fold = self._find_fold_record(span_id)
        if fold is None:
            return {"error": f"unknown span_id: {span_id}"}
        parts = []
        for cid in fold.get("chunk_ids") or []:
            ev = self.core.store.get_event(cid)
            if not ev:
                return {"error": f"span_id {span_id} is missing chunk {cid} -- cannot rehydrate",
                        "span_id": span_id}
            payload = ev.get("payload")
            payload = json.loads(payload) if isinstance(payload, str) else (payload or {})
            parts.append(payload.get("excerpt", ""))
        content = "".join(parts)
        return {"span_id": span_id, "role": fold.get("role"), "content": content,
                "verified": hash_str(content) == fold.get("digest")}

    # -- checkpoint digest (§R7) --------------------------------------------

    def _digest_lines_for(self, content: str) -> list[str]:
        """Deterministic digest lines for one span's content -- no model call.

        Runs the same regex-only HeuristicExtractor durable capture uses (§16)
        and turns the facts, entities and directives it finds into short
        lines. Extraction is pure-function over `content`, so the
        same content always yields the same lines (replay determinism).
        """
        if _DIGEST_EXTRACTOR is None or not content or len(content) < 8:
            return []
        try:
            result = _DIGEST_EXTRACTOR.extract(content, source_event="",
                                               owner=self._principal_id, domain="user",
                                               session_id=self._session_id)
        except Exception:  # extraction must never break compression itself
            logger.debug("Chronicle checkpoint digest: extraction failed on a span", exc_info=True)
            return []
        lines: list[str] = []
        for item in result.items:
            body = (item.get("body") or "").strip()
            if not body:
                continue
            kind = item.get("kind")
            key = item.get("key") or {}
            if kind == "fact":
                subject = key.get("entity_name") or key.get("entity_id") or "user"
                pred = key.get("predicate_canonical") or key.get("attribute") or "?"
                line = f"{subject}.{pred}: {body}"
            elif kind == "entity":
                etype = key.get("entity_type") or key.get("type") or ""
                line = f"entity: {body} ({etype})" if etype else f"entity: {body}"
            elif kind == "note":
                line = f"[directive] {body}"
            else:
                # An episode is the user's message restated, and the handoff
                # quotes folded requests verbatim; in the capped digest they
                # pushed the facts out, oldest first.
                continue
            lines.append(line[:200])
        return lines

    def _update_checkpoint_digest(self, evicted: list[dict]) -> str:
        """Fold newly evicted spans into the rolling checkpoint digest (§R7).

        `evicted` is durably stored ALREADY (I17; compress() calls this after
        _ensure_durable). New, not-already-seen lines are appended; the digest
        is then capped to context_engine.checkpoint_digest_max_tokens by
        dropping the OLDEST lines first, so a long session stays bounded.

        A refreshed digest is durably recorded as its own `checkpoint_digest`
        event -- but only when something actually changed, so repeated
        compress() on identical input (replay determinism) does not spam events
        or change the returned digest text.
        """
        new_lines: list[str] = []
        for m in evicted:
            for line in self._digest_lines_for(_text(m)):
                if line not in self._checkpoint_lines and line not in new_lines:
                    new_lines.append(line)
        if not new_lines:
            return "\n".join(self._checkpoint_lines)

        self._checkpoint_lines.extend(new_lines)
        cap = self.core.cfg.get("context_engine.checkpoint_digest_max_tokens", 300)
        try:
            cap = max(0, int(cap))
        except (TypeError, ValueError):
            cap = 300
        while self._checkpoint_lines and estimate_tokens("\n".join(self._checkpoint_lines), margin=COMPRESSION_BUDGET) > cap:
            self._checkpoint_lines.pop(0)  # oldest first -- rolling, not a fixed snapshot

        digest_text = "\n".join(self._checkpoint_lines)
        self.core.capture.append("checkpoint_digest", {
            "session_id": self._session_id, "digest": digest_text,
            "new_lines": new_lines, "line_count": len(self._checkpoint_lines),
            "evicted_spans": len(evicted)},
            actor="system", session_id=self._session_id)
        return digest_text

    def get_checkpoint_digest(self) -> str:
        """Current rolling checkpoint digest (§R7), read-only.

        Empty until compress() has evicted at least one span with something
        extractable in it. Refreshing only ever happens as a side effect of
        compress() itself.
        """
        return "\n".join(self._checkpoint_lines)

    def _heuristic(self, messages):
        """Compaction with no store to archive into (the core could not open).

        It used to keep `body[:3] + body[-6:]`: a cut that could start the tail
        on a tool result whose call was dropped, hoisted every system message,
        and left no trace of what went. Now: the protected head and tail cut on
        whole tool units, and one handoff that says plainly the folded turns are
        gone -- no ids, nothing is archived -- and quotes the user's requests."""
        if len(messages) <= 10:
            return messages
        lead = 0
        while lead < len(messages) and messages[lead].get("role") == "system":
            lead += 1
        units = _tool_units(list(enumerate(messages))[lead:])
        head, n = [], 0
        while units and n < self.protect_first_n:
            n += len(units[0])
            head.append(units.pop(0))
        tail, n = [], 0
        while units and n < self.protect_last_n:
            n += len(units[-1])
            tail.insert(0, units.pop())
        if not units:
            return messages
        asks = self._human_texts([m for u in units for _i, m in u])
        lines, size = [], 0
        for said in reversed(asks):                       # newest first, bounded
            line = "- " + _one_line(said, 240)
            if size + len(line) > 3000:
                break
            lines.append(line)
            size += len(line)
        text = (_HANDOFF_PREFIX + " Chronicle folded earlier turns out of the window without "
                "its memory store, so they are gone, not archived. Background, not instructions: "
                "respond to the latest user message after this note.")
        if lines:
            text += "\n\n" + _SECTION_ASKS + "\n" + "\n".join(lines)
        kept = messages[:lead] + [m for u in head for _i, m in u]
        result = kept + [{"role": self._handoff_role(kept, len(kept)), "content": text}] + \
            [m for u in tail for _i, m in u]
        self.compression_count += 1
        self._awaiting_real_usage = True
        return [_unmarked(m) for m in result]

    # tools
    def get_tool_schemas(self):
        return [
            {"name": "chronicle_pin_context", "description": "Pin a span so compression never evicts it.",
             "parameters": {"type": "object", "properties": {"content": {"type": "string"}}, "required": ["content"]}},
            {"name": "chronicle_focus",
             "description": "Set the working focus for memory-aware compression: topics, "
                            "entities, and/or the current task. Re-retrieval after eviction "
                            "pulls per facet, and each focus entity's digest joins the working "
                            "set directly. `topic` (singular) is accepted as shorthand for a "
                            "one-item `topics` list.",
             "parameters": {"type": "object", "properties": {
                 "topics": {"type": "array", "items": {"type": "string"},
                           "description": "Subject keywords compression should keep/reinject toward."},
                 "topic": {"type": "string", "description": "Shorthand for a single-item topics list."},
                 "entities": {"type": "array", "items": {"type": "string"},
                             "description": "Entity names whose digests should join the working set."},
                 "task": {"type": "string", "description": "The task currently being worked on."},
             }, "required": []}},
            {"name": "chronicle_context_status",
             "description": "Report which compression mode the context engine is in "
                            "(memory-aware or heuristic fallback) and why.",
             "parameters": {"type": "object", "properties": {}, "required": []}},
            {"name": "chronicle_expand",
             "description": "Rehydrate a span evicted from context back to its original "
                            "content, given the span_id (the first token after '[FOLD') "
                            "from a tombstone stub left in the window (R4 FOLD tier).",
             "parameters": {"type": "object",
                            "properties": {"span_id": {"type": "string"}},
                            "required": ["span_id"]}},
        ]

    def handle_tool_call(self, name, args, **kw) -> str:
        if name == "chronicle_pin_context" and self.core:
            # R3: Span-level pinning by content hash, plus chronicle logging
            content = args.get("content", "")
            content_hash = hashlib.sha256(content.encode("utf-8")).hexdigest()
            self._pinned_content_hashes.add(content_hash)
            self.core.capture.agent_explicit("pin", "context", content)
            return json.dumps({"status": "pinned"})
        if name == "chronicle_focus":
            # `topic` (singular) is pre-R8 shorthand for a one-item `topics`
            # list; honored alongside `topics` (union), not instead of it.
            topics = list(args.get("topics") or [])
            if args.get("topic"):
                topics.append(args["topic"])
            self.focus = self._normalize_focus(
                {"topics": topics, "entities": args.get("entities") or [], "task": args.get("task")})
            # self.focus_topic mirrors the structured focus for any caller still
            # reading the pre-R8 single-string attribute: the task if set, else
            # the first topic, else None.
            self.focus_topic = self.focus["task"] or (self.focus["topics"][0] if self.focus["topics"] else None)
            return json.dumps({"status": "focus_set", "focus": self.focus, "topic": self.focus_topic})
        if name == "chronicle_context_status":
            return json.dumps(self.context_status())
        if name == "chronicle_expand":
            if not self.core:
                return json.dumps({"error": "chronicle_expand requires the memory-aware "
                                             "engine (heuristic fallback has no event store)"})
            return json.dumps(self.chronicle_expand(args.get("span_id", "")))
        return json.dumps({"error": f"unknown tool: {name}"})

    def context_status(self) -> dict:
        """Which compression mode is live, and why (chronicle_context_status).

        Read-only by design — asking what mode you are in must not itself trigger
        a core rebuild. Mode is derived from `self.core`, the one thing that
        actually decides which branch compress() takes, so the report cannot
        disagree with the behaviour.
        """
        live = self.core is not None
        if live:
            reason = ("re-initialized after %d failed attempt(s)" % self._recovered_after
                      if self._recoveries else "initialized at session start")
        elif not self._init_started:
            reason = "not initialized yet (no session start)"
        else:
            reason = "init failed: %s" % (self._last_error or "unknown")
        due = self._retry_due_in()
        res = {
            "engine": self.name,
            "mode": "memory_aware" if live else "heuristic_fallback",
            "reason": reason,
            "init_attempts": self._init_attempts,
            "consecutive_failures": self._consecutive_failures,
            "recoveries": self._recoveries,
            "last_error": self._last_error,
            "retry_due_in_sec": due,
            "retry_budget_spent": (not live and self._init_started and due is None),
            "attempts_this_hour": len(self._attempt_times),
        }
        res["compaction"] = {
            "trigger_tokens": self.threshold_tokens,
            "target_tokens": self._target_budget() if live else None,
            "context_length": self.context_length,
            "protect_first_n": self.protect_first_n,
            "protect_last_n": self.protect_last_n,
            "max_messages": self.max_messages,
            "passes": self.compression_count,
            "last_pass": self.last_pass,
            "folded_requests": len(self._handoff_asks),
            "folded_steps": len(self._handoff_steps),
            "stated_facts": len(self._checkpoint_lines),
            "pinned": len(self._pinned_content_hashes),
        }
        if live and self.core:
            res["diagnostics"] = self.core.diagnostics()
        return res

    def log_context_status(self):
        """Emit the status as one operator-readable line.

        WARNING while degraded: a silently heuristic context engine is the whole
        defect, and INFO is filtered out on the box where it happened.
        """
        st = self.context_status()
        log = logger.info if self.core is not None else logger.warning
        log("chronicle_context_status: mode=%s reason=%s attempts=%d recoveries=%d",
            st["mode"], st["reason"], st["init_attempts"], st["recoveries"])
        return st

    # status
    # -- proactive tool-output trim (host: prune_tool_results_only) --------
    _IDENTICAL = "[identical to a later tool result in this conversation]"

    def _messages_tokens(self, messages) -> int:
        return sum(estimate_tokens(_text(m), margin=COMPRESSION_BUDGET) for m in messages)

    def prune_tool_results_only(self, messages, current_tokens=None):
        """Trim old tool output without a model, before a full compaction is due.

        Hermes calls this on a lower trigger than compress() (turn_preflight),
        and commits the result only when it is a NEW list with a non-zero
        count. Its built-in compressor implements it; a plugin engine inherits a
        no-op, so switching the context engine to Chronicle quietly stopped
        trimming the tool output that fills most of an agent's window. The same
        two safe passes as the host's:

          1. LOSSLESS. A tool result byte-identical to a LATER one becomes a
             one-line pointer to it; the newest copy stays whole.
          2. An old result over `min_chars` keeps its first `keep_head_chars` and
             last `keep_tail_chars` (a status line and a final result are
             usually at the ends) and says exactly how much was removed.

        Never touched: anything but role=tool, the protected head and tail, a
        pinned or directive span (_never_evict), and non-text content. Nothing
        is lost to memory — the turn was captured whole when it ended.

        A trim rewrites earlier messages, which breaks the provider's prompt
        cache, so it is committed only when it saves `min_reclaim_tokens`, and
        after one the context must regrow by a full trigger's worth (the host's
        own runway rule) before the next. Returns the INPUT list on a no-op.
        """
        def cfg(key, default):
            return self._cfg_percent("prune_tool_results.%s" % key, default)
        if not cfg("enabled", True) or not self.context_length:
            return messages, 0
        trigger = int(self.context_length * float(cfg("at_percent", 0.5)))
        tokens = current_tokens if current_tokens is not None else self._messages_tokens(messages)
        if tokens < max(trigger, self._prune_rearm_tokens):
            return messages, 0
        n = len(messages)
        head_n, tail_n = self.protect_first_n, self.protect_last_n
        if n <= head_n + tail_n + 1:
            return messages, 0
        min_chars = int(cfg("min_chars", 2000))
        keep_head = int(cfg("keep_head_chars", 500))
        keep_tail = int(cfg("keep_tail_chars", 300))

        out = list(messages)
        changed = 0
        # 1) lossless: point an older exact duplicate at the newest copy
        newest = set()
        for i in range(n - 1, -1, -1):
            m = messages[i]
            c = m.get("content")
            if m.get("role") != "tool" or not isinstance(c, str) or len(c) < 200:
                continue
            key = hashlib.sha256(c.encode("utf-8")).hexdigest()
            if key not in newest:
                newest.add(key)
            elif head_n <= i < n - tail_n and not self._never_evict(m):
                out[i] = dict(m, content=self._IDENTICAL)
                changed += 1
        # 2) keep the ends of a large old result
        for i in range(head_n, n - tail_n):
            m = out[i]
            c = m.get("content")
            if m.get("role") != "tool" or not isinstance(c, str) or len(c) <= min_chars:
                continue
            if self._never_evict(messages[i]):
                continue
            removed = len(c) - keep_head - keep_tail
            if removed <= 0:
                continue
            out[i] = dict(m, content="%s\n[... %d characters of this old tool result trimmed ...]\n%s"
                          % (c[:keep_head], removed, c[-keep_tail:] if keep_tail else ""))
            changed += 1
        if not changed:
            return messages, 0
        before, after = self._messages_tokens(messages), self._messages_tokens(out)
        reclaimed = before - after
        min_reclaim = int(cfg("min_reclaim_tokens", 1500))
        if reclaimed < min_reclaim:
            return messages, 0
        self._prune_rearm_tokens = after + max(reclaimed, trigger, min_reclaim)
        return out, changed

    def has_content_to_compress(self, messages) -> bool:
        """`/compress` preflight: is there anything compress() may evict?

        The host asks before a manual compaction so it can answer "nothing to
        compress yet" instead of running a pass that changes nothing. The
        default says yes to everything. The same partition compress() uses:
        system rows, the head, the tail, and directive or pinned spans are
        protected; anything else in the middle is fair game."""
        body = [m for m in messages if m.get("role") != "system"]
        middle = body[self.protect_first_n: max(self.protect_first_n, len(body) - self.protect_last_n)]
        return any(not self._never_evict(m) for m in middle)

    def should_defer_preflight_to_real_usage(self, rough_tokens) -> bool:
        """Whether a ROUGH over-threshold estimate should wait one request for
        the provider's real count. The host's own semantics, point for point
        (agent/context_compressor.py), because the host calls this only for
        whole-context rough estimates and its anti-thrash reasoning assumes
        them. Chronicle used to inherit the default `False`, so right after a
        compaction a stale estimate could compact a request that already fit.

          under the threshold        -> no reason to defer
          a compaction just ran      -> defer: the last real reading predates it
          the provider proved it     -> do not defer: real usage says it is over
          provider omits usage       -> do not defer, or compression could never
                                        fire on the estimate, its only signal
        """
        if not self.threshold_tokens or rough_tokens < self.threshold_tokens:
            return False
        if self._awaiting_real_usage:
            return True
        if self.last_prompt_tokens >= self.threshold_tokens:
            return False
        return self._provider_reports_usage

    def should_compress_preflight(self, messages) -> bool:
        """Preflight (§R10): use idle time BEFORE the HIGH watermark forces a
        reactive compress() to do that pass's expensive, I/O-bound prep early --
        rescue (durable capture of critical spans) and pre-durabilizing the
        spans that would be evicted if compress() ran right now (fold
        candidates). Bounded by `capture.precompress.budget_ms` (previously read
        by nothing at all -- this method was hardcoded False) so a slow store
        can never turn a spare moment into new latency on the request path.

        Only in the LOW..HIGH watermark gap: below LOW there is no pressure yet;
        at/above HIGH, should_compress() is already True and the reactive path
        owns this pass.

        Returns True iff preflight found pressure and did (some of) the prep;
        False if there was nothing to do or no core (heuristic fallback has no
        store, matching R1).
        """
        if not self.core or self.context_length <= 0:
            return False

        high_tokens = self.threshold_tokens or int(self.context_length * self.high_watermark_percent)
        low_tokens = int(self.context_length * self.low_watermark_percent)   # see _apply_policy
        tokens_now = sum(estimate_tokens(_text(m), margin=COMPRESSION_BUDGET) for m in messages)
        if tokens_now < low_tokens or tokens_now >= high_tokens:
            return False

        budget_ms = self.core.cfg.get("capture.precompress.budget_ms", 400)
        deadline = time.monotonic() + max(0, budget_ms) / 1000.0
        focus = self._normalize_focus(self.focus if self.focus is not None else self.focus_topic)
        self._rescue_and_fold_candidates(messages, focus, deadline)
        return True

    def _rescue_and_fold_candidates(self, messages, focus, deadline):
        """Do compress()'s I/O-heavy work early, off the hot path (§R10).

        Mirrors compress()'s rescue + eviction-scoring (§R2/R3) to identify
        which spans it would evict against `messages` right now, then durably
        stores those candidates ahead of time via _ensure_durable (I17). A
        read-only preview: it never mutates `messages` and never commits an
        eviction, so a stale guess only costs a little redundant durability
        I/O, never correctness. Stops the moment `deadline` (a time.monotonic()
        cutoff from capture.precompress.budget_ms) passes.
        """
        self.core.capture.rescue(messages, session_id=self._session_id,
                                speaker_context=self._host_context)
        if time.monotonic() >= deadline:
            return

        body = [m for m in messages if m.get("role") != "system"]
        if len(body) <= self.protect_first_n + self.protect_last_n:
            return  # nothing would be evicted yet -- no fold candidates to prep

        protected = (
            [m for m in messages if m.get("role") == "system"]
            + body[:self.protect_first_n] + body[-self.protect_last_n:]
        )
        middle = body[self.protect_first_n:-self.protect_last_n]
        budget = self._target_budget()
        used = sum(estimate_tokens(_text(m), margin=COMPRESSION_BUDGET) for m in protected)

        never_idx, scored = [], []
        total_middle = len(middle)
        for i, m in enumerate(middle):
            if self._never_evict(m):
                never_idx.append(i)
            else:
                recency_position = i / max(1, total_middle - 1) if total_middle > 1 else 1.0
                scored.append((self._keep_score(m, focus, recency_position), i))
        scored.sort(key=lambda pair: pair[0], reverse=True)

        kept_idx = set(never_idx)
        for _score, i in scored:
            cost = estimate_tokens(_text(middle[i]), margin=COMPRESSION_BUDGET)
            if used + cost <= budget:
                kept_idx.add(i)
                used += cost

        for i, m in enumerate(middle):
            if i in kept_idx:
                continue
            self._ensure_durable(m)  # fold candidate: pre-durabilized ahead of the deadline
            if time.monotonic() >= deadline:
                return

    def get_status(self) -> dict:
        st = self.context_status()
        return {
            "engine": self.name,
            "mode": st["mode"],
            "mode_reason": st["reason"],
            "context_length": self.context_length,
            "threshold_tokens": self.threshold_tokens,
            "last_prompt_tokens": self.last_prompt_tokens,
            "last_total_tokens": self.last_total_tokens,
            "compression_count": self.compression_count,
        }
