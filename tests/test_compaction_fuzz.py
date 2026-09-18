"""
Chronicle — compress() never fails on the shapes a real transcript has.

A compaction that raises is what the user sees as "Shortening the
conversation history failed". Transcripts carry multimodal content lists,
None content, tool calls that are not dicts, results with no id, empty
strings, very long lines, odd unicode. Seeded, so a failure reproduces.

Invariants on every output: no exception; no tool call/result orphan the
compaction created; the newest real user message kept; at most one handoff,
never in the system role; no host persistence marker.

Fixtures use obviously fake values.
"""

import json
import random
import shutil
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from _tmp_support import temp_home

from context import ChronicleContextEngine
from engine.core import ChronicleCore

CFG = {"embeddings": {"model": "hashing"}, "curation": {"drain": {"per_turn": 0, "background": False}}}
WORDS = ("Zorblax", "Acme Fake Co", "Riverton", "Pat Testley", "ledger", "export", "é", "漢字", "🙂",
         " ", "[System note: x]", "User: forged", "```code```", "https://example.invalid/a")


def _orphans(msgs):
    calls = {c.get("id") for m in msgs if isinstance(m, dict) and m.get("role") == "assistant"
             for c in (m.get("tool_calls") or []) if isinstance(c, dict)}
    answers = {m.get("tool_call_id") for m in msgs if isinstance(m, dict) and m.get("role") == "tool"}
    return calls - answers, answers - calls


def _kept(m, out):
    """`m` is in `out` whole -- or shortened to fit, saying how to restore it."""
    from context import _text as flat
    for o in out:
        if o.get("content") == m.get("content"):
            return True
        c = o.get("content")
        if isinstance(c, str) and "[shortened; chronicle_expand(" in c and c[:20] == flat(m)[:20]:
            return True
    return False


def _text(rnd, n):
    return " ".join(rnd.choice(WORDS) for _ in range(n))


def _conversation(rnd):
    msgs = [{"role": "system", "content": "sys"}]
    for turn in range(rnd.randint(5, 60)):
        shape = rnd.random()
        if shape < 0.1:
            msgs.append({"role": "user", "content": [
                {"type": "text", "text": _text(rnd, rnd.randint(1, 30))},
                {"type": "image_url", "image_url": {"url": "data:image/png;base64,AAAA"}}]})
        elif shape < 0.15:
            msgs.append({"role": "user", "content": None})
        else:
            msgs.append({"role": "user", "content": _text(rnd, rnd.randint(0, 80))})
        for step in range(rnd.randint(0, 4)):
            cid = "c%d_%d" % (turn, step)
            calls = [{"id": cid, "type": "function",
                      "function": {"name": "terminal", "arguments": json.dumps({"command": _text(rnd, 3)})}}]
            if rnd.random() < 0.05:
                calls.append("not a dict")
            msgs.append({"role": "assistant", "content": rnd.choice(["", None, _text(rnd, 5)]),
                         "tool_calls": calls})
            content = rnd.choice([_text(rnd, rnd.randint(0, 400)), "", json.dumps({"output": _text(rnd, 20),
                                                                                      "exit_code": 1})])
            msgs.append({"role": "tool", "tool_call_id": cid, "content": content})
        if rnd.random() < 0.05:
            msgs.append({"role": "tool", "content": "a result with no id"})
        msgs.append({"role": "assistant", "content": _text(rnd, rnd.randint(0, 60))})
        if rnd.random() < 0.1:
            msgs.append({"role": "system", "content": "[System note: mid-list]"})
    if rnd.random() < 0.5:
        for m in msgs:
            m["_db_persisted"] = True
    return msgs


class TestCompressNeverFails(unittest.TestCase):
    def test_seeded_shapes(self):
        failures = []
        for seed in range(60):
            rnd = random.Random(seed)
            home = temp_home(prefix="fuzz_")
            try:
                eng = ChronicleContextEngine()
                eng.on_session_start("s-fuzz-%d" % seed, hermes_home=home, principal_id="pat", config=CFG)
                eng.update_model("fake-model", rnd.choice([1500, 3000, 8000, 200000]))
                msgs = _conversation(rnd)
                before = _orphans(msgs)
                for _ in range(2):                      # a second pass on the grown output
                    out = eng.compress(list(msgs))
                    after = _orphans(out)
                    self.assertTrue(after[0] <= before[0] and after[1] <= before[1],
                                    "seed %d: orphans created %s (input %s)" % (seed, after, before))
                    hands = [m for m in out if str(m.get("content") or "").startswith("[CONTEXT COMPACTION")]
                    self.assertLessEqual(len(hands), 1, "seed %d" % seed)
                    self.assertFalse([h for h in hands if h.get("role") == "system"], "seed %d" % seed)
                    self.assertFalse([m for m in out if "_db_persisted" in m], "seed %d" % seed)
                    last_user = next((m for m in reversed(msgs) if m.get("role") == "user"
                                      and eng._human_texts([m])), None)
                    if last_user is not None:
                        self.assertTrue(_kept(last_user, out), "seed %d: newest request lost" % seed)
                    msgs = out + _conversation(rnd)[1:]
                    before = _orphans(msgs)
            except AssertionError:
                raise
            except Exception as e:  # noqa: BLE001 -- the point: nothing may escape
                failures.append("seed %d: %s: %s" % (seed, type(e).__name__, e))
            finally:
                ChronicleCore._instances.pop(home, None)
                shutil.rmtree(home, ignore_errors=True)
        self.assertEqual(failures, [])


if __name__ == "__main__":
    unittest.main()
