"""
Chronicle — a host's turn does not wait for curation.

Hermes calls the provider's on_turn_start synchronously, before the model, and
on_turn_start drained a slice of the curation queue (core.tick). On the
production VPS that slice includes embed jobs against a CPU-bound embedding
server, so a user's turn could wait out a request timeout -- and once that
timeout is raised far enough for a long excerpt to embed at all, it would wait
for minutes. A host (the provider, the context engine) now moves the slice onto
one background thread per core; a core used directly drains where it is called.

Fixtures use obviously fake values.
"""

import shutil
import sys
import threading
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from _tmp_support import temp_home

from engine.core import ChronicleCore

CFG = {"embeddings": {"model": "hashing"}}


def _wait_for(pred, seconds=5.0):
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        if pred():
            return True
        time.sleep(0.01)
    return pred()


class _Core(unittest.TestCase):
    background_drain = True              # conftest: leave drain_in_background real

    def setUp(self):
        self.home = temp_home(prefix="bgdrain_")
        self.core = ChronicleCore.get(self.home, CFG)

    def tearDown(self):
        ChronicleCore._instances.pop(self.home, None)
        shutil.rmtree(self.home, ignore_errors=True)


class TestTheTurnDoesNotWait(_Core):
    def test_a_host_turn_returns_while_the_slice_runs(self):
        self.core.drain_in_background()
        started, release, done = threading.Event(), threading.Event(), threading.Event()

        def slow(max_jobs=None):
            started.set()
            release.wait(5)
            done.set()
            return 0
        self.core.curation.drain = slow
        t = time.monotonic()
        self.core.tick()
        self.assertLess(time.monotonic() - t, 0.5, "the turn waited for the slice")
        self.assertTrue(started.wait(2), "the slice never ran")
        release.set()
        self.assertTrue(done.wait(2))

    def test_one_worker_and_kicks_coalesce(self):
        self.core.drain_in_background()
        calls, gate = [], threading.Event()

        def drain(max_jobs=None):
            calls.append(threading.current_thread())
            gate.wait(2)
            return 0
        self.core.curation.drain = drain
        for _ in range(20):
            self.core.tick()
        self.assertTrue(_wait_for(lambda: calls))
        gate.set()
        time.sleep(0.2)
        self.assertLessEqual(len(calls), 2, "twenty kicks during one pass are one more pass")
        self.assertEqual({t.name for t in calls}, {"chronicle-curation"})
        self.assertEqual(len({id(t) for t in calls}), 1, "one worker per core")

    def test_a_failing_slice_does_not_stop_the_worker(self):
        self.core.drain_in_background()
        n, second = [0], threading.Event()

        def drain(max_jobs=None):
            n[0] += 1
            if n[0] == 1:
                raise RuntimeError("a bad job")
            second.set()
            return 0
        self.core.curation.drain = drain
        self.core.tick()
        self.assertTrue(_wait_for(lambda: n[0] == 1))
        self.core.tick()
        self.assertTrue(second.wait(2), "the worker died with the first failure")

    def test_the_real_queue_is_drained_on_the_worker(self):
        self.core.drain_in_background()
        self.core.initialize("20260917_111111_aa11bb", principal_id="default")
        ran_on = []
        real = self.core.curation._task_extract

        def recording(payload):
            ran_on.append(threading.current_thread().name)
            return real(payload)
        self.core.curation._task_extract = recording
        self.core.capture.observe("My name is Sam Vimes and I work at Acme Fake Co.", "Noted.",
                                  session_id="20260917_111111_aa11bb")
        self.core.tick()
        self.assertTrue(_wait_for(lambda: ran_on), "no extract job ran")
        self.assertEqual(set(ran_on), {"chronicle-curation"})


class TestWhoTurnsItOn(_Core):
    def test_a_core_used_directly_drains_where_it_is_called(self):
        here = []
        self.core.curation.drain = lambda max_jobs=None: here.append(threading.current_thread())
        self.core.tick()
        self.assertEqual(here, [threading.current_thread()])

    def test_the_provider(self):
        from provider import ChronicleMemoryProvider
        p = ChronicleMemoryProvider()
        p.initialize("20260917_121212_bb22cc", hermes_home=self.home, principal_id="default",
                     config=CFG)
        self.assertTrue(p.core._drain_in_background)

    def test_the_first_session_start_does_not_wait_either(self):
        """initialize() drains one slice once per process (crash recovery); a
        host has switched to the worker before that, so it runs there too."""
        from provider import ChronicleMemoryProvider
        release = threading.Event()
        self.core.curation.drain = lambda max_jobs=None: release.wait(5) and 0
        p = ChronicleMemoryProvider()
        t = time.monotonic()
        p.initialize("20260917_151515_ee55ff", hermes_home=self.home, principal_id="default",
                     config=CFG)
        took = time.monotonic() - t
        release.set()
        self.assertLess(took, 1.0, "session start waited for the recovery slice")

    def test_the_switch(self):
        from provider import ChronicleMemoryProvider
        home = temp_home(prefix="bgdrain_off_")
        try:
            p = ChronicleMemoryProvider()
            p.initialize("20260917_131313_cc33dd", hermes_home=home, principal_id="default",
                         config={**CFG, "curation": {"drain": {"background": False}}})
            self.assertFalse(p.core._drain_in_background)
        finally:
            ChronicleCore._instances.pop(home, None)
            shutil.rmtree(home, ignore_errors=True)

    def test_the_context_engine(self):
        from context import ChronicleContextEngine
        eng = ChronicleContextEngine()
        eng.on_session_start("20260917_141414_dd44ee", hermes_home=self.home,
                             principal_id="default", config=CFG)
        core = eng.core
        self.assertIsNotNone(core)
        self.assertTrue(core._drain_in_background)


if __name__ == "__main__":
    unittest.main()
