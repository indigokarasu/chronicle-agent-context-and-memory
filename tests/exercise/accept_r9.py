"""
Acceptance — R9: Pressure warning span at the high watermark (issue #2 R9).

Spec: "Emit an advisory span when window pressure crosses the high watermark
so the agent can pin/save before forced compression."

context.py adds `is_under_pressure()`, `_pressure_warning_span()`, and a
`_pressure_warning_injected` latch so compress() emits a one-shot system-role
advisory the first time `last_prompt_tokens` reaches `threshold_tokens` (the
HIGH watermark, §R2), then stays quiet until `update_from_response` observes
the window drop back below it.

A first cut of this shipped with two real bugs, both reproduced and fixed
here:

  (1) Latch-without-delivery. compress()'s small-body early return
      (`len(body) <= protect_first_n + protect_last_n: return messages`) ran
      AFTER the warning flag was already set True, so under sustained
      pressure with a small message list the flag latched but the warning
      never reached the caller -- permanently, since the flag only resets on
      dropping back below the watermark. Fixed by computing "should we warn"
      without mutating state, and only latching inside the single helper
      (_emit_pressure_warning) that every compress() return path funnels
      through, at the point the warning is actually spliced into the output.

  (2) Unbudgeted append. The warning span used to be appended to `output`
      AFTER budget-fitting, so its tokens were never counted against the R2
      "compress() output <= budget" guarantee -- reproduced on the existing
      oversized-tail fixture (context_length=1000 -> budget=550): output
      landed at 615 tokens. Fixed by routing the warning through the same
      budget accounting (`used`/`budget`) as everything else, clipping or
      (if there's no room at all) skipping it -- never latching on a skip.

Both are exercised below, plus the basic crossing/no-crossing/one-shot/
re-arm behavior the feature is supposed to have.

Run: python3 tests/exercise/accept_r9.py
"""

import sys
import shutil
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))

from engine.embeddings import estimate_tokens                                  # noqa: E402
from context import ChronicleContextEngine                                     # noqa: E402

CFG = {"embeddings": {"model": "hashing"}}  # offline, deterministic

_WARNING_MARK = "[Context pressure warning]"


def _msg(role, text):
    return {"role": role, "content": text}


def _filler_body(n):
    return [_msg("user" if i % 2 == 0 else "assistant", "padding %d %s" % (i, "pad " * 8))
            for i in range(n)]


def _make_engine(tag):
    home = tempfile.mkdtemp(prefix=f"accept_r9_{tag}_")
    eng = ChronicleContextEngine()
    eng.on_session_start(f"r9-{tag}", hermes_home=home, principal_id="tester", config=CFG)
    assert eng.core is not None, "test setup: engine failed to initialize a real core"
    return eng, home


def _output_tokens(out):
    return sum(estimate_tokens(m.get("content")) for m in out)


def _has_warning(out):
    return any(m.get("role") == "system" and _WARNING_MARK in (m.get("content") or "") for m in out)


def test_warning_emitted_on_crossing_high_watermark():
    """Basic case: prompt tokens at/above the HIGH watermark -> a pressure
    span is present in compress()'s output."""
    eng, home = _make_engine("cross")
    try:
        eng.update_model("test-model", context_length=2000)  # threshold = 1500
        messages = [_msg("system", "sys")] + _filler_body(20)
        eng.update_from_response({"prompt_tokens": eng.threshold_tokens,
                                  "completion_tokens": 0, "total_tokens": eng.threshold_tokens})
        out = eng.compress(list(messages), focus_topic=None)
        assert _has_warning(out), "expected a pressure-warning span once prompt tokens reach the HIGH watermark"
        print("PASS: pressure warning present once prompt tokens reach the high watermark")
    finally:
        shutil.rmtree(home, ignore_errors=True)


def test_no_warning_below_high_watermark():
    """Below the watermark: no advisory span, ever."""
    eng, home = _make_engine("nopressure")
    try:
        eng.update_model("test-model", context_length=2000)
        messages = [_msg("system", "sys")] + _filler_body(20)
        eng.update_from_response({"prompt_tokens": eng.threshold_tokens - 100,
                                  "completion_tokens": 0, "total_tokens": 0})
        out = eng.compress(list(messages), focus_topic=None)
        assert not _has_warning(out), "no warning expected below the high watermark"
        print("PASS: no pressure warning below the high watermark")
    finally:
        shutil.rmtree(home, ignore_errors=True)


def test_warning_fires_once_then_rearms_after_dropping_below():
    """One-shot per crossing: a second call under the SAME sustained
    pressure must not repeat the warning (no spam); dropping back below the
    watermark and crossing again re-arms it."""
    eng, home = _make_engine("rearm")
    try:
        eng.update_model("test-model", context_length=2000)
        messages = [_msg("system", "sys")] + _filler_body(20)

        eng.update_from_response({"prompt_tokens": eng.threshold_tokens,
                                  "completion_tokens": 0, "total_tokens": 0})
        out1 = eng.compress(list(messages), focus_topic=None)
        assert _has_warning(out1), "first crossing should deliver the warning"

        out2 = eng.compress(list(messages), focus_topic=None)
        assert not _has_warning(out2), (
            "warning must not repeat on every call while pressure stays sustained (spam)")

        eng.update_from_response({"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0})
        eng.update_from_response({"prompt_tokens": eng.threshold_tokens,
                                  "completion_tokens": 0, "total_tokens": 0})
        out3 = eng.compress(list(messages), focus_topic=None)
        assert _has_warning(out3), "should warn again after dropping below the watermark and re-crossing"
        print("PASS: warning fires once per crossing, re-arms after a drop below the watermark")
    finally:
        shutil.rmtree(home, ignore_errors=True)


def test_small_body_shortcut_still_delivers_the_warning_bug1():
    """Regression (1): under pressure with a body small enough to hit
    compress()'s early return (len(body) <= protect_first_n + protect_last_n),
    the warning must actually reach the caller -- and the internal latch
    (`_pressure_warning_injected`) must never disagree with whether it did.
    The original bug set the latch True on this path while never inserting
    the span, permanently starving the warning for the rest of the session."""
    eng, home = _make_engine("smallbody")
    try:
        eng.update_model("test-model", context_length=2000)
        small_body = _filler_body(4)  # 4 <= protect_first_n(3) + protect_last_n(6) -> early return
        messages = [_msg("system", "sys")] + small_body
        assert len(small_body) <= eng.protect_first_n + eng.protect_last_n, \
            "fixture must be small enough to hit compress()'s early-return shortcut"

        eng.update_from_response({"prompt_tokens": eng.threshold_tokens,
                                  "completion_tokens": 0, "total_tokens": 0})
        out = eng.compress(list(messages), focus_topic=None)

        delivered = _has_warning(out)
        assert delivered, "the small-body shortcut must still deliver the pressure warning"
        assert eng._pressure_warning_injected == delivered, (
            "internal latch must agree with what was actually delivered "
            f"(latch={eng._pressure_warning_injected}, delivered={delivered})")

        # every original message must still be present, untouched, alongside the warning
        original_contents = [m.get("content") for m in messages]
        out_contents = [m.get("content") for m in out]
        for c in original_contents:
            assert c in out_contents, f"small-body shortcut must not drop original content: {c!r}"
        print("PASS: small-body early-return path delivers the warning; latch matches delivery")
    finally:
        shutil.rmtree(home, ignore_errors=True)


def test_budget_guarantee_holds_with_warning_under_pressure_bug2():
    """Regression (2): the oversized-protected-tail fixture (the same shape
    as the R2 watermark test) combined with sustained pressure. Before the
    fix this landed at 615 tokens against a budget of 550 because the warning
    span was appended after budget-fitting, uncounted."""
    eng, home = _make_engine("budget")
    try:
        eng.update_model("test-model", context_length=1000)  # budget = 0.55*1000 = 550, threshold = 750
        huge = "Acme Fake Co tool output: " + ("x" * 6000)  # ~2009 tokens alone, > budget
        messages = (
            [_msg("system", "sys")]
            + [_msg("user", "head %d" % i) for i in range(3)]
            + [_msg("user", "middle filler %d %s" % (i, "pad " * 20)) for i in range(10)]
            + [_msg("assistant", "tail %d" % i) for i in range(5)]
            + [_msg("assistant", huge)]  # lands inside protect_last_n
        )
        eng.update_from_response({"prompt_tokens": eng.threshold_tokens,
                                  "completion_tokens": 0, "total_tokens": 0})
        out = eng.compress(list(messages), focus_topic=None)
        budget = eng._target_budget()
        total = _output_tokens(out)
        assert total <= budget, (
            f"compress() exceeded its own budget with the pressure warning included: "
            f"{total} tokens > {budget} budget")
        assert any("Acme Fake Co tool output:" in (m.get("content") or "") for m in out), (
            "the oversized protected span must stay present (clipped), not be dropped")
        print(f"PASS: {total} tokens <= {budget} budget even with a pressure warning under an "
              f"already-tight oversized-protected-tail fixture "
              f"(warning delivered={_has_warning(out)})")
    finally:
        shutil.rmtree(home, ignore_errors=True)


def test_no_warning_without_a_model_window():
    """context_length never set (update_model not called): is_under_pressure
    must stay False -- there is no watermark to have crossed."""
    eng, home = _make_engine("nowindow")
    try:
        messages = [_msg("system", "sys")] + _filler_body(20)
        eng.last_prompt_tokens = 10 ** 9  # absurdly large; must not matter with context_length == 0
        assert eng.context_length == 0
        out = eng.compress(list(messages), focus_topic=None)
        assert not _has_warning(out), "no watermark is defined without a reported model window"
        print("PASS: no pressure warning when context_length is unset")
    finally:
        shutil.rmtree(home, ignore_errors=True)


if __name__ == "__main__":
    test_warning_emitted_on_crossing_high_watermark()
    test_no_warning_below_high_watermark()
    test_warning_fires_once_then_rearms_after_dropping_below()
    test_small_body_shortcut_still_delivers_the_warning_bug1()
    test_budget_guarantee_holds_with_warning_under_pressure_bug2()
    test_no_warning_without_a_model_window()
    print("\nAll R9 acceptance tests passed.")
