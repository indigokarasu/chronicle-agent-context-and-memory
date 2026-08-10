"""
Chronicle — Compression-fidelity harness (Ladder 7 / R0, §13).

Baselines `context.py`'s compression behavior (ChronicleContextEngine.compress /
_heuristic) against I17 (a span may be evicted only if it is durably stored,
verified by re-reading the store) and the properties R1..R11 are meant to
establish on top of it: fallback parity with the core path, real pin
protection, focus-driven memory reinjection, a hard token budget, replay
determinism (both "same input -> same output" and "the audit log alone can
reconstruct the window"), stable prefix ordering across turns, and a complete
audit trail.

R0 is BASELINE ONLY — it changes no production code. Several checks below are
declared with `expect_baseline_fail=True` because the current implementation
does not yet provide the guarantee being tested; that is documented, not
accidental, and each one names the future task that is expected to fix it.
`check()` enforces the contract in both directions:

  * expect_baseline_fail=True and the condition is False (still broken): a
    "BASELINE-FAIL" line is printed and the test stays GREEN. This is the
    expected, current state of the world.
  * expect_baseline_fail=True and the condition is True (unexpectedly fixed):
    the test FAILS LOUDLY. A later task must flip the flag to False (and drop
    `expect_baseline_fail=True`) as part of landing the fix — a bug that is
    silently fixed while still flagged "known baseline gap" is exactly the
    kind of drift this harness exists to catch.
  * expect_baseline_fail=False: ordinary assertion. A regression here is real
    and must fail the suite.

Run directly for a human-readable report:
    /usr/bin/python3 tests/test_compression_fidelity.py
Or as part of the suite:
    /usr/bin/python3 -m pytest tests/test_compression_fidelity.py -q
Either way the process exits 0 as long as reality matches the documented
expectations (baseline gaps included) — exit 1 only on a genuine surprise
(an unexpected regression, or a documented gap that has silently closed).
"""

from __future__ import annotations

import copy
import json
import sys
import tempfile
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).parent.parent))

from context import ChronicleContextEngine  # noqa: E402

# -- fidelity-check bookkeeping ---------------------------------------------

PASSED: list[str] = []             # ordinary assertions that held
BASELINE_FAILURES: list[str] = []  # documented gaps, confirmed still open


def check(name: str, condition: bool, *, expect_baseline_fail: bool, detail: str = "") -> None:
    """One fidelity assertion. See module docstring for the two-way contract."""
    if expect_baseline_fail:
        if condition:
            raise AssertionError(
                f"{name}: expected a documented BASELINE-FAIL but the condition now HOLDS -- "
                f"the fix appears to have landed. Flip expect_baseline_fail=False for this "
                f"assertion in tests/test_compression_fidelity.py. ({detail})")
        print(f"BASELINE-FAIL: {name}" + (f" -- {detail}" if detail else ""))
        BASELINE_FAILURES.append(name)
        return
    if not condition:
        raise AssertionError(f"{name}: {detail}" if detail else name)
    PASSED.append(name)


# -- fixtures -----------------------------------------------------------------

_BAD_WORDS = ("remember", "always", "never", "important", "must", "should", "critical",
              "note:", "don't", "do not", "allerg", "medication", "[directive]")


def _filler(i: int) -> str:
    """Deterministic, low-salience filler text: no rescue/never-evict keyword,
    no focus match -> always scores the 0.2 recency baseline in _keep_score."""
    text = f"padding line {i} lorem ipsum dolor sit amet consectetur adipiscing elit"
    assert not any(w in text.lower() for w in _BAD_WORDS)  # guard the fixture itself
    return text


def _body(n: int, middle_content: str | None = None, middle_index: int = 3) -> list[dict]:
    """`n` plain messages (no system role); optionally pins one distinctive
    string at `middle_index` so the eviction target is unambiguous."""
    msgs = []
    for i in range(n):
        role = "user" if i % 2 == 0 else "assistant"
        content = middle_content if (middle_content is not None and i == middle_index) else _filler(i)
        msgs.append({"role": role, "content": content})
    return msgs


def _make_engine(tag: str, config_overrides: dict | None = None):
    """A ChronicleContextEngine backed by a real (temp, hashing-embedder) core.

    `config_overrides` deep-merges on top of the base {"embeddings": ...}
    config (e.g. {"context": {"default_token_budget": N}}) for tests that
    need to force real eviction under R2's per-token-budget model.
    """
    home = tempfile.mkdtemp(prefix=f"chronicle_fidelity_{tag}_")
    session_id = f"sess-{tag}"
    eng = ChronicleContextEngine()
    config = {"embeddings": {"model": "hashing"}}
    if config_overrides:
        config.update(config_overrides)
    eng.on_session_start(session_id, hermes_home=home, principal_id="tester", config=config)
    assert eng.core is not None, "test setup: engine failed to initialize a real core"
    return eng, session_id, home


def _durability_events(eng, session_id):
    evs = eng.core.store.get_events_by_session(session_id)
    return [e for e in evs if e["type"] == "observed"
            and json.loads(e["payload"]).get("source_type") == "context_eviction"]


def _patched_home(tag: str):
    """Context manager patching context.Path.home() to a disposable tempdir.

    compress()'s never-started lazy-init path (R1) resolves its default
    hermes_home via context._default_hermes_home() -> Path.home() / ".hermes"
    -- correctly expanded, unlike the pre-fix literal "~/.hermes" that
    resolved relative to cwd. Tests exercising that exact bare-engine
    codepath must not let it write a real, persistent SQLite store into the
    developer's actual $HOME while the suite runs; patching Path.home() for
    the duration keeps the test hitting the real default-resolution logic
    without touching anything outside a tempdir this test owns.
    """
    tmp_home = Path(tempfile.mkdtemp(prefix=f"chronicle_fidelity_{tag}_home_"))
    return mock.patch("context.Path.home", return_value=tmp_home)


def _recover_excerpt(events) -> str:
    """Reconstruct a durably-stored excerpt from one or more sibling
    context_eviction events. R11 chunks spans over the excerpt cap into
    sibling events ordered by chunk_index; "".join of the chunks in that
    order reproduces the original span byte for byte (same contract as
    engine.capture._split_excerpt / tests/exercise/accept_r11.py)."""
    payloads = [json.loads(e["payload"]) for e in events]
    payloads.sort(key=lambda p: p.get("chunk_index", 0))
    return "".join(p["excerpt"] for p in payloads)


# -- byte-exact I17 recovery ---------------------------------------------------

def test_i17_small_span_byte_exact():
    """A small evicted span (under the 4000-char excerpt clip) is recoverable
    byte-for-byte by re-reading the durability event(s) context.py wrote for
    it. Forced under a tight token budget: R2's real per-span token
    accounting only evicts middle spans once the (system+head+tail+never-
    evict) protected set has claimed the whole budget, so a lone small
    filler message needs a small budget to be evicted by at all -- otherwise
    it simply fits and is kept, and there is nothing to recover (R2/R11
    compose)."""
    eng, sid, _home = _make_engine("i17small", {"context": {"default_token_budget": 250}})
    target = "UNIQUE-SMALL-" + ("x" * 180)
    body = _body(10, middle_content=target)
    result = eng.compress(body)
    assert target not in [m.get("content") for m in result], \
        "setup invariant: plain low-score filler must be evicted from the window"
    evs = _durability_events(eng, sid)
    assert evs, "expected at least one context_eviction durability event for the evicted span"
    recovered = _recover_excerpt(evs)
    check("i17_small_span_byte_exact", recovered == target, expect_baseline_fail=False,
          detail=f"recovered {len(recovered)} chars via {len(evs)} event(s), expected {len(target)}")


def test_i17_large_span_byte_exact():
    """A large evicted span (over the excerpt cap) must ALSO be recoverable
    byte-for-byte. R11 chunks such spans across sibling context_eviction
    events (chunk_index/chunk_count) instead of the old lossy
    `content[:4000]` clip, so byte-exact recovery means joining every sibling
    chunk in order, not reading a single event's excerpt."""
    eng, sid, _home = _make_engine("i17large")
    target = "UNIQUE-LARGE-" + "".join(f"seg{i:05d}-" for i in range(500))
    assert len(target) > 4000, "fixture must exceed the excerpt clip to exercise the bug"
    body = _body(10, middle_content=target)
    result = eng.compress(body)
    assert target not in [m.get("content") for m in result]
    evs = _durability_events(eng, sid)
    assert evs, "expected at least one context_eviction durability event for the evicted span"
    recovered = _recover_excerpt(evs)
    check("i17_large_span_byte_exact", recovered == target, expect_baseline_fail=False,
          detail=f"recovered {len(recovered)}/{len(target)} chars via {len(evs)} chunk event(s) (R11)")


# -- fallback-mode I17 ----------------------------------------------------------

def test_fallback_i17_durability():
    """_heuristic() (used whenever self.core is None) must not drop the window
    middle with nowhere to durably store it first -- that would be an
    outright I17 violation, not just a lossy one. compress() now lazily
    inits a real core (on_session_start's own defaults) the first time it is
    reached with no explicit session start, so a bare, never-started engine
    self-heals into the memory-aware path instead of latching a permanently
    lossy fallback (R1)."""
    eng = ChronicleContextEngine()  # no on_session_start -> compress() lazy-inits one
    body = _body(14)
    target_index = 6  # inside the dropped middle: body[:3] + body[-6:] retained
    target = body[target_index]["content"]
    with _patched_home("fallback_i17"):  # see _patched_home docstring
        result = eng.compress(body)
    dropped = target not in [m.get("content") for m in result]
    durably_recoverable = eng.core is not None  # no core => no store => nothing to re-read
    check("fallback_i17_durability", not (dropped and not durably_recoverable), expect_baseline_fail=False,
          detail="heuristic fallback drops the window middle with nothing durably stored to recover "
                 "it from -- no core, no store, unrecoverable (R1)")


def test_fallback_audit_event():
    """Fallback compression must also emit the 'compressed' audit event (R1).
    A bare engine that never called on_session_start now gets a real lazy
    init from compress() itself, so it has a store to append into."""
    eng = ChronicleContextEngine()
    body = _body(14)
    with _patched_home("fallback_audit"):  # see _patched_home docstring
        eng.compress(body)
    check("fallback_audit_event", eng.core is not None, expect_baseline_fail=False,
          detail="heuristic fallback has no store to append a 'compressed' audit event into (R1)")


# -- pin survival ---------------------------------------------------------------

def test_pin_write_recorded():
    """chronicle_pin_context does durably record the pin request itself."""
    eng, _sid, _home = _make_engine("pinwrite")
    pin_content = "PIN-TARGET " + _filler(99)
    resp = json.loads(eng.handle_tool_call("chronicle_pin_context", {"content": pin_content}))
    assert resp == {"status": "pinned"}
    evs = eng.core.store.get_events_by_type("observed")
    matches = [e for e in evs if json.loads(e["payload"]).get("action") == "pin"
               and json.loads(e["payload"]).get("excerpt") == pin_content]
    check("pin_write_recorded", len(matches) == 1, expect_baseline_fail=False,
          detail=f"chronicle_pin_context should durably record the pin exactly once, found {len(matches)}")


def test_pin_span_survives_eviction():
    """A pinned span must survive compression even when its score would
    otherwise get it evicted. chronicle_pin_context writes an unlinked
    durability record; nothing maps it back to the live span, and
    _never_evict only substring-matches a fixed keyword list -- so a pinned,
    low-score span is still evicted today (R3)."""
    eng, _sid, _home = _make_engine("pinspan")
    pin_content = "PIN-TARGET " + _filler(99)
    eng.handle_tool_call("chronicle_pin_context", {"content": pin_content})
    body = _body(10, middle_content=pin_content)  # scores 0.2 -> normally evicted
    result = eng.compress(body)
    survived = pin_content in [m.get("content") for m in result]
    check("pin_span_survives_eviction", survived, expect_baseline_fail=False,
          detail="pinning does not actually protect the span by id -- the pinned, low-score span "
                 "is still evicted (R3)")


# -- focus reinjection ------------------------------------------------------------

def test_focus_reinjection_present():
    """After eviction, a durable memory relevant to the focus topic should be
    re-retrieved and injected back into the window."""
    eng, sid, _home = _make_engine("focus")
    topic = "vetappointment"
    marker = "ANSWER-9182-ZZYZX"
    eng.core.capture.append("observed",
                            {"source_type": "test_seed",
                             "excerpt": f"Regarding {topic}: {marker} is the detail to recall."},
                            actor="user", session_id=sid)
    body = _body(10)
    result = eng.compress(body, focus_topic=topic)
    injected = [m for m in result if m.get("role") == "system" and marker in (m.get("content") or "")]
    check("focus_reinjection_present", len(injected) >= 1, expect_baseline_fail=False,
          detail=f"expected a retrieved memory containing {marker!r} re-injected for "
                 f"focus_topic={topic!r}, found {len(injected)} matching system spans")


# -- output fits budget ------------------------------------------------------------

def test_output_fits_token_budget():
    """compress() must guarantee its output fits within the configured token
    budget. Today it bounds by MESSAGE COUNT only (protect_first_n/
    protect_last_n) and reads no token budget at all, so large protected
    spans blow straight through it (R2)."""
    eng, _sid, _home = _make_engine("budget")
    budget_tokens = eng.core.cfg.get("context.default_token_budget", 1500)
    big = "B" * 2000  # ~500 tokens at the ~4-chars/token estimate used below
    body = ([{"role": "user", "content": f"HEAD{i} " + big} for i in range(3)]
            + [{"role": "assistant" if i % 2 else "user", "content": f"MID{i} " + _filler(i)}
               for i in range(4)]
            + [{"role": "assistant", "content": f"TAIL{i} " + big} for i in range(6)])
    result = eng.compress(body)
    approx_tokens = sum(len(m.get("content") or "") for m in result) / 4.0
    check("output_fits_token_budget", approx_tokens <= budget_tokens, expect_baseline_fail=False,
          detail=f"~{approx_tokens:.0f} tokens vs context.default_token_budget={budget_tokens} "
                 f"-- compress() does not account for tokens, only message count (R2)")


# -- replay determinism -------------------------------------------------------------

def test_replay_determinism_partition():
    """The same input, compressed twice, must partition into the same
    kept/evicted/retained window both times."""
    eng, _sid, _home = _make_engine("replay")
    body = ([{"role": "user", "content": f"HEAD{i} " + _filler(i)} for i in range(4)]
            + [{"role": "assistant" if i % 2 else "user", "content": f"MID{i} " + _filler(100 + i)}
               for i in range(5)]
            + [{"role": "assistant", "content": f"TAIL{i} " + _filler(200 + i)} for i in range(6)])
    result1 = eng.compress(copy.deepcopy(body), focus_topic=None)
    result2 = eng.compress(copy.deepcopy(body), focus_topic=None)
    check("replay_determinism_partition", result1 == result2, expect_baseline_fail=False,
          detail="compress() should deterministically partition identical input the same way "
                 "across repeated calls")


def test_replay_from_audit_log_has_span_ids():
    """The 'compressed' audit event should carry enough information (evicted
    span ids) to replay/reconstruct the window from the log alone (R6)."""
    eng, _sid, _home = _make_engine("auditlog")
    # Oversized protected content (head/tail) forces a genuine eviction: R2's
    # real per-span token accounting means a single small, low-score middle
    # span fits under the ~1500-token default budget and is KEPT. Oversized
    # head/tail spends the whole budget on protected content, so the scored
    # middle span has no room left and is reliably evicted.
    big = "B" * 6000
    body = ([{"role": "user", "content": f"HEAD{i} " + big} for i in range(3)]
            + [{"role": "user", "content": "AUDIT-TARGET " + _filler(999)}]
            + [{"role": "assistant", "content": f"TAIL{i} " + big} for i in range(6)])
    result = eng.compress(body)
    assert "AUDIT-TARGET" not in " ".join(m.get("content") or "" for m in result), \
        "setup invariant: the scored middle span must be evicted once head/tail exhaust the budget"
    events = eng.core.store.get_events_by_type("compressed")
    assert events, "compress() should emit a 'compressed' audit event"
    payload = json.loads(events[-1]["payload"])
    evicted = payload.get("evicted_spans")
    check("replay_from_audit_log_has_span_ids", isinstance(evicted, list) and len(evicted) > 0,
          expect_baseline_fail=False,
          detail=f"'compressed' audit payload should store evicted span ids, not a count "
                 f"({evicted!r}) -- the window must be replayable from the log alone (R6)")


# -- prefix stability ------------------------------------------------------------------

def test_prefix_stability_across_growth():
    """A span that was protected (tail) on one pass must not silently drop out
    once the conversation grows and it slides into the scored middle on a
    later pass -- compress() should keep the prefix append-only-stable rather
    than re-scoring the whole window from scratch every time (R5)."""
    eng, _sid, _home = _make_engine("prefix")
    v1 = _body(10)  # head(3) + 1 scored middle + tail(6)
    result1 = eng.compress([dict(m) for m in v1], focus_topic=None)
    tail_v1_contents = {m["content"] for m in v1[-6:]}
    retained_tail_v1 = tail_v1_contents & {m.get("content") for m in result1}
    assert retained_tail_v1 == tail_v1_contents, \
        "setup invariant: protect_last_n must retain the tail on the first pass"

    v2 = v1 + [{"role": "assistant" if i % 2 else "user", "content": f"GROWTH{i} " + _filler(300 + i)}
               for i in range(6)]
    result2 = eng.compress([dict(m) for m in v2], focus_topic=None)
    result2_contents = {m.get("content") for m in result2}
    still_present = tail_v1_contents & result2_contents
    check("prefix_stability_across_growth", still_present == tail_v1_contents, expect_baseline_fail=False,
          detail=f"{len(tail_v1_contents - still_present)}/{len(tail_v1_contents)} previously "
                 f"tail-protected spans were evicted once the conversation grew and they slid into "
                 f"the rescored middle (R5)")


# -- audit event emitted -----------------------------------------------------------------

def test_audit_event_emitted_memory_aware():
    """Memory-aware compression does emit a 'compressed' audit event for the
    session (this part already works today)."""
    eng, sid, _home = _make_engine("auditok")
    body = _body(10, middle_content="AUDIT-OK " + _filler(1))
    eng.compress(body)
    events = eng.core.store.get_events_by_type("compressed")
    matches = [e for e in events if e.get("session_id") == sid]
    check("audit_event_emitted_memory_aware", len(matches) >= 1, expect_baseline_fail=False,
          detail="memory-aware compress() should append a 'compressed' audit event for the session")


# -- standalone runner ------------------------------------------------------------------

if __name__ == "__main__":
    import traceback

    tests = [(n, f) for n, f in sorted(globals().items())
             if n.startswith("test_") and callable(f)]
    unexpected: list[tuple[str, BaseException]] = []
    for name, fn in tests:
        try:
            fn()
        except BaseException as e:  # noqa: BLE001 - report every kind, then decide the exit code
            unexpected.append((name, e))
            print(f"REAL-FAIL: {name}: {type(e).__name__}: {e}")

    print()
    print(f"compression-fidelity baseline: {len(tests)} checks run, {len(PASSED)} passed, "
          f"{len(BASELINE_FAILURES)} documented BASELINE-FAIL, {len(unexpected)} unexpected.")
    if BASELINE_FAILURES:
        print("Documented baseline gaps (expected, tracked against R1-R11):")
        for name in BASELINE_FAILURES:
            print(f"  - {name}")

    if unexpected:
        print()
        for name, e in unexpected:
            print(f"--- {name} ---")
            traceback.print_exception(type(e), e, e.__traceback__)
        sys.exit(1)
    sys.exit(0)
