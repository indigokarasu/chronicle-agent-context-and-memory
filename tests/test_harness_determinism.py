"""
Chronicle — the SUITE'S OWN gate is reproducible.

THE DEFECT. `tests/conftest.py` pinned `PYTHONHASHSEED` for CHILD processes
only — it said so, in a comment: "Cannot change this process's hash seed (it is
fixed at interpreter start), but every child process the suite spawns gets a
fixed one." True, and it left the process that COLLECTS, ORDERS AND RUNS every
test on whatever seed the OS drew. So the four documented modes were not
reproducible, and every "1700 passed / 1 skipped" this program recorded carried
an input nobody wrote down. A gate that cannot be re-run is not a gate; it is
an observation.

This is the project's signature bug one level up. `query_understanding` joined
a `set` into the text it embedded, so the query vector changed per process and
three investigations blamed float jitter; A15 then found five more surfaces of
the same class. Those are tested in `test_precision_packing.py` and
`test_replay_determinism.py` by running the subject under five seeds and
comparing bytes. This file tests the thing that runs THOSE: the harness.

WHAT ACTUALLY BINDS IT. `conftest._bind_parent_hash_seed` re-execs the
interpreter under `PYTHONHASHSEED=0` when it did not start with one — a
documented invocation can be advice, and advice does not bind; `os.execve`
does. `sys.flags.hash_randomization` is the flag the interpreter BOOTED with,
so it is the one thing here that cannot be faked after the fact, and every
assertion below is written against it rather than against `os.environ`.

Each test names the mutation that kills it.
"""
import os
import subprocess
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).parent.parent))

import conftest  # noqa: E402  (tests/ is on sys.path; this is the harness itself)

ROOT = Path(__file__).parent.parent
SELF = "tests/test_harness_determinism.py"
PINNED_NODE = (SELF + "::TestTheParentInterpretersSeedIsPinned"
                      "::test_this_interpreter_started_under_the_pinned_seed")


class TestTheParentInterpretersSeedIsPinned(unittest.TestCase):

    def test_this_interpreter_started_under_the_pinned_seed(self):
        """The whole point, asserted on the boot flag.

        Killed by deleting the `_bind_parent_hash_seed(config)` call from
        `pytest_configure`: a run started without `PYTHONHASHSEED=0` in the
        shell then keeps the OS's random seed and
        `sys.flags.hash_randomization` is 1.
        """
        self.assertEqual(conftest.HASH_SEED, "0")
        self.assertTrue(conftest.HASH_SEED_BOUND,
                        "conftest does not believe the parent seed is bound")
        self.assertEqual(
            sys.flags.hash_randomization, 0,
            "the pytest PARENT is running under a random hash seed, so this "
            "run is not reproducible and neither is its result")

    def test_the_bound_check_reads_the_boot_flag_not_the_environment(self):
        """`_pin_environment` writes `PYTHONHASHSEED` into `os.environ` for the
        children's benefit, so by the time any test runs, the environment
        already SAYS the seed is pinned whether or not this process was ever
        re-executed. A check that read it would report success for exactly the
        broken case it exists to catch.

        Killed by rewriting `_hash_seed_is_bound` to compare
        `os.environ["PYTHONHASHSEED"]` in the default (seed 0) case.
        """
        with mock.patch.dict(os.environ, {"PYTHONHASHSEED": "not-a-seed"}):
            self.assertTrue(conftest._hash_seed_is_bound())
        with mock.patch.dict(os.environ, {}, clear=True):
            self.assertTrue(conftest._hash_seed_is_bound())

    def test_children_inherit_the_seed_the_parent_runs_under(self):
        """Parent and children must agree, or a cross-process comparison is
        comparing two different hash orders and calling the difference a bug.

        Killed by pinning `PINNED_ENV["PYTHONHASHSEED"]` to a literal that no
        longer tracks `HASH_SEED`.
        """
        out = subprocess.run(
            [sys.executable, "-c",
             "import sys, os; print(sys.flags.hash_randomization, "
             "os.environ.get('PYTHONHASHSEED'))"],
            capture_output=True, text=True, env=dict(os.environ))
        self.assertEqual(out.returncode, 0, out.stderr)
        self.assertEqual(out.stdout.split(), ["0", conftest.HASH_SEED])

    def test_the_pin_binds_whatever_seed_the_shell_happened_to_hold(self):
        """End to end, the acceptance property: run this file's own pinned-seed
        test in a real pytest, under ambient seeds that are NOT the pinned one,
        and require it green each time. That is the six-seed sweep in miniature,
        wired into the suite so it cannot quietly stop being true.

        Killed by the same mutation as the first test — and unlike the first
        test, killed even on a developer's machine that happens to export
        PYTHONHASHSEED=0, because the ambient seed here is chosen, not inherited.
        """
        for ambient in ("3", "7", "99999"):
            env = dict(os.environ, PYTHONHASHSEED=ambient)
            env.pop(conftest._REEXEC_MARK, None)
            proc = subprocess.run(
                [sys.executable, "-m", "pytest", PINNED_NODE, "-q", "--no-header",
                 "-p", "no:cacheprovider"],
                cwd=str(ROOT), env=env, capture_output=True, text=True)
            self.assertEqual(
                proc.returncode, 0,
                "an ambient PYTHONHASHSEED=%s was not rebound:\n%s\n%s"
                % (ambient, proc.stdout[-2000:], proc.stderr[-2000:]))

    def test_the_loop_guard_is_read_before_the_environment_is_pinned(self):
        """Two properties that pull against each other, and the bug is having
        only one of them: the mark must survive into the re-executed process
        (or a failed exec loops forever), and it must NOT survive into the
        suite's own children (or a nested pytest refuses to re-exec and raises
        instead of running).

        Killed either way — by dropping `_REEXEC_MARK` from `CLEARED_ENV`
        (`test_the_pin_binds_whatever_seed...` above then raises inside the
        child), or by having `_bind_parent_hash_seed` re-read `os.environ`
        instead of the `_REEXECED` snapshot (the guard is then always False and
        a seed that cannot be bound execs forever).
        """
        self.assertIn(conftest._REEXEC_MARK, conftest.CLEARED_ENV)
        self.assertNotIn(conftest._REEXEC_MARK, os.environ)
        self.assertIsInstance(conftest._REEXECED, bool)


class TestTheDocumentedInvocationsAreTheReproducibleOnes(unittest.TestCase):
    """tests/README.md lists the four modes that must be green. The pin has to
    apply to all four, and the file has to say so — a mode documented without
    it would be a fifth, unreproducible way to run the gate."""

    README = ROOT / "tests" / "README.md"

    def test_every_documented_mode_runs_through_the_conftest_that_pins(self):
        """All four documented invocations are `pytest tests/…`, so all four
        import `tests/conftest.py` and all four are re-executed. Killed by
        documenting a mode that runs a test file directly (`python3
        tests/test_x.py`), which loads no conftest and pins nothing.
        """
        text = self.README.read_text()
        modes = [ln.strip() for ln in text.splitlines()
                 if "pytest tests/" in ln and ln.strip().startswith(("/usr/bin", "CHRONICLE"))]
        self.assertEqual(len(modes), 4, "expected the four documented modes, got:\n%s"
                         % "\n".join(modes))
        for line in modes:
            self.assertIn("-m pytest tests/", line)

    def test_the_readme_states_that_the_parent_seed_is_pinned(self):
        """The README used to say the opposite in so many words — "children
        only — this process's seed is fixed at interpreter start". That
        sentence was TRUE and it was the defect; leaving it would document a
        guarantee the harness no longer fails to make."""
        text = self.README.read_text()
        self.assertNotIn("children only", text)
        self.assertIn("CHRONICLE_TEST_HASH_SEED", text)


if __name__ == "__main__":
    unittest.main()
