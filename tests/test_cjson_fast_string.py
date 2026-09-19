"""
Chronicle — CJSON strings through the C encoder, byte for byte.

Every event id and span id hashes CJSON of the full text. Encoding strings one
character at a time in Python was 12 s of a 17 s compaction on the production
box; the standard library's `encode_basestring` applies the same rule in C.
An id that changed would break idempotency (I2) and every stored reference, so
the two are compared over every code point.
"""

import random
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from engine import serialize as S


class TestTheSameBytes(unittest.TestCase):
    def test_every_code_point(self):
        bad = [cp for cp in range(0x110000) if S._cjson_str(chr(cp)) != S._cjson_str_py(chr(cp))]
        self.assertEqual(bad, [])

    def test_mixed_strings(self):
        rnd = random.Random(11)
        pool = [chr(i) for i in range(0x80)] + [chr(c) for c in (0xE9, 0x2028, 0xD800, 0x1F600, 0x7F)]
        for _ in range(20000):
            s = "".join(rnd.choice(pool) for _ in range(rnd.randint(0, 30)))
            self.assertEqual(S._cjson_str(s), S._cjson_str_py(s))

    def test_ids_are_unchanged(self):
        """The same event id and span-style hash whichever encoder runs."""
        from unittest import mock
        args = ("observed", {"excerpt": "Pat Testley \u2014 \"quoted\"\n\tAcme Fake Co\x01",
                             "n": 3, "ok": True, "tags": ["a", "\u00e9"]},
                ["ev_b", "ev_a"], "user", "2026-09-18T00:00:00.000Z")
        fast = S.event_id(*args)
        with mock.patch.object(S, "_cjson_str", S._cjson_str_py):
            slow = S.event_id(*args)
        self.assertEqual(fast, slow)


if __name__ == "__main__":
    unittest.main()
