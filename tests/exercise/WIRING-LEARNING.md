# Chronicle Learning Loop — Wiring Audit (§u6.a–c)

## Scope exception, stated up front

This pass is additive except for **one engine change**, already applied and kept:

- `engine/learning.py:63-74` (`activate_policy`) + `engine/store.py:839-841` (new `get_policy`) —
  a data-corruption fix. `activate_policy` used to call `upsert_policy` with `kind=""`,
  `params="{}"`, `parent_version=""` hardcoded. `upsert_policy` builds its
  `ON CONFLICT(version) DO UPDATE SET` clause from the keys of the dict it is handed
  (store.py:828-832), so those blanks were written over the challenger's real columns in the
  same statement that flipped `active=1`: **activating a policy erased the policy**. It now
  reads the challenger row back and reuses its real `kind`/`params`/`parent_version`, and
  raises `E_LEARN_BOUND` for a version that does not exist. Regression:
  `tests/test_learning_trust_tools.py::test_activate_policy_preserves_challenger_fields`.

Everything else here is documentation and `tests/exercise/`. Nothing in the retrieval or
abstention path was touched; the LongMemEval harness is unchanged.

## Corrections to the previous version of this document

The prior pass got the reader search wrong (it grepped `SELECT.*retrieval_log` rather than the
bare identifier) and recommended deleting live schema. Retracted:

| Retracted claim | Ground truth |
|---|---|
| "`retrieval_log` … populated and never queried by anything" | Read at **health.py:54**, `count_rows("retrieval_log")` inside `_recall_gap`, reported as `extraction_recall_gap` by `health.run()` (health.py:32) |
| "delete … the `retrieval_log` table (store.py:1116)" | Would break `_recall_gap`. **Do not delete.** |
| "stop pretending `precision_correct` measures anything — either delete the column" | Read at **health.py:60-61**, `_bad_derivation_rate`, reported by `health.run()` (health.py:33). **Do not delete.** |
| "nothing reads the `utility` column … into ranking (grep for `utility` reads in retrieval.py: none)" | True for *ranking*, false for the subsystem: `utility` is read at **forgetting.py:56**, and it is the only input to `utility_factor` in the decay threshold (forgetting.py:57) |
| Calibration refit "**WIRED** … records an authentic pass/fail signal (not a hardcoded constant)" | The signal is real code but resolves to a **constant `False`** — see §2. Verdict stays WIRED; the finding is worse, not better |
| `_task_derive` "reachable from `_task_consolidate` … also automatic" | Nothing ever enqueues `consolidate` either. The automatic path is the inline derive at curation.py:134-136, which does hold |

## Method

For each subsystem: (1) the **writer**, (2) every caller of it, by **bare-identifier**
`grep -rn` across `engine/ provider.py context.py scripts/ dashboard/ __init__.py` (tests
excluded), (3) the **reader** — what consumes the persisted data — found the same way, (4)
whether either end reaches an automatic engine trigger, an agent-facing tool, or neither, and
(5) a verdict:

- **WIRED** — writer reachable in production *and* a reader applies the value.
- **WIRED-BUT-DORMANT** — mechanically connected in code, not orphaned, but no observable
  effect today: either the reader's own trigger never fires, or the signal cannot vary.
- **UNWIRED** — writer and/or reader have zero production callers. Dead code.

Every numeric claim below was produced by running the engine, not by reading it:
`tests/exercise/exercise_learning.py` (output quoted in §Exercise results).

---

## 1. Credit assignment (§22)

**Intended**: retrievals are logged with a success score; outcomes are marked resolved;
`record_outcome()` folds them into a per-belief `utility` EWMA; `utility` feeds ranking/decay.

Two legs, with different verdicts. Neither is dead code.

### 1a. `retrieval_log` → health recall-gap metric — WIRED-BUT-DORMANT

**WRITER**: `store.log_retrieval(query, domain, top_score)` — store.py:792.
**CALLERS**: retrieval.py:334, 344, 357, 363 — all four inside `RetrievalEngine.answer()`
(retrieval.py:322): the confident Tier-1 path and the three abstain paths. `answer()`'s only
production caller is `tools.py:172` (`_t_answer`, the `chronicle_answer` tool, schema
tools.py:35). Tool-gated but real. `get_context()` (retrieval.py:421) does **not** call
`answer()` and does not log — it goes through `search()`/`retrieve_raw()` directly, so prefetch
traffic (provider.py:139) never reaches this writer.

**READER**: `health._recall_gap()` — health.py:53-56:
```python
total = self.store.count_rows("retrieval_log")     # health.py:54
misses = self.store.count_rows("search_misses")    # health.py:55
return round(misses / total, 4) if total else 0.0  # health.py:56
```
surfaced as `results["extraction_recall_gap"]` (health.py:32) and persisted by
`store.record_health_run` (health.py:44 → store.py:812).

**Why dormant**: `health.run()`'s only engine caller is `curation._task_health`
(curation.py:255-256), and **nothing ever enqueues a `health` job**. Every `enqueue_curation`
call site in the tree writes `extract` (capture.py:201, reducer.py:108, retrieval.py:370,
curation.py:265, dashboard/plugin_api.py:217), `session_summarize` (capture.py:203),
`journal_ingest` (core.py:176), `canonicalize` (curation.py:138) or `verify` (tools.py:122) —
never `health`, despite `health` being a legal `curation_jobs.task` (store.py:934) with a
handler and a shipped cron string, `health.schedule = "0 4 * * *"` (config.py:154), that no
code reads. Same finding as `tests/exercise/WIRING.md`; it now bites a second subsystem.
Measured: after a full ingest, two `answer()` calls and a full drain, `health_runs` has
**0 rows** and `curation_jobs` holds no `health` row.

**DEFECT (unreported before this pass)**: `_recall_gap` is not a rate. Its numerator and
denominator are incremented on **disjoint** paths of `answer()` — `log_miss` (retrieval.py:367)
fires on the Tier-2 *answered* path, which returns at retrieval.py:371 without ever calling
`log_retrieval`. Measured on three real queries: 1 retrieval row, 2 miss rows,
`extraction_recall_gap = 2.0`. A "gap" of 200%. Related: `search_misses.resolved` is never set
— `store.get_unresolved_misses` (store.py:802) and `store.mark_miss_resolved` (store.py:806)
have zero callers anywhere, tests included.

**DEAD-END**: `retrieval_log.resolved` likewise never changes. No `mark_retrieval_resolved`
exists; nothing joins `retrieval_log` to an outcome. `_recall_gap` counts rows and nothing else
ever reads the table, so the `query`, `top_score` and `resolved` columns are write-only.

### 1b. `record_outcome` → `utility` → decay — UNWIRED writer, WIRED reader

**WRITER**: `learning.record_outcome(belief_id, used, outcome)` — learning.py:31-42.
Bare grep `record_outcome` over `engine/ provider.py context.py scripts/ dashboard/`: **only
its own definition.** Zero production callers. The EWMA itself is correct (verified: 0.5 →
0.6 on `used=True, outcome=1.0`; → 0.47 on `used=False`).

**READER**: `forgetting._eligible` — forgetting.py:56-58:
```python
utility_factor = max(0.25, 1.0 - (row.get("utility") or 0.0))   # forgetting.py:56
threshold = decay_days * max(salience_mult, 0.01) * utility_factor
return age_days > threshold
```
Called from `decay_sweep` (forgetting.py:28), whose only engine caller is `curation._task_decay`
(curation.py:249-250) — another job type nothing enqueues. So the reader is present and correct
in code, and dormant for the same trigger reason as 1a.

**CONSEQUENCE**: with no writer, `utility` never leaves its schema default of `0.0`
(store.py:995 et al). Measured over a real ingest: the distinct set of `utility` values across
every belief is `[0.0]`. `utility_factor` is therefore pinned at `1.0` and contributes nothing.

**DEFECT (unreported before this pass) — the sign is inverted.** `utility_factor = 1.0 -
utility` means a *more useful* belief gets a *smaller* decay threshold, i.e. decays sooner; the
floor `max(0.25, …)` caps the penalty at 4× faster. `record_outcome`'s `used=False` branch
writes a small negative (learning.py:40), which *raises* the threshold — an unused belief
survives longer than a used one. Verified end-to-end through the real `decay_sweep`, two
otherwise identical `general`-domain facts last seen 20 days ago:

```
b-idle   (utility=0.0) fidelity: verbatim     ← untouched
b-useful (utility=0.9) fidelity: gist         ← decayed
decayed events: ['b-useful']
```

This matters for the recommendation: wiring `record_outcome` today, without also fixing
forgetting.py:56, would make Chronicle preferentially forget the beliefs it uses most.

**VERDICT: WIRED-BUT-DORMANT.** Not dead code — the table is written on every
`chronicle_answer` and read by a health metric, and the `utility` column is read by the decay
gate. But the middle of the loop is missing (`record_outcome` has no caller), both readers'
triggers are never enqueued, and both readers are defective in ways that only show up once
someone completes the wiring.

---

## 2. Calibration refit (§10.5, §22)

**Intended**: verified/refuted outcomes accumulate per `source_type` in `calibration_obs`; once
`calibration.min_obs` (50, config.py:138) observations exist, `Calibrator.calibrate()` remaps
raw confidence to an empirically-corrected probability before the agent sees it.

**WRITER**: `store.bump_calibration(source_type, bucket, correct)` — store.py:783.
**CALLER**: `curation._task_verify` — curation.py:246-247. Enqueued only from tools.py:122
(`_t_verify`, the `chronicle_verify` tool). Tool-gated, but a real production path.

**READER**: `Calibrator.calibrate(raw, source_type)` — trust.py:50, over
`store.get_calibration_obs` (store.py:779). Constructed at retrieval.py:100-101 and called
**unconditionally on every `answer()`** — retrieval.py:376 (Tier-1) and retrieval.py:397
(Tier-2). Below `min_obs` it returns `raw` unchanged (trust.py:53-54).

**VERDICT: WIRED.** This is the one subsystem of the four whose writer and reader are both
reachable and whose reader runs automatically. It is also the only one that measurably changes
behavior — and it changes it in the wrong direction.

**DEFECT — the verify signal is pinned to `False`.** `_task_verify` resolves the source span
through the belief's provenance:
```python
prov = json.loads(f.get("provenance") or "{}")            # curation.py:238
src = self.store.get_event(prov.get("source_event", ""))  # curation.py:239
...
ok = f["value"].lower() in (sp.get("excerpt", "").lower())  # curation.py:243
```
But `provenance.source_event` is set to the belief's **own `asserted` event**, not the
`observed` event carrying the text — `reducer._insert_belief` writes
`"source_event": event.get("event_id", "")` (reducer.py:393), where `event` *is* the asserted
event. An `asserted` payload has no `excerpt` key, so `sp.get("excerpt", "")` is `""` and `ok`
is `False` for every extraction-derived belief, always. Measured: ingesting `"I work at Acme
Fake Co"` and verifying the resulting `works_at` fact whose value is literally `Acme Fake Co`
yields `{'source_type': 'session_transcript', 'predicted_bucket': '0.7', 'n': 2, 'correct': 0}`
and a `verified` event with `status: "refuted"`.

The excerpt is not missing, only mis-addressed: `reducer.py:139` writes the *observed* event as
the belief's justification, so `store.get_justifications(belief_id)[0]["support"]` resolves to
`ev_… observed` with `excerpt = 'User: I work at Acme Fake Co\nAssistant: ok'` — which contains
the value. The data needed to verify correctly is one call away.

**CONSEQUENCE, measured.** Because the reader is live, the pinned-`False` signal is not inert.
With `calibration.min_obs` lowered to 2 (the only change; everything else is stock) and two real
`chronicle_verify` calls on two correct facts:
```
BEFORE calibrate(0.75): 0.75      BEFORE answer conf: 0.5
AFTER  calibrate(0.75): 0.25      AFTER  answer conf: 0.25
```
`calibrate` smooths to `(correct + 1) / (n + 2)` (trust.py:58), so a source_type with all-refuted
observations converges toward ~0 and drags every subsequent answer's confidence down with it.
In a stock deployment this is latent only because nothing drives 50 `chronicle_verify` calls —
the protection is low volume, not correctness. **"Nothing has ever measurably trained" is
wrong: this trains, and it trains backwards.**

**Dead config**: `calibration.refit_every` (config.py:138) has zero readers; `calibrate()`
recomputes from all observations on every call, so no batched refit step exists at all.

---

## 3. Rule precision auto-disable (§22)

**Intended**: each derivation rule accrues `precision_n` (fired) and `precision_correct`
(conclusion was right); rules with ≥10 firings below `derivation.auto_disable_precision_below`
(0.6, config.py:102) get disabled.

**WRITER**: `derivation._bump_precision(rule_id, fired=True, correct=True)` — derivation.py:194,
persisting via `upsert_derivation_rule` (derivation.py:198-203). Its **only** call site is
derivation.py:179 inside `_materialize`, and it passes no `correct=` argument.

This writer is genuinely **automatic**: `_materialize` ← `derive_for_subject` ←
curation.py:134-136, the inline derive at the end of `_task_extract`, which runs for every
ingested event that touches a fact-bearing subject. No tool call required. Measured after
ingesting two ordinary sentences: `[('workplace_location', 1, 1)]`.

**READERS — two, and the previous version of this document missed the live one**:
1. `health._bad_derivation_rate()` — health.py:58-62, `sum(precision_n)` / `sum(precision_correct)`
   over all rules, surfaced as `results["bad_derivation_rate"]` (health.py:33).
2. `learning.auto_disable_low_precision_rules()` — learning.py:44-52. Bare grep
   `auto_disable_low_precision` across `engine/ provider.py context.py scripts/ dashboard/`:
   only its own definition. Zero production callers.

never overrides it, so `precision_correct` increments in lockstep with `precision_n`
(derivation.py:202-203) and the ratio is pinned at `1.0` for every rule forever. Therefore:

> **`health.run()` reports `bad_derivation_rate: 0.0` unconditionally, for every corpus, no
> matter how wrong the derivation rules are.** It is not a measurement; it is the constant
> `1 - n/n`. Measured on a live run: `{"…, "bad_derivation_rate": 0.0, …}`.

That is worse than the never-called auto-disable, because it is a *reported* clean bill of
health rather than an obviously missing feature. It is currently unreported anywhere.
`auto_disable_low_precision_rules` is the second casualty: even if something called it on a
schedule, it could never disable a rule, because its input cannot fall below 1.0. Its logic is
correct in isolation — hand-seed `precision_n=15, precision_correct=3` and it disables the rule
— which is exactly why unit coverage never caught this.

**VERDICT: WIRED-BUT-DORMANT.** Writer automatic and live; one reader live (inside a `health.run()`
that nothing triggers), one reader with no callers; signal structurally incapable of varying.

---

## 4. Policy champion/challenger (§22, I19)

**Intended**: propose bounded policy deltas, benchmark challenger vs champion, activate the
winner, and have retrieval/ranking read the active policy.

**WRITERS**: `learning.propose_policy` (learning.py:54), `learning.activate_policy`
(learning.py:63), `store.upsert_policy` (store.py:826). The bounds are real and enforced —
`kind ∈ learning.mutable_dimensions`, `|delta| ≤ learning.max_delta_magnitude`, at most
`learning.max_active_deltas` active (config.py:157-160) — and all of it is verified in the
exercise.

**CALLERS**: bare grep `propose_policy` / `activate_policy` across `engine/ provider.py
context.py scripts/ dashboard/`: only their own definitions. Zero.

**DEAD-END 1 — no evaluator.** Nothing anywhere computes `beats_champion`. Every caller in the
tree passes a literal `True`/`False`, and all of them are tests. There is no eval harness,
no `eval_baselines` writer (the table exists at store.py:1134 and has no reader or writer either).

**DEAD-END 2 — active policies are never read.** `store.get_active_policy(kind)` (store.py:834):
only its own definition. No RRF weight, context weight, decay multiplier, reranker choice, or
read-confidence gate is ever sourced from `policies`. Verified behaviorally: proposing and
activating an `rrf_weights` delta at the magnitude cap leaves `search()` returning a
byte-identical result list, same order, same scores.

**VERDICT: UNWIRED.** The only production-visible effect the `policies` table ever had was the
destroying the policy record.

---

## Summary

| Subsystem | Writer | Reader | Signal can vary? | Verdict | Recommendation |
|---|---|---|---|---|---|
| Credit assignment — `retrieval_log` | Live, tool-gated (`chronicle_answer`) | `health._recall_gap` (health.py:54) — trigger never enqueued | Yes, but the ratio is malformed (measured 2.0) | **WIRED-BUT-DORMANT** | Keep table. Fix `_recall_gap`'s denominator; drop `resolved` + the unused miss helpers |
| Credit assignment — `record_outcome`/`utility` | **Zero callers** | `forgetting._eligible` (forgetting.py:56) — live code, trigger never enqueued | No — `utility` measured `[0.0]` everywhere | **UNWIRED** (writer) | **Excise** `record_outcome`; keep the `utility` column; fix the inverted sign before ever wiring it |
| Calibration refit | Live, tool-gated (`chronicle_verify`) | `Calibrator.calibrate` — **unconditional on every `answer()`** | No — pinned `refuted` (wrong event id) | **WIRED** | **Wire** — one-line fix at curation.py:239. Highest-value item here |
| Rule precision | **Automatic**, every extraction | `health._bad_derivation_rate` (live-in-code) + `auto_disable_low_precision_rules` (zero callers) | No — `correct=True` hardcoded ⇒ `bad_derivation_rate ≡ 0.0` | **WIRED-BUT-DORMANT** | **Excise** the auto-disable reader + its config key; keep the columns; stop reporting a constant as a metric |
| Policy champion/challenger | Zero callers | Zero callers | N/A — no evaluator | **UNWIRED** | **Excise** (keep the applied corruption fix if retained instead) |

## Recommendations

### 1a. `retrieval_log` — KEEP, fix the metric (not excise)
`_recall_gap` reads it, so the table stays. Two defects to close:
- **`_recall_gap` is not a rate.** Either log every `answer()` outcome (add `log_retrieval` to
  the Tier-2 success return at retrieval.py:371, so the denominator counts all answers), or
  compute the gap from `search_misses` alone. As written it can and does exceed 1.0.
- **Dead columns**: `retrieval_log.resolved` (store.py:1118) and the unused
  `store.get_unresolved_misses`/`mark_miss_resolved` pair (store.py:802-808) have no callers
  anywhere, tests included. Delete those three; they are the only genuinely orphaned pieces here.

### 1b. `record_outcome` / `utility` — EXCISE the writer (skeptical default)
**To excise**: delete `learning.record_outcome` (learning.py:31-42) and drop the "credit
assignment" sentence from the module docstring (learning.py:4). **Keep the `utility` column** —
`forgetting._eligible` reads it, and at a constant 0.0 it is a harmless no-op.
**To wire instead**, the sign fix is mandatory and comes first — forgetting.py:56 becomes
```python
utility_factor = min(4.0, 1.0 + (row.get("utility") or 0.0))   # useful ⇒ survives longer
```
and only then add a caller (a curation task that walks recently-answered beliefs). Wiring
without that line makes Chronicle forget its most-used beliefs 4× faster (demonstrated above).

### 2. Calibration refit — WIRE, one line
This is the only subsystem worth wiring and the only one currently doing harm. Replace
curation.py:239:
```python
src = self.store.get_event(prov.get("source_event", ""))
```
with a lookup through the belief's justification, which already points at the `observed` event
(reducer.py:139):
```python
src = self.store.get_event(((self.store.get_justifications(bid) or [{}])[0]).get("support", ""))
```
That single line turns `ok` from a constant `False` into the real span check the code was
written to perform. **Verified by monkeypatching exactly that line onto `_task_verify` and
re-running the §2 scenario**: `calibration_obs` becomes `n=2, correct=2`, both `verified` events
read `status: "verified"`, `calibrate(0.75)` stays `0.75`, and the same answer's confidence goes
`0.5 → 0.75` instead of `0.5 → 0.25`. Derived beliefs degrade safely — their justifications are
`support_kind='belief'/'assumption'`, so `get_event` returns `None` and `ok` stays `False`,
exactly as today. If it is not fixed, the *safe* interim is to stop calling
`bump_calibration` (comment out curation.py:246-247) — collecting refutations of correct facts
is worse than collecting nothing, because the reader is live. Also delete the unread
`calibration.refit_every` key (config.py:138).

### 3. Rule precision — EXCISE the reader, keep the columns
**Excise**: `learning.auto_disable_low_precision_rules` (learning.py:44-52) and
`derivation.auto_disable_precision_below` (config.py:102) — a reader with no caller that could
not act if it had one. **Keep** `precision_n`/`precision_correct` (store.py:1080): health reads
them, and `precision_n` alone is an honest "times fired" counter.
Then make `health.run()` stop reporting a constant: either drop the `bad_derivation_rate` key
(health.py:33, and `_bad_derivation_rate`, health.py:58-62), or thread a real signal —
`_task_verify`'s span check applied to derived beliefs, or a retraction/contradiction against a
derived fact — into `_bump_precision`'s `correct=` at derivation.py:179. Do not do the latter
before fixing §2, since the span check is the same broken lookup.

### 4. Policy champion/challenger — EXCISE
Delete `learning.propose_policy`, `activate_policy`, `_check_bounds` (learning.py:54-81),
`store.upsert_policy`/`get_active_policy`/`get_policy`/`count_active_policies`
(store.py:826-844), the `policies` and unused `eval_baselines` tables (store.py:1130-1135), and
the `learning.*` config block (config.py:157-160). Nothing proposes, evaluates, activates or
reads a policy; there is no evaluator to write `beats_champion` and no consumer for `active`.
If it is kept as a placeholder instead, keep the corruption fix — without it the feature's only
observable behavior is destroying its own rows.

### Cross-cutting — the trigger gap
Three of the readers above (`_recall_gap`, `_bad_derivation_rate`, `_eligible`) sit behind
curation job types (`health`, `decay`) that **no code ever enqueues**, while `config.py:154`
ships a cron string nothing reads. Adding that trigger is a genuinely small change and looks
like the obvious win — do not make it first. Turned on today it would begin recording
`extraction_recall_gap > 1.0` and a constant `bad_derivation_rate: 0.0` into `health_runs`,
i.e. persist two meaningless numbers as if they were measurements. Fix §1a and §3 first.

---

## Exercise results

`tests/exercise/exercise_learning.py` drives all four subsystems synthetically against a real
`ChronicleCore` (hashing embedder, temp home) and asserts observable state, not call graphs.
Every number quoted in this document comes from it. Run:

```
/usr/bin/python3 tests/exercise/exercise_learning.py
```

`Ran 21 tests … OK`, followed by the findings block (verbatim):

```
FINDING 2    calibration IS live  — calibrate(0.75): 0.75 -> 0.25; answer confidence 0.5 -> 0.25
FINDING 2    verify signal pinned — 2 obs, 0 correct, on facts whose value IS in the excerpt
FINDING 1b   decay sign inverted — utility=0.9 decays at 20d, utility=0.0 does not
FINDING 1b   utility never written — distinct utility over a real corpus: [0.0]
FINDING 4    policies inert       — activating an rrf_weights delta leaves search() identical
FINDING 1a   health.run() never triggered — health_runs rows after full ingest+drain: 0
FINDING 1a   retrieval_log IS read  — health._recall_gap (health.py:54); recall_gap=2.0 (>1: not a rate)
FINDING 3    precision pinned     — workplace_location n=1 correct=1; bad_derivation_rate=0.0
```

Subsystem coverage:
1. **Credit assignment** — logs retrievals and asserts `_recall_gap` reads them; drives real
   `answer()` calls to reproduce `recall_gap > 1.0`; confirms `health_runs` stays empty without
   an explicit call; verifies the EWMA arithmetic and that nothing in production invokes it;
   demonstrates the decay sign inversion through the real `decay_sweep`.
2. **Calibration refit** — drives `chronicle_verify` end to end, shows every correct belief is
   recorded `refuted`, shows the excerpt that *would* verify it is reachable via
   `get_justifications`, and measures the resulting confidence collapse once `min_obs` is met.
3. **Rule precision** — ingests two sentences, confirms `_bump_precision` fires automatically,
   asserts `precision_correct == precision_n` and `bad_derivation_rate == 0.0`; separately
   hand-seeds a low-precision row to show the auto-disable logic is correct and unreachable.
4. **Policy champion/challenger** — exercises the bounds, the active cap, the corruption
   regression, the unknown-version guard, and proves activation has no effect on `search()`.

## Final verdict

| Subsystem | Verdict |
|---|---|
| Credit assignment | **WIRED-BUT-DORMANT** (log→health leg) / **UNWIRED** (`record_outcome`→`utility` leg) |
| Calibration refit | **WIRED** — and actively mis-training |
| Rule precision auto-disable | **WIRED-BUT-DORMANT** — signal pinned, and `bad_derivation_rate ≡ 0.0` is reported as a metric |
| Policy champion/challenger | **UNWIRED** |

The premise "nothing has ever measurably trained" holds for three of four, but not for
calibration: it is wired end to end, it does change what the agent is told, and it is wrong.
Fix it (one line) or stop feeding it (one line) before excising anything else.
