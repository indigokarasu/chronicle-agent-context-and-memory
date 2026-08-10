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
    from .engine.embeddings import estimate_tokens  # type: ignore
except Exception:  # … else top-level layout (plugin-package vs. flat checkout)
    try:
        from engine.embeddings import estimate_tokens
    except Exception:  # pragma: no cover
        def estimate_tokens(text):
            """Fallback if engine.embeddings is unavailable: chars/3 ceiling,
            matching estimate_tokens's own conservative ratio (§27 embeddings)."""
            return -(-len(text or "") // 3)

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
        self.threshold_percent = 0.75
        self.protect_first_n = 3
        self.protect_last_n = 6
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
        # Rolling checkpoint digest (§R7): deterministic, no-model lines built
        # from extraction artifacts over every span compress() has folded out
        # of the window this session. Oldest-first so the cap can trim the
        # front. Reset per session in on_session_start.
        self._checkpoint_lines: list[str] = []
        # -- pressure warning state (§R9) ----------------------------------
        # Emit an advisory span once per high-watermark crossing so the agent
        # can pin/save before compress() forcibly evicts. Latched ONLY when the
        # warning is actually delivered inside a compress() return value (see
        # _emit_pressure_warning) -- never on intent alone.
        self._pressure_warning_injected = False  # latched only on actual delivery
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

    # lifecycle
    def on_session_start(self, session_id, *, hermes_home=None, principal_id="default", config=None, **kw):
        # None (not passed / explicitly cleared) resolves to the real home
        # directory here, at call time -- see _default_hermes_home().
        hermes_home = hermes_home or _default_hermes_home()
        self._session_id = session_id
        self._principal_id = principal_id
        self._init_args = {"hermes_home": hermes_home, "config": config}
        self._init_started = True
        self._locked_prefix = []  # §R5: a new session starts with nothing settled
        self._checkpoint_lines = []  # §R7: the rolling digest is scoped to THIS session
        self._pressure_warning_injected = False  # §R9: re-arm for the new session
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

    def update_model(self, model, context_length, base_url="", api_key="", provider="", api_mode=""):
        self.context_length = context_length
        # HIGH watermark (§R2): the fraction of the window that decides a
        # compression pass is due. Computed once here, same as before, so
        # threshold_tokens (read directly by get_status()/the host) can never
        # disagree with what should_compress() actually tests against.
        self.threshold_percent = self._cfg_percent("high_watermark_percent", self.threshold_percent)
        self.threshold_tokens = int(context_length * self.threshold_percent)

    def update_from_response(self, usage):
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

    def _pressure_warning_span(self) -> dict[str, str]:
        """A system-role advisory (§R9), emitted once per high-watermark
        crossing, so the agent can pin/save before compression runs."""
        pressure_pct = int(100 * self.last_prompt_tokens / max(1, self.context_length))
        return {
            "role": "system",
            "content": (
                f"[Context pressure warning] Your context window is at {pressure_pct}% capacity "
                f"(the high watermark). Compression will run soon and may evict less-relevant "
                f"context -- pin anything important now with chronicle_pin_context."
            )
        }

    def _emit_pressure_warning(self, output, warn_pending, *, used=None, budget=None):
        """Insert the §R9 pressure-warning span into `output`, honoring the R2
        "output <= budget" guarantee, and latch _pressure_warning_injected ONLY
        when the warning is actually included in what's returned.

        Every compress() return path funnels through here so a newly-crossed
        high watermark can never be latched without being delivered. `used`/
        `budget` come from the full pipeline; on the small-body shortcut both
        are None and are derived fresh here, so the warning is fit against the
        same target budget either way. Returns `output` unchanged (latch stays
        False) when nothing is pending or there is no room under budget.
        """
        if not warn_pending:
            return output
        if budget is None:
            budget = self._target_budget()
        if used is None:
            used = sum(estimate_tokens(m.get("content")) for m in output)
        remaining = budget - used
        if remaining <= 0:
            return output  # no room this call -- stays un-latched, retried next time
        warning = self._pressure_warning_span()
        cost = estimate_tokens(warning["content"])
        if cost > remaining:
            warning = dict(warning, content=warning["content"][:max(0, remaining * 3)])
        if not warning["content"]:
            return output
        self._pressure_warning_injected = True
        insert_at = 0
        while insert_at < len(output) and output[insert_at].get("role") == "system":
            insert_at += 1
        return output[:insert_at] + [warning] + output[insert_at:]

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

        # Pressure warning (§R9): whether this call is the one that delivers a
        # newly-crossed high-watermark warning. NOT latched here -- only
        # _emit_pressure_warning may set _pressure_warning_injected, and only
        # once the warning is actually in the returned output. Computed before
        # the small-body early return below so that path is covered too.
        warn_pending = self.is_under_pressure() and not self._pressure_warning_injected

        # 1) rescue critical/high-salience spans → durable beliefs (I14)
        self.core.capture.rescue(messages, session_id=self._session_id)

        # 1.5) stable cut-point geometry (§R5): reuse whatever leading run of
        # `messages` is byte-identical, in order, to what compress() already
        # committed to last pass. That run is SETTLED -- reproduced verbatim,
        # never rescored or reordered -- so only the genuinely new tail
        # (whatever the host appended since) is fresh territory for a
        # head/tail/score decision.
        locked_len = self._match_locked_prefix(messages)
        locked = list(messages[:locked_len])
        fresh = messages[locked_len:]
        is_first_pass = locked_len == 0

        if is_first_pass:
            # Original short-circuit, preserved for a from-scratch window too
            # small to bother compressing at all.
            body_only = [m for m in fresh if m.get("role") != "system"]
            if len(body_only) <= self.protect_first_n + self.protect_last_n:
                return self._emit_pressure_warning(messages, warn_pending)

        # Index-tag `fresh` so the decided subset can be re-emitted in its
        # ORIGINAL relative order at the end (§R5: no more "system hoist").
        fresh_indexed = list(enumerate(fresh))
        fresh_system = [(i, m) for i, m in fresh_indexed if m.get("role") == "system"]
        fresh_body = [(i, m) for i, m in fresh_indexed if m.get("role") != "system"]

        # protect_first_n is a first-pass-only concept: once settled the true
        # head lives inside `locked`. Later passes only keep a rolling tail
        # reserve over whatever is newly appended.
        if is_first_pass:
            head, rest = fresh_body[:self.protect_first_n], fresh_body[self.protect_first_n:]
        else:
            head, rest = [], fresh_body

        if len(rest) <= self.protect_last_n:
            tail, middle = rest, []
        else:
            tail, middle = rest[-self.protect_last_n:], rest[:-self.protect_last_n]

        # 2) two-watermark hysteresis (§R2): admit best-scoring evictable spans,
        # by REAL per-span token cost, only while there is room under the LOW
        # watermark. Recency-weighted (§R3): newer middle spans score higher,
        # so the oldest lose the budget race first.
        budget = self._target_budget()

        never_pos, scored = [], []
        total_middle = len(middle)
        for pos, (_idx, m) in enumerate(middle):
            if self._never_evict(m):
                never_pos.append(pos)
            else:
                recency_position = pos / max(1, total_middle - 1) if total_middle > 1 else 1.0
                scored.append((self._keep_score(m, focus, recency_position), pos))
        scored.sort(key=lambda pair: pair[0], reverse=True)  # best-scoring first; ties keep document order

        # `locked` is SUNK COST (§R5): every byte already survived a previous
        # pass's budget check and is never rescored/reclipped again. Only the
        # budget REMAINING after its real token cost is available to whatever
        # this pass freshly decides.
        used_locked = sum(estimate_tokens(m.get("content")) for m in locked)
        fresh_budget = max(0, budget - used_locked)

        # compress() must guarantee output <= budget (§R2). Priority order
        # (system, then head, then tail, then never-evict middle) decides who
        # gets first claim before anything is clipped. A span with SOME room
        # is shortened; a span with NO room is made durable (I17) and dropped
        # outright -- never blanked-but-present (§R5).
        req_fresh = list(fresh_system) + list(head) + list(tail)
        fitted, used_req, dropped_req = self._fit_within_budget(req_fresh, fresh_budget)
        fitted_content = dict(fitted)
        fresh_system = [(i, fitted_content[i]) for i, _m in fresh_system if i in fitted_content]
        head = [(i, fitted_content[i]) for i, _m in head if i in fitted_content]
        tail = [(i, fitted_content[i]) for i, _m in tail if i in fitted_content]

        # never-evict middle spans get whatever's left after system/head/tail.
        never_budget = max(0, fresh_budget - used_req)
        fitted_never, used_never, dropped_never = self._fit_within_budget(
            [middle[p] for p in never_pos], never_budget)
        fitted_never_content = dict(fitted_never)
        dropped_never_idx = {idx for idx, _m in dropped_never}
        middle = list(middle)
        for p in never_pos:
            orig_idx, _m = middle[p]
            if orig_idx in fitted_never_content:
                middle[p] = (orig_idx, fitted_never_content[orig_idx])

        used = used_locked + used_req + used_never

        kept_pos = {p for p in never_pos if middle[p][0] not in dropped_never_idx}
        for _score, pos in scored:
            cost = estimate_tokens(middle[pos][1].get("content"))
            if used + cost <= budget:
                kept_pos.add(pos)
                used += cost
            # else: budget is full -- stays evicted, regardless of score

        # 3) evict ONLY durable spans — make each durable first (I17), then FOLD
        # (R4): a reversible eviction. Every evicted span gets a byte-exact
        # durable copy (_ensure_durable, chunked per R11) plus a content-
        # addressed span_id in a `folded` event pointing at those chunks --
        # recoverable via chronicle_expand(span_id). Score-evicted middle spans
        # that still fit the leftover budget leave a one-line tombstone stub AT
        # THEIR OLD POSITION (best-scoring evictions get first claim on the
        # stub room). Required/never spans dropped for budget are durably folded
        # too, but never get a stub (the budget is already spent).
        score_evicted = [pos for _score, pos in scored if pos not in kept_pos]
        durable_evicted = []
        evicted_span_ids: list[str] = []
        n_stubs = 0
        for pos in score_evicted:
            orig_idx, m = middle[pos]
            durable_evicted.append(m)
            chunk_ids = self._ensure_durable(m)
            span_id, _digest, stub = self._fold(m, chunk_ids)
            evicted_span_ids.append(span_id)
            stub_cost = estimate_tokens(stub.get("content"))
            if used + stub_cost <= budget:
                middle[pos] = (orig_idx, stub)
                kept_pos.add(pos)
                used += stub_cost
                n_stubs += 1
            # else: no room even for the tombstone -- still durably recoverable
            # from the log (I17), just not in-window.
        for _idx, m in list(dropped_req) + list(dropped_never):
            durable_evicted.append(m)
            chunk_ids = self._ensure_durable(m)
            span_id, _digest, _stub = self._fold(m, chunk_ids)
            evicted_span_ids.append(span_id)

        kept_middle = [middle[p] for p in range(len(middle)) if p in kept_pos]

        # Re-emit the decided subset of `fresh` in its ORIGINAL relative order
        # (§R5) -- a message's output position is a monotonic function of its
        # input position, no system-first bucket concatenation.
        decided = sorted(fresh_system + head + kept_middle + tail, key=lambda pair: pair[0])
        settled = [m for _idx, m in decided]

        # 4) re-retrieve long-term memory toward focus, sized to whatever room
        # is left under the low watermark. §R8: working-set rehydration pulls
        # PER FACET -- each topic, the task, and each focus entity's own digest
        # -- rather than one query against a flattened focus string, so a facet
        # with no lexical overlap with the others still gets its own shot at
        # the reinjection budget.
        injected = []
        if focus["topics"] or focus["entities"] or focus["task"]:
            remaining = budget - used
            inject_budget = self._reinject_budget(remaining)
            if inject_budget > 0:
                injected, used = self._rehydrate_working_set(focus, inject_budget, used)

        # 4b) checkpoint digest (§R7): a deterministic, no-model rolling digest
        # of everything compression has folded out of the window this session,
        # capped so it can never grow unbounded. Built from extraction
        # artifacts (facts/entities/directives/episodes) — never a model call.
        # Injected only into whatever budget room is left, always clipped to
        # fit, so it never breaks the compress() output<=budget guarantee (§R2).
        digest_text = self._update_checkpoint_digest(durable_evicted)
        if digest_text:
            remaining = budget - used
            if remaining > 0:
                content = f"[Checkpoint: {digest_text}]"
                if estimate_tokens(content) > remaining:
                    content = content[:max(0, remaining * 3)]
                if content:
                    injected.append({"role": "system", "content": content})
                    used += estimate_tokens(content)

        # 5) audit event (§R6/R4): evicted_spans/kept_spans/folded_spans carry
        # actual span ids (not counts) so the kept/evicted/folded partition of
        # this window is replayable from the log alone.
        result = locked + settled
        kept_span_ids = [self._span_id(m) for m in result]
        self.core.capture.append("compressed", {
            "session_id": self._session_id,
            "evicted_spans": evicted_span_ids, "kept_spans": kept_span_ids,
            "folded_spans": evicted_span_ids, "folded_in_window": n_stubs,
            "evicted_count": len(evicted_span_ids), "retained": len(kept_span_ids),
            "summary_ref": "", "budget_tokens": budget, "used_tokens": used},
            actor="system", session_id=self._session_id)

        self.compression_count += 1
        # §R5: lock in everything just decided -- never rescored/reordered again
        # -- EXCEPT the memory injection, which is regenerated fresh every pass
        # and so stays ordinary evictable content on the NEXT call.
        self._locked_prefix = result
        # 6) pressure warning (§R9): counted against `budget`/`used` like
        # everything else, so a newly-crossed high watermark can never push
        # compress()'s output over its own budget guarantee (R2).
        output = result + injected
        return self._emit_pressure_warning(output, warn_pending, used=used, budget=budget)

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
        while k < n and messages[k] == locked[k]:
            k += 1
        return k

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
        content = (m.get("content") or "").lower()

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

        # Salience: high-value keywords (critical, important, remember, must)
        if any(k in content for k in ("important", "remember", "critical", "must")):
            score += w.get("salience", 0.20)

        # Criticality: criticality-specific keywords (folded into salience concept)
        if any(k in content for k in ("critical", "must", "urgent", "important")):
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
            ctx = self.core.retrieval.get_context(hint, token_budget=facet_budget,
                                                  include_directives=False, principal=self._principal_id)
            if not ctx:
                continue
            content = f"[Relevant memory: {hint}]\n{ctx}"
            if estimate_tokens(content) > remaining:
                content = content[:max(0, remaining * 3)]
            if content:
                injected.append({"role": "system", "content": content})
                cost = estimate_tokens(content)
                used += cost
                remaining -= cost

        if entity_ids and remaining > 0:
            facet_budget = min(share, remaining)
            lines = self._entity_digest_lines(entity_ids, facet_budget)
            if lines:
                content = "[Entity working set]\n" + "\n".join(lines)
                if estimate_tokens(content) > remaining:
                    content = content[:max(0, remaining * 3)]
                if content:
                    injected.append({"role": "system", "content": content})
                    used += estimate_tokens(content)

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
        budget_chars = max(0, token_budget * 3)  # chars/3 ceiling, same as estimate_tokens
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
                entity_row = self.core.store.get_belief("entities", eid) or {}
                line = "- {}: {}".format(entity_row.get("name") or eid, rendered)
            if used_chars + len(line) + 1 > budget_chars:
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
        low = self._cfg_percent("low_watermark_percent", self.low_watermark_percent)
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
            content = m.get("content") or ""
            cost = estimate_tokens(content)
            remaining = budget - used
            if cost <= remaining:
                kept.append((idx, m))
                used += cost
                continue
            if remaining <= 0:
                dropped.append((idx, m))
                continue
            clipped = content[:remaining * 3]  # chars/3 ceiling -> estimate_tokens(clipped) <= remaining
            kept.append((idx, dict(m, content=clipped) if clipped != content else m))
            used += estimate_tokens(clipped)
        return kept, used, dropped

    def _compute_content_hash(self, m) -> str:
        """Compute sha256 hash of message content for span-level pinning (R3)."""
        content = (m.get("content") or "").encode("utf-8")
        return hashlib.sha256(content).hexdigest()

    def _is_pinned(self, m) -> bool:
        """Check if message is pinned by content hash (R3: span-level protection)."""
        return self._compute_content_hash(m) in self._pinned_content_hashes

    def _never_evict(self, m) -> bool:
        """R3: never evict directives (never/always/must keywords) or pinned spans."""
        c = (m.get("content") or "").lower()
        if any(k in c for k in _NEVER_EVICT_KW):
            return True
        if self._is_pinned(m):
            return True
        return False

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
        content = m.get("content") or ""
        if len(content) < 1:
            return []
        # Normalize chat-role to a valid Chronicle actor (CHECK constraint allows
        # only 'user','agent','curator','system'). "assistant" is not a valid actor.
        role = m.get("role", "system")
        actor = role if role in ("user", "agent", "curator", "system") else "agent"

        # Import the chunker from capture (same as observe() uses)
        try:
            from .engine.capture import _split_excerpt
        except ImportError:
            from engine.capture import _split_excerpt

        # Chunk the content to store it durably without loss
        cap = self.core.capture._excerpt_cap()
        chunks = _split_excerpt(content, cap)

        # Store each chunk as a separate durable event, just like observe() does
        chunk_ids = []
        for i, chunk in enumerate(chunks):
            eid = self.core.capture.append("observed", {
                "source_type": "context_eviction",
                "excerpt": chunk,
                "source_ref": self._session_id,
                "span_id": span_id,
                "chunk_index": i,
                "chunk_count": len(chunks)
            },
            actor=actor,
            session_id=self._session_id)
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
        content = m.get("content") or ""
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
        and turns whatever it finds (facts, entities, directives, episodes)
        into short lines. Extraction is pure-function over `content`, so the
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
            elif kind == "episode":
                line = f"[episode] {body}"
            else:
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
            for line in self._digest_lines_for(m.get("content") or ""):
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
        while self._checkpoint_lines and estimate_tokens("\n".join(self._checkpoint_lines)) > cap:
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
        if len(messages) <= 10:
            return messages
        system = [m for m in messages if m.get("role") == "system"]
        body = [m for m in messages if m.get("role") != "system"]
        self.compression_count += 1
        return system + body[:3] + body[-6:]

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
        return {
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

        high_tokens = self.threshold_tokens or int(
            self.context_length * self._cfg_percent("high_watermark_percent", self.threshold_percent))
        low_tokens = int(self.context_length * self._cfg_percent(
            "low_watermark_percent", self.low_watermark_percent))
        tokens_now = sum(estimate_tokens(m.get("content")) for m in messages)
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
        self.core.capture.rescue(messages, session_id=self._session_id)
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
        used = sum(estimate_tokens(m.get("content")) for m in protected)

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
            cost = estimate_tokens(middle[i].get("content"))
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
