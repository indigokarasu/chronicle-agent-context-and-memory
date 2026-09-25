# Changelog

All notable changes to the Chronicle Hermes plugin. Versioning follows the
`version` in `plugin.yaml`.

## 5.10.1

**A question that names something reaches the records about it.** The per-turn relevance gate
keeps a line that shares only ONE of the question's words only when its vector is close to the
question (cosine 0.65 with the default embedder), because most one-word matches are coincidences.
A purchase record for a merchant the question names shares exactly one word with "what did I buy
at <Merchant> last week" (records never say "buy"), scored 0.52-0.59, and was dropped: the
question injected nothing although the records existed. A federated record now passes on one word
when that word is a proper noun of the question (capitalised, and not the question's first word);
common words keep the bar, and memory lines keep the old rule. `scripts/prefetch_eval.py
--with-embedder` measures the gate as it runs live: without vectors every item reads "no vector",
which is how the harness had shown this question as answered all along.

## 5.10.0

**Whole documents, grouped results, and search that finds the specific word.**

Built as one ladder of thirteen changes, each gated on the full suite before merging.

**Documents are searchable as documents.** A record may now carry *passage* vectors: its full
text is cut on paragraph, line, sentence and word boundaries into ~900-character passages, each
prefixed with the record's name and short identifying fields (a file's folder path, for example),
and embedded alongside the record's own vector. Search keeps one slot per record, scored by its
best passage, and shows that passage as the snippet, re-cut deterministically from the source so
nothing extra is stored. A source declares where its text lives (`passages: {column}` for a
column of the same row, or `passages: {from: {path, table, key_column, join_column, text_column}}`
for another database), with `size` and `max_per_record` limits. When the sweep sees a record
change, its vector, passages and bookkeeping row are dropped together. Before this, a long
document's vector saw only its opening, and a record whose text lived outside its card was
searchable by title alone.

**Results collapse into their container.** A source can declare `container: {column, label}`: search
hits that share a container, such as messages in one thread, show as the best one plus "and N more
in this thread". The key is read from the source at query time and never enters the record's
card, so declaring a container re-embeds nothing. With `path_separator`, the container is a
path: a question whose words all match segments of a folder path (a four-digit year must match a
year segment exactly) returns that folder with its file count and top files, and a year in the
path counts as a date hint.

**The keyword channel finds the specific word.** Each source's keyword search OR'd every token
into one query and kept the first five rows it found, in rowid order. A short common word riding
beside a proper noun could fill all five slots before the row the question named was reached.
Measured on a table where the specific rows sort after the generic ones: 0 of 5 hits named the
merchant before, 5 of 5 after. Tokens are now searched longest first, one bounded subquery each,
in one statement.

**Caches cannot serve a stale vector.** The event-vector cache now checks the identity of its
newest row, like the projection cache: a deleted-and-reinserted newest row keeps count and max
rowid, and used to go unseen. A per-table write generation catches the one change neither check
can: a vector rewritten in place. Only same-rowid writes bump it, because inserts, replaces and
deletes are already caught arithmetically, and writers that append with plain SQL must keep the
cheap append path.

**The wrong-dimension census reads no vectors.** It counted with a predicate that named the
embedding column itself, so SQLite read every blob. It now uses covering indexes on
(length(embedding), id) per vector table and never touches a blob page. The projection table had
no width index at all.

**Automation sessions leave the backfill queue.** The backfill sweep now writes the empty marker
row for an automation session directly, instead of queuing a summary job that only wrote the
marker. A skip without the marker would have kept those sessions in the sweep's candidate list
forever.

## 5.9.0

**The raw tier stops reading the disk, and the per-turn channel sees every source.**

Seventeen changes built as one ladder, each gated on the full suite (2,406 tests) and measured
on a production-sized store (2.3 GB, 742k events, 98k projection vectors) before and after.

**Speed.** `chronicle_search` warm went from 1.3–1.7 s to 0.46–0.60 s, and the first query in a
fresh process from 17.9 s to 3.6 s. Two causes, both in the raw vector tier:

- The projection tier paged every `projection_vectors` blob out of SQLite on every query (280 MB).
  It now shortlists candidates from an in-process float16 copy and re-scores only those rows from
  their float32 blobs, so results are identical to the paged scan (asserted to 1e-6 in tests) while
  the tier drops from 1.2–1.6 s to 0.33–0.36 s. The copy is invalidated by row count, max rowid AND
  the identity of the row at that rowid: a deleted-and-reinserted newest row keeps its rowid, which
  the count/max-rowid rule alone cannot see. (`retrieval.projection_cache.enabled`, default on;
  `max_rows` 400000 falls back to paging.)
- The wrong-dimension diagnostic ran `length(embedding) != ?` over the whole table on every query —
  a scan the width index cannot serve without a model predicate: 0.2 s warm and 10 s cold on the
  projection table alone. Its census is now remembered per table while the table stands still, and
  still reported on every query, so the once-per-process warning and the counter behave as before.

Also: connection pragmas (64 MB page cache, 512 MB mmap, a 64 MB journal size limit) declared under
`store.*`; a truncating WAL checkpoint in the nightly quiet window; a changed source row now drops
its stale vector so the backlog re-embeds the new text.

**Recall.** The federated read channel searched only the first `MAX_DBS` = 3 declared sources — a
cap that was never measured (the channel costs ~20–30 ms). It is now `federation.channel_max_dbs`.
On ten fixed questions through the per-turn prefetch, the number reaching no connected source fell
from 5 to 2 once every source was declared: schedule questions reach the calendar, purchases reach
transactions, documents reach the file index. `scripts/prefetch_eval.py` is the harness (read-only,
deterministic, no model calls). Automation sessions — most of a production store's turns — are no
longer embedded or summarized (`embeddings.skip_automation`, `sessions.summarize_automation`), and
already-queued jobs for them complete without a model call, which drains a backlog that had been
starving the user's own events. `chronicle_ask_about` now follows entity merges and accepts a name.

**Resiliency.** An unreachable embed server used to raise out of every explicit search; the query
path now degrades to lexical with one warning. The aged-job pruner deleted one batch per daily
health run against tens of thousands of new jobs a day, so the backlog only grew (186,827 dead rows
on the production store); it now loops up to `max_rows` per call. Long-retracted projection rows
(112k on that store) are pruned under `curation.retention.retracted_*`, never a row another row's
`superseded_by` points at. `git_queue` rows are written only when the mirror is enabled, so scripts
that construct the store directly no longer grow an undrained queue. Host-owned keys are read from
the section the host handed the core, not through the engine's declared config, which two
config-honesty tests had rightly flagged. A per-turn advisory skill suggestion can be attached from
an external router (`suggest.*`, default off): a hard time budget on a daemon thread, fail-open,
never on an automation turn.

Corrections to the audit that produced this ladder, recorded so the numbers stay honest:
`synchronous` was already NORMAL on engine connections (the audit's FULL reading came from a CLI
probe measuring its own connection), and the retention pruner was present, not missing — it was
under-provisioned for the job inflow.

## Unreleased — `keep_literals` is ON: the first flag to earn its default

The rule for this whole build was that nothing defaults on until a replay
shows a win. This one did, on two corpora that share nothing — a copy of the
production store, and real tool-shaped transcripts written by a different
agent doing different work — at the same budget:

    chronicle copy (3 sessions)   38.0% -> 45.1% literals kept   out tokens -675
    transcripts    (5 sessions)    1.8% ->  2.1%                 out tokens   -5

**+18.8% and +17.8% relative: the same number twice.** The absolute share is a
fact about how hard the session compresses, not about the flag — the
transcript sessions go 4,023,745 → 29,998 tokens, a 99.25% cut, and almost
nothing survives that either way. The relative figure is the one that
transfers, and it transferred.

It also keeps MORE messages while doing it (38→48, 45→52, 37→49): spending a
cut on literals leaves room, it does not take it. What a reader gets instead
of the sentence introducing the work is the port number, the path, the
container id and the command that failed.

**A correction to how the earlier numbers were reported.** Those runs had
`keep_weights.involatile` at 0.25 alongside the flag, and the pair was written
up as if it were one thing. Re-run with the weight at 0.0 the figures are
byte-identical on both corpora: the weight contributes nothing and the whole
effect is `keep_literals`. It stays at 0.0, so the shape scan it would pay for
is not paid for.

Everything the flag touches is still restorable either way
(`chronicle_expand`), so this decides what a reader sees without asking, not
what the store holds. Turned off, compaction cuts exactly as every release up
to 5.8.35 did.

## Unreleased — the redaction sentinel is Hermes', and the pointer is on

Jared: "`[redacted]` might confuse the system, why don't you just put the
correct pointer to the secrets system in its place?" Both halves of that are
right, and the second one has a specific answer in Hermes' own source.

**`[redacted]` was a dialect the host does not speak.** `agent/redact.py`
already masks to `«redacted-secret»`, `«redacted:ghp_…»` (prefix matched,
vendor label kept) and `«redacted-vault-secret»`, and its own "already
masked?" guards test `value.startswith("«redacted")` and `"***" in value`.
Chronicle's marker matched neither, so a host redaction pass did not recognise
Chronicle's output as masked and could mask it again. Chronicle had invented a
second convention where the host had one — the same mistake the spec warned
about for `secrets/<NAME>`. It now emits the host's.

**The pointer goes INSIDE the sentinel, not in place of the value.** Putting a
bare `vault_ab12cd34ef56` where the value stood is the shape Hermes
deliberately rejected, and its docstring for `_mask_token_nonreusable` says
why: *"an agent once wrote a truncated-looking mask back into a config file"*,
corrupting the stored credential (issue #35519). A bare pointer reads as a
usable string; an agent that round-trips a config writes it back over the real
secret. The sentinel cannot be pasted anywhere and still carries the pointer:

    OPENROUTER_API_KEY=«redacted:env:OPENROUTER_API_KEY»
    the Zoom login is vault_ab12cd34ef56 password: «redacted:vault_ab12cd34ef56»
    token «redacted:ghp_…»          ← vendor label only, Hermes' exact form
    password: «redacted-secret»     ← nothing in the text to point at

It also makes masking idempotent for free. A bare `vault_ab12cd34ef56` passes
`_looks_secret` (letters, digits, six characters), so the next fold would
re-mask Chronicle's own pointer; the guillemets match the existing prefix
guard and need no special case.

**`credentials.pointers` now defaults to ON**, at Jared's request. Because the
marker is a stored string and nothing migrates, a store will hold both shapes:
beliefs folded from now on carry the pointer, and the ones already masked keep
what they were masked with. That is the expected state, not a bug.

## Unreleased — the handoff was the one surface still carrying a credential

Found by asking what happens when Phase C and Phase E are both on, which is a
question neither phase's own tests ask.

A tool result that prints `OPENROUTER_API_KEY=…` used to reach the compacted
window three ways. Two were already handled: a capped tool result is masked
(`tiers.masked_and_shortened`) and a belief is masked in the fold. The third
was not — **the compaction handoff, which Chronicle writes itself, carried the
key in full.**

That is the one that mattered most, and not because the model has not already
read it. Chronicle writes that line from a span it is folding AWAY, and the
line survives where the span does not: after a rotation the child session
carries the handoff and not the turns behind it. An unmasked value there
outlives the message it came from and travels into a conversation that never
saw it.

Every handoff line — folded requests and folded steps both — now goes through
`engine/credentials`. Unconditional, like the other two surfaces: this is not
an optimisation waiting on a replay, it is the rule they already follow.
`credentials.pointers` only decides whether the marker also says where the
value lives, so the handoff reads `OPENROUTER_API_KEY=«redacted-secret»`
or `OPENROUTER_API_KEY=«redacted:env:OPENROUTER_API_KEY»`.

What deliberately did NOT change: a tool result that was KEPT keeps what it
said. That is the transcript, the agent it was given to can still search it,
and rewriting it is a different decision from masking a line Chronicle
authored. The test asserts that separation rather than leaving it to a
comment — after the fix, every message in the window still holding the value
is a `role: tool` original.

## Unreleased — Phase E: a masked value says where to fetch it

A bare marker is a dead end. An agent that meets one asks the user to type the
secret again, which is how a secret reaches a transcript twice. Behind
`credentials.pointers`, **default off**, the marker carries the pointer the
text was already holding:

    OPENROUTER_API_KEY=«redacted:env:OPENROUTER_API_KEY»
    the Zoom login is vault_ab12cd34ef56 password: «redacted:vault_ab12cd34ef56»
    token «redacted:ghp_…»

**It reads neither the vault nor the environment, and it cannot.** The vault
(`agent/vault_store.py`) exists precisely so that values never reach a tool
result, and guessing which vault item a masked string *was* would be inventing
a reference — which the spec forbade in the same breath as saying the form
`secrets/<NAME>` was illustrative only. Both mechanisms were read from source
before any of this was written: the vault takes `login`/`payment`/`address`
items referenced by an opaque `vault_<12 hex>` id and resolved server-side by
`resolve_secret()`; provider API keys are **not** vault items, they are
environment variables from the profile `.env`
(`agent/credential_persistence.py`).

So all this does is keep what the text said. Nothing it renders is secret: an
env-var name is not, a vault id is designed to be shown, and `sk-` is a
vendor's public prefix. A bare `password:` with no variable name behind it
gets no invented pointer — the sentinel stays bare. Tested end to end
through a real fold, and tested that no part of a secret survives either way.

Off by default because the marker is a **stored** string: turning it on
changes the text of every belief folded after it, while the ones already
masked keep the bare marker. That is a migration to choose, not a default.

One thing it broke and fixed: `_looks_secret` skipped an already-masked value
by testing `startswith(REDACTED)` — the whole bare sentinel, closing
delimiter included. With a label the marker is longer, so a second pass
re-masked its own output and appended a second pointer. It now tests
the opening delimiter. Masking has to be idempotent; the fold re-runs over beliefs it
has already masked.

Still not done in this phase, and named rather than glossed: nothing resolves
a pointer back to a value, and the raw transcript still keeps credential
values by design — the documented trade-off, worth re-deciding out loud rather
than inheriting.

## Unreleased — Phase C: a folded unit can leave a distilled episode

Phase C wants recall to return one compact episode instead of several raw
turns. **Production has no such episodes to return**: the live store holds 22
active ones and every one is the agent's own memory write, because the
transcript episodes were retracted as junk. So the phase needs a generation
step before its recall step, and the compaction already writes the text —
one line per folded unit saying what was called and what came back.

Behind `context_engine.digest_episodes`, **default off**: each folded step's
line is also kept as an episode (`source_type` `compaction_digest`, its fold
id as the source event, the session as `session_ref`), at most
`_DIGEST_EPISODE_CAP` (40) per pass so a thousand-turn compaction cannot
become a thousand beliefs. Identical work folded twice confirms one episode
rather than writing a second.

Two rules it keeps, both learned here:

* only a STEP becomes one. 5.8.1 removed digest episodes because the lines
  being extracted were the user's own requests restated, and the handoff
  quotes every folded request verbatim already.
* these describe the AGENT's work, not the user's life, so per-turn recall
  never injects them unasked (`_NOT_UNASKED` in engine/retrieval.py, beside
  the agent's own memory writes). Explicit search and the engine's own
  rehydration still see them — which is the question Phase C's second half
  ranks.

One thing the first pass got wrong, fixed here: `session_ref` was passed
alongside the key rather than inside it. It is half an episode's natural key
(`reducer._natural_key`: title + session_ref), so every digest landed with
`session_ref` empty — the same line folded in two different conversations
confirmed ONE episode belonging to neither, and the recall half below had
nothing to prefer over a session's raw turns.

### The recall half

Behind `retrieval.prefer_digest_episodes`, **also default off**: when a
distilled episode survives into the Tier-1 block, the raw fill below it caps
how many of that SAME session's turns it then spends budget on
(`retrieval.digest_session_excerpts`). Three things it is careful about:

* the cap binds across BOTH raw phases. Capping the ranked fill alone caps
  nothing — the session-window expansion returns every turn the ranked fill
  did not carry, so one kept excerpt put the whole session back and the block
  came within 0.7% of its unpreferred size. (That mistake produced a first set
  of numbers showing coverage *improving*; they are withdrawn.)
* a digest that was RANKED but cut by the Tier-1 budget prefers nothing, or
  the reader loses the episode and its turns both.
* per-turn recall is untouched. These episodes describe the agent's work, so
  it never sees them (`_NOT_UNASKED`), so there is never one to prefer.

**Measured, and the phase is not what it was written to be.**
`deploy570/digest_measure.py`, 5 real transcripts, 40 question/answer pairs,
budget 1200, offline embedder. "Answer words" is the share of the next
assistant turn's content words still on the page — scoring the QUESTION's own
words scores whether the block echoed the question, and the turn holding those
words is the turn this skips, so that number falls by construction:

      keep   chars     answer words
         0   -43.1%    -9.1 points
         1   -34.4%    -7.9
         2   -25.2%    -3.6
         4   -14.6%    -1.4
         6    -5.8%    -0.2
         8    -4.3%    +0.3   <- default
        12    -1.8%    +0.3

The large saving eats answers: a distilled line is ~220 characters of what was
called and what came back, and below about six kept turns it is replacing
turns that held the answer. The default is the most it saves for free, which
is 4.3% — real, small, and not the win the phase was written for. Both flags
therefore stay off, and this is the number a later run has to beat.

Two things the harness had to fix before it could measure anything, both of
which apply to the Phase B and D harnesses beside it:

* **the role is in the excerpt, not in `actor`.** A session_transcript capture
  writes every observed event with `actor='user'` (41,495 against 12,158
  `agent` on the August copy) and puts the real role in the text
  (`assistant: …`, `tool: …`). Rebuilding a session from `actor` hands the
  compressor a conversation of pure requests, no folded unit is ever a step,
  and the generation half cannot fire at all. `bench.py` and `tier_measure.py`
  both rebuild from `actor`.
* **the production copy cannot support this measurement.** Even with roles
  restored, 13 non-cron sessions on it reach 25 observed events and exactly
  ONE usable user question survives across all of them. The corpus used
  instead is a directory of real Claude Code transcripts — real conversations,
  real questions, real tool calls, i.e. the message shape a live compaction
  sees — and it is NOT Hermes sessions: a different agent, and engineering
  work rather than this user's life. Labelled as such wherever it is reported.
  The two sessions being written while the measurement ran were excluded.

## Unreleased — Phase D: a standing local benchmark

`deploy570/bench.py` (outside the repo, with the other harnesses) runs the
provider and the compaction against a COPY of the production store and writes
one JSON record: recall (items, characters, seconds, how many one-word and
few-word matches the floors judged), compaction (tokens in/out, messages,
seconds, exact literals still on the page, restorability), and the shared
score's distribution over a fixed sample. Pass a previous record and it prints
the deltas, so a change has to say what it did to the numbers before it earns
a default.

Two baselines are kept. Offline, against the August store copy
(`deploy570/bench_baseline.json`): 34 messages -> 246 items / 93,149
characters; 93,473 -> 29,595 tokens with 278 of 1,497 literals. Against the
live store, read-only, with the profile's own embedder and each message's own
session excluded as a real turn would
(`deploy570/bench_live_baseline.json`): 34 messages -> 27 items / 28,064
characters in 6.6 s, with the similarity floors doing their work (28 one-word
and 52 few-word checks, 984 gate drops); two real sessions 137,764 -> 56,839
tokens, keeping 701 of 2,006 exact literals (34.9%) in 0.54 s.

The two differ by four times on recall because the copy is a pre-cleanup
snapshot: it still holds 67,685 active episodes and 30,018 notes that
production has since retracted, most of them the phantom directives the
speaker-attribution fix removed. Offline runs are for comparing a change
against the previous offline run; the live figures are the ones that describe
production, and `CHRONICLE_BENCH_PROFILE` is what turns the real embedder on.

## Unreleased — Phase B: what may be summarised, and what only pointed at

**A cut for budget no longer spends itself on the prose.** Compaction's one
lossy step shortens a span that will not fit and leaves the id that restores
it; cutting the head keeps whatever happens to be first, which on these
transcripts is the sentence introducing the work, while the port number, the
path, the container id and the failing command sit further in and go.
`engine/tiers.py` classifies by shape — involatile (exact literals), critical,
context, pointer — and spends the same budget on the literals first, in the
cut path and in the handoff's step lines. A credential is the one literal that
does not survive: engine/credentials.py masks it first.

Behind `context_engine.keep_literals`, **default off**, and
`keep_weights.involatile`, **default 0.0**: with both at their defaults the
compaction is byte-for-byte what 5.8.35 produced (full gate, four modes).

Measured, not assumed. Replaying the largest real session out of a copy of the
production store (124 messages, 93,473 → ~29,600 tokens):

* literal-first cutting keeps **289 of 1,497 exact literals against 278**
  (19.3% vs 18.6%) at the same budget — +11, about 4% more;
* the `involatile` keep-weight changed **nothing at any value** (0.15 to 0.9),
  because 100 of 101 middle units on this corpus contain a literal: presence
  is not scarce enough to rank by, so a flat bump lifts everything;
* what the handoff can carry is the real ceiling: 25 step lines at 220
  characters, holding 285 of the 289 surviving literals.

Re-measured afterwards against the LIVE store (read-only), where only two
genuine sessions still hold enough turns to compact: 484 of 1,750 literals
against 473 (27.7% vs 27.0%), tokens slightly lower (55,311 vs 55,668). One of
those sessions gains 11 literals and the other is unchanged.

A third session did gain 9 points (83.1% → 92.1%) — but it is one of the
scratch sessions a harness leaked into the store on 2026-09-18, a copy of a
real transcript rather than a real one, so it is excluded from the figures
above. It does show the mechanism bites when messages are moderate-sized
rather than thousands of characters each.

So the flag stays off: under a point of aggregate gain is not a win worth
defaulting. The lever this measurement points at is not the cut but the
handoff's room and how densely a folded unit's literals are packed into its
line.

## Unreleased — Phase A: one importance model

**Recall and compaction score importance with one model.** The per-turn recall
gate (a message's content words, how many an item must share, when an
inflection counts) and the context engine's keep/evict score (recency, focus
match, salience and criticality keywords) were separate implementations of the
same question, with nothing to make them agree: a rule fixed on one side — a
URL's pieces are not content words, a short number is not either — had to be
remembered on the other. Both now call `engine/salience.py`, which also offers
the score over any unit (`Unit`, `rank`) so a turn, an episode and a memory can
be ordered the same way.

A pure extraction, moved verbatim. Accepted by replaying 34 real messages out
of a copy of the production store through both checkouts: recall blocks
byte-identical (93,149 characters), all 204 keep scores identical, full gate
green in four modes. `tests/test_salience_parity.py` pins the values and the
wiring (the names retrieval exports must BE salience's, and the engine must
call `keep_score` rather than re-implement it).

Not deployed: this track is local-only by the build spec.

## 5.8.35

**The Hermes plugin security scan passes, on Chronicle's own files.** The
validation workflow checked the validator (Hermes itself) out INSIDE the plugin
directory it validates, so the scan's first real run reported 4,282 "dangerous"
findings, every one in Hermes's own tests, docs and `.mailmap`. The validator
now lives in `$RUNNER_TEMP`. On Chronicle alone the verdict is `caution`, with
11 findings, each reviewed:

* **Fixed:** literal bidi-control characters in `engine/substance.py` (the
  table that strips Gmail's bidi isolates) and one test, invisible in review.
  Written as `\u` escapes (same code points); `tests/test_no_invisible_unicode.py`
  fails if a literal one enters any tracked text file again.
* **Intended test data, left as is:** `sk-FAKEfake...` and "hunter2" in
  `tests/test_credentials.py` (the credential masker's own fixtures, invented);
  "ignore previous instructions" in `tests/test_reader_text.py` and one
  CHANGELOG line (adversarial fixtures proving a forged `User:` line is never
  read as the user); `0.0.0.0` in `tests/test_onhost_guard.py` (an endpoint the
  on-host guard must classify, not a bind); `os.environ` in the workflow (the
  validator path) and a README paragraph about the hermetic suite.

A separate sweep of the tree and all history reachable from `main` found no API
keys, private keys or real credentials.

## 5.8.34

**CI green again.** The 5.8.33 cache tests assumed numpy; the CI runner has
none, so the cache (correctly) stepped aside and five tests failed. They now
skip without numpy, and a new test checks that without it the paged scan gives
the same answer. The Hermes plugin-validation workflow also installs
`packaging`, which the upstream validator imports (that job was already failing
on `main` before the merge).

## 5.8.33

**`chronicle_search`'s raw tier scores from memory.** The raw tier's vector pass
read every observed vector from SQLite a page at a time on every query; on the
production store that was ~3.0 of `chronicle_search`'s 3.4 s. Each process now
keeps them as a float16 matrix (`engine/vector_cache.py`, ~100 MB for 66k
768-wide rows) and scores a query against all of them at once. On a local
synthetic store of that size: paged scan 0.19 s, warm cache 0.064 s, first
build 0.39 s, identical top results. (Not measured on the production box: no
VPS work while deploys are frozen.)

* The result is the paged scan's: the same 0.1 floor, ACL check, automation
  exclusion and framing check, the same top-k heap; FTS hits are credited
  whatever their rank. Candidates are visited best-first, so the scan stops
  once nothing left can enter the heap. Scores differ from float32 by ~1e-3.
* Never stale: every use checks the table's row count and max rowid at the
  query's width. New rows are appended; a delete or a re-embed rebuilds.
* `retrieval.observed_vector_cache` (default on) and
  `retrieval.observed_vector_cache_max_rows` (250,000; above it, the paged
  scan). No numpy, or any error in the cache, also falls back to the scan.
* Not sqlite-vec: its index is filled only by new writes and never backfilled,
  so enabling it over a populated store hides every existing vector.

## 5.8.32

**The AI review threads on #20 and #23 that were real bugs, fixed.** Each has a
test in `tests/test_review_fixes_5832.py`, mutation-checked.

* **A hot rollback journal is never read `immutable`.** The write-back reader
  and the Tapestry read model fell back to `immutable=1` when a read-only open
  failed, checking only for WAL frames; a non-empty `-journal` needs a rollback
  that an immutable open skips, so they could read a half-written file. Both
  now refuse instead.
* **Tapestry read model:** an unreviewed people-store contact is counted as
  unclassified instead of being guessed to be a person; a merge cycle
  (A -> B -> A) lists its entity once under the smallest id instead of hiding
  every id in it; a fact history orders a version before the one that replaced
  it even when the replacement carries an earlier timestamp (a topological
  order, time breaking ties); the log opened from a fact or mention selects and
  centres the event it cites (facts now carry `src_seq`); speaker labels are
  looked up as own properties only; the place/concept counting is one helper.
* **`scripts/clean_entities.py`:** a live relationship keeps both of its
  endpoints (an entity only a relationship used could be dropped), and a merge
  moves relationship endpoints and fact `entity_id`s to the survivor.
* **An event fact written plainly is kept.** "bought dog food" and "went to the
  gym" were refused because nothing in them is capitalised. A short lower-case
  account with any word outside the notification vocabulary is kept; "Payment
  received", "Delivery delayed" and "Your order has shipped!" still are not.
* **Startup recovery is latched only when it succeeds.** A recovery that raised
  was marked done, so the rest of the process skipped it.
* **Folded attachments get distinct ids.** Two photos with the same caption
  flattened to the same text and so the same fold id; a message with parts is
  hashed as its full structure (a plain string keeps its old id).
* **The `/compress` preflight asks about what the next pass would touch.** After
  a compaction it looked at the settled prefix too, and could report content
  to compress when an extending pass had none. It now shares compress()'s own
  extend-or-rebase decision (`_settled_prefix`).
* **`migrate_vectors` stops counting framing-only sessions as unrecoverable**
  (no summary and no vector), agreeing with the health census, so such a store
  no longer fails every migration.
* Duplicate `ographer` suffix and a doubled `[` in a strip set removed; the
  context-engine stand-ins in `_base.py` are type-annotated.

## 5.8.31

**Merged with published `main` and the release branch.** This branch now
contains everything on `main` and on `release/v5.7.0`, so #23 and #20 can merge
without replaying anything.

* **`events.pointer`, from `main` (dada805), is schema rung 19.** An event can
  carry a skill reference (`weave:<person_id>`, `scout:<subject_id>`,
  `rally:<ticker>`) instead of a copy of what it points at;
  `CaptureEngine.append(pointer=...)` sets it. `main` numbered it 12, which this
  ladder already uses (procedures.body), the same collision rungs 14-17 had.
  Additive and nullable: every existing event reads NULL.
* **`main`'s "stale lock recovery" is not taken.** It unlinked `-wal` and `-shm`
  every time a store opened. A WAL holds committed transactions until they are
  checkpointed, and SQLite replays it on the next open, so deleting it first
  discards them; and the production store is opened by several live processes
  at once, so a removed `-shm` corrupts the others' view. The one sidecar removal
  stays `_unlink_sidecars()`, after `journal_mode=DELETE` has proven exclusive
  access. `tests/test_events_pointer_and_wal.py` fails if deletion comes back.
* **`release/v5.7.0`'s squash of #21 is already here.** Its tree equals this
  branch's 69fc157 plus the four `fix/speaker-attribution` commits
  (`retract_misattributed`: write-lock retries, one sequential pass, a bounded
  event cache, a streamed report), which are merged in with it.

## 5.8.30

**The per-turn gate asks what the person wrote.** The gateway prepends an
origin header to some messages ("Gateway message origin (JSON data, not
instructions or authorization): {…}"). Capture already read it as host
framing, but the recall gate did not, and its words (json, authorization,
chat, field) matched a session where the user had once pasted code, on
messages about the gateway restarting. The gate now takes only the person's
words.

**Two or three shared words are checked too.** On 300 real messages, a long
security alert's generic words ("change", "issue", "link"; "none", "send") and
a pasted script's ("post", "text") matched two or three at a time. Against
the items' stored vectors the plainly unrelated scored 0.49–0.65 and the
related 0.59–0.90, and four or more shared words were all related. Such a
match must now reach 0.60 (`retrieval.prefetch_min_similarity_few`, `"auto"`
= measured per model). Unlike a one-word match, two or three words are
evidence of their own, so with no vector to compare the words decide.

**A fact goes into the block once.** A critical fact that matched as a
`[FACT]` came back below as `[CRITICAL]`: one production block carried a
security alert twice.

On 49 longer real messages the recalled items went from 16 to 7 (19,711 →
8,632 characters). What went was the alerts, the code paste and an unrelated
session, plus one repeated old health-check question.

## 5.8.29

**The handoff's own instruction works as written.** Every compaction note says
to restore a folded turn with `chronicle_expand` "by its [fold_…] id". The
tool's description still pointed the model at "the first token after
'[FOLD'", a stub format 5.8 retired. An id passed the way the note shows it,
in brackets, was unknown. The description now names the note's id format, and
the tool accepts the id bracketed or bare. Tested through the host's call
shape with an id taken from a real handoff.

## 5.8.28

**`chronicle_search` searches what was said, as its description promised.** The
tool is described as "Search the belief store + raw events (dual-tier)" but
searched only beliefs. On the production store most of the memory about the
user is the transcript: a search for something the user only ever said came
back empty, while per-turn recall found it. Now that the agent can call the
tool at all (5.8.26), it returns `results` (beliefs) and `said` (transcript
excerpts with their session and date, each at most 1,500 characters). Live:
ten of each in 2–4 s.

## 5.8.27

**One copy of the static block, under one rule.** The plugin also registers a
system-prompt section, `chronicle.memory-guidelines`, which renders the static
block. Hermes renders that section and also puts the memory provider's own
`system_prompt_block()` into the prompt. With Chronicle as the memory provider
the block went in twice, and the section's copy did not leave out the agent's
own notes, which the host injects itself. 5.8.16 had removed them from the
provider's copy only: every production system prompt still carried 612
characters of stale copies, one cut off mid-sentence. The section now renders
nothing when Chronicle is the host's memory provider. It serves a host running
Chronicle as the context engine alone, and then follows the same
agent's-own-notes rule.

## 5.8.26

**The agent can call Chronicle's memory tools.** Hermes routes a memory
provider's tools by the list it takes at `add_provider()`, which runs before
the provider's `initialize()`. The model's own tool list is asked for again
later. Chronicle answered the first request with nothing, because its tools
lived on a core that did not exist yet. So the production log read "Memory
provider 'chronicle' registered (0 tools)" on every start, and the model,
shown `chronicle_search`, `chronicle_remember` and the rest, got "Unknown tool"
on all 77 calls it made from 2026-09-03 to 2026-09-17. The schemas do not
depend on the store, and are now returned before `initialize()`. Checked with
Hermes' own MemoryManager: 0 routable tools before, 35 after. The context
engine's tools (`chronicle_expand`, `chronicle_pin_context` …) were registered
by a different path and were not affected.

## 5.8.25

**A request is not something that happened, and a wanted state is not a fact.**
Three shapes from the user's real messages were still stored as memories:

- "…once everything is correctly backed up … run genie again" became an
  episode. The command followed a leading clause with no comma, and only a
  clause ending in a comma was recognised.
- "Same rules apply, don't out yourself, use the vibes skill on any prose"
  became an episode, because the commands came after commas. Command clauses
  are now taken out and the account stays: "There isn't enough space on the
  VPS …, so that isn't a viable path, figure out something …" keeps everything
  but "figure out …".
- "Fix is so that my library is a folder slskd can see" became a fact,
  library = "folder slskd can see". The generic "my X is Y" rule now ignores
  a state asked for (after "so that", "should", "want", "until" …), a
  hypothetical, and a sentence that opens with a command.

A listed verb after a subject, an auxiliary, a preposition or a determiner is
not a command ("I would run every morning before work"). Over 195 real
messages, exactly those three items went and nothing else changed.

## 5.8.24

**Masking is final.** 5.8.23 read its own `[redacted]` marker as a credential
value: masking text that was already masked trimmed the marker's closing
bracket and masked it again, so per-turn recall showed a belief the fold had
masked as `pwd=[redacted]]`. The detector also reported the masked text as
still holding a credential. A masked value is now never a credential, and
masking twice changes nothing.

## 5.8.23

**A credential is not a memory.** Users hand the agent logins to use. On the
production store the extractor turned two such messages, a site login and a
file-sharing account ("Username: … Password: …"), into episodes. Those are
beliefs, which per-turn recall puts into later prompts unasked and the
dashboard shows. Now (`engine/credentials.py`):

- The fold masks any credential value in a belief's key and body, on assert,
  derive and correct. The belief stays, masked: an appointment whose meeting
  link carries `?pwd=` is still an appointment. Being in the fold, a rebuild
  masks the ones already stored.
- Per-turn recall masks them in what it injects unasked.
- The transcript keeps the message, and the agent's own explicit search still
  finds it.

Detection is by shape. A labelled value counts (password, passcode, PIN, API
key, token, secret, private key, auth code, OTP, then `:`, `=` or "is", then
something that looks like a secret), as does a key-shaped token (`sk-…`,
`ghp_…`, `AKIA…` and similar). "The full password is not in the log" and
"Your password has been updated" name no value and are left alone. On the
production store one active belief held one: an appointment's meeting
passcode.

## 5.8.22

**An importer's sender and sent-date no longer vouch for a subject line.** The
rule that a fact must say what happened (5.7.3) keeps a value with a quoted
title or an explicit date. The email importer appends `| from "<sender>" |
<sent-time>` to every value, so the quoted sender and the sent-time passed
both tests, and every subject line it wrote was kept. The production store
held "Delivered 1 item: Skin Care", "Your Subscription Renewal" and "Your return
drop off confirmation" as things the user had bought. The rule now judges the
value without those provenance segments. An event date in its own segment
("Dinner at Fake Izakaya | 2026-09-12") is content and stays.

**A count of items names nothing.** "Delivered 1 item: Clothing" is the owner's
own example of noise, and the rule still kept it because the capitalised store
category after the count read as a name. A value whose object is a count of
items ("Ordered 3 items: Appliances, Health Care, and more", "Shipped: 3 Pet
items") now says something happened without saying what. A thing named first
and counted after ("Refund issued for Acme Fake Switch… and 3 other items") is
kept.

Replayed over all 1,488 active facts on the production store: 45 refused, each
read and each noise (37 item counts, 8 subject lines). The first version of the
count rule also refused the switch refund, and was narrowed to a count as the
object before release.

## 5.8.21

**Per-turn recall no longer repeats the conversation in progress.** The
provider captures every turn as it happens, so a follow-up found the user's
own message from minutes earlier and injected it again, though it was still
in the model's window. On the production store, 10 of 101 real messages got
an excerpt of their own conversation from before them: 23,000 characters,
about 40% of everything recalled. Prefetch now passes the live session, and
retrieval leaves its turns out, the session window included. The exception is
the copies the context engine wrote when a compaction folded messages out of
the window, which are exactly what the window no longer has. Explicit search
is not narrowed. With the rule on, the same messages got 0 such excerpts;
recall from other conversations was unchanged (21 items).

**A one-word match nothing can vouch for is left out.** In 5.8.19/5.8.20 a
one-word match fell back to the word rule when the embedder could not answer
in time. Under load that let every coincidence back in: one probe run over the
same messages carried 30 belief lines instead of 6. With a floor in force, an
unvouched one-word match is now dropped (71 of 75 were coincidences). An
embedder the gate cannot ask, such as hashing, has no floor and keeps the
word rule.

## 5.8.20

**An item with no vector to compare is embedded on the spot, if short.**
5.8.19's check needs the item's stored vector; entities have none, and a few
facts and the newest turns are not embedded yet, so their one-word matches
passed unchecked. Live that was "address and fix all the issues" bringing an
entity named "Issue-closing" and "…would return nothing?" an Amazon return
receipt. A short item (240 characters or less) with no vector of this model
is now embedded on the spot. That's at most three per turn, all of a turn's
gate requests within 1.5 s, and a long one keeps the word rule. The second
directive path (topic notes) now carries the note's id, so a directive is
checked on either path. Over 400 real messages: 59 one-word matches, 55
dropped, 4 kept (0.66–0.75); a turn's recall took 0.08 s at the median and
0.60 s at the slowest.

## 5.8.19

**A short message's one shared word must also be near it in meaning.** A
message with three content words or fewer passes the per-turn gate on a single
shared word, and on the production store that word was usually a coincidence.
Over 250 real messages there were 64 such matches: "system health check"
brought a prescription refill (its attribute is `health_event`), "address and
fix all the issues" refunds that were "issued", "why is the gateway restarting
every 10 mins?" two contacts named Min, "sure get it set up" a model-switching
chat. The item's stored vector against the message's separates them. Read one
by one, the plainly unrelated matches scored 0.32–0.64 (nomic-embed-text) and
the plainly related ones 0.66–0.75. A few loosely related ones — an older
question about the same tool — fell on both sides. A one-word match is now
kept only at 0.65 or above (`retrieval.prefetch_min_similarity`, `"auto"` =
the floor measured for the model, none for an unknown one). The message is
embedded once, only when a one-word match needs it, in one request with a
one-second limit that never trips the embedder's breaker. With no vector of
the item's, or no answer in time, the word rule stands as before. Each
decision is in `last_context_debug["relevance_gate"]["one_word"]`.

**A long session's compactions no longer slow down pass after pass.** Naming
the entries the handoff has no room to show compared each one against a list,
and the lists grow all session. Over 150 compactions of a synthetic 3,000-turn
session, a pass went from 0.15 s to 0.49 s; it now stays at 0.15–0.2 s, and
the output is identical. A new test runs 25 compactions and checks that every
pass lands at the target, the newest request survives, and the handoff does
not grow.

**A pass over the message count keeps the count.** 5.8.18 moved the user's
newest request out of the tail into a list of its own, and the count of kept
messages did not include that list: a pass folding down to half of
`hygiene_hard_message_limit` kept one message more than half. (5.8.18 was
released after a gate whose log was stale; the full suite, run properly,
caught it. The gate now writes its own log.)

## 5.8.18

**The user's newest request survives a tight budget wherever it sits.** A
seeded fuzz of `compress()` (multimodal content, None content, tool calls
that are not dicts, results with no id, system notes mid-list, host
persistence markers) found one way to lose the request: on a small context
window, the protected tail's newer tool results and the leading system
messages claimed the budget before the request was reached, and it was
dropped. The request is now fitted second — right after the newest unit —
whether it is in the tail or further back. The fuzz runs 60 seeds, two
passes each, and checks: nothing raises, no call/result pair is split, at
most one handoff and never in the system role, no persistence marker, the
newest request kept (whole, or shortened with the id that restores it).

## 5.8.17

**The handoff alternates the way Hermes counts turns.** The handoff's role was
the opposite of the last row before it, a tool row counting as the
assistant's side, so after a tool loop — "…tool result, [handoff], the user's
request" — it came out as a second user message in a row. Hermes places its
own summary against the roles a strict chat template counts, where tool rows
and an assistant's tool-call row are exempt; so does the handoff now (after a
tool loop the last counted turn is the user's request, and the handoff is the
assistant's).

## 5.8.16

**The agent's own notes come from the agent's own file.** Every directive in
the production static block was a copy of something the agent wrote with its
memory tool — and Hermes' built-in memory already puts the agent's CURRENT
memory file into the same system prompt. Chronicle's copies were older: one
read "never answer from a assumed location (e", cut off mid-sentence by an
earlier extractor, while the agent's file had since rewritten it. When the
host injects the agent's memory itself (`memory.memory_enabled`), the static
block leaves those copies out; outside Hermes, or with built-in memory off,
Chronicle's copy is the only one and stays. The user's own directives are
always included.

## 5.8.15

**Every system prompt carries only what must always be there.** The memory
provider's static block goes into every agent's system prompt — scheduled
jobs included — whatever the turn is about. On the production store its
"CRITICAL" section was the user's medical history (a prescription refill, a
lab visit, a past procedure: medical facts are critical so they never decay,
and "Quest Diagnostics" is medical by its name), and its "USER PROFILE" an
attended birthday. The always-on section now holds safety facts only (an
allergy, anaphylaxis, a DNR); medical facts still never decay and still
surface when a message is about them. The profile leaves out events — what
happened to the user, not who they are.

## 5.8.14

**An instruction about the task in hand is not a standing one.** A standing
instruction becomes a directive injected into every later turn. The
classifier took any "don't …", "never …" or "I want you to …" — so, from the
user's real messages, "Don't try to come up with a fix yet, just understand
the issue", "don't stop until you have any stuck or broken processes fixed"
and "I want you to review the search code here <url>" would each have told
the agent, forever, not to fix things or to keep going. An instruction scoped
to now ("yet", "for now", "until", "this", "here", a link) is not standing
unless it says so ("always", "never", "from now on", "ever"). The five live
directives are the agent's own memory writes and are untouched.

## 5.8.13

**The episode rule, tightened where it leaked and loosened where it lost.**
Over 195 real messages 5.8.12 still made episodes of "Then proceed with the
plex option…" and "Yes, and once everything is backed up, run genie again"
(a command after "yes" or a leading clause), and would have dropped a story
that opens like a question ("When we got to Riverton, …"). A command is now
found after an affirmation or a leading "once/when/if …," clause — one that
ends in a comma: the real "Yes, and once everything is correctly backed up
and will back up run genie again" still slips; a question without its "?"
is recognised only by an auxiliary opening ("can the…", "is there…", "did
the…"), not by "when" or "what", which open narrative too. Over the 195
messages: 9 episodes remain, mostly statements about the user's own systems.

## 5.8.12

**An episode is something the user says happened.** The heuristic extractor
made an episode of every user message over 60 characters. Run over the
user's sixty most recent real messages, that rule made 17 episodes, and every
one was a request to the agent or a question: "Just work through all of them
one by one…", "Come up with a way to ensure backups…", "Would any of this
help SIFT? <url>". A sentence now counts only when it does not ask (a "?", or
an opening such as "can", "what" or "did"), does not speak to the agent
("you", "please"), and does not open — after a filler word or two — with a
command; the episode is those sentences. Same sixty messages: 17 → 0 such
episodes, while "My sister moved to Riverton last week. Can you remind me to
call her?" still keeps its first sentence.

**A reply quote is the host's.** When the user replies to a message, the
gateway quotes it — usually the agent's own — as `[Replying to: "…"]` ahead
of what the user wrote, over as many lines as it has. That quote was read as
the user's words. It is host framing now (no stored memory came from one).

## 5.8.11

**A folded tool step says what happened.** Each folded tool step is one line
in the handoff, and on a real session most of that line was envelope:
`terminal({"command": "journalctl -xn 50 …", "timeout": 10}) → {"output":
"░░ \nThe job identifier…", "exit_code": 0, "error": null}`. The line now
carries the call's telling argument (the command, path, query or URL) and the
result's error if it has one, else its output, with a non-zero exit code:
`called terminal(systemctl start nginx) → exit 1: Job for nginx.service
failed…`.

**The README says how compaction and per-turn recall behave** — the policy it
follows, what it keeps, the handoff, restoring a folded turn, cache behaviour,
what goes into a turn unasked — and lists the new keys.

## 5.8.10

**The user's newest request is always kept.** In a long tool loop the request
the agent is working on sits further back than the protected tail (twenty
messages of calls and results), and a compaction could fold it — leaving it
only as a line in the handoff, which tells the model to answer "the latest
user message after this note". Hermes' own user-turn guarantee does not fire
while the protected head still holds an older request. Replayed over six real
sessions it happened in one pass of eleven; driving a compaction through
Hermes' own `_compress_context` showed the same. The newest real user message
is now kept verbatim, after the handoff, whenever the tail does not already
hold one.

## 5.8.9

**The gate matches words, not prefixes, and a long message needs two.**
Sampled on fourteen real messages against the production store, most of the
per-turn block was a coincidence of letters: any extension of up to three
letters counted as the same word, so "repos" drew "earnings report", "rich"
Richard, "access" accessories and "spec" a person named Specht; a pasted URL
contributed "https", "com" and its year; and in a long message a single
shared word — "fire every hour" and "SF Fire Credit Union", "suite" and every
street address with a Suite B — was enough. Now:

* two words are one only as an inflection: an ending (s, es, ed, d, ing, er,
  ers), a doubled consonant (plan/planned), a dropped "e" (bake/baking) or
  "y" as "i" (happy/happier);
* URLs and numbers of four digits or fewer are not content words;
* a message with more than three content words needs two of them in an
  item.

Same fourteen messages: 22,100 → 9,200 characters injected; seven of them
now get nothing, where everything they got was such a match. (The threshold
also had to get its own name: `need` is reused further down the function for
character budgets, and the closure read the later value.)

## 5.8.8

**Without its store, a compaction still keeps tool calls whole and says what
went.** The fallback used when the core cannot open kept `body[:3] +
body[-6:]`: a cut that could start the tail on a tool result whose call was
dropped, hoisted every system message to the top, and left no trace of what
was dropped. It now cuts the protected head and tail on whole tool units,
keeps leading system messages where they are, and leaves one handoff that
says plainly the folded turns are gone (nothing could be archived, so it
names no ids) and quotes the user's requests from them.

**An archive copy stays out of the user's own index.** A copy of a turn the
memory provider already captured was also indexed in `observed_user_fts`, so
per-turn recall could show the same turn twice. It stays searchable and
expandable through the main index.

Also removed: the pressure-warning helpers no path called since the warning
moved into the handoff.

## 5.8.7

**The budget counts what is sent.** Hermes stamps each user turn's recall
block into an `api_content` sidecar and replays that sidecar, not `content`,
on every later call; its own compressor charges the sidecar. Chronicle
charged `content`, so every kept turn's recall block (up to 4,800 characters
before 5.8.4) went uncounted. It is charged now; when the protected spans do
not fit, a turn's stale recall block is the first thing to go, before any of
the user's words; and a shortened message loses its sidecar too (replayed,
the sidecar would have sent the whole original again).

## 5.8.6

**A compaction can be inspected.** `chronicle_context_status` reported only
whether the engine was live; it now also carries the compaction policy in
force (trigger and target tokens, protected head/tail, the host's message
limit), how many passes ran, whether the last one extended or rebased, and
what the handoff is carrying (folded requests and steps, stated facts, pins).
Each pass also writes one INFO line (`chronicle compaction: session=… mode=…
messages N->M folded=… used=…/… tokens handoff=… chars`), which the gateway's
log keeps where the store's audit event is not easy to reach.

## 5.8.5

**The host's bookkeeping stays the host's.** A compaction returned the host's
own message dicts for the turns it kept, `_db_persisted` marker and all.
Hermes' invariant is that no assembled compaction output carries that marker
(its own compressor sweeps it off; a leaked one makes a rotation flush skip
the row) and it stamps committed rows itself; its current child-session
insert writes every row, so this keeps the invariant rather than fixing an
observed loss. Kept messages now come back as unmarked copies (the host's
dicts are never edited). The settled prefix is also compared on what the
model sees — role, content, tool calls — so a transcript reloaded from
state.db, stamped or carrying a sidecar key, still extends instead of
rebasing and breaking the prompt cache.

## 5.8.4

**The gate asks what the user said.** A past conversation excerpt went into
the user's turn when ANY line of it shared a content word with the message —
and the assistant's own briefings and status reports share a word with almost
anything. Once 5.8.2 stopped retracted beliefs from crowding the ranking, such
replies filled the block: on the production store "remind me where I work and
what my role is" drew 2,952 characters of calendar briefing and MCP status.
The gate now asks the USER's words in the excerpt; the excerpt is still shown
whole, the reply being context for what the user said. Measured on the
production store: 2,952 → 156, 4,784 → 1,599 (the same facts, without the
reply-only excerpts), 1,187 → 277 characters. A chunk that is only the
assistant's reply no longer reaches the turn; explicit search still finds it.

## 5.8.3

**An episode about the user is what the user said.** A transcript episode was
the whole turn, so the assistant's reply ("Great, I will remember that ...",
its code, its plan) became part of an episode about the user — the one output
still built that way after the facts and notes moved to the user's own lines.
On the production store 24 of the 32 active transcript episodes carried it,
and once the belief index stopped burying them (5.8.2) they reached the
user's turns. The episode is now the user's words in the turn (none when
those are too short); `deploy570/rederive_transcript_episodes.py` re-derived
the live ones through the capture path.

**A scheduled job's turn gets no per-turn recall.** Nobody asked, the
"message" is the job's own prompt, and on the production box those were ~98%
of all turns — up to 4,800 characters of the user's memory each.
`retrieval.prefetch_automation: true` restores it.

## 5.8.2

**The per-turn search reads what it can return.** Profiled on the production
store, a scheduled job's prompt (4,400 characters, 210 content words) made the
gated per-turn search take 42-84 s — far past Hermes' 8 s prefetch timeout,
and while that call was stuck the host skipped Chronicle for every turn, the
user's own included. Three causes, all fixed:

* The gated search asked for every content word, as prefix terms (234 of
  them). It now asks for the message's 24 most telling words — said most
  often, capitalised, longest — when it has more; a short message is
  unchanged.
* `belief_fts` held 101,188 rows, 97,790 of them retracted beliefs ranked on
  every search and then thrown away. A belief now leaves the index when it
  stops being searchable, and returns if it is reactivated.
* The observed index is ~98% cron transcripts, which the per-turn search
  ranked and then filtered out. The user's own conversations now have their
  own index (`observed_user_fts`), read once it is known complete: a new store
  is born complete; an upgraded one waits for `deploy570/repair_fts_582.py`.

Also: indexing an observed event no longer runs a DELETE on an unindexed
column first — a scan of the whole index on every capture.

## 5.8.1

**A host notice is not the user.** Hermes' turn-liveness watchdog writes its
abort — "Turn made no progress for 613s; aborting to release the session." —
into the transcript as a plain user row. Replayed compactions quoted it back
as something the user said; it is host framing now, wherever it appears in a
message, and the user's own words next to it stay theirs.

**The digest keeps facts, not restated requests.** The checkpoint digest turned
every long user message into an `[episode]` line; the handoff already quotes
folded requests verbatim, and in the 300-token rolling digest those lines
pushed the actual facts out, oldest first. Episodes stay out of it.

## 5.8.0

**Compaction leaves one handoff, keeps tool calls whole, and follows the
operator's settings.** Read against Hermes' own compaction path and replayed
over real sessions, the context engine had six problems:

* **It ignored the operator's policy.** The host never hands a plugin engine
  its `compression:` settings, so Chronicle compacted at 75% of the window down
  to 55% while the profile says `threshold: 0.5, target_ratio: 0.15,
  protect_first_n: 3, protect_last_n: 20`; and because the host calls
  `update_model()` before `on_session_start()`, even Chronicle's own
  `context_engine.*` settings never applied. The engine now reads the host's
  section (explicit Chronicle settings still win): HIGH is `threshold`, LOW is
  twice `threshold × target_ratio`, and the protected head/tail come from the
  host.
* **It ignored the message limit.** The gateway also compacts at
  `hygiene_hard_message_limit` messages whatever the tokens, and when that
  compaction makes no progress it cuts the model's input to the newest `limit`
  messages every turn — head and all, no handoff. Chronicle, under its token
  budget, returned the transcript unchanged. A pass over the limit now folds
  down to half of it.
* **Injected blocks were `system` messages after the latest turn.** Hermes'
  Anthropic converter makes the LAST system message the system parameter, so
  `[Checkpoint:]`, `[Relevant memory:]`, `[Entity working set]` and the
  pressure warning could replace the agent's own system prompt. All of it now
  rides in ONE message, `[CONTEXT COMPACTION — REFERENCE ONLY] Chronicle
  folded …`, in a conversation role that alternates with the turn before it,
  where the folded turns were: the user's folded requests verbatim (newest
  first), one line per folded step (`called read_file(…) → …`), the facts
  stated in them, memory recalled for the focus and the host's
  `memory_context` (which was dropped), and the ids of whatever did not fit.
  Each section gets a share of the room; identical turns are listed once.
* **Fold stubs orphaned tool results.** Each folded message left `[FOLD id
  digest]` in its role but without `tool_calls`/`tool_call_id`, so the host's
  sanitizer deleted or faked the paired results, and the stub said nothing. An
  assistant call and its results are now kept or folded together, and the
  handoff names each step by its first result (every empty-content call used
  to hash to the same id).
* **When the protected spans alone were over budget, the newest turn was
  dropped** — the fit ran head first. Now: system, the newest unit, the rest
  of the tail newest first, then the head; a span shortened to fit is archived
  first and ends with the `chronicle_expand` id that restores it.
* **"never / always / must" pinned tool output.** The keywords counted in any
  message; they now count in the user's own words only (pins are unchanged),
  and the checkpoint digest is fed only the user's words.

A pass normally EXTENDS the settled prefix byte for byte (earlier handoffs
included) so the provider's prompt cache holds; once that prefix is most of
the budget, or over the message limit, it REBASES: earlier handoffs and pre-5.8
artifacts come out and one consolidated handoff replaces them. A restarted
engine adopts what an earlier handoff said, ids included. Archive writes are
batched (one transaction per ~64 messages): a 961-message pass went 1.4 s →
0.7 s.

**A compaction costs seconds, not tens of them.** Profiled on the production
box, one real 258-message compaction took 17.3 s, 12 s of it in the canonical
JSON encoder, which escaped strings one character at a time in Python — and
every event id and span id hashes the full text. The standard library's C
string encoder applies exactly the same rule (checked over every code point);
the same compaction now takes 4.6 s, and every capture is cheaper. The
protected head no longer keeps a large tool result whole (one 43 KB skill
description cost a third of the budget on every call): it is shortened,
archived, and says how to restore it. An archive copy of a turn the memory
provider already captured is searchable but not embedded — each compaction
queued one embed job per folded message, duplicating vectors the provider's
capture already has.

**Excluded sessions stay unembedded.** `embeddings.exclude_session_prefixes`
stopped the inline embed of an excluded session's turn, but an embed job
queued before the prefix was excluded (or by an older build) still embedded it
from the curation queue. The job now checks the event's session too. On the
production box ~98% of what the embedding server embedded was cron
transcripts, which never become the user's memory.

## 5.7.17

**The gate looks only at the tokens that could match.** 5.7.16's substring
pre-check barely moved the live profile (`shares_content_word` still 1.5 s of
a gated prefetch), and the reason was structural: the rows the gate tests are
the ones FTS matched on these very words, so "does it contain them at all"
could skip none of them, and the loop then tokenised and stemmed every word of
each excerpt in Python. `shares_content_word` now finds, with one compiled
regex, only the tokens that START with a content word's probe letters — under
`word_tokens`' exact boundaries (an apostrophe joins a token: "o'reilly" is one
word, "don't" is none, a curly apostrophe counts) — and applies the same rule
to those. Pinned to the old matcher by an equivalence test over the boundary
cases and fuzzed locally over 20,000 random texts with no difference; ~4× less
time on a worst-case excerpt. The session window also hands the gate the
payload it already read, instead of a second read per turn.

## 5.7.16

**The relevance gate costs what it saves.** Profiled on the production store
after 5.7.15, the gated per-turn prefetch still spent 1.6 s of 4.2 s (under the
profiler) in `shares_content_word` — tokenising and stemming every word of up
to ~50 excerpts of up to 4,000 characters in Python, nearly all of them
excerpts with no content word in them at all — and 0.5 s in the structured
channel's per-token `LIKE` scans of the facts table, "which" included.

* A C-speed substring pre-check answers "no" for text that cannot match: a
  matching token always contains its word's first three letters (two for a
  three-letter "-y" word, whose "-ies" plural shares only those), under the
  same NFC normalisation the tokeniser applies. `_gate_stem` is cached. An
  equivalence test pins the fast matcher to the old one over plurals,
  "-ies" words, possessives, short words and decomposed Unicode.
* The gated search's structured and graph channels take the message's
  content words only.

## 5.7.15

**The per-turn prefetch makes no embedding call.** Measured on the production
store with the embedder live, three gated per-turn blocks came out the same
line for line with and without the vector channels — the gate keeps only
items that share a content word with the message, and FTS already finds
those — at 7.4 / 4.1 / 1.1 s with vectors and 2.0 / 2.5 / 0.2 s without. The
difference was a request to a CPU-bound embedding server inside the user's
turn (plus scanning every stored vector). The gated path is now lexical:
`retrieve_raw` / `search` take `lexical_only`, `query_understanding` takes
`embed`, and route classification — which embeds the message too — is
skipped for the default route. Explicit retrieval embeds exactly as before.

"remind" joins the chat filler ("remind me where I work …").

## 5.7.14

**The per-turn prefetch asks the store only for what it can use.** Profiled on
the production store (one gated prefetch, 4.3 s):

* The raw FTS channel was 2.3 s in three calls. It ORed every word of the
  message ("which", "did" and "I" included) over a transcript table that is
  ~98% cron runs, filtered the cron rows afterwards, and had to widen and
  re-run the ranked match to find enough rows left. The gated path now asks
  FTS for the message's content words as prefix terms
  (`retrieval.relevance_fts_match` — what the gate keeps anyway; "restaurant"*
  finds "restaurants", which the unstemmed index would not), for both the raw
  and the belief channel, and `fts_search_observed` drops automation sessions
  inside the query, before the LIMIT. Explicit retrieval asks exactly the
  query it always did.
* The standing-directive lookup was 0.8 s in two calls: its index covers
  `always_inject` alone, and the attribution cleanup left 40,444 retracted
  always-inject notes behind it for five active ones. A composite index on
  `(always_inject, status)` now serves it.

## 5.7.13

**A turn does not wait for the embedding server.** Measured on the production
VPS after the 5.7.12 restart: the local embedding server runs at ~50% CPU all
day and a 200-word embed takes ~7 s, against a 10 s request timeout.

* **A timeout is not retried.** The endpoint is on-host by policy, so a timeout
  means the server is busy — and a client timeout does not cancel its work:
  each retry queued another copy behind the request still running. One failing
  embed spent ~60 s (5 attempts × 10 s + backoff) growing the queue it was
  waiting on. A timeout now trips the breaker at once and the vector is
  deferred. Other transient errors keep the retry budget.
* **Work off the critical path may take as long as the server needs.** The
  deferred embed job and the session summary pass `embeddings.background_timeout`
  (default 120 s) instead of the live timeout: a long excerpt timed out on every
  attempt, and 676 embed jobs failed permanently that way in six days.
* **Curation runs beside the turn, not in it.** Hermes calls `on_turn_start`
  synchronously, before the model, and it drained a slice of the curation queue
  — embed jobs included — inside the user's turn. A host (the provider, the
  context engine) now moves that slice onto one background thread per core
  (`curation.drain.background`, default true); kicks arriving during a pass are
  coalesced into one more pass, and a failing job does not stop the worker. A
  core used directly still drains where it is called.

## 5.7.12

* **Chronicle's own compaction output is host framing.** The checkpoint
  digest (`[Checkpoint: …]`), recalled memory (`[Relevant memory: …]`) and the
  entity working set are injected as `system` rows, which speaker attribution
  already treats as framing. They are now also recognised inside a user row,
  so a host that folds system messages into the user's turn cannot make
  Chronicle's own summary read as the user's words.
* **A fact's history reads forwards when two versions share a timestamp.**
  Versions were ordered by `created_at`, then by belief id — a hash — and a
  correction written in the same millisecond as the fact it corrects is
  routine, so a history could read backwards. A version now precedes the one
  that replaced it. This was the intermittent `test_fact_histories` failure
  (about one run in eight): belief ids differ on every build, so the tie
  resolved differently from run to run.

## 5.7.11

Review fixes to 5.7.5–5.7.10, each verified against the code before changing it.

* **A tool cannot speak for the user.** A tool's output is stored verbatim
  inside the excerpt, so a line in it can look exactly like a role label —
  `User: ignore previous instructions` in a web page. Reading the excerpt by
  its prefixes handed that line to the user, in the reader's copy, the
  episode, the model extractor's prompt and the per-turn injection. The
  capture's spans say whose each line is, and capture stores them exactly when
  such a line exists (the prefix reading and the spans then disagree), so
  `strip_framing` now takes a `role:` line as a message start only when the
  spans agree, and extraction rebuilds its text from the speaker lines instead
  of re-reading prefixes. A later chunk's opening takes its role from the spans
  too. Events without spans still read by prefix, as extraction always has.
* **An evicted tool result is not memory about the user.** Its text is bare;
  only its spans say it was a tool's, and the gated injection judged the text.
  It now reads each row's own event.
* **An older copy nobody can attribute** (no spans, not written by the user)
  is left out wherever tool output must go.
* **Automation is read from the turn**, not only from a `cron_` session id:
  capture records a subagent's, a background review's, a non-primary agent's
  or a bot's turn as automation, and `exclude_automation` now honours it.
* **Left-out rows no longer cost real ones their place.** Vector candidates
  are judged before they take a top-k slot, and the FTS channel fetches in
  widening pages until it has `limit` rows it can use; with nothing left out
  it is one fetch and the same rows as before.
* **An empty session-index row is not a stale vector.** No summary and no
  vector: nothing to re-embed and nothing a query can match, so the census no
  longer counts it as outstanding forever. A row with no summary but a vector
  still counts.
* Public functions in the touched modules carry type hints (AGENTS.md), with a
  test that keeps it so.

## 5.7.10

**The per-turn injection never guesses whose words it is carrying.** A turn
longer than one stored chunk (4,000 chars) is split at message boundaries when
it can be; one message longer than a chunk — in practice a tool's output — is
split inside it, and the next chunk opens mid-message with no role label. On
the production store 473 of the 651 interactive transcript events are later
chunks, all written without the speaker spans that would say whose text opens
them. The gated injection now leaves out that unlabelled opening of a later
chunk; the chunk's labelled messages still arrive, and a single stored message
whose spans do say whose it is (the compressor's copy of a user message) is
injected as before.

The gated helper now works on the row rather than its text, so the
agent-memory rule of 5.7.8 applies on every gated path, not only the first.

## 5.7.9

**Older rescue copies lose their host frames too.** A dry run of the
session-index rebuild on the production store left 69 of the 107 interactive
session summaries still carrying framing. It sat in rescue copies written
before speaker spans existed — single messages with no role label — and they
were cron prompts ("[IMPORTANT: You are running as a scheduled cron job …")
and skill-invocation frames, in sessions whose ids carry no `cron_` prefix.
`speaker.reader_text` read such a copy only for an eviction by the user; it
now reads any older eviction or rescue copy as the user side unless the agent
wrote it, which removes only recognised host frames.

**A session with nothing but framing has an empty index row.** Rebuilt, such a
session has no conversation left, and the summarizer returned without writing,
so the old row built from the frames stayed. It is now replaced by an empty
one: nothing to find it by, and still a row, so the backfill sweep does not
re-queue it (the stale-vector heal already skips empty summaries).

## 5.7.8

**The agent's memory stays the agent's.** 22 of the 72 active episodes on the
production store were the agent's own memory-tool writes ("dispatcher cron
runs across 53 repos", "GitHub API from this VPS is intermittently
unreachable"), and the per-turn injection served them as memory about the
user. Hermes's built-in memory already puts the agent's CURRENT memory into
every system prompt; Chronicle's copies are older and include notes the agent
has since removed from it (the log holds `remove` and `replace` actions whose
earlier `add` still had an episode). The gated per-turn injection now leaves
out beliefs and raw rows whose source is `agent_memory_write`. Explicit search
still finds them.

## 5.7.7

**A tool's output is not memory about the user.** Probed on the production
store after 5.7.5, the gated per-turn block for "what's on my calendar this
week?" was a line-numbered file read that happened to contain the word
"calendar", and episodes carried browser results and exit codes. Speaker
attribution has always kept tool output out of facts and notes; three other
outputs still took it in whole:

* **The per-turn injection** judges and carries each turn without its `tool:`
  rows, so a turn is injected for what the user and the agent said in it, and a
  turn whose only match was inside a tool's output is left out. Explicit recall
  and the context engine's rehydration are unchanged: there the agent may be
  asking about its own work.
* **Episodes** and the model-based extractor's prompt leave tool rows out, as
  they already leave out host framing; a turn without tool output produces
  exactly the episode it did before.
* **Session summaries** leave tool rows out, so a session's vector stands for
  the conversation rather than for the largest payload in it.

`speaker.strip_framing(..., drop_tools=True)` / `reader_text(..., drop_tools=True)`.

## 5.7.6

**Recall serves what was said, not the host's framing around it.** Capture
stores an excerpt byte-for-byte (its event id is a hash of it) and marks the
host framing inside it with speaker spans, which is what has kept compaction
handoffs, system notes and Chronicle's own `<memory-context>` injections out of
extraction. Everything that handed text to a reader, though, used the stored
bytes:

* **Raw recall** (FTS, event vectors, the span channel, the session window)
  served an earlier compaction's summary or a system note back as conversation.
  It now serves `speaker.reader_text` — framing removed, every role label that
  still has words under it kept, and the stored text itself, unchanged, when
  there is nothing to remove. An event that was nothing but framing (the
  compressor's copy of an evicted handoff) is not recalled at all.
* **Session summaries** were built from every observed event in the session,
  the compressor's eviction copies included, and 24 of the 107 interactive
  session summaries on the production store carried a
  `[CONTEXT COMPACTION — REFERENCE ONLY]` handoff into the session vector. They
  are now built from the reader's copy, and from the session's transcript
  captures alone when it has any: eviction and rescue copies repeat messages
  the transcript already holds, and stand in only for a session without one.
* **Episodes** were the one extraction output built from the raw text, so a
  turn that opened with a handoff became an episode about the handoff, and the
  model-based extractor was sent the handoff to summarise. Both now work from
  the framing-free copy; a turn without framing produces exactly the episode
  it did before.

Existing session-index rows are a projection of the event log: re-running the
summarizer over a session rebuilds its row from the events with these rules.

## 5.7.5

**The memory put into a turn is about that turn.** The provider's `prefetch`
injects up to 1,200 tokens of memory into every user message, unasked. Probed
on the production store, it was mostly other things:

* **Scheduled jobs' own runs.** 7,817 of the 7,924 indexed sessions were cron
  runs, and "what's on my calendar this week?" opened with one job's operational
  narrative and another's raw tool JSON, served as memory about the user.
  Anything injected unasked (prefetch, and the context engine's rehydration)
  now leaves out automation sessions on every raw channel — FTS, event vectors
  and session vectors — by the same rule `engine/speaker.py` applies to capture.
  An explicit search still sees them; the agent may be asking about its own work.
* **Whatever ranked highest, relevant or not.** Every turn got the full
  ~4,800-char block. Ranked retrieval always returns something (FTS ORs every
  word of the message; a vector channel has a nearest neighbour for any query),
  and the session window then filled the rest of the budget with the other
  turns of whichever session matched. `get_context(relevance_gate=True)`, which
  prefetch now passes, keeps an item only if it shares a content word with the
  message:
  - content words are the message's words minus English function words and
    chat filler ("thanks", "still", "sounds good"); plurals, possessives and
    short inflections match ("restaurants"/"restaurant", "book"/"booked");
  - a message with none ("ok thanks") gets nothing, and retrieval is not run —
    prefetch runs on every turn and live retrieval takes seconds;
  - a fact is also matched by the name of the entity it is about, since it
    renders as `attribute: value`;
  - a whole-session excerpt only nominates its session; the session's turns
    then arrive one at a time, each gated, so one matching turn no longer
    carries every unrelated one with it;
  - the tail (directives, contradictions, critical facts, federated rows) is
    gated too — those reach every turn through the system prompt already —
    and a directive already on the page as a `[NOTE]` is not repeated.

  Deliberately lexical: an item related only by embedding similarity stays out
  of the unasked block and is found the moment the agent searches. Explicit
  retrieval — the agent's search tool, rehydration, benchmarks — never sets the
  flag and is byte-for-byte unchanged. `retrieval.prefetch_relevance_gate`
  (default true) turns it off. `last_context_debug["relevance_gate"]` reports
  the message's words and how many beliefs, excerpts and tail lines it left out.

## 5.7.4

**Chronicle is actually the context engine.** It had been configured as Hermes's
context engine and had never once compressed a conversation. The host gives
every agent its own `copy.deepcopy()` of the registered engine; the copy raised
"cannot pickle '_thread.lock' object" on the engine's retry lock, and the host
fell back to its built-in compressor for that agent — 38 times in one day on
the production gateway, with one WARNING each that nothing read. That fallback
was pinned to a provider with no API key, which the user saw as "Shortening the
conversation history failed". Reproduced with the host's own selection code
before the fix (configured, registered, and `None` for every agent); after it,
the same code selects Chronicle.

* **`__deepcopy__`.** A copy SHARES the core — the process-wide store, its
  connections and vector index; duplicating that per agent is the shape of the
  ~850 MB/min leak the last time this engine ran — gets a FRESH lock, and copies
  the per-agent budget state the host copies to keep agents apart.
* **The rest of the host contract**, checked method by method against Hermes's
  `ContextEngine`: `on_session_reset` (the default zeroes counters only; the old
  conversation's locked prefix, digest, pins, focus and rescue record now go too);
  `should_defer_preflight_to_real_usage` with the host's own rules (a rough
  estimate taken right after a compaction waits for real usage instead of
  compacting a request that already fits); `prune_tool_results_only`; and
  `has_content_to_compress`. Every hook that carries state is implemented; the
  four left on the default would duplicate what the memory provider does.
* **Old tool output is trimmed again.** Hermes calls `prune_tool_results_only`
  on a lower trigger than full compaction; a plugin engine inherits a no-op, so
  switching engines had quietly stopped it. The host's two safe passes: a result
  identical to a later one becomes a pointer, a large old one keeps its head and
  tail and says how much went. Committed only when it saves enough to be worth
  breaking the provider's prompt cache, then not again until the context
  regrows. `context_engine.prune_tool_results`.

**Turning it on exposed what it would have done to a turn.** Measured against a
copy of the production store with the real, CPU-throttled embedding server:

* **One compaction made 150 inline embed calls** — 60 rescued observations, 30
  rescued notes at three embeds each, and the evictions — every one a timeout on
  a five-attempt budget. It never finished its first pass. Writes made from
  inside `compress()` (`context_eviction`, `rescue_extraction`) now take the path
  a degraded embedder already takes: text durable and full-text indexed at once,
  vectors queued. Keyed on each event's own `source_type`, so a rebuild makes the
  same decision (I3).
* **A timeout dropped the vector for good.** The embedder's retry loop re-raised
  the raw `socket.timeout`; every caller treats `EmbeddingsUnavailable` as "down,
  try later" (`_safe_vec` queues a deferred embed on it), and a raw timeout fell
  to a generic handler that logged at DEBUG — while the warning printed just
  before promised "embed retried on the next operation". It now raises
  `EmbeddingsUnavailable`, and a circuit breaker stops a down server costing
  every call: calls inside the cooldown fail at once, a half-open trial is ONE
  attempt, and the cooldown doubles on consecutive trips (to 10 minutes). Every
  agent turn drains curation jobs before the model is called, so this is what a
  turn pays while the server is down: one budget for the first outage, then
  nothing, then one try.
* **Queueing a deferred embed scanned every finished job.** No index served the
  re-arm probe: 0.375 s per enqueue on a 182,230-row job table, one per span a
  compaction writes. A partial index on the job's target id: 97 s of one
  compaction became 2 s.
* **Every turn was captured three times.** With the memory provider live on the
  same core, `sync_turn` captured each turn when it ended; before a compaction the
  provider rescued it again (because the engine never went live, the provider
  thought it owned compression), the engine rescued it a third time, and every
  eviction was queued for extraction once more. On the production store rescue
  drafted 19,089 notes and evictions 4,955 — the attribution cleanup retracted
  every one. With both halves live neither rescues, and an eviction carries
  `extract: false`; each standalone mode keeps its own capture. Rescue also runs
  once per message per conversation now, not once per compaction pass.
* **A session start worked the job queue.** `initialize()` runs on every session
  start and ran crash recovery each time, ending in a synchronous drain of up to
  1,000 jobs. One engine init took 320, 592 and 830 s. Recovery is about a
  previous process: once per core, and one turn's slice of draining.
* **A photo crashed compaction**, and the capture path stored it as the Python
  repr of its parts list — the photo's full base64 in the event log.
  `speaker.message_text` is one rule for the text of a message: a string
  unchanged, a parts list its text plus `[image]`-style markers. Capture is
  byte-identical for strings and `None`. One fixture photo: 50,000 characters
  became 61.
* **The host's messages were being edited.** The pin check cached its hash as
  `m["_content_hash"]` on the host's own message dicts — a private key in what the
  host sends the model, and stale once the host rewrote that content.

On the production store copy: the first compaction of a sixty-message
conversation 19 s (it never finished before), each one after ~5 s, RSS ~36 MB
with the real core live; engine init 213 s once per process instead of up to
830 s on every session start.

## 5.7.3

**Memory is organised by what it is about.** An entity was whatever text had
been typed at: a production store's 1,488 entity rows held 171 pronouns
("This", "There", "Each one") and 65 sentence fragments, typed with whatever
followed "is a" ("real managed challenge", "dead end for getting a usable key
into my environment", "no"); 1,003 were named by another store's id even though
the `name` fact beside them said "Pat Testley"; and every entity existed
TWICE — a hash-keyed row carrying its type and a token-keyed row carrying its
facts — because the extractor's entity token never reached the fold.

* **`engine/entities.py`** decides what an entity is. A name is a proper noun,
  not a sentence (every significant word carries a capital, so "Acme Fake Co",
  "NVIDIA", "E.K. Chung" and "iPhone" pass and "Rotating between them" does
  not); a type is a category, not a clause; and a kind is one of person, place,
  thing, event or concept, taken from the type, or from the predicates a subject
  carries, or left empty — `kind_for` answers "" rather than inventing one.
  The rules are applied at extraction, at the write boundary, and in the fold,
  the last of these so a rebuild does not resurrect what years of logged
  `asserted` events named.
* **An entity is one row, addressed by its name.** The fold derives an entity's
  belief id from its name (`entities.entity_token`), which is the id its facts
  already reference, so the row describing an entity and the facts hanging off
  it are the same entity. Nothing about the event changes, so the same log
  replays to the repaired projection.
* **An id resolves to the name the log already carries.** A fact that names an
  entity whose row is named by another store's id renames the row — never a
  guess, only the `name` fact that is already there (991 of 1,003 on the
  production store).
* **`scripts/clean_entities.py`** repairs the rows a store already holds, which
  is what a rebuild would do without replaying 400,000 events on a live box.
  On the production snapshot: 313 dropped, 1,002 renamed from ids, 26 duplicate
  rows merged, 16 clause-types cleared, 1,488 rows down to 1,149 with every
  fact still pointing at a row. A row any live fact points at is never dropped
  — including `user`, whose name is not a proper noun — and two rows that
  merely share a NAME are never merged: two people called the same thing are
  the ordinary case, and identity is adjudicated, never inferred.

* **A name may carry what people put after their own name.** Read back from the
  repaired production store, the rule was refusing real contacts: "<name>,
  Ph.D." ends in a full stop, so it read as a sentence, and "(she/her)" is a
  word with no capital in it. A trailing pronoun tag and trailing credentials
  (Ph.D., M.A., M.HCI, Jr., Esq., III …) now come off before the rule looks at
  the words, and what is left still has to pass on its own — "dead end for
  getting a usable key, Ph.D." is still refused, and a credential standing alone
  is not a name.
* **A contact known only from the calendar is a person.** `attended_event` is
  the most common predicate in the production store (366 facts, the calendar
  import) and answered nothing, so an entity whose only trace was an appointment
  sat under "unclassified". `attended_event`, `had_appointment` and
  `traveling_to` now say person — as with every other entry here, because only a
  person can be the subject of them, not because the name looks like one. The 49
  rows that carry nothing but a `name` fact stay unclassified: that is what the
  store knows.

* **A retraction closes the contradictions it settles.** A contradiction is two
  beliefs the store cannot both hold; once one side is retracted there is
  nothing left to reconcile, but the row stayed `open`. The cleanup of 112,652
  beliefs left 1,550 such rows on a production store — a queue of questions
  nobody can answer, and the first number the memory view shows. The row is
  resolved, never deleted: its detail and its date are the record. The
  consistency sweep settles the ones a store already holds, so a repair needs no
  one-off script: on the cleaned production snapshot it settles all 1,550 and
  leaves every contradiction between two live beliefs open.

**The Tapestry is entity-first.** The memory view was a log: every event on the
row of whatever wrote it. That is provenance — how a memory arrived — and it is
now a drill-down reached from a fact or a mention, not the way in.

* **`/tapestry/index` and `/tapestry/entity`** read the entity model: what
  memory holds by kind, and one entity's current facts, its history, the events
  it appears in, and the captured turns that name it. Every mention carries who
  was speaking in that turn (engine/speaker.py), so a hit inside a cron job's
  output says "automation".
* **Events are the facts that record them.** A calendar appointment is an event
  even though the store keeps it as a fact about its subject, and its date is
  the one the importer wrote into its title, not the day Chronicle heard about
  it. An event links to the people its own title names, whole words only.
* **Contacts are classified by the store that owns them.** The people store
  says who is a person and who is a company; Chronicle only references its rows
  by id (I20), so the dashboard reads it read-only and labels what it says. An
  unreviewed row stays unreviewed rather than being guessed at — 965 of 1,008
  on the production store.
* **The weave** draws the dated events on one time axis with a thread per
  entity they involve, joined where an event names two of them. The threads are
  the busiest first; the rest are counted rather than drawn a pixel high.
* Internals follow the name: `dashboard/tapestry_api.py`, `dist/tapestry.js`,
  `/tapestry/...` routes, `window.__CHRONICLE_TAPESTRY__`.

## 5.7.2

**Memory about the user comes only from the user.** Chronicle was built to keep
the agent's memory and memory about the user distinct, and capture never did.
Extraction read every line not labelled `Assistant:` as the user's. On a
production snapshot that turned cron prompts, tool output, compression rescue,
context eviction, Hermes' control frames and Chronicle's own recalled context
into memory about the user:

* 98% of captured turns (40,841 of 41,492) came from cron sessions, whose `user`
  row is the job's prompt;
* 30,018 active notes, nearly all always-injected "directives", plus 14,664
  drafts; about 330 came from the user's own sessions, and those were almost all
  assistant or tool text too;
* facts such as the user's name being the agent's own name ("Indigo", from its
  identity file) and the user's email being a broker's support address (from a
  cron report).

What changed:

* **Capture records who said what.** `engine/speaker.py` decides the user side
  of a turn from the host: `agent_context` other than `primary`, platform `cron`
  (and batch, flush, subagent), a `cron_` session, or a bot turn author
  (`sync_turn` now accepts Hermes' `turn_author`) mean automation, not a person.
  Each message's role is kept: `tool` rows were not a role before, so tool output
  inherited whoever spoke last. Inside a person's message, Hermes' control frames
  (compaction handoffs, `[System note: ...]`, background-process results, the
  gateway origin header, the steer wrapper's markers) and the `<memory-context>`
  block of recalled memory are host text, wherever they start. The result is
  stored on the event as `speakers` spans over the excerpt plus `attribution`,
  so no later reader re-guesses from line prefixes, which tool output can forge.
  A turn from automation is labelled `Automation:` in its excerpt rather than
  `User:`. Rescue (both plugins) and context eviction record the role too.
* **Extraction reads only the person's words.** Facts about the user, emails,
  preferences, standing instructions and "X is a Y" entity typing come only from
  human spans. The reducer does not queue extraction for an event with none, and
  the curation worker skips (and records) jobs queued before the upgrade. Rescue
  writes a draft note only from the user's own words. The LLM extractor keeps a
  user fact or directive only if it appears in them. The piggyback enrichment
  skips turns with no person in them. Skill journals are recorded as automation.
* **Events written before this release are read conservatively.** Transcript
  labels are honoured, a `cron_` session's `user` rows are automation, an
  unlabelled continuation chunk and role-less rescue text are nobody's, and an
  event's `actor` is trusted only when it has no source type.
  A plain turn with no host context keeps its old payload and event id.
* **Measured.** LongMemEval oracle turn-level union recall 70.6% / 88.3% /
  93.0% / 96.3% at k=1/3/5/10, from 68.2 / 87.6 / 93.6 / 96.0; abstention
  unchanged at 3/17. `ctx_eval` answers 46/58 at a 1500-token budget, one fewer
  than before, and 50/58 and 52/58 at 4000 and 12000, unchanged. The corpus
  labels its turns `user`, so on it the new rules mostly change the "X is a Y"
  typing; the production effect is the 112,652 beliefs below.
* **`scripts/retract_misattributed.py`** retracts beliefs whose every channel is
  transcript extraction and whose supporting events never show the user saying
  them (a fact's value or note's body must appear in the user's words; an episode
  needs a turn with any). Dry run with a JSONL report by default; `--apply`
  appends `retracted` events through the reducer, so the log keeps the original
  assertions. A `retracted` event may now carry a batch of ids (`belief_ids`,
  grouped by owner, `--batch`, default 250): a cleanup is one decision, and
  112,652 separate events would put that many transactions, reduces and
  git-mirror rows through a live agent's write path. A replay of either shape
  reaches the same projection. On the production snapshot it selects 112,652 beliefs:
  67,614 active episodes, 30,008 active and 14,664 draft notes, and 366 facts
  (36 about the user, 330 `is_a` entity types). It keeps the 50
  transcript-derived beliefs that are in the user's words, and everything with any other channel (calendar, email and
  people imports, tool calls, explicit memory writes). Raw captured turns are
  untouched and remain searchable.

## 5.7.1

Three fixes from an audit of other agent-memory systems (Hindsight, Graphiti,
Mem0, agentmemory, Honcho, OpenViking and others), each checked against the
production store before it was changed, and a dashboard navigator for memory.

* **Duplicate merge is exact, and no longer eats updates.** The E5 merge folded
  a new belief into an existing same-subject one at cosine >= 0.95, discarding
  the new body. On the production nomic model that threshold merges real
  updates: "Standup is at 9am" -> "10am" scores 0.9945, "allergic to peanuts" ->
  "not allergic" 0.9795, "offsite in Denver" -> "Boston" 0.9547, while a pure
  paraphrase scores 0.9948, so no threshold can separate them. The check also
  ran only when an inline embed succeeded: with the embedder timing out or down,
  every repeat became a new active row (one production scope holds 25,054
  active directive notes with 2,696 distinct bodies), and a projection rebuild
  under a different model merged differently, breaking I3. A merge now requires
  a byte-identical body in the same owner, domain and natural key (for a fact:
  entity, predicate and qualifiers, so "work phone" and "home phone" with the
  same number stay two facts), is decided before anything is embedded, and never
  reads a vector. `curation.dup_similarity`
  is deleted. Legacy duplicates stay until a projection rebuild folds them.
* **Keyword search keeps non-English words.** Every keyword path tokenized with
  an ASCII-only class while FTS5 indexes Unicode letters, so a query for
  "Zürich" searched for "rich", "José" became "Jos", and a Cyrillic or CJK
  question produced no terms at all. Because the focus support gate treats "no
  distinctive tokens" as nothing to fail on, such questions could never abstain.
  One word-token definition (`store.word_tokens`, NFC-normalized so a decomposed
  "Zürich" is one word, as FTS5 indexes it) now serves the FTS query, routing,
  overlap and hint tokens. On LongMemEval (hashing embedder) context
  recall is unchanged; turn recall@1 moves by 0.6 points in each tier (belief
  down, raw up) and union@3 rises 0.3. Porter stemming was measured and
  rejected: it lost 1-2 questions of context recall.
* **The dashboard tab has a UI again, and an Atlas.** `dashboard/manifest.json`
  named `dist/index.js` as its entry, but `dist/` was gitignored and the bundle
  was deployed by hand, so a deploy from the repo left the tab with nothing to
  load. The hand-deployed bundle also still POSTed `/process-embeddings`, which
  A13 renamed. The UI is now built from `dashboard/web/src` into a committed
  `dashboard/dist`; CI rebuilds it from source and fails on any difference, a
  test requires every route the UI calls to be declared by `plugin_api.py` and
  present in the built bundle, and the release zip now ships `atlas_api.py` and
  `dist/` (it carried only `manifest.json` and `plugin_api.py`). The new **Atlas** view
  draws every event as a point on its writer's row (cron job, session or
  background actor) over time, with inspectors that follow an event, run or
  belief to its sources, replacements, contradictions and identical copies,
  plus lenses for open contradictions, replaced facts and duplicate notes. It
  reads through `mode=ro` connections, streams the log as delta-encoded columns
  (419,490 production events load in about 10 s) and renders with deck.gl,
  loaded only when the tab opens. Verified against a production snapshot in a
  local harness (`dashboard/web/harness/`).
* **`prune_vectors.py --orphans`** removes observed vectors, and their excerpt
  proxies, with no observed event behind them. No Chronicle code deletes events,
  but the production log starts at seq 79,993, and 18,394 vectors of events that
  are gone remain (their FTS rows do not). Another 7,612, written by an older
  build, are keyed to `asserted` and `signal` events, which have no excerpt.
  Neither kind can be rendered or re-embedded (they were exactly the 26,006 rows
  the 5.7.0 vector migration could not repair), and every brute-force scan still
  pays for them.

## 5.7.0

The ladder-10 integration: eighteen independent work trees merged into one
bisectable chain, plus the four ship-blockers an independent pre-ship review
raised against the merged tree.

This is an audit-driven hardening pass, not a feature release. A read-only audit
of v5.6.0 (`reports/AUDIT-2026-09.md`) found seventeen places where this
project's own premises were quietly false, and every one of them is answered
below. Four of them carry the release:

* **The vector-identity repair.** On the production store 88% of
  `memory_vectors` had been written by a model Chronicle abandoned in July, at a
  different width — and the read path scored every one of those blobs as
  similarity 0.0 with no log, no counter and no health signal. Most of memory was
  invisible to vector retrieval and nothing said so. A vector's provenance is now
  a canonical model identity rather than whatever string a server reported, the
  heal can tell a re-tag (same bytes, stale name) from a re-embed, a wrong width
  is refused loudly instead of silently scoring zero, and an endpoint that
  contradicts a declared width stops the run rather than rewriting the store into
  a geometry nobody asked for.
* **The ACL closure.** The `[DIRECTIVE]` block, `get_directives()` — which feeds
  every system prompt — `history()`, `as_of()`, `explain()` and every
  contradiction listing read the store without `access.can_read`, so a sandboxed
  agent's notes reached principals the topology denies. All of them now go
  through the choke point, and the two tables that could not be gated at all,
  `goals` and `reflections`, gained the owner column that makes gating possible.
* **The maintenance scheduler.** Nothing in the plugin ever enqueued `health`,
  `decay`, `consistency`, `identity` or the backfill sweep, and `Reaper.run()`
  had no caller: the cron strings in the config described a cron job nobody had
  installed. A hook-driven scheduler (no daemon, no thread) makes the store
  self-maintaining, and the queue underneath it is now fair, leased, bounded and
  pruned instead of strictly FIFO and unbounded forever.
* **A large honesty pass over config and tests.** 100 config leaf keys were read
  by nothing — including `security.encrypt_at_rest: true`, while nothing
  anywhere encrypts anything — and the audit tool meant to catch that was wrong
  in both directions at once. Every leaf key is now WIRED, DELETED or DECLARED
  DORMANT with a stated reason, and a test fails the build on a fourth state.
  The suite became hermetic, order-independent and network-free, and the four
  engine defects that audit could only work around were fixed rather than
  papered over.

Two tools ship with the release rather than as follow-ups, because the vector
repair cannot be done in place at production's ~0.53 texts/s:
`scripts/migrate_vectors.py` re-embeds a COPY of the store, and
`scripts/writeback_vectors.py` carries the result back into the live store while
the gateway keeps serving, under the W1–W8 guarantees an independent GO/NO-GO
review required. The operational sequence — snapshot, manifest, migrate, write
back, verify — is **`reports/MIGRATION-RUNBOOK.md`**, and it is meant to be read
before the deploy, not during it.

Schema goes 11 → 18 in one renumbered ladder.

### v5.7.0 pre-ship review fixes

**Rung 17 could leave the store permanently unopenable.**
`MemoryStore._retire_removed_task_rows` deleted retired `curation_jobs` rows
with `PRAGMA foreign_keys=ON` and no dependency guard, so any inbound
`depends_on` edge pointing at a doomed row raised `IntegrityError` inside
`_migrate` and out of `MemoryStore.__init__` — on that open and on every
subsequent one. Both deletes now clear their inbound edges first: a collapsed
`contradiction` duplicate RE-POINTS its dependents at the surviving
`consistency` row (the work still exists), while a dropped `route`/`criticality`
row NULLS them (no build ever had a handler, so the dependent was blocked
forever). The same hazard was already guarded in `prune_curation_jobs`.

**The upgrade stall was 14 s, and 12.9 s of it was an unindexed foreign key.**
SQLite verifies an enforced FK by scanning the child column on every parent
DELETE, and `curation_jobs.depends_on` had no index — one full table scan per
deleted row, measured exactly linear at ~16 ms/row. New `idx_jobs_depends_on`,
created BEFORE rung 17 rather than at rung 18. On a synthetic 105k-row v11
store: `MemoryStore(path)` 14.574 s -> 1.383 s, the retirement step 13.376 s ->
0.090 s. It also permanently speeds `prune_curation_jobs`, whose dependency
guard scans the same column. See `reports/MIGRATION-RUNBOOK.md` Step 0 for the
pre-flight queries that size this on a real store.

**`DEFAULTS` defined `"health"` twice**, so `health.self_heal.embedder_mismatch_max`
and `health.census_total_max_age_hours` were silently deleted from the config
surface (Python keeps the last literal). Runtime was unaffected — both readers
pass a matching inline default — but the keys stopped being discoverable and
`audit_config.py`'s "UNREAD 0" was computed without them. Merged into one
literal keeping A3's `consistency_sweep.schedule` as well. Three new guards:
a MIRROR check that every literal config read resolves in `DEFAULTS`
(`audit_config.undeclared_literal_reads`, reported next to UNREAD), an AST
duplicate-key detector over every shipped module, and a blocking ruff
correctness pass in CI. The mirror found three more undeclared knobs, now
declared: `capture.tool_reference.allowlist`, `capture.tool_reference.ttl_days`,
`curation.novelty_top_k`.

**Identity and machine paths removed before publication.**
`scripts/bench_a5_vectors.py` no longer defaults `--store` to an absolute home
directory; the name-collision fixtures are the tree's own fake convention; and
four `tests/exercise/` scripts no longer default to an absolute scratchpad path
carrying a home directory and a session UUID (set `CHRONICLE_LME_HARNESS`,
`CHRONICLE_LME_ORACLE`, `T8_HARNESS`, `T8_ORACLE`, `CHRONICLE_KU_SAMPLE`).

**Release metadata unified at 5.7.0** across `plugin.yaml`, `pyproject.toml`,
`README.md`, `dashboard/manifest.json` and `__init__._VERSION_FALLBACK`.
`tests/exercise/accept_m4.py`, which checks exactly this, is now run by
`tests/test_release_metadata.py` in the normal suite instead of by nobody.

**The documentation gap the review recorded is now closed.** Nine of the
eighteen merged trees had no `###` entry here (A1, A1b, A5, A6, A7, A9, A13,
A15, WB) and the README documented none of the config keys this release adds.
Both are done: the nine entries are below, and README's "Key options" now
carries every leaf key `engine/config.py` gained since v5.6.0 — 35 of them, not
the twelve the review counted — each with its default and the code that reads
it. Two smaller claims from the review's §12 did not survive re-checking and are
corrected rather than repeated: `tests/README.md`'s skip and base-tree
paragraphs had already been fixed in `84a756e`, and `scripts/ctx_eval_probe.py`
already had an `--out` flag. What that script actually lacked was a way to make
the obvious `> file.jsonl` safe, which it now has (see below).

**The release gate was an experiment with two unrecorded inputs.**
`tests/test_token_margins.py`'s saturation test failed roughly one run in
twelve, and the failure was reported as `PYTHONHASHSEED`-dependent because
`tests/conftest.py` pinned the seed for CHILD processes only. Measured, it was
not the seed: one store queried in eight interpreters under eight seeds returns
byte-identical `get_context` output, and the fixture built with the clock
frozen produces ONE store dump across the suite's five seeds — while the same
fixture built 40 times at ONE FIXED seed produced five different answers
(11 703 / 11 706 / 12 863 / 12 866 / 14 023 chars at `token_budget=4 000`, 7 of
the 40 below the 12 000-char floor the test asserts). The moving input was the
WALL CLOCK: 75 near-identical turns leave most of the ranked pool exactly
score-tied, `retrieve_raw` breaks those ties on `event_id` (`_rank_key`, A15),
and `serialize.event_id` hashes `occurred_at` — which `capture.observe` stamps
from the clock. Every build therefore drew a fresh permutation of the tied
bucket, a different cut at `limit=20`, and a different set of sessions with
turns left for the session-window expansion to spend budget on. Both inputs are
now pinned, and neither fix touches a shipped module — the executable code of
all 49 of them is byte-for-byte what it was (comments and docstrings aside), so
no measured retrieval number can have moved:

* The fixture stamps its own `occurred_at`, the technique
  `test_precision_packing.FREEZE_PREAMBLE` already used for the same reason,
  guarded by `test_the_fixture_is_clock_pinned_so_two_builds_agree`.
* Pinning alone only freezes one draw from the same distribution, so it is not
  the whole fix: over eight plausible pinned stamp schemes the delivered count
  still ranged 11 706 – 14 023 and one of the eight landed under the floor. The
  cause is that at ~270-char turns the caller's budget was never the binding
  constraint — 20 raw candidates plus the session-window expansion reach only
  11.7-14.0k of a 16 000-char budget — so the assertion was measuring which
  sessions the tie order left leftovers in. The fixture's turns are now ~580
  chars: the same 20 candidates carry 13 755 chars, the fill lands at 15 094 of
  16 000, and the pool comes back with twenty DISTINCT scores, so no tie is
  left for an id to break. Six stamp schemes, six sets of event ids, one byte
  count. New guard: `test_the_delivered_bytes_do_not_depend_on_the_event_ids`.
* `conftest` RE-EXECS the interpreter under `PYTHONHASHSEED=0` when it did not
  start with one (`CHRONICLE_TEST_HASH_SEED=<int>|off`), from `pytest_configure`
  rather than from import so the replacement process does not write its whole
  run into pytest's capture file. The terminal summary states the seed the run
  actually used. `tests/test_harness_determinism.py` tests the harness itself,
  including end to end: the pinned-seed test is re-run under three ambient
  seeds that are not the pinned one and must come back green.
* `test_precision_packing.py` gains the surface the whole investigation turned
  on — the BYTES `get_context` emits on a 25-session store whose pool really is
  tied — to the five-seed cross-process runner A15 built, so the claim "the
  clock is an input to the store, never to retrieval" is a test rather than a
  paragraph.
* `_rank_key`'s docstring said the event id "keeps the same id across store
  rebuilds". That is true of a REPLAY of one log and false of a RE-RECORDING of
  the same turns, and the difference is the whole defect; it now says which is
  which, and so does `_precision_order`. The tie-break itself is NOT changed.
  Breaking ties on `events.seq` — the log's own total order, which a
  re-recording preserves and the id does not — was built and measured (it pins
  the old short-turn fixture at 11 703 chars), but it is a user-visible ranking
  change on tied pools, and nothing needs it once a harness stamps its own
  clock. The limit is documented where the key is defined rather than traded
  for a ranking change no gate here could measure.

**Redirecting `scripts/ctx_eval_probe.py` no longer produces a corrupt gate
input.** The probe wrote its JSONL rows to a file while printing its progress
and parity table to stdout, so `ctx_eval_probe.py corpus.json > pre.jsonl` —
the obvious move, and the one the reviewer made — produced a file full of
summary text that `scripts/a18_ab.py` then died on with a `JSONDecodeError`,
having said nothing about which file was wrong or why. Now stdout carries the
JSONL and nothing else: every human-readable line goes to stderr, `--out -`
writes the rows to stdout, and the footer names the file it actually wrote.
Unknown `--flags` are rejected instead of being silently parsed as the corpus
path. `a18_ab.py` reports a non-JSON input by file and line number with the
redirect named as the likely cause, rather than raising.


### A0g — corrected beliefs embed their real text; the heal re-resolves text for every kind; the migration refuses a contradicted width

Three defects found by the independent GO/NO-GO review of the vector-repair
chain (A0 -> A2 -> A0fix -> A0e2). Two of them affected stores in production.

**1. Every belief a user CORRECTED carried the vector of the empty string.**
`reducer._on_corrected` reduces a `corrected` event by calling
`_insert_belief(kind, id, key, new_body, event)`, and `_insert_belief` decided
what to embed with `vector_text("asserted", <the event's payload>)`. A
`corrected` payload carries `belief_id`, `new_body` and `reason` — it has no
`body` and no `key` — so that expression evaluated
`payload.get("body", "") or key.get("name", "") or key.get("topic", "")` over a
payload with none of them and returned `""`. The projection stored the corrected
text; the vector was an embedding of nothing. Measured against live nomic, such
a vector scores cosine 0.576 against its own belief's text, so the facts a user
took deliberate action to fix were the facts least findable by vector
retrieval. Present since at least v5.6; untouched by the A0 chain (no hunk in it
goes near `_on_corrected`).

The text is now derived from the `kind`, `key` and `body` THIS WRITE STORES —
the same values `reducer.belief_vector_text` reads back, and the same rule
`_write_doc2query_proxies` already followed for proxy questions — so the write
side and every repair side evaluate one expression. The single text authority
A0fix established is unchanged: there is still exactly one `vector_text`, and no
new accessor beside the four. Every other handler that reaches `_insert_belief`
(`_on_asserted`, `_apply_fact_conflict`'s supersede/flag-for-review branches,
`_on_derived`) passes its own payload's `kind`/`key`/`body` straight through, so
for them the change is a no-op — audited, and pinned by a test that walks every
memory vector in a store built from all four paths and asserts each one equals
the embedding of the text the authority recovers.

A belief whose text is empty now writes NO vector rather than the vector of
`""`: `belief_vector_text` reports an empty text as UNRECOVERABLE, so such a row
could never be repaired by the heal or by `migrate_vectors` and would sit in
every run's `failed` list forever.

**EXISTING STORES.** Every belief corrected through `chronicle_correct` before
this fix still carries the empty-string vector, and nothing about reading the
store reveals it — the row has the canonical model tag and the right width, so
the heal's identity+geometry scan correctly calls it healthy. It is a WRONG TEXT
under a right tag, which is exactly the class of damage the A0fix refusal
contract exists to avoid creating and cannot retroactively detect. Both repair
paths do fix it, because both re-embed from the projection's own columns rather
than from anything the event said: `scripts/migrate_vectors.py` rewrites such a
row the moment it is re-embedded for any reason (a model change, a width change,
a tag canonicalisation), and the health heal does the same for any corrected
belief its mismatch scan requeues. On a store that is already canonical, neither
path visits those rows at all — they look healthy — so a store with no pending
migration should be re-embedded deliberately if past corrections matter to
recall. Verified end to end against a deterministic endpoint whose vector is a
hash of the full wire input: migrate, heal+drain and requeue+drain all recover
`search_document: <the corrected text>` byte for byte.

Two write-path side effects clear up with it: a corrected fact's mention no
longer folds an empty-string vector into its entity's identity centroid
(`_identity_evidence`), and E5 novelty / supersede-candidate detection now score
the correction's real text instead of being skipped or scored against nothing.

**2. The heal did not re-embed what the write path embedded.**
`store.enqueue_embed_job` clamped its payload to `text[:8000]` (since v5.4.0) and
`curation._task_embed` embedded that payload for `observed` and belief kinds —
only `kind='session'` re-resolved through the text authority. So for any item
over 8000 characters the deferred/heal path wrote a vector of a DIFFERENT string
from the write path, under the same canonical tag that declares a vector
correct. This is not masked at production's `max_input_tokens: 650`: production
also sets `overflow: chunk_mean`, which sends every chunk of the input to the
model, so a 9,736-character note re-embedded from 8,017 wire characters is a
different vector regardless of how small the token cap is. Measured on the
production shape and at `max_input_tokens: 8192`.

`_task_embed` now re-resolves the text through the reducer's four accessors for
EVERY kind, and the 8000-character clamp is gone, so no independent clamp
survives to disagree with the embedder's own configured one. `recoverable`
False leaves the row untouched, per the A0fix refusal contract. Two consequences
worth stating: a projection's job payload is now the complete rendered text
(§g5a — it is the only record of it, so truncating it was destroying the one
copy), and a belief whose body changed between enqueue and drain is embedded as
it now reads rather than as it read when the job was queued.

**3. A misreporting endpoint could re-geometry a whole store.**
`OpenAICompatEmbedder.healthcheck()` ends with `self.dimensions = len(v)` —
"trust the server's real dimensionality" — and every width decision downstream
is made against that adopted number, while `embeddings.dimensions` from config
was read at construction and then thrown away. With a server answering 384 for a
768-dim model name, `scripts/migrate_vectors.py` printed "expected width: 384
dims" and rewrote 1,534 of 1,536 rows into a 384-dim geometry stamped
`nomic-embed-text[prefixed]`, leaving nothing in the store to say the vectors
had ever been 768.

A probe's answer is now only trusted where nothing states what the width should
be. `migrate_vectors` and the health heal both consult
`embeddings.width_contradiction`, which takes the expectation from, in order:
`--expect-dims` (that run only); a DECLARED `embeddings.dimensions`
(`Config.explicit`, new — the merged DEFAULTS value is a recommendation, not a
declaration, and must not make an unlisted 1024-dim model look misconfigured);
then `embeddings.KNOWN_MODEL_DIMENSIONS`, a small documented table of published
widths for canonical model ids (today: `nomic-embed-text` -> 768, with its
citations in the source). A contradiction REFUSES: `migrate_vectors` exits 1
before it even opens the database — verified by sha256 over db, -wal and -shm —
naming expected vs reported and how to state a new geometry deliberately; the
heal re-tags nothing, requeues nothing and drops no proxy, warns once per run,
and reports `width_refused` in its summary and in the `health_runs` row. An
unknown canonical id with nothing declared has NO expectation and is never
refused: this is a guard against a contradiction, not a gate on models the
table has not heard of.

`migrate_vectors` also gains `--tables`, a priority ORDER (never a filter, so
"converged" keeps covering every table) — `--tables memory_vectors` puts belief
recall first during a long migration.

Three test fixtures now DECLARE `embeddings.dimensions` because they run
hashing-backed stand-ins at 16 or 256 dims under a nomic NAME, which is
precisely the contradiction shape the guard refuses; declaring the width is the
documented way to say what a deployment means, and no assertion in them changed.

### WB — the write-back, because the repair cannot happen where the store is

**A migration that takes four days cannot run against the live store, and a
copy is stale the moment it is taken.** `scripts/migrate_vectors.py` re-embeds
at a measured 0.53 texts/s on the production box and 5.57 texts/s on a laptop
serving the identical gguf, so repairing ~186k vectors is roughly four contended
days in place against roughly nine hours on a copy. But while the copy is being
repaired the gateway keeps serving: it writes new beliefs, edits old ones, and
retracts some of them. `scripts/writeback_vectors.py` is the step that carries
the recomputed vectors from the copy back into the LIVE database with all of
that happening, and it is the only part of the A0 chain that touches production
at all. Every check therefore runs INSIDE the same `BEGIN IMMEDIATE` as the
write, not as a pre-flight a concurrent writer can invalidate between the look
and the leap:

* **W1** — `UPDATE … WHERE <natural key>`. There is no `INSERT` anywhere in the
  module, so a belief retracted or forgotten on live after the snapshot STAYS
  gone. `INSERT OR REPLACE` would have resurrected forgotten content, which is
  the worst thing a memory system can do.
* **W2** — compare-and-swap on the snapshot's `(model, sha256(embedding))`. A
  row that changed since the copy is skipped and counted as
  `skipped-changed`, never overwritten.
* **W3** — the reducer-authority text recomputed ON LIVE must still hash to the
  text the copy embedded. An active session legitimately fails this and is
  legitimately skipped.
* **W4** — no pending or claimed `embed` job for that target. Stamping the
  canonical tag and the right width onto a row whose re-embed job is already
  queued turns that job into a permanent no-op, because `_task_embed`'s
  "already current" test reads tag and width only — a wrong-text-under-a-
  right-tag outcome created *by* the repair.
* **W5** — new blob width and tag byte-equal to the live gateway's active pair,
  or the whole run refuses before it opens a transaction.
* **W6** — rows whose authority text exceeds 8000 characters bypass W2 and only
  W2 (W1/W3/W4/W5 still apply), so heal activity during the window cannot make
  the old `text[:8000]` clamp permanent for exactly the rows it damaged.
* **W7** — only rows whose `(model, embedding)` actually changed on the copy.
* **W8** — batches of at most 500 (a contract, not a tunable: `_MAX_BATCH` is
  also 500), `busy_timeout` 30 s, resumable from a persisted cursor with a
  write-ahead record, so a crash between `COMMIT` and the cursor write is
  reconciled rather than redone — and a resume does not re-report our own
  writes as conflicts.

**The pre-image W2 needs does not exist anywhere after the migration.** That is
the design problem, and the answer is that the copy *before* migration IS live
at snapshot time: `--build-manifest` records `(model, sha256(embedding))` plus
the source-text hash from the PRISTINE copy, in the window between the `.backup`
and `migrate_vectors`. Nothing is asked of `migrate_vectors`, so the manifest
cannot drift from the thing it describes. A missing or non-binding manifest is a
hard refusal at four independent sites — the mutation harness had to disable all
four before it could start a run — never a quiet skip of W2, which is precisely
the failure W2 exists to catch.

The live database is opened as a plain `sqlite3` connection and never as a
`MemoryStore`, so the tool cannot ALTER a 2.9 GB production schema as a side
effect of opening it. An AST guard bans `INSERT`/`REPLACE`/`DELETE`/`ALTER` from
the module's own source, and a spy test proves the reducer's text accessors are
CALLED rather than reimplemented locally, which kills the D3-class mutation at
its root.

Measured, not argued: SIGKILL mid-batch leaves `PRAGMA integrity_check` ok, 0
half-written rows, and a resume reporting `skipped-changed = 0`; a concurrent
writer lands 167 inserts with 0 lock errors; deleted rows stay deleted
(resurrection test); queued-job rows are untouched; a width or tag mismatch
refuses before any transaction with the live bytes provably unchanged. 44
acceptance tests, 16/16 mutations killed. Manifests load per table because
216k rows at once measured ~500 MB on a box with OOM history — 569 B/row, 74 MB
peak as shipped.

The full operational sequence is `reports/MIGRATION-RUNBOOK.md`.

### A1 — directives, history and contradictions went around the ACL

**The one thing every system prompt carries was the one read nothing checked.**
`get_context`'s `[DIRECTIVE]` block called
`query_beliefs("notes", "always_inject=1 AND status='active'", …)` and rendered
whatever came back. So did `get_directives()`, which reaches
`static_block()` → `provider.system_prompt_block()` → **every** system prompt,
and so did `chronicle_list_directives`. None of the three consulted
`access.can_read`. A norm note authored by a SANDBOXED agent — the case the
topology's veto exists for — was injected into a sibling principal's context on
every turn, and a cross-user principal got the same treatment. This was an
inconsistency rather than a design choice: the topic-gated directive block a
hundred lines further down in the same function already called `_readable`.

The sibling leaks were the same shape. `history()` returned any belief's value
by id; `as_of()` replayed every `asserted` event in the log; `changes_since()`
listed recent facts; `derivation.explain()` returned a body. "You have to know
the id" was never access control — belief ids are content hashes that appear in
contradiction rows and in ordinary tool output.

All seven spec'd paths now route through `_readable`/`access.can_read` via two
new choke points, `RetrievalEngine.directive_rows` and
`RetrievalEngine.open_contradictions`, so there is exactly one place a future
surface has to reuse rather than seven places it can forget. The shapes chosen
matter as much as the filtering:

* An unreadable link ENDS `history()`'s walk exactly the way a missing one does
  — same short chain, no error, no marker — because refusing loudly would turn a
  guessed id into an existence oracle. `explain()` returns the same
  `not_found` a genuinely absent belief returns.
* `as_of()` is filtered TWICE, because a reconstructed fact has two owners to
  answer to: the EVENT that asserted it (events carry an owner and no
  `read_acl`, which is what stops a sandbox's assertions being replayed into the
  listing) and, where the belief still exists, that row's own `read_acl` (which
  is where `owner_only` is actually recorded — the event log never carries it).
* A contradiction row is a disclosure in itself: it names two belief ids and
  spells the conflict out in `detail`, so ONE unreadable side drops the whole
  row. The SQL limit is deliberately not widened to compensate — back-filling a
  restricted principal's listing would make the row count itself report on rows
  that principal may not see.

**The sweep found more than the audit listed, and those are fixed too:** entity
digest display names, `what_user_knows`/`annotate`, `get_procedure` and
`plan_context`, and rerank hints, which were keyed by `access.user_of(principal)`
so a sandboxed agent's verdicts re-weighted its siblings' rankings (ordering
only, but still a channel out of the sandbox — `rerank_hints` gains a
`principal` column, rung 14). Worst of the additions: `chronicle_set_acl` was
BOTH an existence oracle AND a privilege escalation — called against another
principal's `owner_only` belief it reset `read_acl` to the default, i.e. a
principal who could not read a belief could make it world-readable.

Surfaces that were already filtered are cited in the source rather than
re-filtered. 30/30 mutations killed; `tests/test_acl_topology.py` is 105 tests
after A1b.

### A1b — goals and reflections had no owner to gate on

**A1's honest residual, and it was a P0-class leak of the same kind.** Two
tables — `goals` and `reflections` — carried no `owner` and no `read_acl`
columns at all, so `active_goals()` and `recall_similar_situations()` could not
be put on A1's choke point: there was nothing for `access.can_read` to decide
on. Both reach user-visible output (`chronicle_active_goals`, and
`plan_context`'s `standing_goals`), so under any configured topology a sandboxed
or cross-user principal read every principal's standing goals and reflections.

Schema rung 15 adds the same `owner`/`read_acl` pair every other belief table
already carries. `ReasoningLayer._readable_row` is the one gate over both
tables, restating no ACL rule of its own, and `_stamp()` is the one thing all
five write paths use — an unstamped write would mint a row indistinguishable
from a legacy one, which is a hole in the gate rather than a missing field.

**A second hole turned up in the write path.** `update_goal` went through
`upsert_goal`, an `INSERT … ON CONFLICT`, so updating a stranger's goal id — or
a NONEXISTENT one — silently wrote the row anyway, with no owner on it. It was
a cross-principal write AND a manufacturer of fresh unattributed rows on demand.
It now refuses unreadable targets (silently, returning what a successful update
returns, for the same existence-oracle reason as `history()`) and preserves the
existing `owner`/`read_acl` instead of re-ownering someone else's goal.

**The legacy rule is to invent nothing.** Pre-15 rows keep `owner IS NULL`; there
is no backfill and no column DEFAULT, because backfilling attribution invents a
fact the store then carries forever. NULL resolves AT THE GATE to a legacy
identity that fails closed — invisible to every declared principal, and
byte-identical behaviour on the single-principal installs that are the common
case. The cost is stated rather than hidden: under some topologies a principal
cannot read its own pre-15 rows. Losing sight of an unattributed row is
recoverable; handing a sandbox's dossier to its sibling is not. 9/9 mutations
killed.

### A11b — four engine defects the hermeticity audit could only work around

The A11 audit made the test suite hermetic and, correctly, stopped at the
tree line: four of the things it had to work around were defects in the
ENGINE, not in the tests. This entry fixes those four.

**1. `MemoryStore` had no `close()`.** Its SQLite connection is thread-local
and was never closed, so every store ever constructed held its handle until
the process exited and left `<db>-wal` / `<db>-shm` on disk (~100 stray files
per suite run; on a host, a database that is never checkpointed down).
`MemoryStore.close()` now checkpoints (TRUNCATE), switches `journal_mode` to
DELETE and closes every connection it can reach, then removes the residual
sidecars — this platform's SQLite (3.54.0, Apple build) does *not* unlink
`-shm` on last close, so trusting it would have left the leak in place. The
journal-mode switch doubles as the safety interlock: it cannot succeed while
any other connection holds the database, and the unlink is skipped in exactly
that case. Closing is idempotent; a use-after-close raises `StoreClosed`
rather than silently reopening. sqlite3 pins a connection to its creating
thread, so a foreign thread's connection is *reported* in the close report
(and warned about) instead of vanishing — that thread calls
`close_thread_connection()` itself. `ChronicleCore.close()` owns the store's
lifetime and de-registers the core from the process singleton table; both
objects are context managers.

**2. `get_embedder("auto")` opened TCP connections at CONSTRUCTION.** That is
the default, i.e. what every `ChronicleCore(...)` without an explicit
embeddings config got: three `create_connection` calls to localhost:1234,
:11434 and :8080 before the constructor returned. Whether a machine happened
to be running Ollama therefore decided which embedder the core held and which
geometry every vector it wrote lived in — a REPRODUCIBILITY defect (two
machines, same commit, different behaviour) before it is a hermeticity one.
All endpoint I/O now goes through one injectable `EndpointProbe`
(`list_models` / `make` / `healthcheck`). `NetworkProbe()` remains the
default and the real-deployment behaviour is unchanged, but it is now written
down instead of implicit; `NullProbe()` contacts nothing, `StaticProbe({...})`
describes a fixed set of listeners, `set_default_probe()` pins one
process-wide for a harness that does not own the call sites, and
`ChronicleCore(..., embedder_probe=...)` threads one in. A `DegradedEmbedder`
keeps the probe it was built with, so `recheck()` cannot adopt a real server
later and reintroduce the nondeterminism. **A2 is not delegated to the probe:**
`_probe_endpoints` applies the on-host guard to every candidate before the
probe sees it *and* to whatever the probe hands back, so a substituted probe
supplies the reachability answer and never the destination policy.

**3. The probe loop swallowed every exception.** `except Exception: continue`,
twice — so a guard refusal, an HTTP 500, a malformed `/v1/models` body and
"nothing is listening" were the same silent `continue`, and a broken
deployment and an empty one produced identical output. Every candidate now
gets a recorded outcome (`refused` / `unreachable` / `no_models` /
`not_embedder` / `error` / `ok`) with its reason, readable from
`last_probe_report()`, from `DegradedEmbedder.probe_report`, and summarised in
the DEGRADED log line. Noise is controlled by outcome rather than by throwing
the information away: "nothing listening" logs at DEBUG, anything else logs
one WARNING per (endpoint, outcome) per process. An HTTP status classifies as
`error`, not `unreachable` — `HTTPError` is an `OSError` subclass, and a
server that answered 500 exists and is broken.

**4. `engine/serialize.py` read `CHRONICLE_REQUIRE_BLAKE3` at import time.**
That made the module's behaviour a function of import order and forced A11's
conftest to pin the environment before any test module was imported. The
variable is now read where it is used (`hash_name()`, `content_hash()`); the
`blake3` *import* is still attempted once and cached, since only the policy
question can change. `HASH_NAME` still reads on both `engine.serialize` and
`engine` via PEP 562, but resolves on access.

Suite: 1064 -> 1109 (45 new tests in
`tests/test_a11b_lifecycle_and_probe.py`), plus
`tests/exercise/accept_a11b_proofs.py`, which prints the socket counts and the
sidecar listings rather than asserting them.

### A12 — Config honesty: an accurate audit, and every key wired, deleted or declared

**The signature defect, measured.** Chronicle's premise is that config never
promises what code does not deliver, and the CHANGELOG lists a shipped bug of
this class for nearly every release. The 2026-09 audit found ~70 more at once —
including `security.encrypt_at_rest: true` shipped as a DEFAULT on a store that
encrypts nothing. Every declared key now has one of exactly three dispositions,
enforced by a test.

**1. The audit tool was itself dishonest, in both directions.** It grepped for
`cfg.get("<path>"` and reported 138 of 233 keys as "possibly-dormant". Measured
against an AST scan of the same tree, the truth was 100 — it was calling 44
*wired* keys dormant, because it could not see `_clamp_cfg(self.cfg,
"retrieval.rerank_top_k", …)`, a sub-dict fetched once and indexed later
(`w = cfg.get("context_engine.keep_weights"); w.get("recency")`), or a dynamic
key template (`cfg.get(f"sweeps.budgets.{name}")`). Nobody trusted its output,
which is the same failure mode as the config it audits. It also lost empty-dict
leaves entirely (`federation.pins` could never appear in the report).

`scripts/audit_config.py` is now an AST scanner that requires a string literal
to REACH a config accessor. The loose alternative — "treat any quoted dotted
path as a read" — was measured and rejected earlier (A3): it flips genuinely
unread keys like `provider` and `store` to WIRED, because those words appear as
quoted literals all over the tree. Recognised shapes: direct `get`/subscript on
`cfg` / `self.cfg` / `self.core.cfg`; helper parameters (a function whose own
body does `cfg.get(param)`, resolved per FILE so three different `_clamp`s do
not shift each other's argument positions); sub-dicts, including one hop into a
callee and into a constructor (`Topology(principals_cfg)`); key templates in
f-string, `.format()`, `%` and `+` form, with the hole anywhere in the path
(`"domains.{}.contradiction_policy"`); and table-driven reads (literals in a
collection iterated into a config read). A template whose call sites all pass
literals resolves to exactly those keys — so `_cfg_percent`'s own
`f"context_engine.{name}"` no longer wires `context_engine.engine`, which no
caller ever asks for — and a template no caller pins down falls back to a
wildcard over its subtree.

Before → after on this tree: **233 keys / 90 WIRED / 138 "possibly-dormant"**
→ **218 keys / 153 WIRED / 65 DORMANT (declared, with reasons) / 0 UNREAD**.

**2. The regression guard.** `tests/test_config_honesty.py` fails if any
DEFAULTS leaf is neither read nor listed in the new `engine.config.
DECLARED_DORMANT` map, and fails the mirror case too: a declaration that names
a key which is now wired or gone. Proven by mutation — adding an unread key to
DEFAULTS fails the guard, removing it passes. The scanner itself is proven in
both directions with planted fixtures: one module per accessor shape reported
WIRED, and a module that merely contains the dotted path as a plain string
(plus leaf-name collisions, parent-dict reads, and a helper body) still reported
UNREAD.

**3. Constants that ignored their own config.** `trust.py` imported
`CONFIDENCE_BASE`/`TRUST_CEILING` directly, so `confidence.base.*` and
`confidence.trust_ceiling.*` were decoration — while `hostmodel.py` told the
operator their host facts used "the operator's configured confidence.base".
`reducer.DOMAIN_POLICY` did the same for `domains.*.contradiction_policy`.
`trust.base_confidence`/`ceiling`/`raw_confidence`/`clamp_to_ceiling` now take
an optional `cfg` and read it (cfg=None keeps the module constants, which the
several `Reducer(store)` construction paths rely on), and the reducer passes
`self.cfg`. Acceptance: an override of `confidence.base.user_direct` changes a
stored fact's confidence (0.85 → 0.95 → 0.30, measured end to end through
`ChronicleCore`), and `confidence.trust_ceiling` caps it. A contradiction-policy
value outside the three the handler branches on falls back and logs once rather
than silently changing behaviour.

**4. `security.encrypt_at_rest` — deleted and REFUSED, not ignored.** A security
promise that silently does nothing is worse than an absent one. Nothing in this
tree encrypts anything: SQLite, WAL, git mirror and vector blobs are all in the
clear. Both `security.encrypt_at_rest` and `principals.encryption.
restricted_partition_keys` are removed from DEFAULTS, and `Config()` now RAISES
if a config sets either, naming what is and is not true. Refusing beats
ignoring: ignoring leaves the operator's false belief intact, refusing costs
them one boot and corrects it. README states it plainly under "Security".

**Deleted (the key promised nothing real):** `provider`, `store` (self-describing
labels the engine never consulted; the host's own `memory.provider` slot is
untouched) · `principals.deployment` (no per-agent-isolated deployment exists) ·
`principals.encryption.restricted_partition_keys` and `security.encrypt_at_rest`
(above) · `context.weights.*` (four weights, superseded by
`context_engine.keep_weights`, which is read and has different names AND values —
two weight tables, one fictional, is worse than one) ·
`context_engine.keep_weights.redundancy_vs_store` (the scorer has four
dimensions and no redundancy term) · `retrieval.predictive_prefetch` (its only
consumer, `provider.queue_prefetch`, is `pass`) ·
`vector_index.bruteforce_ceiling` (a ceiling past which a second, nonexistent
backend takes over) · `calibration.refit_every` (the calibrator refits on every
read; there is no periodic job) · `tier_triggers.*` (three thresholds with no
consumer).

**Declared dormant (65 keys):** every remaining unread key is in
`DECLARED_DORMANT` with a one-line reason naming what is missing — the
scheduler-shaped keys A3 will re-type (`health.schedule`, `reaper.schedule`,
`curation.sweep_schedule`, `git.snapshot_interval`), the read-and-answer and
raw-tier switches that cannot switch anything, the extraction ensemble knobs
with no ensemble, `behavior_change.high_risk_requires_review` (A16), and the
rest. Twelve of them also warn at runtime: four whose ON value claims a
protection that does not run (`forgetting.confirm_critical`,
`behavior_change.high_risk_requires_review`, `consent.enforce_purpose`,
`extraction.promote_on_read` — these fire at stock defaults, which is the honest
report), and eight whose OFF value would claim a feature is disabled when it
still runs (silent at defaults; loud the moment an operator tries to turn one
off and would otherwise believe they had).

**Wired:** `confidence.base.*` (9) · `confidence.trust_ceiling.*` (5) ·
`domains.*.contradiction_policy` (3) · `reaper.enabled` and
`reaper.startup_recovery` (the documented way to turn the reaper off did
nothing; the Reaper is still constructed, so every `core.reaper.*` caller is
unchanged, but its startup recovery is no longer driven from `initialize`).

Gates: 1041 passed (was 1004 + 37 new) · LME union@1 67.6% · ctx_eval
75.9/84.5/89.7 · compression fidelity 12/12 · H1 inertness intact. Five
assertions in `test_config_errors.py` that used `provider`/`store` as example
keys now use `db_path`/`git_repo`; `tests/exercise/accept_u1.py` reads the new
report format.
### A15 — determinism: a total order at every boundary that reaches output

**The ladder-9 F1 bug had five more siblings, and no offline gate could see any
of them.** F1's root cause was `query_understanding` joining a SET into the text
it sent to the embedder: CPython randomises string hashing per process, so the
same query embedded differently in different processes. Three investigations
blamed embedder float jitter before anyone tested ACROSS processes, and every
gate was blind because the hashing embedder is a bag of hashed tokens — it
cannot see order at all. Measured on the base tree with five `PYTHONHASHSEED`
values (0/1/42/1234/99999) in real subprocesses:

    surface                                       distinct results / 5 seeds
    event log + curation queue after one turn          5  ->  1
    retrieve_raw's order on a tied pool                5  ->  1
    search()'s order on a tied pool                    5  ->  1
    get_supersede_chain on equally-dated facts         5  ->  1
    DerivationEngine._affected_subjects                2  ->  1

The worst is the first. `curation._task_extract` built `subjects = set()` and
iterated it three ways: `derive_for_subject` per subject (which appends
`derived` events, so `seq`, `prev_head` and every downstream `event_id` moved),
one `enqueue_curation("digest", …)` per subject, and `list(subjects)` STORED as
the `canonicalize` job's payload. That payload is also the job's dedupe key —
`json.dumps(payload, sort_keys=True)` orders keys, not a list's members — so
across processes the collapse that key exists for silently stopped collapsing.
Sorted once into `ordered_subjects`, read by both consumers.

The most user-visible is `store.get_supersede_chain`: a BFS into a set, then
iterated, then sorted on `created_at` ALONE. Facts minted by one source event
share a `valid_from`, so that key ties constantly, and `get_context` prints the
result verbatim into the reader's context as `[history: a (d) -> b (d)]`. Now
`sorted(seen)` plus a `(created_at, belief_id)` key.

Retrieval gets ONE tie relation, `_rank_key`: score descending, then the
candidate's own id ascending. It is not a new relation — it is the secondary key
`_precision_order` already broke its bucket ties on, lifted out so the gate and
the ranking it reads cannot disagree about who is tied, which is the exact defect
F1 fixed one level in. Applied at `retrieve_raw`'s final sort, at `search()`'s
sort both BEFORE MMR selection (its eligibility window and greedy argmax both
inherit the pool's order) and after it, and in `_rerank` after blending, since a
blend can tie two candidates the fusion score separated and a stable sort would
then order them by scores the code no longer holds.

**The harmless sites were enumerated, not skipped.** An AST sweep over `engine/`,
the repo root, `dashboard/` and `scripts/` for every name bound to a
set/setcomp/`set()` and then iterated, `list()`-ed or joined found exactly those
four write-path sites; the rest are listed in the commit with the reason each
one cannot reach output (membership-only, already sorted at the boundary, a
scalar or boolean result, a dict rather than a set, or a sort whose tie is
already broken). One site is flagged and deliberately NOT edited because it
belonged to a concurrent editor: `health.py:89`'s `sorted(facts,
key=created_at)[:2]` has a tie a total order would settle.

F1's cross-process guard was EXTENDED rather than duplicated — its subprocess
runner became `run_under_hash_seed` / `assert_one_answer_across_seeds` and the
five new surfaces reuse it and the same five seeds. Reverting any one of the five
fixes fails its own named test; all five verified by mutation. Differential
against the base tree over a 12-turn store and 12 queries: 24 ranked lists
compared, 2 changed, 4 positions moved, every move inside a run of
BYTE-IDENTICAL scores, 0 candidates crossing a score boundary, appearing or
disappearing.

### Ladder 10 A4 — projection replay is byte-identical, and now provably so

- **Four projection side tables stopped minting `uuid4()` row ids and reading
  the wall clock inside the reducer.** `contradictions`, `corrections`,
  `supersede_candidates` and `identity_candidates` are projection state --
  `truncate_projection()` empties them and a full replay is supposed to put
  them back -- but every row they wrote carried a random id and a `now_iso()`
  stamp minted at REDUCE time. So a rebuild produced an *equivalent*
  projection and never an identical one, the CHANGELOG's 5.0.0 "full-log
  rebuild is byte-identical" claim was false, and nothing could reference one
  of those rows by id across a rebuild (which is exactly why F4d had to address
  an adjudication outcome by dedupe key instead). Each id is now a content
  hash, `serialize.projection_row_id`, built the same way `belief_id` is:
  * `contradictions.id` = `con_` + hash(belief_a, belief_b, detail, source
    event) — `_on_contradicted` and the `flag_for_review` conflict path each
  pass their own triggering event, so two events over one belief pair stay two
  rows;
  * `corrections.id` = `cor_` + hash(belief_id, reason, correction_ref,
    propagated, source event) — `_cascade` now threads the triggering event's
    id and timestamp down the recursion instead of re-reading the clock at each
    level;
  * `supersede_candidates.id` = `sup_` + hash(new_belief_id, old_belief_id) —
    the UNIQUE key the table already had. `similarity` is deliberately out of
    the hash: it is a float read off the embedder, and an edge's identity must
    not move when its embedding does;
  * `identity_candidates.id` = `idc_` + hash of the (kind, entity_id, other_id,
    mention_ref) DEDUPE KEY — so the id-addressed and key-addressed resolve
    paths now name the same row.
  All four writers became INSERT OR IGNORE, which is what the derived id means:
  re-deriving the same row from the same source is that row. A side effect
  worth naming — the health sweep no longer appends a duplicate open
  `contradictions` row on every pass.
- **Timestamps come from the event, not the clock.** The four tables above plus
  `observed_vectors`, `memory_vectors` and `query_proxy_vectors` (all in
  `truncate_projection`'s list, all written by the reducer) now take
  `created_at` from the triggering event's `recorded_at`. `now_iso()` survives
  only as the fallback for callers OUTSIDE the fold — the health sweep, the
  degraded-embedder retry queue in curation.py, the §H2 host drain — whose rows
  a replay does not claim to reproduce and which a rebuild replaces with
  event-derived ones. `truncate_projection`'s table list moved to a module
  constant, `store.PROJECTION_TABLES`, so the determinism test cannot drift
  from what is actually truncated.
- **The tests that were supposed to catch this pinned the thing they were
  testing.** `tests/h1_store_dump.py` monkeypatched `uuid.uuid4` before dumping
  a store, and `test_build.test_rebuild_identical` snapshotted five belief
  columns; between them the defect was invisible. New
  `tests/test_replay_determinism.py` pins NOTHING: real clock, real `uuid4`,
  whatever `PYTHONHASHSEED` the process got. It captures a fixture that
  populates all four tables, snapshots every column of every table
  `truncate_projection` empties (blobs digested, bytes compared), truncates,
  replays, and demands byte-identity. Plus: ids are content hashes that parse
  as no UUID; every projection `created_at` is a timestamp the event log
  actually carries; a second store built from the same log agrees byte for
  byte; and five subprocesses replaying one captured log under five different
  hash seeds produce one digest (the seed set is imported from the F1
  cross-process harness in `test_precision_packing.py` rather than re-typed, so
  the two cannot drift). Mutation-checked, not asserted: re-introducing `uuid4`
  in `projection_row_id` turns 6 of the 9 red, re-introducing it in any ONE of
  the four tables fails byte-identity on its own (all four measured), and the
  lying-clock replay — `now_iso` replaced in every engine module, not just
  `store`, since seven of them bind it by value — must not move a byte, while
  the same lying clock does move one as soon as the pre-A4 reduce-time clock
  read is put back.
- **`extractions.id` is derived too, and the H1 inertness probe lost its uuid
  pin.** `extractions` is not projection state (`truncate_projection` keeps it
  deliberately) so this is not a replay fix; it is what removes the last random
  id from a default capture flow, which is what lets `h1_store_dump.py` drop
  the `uuid.uuid4` monkeypatch. Two consecutive probes of this tree are now
  byte-identical with only the CAPTURE clock frozen — measured — where two
  probes of the pre-A4 tree differ on four rows. The capture-clock pin stays
  and is a different kind of thing: it controls an INPUT (`occurred_at` feeds
  `event_id` feeds `belief_id`), so two trees probed minutes apart can be
  compared at all. It does mean that dump cannot prove the reducer stopped
  inventing timestamps — frozen, an invented `now_iso()` and the event's own
  `recorded_at` are the same string — and `test_replay_determinism.py` is where
  that half is proved instead.
- **`TestDisabledMatchesPreH1TreeExactly`'s baseline moved to a worktree pinned
  at this commit** (`../L10_A4_base`, `CHRONICLE_BASE_TREE` still overrides).
  `v560_preH1` cannot serve any more for two reasons: A4 intentionally changes
  two id columns a default flow writes, and — with the uuid pin gone — that
  tree no longer agrees with ITSELF between runs. A baseline that disagrees
  with itself is not a baseline. The re-pin compares equal the day it is made,
  deliberately; its job starts with the next change to the default write path.
- **Old stores are not rewritten.** No schema change, no version bump: the id
  columns are already `TEXT`, and existing uuid4 rows keep their ids and keep
  working. `identity_candidates` and `supersede_candidates` cannot duplicate
  (their UNIQUE indexes are on the content the id now derives from, so an old
  row blocks the new-shaped insert and survives); `contradictions` and
  `corrections` are keyed only by id, so one re-trigger of an identical row can
  leave a uuid-shaped row and a hash-shaped row side by side until the next
  `rebuild()`, after which all four tables carry derived ids only. Read paths
  key on content, never on id shape. Measured on a store seeded with pre-A4
  uuid4 rows and then re-fed the same four logical rows through the A4 writers:
  `identity_candidates` 1 row (old id kept), `supersede_candidates` 1 row (old
  id kept), `contradictions` 2 rows, `corrections` 2 rows — nothing rewritten,
  nothing lost.
### A18 — route-aware breadth floor in context packing

**MEASURED FIRST.** A10b left one instance behind: at `token_budget=1500`
ctx_eval #16 ("How many plants did I acquire in the last month?") regressed
because the top-scoring session expanded from 2 941 to 4 487 chars and crowded
the answer session out. A10b called that a packer property rather than an
estimator flaw; one instance is not a property, so `scripts/ctx_eval_probe.py`
(ctx_eval plus instrumentation — same ingest, same 58 instances, same hit
criterion, and it reproduces ctx_eval's three totals exactly) records per
instance per tier the E9 route, the number of distinct `[SESSION ...]` blocks,
the share of the raw-evidence fill claimed by the largest one, gold-session
coverage, and the pass.

**It is a property, and it belongs to the tight tier only.** At 1 500 tokens
the raw fill is ONE session for 13 of the 28 aggregation-route instances and
the median largest session claims **99-100%** of it, while the budget is 99.9%
saturated — 13 of the 33 multi-gold-session instances carry no gold session at
all, 12 of them with <= 2 sessions emitted. At 4 000 the largest session is 56%
of the fill and at 12 000 it is 19%, where the same counts fall to 4 and 1.
#16 is representative, not an outlier. (Corpus shape: 33 of 58 instances have
evidence in two or more sessions. Route distribution under the hashing
embedder: aggregation 28 / factual 26 / preference 3 / temporal 1.)

**THE FIX.** Group i of the first N gets `remaining // (N - i)` chars of the
ranked-excerpt fill: the first session a fifth of it, the second a quarter of
what is then left, the Nth and everything after it all of it. No session can
spend the budget before the next has been offered its share, and a session that
underspends hands the surplus straight to the next divisor, so nothing is
reserved and then wasted. It rations the ranked fill only — the session-window
expansion that follows is depth bought with what breadth did not need, and is
left alone (rationing it too measurably left budget unspent).

Config-gated with documented defaults: `context.breadth_floor` (True),
`context.breadth_floor_sessions` (5) and `context.breadth_floor_routes`
(`["aggregation", "temporal"]`). N=5 is read off a sweep of 2/3/4/5/6/8 over
all three tiers, not chosen: it is the only value that improves BOTH tight
tiers, and 8 — which buys one more @1500 hit — pays for it at @4000. The
decision is exposed in `last_context_debug["breadth_floor"]` (route, sessions,
groups, share_chars), `None` whenever no floor was in force.

**The factual path is excluded BY CONSTRUCTION, and proved so.** A factual
question is answered by one session and E12 precision packing depends on
concentrating there; the preference route runs `_pref_pack_fill`, which already
weighs every group against every other. Of the 174 (instance, budget) contexts
in the corpus, the 87 on uncovered routes hash IDENTICALLY to the pre-change
tree by sha256, and all 60 that changed are on a covered route
(`scripts/a18_ab.py` exits non-zero if that ever stops being true).

**Measured results.** ctx_eval 75.9/84.5/89.7 -> **77.6/86.2/89.7**: @1500
+1.7 (gained #16 and #27, lost #19), @4000 +1.7 (gained #25, lost nothing),
@12000 unchanged. #19 is the honest cost and the same mechanism in reverse —
its ONE emitted session was already the gold one, with the answer turn deep
inside a 3 793-char block that the floor cuts to ~940. Saturation goes UP
(99.9/97.6/94.6% -> 99.9/99.9/100.0% of the enforced char ceiling): breadth
reaches sessions that still had content after the first one ran out.
lme_recall union@1 67.6 unchanged; compression fidelity 12/12; the H1 inertness
dump is byte-identical by sha256; ACL topology 72; the suite goes 1 000 ->
1 015 tests.

**Guards, each killed by a named test** (`tests/test_breadth_floor.py`): a
fixture whose gold evidence sits in the SECOND-best session at a tight budget
keeps it under the breadth route and loses it under the factual route (both
asserted, plus a positive control that the fixture really does rank the gold
session second); deleting the ceiling from `engine/retrieval.py` fails exactly
`test_the_breadth_route_keeps_the_second_session` and nothing else, verified by
doing it; `breadth_floor_sessions: 1` is byte-identical to the flag being off;
the debug field is asserted present and absent in the right cases; and the
context is byte-stable across five PYTHONHASHSEEDs, through the existing
`tests/test_precision_packing.py` subprocess harness rather than a second one.
One shape where the floor under-spends (a store with a single long session
whose ranked excerpts phase 1 declines to emit are already in `seen_excerpts`)
is characterized rather than papered over, with the reason it is left alone.

### A10b — one token ESTIMATE, explicit per-call-site safety margins

**A10 unified two chars/token ratios into one and then set that one to a
SAFETY MARGIN.** `estimate_tokens` counted chars/3 everywhere. Measured on the
corpora this project evaluates on (`scripts/measure_chars_per_token.py`;
chars-per-atom bounds true chars/token from above because a byte-level BPE
merges bytes within a pre-tokenizer atom, so tokens >= atoms): oracle.json
4.63, s_sample100.json 4.76. chars/3 therefore over-estimates true tokens by
>= 1.54x, and a caller asking `get_context` for 12 000 tokens received ~36 000
characters where ~48 000 fit — Chronicle silently returned about a third less
evidence than every budget allowed. A10 measured the cost itself and shipped it
anyway (ctx_eval @12k 89.7 -> 86.2) because the SAME estimator clamps embedding
input, where under-estimating is catastrophic: a 2048-token nomic server, an
over-long request, HTTP 500, and a curation job left permanently poisoned.

Two purposes with opposite failure modes were sharing one number. A10b splits
them:

* **the ESTIMATE** is `_CHARS_PER_TOKEN = 4` — the largest integer strictly
  below both measured bounds, leaving >= 14% for atoms that really do split
  into several tokens, and an integer so estimate and inverse stay exact in
  integer arithmetic.
* **the MARGINS** are named, documented `SafetyMargin` values applied BY each
  call site, never folded back into the estimate:
  * `CONTEXT_BUDGET` (x1) — get_context assembly/packing/trim. Under-delivery
    IS the failure mode here; the caller's own N is the headroom.
  * `COMPRESSION_BUDGET` (x1) — compress()/preflight/digest/rehydration. The
    headroom is stated elsewhere and must not be double-charged: the target is
    `low_watermark_percent` (0.55) of the model's REAL window, and
    `should_compress` re-fires off the host's real prompt-token count.
  * `EMBED_INPUT` (x4/3) — the embedding clamp, the one place an estimate
    crosses a hard model boundary. 4/3 of chars/4 IS chars/3, so this
    reproduces the incident-tested ceiling byte for byte (verified over
    0-5000 chars in both directions). Honest about its limit: it covers
    content down to 3 true chars/token, not the chars/atom ~= 1 worst case.

`context.py`'s A10 fallback pair kept `_FALLBACK_CHARS_PER_TOKEN = 3` — a second
constant that agreed on the day it was written and would have gone stale here.
It keeps none now: the import still succeeds (a checkout without
engine.embeddings degrades to `_heuristic`, which counts no tokens at all) and
any path that would have budgeted against a private ratio raises instead.

`tests/test_token_margins.py` (21) pins all of it: one constant in the tree, no
hand-written ratios, every production call naming a registered margin, and a
per-module site table so swapping a margin fails. 11/11 mutations killed,
including both directions the audit asked for (drop the margin at the embed
clamp; use the conservative margin for a budget). One of those mutations found
a pre-existing gap: because every section checks the budget before appending,
`_fit_units` is inert on every real path, so DELETING the final-trim call site
passed the whole suite — `test_the_final_trim_is_still_wired_up` now drives
`_emit` directly.

**Config restatements** (the unit moved, the measured quantity did not):
`context.precision_budget` 2000 -> 1500 (2000 x 3 = 6000 chars = 1500 x 4) and
`context.preference_budget` 4000 -> 3000 (4000 x 3 = 12000 = 3000 x 4). Both
are back at their pre-A10 literals, which is the point: E12 measured ~6 000
chars and F5 measured 12 000, and only the unit those are written in has been
moving.

**Compression fixtures re-tuned as units restatements**, every one exact
(x 3/4) and each carrying its arithmetic: context_length 2000->1500,
1000->750, 3000->2250, 800->600, 200->150, 100000->75000;
`checkpoint_digest_max_tokens` 20->15; explicit `default_token_budget` 1125
(= the 4 500-char window these fixtures were built against) where they had been
riding on a production default whose unit changed. Two sites were NOT restated
because a probe showed their decisions never depended on the unit (they assert
that watermarks SCALE with the window).

**Measured, not assumed.** A pytest plugin recorded a hash of every compression
decision per test; two baseline runs are identical, 36 nodes changed under a
bare units flip, and after restatement every test's *property* holds and the
delivered size matches to within ~1%. 26 nodes still differ byte-for-byte, and
the cause is the per-span CEILING, not the restatement: a 50-char span costs 51
chars of budget at chars/3 and 52 at chars/4, so an identical 4 500-char budget
holds 87 such spans instead of 85. The direction depends on length mod 3 vs mod
4 (a 136-char span costs 2 chars LESS at chars/4), which is why 8 nodes keep one
span more and 7 evict two fewer. No budget can remove that, and none was tuned
to try.

**Measured results.** ctx_eval 77.6/82.8/86.2 -> 75.9/84.5/89.7: @4000 +1.7 and
@12000 +3.5, both exactly back to the pre-A10 figures. @1500 goes the other way
(-1.7, one instance) and that is a real finding rather than noise — see
MEASUREMENTS/commit body. lme_recall union@1 67.6 unchanged (retrieval is not
budget-bound); compression fidelity 12/12; the H1 inertness dump is byte-
identical by sha256.

### A10 + A16 — one token estimator, whole-unit trimming, drafts marked

**A10 — the context engine had two chars/token ratios and a blind final cut.**
`get_context` budgeted `token_budget * 4` chars while `estimate_tokens`
(engine/embeddings.py) — and therefore compress(), the working-set
rehydration, the checkpoint-digest cap and every budget test — counted chars/3.
`get_context(1500)` handed back up to 6 000 chars, i.e. 2 000 tokens by the
only estimator anything else used, and `last_context_debug` reported the budget
through a third expression again (`max_chars // 4`), so the number a caller
read described neither the budget enforced nor the bytes emitted.
`_rehydrate_working_set` was the visible symptom: it asked for N tokens,
received 1.33N, and hard-cut the result mid-word.

`engine/embeddings.py` now exposes `budget_chars(n)` as the exact inverse of
`estimate_tokens`, and every budget decision in `get_context` and `context.py`
goes through that pair — `len(text) <= budget_chars(n)` *is*
`estimate_tokens(text) <= n`, so the two directions cannot drift again.

The constant stays 3 and the basis is now measured rather than asserted. No BPE
tokenizer is installable offline, so the ratio is bracketed instead: a
byte-level BPE's pre-tokenizer splits at `[A-Za-z0-9]+` / single-punctuation
boundaries and merges bytes within a piece, so every such atom costs at least
one token and `chars/atom` is an upper bound on the true chars/token ratio.
Measured on the corpora this project evaluates on — oracle.json 4.63,
s_sample100.json 4.76 — chars/3 over-estimates the true token count by >=1.54x
and chars/4 by >=1.16x. Both are safe on measured text; 3 is kept because the
same estimator clamps embedding input, where the content is arbitrary (URLs,
base64, CJK drive chars/atom toward 1), the failure is an HTTP 500 and a
poisoned curation job, and the whole compression subsystem is calibrated in
these units (chars/4 changes what compress() evicts: 9 tests, including 2 of
test_compression_fidelity's byte-exact I17 checks, stop firing).

Also fixed, all three found by asserting the new invariant rather than by
reading:
* the Tier-1 belief block was explicitly unbudgeted and could overrun before
  the raw fill ran; it now stops at the first line that does not fit;
* phase 1's boundary-truncating branch appended a `[SESSION ...]` header and
  then charged `remaining_chars` for the excerpt only, so every later section
  ran with budget that had already been spent (the other three truncating
  branches charged it correctly);
* the final cut `ctx[:max_chars] + "… (truncated)"` sliced through whichever
  fact or excerpt straddled the boundary. `_fit_units` drops WHOLE rendered
  lines from the tail and reports how many, counting its own notice against
  the budget. With every section now checking the budget before it appends,
  that trim is inert on every measured path (`dropped_units == 0`).

`last_context_debug` gains `used_tokens` / `used_chars` / `dropped_units` and
reports `token_budget` as the budget actually enforced.

`context.precision_budget` 1500 -> 2000 and `context.preference_budget`
3000 -> 4000 are RESTATEMENTS, not retunes: every figure that set them is a
char count (E12's 5 994-5 997-char contexts; F5's "6 000 chars holds 4.6-7.3
sessions, 12 000 holds 9.2-14.6"), so the token literals had to move with the
conversion to keep the measured behaviour. Their char sizes are unchanged and
are now pinned as such in the tests.

**A16 — drafts reached the reader unmarked.** `_readable` admits
`status in ("active", "draft", None)` and the structured channel selects drafts
by name, so a `flag_for_review` loser, a high-risk norm awaiting review and a
user-domain derived inference all rendered as a plain `[FACT]`/`[NOTE]`.
Drafts are now MARKED, not excluded — three producers deliberately write a
draft rather than dropping the value, so the information is meant to reach a
reader and what was missing is the caveat. `[DRAFT]` leads the line in the same
shape as the existing `[CRITICAL]`/`[CONTRADICTION]` annotations, applied in
`_render` (the one belief render, shared by the Tier-1 block and `answer()`)
and in supersession-chain points, where "latest wins" on an unconfirmed last
point is the wrong rule. `retrieval.include_drafts` (default true) drops them
instead, read at the single `_readable` choke point so it covers every channel
and every packing path at once.

Tests: `tests/test_context_budget_honesty.py` (17), each named in the fix it
guards; eight mutations (estimator reverted, `_fit_units` bypassed at the call
site and in its body, tier-1 check removed, header charge removed, `_render`
marker removed, `_readable` gate removed, `_chain_point` marker removed,
rehydration clip restored) each fail a named test.
### A5 — `search()` copied the whole vector store into Python on every query

**Not a leak: a per-query full copy.** `_vector_beliefs` called
`store.iter_memory_vectors()`, which is `SELECT * FROM memory_vectors` into a
list of dicts, on every `search()`; `_vector_proxies` and `_observed_proxies`
did the same for `query_proxy_vectors`. At 100k rows with production's width
split that is 1077 ms and an 812 MB allocation peak per query, 1178 MB process
RSS — and most of it was then scored 0.0 and discarded, because those were the
wrong-width rows A0 documents. Measured after: **102 ms, 11 MB, RSS 62 MB.**
This is also the shape of the "850 MB/min" context-engine growth that was
diagnosed as a leak once.

The three materialising readers now page `memory_vectors` and
`query_proxy_vectors` by rowid through one shared `_paged_vector_scan` and keep
a bounded top-k heap (or a scores-only best-per-belief dict). The width and kind
predicates move into SQL, where they restate rules the Python already applied.

**Ranking is byte-identical, and that was proven rather than assumed** — three
ways: a differential test over a 5,003-row seeded store running both paths at
page sizes 128 through 100000 with ties, duplicates and mixed widths; a sha256
over every result at 100k rows inside the benchmark itself; and all three eval
gates unmoved to the decimal.

**Demanding that proof found a numerical bug.** "Each row's dot product is
independent, so paging is free" is false: `batch_cosine` hands BLAS one matrix
and Accelerate changes its gemv kernel with the matrix's SHAPE, so a scan's
short final page — always under that crossover — drifted ~3e-8. The crossover is
a shape threshold that moves with `d` (768 needs ~128 rows, 64 needs ~2000), so
padding was rejected: it fixes `d=768` and breaks `d=96`. `_tail_merged` folds
the final page into its predecessor instead; verified bit-identical to the
single-matrix path across all 63 combinations of
`d ∈ {128,256,384,768,1024,2048,3072}` and nine row counts, at a cost of at most
two pages resident instead of one. Nothing downstream resolves 3e-8 — the floors
are 0.1/0.15 and RRF is rank-based — but "ranking-identical" is A5's contract,
so it is met exactly rather than approximately.

**A5 and A0 could have cancelled each other out, and the pin now runs both
ways.** A5 filters wrong-width rows out in SQL; A0 makes a wrong-width row LOUD.
If the predicate removes the rows before the counter sees them, A0's counters
read zero and the loud refusal goes quiet — two correct fixes that silently undo
each other. The integration keeps `width=` on the scoring scans and restores
A0's per-query signal with an ID-ONLY complement query per table
(`_note_wrong_dim_table`), inside the same diagnostic scope, using identity
rather than `COUNT(*)` because A0 dedupes across two tiers. Deleting the
complement turns 5 of the 9 tests in `tests/test_wrong_dim_read_refusal.py` red.
Dropping `width=` from a scoring scan — which that method's own docstring calls
"the one thing that silently reverts A5" — was caught by nothing, and rather
than repeat the claim it was measured: mutating `_retrieve_raw_inner`'s
`observed_vectors` scan in an isolated tree copy ran 1662 passed / 32 skipped,
exit 0. The review's claim holds exactly for the three `_retrieve_raw_inner`
sites and is slightly too strong for two others that the differential happens to
cover at non-default page sizes. A two-part guard now covers all six uniformly:
a behavioural spy over every `iter_*_paged` call the real queries make, and an
AST pass that reaches sites no test exercises, each with its own
not-vacuous/not-inert test.

**One negative result is recorded at the call site rather than discarded.**
Restructuring `search()`'s structured LIKE channel into a single scan measured
217 ms against a 25 ms baseline in the common case — 10x WORSE — because a
per-token `LIMIT`'s early exit is worth more than cutting six scans to one.
Narrowing `SELECT *` to `SELECT belief_id` was noise (24.4 vs 25.5 ms). FTS
backing is the real fix for that channel, and it is not A5's.

Also established while bounding the brute-force path: `vector_index` is real and
fully wired but UNREACHABLE — the backend defaults to `bruteforce` AND Apple's
`/usr/bin/python3` 3.9.6 has no `enable_load_extension`, so `sqlite_vec` can
never load there. Brute force is the only executable path, which is why bounding
it was the right thing to do.

### A7 — one heal run could stop the write path for weeks

**Strict FIFO plus one unbounded producer is a system that stops working.**
`claim_curation_job` claimed by `id` ascending and `drain` took whatever it
handed back. One health run enqueues an `embed` job per stale vector — 105k of
them on the live store — and every `extract` enqueued afterwards sits behind all
of them. At 16 jobs a turn that is ~6,500 turns before the next new turn is read
at all. Extraction is the premise's write path; it stopping is not a slowdown,
it is the system not working.

The drain is now weighted round-robin over three task CLASSES (`write_path`,
`embed`, `maintenance`) with FIFO inside a class. `drain_quotas` splits the
budget by declared shares with a ONE-JOB FLOOR — a positive share too small to
round up to a whole job is lent exactly one job from the largest class rather
than rounded away — so a class with pending work is served every turn. That
floor is the anti-starvation guarantee. Leftover budget is never thrown away: a
class that runs dry hands its quota back and a second phase spends it on whoever
still has work, so fairness costs no throughput on an uncontended queue, which
is the common case and is byte-for-byte the old behaviour. Round-robin rather
than "drain class A's quota, then B's" because the two differ when a handler
ENQUEUES: an extract that queues a digest should not put that digest behind the
whole embed quota. A control test reproduces the original starvation exactly —
0 of 5 extracts under FIFO, 5 of 5 under the fair drain.

**A claimed job whose worker died was lost forever.** `claim_curation_job` marks
a row `running` and stamps `started_at`; nothing ever moved it back, so an OOM,
a gateway restart killing in-flight work, or a plain crash left the row
invisible to every future claim. The live store had **245 `extract` rows stuck
in `running`, with 147 more failed**. `started_at` is now read as a LEASE:
health re-arms a running row older than `curation.lease_seconds` (900 s), or
fails it with a stated reason once it has burned `curation.max_attempts` (20)
claims. The reset rule is explicit — attempts go back to 0 when the SAME unit of
work is re-enqueued, so an exhausted counter describes one attempt streak and is
never a permanent tombstone.

**`curation_jobs` was unbounded.** Done and failed rows were never deleted, so
every enqueue's dedupe probe and every claim's dependency sub-select paid for
the whole history of the store, forever. `curation.retention.*` bounds it by age
AND by row count — age catches a quiet store, the cap catches a busy one that
outruns the age bound. Terminal rows only: pending and running work is never
pruned, and neither is a done row that a pending job still depends on, because
pruning that would make the dependent unclaimable — the stuck-forever state this
whole task removes. **Writing the prune surfaced a bug in its first form:** it
raised `IntegrityError` when a done row was referenced by another done row, and
one such pair aborted the entire prune.

**And the heal itself made zero progress on run 2 and every run after.** It
re-selected the same first 500 mismatched rows and offered them to
`enqueue_embed_job`, which deduped every single one: 500 row reads and 500
dedupe probes per run, achieving nothing, for as long as the backlog took to
drain. **That is the production symptom** — 60 rows re-tagged in 9 days. The fix
is that the bound is on the QUEUE, not on the call: the budget is spent on what
is already queued first and only the remaining room is used, so on a saturated
queue the requeue pass does not run at all, which is also the honest answer to
"should the heal add more work right now?". Re-TAGGING is deliberately not
bounded by it — that is a metadata UPDATE with no model call and no I/O per row,
so the same-model-different-name case converges completely in one run instead of
dripping. The retag path still repairs 1000 rows under a 10k-job backlog.

The census underneath it became a seek rather than a scan (`_mismatched_groups`
probes only the groups that are NOT the active tag at the expected width, so a
healthy store's pass 1 is a handful of empty index probes), and the one part
that cannot be a seek — an exact `COUNT(*)`, measured at ~300 ms cold on a
100k-row store, on every health run, on a store with nothing wrong with it — is
cached behind `health.census_total_max_age_hours` and force-recounted the moment
a run finds anything mismatched. The mismatch numerator is always live and
exact; only the denominator is ever cached.

### A9 — nine sweeps read the same 5000 rows forever and reported success

**A cap with no ORDER BY and no cursor is not a bound, it is a blind spot.**
Every periodic sweep carried a literal `limit=5000`, so past 5000 matching rows
it re-read *a* prefix on every run, never reached the rest, and returned
success. Nine capped sweeps were audited. **Eight were the defect**, and the
clearest is `reextract`: it spent 221 ms selecting ZERO of 22,562 eligible
events and reported that it had succeeded. That is the A7 heal's shape again,
one sweep wider — systemic rather than incidental.

The bound stays, because an unbounded sweep on a 2-core box is the hazard A7's
drain exists to prevent, but it is now a STATED PACE with a persisted cursor
behind it and a report in front of it. New `engine/sweeps.py` owns all three
parts: `sweep_budget` (per-sweep `sweeps.budgets.<name>`, falling back to the
shared `sweeps.row_budget`), a cursor in `meta` so run N+1 starts where run N
stopped and wraps when a lap finishes, and `SweepPage`, which reports
`processed` / `remaining` / `bounded` / `wrapped` — `remaining` counted against
the cursor, so it is a fact about the store rather than an estimate.
`health.run()` surfaces all of it. Eight config keys are wired as a result.

**The ninth was the opposite case, and it was the more serious one.**
Forbidden-content retraction (`reducer._on_forbidden`) was CAPPED. Everywhere
else a per-run budget is right because a sweep that is behind is merely late;
here a partial pass leaves forbidden content live and readable while the event
log records that it was forbidden — a worse defect than the one being fixed. A
bound on a redaction is a leak. It now loops to exhaustion, and `iter_all_rows`
pages it for MEMORY only (it used to materialise all 89,562 observed events at
once) and never truncates. Cost: 1144 ms against the old 50 ms, accepted
deliberately.

**Two more latent bugs turned up while testing.** `sweeps.row_budget` was
shadowed by per-sweep defaults, making the shared key unreachable — a knob that
looked wired and did nothing. And the group cursor's start sentinel was `""`:
nothing sorts before `""` under an exclusive `> after`, so every NULL-keyed
group was skipped FOREVER. That is the same defect one group wide, and the
sentinel is now `None`.

H1 inertness is handled honestly rather than by widening an exclusion: the flow
genuinely writes a `meta` row, so the store dump skips `sweep:*` keys WITH a
test proving the skip actually fires, that the row is really written rather than
decorative, and that no excluded row carries a belief, event, session or entity
id.

### A13 — a task name the schema admits but nothing can run is a schema defect

**The `curation_jobs` task CHECK and the set of handlers that exist had drifted
apart, in both directions.** `route` and `criticality` were CHECK-listed tasks
with no `_task_route` and no `_task_criticality` in any build ever shipped, so a
row enqueued under either name was work that could never happen — it sat pending
forever and made the queue depth a lie. In the other direction
`federated.enqueue_candidates_for_review` enqueued `federated_identity_review`,
which is NOT in the CHECK, so it would have raised `IntegrityError` the first
time anything called it; nothing ever did, which is why the defect was invisible
and why `FederatedChannel.pending_candidates` only ever accumulated in memory
and was dropped. The hand-maintained list inside the migration had its own
history of the same class: it silently missed `digest` and `federate_sweep`,
each miss leaving existing stores enqueuing a task their CHECK rejected — an
`IntegrityError` raised INSIDE `append_event`'s durable-capture transaction.

The CHECK is now GENERATED from `store.CURATION_TASKS` and bound to the handler
set in BOTH directions, plus an AST scan of every `enqueue_curation` call site,
so the drift class cannot recur by omission. `route` and `criticality` are gone;
`contradiction` is resolved as an ALIAS of `consistency`, because
`_task_contradiction`'s entire body was the call `_task_consistency` makes.

**Rows already queued under a retired name are never left pending.** That
distinction is the whole of `_retire_removed_task_rows`: a `contradiction` row
is real, runnable work under a truthful new name, so it is RE-TASKED (with
duplicates collapsed first, so the rename cannot violate the enqueue dedupe
invariant); a `route`/`criticality` row is work that could never happen, so it
is deleted — counted, logged at WARNING with its ids, and recorded in
`meta.curation_tasks_retired` with per-task counts and up to 200 ids, so an
operator finds out what happened rather than noticing a queue got shorter.

**The rebuild reads `PRAGMA table_info`, and that is load-bearing.** SQLite
cannot ALTER a CHECK, so narrowing one means a table rebuild — and a rebuild
written against hardcoded DDL REPORTS SUCCESS while silently dropping any column
another migration added. Proven on the real case: A7's `lease_owner` and
`max_attempts` vanish under the hardcoded form and survive under
`PRAGMA table_info`, along with types, defaults and a foreign index. Pinned by a
four-case test.

Dead code removed with it, each with a test stating what depended on it:
`provider.queue_prefetch` (a no-op OVERRIDE of a base method that is already a
documented no-op), `capture.flush_best_effort` (a no-op called by
`provider.shutdown()` — a call that read like a durability guarantee and was
not one; capture was already durable at append time), `reducer._on_distilled` (a
`pass` in the event-dispatch table for an event type nothing appends, so such an
event is now reported rather than silently swallowed), the uncallable enqueue
above, and three tracked artefacts that should never have been in a repository
(`dashboard/plugin_api.py.bak`, `plugin.yaml.bak.20260625_114235`,
`ctx_eval_r2.log`). The dashboard's `POST /process-embeddings` was wrong four
ways at once — it embedded nothing, inserted `extract` jobs by raw SQL that
bypassed `enqueue_curation`'s dedupe, matched by substring `LIKE`, and wrote
`datetime('now')`, a different timestamp format from `now_iso()` that sorts
before every row the engine writes. It is now `POST /enqueue-extractions` and
writes claimable rows through the ordinary path.

One knob was found ON and read by nobody: `retrieval.predictive_prefetch: True`.
It is DECLARED DORMANT rather than deleted — a deleted key an operator has set
is read back in silence, leaving the false belief intact, while a declared one
warns.

### A6 — the no-LLM extraction floor recalled 21% of what it was given

**`HeuristicExtractor` is the DEFAULT extractor, so its recall is what
"Chronicle captured it" means whenever no model is present** — and on the
audit's fixture (20 realistic turns, 24 expected facts) it captured 5. Four
defects, each now pinned by `tests/test_extraction_floor.py`:

**1. The sentence splitter cut inside every email address, URL, decimal and
abbreviation.** `re.split(r"[\n.!?]+", …)` turns `pat.testley@example.com` into
three fragments, so `_EMAIL` could never match a real address and the `email`
predicate advertised in `PREDICATE_MAP` was UNREACHABLE. A boundary is now
terminal punctuation plus whitespace plus an opening capital, quote or digit,
with a short abbreviation list; `v1.5` and `3.5%` survive intact.

**2. "I don't like cilantro" became a standing directive injected into every
context.** The norm gate fired on `always|never|don't|must` appearing ANYWHERE
in a line, so an ordinary preference became a `norm` note, which sets
`always_inject=1`, which puts it in the `[DIRECTIVE]` block of every context
forever. **That is the mechanism behind the L8 "~110 active norm notes" flood**,
and the reason `context.max_directives` had to be capped at 5 in the first
place. `is_standing_instruction()` now requires imperative or
standing-instruction SHAPE (a lead imperative, "you should/must", "I want you
to") and refuses questions, "never mind", and adverbial "always <gerund |
stative>". First-person preferences become retrievable PREFERENCE-class facts
and habits become `habit` facts — retrievable when relevant, neither of them
always-inject. `criticality.py` had the same bug in its "boundary" rule, where
`"never "`, `"do not "`, `"don't "` and `"always ask"` were plain substrings
promoting any text containing them to `high` — never-evict and exempt from
decay. It now shares `is_standing_instruction()` with the extractor, so the two
classifiers cannot drift.

**3. A sentence with two facts yielded one.** `_first_person_fact` returned
after the FIRST match, so "My name is Pat Testley and I work at Acme Fake Co."
stored only the name. Extraction is now multi-fact per sentence, deduped on
`(kind, entity, predicate, value)` and bounded at `_MAX_FACTS_PER_SENTENCE = 8`.

**4. Subject grounding was wrong.** "I'm Vegetarian" produced `name=Vegetarian`
on a capitalised-word test alone, and "My wife Robin Placeholder is a
pediatrician" produced entity `my_wife_robin_placeholder` with predicate `is_a`
— wrong subject and wrong relation. Names are now gated against state words and
the relation grounds on the person.

F3 §5.4's preference patterns are implemented but FENCED, because F3's own
measurement is the reason: an unfenced `\bi (like|love|prefer)\b` scored 3.8%
precision, firing overwhelmingly on politeness toward the assistant's own
suggestions. The object must be a thing rather than a pointer at the exchange,
and the speaker must be the user. Every new pattern ships with a negative case
naming what it refuses.

    metric                                     before        after
    recall    (24 expected facts)              5 (20.8%)     24 (100%)
    precision (durable items emitted)          5/8 (62.5%)   24/24 (100%)
    durable items on the 27 negatives          13            0
    norm notes / 9,800 real LME user turns     690           119
    preference-class facts, same turns         0             72
    habit facts, same turns                    0             30
    total facts, same turns                    311           397

**100% on the fixture is FITTED and says so** — the audit named those 24 facts
and A6 wrote patterns for them, so only its value against the audit's ≥70% bar
is meaningful. The unfitted numbers are the 27-case negative corpus (which
asserts zero durable items) and the two counts over 9,800 real corpus turns.
Gates moved with it: ctx_eval@1500 75.9 → **81.0** (+5.1) and recall union@1
67.6 → 68.2.

One pre-existing test fixture is restated rather than weakened:
`TestDirectiveTopicGate` used "I always prefer window seats when flying", which
was only ever a norm BECAUSE of defect 2. The channel under test is retrieval's
topic gate over norm notes, not extraction's classifier, so the fixture is
restated in the imperative shape a norm actually requires and every assertion is
kept at full strength, including the exact `ctx.count("[DIRECTIVE] …") == 1`.

### Ladder 10 A8 — an exact-name entity merge was an inferred identity decision

**Defect (premise violation).** `curation._task_identity` merged every pair of
entities sharing `(normalized_name, owner, domain)`, folding each into whichever
one the unordered scan saw first by appending a `merged` event stamped
`evidence: exact_name_match`. No adjudication, no review, no record that the two
had ever been distinct.

Chronicle's premise is that **identity is adjudicated, never inferred**, and the
project's own worked example is the whole argument: "Robin Placeholder" is one
person recorded twice — a *split* risk, if you assume difference — while two different
people are both named "Pat Testley" — a *merge* risk, if you assume sameness.
An exact name match is exactly the second case. And unlike almost everything
else in this store, the mistake does not come back: supersession can reverse a
belief because the old row survives with `status` flipped, but `merged_into`
collapses two provenance chains into one, so the projection no longer contains
the fact that there were ever two people.

The path was dead in ladder-9 (nothing enqueued `identity`), which is why A3 had
to ship the `identity` maintenance task **unscheduled** — a cadence bolted onto
this handler would have merged two same-named strangers on a timer.

**Fix — the collision becomes a candidate.** `_task_identity` now routes each
exact-name collision into E7's existing adjudication queue
(`identity_candidates`, `kind='merge'`) and applies nothing: no `merged` event,
no `merged_into` write, no entity row touched. It reuses E7's machinery whole
rather than building a parallel one, dedupe key included — the pair is stored in
sorted order with an empty `mention_ref`, the same key
`identity.observe_mention`'s centroid-driven proposal uses — so one entity pair
is **one** pending question however it was raised, re-running the sweep keeps
the original row rather than duplicating it, and a question already answered
(`rejected`) is not reopened by the next night's sweep. `similarity` is `1.0`,
which scores the *evidence*: the names are identical. Per-name proposals are
capped at `_IDENTITY_MAX_CANDIDATES_PER_NAME` (10), for the reason the
federation sweep is capped: a name matching hundreds of entities is noise, and a
queue of hundreds of unanswerable questions is not adjudication.

**What did NOT change.** An explicit `merged` event still merges
(`reducer._on_merged`). That event records a decision a principal made; only the
*inferred* path is gone.

**A3's `identity` task is now scheduled.** Moved out of `scheduler.UNSCHEDULED`
(removed from the dict entirely, rather than left there with a rewritten reason —
a scheduled task listed as unscheduled is a lie the runtime audit surface tells)
into `_ENTRY_DEFS`, on new config key `identity.schedule`, default `0 5 * * *`
(daily, an hour off `health` so two daily sweeps do not contend for one hook
call), gated on `identity.enabled` so turning identity evidence off turns off
*both* producers of the same queue. `engine/config.py`'s scheduled/unscheduled
reason table and the README were updated with it.

**Stores that already ran the old sweep.** Their merges stand. They are **not**
un-merged, and no migration attempts it: reversing them in bulk would be the
same mistake pointed backwards — an automatic identity decision, taken from the
absence of evidence instead of from a name — and some of those merges were
certainly correct. What the fix does instead is make the situation *visible*:
`store.count_inferred_entity_merges()` counts `merged` events carrying
`evidence: exact_name_match` (an index seek on `idx_events_type`, not a scan)
and `health.run()` reports it as `inferred_entity_merges`. An operator who wants
a specific historical merge undone can adjudicate it — `unmerged` is already an
event type — one decision at a time.

**Acceptance.** Two *different* people sharing an exact name ("Sam Vimes" the
baker, "Sam Vimes" the astronaut, whose mention contexts diverge below
`identity.split_below`, so the name is the only thing arguing for a merge): two
entities remain distinct, entity rows byte-identical column-for-column across
the processing pass, zero `merged` events, exactly one pending merge candidate
in canonical pair order. Re-running the sweep four more times does not duplicate
it or replace its row id. An explicit `merged` event still merges, and the sweep
then skips the merged entity. The job completes `done` through the real curation
worker. Restoring the auto-merge fails five of these tests.

### Ladder 10 A3 — the maintenance half of Chronicle was unreachable

**Defect.** Nothing in the plugin ever enqueued `health`, `decay`,
`consistency` or `backfill_sweep`; `Reaper.run()` had no caller anywhere
outside crash recovery; and `health.schedule`, `reaper.schedule`,
`curation.sweep_schedule`, `reaper.enabled` and
`health.consistency_sweep.enabled` were read by no code at all. The config
described a cron job nobody installs. In effect: nothing ever decayed
(`domains.*.auto_decay`, `salience.decay_multipliers` were dead by
consequence), a session that went quiet without a clean exit stayed `active`
forever, the CSP consistency sweep never ran, and the embedder-mismatch heal
fired only when something *outside* the tree called `core.health.run()` — while
`curation.py`'s docstring and the README described all of it as running.

**Fix — a cadence, not a daemon.** New `engine/scheduler.py`. On the existing
hook cadence (`core.tick()`, i.e. `on_turn_start`/`on_memory_write`, plus
`provider.on_session_end`) it compares each schedule's cron string against a
persisted watermark and enqueues **at most one** due job onto the ordinary
curation queue. No thread, no timer, nothing that outlives a hook call. The
work is then done by the existing bounded per-turn drain on the ordinary
`append_event` path. The decision is bounded by `maintenance.budget_ms`
(default 5) and resumes at the entry it did not reach, so no schedule starves;
`tick()` drains *before* it decides, so a job scheduled this turn never runs
inside this turn. Measured over 20 000 nothing-due calls: 0.084ms mean, 0.048ms
p50, 0.171ms p95, 0.853ms p99 (the thin tail beyond that is host scheduling
noise — it survives `gc.disable()` unchanged). The stronger measurement is
exact rather than statistical: with a trace callback on the connection, 200
nothing-due hook calls execute **0** SQLite statements. Config is parsed once
per process and the anchor is cached, so the fast path is set lookups and
integer comparisons.

**Schedules (config key → curation task), all pre-existing keys honoured:**
`reaper.schedule` (`*/5 * * * *`) → `decay {"sweep":"reaper"}`;
`forgetting.decay_schedule` (`0 3 * * *`, new) → `decay {"sweep":"beliefs"}`;
`health.consistency_sweep.schedule` (`0 * * * *`, new) → `consistency`;
`health.schedule` (`0 4 * * *`) → `health`; `curation.sweep_schedule`
(`0 * * * *`) → `backfill_sweep`. The cron parser is stdlib-only and covers
`*`, `*/N`, `A`, `A-B`, `A-B/N` and comma lists, with the standard
"day-of-month OR day-of-week when both are restricted" rule; times are UTC.
Names (`MON`), `@daily`, seconds and the Quartz extensions are REFUSED, not
approximated — an unparseable string disables its schedule with a warning, the
same as the empty string does deliberately.

**`Reaper.run()` gets a caller** inside `_task_decay`, told apart from the
belief-decay half by payload, because the two want cadences three orders of
magnitude apart. A hand-enqueued `decay {}` still means both, as it always did.

**What is deliberately NOT scheduled**, with the reason recorded in
`scheduler.UNSCHEDULED`, surfaced by `core.maintenance_status()` and asserted
by the test suite: `identity` (its handler AUTO-MERGES entities on an exact
name match — an inferred identity decision, which the premise forbids; blocked
on A8), `derive`/`consolidate` (they mint new beliefs: capture, not
maintenance), `reextract` (materialises the whole observed-event table before
slicing 200 off it), `contradiction` (an alias of `consistency`), and
`route`/`criticality`, which have NO handler at all — a scheduled no-op is
worse than no schedule, because it looks like maintenance. Every other task in
the `curation_jobs` CHECK already has a producer, and a test asserts that no
task value is silently unaccounted for.

**Watermarks: `maintenance_runs` (schema_version 11 → 12)**, probe-then-create
like every step of the ladder, with an old-DB upgrade test. Keyed by schedule
ENTRY, not task (one task, two cadences). The column records the *schedule
instant* the entry was last enqueued for, not the wall clock and not the job's
outcome — so a missed day is one catch-up rather than a queue of them, and a
permanently failing job cannot become an infinite enqueue loop.
`truncate_projection` deliberately does NOT clear it: a watermark is not
derived from the event log, so a rebuild cannot recreate it, and clearing it
would make every rebuilt store look like one that had never run maintenance and
fire every sweep at once.

**First run.** A schedule with no watermark measures from the store's own
beginning — its earliest recorded event — falling back to process start for an
empty store. Nothing is persisted to bootstrap that (which is what keeps the
default path inert), it is identical in every process (so a restart cannot
reset a daily schedule), and it means an existing store, which has by
definition never run maintenance, finds everything overdue on its first hook
call and works through it one job per call.

**Two idempotence defects that scheduling would have exposed**, found by
running the sweeps repeatedly for the first time:
* `store.open_contradiction` filed a NEW row every call. Hourly, one
  unresolved disagreement would have become 24 rows a day in the health
  snapshot and the `[CONTRADICTIONS]` context block. Now conditional on no open
  row for the pair; a resolved contradiction that comes back is still news.
* `forgetting.decay_sweep` takes one rung off the fidelity ladder per run and
  does not re-date the belief, so the SWEEP INTERVAL, not `domains.*.decay_days`,
  decides how fast an already-old belief reaches `tombstone`. That is why the
  decay schedule is daily rather than hourly. **Not fixed here** (it is a
  forgetting.py semantics change, outside A3): an eligible belief still ladders
  one rung per day rather than per `decay_days`. Flagged for the register.

**Surfaces.** `core.maintenance_status()` (last run / next due / disabled
reason per schedule, plus the unscheduled list); the same dict inside
`health.run()`'s result, so it is recorded in `health_runs`; and a
`maintenance` panel in the dashboard's `/status`.

**H1 inertness.** `maintenance_runs` is deliberately NOT added to the dump's
exclusion list. It would qualify (empty at defaults, asserted directly) — but
the base tree has no such table, so leaving it inside the comparison means a
watermark written on the default path fails
`test_store_dump_is_byte_identical_to_the_base_tree` immediately, which
excluding it would trade for a promise. An empty table renders no lines, so it
costs the dump nothing. A test asserts it stays out of `H1_TABLES`; the probe
flow is run for real (subprocess, frozen clock) and the table read back empty.

**Still open, recorded rather than fixed.** `scripts/audit_config.py` still
reports the five schedule keys as "possibly-dormant". They are genuinely read
now — but through `scheduler._ENTRY_DEFS`, a table of key names consulted by
`self.cfg.get(key, default)` with `key` as a variable, and the script only
models a quoted literal sitting next to an accessor. That is the same
under-reporting A12 already owns ("teach `audit_config.py` the accessor forms");
the loose fix available here — treat any quoted dotted path as a read — was
measured and rejected: it would also flip `provider` and `store` to WIRED, and
those two really are unread. Making the tool wrong in the other direction is
not an improvement.

Tests: `tests/test_maintenance_scheduler.py` (66). Gates: pytest 954 passed;
LongMemEval union turn-recall@1 67.6%; ctx_eval 75.9/84.5/89.7;
compression-fidelity 12/12; H1 byte-identity dump unchanged.


## 5.6.0

Everything below this line predates v5.7.0. These entries were written while
this file kept all unreleased work under a single heading, so they span the
5.4.1 → 5.6.0 line rather than 5.6.0 alone. v5.7.0 added per-version headings
above but does not split these retroactively: the boundaries are not recoverable
from the text, and inventing them would put a wrong date on real work. `git log`
is authoritative for which release a given change shipped in.

### Ladder 9 fix program (F1 / F2X / F5 / F4) — integration summary

Four independently-developed work items, integrated onto `v560` in that order.
Each has its own full entry below; this is the map of what the program set out
to fix and, at the end, the one place where two of the items meet.

**F1 — the E12 firing shuffle was never float jitter.** The same six
LongMemEval instances fired E12 on 4 of 6 one day and 5 of 6 the next with no
code change, and the cause was found rather than guessed at:
`query_understanding` joined a `set` into the text it embedded, and CPython
randomises string hashing per process, so the same question was embedded as a
different **word order in every process**. A word-order-sensitive embedder
therefore produced a different query vector, a different top-20, and a
different gate answer each run. It went unseen because every offline gate runs
the hashing embedder — a bag of hashed tokens, and so the one embedder that
cannot observe the bug. Recorded so nobody re-derives it: ollama/nomic returns
bit-identical vectors for identical input, and two stores built from one
instance inside ONE process agree to the last float. There is no per-build
jitter in this pipeline at all. The REAL ties that remain are handled
separately, by a relative tie epsilon, a tie-aware head and an event-id
tiebreak, so the gate's ordering and its head boundary can never disagree
about who is tied.

**F2X — two always-on refusals for E12, both from measured failures.** The
supersede-chain veto: the cut drops every session but the modal one *and*
skips the ranked-belief block, which is the only place E4's
`[history: A -> B]` annotation renders, so on evidence the store has already
recorded an update for, it hands the reader the pre-update value with nothing
anywhere to say a later one exists. Scoped to the measured head rather than
the leader, because the head is the pool the gate's own claim is made over.
The true-argmax gate: E9's margin gate sends an unconvincing winner back to
`"factual"`, so the route string conflated "factual is nearest" with "nothing
else was convincing" — and E12 read the string. Neither refusal is a dial;
neither adds a config key.

**F5 — the preference route was dead code, and so was the E12 guard that
depended on it.** One global 0.20 routing margin assumed four prototype routes
separate equally well; measured over 250 real questions the shipped
distribution was factual 240 / aggregation 10 / preference 0 / temporal 0.
Per-kind margins make the route reachable; preference packing then spends the
budget on the user's own turns instead of assistant prose; and E9's dead
`[PREFERENCE]` addendum was excised rather than repaired, after measuring that
repairing it does not work.

**F4 — four review findings and one revalidation.** A vestigial
`reranker_version` knob removed rather than documented again (F4a); the E10
config-coercion path driven end-to-end through `answer()` instead of only in
isolation (F4b); rerank hints scoped to an owner, closing an ordering-only but
real cross-owner leak, at `schema_version` 11 (F4c); identity-candidate
adjudications made replay-safe by addressing them through their stable dedupe
key rather than a uuid4 row id a rebuild re-mints (F4d); and
`_MMR_POOL_OVERFETCH = 1.5` revalidated on the 40 `ctx_eval` instances it was
never tuned against, confirming the value (F4e).

**Where F5 and F2X meet — two independent layers, both kept.** A preference
question is now excluded from E12 precision packing for two separate reasons:
F5 routes it `preference`, so E12's `route == "factual"` precondition excludes
it, and F2X's `_raw_route` requires the raw score geometry to name factual,
which on a preference question it does not — even when the margin gate has
snapped the route *string* back. The overlap is real, not notional: F5 shipped
one discriminating test that restored the 0.20 margin and asserted the defect
returned, and on the merged tree that assertion is false, because F2X holds
the gate on its own. `tests/test_pref_pack.py::TestE12DoesNotPrecisionPackPreference`
therefore disables the layers one at a time — plus a case with both off,
showing the original defect still reproduces on the fixture. This matters
concretely: with F5's route guard deleted and F2X left standing, exactly one
test in the whole suite fails, and it is the one written for this. Without it,
that layer could have been removed with a fully green suite.

- **E12 will not cut a context that has a recorded update in it, and will not
  cut on a `factual` route it got by default (Ladder 9 F2X).** Two refusals,
  both from measured LongMemEval failures (`reports/F2-ku-abstention.md`), both
  always-on safety semantics rather than dials — no new config key, and no
  effect on any query where E12 was not going to fire.
  * **Supersede-chain veto** (`_head_has_live_update`, consulted last in
    `_precision_decision`). The cut drops every session but the modal one *and*
    skips the ranked-belief block — the only place E4's `[history: A -> B]`
    annotation renders — so on evidence the store has already recorded an
    update for, it delivers the pre-update value with nothing anywhere to say a
    later one exists. Measured on `07741c44` ("Where do I initially keep my old
    sneakers?", real nomic): 47,998 chars → 5,904 with the updated location
    absent, and a reader that answered correctly at full budget said "I don't
    know". Scope is the **measured head**, not the leading candidate: the
    leader-only version was implemented first and does not fire on that
    instance (the leader's derived belief has no chain, the head's fifth
    member's does), and the gate's own claim — "the modal session holds
    `precision_concentration` of the top candidates" — is a claim about the
    head. Honest about what it detects: "this head carries a live update edge",
    not "that edge answers this query"; it refuses rather than resolves.
  * **True-argmax gate** (`_raw_route`, at the E12 call site in
    `get_context`). E9's margin gate sends any non-factual winner that fails to
    beat `factual` by `retrieval.query_routing_margin` back to `"factual"`, so
    the route *string* conflates "factual is nearest" with "nothing else was
    convincing". E12 read the string and cut a multi-session cost comparison
    whose true argmax was `preference` (0.448 vs factual 0.373, the lowest of
    the four) down to one clean session; the reader stopped abstaining and
    produced a confident fare breakdown (`09ba9854`, 47,992 → 5,997). E12 now
    additionally requires the raw geometry to name `factual`. E9 itself is
    untouched — same route string, same margin, same debug field — and
    `_raw_route` reads `scores` only, so how the margin is applied can change
    without moving it. Empty `scores` (routing disabled, no embedder, an
    unembeddable bank) returns `"factual"`, so a tree with no routing signal is
    byte-identical to before.
  Gates: 853 tests (15 new, each differential against the same store with the
  guard removed); union@1 **67.6%**; compression fidelity 12/12; H1 inertness
  dump byte-identical to `v560_preH1`. `ctx_eval` **77.6/84.5/89.7 →
  75.9/84.5/89.7**, attributed instance by instance: 4 of the 5 firing
  instances stop firing (all four have a non-factual raw argmax **under the
  hashing embedder**, where that argmax is a token-overlap hash and least
  meaningful), 3 of them score identically at every budget, and exactly one
  (`gpt4_731e37d7`) loses the answer-bearing turn at `token_budget=1500` only —
  it is still a hit at 4000 and 12000, so this is a position change at the
  tightest budget, not lost evidence. The chain veto changes **nothing** on
  either offline corpus: E4's default `curation.supersede_similarity` (0.82) is
  dormant under hashing, so no edge exists there to trip on.
  Cost recorded rather than hidden: under real nomic the true-argmax gate also
  stops the cut on `58ef2f1c` (argmax `temporal`) and `af8d2e46` (argmax
  `aggregation`), two single-session-user questions where E12 fires today. Both
  are arguably questions E12's own doc-comment says should never take this
  path, but the reader-accuracy effect is **unmeasured**.

- **The embedded query text no longer depends on `PYTHONHASHSEED` (Ladder 9
  F1).** `query_understanding` built its expansion as a `set` and then
  `" ".join(...)`-ed it into the text handed to the embedder. CPython
  randomises string hashing per process, so the same question was embedded as a
  different **word order in every process** — and a semantic embedder is word-
  order sensitive, so the query vector, the candidate pool, its top five and
  therefore the E12 gate's answer changed from one run to the next **on the
  same store**. That was the whole "E12 fires on 4 of its 6 motivating
  LongMemEval instances today and 5 tomorrow" defect. It is now the query's own
  content words in the order they were asked, deduped, then predicate synonyms
  in a fixed order.
  Not embedder noise, which is where it was expected to be: measured while
  chasing it, ollama/nomic returns **bit-identical** vectors for identical
  input (single and batched), and two stores built from one instance inside a
  single process produce candidate pools that agree to the last float. Nothing
  in the existing suite could have caught this because every offline gate runs
  the hashing embedder, which is a bag of hashed tokens and therefore order-
  **invariant** — the one embedder that cannot observe the bug. The regression
  test is consequently cross-process, over five `PYTHONHASHSEED` values.
  Measured effect: the six instances now probe **byte-identically across three
  independent store builds each** (18/18 runs), where before the firing set
  moved between runs. Every offline gate is unchanged (union@1 67.6%,
  ctx_eval 77.6/84.5/89.7, all 180 corpus contexts byte-identical to v560),
  precisely because the hashing embedder cannot see word order.

- **The precision gate's answer is a function of the scores, not of arrival
  order (Ladder 9 F1).** Two guards on E12's head, both about ties that are
  real rather than noise:
  * `_precision_order` — the gate and its packing now read the pool ordered by
    **tie bucket** (the score as a fraction of the pool's best, snapped to a
    `_PRECISION_TIE_EPS` = 1e-3 relative grid) and then by event id. Before,
    equal-scoring candidates came back in whatever order `retrieve_raw`'s dict
    was filled in — an FTS pass followed by a heap drain.
  * `_precision_head` — the 5-candidate head boundary is **tie-aware**: it is
    drawn on the same buckets, so every member of a tie at the cut is counted
    instead of whichever one sorted fifth. The suite's own dominant fixture has
    such a tie (ranks 5-7 are three bulk turns agreeing to better than a
    thousandth) and its head came out 5 long or 7 long from an identical pool.
    The extension is not a "be more conservative" knob — it can move the share
    either way (`e47becba` measures 0.40 under the hard cut and 0.50 tie-aware)
    — it just returns one number.
  The reported `margin` is floored at zero, because inside one bucket the id
  decides the order and the runner-up's raw score can sit a hair above the
  leader's; unfloored, a negative lead would silently refuse the query, since
  `context.precision_margin` defaults to 0.0.
  Also: `_precision_decision` no longer takes a `principal` no code read (the
  pool was already ACL-cleared by `retrieve_raw`; the argument now lives in the
  docstring), and `_expand_session_window` takes `existing_event_ids` so the
  precision leader is excluded from its own session window by identity rather
  than by exact excerpt-string equality. Scoped to the precision path: on the
  full-budget path `retrieve_raw` can hand phase 1 an FTS row whose excerpt is
  not the payload's, and that path's bar is byte-identity with a pre-E12 tree.

- **Per-kind query-routing margins (Ladder 9 F5).** `retrieval.query_routing_margins`
  overrides `retrieval.query_routing_margin` for named question kinds; ships as
  `{"preference": 0.05}`. One global threshold assumed the four prototype routes
  separate equally well and they do not: measured over 250 real LongMemEval
  questions with a real embedder, `preference` is the argmax on 15/15
  single-session-preference questions but never leads `factual` by more than
  0.138, so at 0.20 the shipped route distribution was factual 240 /
  aggregation 10 / **preference 0** / **temporal 0**. Both the E9 preference
  route and the E12 guard that depends on it were dead code. 0.05 is read off
  the measured sweep — it covers 12 of the 15 targets at 15 cross-type
  collateral, against 15/15 at 23 collateral for 0.02 — and it is what makes
  E12's `route == "factual"` gate non-vacuous here: a preference question was
  measurably precision-packed onto the wrong session (`1d4e3b97`), which is
  what that gate exists to prevent. Kinds absent from the map are unchanged.
  Note the narrowed contract: `query_routing_margin: 1.0` no longer forces every
  kind factual — `query_routing: false` is the switch that disables routing.

- **Preference packing: user turns first (Ladder 9 F5).** On the `preference`
  route `get_context` now packs the **leading message of every ranked excerpt**
  — the user's own turn — across all sessions first, defers the assistant
  halves, skips the tier-1 ranked-belief block, and cuts to
  `context.preference_budget` (default 3000 tokens). Why: a preference question
  is not answered by any item in memory, so the reader needs everything the user
  said about themselves, and measurement said it was not getting it — 73–91% of
  a packed preference context was assistant prose, and the one instance E12 had
  already cut to 1500 tokens spent 5 471 of 5 994 chars on a recipe list and
  delivered 3 of the gold session's 9 user turns. Re-measured after this change,
  the same contexts are 94–95% user text at a quarter of the volume, and on the
  probed preference misses the answer session's evidence turn arrives verbatim
  where it did not: `1d4e3b97` 0/2 → 2/2 (2 runs), `06f04340` 0/1 → 1/1
  (5 runs), with `caf03d32` 2/2 and `57f827a0` 1/1 held at 1/4 the bytes.
  `75832dbd`, whose answer session ranks 6th–9th of 10–12, is the one that got
  less reliable rather than more: 1/1 on 3 of 5 runs against 1/1 at the old 48k.
  Gated on a non-empty raw tier: with nothing to pack, trading the belief tier
  away is not a trade, so the route stays on the full-budget path.
  `context.preference_packing: false` restores the un-split fill. The decision
  joins the E12 fields on `RetrievalEngine.last_context_debug` as `pref_pack`.
  The budget is 3000 rather than precision packing's 1500 because of counting,
  not taste: a median session in these haystacks holds 6 user turns totalling
  ~1 000 chars, so 6 000 chars fits 4.6–7.3 sessions complete, not the ~10 the
  design assumed. That shortfall is worse than it sounds, because `retrieve_raw`
  orders near-tied candidates differently from run to run (measured on v560 as
  well: the same instance's answer session came back at header rank 4, then 5),
  so at 1500 tokens the same instance delivered 7 of 7 answer-session user turns
  on one run and a bare header on the next. 12 000 chars holds 9.2–14.6 sessions
  complete, which covers the whole group list and takes the ordering out of the
  decision.

- **E9's preference-belief addendum removed (Ladder 9 F5).** `get_context` no
  longer appends `[PREFERENCE] <attribute>: <value>` lines on the preference
  route, and `retrieval.query_routing_preference_cap` is gone with it. It
  selected those lines with no relevance term and no `ORDER BY` — rowid order —
  and it was dead in three independent ways: the route never fired, the default
  heuristic extractor emits no preference-shaped facts (0 rows in 7 of 8 probed
  haystacks), and its `len(ctx) < max_chars` guard cannot fire against a raw
  fill that spends the budget to the last byte. Repairing it was measured
  rather than assumed: adding first-person preference patterns to the extractor
  yields 211 facts across the 9 probed haystacks of which 8 (3.8%) come from
  the answer session, and no ordering rescues the five lines it would inject
  (rowid 0/45 from the answer session, `created_at DESC` 3/45, ASC 0/45).
  Preference packing delivers the same content from the primary source — the
  user's own sentence, out of the sessions retrieval ranked for that question.

- **Precision packing: deliver less when confident (Ladder 9 E12).**
  `get_context` now cuts to `context.precision_budget` (default 1500 tokens)
  when — and only when — the query routes **factual** (E9) *and* retrieval has
  **converged on one session**: the modal session of the top-5 raw candidates
  holds at least `context.precision_concentration` (default 0.60, i.e. 3 of 5)
  of that head, and the leading candidate is itself inside it. It then packs
  that leader first (§L8 evidence-forward, unchanged), the rest of that session
  interleaved nearest-turn / best-ranked, and nothing else — no ranked-belief
  block, no directives/contradictions/critical facts, no digests or federated
  rows. Why: measured on stratified-250 with a real embedder and a judged
  reader, contexts that made the reader **abstain** at a 12k budget were
  answered correctly when cut to ~1k of the same items' head, evidence position
  unchanged — abstention tracks context volume, not evidence quality.
  Session concentration is the gate because it is what measurement showed
  separates the two populations: on the six single-session-user questions this
  exists for, the leader's score margin is 0.02–0.16, inside the range of the
  crowded multi-evidence questions (up to 0.46), while their top-5 piles into
  one session (0.6–1.0) where the crowded ones spread (0.2–0.4). An earlier
  margin-gated build was either inert on all six or cost up to 12 ctx_eval
  points; the shipped gate fires on 4 of the 6 (48k-char contexts → ~6k, each
  still carrying its evidence turn) and *lifts* ctx_eval@1500 from 75.9% to
  77.6% with @4000/@12000 unchanged — 165 of that corpus's 180 contexts come
  back byte-identical to the pre-E12 tree, and the 15 that change are the
  firing ones.
  The gate is conservative by construction and every ambiguity resolves to the
  full budget: a spread head, a pool too short to fill the head, a pool that
  only knows one session (nothing to converge away from), a leader outside the
  modal session, a leader that is a `session:`/`proj:` pointer rather than a
  turn, a non-factual route, or no embedder (with no cosine term the head is
  FTS rank order, which cannot say where retrieval converged).
  `context.precision_margin` (default 0.0) is a secondary tightening dial on
  the leader's lead. Config-gated by `context.precision_packing` (default on);
  off, and in every non-firing case, output is byte-identical to before.
  Costs no extra retrieval: the probe is the same `retrieve_raw` call the raw
  fill already made. The decision is exposed as
  `RetrievalEngine.last_context_debug` (`route`, `precision`,
  `precision_concentration`, `precision_margin`, `precision_session`,
  `precision_event_id`, `token_budget`) and on the `get_context` tool result,
  so an eval can attribute an answer to the packing that produced it.

- **Context-pressure warning span (Ladder 7 R9).** `compress()` now emits a
  one-shot system-role advisory the first time `last_prompt_tokens` reaches
  the HIGH watermark (`context_engine.is_under_pressure()`), so the agent has
  a chance to `chronicle_pin_context` anything it wants to keep before forced
  eviction runs; the flag re-arms once `update_from_response` observes the
  window drop back below the watermark. The warning is fit against the same
  `_target_budget()`/`used` accounting as the rest of the output (clipped, or
  skipped and left un-latched if there's no room this call) so it can never
  push `compress()` over its own R2 budget guarantee, and it is only latched
  once actually included in what's returned -- so the small-body early-return
  shortcut can no longer latch the flag without ever delivering the span.
- **`vector_index.backend: sqlite-vec` is real.** It was configuration fiction —
  the setting existed, and every query brute-forced anyway. It now maintains a
  `vec0` virtual table mirroring `observed_vectors` (created lazily, written on
  add, cleaned on delete/prune/truncate) and serves `retrieve_raw`'s vector scan
  by KNN `MATCH`. Strictly optional, guarded like the numpy path in
  `embeddings.batch_cosine`: the library missing, a sqlite3 built without
  loadable extensions (Apple's macOS system Python), or a `vec0` left at a
  different embedding width all fall back to the paged scan, permanently and
  quietly. `bruteforce` stays the default and is untouched. Results are the same
  either way — the paged scan credits every FTS hit's vector contribution as a
  side effect of scanning past it, so the fast path fetches those vectors by id
  rather than letting a bounded window drop them, and widens the window when ACL
  filtering prunes its top. 5,000 vectors, 50 queries: 37.5ms → 6.4ms per query.

- **No more silent hash fallback.** `model: auto` with no reachable embedding
  server used to quietly switch to the offline hashing embedder — hash vectors are
  indistinguishable from model vectors downstream and permanently skew retrieval.
  It now runs **degraded**: no vectors are written, each one becomes an `embed`
  curation job that is deferred and retried with backoff (30s → 30m) until a
  server appears, at which point the worker adopts it and drains the backlog. One
  loud log line at init says which mode is live and why. `model: hashing` is
  unchanged — that is the deliberate offline/CI setting.
- `$CHRONICLE_EMBED_MODEL` overrides `embeddings.model`, so eval/CI can pin the
  deterministic offline embedder without editing config.
- Schema v2 + migration: `curation_jobs.run_after` (deferred retry) and task
  `'embed'`. Existing stores are migrated in place on open — `CREATE TABLE IF NOT
  EXISTS` never touches an existing table, so without this an old store would fail
  the task CHECK *inside* the durable-capture transaction and fail every claim on
  the missing column. `meta.schema_version` records the level.
- `scripts/requeue_hash_vectors.py <db> [--dry-run]`: delete vectors written by
  the hashing embedder and requeue the real embeds. Idempotent.

## 5.4.0
Abstention support gate; chunked capture; degraded-mode embeddings with retry queue and self-heal; paged vector scan + optional sqlite-vec; session-grouped dated context with session windows; temporal channel (absolute + relative w/ now=); graph read channel; entity digests; standing user profile; NOOP-dedup; corrected chronicle_correct/chronicle_remember; generic local-DB federation provider + projection embeddings + SELECT-only db_query tool; config honesty audit. Canonical embedder: nomic-embed-text (local only).

## 5.3.3

- Fix: context engine not loading ("Context engine 'chronicle' loaded but no
  engine instance found" → fell back to the built-in compressor). The
  context-engine loader's subclass-fallback path scans the module for a
  ContextEngine subclass, but the classes were only imported lazily inside
  register(). Now ChronicleContextEngine / ChronicleMemoryProvider are exposed at
  package top level so that path finds them.
- Hardened register(ctx): each slot (memory / context / command) is registered
  independently, so a loader collector that rejects command registration can no
  longer discard an already-registered context engine.

## 5.3.2

- Added a user-facing **`/chronicle`** slash command (registered via the general
  plugin system) that prints status in-session — including whether embeddings are
  a live local model or the offline hashing fallback, plus store counts. Tools are
  agent-invoked; this gives the user a direct handle Hermes understands.

## 5.3.1

- Added an embedding diagnostic so you can confirm whether the selected model
  actually embeds: `scripts/embedding_check.py` (shell) reports the configured
  model, visible local servers/models, the resolved embedder, and a strict live
  test embed (exit 0 = real model, 2 = offline hashing, 3 = selected-but-failing).
  Also exposed as the `chronicle_embedding_status` tool / `core.embedding_status()`
  for checking the live runtime selection from within Hermes.

## 5.3.0

- Embedding model default is now **`auto`** (no hardcoded `embeddinggemma-300m`).
  Auto-detects a running local OpenAI-compatible server and uses **whatever
  embedding model it serves** — queries `/v1/models`, picks an embedding-looking
  id (or test-embeds candidates), so it adapts to Ollama / LM Studio / llama.cpp
  naming instead of assuming an id. Pin a specific id to override; `hashing`
  forces offline; falls back to hashing if nothing is reachable.

## 5.2.1

- Graceful failure when a local model is configured but can't embed. `embed()` is
  now resilient: a model with no embeddings support, a missing `/v1/embeddings`
  route, a wrong model id, a timeout, or a server that dies mid-session no longer
  raises — the embedder trips to the offline hashing embedder (same dimensions)
  for the session and logs once.
- The durable capture path is guarded independently (`reducer._safe_vec`), so the
  embedding backend can never roll back a `sync_turn` write (I12); retrieval and
  session-summary embedding are guarded too. FTS retrieval continues regardless.
- `healthcheck()` stays strict (init still cleanly falls back to hashing when the
  endpoint/model can't embed) and uses a short timeout so a hung server can't
  stall startup.

## 5.2.0

- **Local embedding model is now the default.** Embeddings use a real local
  model (`embeddinggemma-300m`) over an OpenAI-compatible `/v1/embeddings`
  endpoint, auto-detected across common local servers (LM Studio :1234, Ollama
  :11434, llama.cpp :8080) or a configured `embeddings.base_url` /
  `$CHRONICLE_EMBED_BASE_URL`. New `OpenAICompatEmbedder` (stdlib `urllib`, no
  new deps).
- If no local server is reachable, Chronicle **falls back to the offline hashing
  embedder** with a warning — retrieval (FTS + vectors) never hard-breaks, and
  the box still works with no model running. Set `embeddings.model: hashing` to
  force offline.
- Setup wizard adds an `embeddings_base_url` field; `embeddings_model` now
  defaults to the local model.

## 5.1.1

- Embeddings are honest about the default: the built-in **offline hashing**
  embedder is the default and always-available fallback. `engine/config.py`,
  the core, and the setup-wizard field now agree (no more `embeddinggemma-300m`
  shown as the default when hashing is what actually runs).
- The core now builds its embedder from config via `get_embedder(...)`; setting
  a real model name attempts to load a local runtime and **falls back to hashing
  with a warning** if unavailable (`engine/embeddings.py:_load_model_embedder`
  is the pluggable hook), instead of being ignored.

## 5.1.0

- Bumped version so the version-checked installer/updater detects changes since
  5.0.0 (the proper-Hermes-plugin restructure — `register(ctx)`, relative
  imports, root-level adapters — is in the 5.0.0 notes below).
- Removed references to other OCAS skills from the plugin (no longer names
  predecessor/sibling skills in manifest, docs, or code).

## 5.0.0

First complete build of the Chronicle memory system — the canonical event-sourced
memory + working-memory context for Hermes.

### Added — packaging
- Hermes **plugin** package: `plugin.yaml` manifest + a `register(ctx)` entry
  point in `__init__.py` that registers BOTH slots (memory provider + context
  engine) from one shared core, defensively across the memory / context-engine /
  general discovery paths. Adapters live at the package root (`provider.py`,
  `context.py`) and use relative imports, so the Hermes loader's synthetic-parent
  package resolves them. Installs via
  `hermes plugins install indigokarasu/chronicle-agent-context-and-memory`;
  activate with `memory.provider: chronicle` / `context.engine: chronicle`.

### Added — engine (all six build phases)
- Event-sourced data plane: append-only log + pure reducer → belief store, with
  atomic append = reduce + git-queue + curation in one transaction; idempotent,
  content-addressed; full-log rebuild is byte-identical.
- Capture + reaper: durable per-turn capture; crash-only finalization independent
  of clean shutdown.
- Recall-oriented extraction (pluggable + deterministic offline default);
  curation worker + DAG.
- Dual-tier retrieval + read-and-answer with promote-on-read (recall floor) and
  abstention; structured + bitemporal lookups; ACL/purpose filtering.
- Truth maintenance + guarded compositional derivation (scoped, hedged,
  defeasible) with the workplace-location starter rule.
- Provenance, trust ceilings, and calibration.
- Capability federation (reference, don't own) with graceful degradation.
- Asymmetric forgetting (criticality floor + fidelity ladder + unlearning).
- Health auditor + consistency sweep + bounded self-repair.
- Bounded learning loop (champion/challenger, capped deltas).
- Reasoning layer (procedures, reflections, plan_context) + user epistemic model.
- Git mirror flush + disk recovery.
- Two Hermes plugin adapters (memory-provider + context-engine slots) sharing one
  core; memory-aware compression that evicts only durable spans.

### Tests
- Property/acceptance suite P1–P21 + worked examples B.1–B.6 (38 tests).

### Deferred (per spec)
- Distributed CRDT tier, L3 parametric adapters, and TLA⁺ models.
- Extraction and read-and-answer use a deterministic offline heuristic behind a
  pluggable interface; a local model drops in without other changes.
