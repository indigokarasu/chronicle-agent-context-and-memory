# Chronicle Subsystems — Wiring Audit (§t3.a)

Ground truth given for this audit (production corpus): **contradictions=6, corrections=0,
reflections=0, user_knowledge=0**. The prior pass at this document verified none of that
against the store — it read every subsystem's dispatch chain, saw the chain was intact, and
called all five "WIRED", including a table that listed corrections as "6 rows (corpus)"
(a copy-paste of the contradictions number). This version traces each one to an actual
runtime trigger and checks which triggers can fire without a human/agent explicitly choosing
to call a specific tool — that distinction, not "does `getattr(self, f'_t_{name}')` resolve",
is what separates a subsystem earning its production rows from one that only *could*.

Method: for each subsystem, find every caller of its store writer (`grep -rn` across
`engine/`, `provider.py`, `context.py`, excluding `tests/`), then walk each caller backward to
either (a) an automatic engine trigger — something that runs as a side effect of ordinary
capture/extraction, with no explicit tool call required — or (b) an agent-facing tool that
requires an external LLM to decide to invoke it. **WIRED** = path (a) exists, or empirical
production evidence confirms the path fires. **UNWIRED** = every path is (b), and nothing
outside `tests/` and the generic `tools.dispatch()` shim actually calls it.

A second finding runs through several of these: two places in the tool-dispatch layer report
success without confirming the write actually landed (see `chronicle_correct` below, and
`tests/exercise/test_manual.py`, which now checks real store state instead of trusting the
JSON status string dispatch() returns).

---

## contradictions (`contradictions` table, §24.1)

**WRITER**: `store.open_contradiction(belief_a, belief_b, detail)` — store.py:380

**CALLERS**:
- `reducer.py:329` — `_apply_fact_conflict()`, called from `_on_asserted` (reducer.py:123) for
  `kind="fact"` when an existing active fact conflicts and `DOMAIN_POLICY[domain]` is
  `"flag_for_review"` (`domain="user"`, reducer.py:26).
- `reducer.py:159` — `_on_contradicted()`, handler for an explicit `"contradicted"` event.
  **Nothing ever emits a `"contradicted"` event** — no tool schema exists for it either
  (`tools.py:schemas()` has no `contradict` entry) — so this handler is unreachable outside
  a test that constructs the event by hand. Dead in production.
- `health.py:82` — `consistency_sweep()`, a direct store call bypassing the event log
  entirely. Engine callers do exist, and all of them are curation-job handlers:
  `curation.py:177` (`_task_contradiction`), `curation.py:215` (`_task_consistency`), and
  `curation.py:218` (`_task_health` → `core.health.run()` → `health.py:41`'s sweep). **So
  `core.health.run()` IS called from engine code** — correcting an over-broad claim in the
  prior version of this document, which asserted nothing outside `tests/` called it.
  The verdict does not change, because handlers are dispatched by job name
  (`getattr(self, f"_task_{job['task']}")`, curation.py:42) and **nothing ever enqueues those
  job types**: every `enqueue_curation` call site in `engine/` writes only `"canonicalize"`
  (curation.py:101), `"extract"` (reducer.py:102, capture.py:133, retrieval.py:170,
  curation.py:227), `"verify"` (tools.py:122), `"journal_ingest"` (core.py:175), or
  `"session_summarize"` (capture.py:135) — never `"health"`, `"consistency"`,
  `"contradiction"`, `"consolidate"`, `"identity"`, `"derive"`, `"decay"`, or `"reextract"`,
  despite all being valid `curation_jobs.task` values (store.py:921-923) with real handlers
  (curation.py:172-228). Config even ships a cron for it — `health.schedule = "0 4 * * *"`
  (config.py:121) — but no code in `engine/`, `provider.py`, or `context.py` reads that key
  (the only `cfg.get("health.…")` reads are `ghost_fact`/`self_heal.tier1_auto`, health.py:28,38,
  both *inside* `run()`). Out of tree, the dashboard's job-enqueue endpoint likewise only ever
  writes `"extract"` (dashboard/plugin_api.py:216). Outside curation, only
  `test_health_criticality.py` and `test_build.py:414` call `health.run()`.
  **Handler wired, trigger absent — dead in production.**

**VERDICT: WIRED** — but only through the `reducer.py:329` path, and that path requires no
explicit tool call at all. Runtime call path: `capture.observe()` (any conversation turn) →
`reducer._on_observed` (reducer.py:102) auto-enqueues an `"extract"` job → `curation._task_extract`
(curation.py:63) → `_emit_item()` (curation.py:114) appends an `"asserted"` event with `domain`
resolved via `domain_for(source_type)` (curation.py:26-27, `"session_transcript"→"user"`) →
`reducer._on_asserted` → `_apply_fact_conflict` → `store.open_contradiction`. This is a pure
side effect of ordinary fact ingestion, not an agent decision.

**Confirmed empirically**: `tests/exercise/exercise_ku.py`, ingesting the 20 real
knowledge-update instances in `s_ku20.json` through this exact path, opened **156**
contradiction rows (see its output). `tests/exercise/test_manual.py`'s
`test_contradiction_from_conflicting_facts` reproduces the mechanism directly on two
`remember()` calls — see the defect note below for why *that* specific case fails.

**Defect found while tracing this** (not fatal to the verdict, but real): the automatic path
above only protects facts ingested through the extraction pipeline. Facts written directly via
the `chronicle_remember` tool do not get it: `_t_remember`'s payload (tools.py:101-104) never
sets a top-level `"domain"` key — only `key["domain"]="user"` (tools.py:92), which the identity
lookup uses but the policy resolution does not. `reducer.py:111`
(`event.get("domain") or p.get("domain", "general")`) reads the payload's *top-level* `domain`,
finds nothing, and defaults to `"general"` → `DOMAIN_POLICY["general"]` is `"refetch"` →
`_apply_fact_conflict`'s `else` branch (reducer.py:333-334) doesn't even supersede: it just
bumps `last_seen_at` on the old row and silently drops the new value. Verified directly:
remembering "My favorite color is blue" then "My favorite color is green" for the same
entity+attribute leaves the store showing `value="blue", status="active"` — no new row, no
supersession, no contradiction (`test_manual.py::test_contradiction_from_conflicting_facts`,
an intentional FAIL documenting this). **Recommend fixing** `_t_remember` to set
`payload["domain"] = key.get("domain", "general")` so tool-written facts get the same
conflict handling as extracted ones — this is a one-line fix with an outsized effect, since
`remember` is the primary agent-facing write tool.

---

## corrections (`corrections` table, §24.1)

**WRITER**: `store.record_correction(belief_id, reason, correction_ref, propagated)` — store.py:398

**CALLERS**:
- `reducer.py:174` — `_on_corrected()`, handler for a `"corrected"` event. The **only**
  emitter of that event is `tools.py:108` (`_t_correct`, the `chronicle_correct` tool) —
  requires an agent to explicitly call it.
- `reducer.py:535, 542` — `_cascade()`, called from `_on_corrected` (already tool-gated above)
  and from `_on_retracted` (reducer.py:176-181, fired by a `"retracted"` event). `"retracted"`
  is emitted by: `tools.py:113` (`_t_forget`, explicit `chronicle_forget` call);
  `forgetting.py:70` (`unlearn()`, called only from `tools.py:118`, explicit
  `chronicle_withdraw_consent` call); `health.py:41` (self-heal orphan retraction) — but that
  is inside `health.run()`, whose only production entry point is the `"health"` curation
  handler (curation.py:218), and nothing ever enqueues that job (see contradictions above). So
  even the cascade path bottoms out in an explicit tool call every time.

**VERDICT: UNWIRED in production.** Every path to `record_correction` requires an agent to
explicitly invoke `chronicle_correct`, `chronicle_forget` (with a derived dependent belief
present), or `chronicle_withdraw_consent` (ditto) — there is no automatic engine trigger
analogous to contradictions' extraction-conflict path. This matches the given ground truth
(0 rows) exactly: after presumably substantial real usage, no agent has ever invoked any of
these with a cascading effect.

The mechanism itself is not broken, though: `tests/exercise/test_manual.py` calls
`chronicle_correct` directly and confirms a real corrections row is written and the old
belief's `status` really flips to `superseded` (not just a `{"status":"corrected"}` string).
**But** it also documents a genuine defect found in the process:
`_t_correct`'s `new_value` is never persisted. `_on_corrected` (reducer.py:166-170) marks the
old belief `superseded` when `new_body` is present but — unlike `_apply_fact_conflict`'s
`newer_wins`/`flag_for_review` branches (reducer.py:313-328), which call `_insert_belief` for
the replacement — never inserts a belief carrying the corrected value. Net effect: calling
`chronicle_correct(new_value=...)` deletes the fact rather than updating it (verified:
`test_manual.py::test_correct_new_value_is_discarded`, an intentional FAIL).

Also worth noting for scale: `record_correction` unconditionally fires even when
`store.find_belief(b_id)` (reducer.py:167) finds nothing — i.e. calling `chronicle_correct`
with an id that isn't a real `belief_id` (an event id, say) writes a corrections row with a
belief_id that matches no belief, while silently doing nothing to any actual state. This is
exactly the bug the prior version of `test_manual.py` tripped over: it passed
`remember_result['event']` (an event id) as `belief_id` and asserted only that a corrections
row existed, which passed regardless of whether anything real happened.

**Recommendation: document-dormant, don't wire, don't delete.** It's a real, working (modulo
the `new_value` defect above) user-facing correction capability; deleting it removes
functionality a user could legitimately invoke with no corresponding benefit, and the code
itself is small and self-contained. The actual gap is that nothing in the current agent
loop/prompting surface ever calls it — that's a product problem, not an engine one. Do fix the
`new_value`-discarded defect regardless of usage, since it makes the tool actively
counter-productive when it IS called.

---

## reflections (`reflections` table, §24.1; §23 plan_context goal tracking)

**WRITER**: `store.add_reflection(reflection: dict)` — store.py:714

**CALLERS**:
- `reasoning.py:91` — `ReasoningLayer.reflect()`, called **only** from `tools.py:154`
  (`_t_reflect`, the `chronicle_reflect` tool) — requires an explicit agent call. No other
  caller exists anywhere in `engine/`, `provider.py`, or `context.py`.

**VERDICT: UNWIRED in production.** No automatic trigger exists — nothing in
capture/extraction/curation ever calls `reflect()` on its own; it is purely an
agent-invoked, agent-facing "log a lesson learned" tool. Matches the given ground truth (0
rows) exactly.

The mechanism itself works when invoked: `test_manual.py::test_reflect_writes_row` confirms a
real `reflections` row is created (not just a `{"status":"reflected"}` string), and that a
durable lesson (>12 chars) also gets asserted as a `procedure` note (reasoning.py:94-99) —
both are real, correct side effects.

**Recommendation: document-dormant, don't wire, don't delete.** Small, correct, cheap to keep.
Zero usage is a prompting/UX gap (the agent is never told to call `chronicle_reflect` after an
outcome), not a code defect — fixing that is out of scope for an engine change.

---

## user_knowledge (`user_knowledge` table, §24.1; §19 epistemic tracking)

**WRITER**: `store.upsert_user_knowledge(uk: dict)` — store.py:623

**CALLERS (write side)**:
- `reducer.py:222` — `_on_informed()`, handler for an `"informed"` event. The **only** emitter
  is `tools.py:162` (`_t_note_informed`, the `chronicle_note_informed` tool) — explicit agent
  call, direct `self._emit(...)` — it does **not** go through `EpistemicModel.note_informed`.

**Dead-code sidebar**: `EpistemicModel.note_informed()` (reasoning.py:28-32) is a convenience
wrapper around the same `"informed"` emission — and has **zero callers anywhere**, including
`tools.py`, which bypasses it entirely. Not test-only, not tool-gated — genuinely unreachable
dead code. **Recommend deleting it outright** (not "document-dormant" — there's no reasoning
to preserve a wrapper nothing calls and whose one caller already does the same thing inline).

**CALLERS (read side, working)**:
- `retrieval.py:235` — `annotate()` reads `user_knowledge` to decide `why=never_told` /
  `why=likely_forgotten` hints inside `get_context`.
- `tools.py:216-217` — `_t_what_user_knows`, the `chronicle_what_user_knows` tool, a direct
  read.

**VERDICT: WIRED for reads, UNWIRED for writes.** The read path is real and exercised on every
`get_context`/`plan_context` call — it's just reading a table nothing ever populates in
production, so `annotate()`'s branches are always the "never told" default and
`what_user_knows()` always returns empty. Matches the given ground truth (0 rows) exactly.
`test_manual.py::test_note_informed_writes_row` confirms the write mechanism itself is correct
when invoked directly (a real `user_knowledge` row with `state="told"` is created).

**Recommendation**: delete `EpistemicModel.note_informed` (dead code, no caller, no cost to
removing it). Document-dormant the tool-facing write path (`chronicle_note_informed`) and
the read path — both work, and the read path degrading to "nothing has ever been told" in the
absence of writes is a safe, low-risk default, not a crash or a wrong answer.

---

## chronicle_correct tool (§23 tools, correct sub-tool)

**DEFINITION**: `tools.py:107-110` — `_t_correct(principal, args)`

**PAYLOAD**: `{"belief_id": str, "new_value": str, "reason": str}`

**REGISTERED**: `tools.schemas()` (tools.py:43); **DISPATCHED**: `tools.dispatch()`
(tools.py:68-76); **EXPOSED**: `provider.get_tool_schemas()` / `provider.handle_tool_call()`
(provider.py:148-154), the actual Hermes-facing surface.

**VERDICT: WIRED as a tool.** The full chain —
`provider.handle_tool_call → tools.dispatch → _t_correct → capture.append("corrected") →
reducer._on_corrected → store.record_correction` — is intact and mechanically verified
end-to-end (`test_manual.py::test_correct_creates_row`,
`test_correct_changes_real_belief_status`). This is the same tool underlying the
`corrections` subsystem above: functionally correct plumbing, zero production invocations,
and one real defect (`new_value` is discarded rather than persisted as a replacement belief —
see `corrections` section). **Recommendation**: fix the `new_value` defect (small, targeted:
mirror `_apply_fact_conflict`'s `_insert_belief` call for the `newer_wins` case); no reason to
delete a tool whose plumbing works and whose contract is easy to complete correctly.

---

## Summary

| Subsystem | Automatic trigger? | Production rows (given) | Verdict | Recommendation |
|---|---|---|---|---|
| contradictions | Yes — extraction fact-conflict (reducer.py:329), no tool call needed | 6 | **WIRED** | Keep. Fix the `chronicle_remember` domain gap (missing top-level `domain` in payload) so tool-written facts get the same protection. |
| corrections | No — every path requires an explicit tool call | 0 | **UNWIRED** (mechanism correct, never invoked) | Document-dormant, don't delete. Fix the `new_value`-discarded defect regardless of usage. |
| reflections | No — `chronicle_reflect` only | 0 | **UNWIRED** (mechanism correct, never invoked) | Document-dormant, don't delete. |
| user_knowledge | No — `chronicle_note_informed` only (write); reads are wired and working | 0 | **UNWIRED** (write); WIRED (read) | Delete dead `EpistemicModel.note_informed`. Document-dormant the rest. |
| chronicle_correct (tool) | N/A — agent-invoked by design | n/a | **WIRED** (dispatch-verified), zero production calls, one real defect | Fix the `new_value` defect. |

**Bottom line**: contradictions is the one subsystem here that earns its production rows
through ordinary operation — everything else in this list is real, dispatch-verified,
functioning code that simply has never been called by an agent, plus two independently
verified defects (`chronicle_correct`'s discarded `new_value`; `chronicle_remember`'s missing
`domain`) that would matter even if usage picked up tomorrow.
