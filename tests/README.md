# Running the Chronicle test suite

Python is always `/usr/bin/python3` (3.9). No dependencies beyond `pytest`.

The suite is **hermetic**: it does not read the ambient environment, does not
open a socket, does not touch `$HOME`, does not depend on collection order, does
not depend on the hash seed your shell happened to hold, and leaves the system
temp directory exactly as it found it. `tests/conftest.py` is what enforces
that; its module docstring is the reference. This file is the short version.

## The four modes — all four must be green

```sh
# 1. default
/usr/bin/python3 -m pytest tests/ -q --ignore=tests/exercise/test_manual.py

# 2. with the documented CI env var set — must behave identically to (1)
CHRONICLE_EMBED_MODEL=hashing /usr/bin/python3 -m pytest tests/ -q --ignore=tests/exercise/test_manual.py

# 3. with sockets disabled (strict: creating an INET socket raises, not just connecting)
CHRONICLE_TEST_STRICT_SOCKETS=1 /usr/bin/python3 -m pytest tests/ -q --ignore=tests/exercise/test_manual.py

# 4. in reversed collection order
CHRONICLE_TEST_ORDER=reverse /usr/bin/python3 -m pytest tests/ -q --ignore=tests/exercise/test_manual.py
```

All four are **reproducible**, whatever `PYTHONHASHSEED` your shell holds: if
the interpreter did not start under the pinned seed, `pytest_configure` re-execs
it under `PYTHONHASHSEED=0` before a single test module is imported, and says so
on stderr. Nothing else changes — same pid, same argv, same exit status — and
the terminal summary line records the seed the run actually used. You do not
need to export anything; exporting `PYTHONHASHSEED=0` yourself simply skips the
re-exec.

This matters because the suite's *own* result was an experiment with an
unrecorded input until v5.7.0. `tests/test_harness_determinism.py` is what
holds it: it asserts on `sys.flags.hash_randomization`, the flag the
interpreter BOOTED with, and re-runs its own pinned-seed test under three
ambient seeds that are not the pinned one.

The pin does **not**, on its own, make a test deterministic, and the one test
blamed on its absence is the example:
`tests/test_token_margins.py::TestContextBudgetGetsTheWholeEstimate` flaked at
a FIXED seed, because its fixture left `occurred_at` to the wall clock and
`event_id` hashes `occurred_at` — so the tie-break over its (deliberately)
score-tied pool was redrawn on every build. A fixture that measures something
order-sensitive has to stamp its own timestamps, and one that measures a budget
has to give the packer more than the budget holds. That class's docstring
carries both measurements; the cross-process guard for a tied pool lives in
`tests/test_precision_packing.py`.

`tests/exercise/` holds acceptance/exercise scripts, not unit tests;
`test_manual.py` is excluded from the gate by design.

## Knobs

| variable | effect |
| --- | --- |
| `CHRONICLE_TEST_ORDER=reverse\|shuffle` | reorder collected tests |
| `CHRONICLE_TEST_SEED=<int>` | seed for `CHRONICLE_TEST_ORDER=shuffle` (default 0) |
| `CHRONICLE_TEST_STRICT_SOCKETS=1` | also deny AF_INET/AF_INET6 socket *creation* |
| `CHRONICLE_TEST_ALLOW_NETWORK=1` | lift the network guard entirely |
| `CHRONICLE_TEST_LIVE_EMBEDDER=1` | run `@pytest.mark.live_embedder` tests |
| `CHRONICLE_TEST_KEEP_TMP=1` | keep the session temp sandbox for inspection |
| `CHRONICLE_TEST_HASH_SEED=<int>` | the seed the parent (and its children) are pinned to; default `0` |
| `CHRONICLE_TEST_HASH_SEED=off` | skip the re-exec and take the OS's random seed. **The run is then not reproducible**, and the summary line says so |
| `CHRONICLE_BASE_TREE=<path>` | base tree for `test_host_model`'s byte-identical store dump (default `../L10_A4_base`); those tests skip if the path has no `provider.py` |
| `CHRONICLE_V560_TREE=<path>` | shipped v5.6.0 worktree that `test_v570_schema_ladder.py` builds its v11 fixture from (default `../v560`) |

Everything else the engine reads from the environment is **pinned** by conftest
before any test module is imported, so exporting it in your shell changes
nothing: `CHRONICLE_EMBED_MODEL` (pinned to `hashing`), `CHRONICLE_DIR`, `HOME`,
`HERMES_HOME`, the `XDG_*` dirs, `TMPDIR`, `TZ`, `LC_ALL`/`LANG`, and
`PYTHONHASHSEED` — the parent by re-exec, every child by inheritance, both at
the same value. `CHRONICLE_EMBED_BASE_URL`, `CHRONICLE_REQUIRE_BLAKE3` and the
`OPENROUTER_*` / `OPENAI_*` / `ANTHROPIC_*` / proxy variables are removed.

## Skipped tests

In a full checkout with its sibling worktrees present, the default run skips
**exactly one** test. Three things can skip, each for a stated reason:

* Anything marked `@pytest.mark.live_embedder` skips without
  `CHRONICLE_TEST_LIVE_EMBEDDER=1`. **This is the one skip the default run
  reports**: `tests/test_a0e_session_projection_vectors.py` carries the marker.
  The marker exists so a test that genuinely needs ollama / llama.cpp has
  somewhere to go other than the default run.
* Two tests in `test_host_model.py` —
  `test_store_dump_is_byte_identical_to_the_base_tree` and
  `test_the_overlay_is_what_makes_the_dumps_match` — skip when the comparison
  tree is not on disk. They diff this tree's store dump against a historical
  checkout that cannot be vendored into the repo. The default moved from
  `../v560_preH1` to `../L10_A4_base` (override with `$CHRONICLE_BASE_TREE`),
  and the comparison was inverted to the stronger form (this tree with the A6
  patch backed out, rather than the base with A6 applied). Where
  `../L10_A4_base` exists, both tests RUN.
* `tests/test_v570_schema_ladder.py` (26 tests) skips when `../v560`, the
  shipped v5.6.0 worktree, is absent — it builds its v11 fixture by running
  v5.6.0's own code in a subprocess rather than hand-writing a DDL. Override
  with `$CHRONICLE_V560_TREE`.

So an export of this tree ALONE (no siblings) skips **29** — 1 + 2 + 26, the
three reasons above — and that is expected; the 1-skip number is for the full
checkout.

## Writing a test

* **Temp paths.** Use `temp_home()` from `tests/_tmp_support.py` instead of
  `tempfile.mkdtemp()`; the harness removes it when the test ends, including
  from module-level helpers such as `make_core()` that have no `self` to hang an
  `addCleanup` on. For a bare SQLite path use `remove_db(path)` rather than
  `os.unlink(path)`: a store that is never closed leaves `-wal`/`-shm` sidecars
  next to the file, and `os.unlink` removes one of the three. `MemoryStore` and
  `ChronicleCore` do have a `close()` now (both are context managers, so `with
  MemoryStore(path) as store:` works), and closing checkpoints the WAL and
  unlinks the sidecars — but `remove_db` is still the right call in `tearDown`,
  because it is idempotent, never raises, and does not care whether the test
  closed anything.
* **Unreachable servers.** Never point a test at a port you believe is closed.
  Patch `urllib.request.urlopen` to raise (`test_build.unreachable_endpoint()`
  is the pattern). The guard fails any test that opens a socket even when the
  code under test swallows the error, which is exactly what the embedder's probe
  loop does.
* **Environment.** If a test is *about* an environment variable, set it inside
  the test over a snapshot (`mock.patch.dict(os.environ)`), the way
  `test_config_errors.TestConfig` does. Never assert a default while the real
  environment can override it.
* **The clock, in any fixture whose assertion a ranking can reach.** Pass an
  explicit `occurred_at=` to `capture.observe()`. `event_id` is a content hash
  that includes `occurred_at` (§5.3), and `retrieve_raw`/`search` break
  *score ties* on that id (`_rank_key`, A15). A fixture full of near-identical
  turns is full of exact ties, so leaving the wall clock in decides the ranked
  order by the microsecond the fixture was built — which is a coin flip wearing
  a content hash. That is what made
  `test_token_margins.py::…::test_a_saturating_caller_actually_receives_the_extra_third`
  flake: 40 builds **at one pinned hash seed** produced five different byte
  counts, 7 of them below the floor it asserts. `test_precision_packing.py`'s
  `FREEZE_PREAMBLE` does the same thing for its subprocess scripts. Pinning the
  clock freezes one draw; if the assertion is a threshold, also check that it is
  not sitting inside the spread the other draws cover.
* **Order.** Don't leave process-wide state behind. `ChronicleCore._instances` /
  `._active` and the ACL topology are reset for you after every test; anything
  else you install, you undo.
