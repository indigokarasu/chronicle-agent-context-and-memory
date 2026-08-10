# R0 — Compression-fidelity baseline

Ladder 7, issue #2 (indigokarasu/chronicle-agent-context-and-memory). Harness:
`tests/test_compression_fidelity.py`, 12 assertions against `context.py`
(`ChronicleContextEngine.compress` / `_heuristic`) as of commit
`9cbe0ed780e4c4507be8f3e9e9bb0cad9f402482` ("mirror dashboard fixes").

This task changes no production code. It only adds the harness and records
where the current implementation stands relative to I17 and the R1–R11
properties, so every later task in the ladder has something concrete to flip
green.

## Result: 5 pass, 7 documented BASELINE-FAIL, 0 unexpected

```
$ CHRONICLE_EMBED_MODEL=hashing /usr/bin/python3 tests/test_compression_fidelity.py
BASELINE-FAIL: fallback_audit_event -- heuristic fallback has no store to append a 'compressed' audit event into (R1)
BASELINE-FAIL: fallback_i17_durability -- heuristic fallback drops the window middle with nothing durably stored to recover it from -- no core, no store, unrecoverable (R1)
BASELINE-FAIL: i17_large_span_byte_exact -- _ensure_durable clips at 4000 chars: recovered 4000/4513 chars (R11)
BASELINE-FAIL: output_fits_token_budget -- ~4514 tokens vs context.default_token_budget=1500 -- compress() does not account for tokens, only message count (R2)
BASELINE-FAIL: pin_span_survives_eviction -- pinning does not actually protect the span by id -- the pinned, low-score span is still evicted (R3)
BASELINE-FAIL: prefix_stability_across_growth -- 6/6 previously tail-protected spans were evicted once the conversation grew and they slid into the rescored middle (R5)
BASELINE-FAIL: replay_from_audit_log_has_span_ids -- 'compressed' audit payload stores only a count (1), not evicted span ids -- the window cannot be replayed from the log alone (R6)

compression-fidelity baseline: 12 checks run, 5 passed, 7 documented BASELINE-FAIL, 0 unexpected.
exit code: 0
```

Under pytest, all 12 tests are green (the BASELINE-FAIL lines are `print()`s,
not failures — `check()` only raises when a result doesn't match its declared
expectation):

```
$ CHRONICLE_EMBED_MODEL=hashing /usr/bin/python3 -m pytest tests/test_compression_fidelity.py -v
...
12 passed in 0.15s
```

## Per-assertion baseline

| # | Assertion | Baseline | Owning task | Why |
|---|---|---|---|---|
| 1 | `i17_small_span_byte_exact` | **PASS** | — | A span under the 4000-char excerpt clip round-trips through `_ensure_durable` byte-for-byte. |
| 2 | `i17_large_span_byte_exact` | FAIL | R11 | `_ensure_durable` does `content[:4000]`; a 4513-char span comes back truncated to 4000 chars. Lossy eviction, an I17 violation in spirit. |
| 3 | `fallback_i17_durability` | FAIL | R1 | `_heuristic()` (used whenever `self.core is None`) drops the window middle with no store to persist it to first — outright unrecoverable, not just lossy. |
| 4 | `fallback_audit_event` | FAIL | R1 | Same fallback path: no store means no `compressed` audit event either. |
| 5 | `pin_write_recorded` | **PASS** | — | `chronicle_pin_context` does durably record the pin request via `capture.agent_explicit`. |
| 6 | `pin_span_survives_eviction` | FAIL | R3 | The durable pin record above is never linked back to the live span; `_never_evict` only substring-matches a fixed keyword list, so a pinned but low-scoring span is evicted anyway. |
| 7 | `focus_reinjection_present` | **PASS** | — | With a focus topic set, a durable memory seeded under that topic is retrieved and re-injected as a `[Relevant memory: …]` system span. |
| 8 | `output_fits_token_budget` | FAIL | R2 | `compress()` bounds only by **message count** (`protect_first_n`/`protect_last_n`); it never reads `context.default_token_budget` (1500) or estimates tokens, so large protected spans blow straight through it (measured ~4514 tokens vs. the 1500 budget). |
| 9 | `replay_determinism_partition` | **PASS** | — | The same input compressed twice partitions into the identical kept/evicted/retained window both times (no randomness, no time-dependence in `_keep_score`). |
| 10 | `replay_from_audit_log_has_span_ids` | FAIL | R6 | The `compressed` audit event stores `evicted_spans` as an **int count**, not a list of span ids — the window cannot be reconstructed from the log alone. |
| 11 | `prefix_stability_across_growth` | FAIL | R5 | `compress()` re-scores the *entire* window from scratch every pass with a fixed-position `protect_last_n` slice; once the conversation grows, previously tail-protected spans slide into the rescored middle and get evicted (measured: 6/6 lost in the test). |
| 12 | `audit_event_emitted_memory_aware` | **PASS** | — | Memory-aware compression does append a `compressed` audit event for the session. |

## Harness contract

`check(name, condition, expect_baseline_fail=..., detail=...)`:

- `expect_baseline_fail=True` and condition False (still broken): prints
  `BASELINE-FAIL: …` and stays green — this is today's documented state.
- `expect_baseline_fail=True` and condition True (unexpectedly fixed): raises
  — the owning task must flip the flag to `False` as part of landing the fix,
  or this harness will keep insisting the bug is still open.
- `expect_baseline_fail=False`: ordinary assertion; a failure here is a real
  regression.

Standalone (`python3 tests/test_compression_fidelity.py`) always exits 0 as
long as reality matches the table above; it exits 1 only on something
unexpected (a real regression, or a documented gap that silently closed).

## Full gate run (this commit, no production code touched)

```
$ /usr/bin/python3 -m pytest tests/ -q --ignore=tests/exercise/test_manual.py
315 passed in 2.16s          # was 303 before R0; +12 from this harness

$ CHRONICLE_EMBED_MODEL=hashing CHRONICLE_DIR=$PWD /usr/bin/python3 lme_recall.py oracle.json
TURN-LEVEL RECALL@k union: k=1 65.0%  k=3 86.4%  k=5 92.2%  k=10 95.6%   # unchanged

$ CHRONICLE_EMBED_MODEL=hashing CHRONICLE_DIR=$PWD /usr/bin/python3 scripts/ctx_eval.py
token_budget=1500:  43/58  (74.1%)
token_budget=4000:  49/58  (84.5%)
token_budget=12000: 52/58  (89.7%)                                      # unchanged
```

## Re-running after each merge

Per the tracking issue's sequencing note, re-run this harness after every
subsequent task (`R1, R2, R3, R11` in parallel, then `R6`, then `R4, R5, R7`
in parallel, then `R8, R9, R10`) and update this table + the corresponding
`expect_baseline_fail` flags as each property flips to PASS.

## R6 update — compressed event stores span ids, replayable from the log

`replay_from_audit_log_has_span_ids` (row 10) flips **FAIL -> PASS**.
`evicted_spans` in the `compressed` audit event is now a list of span ids
(content-addressed, `_span_id`) instead of a count, `kept_spans` (same id
scheme, covering everything the returned window kept from the original
body) is new, and `folded_spans` is a new always-empty key reserved for the
FOLD tier (R4, sequenced after R6). Every durability chunk `_ensure_durable`
writes for an evicted span is now stamped with that span's `span_id`, so a
reader can pull a span's chunks back out of the store by id, in
`chunk_index` order — the log alone is enough to say which spans left the
window and to recover their content, without re-running `compress()`.

The test fixture for that assertion changed too: with R2's real per-span
token accounting, the original `_body(10, middle_content=...)` fixture (one
small middle span, ~9 small protected spans) fits entirely under the
~1500-token default budget and nothing is evicted at all — a genuine gap,
but in R2's eviction *triggering*, not in R6's audit *schema*. The updated
fixture oversizes head/tail so the scored middle span has no budget left
and is reliably evicted (same technique `test_output_fits_token_budget`
already uses), so the schema assertion is exercised against a real
eviction rather than an empty list that happens to satisfy nothing.

Two pre-existing, unrelated failures remain **open** and are unchanged by
this task — `i17_small_span_byte_exact` and `i17_large_span_byte_exact`
(both real `assert` failures under pytest, not `check()` baseline gaps;
see the merge commit for R0+R2+R11: "R2 eviction path bypasses R11
_ensure_durable — needs integration fix"). `i17_small` fails because the
same R2 budget-triggering gap above means the fixture's single small span
is never evicted; `i17_large` fails because R11's chunker correctly splits
a >4000-char span into 2 durability events, while the test still asserts
exactly 1 — stale relative to R11's own (correct) design. Both are R2/R11
integration debt, not R6's item, and are left untouched here; the full
suite (`321 passed, 2 failed`, no `CHRONICLE_EMBED_MODEL` set) is identical
before and after this task.
