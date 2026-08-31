#!/usr/bin/env python3
"""Acceptance test for L8 — evidence-forward get_context().

Diagnosis (measured, judged run on v5.5.0): get_context() returned
reader-hostile context. A judged reader (gpt-4o) given the full 12k-token
get_context output abstained ("I don't know") on 30/30 questions EVEN WHEN
the answer was present in the context — because get_context LED with noise:
~20 [DIRECTIVE] lines (norm notes like "Remember to listen to your body"),
[CONTRADICTION]/[CRITICAL] markers, before the actual [SESSION] evidence. The
same reader given a short slice containing only the evidence answered
correctly; given the full noisy context it abstained. The r1 "raw evidence
first, directives/digests from leftover budget only" priority rule was being
violated in practice: the directive/critical/contradiction block was written
BEFORE evidence and was never itself budget-checked, so it could (and did)
push evidence down and flood the reader.

This reproduces that shape directly against get_context()'s own output — no
reader LLM required, so it also runs as a fast, deterministic acceptance
check: a synthetic store with 30 norm-directive notes (unrelated reminders,
always_inject=1 — exactly what the old unconditional block would have led
with) and ONE evidence turn buried among them ("graduated with a degree in
Acme Studies"). After the L8 fix:

  (a) the evidence lands within the FIRST 2000 chars of a 12k-token budget
      (48000 chars) — i.e. a reader encounters it before the noise tail;
  (b) at most 5 [DIRECTIVE] lines appear in total, regardless of how many
      always_inject notes the store holds (context.max_directives, default
      5 — the old block took the first 20 in store order, uncapped).

Fake data only ("Acme Studies", "Test University"): no real deployment store
is referenced, here or in engine/.
"""
import os
import sys
import tempfile

chronicle_dir = os.environ.get("CHRONICLE_DIR") or os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "..", "..")
sys.path.insert(0, chronicle_dir)

from engine.core import ChronicleCore

QUESTION = "What degree did I graduate with?"
EVIDENCE_TURN = "I graduated with a degree in Acme Studies from Test University."
EVIDENCE_NEEDLE = "graduated with a degree in acme studies"

# 30 unrelated "Remember to ..." reminders — the HeuristicExtractor's norm
# pattern (engine/extraction.py: r"\b(always|never|don'?t|do not|remember to|
# must)\b") reliably classifies these as note_type='norm', always_inject=1 —
# exactly the always-injected directive shape the old unconditional block in
# get_context() led with. None of them share a token with QUESTION/EVIDENCE.
_REMINDER_TOPICS = [
    "listen to your body", "take breaks between long tasks", "stay hydrated",
    "back up your files weekly", "double check the shipping address",
    "water the office plants", "silence notifications during focus time",
    "review the calendar on Monday morning", "stretch after sitting for an hour",
    "log off before midnight", "keep the workspace tidy", "recycle the paper",
    "check the smoke detector batteries", "rotate the tires every 6 months",
    "renew the parking permit", "confirm the meeting room booking",
    "label the leftovers in the fridge", "charge the spare battery",
    "close the garage door at night", "feed the office fish on Fridays",
    "lock the bike properly", "wipe down the whiteboard after use",
    "restock the printer paper", "test the fire extinguisher yearly",
    "update the emergency contact list", "clear the browser cache monthly",
    "empty the recycling bin", "check tire pressure before a road trip",
    "send the weekly status update", "archive old email threads",
]
assert len(_REMINDER_TOPICS) == 30


def _build_core():
    home = tempfile.mkdtemp()
    core = ChronicleCore(home, {"embeddings": {"model": "hashing"}})
    core.initialize("s1", principal_id="assistant")
    return core, home


def _seed(core):
    # 30 unrelated norm-directive notes — deliberately unrelated to QUESTION,
    # so any that reach ctx do so only through the unconditional (count-
    # capped) block, never the topic-gated (§r6) one.
    for i, topic in enumerate(_REMINDER_TOPICS):
        core.capture.observe("Remember to %s." % topic, "", session_id="reminders",
                             occurred_at="2024-01-01T00:%02d:00Z" % i)
    # One evidence-bearing turn, buried among the reminders.
    core.capture.observe(EVIDENCE_TURN, "", session_id="s1",
                         occurred_at="2024-06-15T10:00:00Z")
    core.process_pending()


def test_directives_capped_and_evidence_leads():
    core, home = _build_core()
    try:
        _seed(core)

        rows = core.store.query_beliefs(
            "notes", "always_inject=1 AND status='active'", (), 200)
        assert len(rows) >= 30, \
            f"fixture needs >=30 always_inject notes, got {len(rows)}"
        print(f"  fixture: {len(rows)} always_inject norm notes seeded")

        ctx = core.retrieval.get_context(QUESTION, token_budget=12000)

        # (a) evidence within the first 2000 chars.
        low = ctx.lower()
        idx = low.find(EVIDENCE_NEEDLE)
        assert idx != -1, f"evidence never reached ctx at all:\n{ctx[:2000]}"
        assert idx < 2000, \
            f"evidence reached ctx but not until char {idx} (must be <2000):\n{ctx[:2200]}"
        print(f"  PASS: evidence found at char {idx} (<2000)")

        # (b) at most context.max_directives [DIRECTIVE] lines, total —
        # across BOTH the unconditional block and the §r6 topic-gated
        # addendum, however much of the 48000-char budget is left over.
        max_directives = core.cfg.get("context.max_directives", 5)
        directive_lines = [ln for ln in ctx.split("\n") if ln.startswith("[DIRECTIVE]")]
        assert len(directive_lines) <= max_directives, \
            (f"expected at most {max_directives} [DIRECTIVE] lines, got "
             f"{len(directive_lines)}: {directive_lines}")
        print(f"  PASS: {len(directive_lines)} [DIRECTIVE] line(s) <= cap ({max_directives})")

        # And the noise tail as a whole never dominates: directive+critical+
        # contradiction bytes stay within ~15% of the 48000-char budget.
        noise_chars = sum(len(ln) + 1 for ln in ctx.split("\n")
                          if ln.startswith(("[DIRECTIVE]", "[CONTRADICTION]", "[CRITICAL]")))
        cap = 12000 * 4 * 0.15
        assert noise_chars <= cap + 1, \
            f"noise tail spent {noise_chars} chars, over the ~15% ceiling ({cap:.0f})"
        print(f"  PASS: noise tail {noise_chars} chars <= ~15% ceiling ({cap:.0f})")
    finally:
        import shutil
        shutil.rmtree(home, ignore_errors=True)


def test_tight_budget_still_favors_evidence():
    """Even at a budget too small for the whole store's directives, evidence
    keeps first claim (r1) — this is the scenario a naive 'just cap directive
    count' fix would still get wrong if noise weren't also budget-checked
    itself, not just count-checked."""
    core, home = _build_core()
    try:
        _seed(core)
        ctx = core.retrieval.get_context(QUESTION, token_budget=300)
        assert len(ctx) <= 300 * 4 + len("\n… (truncated)"), \
            f"context exceeded its hard budget: {len(ctx)} chars"
        low = ctx.lower()
        assert EVIDENCE_NEEDLE in low or "acme studies" in low, \
            f"tight budget dropped evidence entirely, kept only:\n{ctx}"
        print(f"  PASS: tight budget (300 tokens) still surfaces evidence "
              f"({len(ctx)} chars total)")
    finally:
        import shutil
        shutil.rmtree(home, ignore_errors=True)


if __name__ == "__main__":
    test_directives_capped_and_evidence_leads()
    test_tight_budget_still_favors_evidence()
    print("\nAll acceptance tests passed.")
