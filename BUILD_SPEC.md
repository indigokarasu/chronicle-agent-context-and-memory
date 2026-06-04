# Chronicle Memory System — Build Specification

> **Status:** Final; ready for implementation.
> **Audience:** Engineers building Chronicle. Self-contained; assumes working knowledge of SQL,
> embeddings, and basic information retrieval. Read Part I for the mental model before the schemas.
> **How to read this:** Part I orients (overview → architecture → concepts → the invariant
> contract). Parts II–VI are the build, in implementation order. Cross-references use this
> document's own section numbers.

---

## Table of contents

**Part I — Orientation**
1. Overview · 2. Architecture · 3. Concepts & terminology · 4. Invariants (the contract)

**Part II — Data plane**
5. Serialization & content addressing · 6. Event log · 7. Projection (the reducer) · 8. Belief store schema ·
9. Truth maintenance & derivation · 10. Provenance, trust, calibration

**Part III — Capture, integration & access**
11. Hermes plugins & shared core · 12. Capture policy (hooks → durable events) · 13. Context Engine (working memory) ·
14. Sources & capability federation · 15. Access control & multi-agent

**Part IV — Processing**
16. Extraction · 17. Curation pipeline · 18. Retrieval (dual-tier + read) · 19. User epistemic model ·
20. Forgetting & compaction · 21. Health & self-healing · 22. Learning loop (bounded) · 23. Reasoning layer

**Part V — Platform**
24. Storage abstraction & tiering · 25. Concurrency & consistency · 26. Git mirror & recovery

**Part VI — Delivery**
27. Configuration reference · 28. Observability · 29. Formal verification · 30. Migration ·
31. Implementation phases & acceptance · 32. Error codes · 33. Worked examples

---

# Part I — Orientation

## 1. Overview

### 1.1 What Chronicle is
A local-first, crash-safe, self-improving, multi-agent **memory system** for the Hermes Agent. It
captures conversation and tool activity, turns it into structured **beliefs**, retrieves them (with a
fallback that reads raw history when needed), revises and infers over them, and improves its own
retrieval/curation policies from observed outcomes.

### 1.2 Shape: two plugins, one core
Chronicle ships as **two Hermes plugins over one shared in-process core** (`ChronicleCore`):
- a **Memory Provider** (Hermes memory-provider slot) — long-term memory: capture + recall;
- a **Context Engine** (Hermes context-engine slot) — working memory: owns the live context window.
They occupy separate single-select Hermes slots but share all state through `ChronicleCore`, so
together they form a multiplier (§13.4). Either runs without the other.

### 1.3 What it owns vs references
Chronicle **owns beliefs** and nothing else. Data another component authoritatively owns — contacts
(Weave), preferences (Taste), or anything an MCP/skill/plugin claims via "use me for X" — is
**referenced through dynamic pointers, never duplicated** (§14, I20).

### 1.4 Non-goals
Not a general-purpose database. The agent's reasoning loop is out of scope (§23 is memory-facing
support). Base-model training is out of scope (producing datasets/adapters, §20.4, is in scope).
Chronicle never eagerly computes full transitive inference closure (§9.4). Distributed operation is
specified (§24.5) but optional; the primary build is single-node.

### 1.5 Priority order (use to resolve design trade-offs)
1. Correctness & auditability — every belief traces to immutable evidence.
2. Recoverability — authoritative state rebuildable from an append-only log; crash-safe.
3. Right capture — remember the right things, durably, under hook constraints.
4. Recall — no unrecoverable miss (raw-tier fallback).
5. Sound, scoped inference.
6. Bounded self-improvement.
7. Performance, then everything else.

---

## 2. Architecture

Read this section for the mental model; later sections fill in each box.

### 2.1 The spine: event-sourced core
Everything written is an **immutable, content-addressed event** appended to a local log (§6). A pure
**reducer** (§7) folds the log into a **belief store** — the queryable projection (§8). The belief
store is disposable: drop it and rebuild it from the log and you get the identical state (I3). This
gives auditability (every belief traces to events), recoverability (rebuild from the log/git mirror),
and reproducibility (replay extraction/derivation with a better model).

### 2.2 Two layers of memory, two-tier retrieval
- The **raw layer** = the durable `observed` events and session transcripts — ground truth.
- The **belief layer** = interpreted, structured beliefs (facts/episodes/notes/…) — the fast tier.

Retrieval (§18) is **dual-tier**: Tier 1 hits the belief layer; when that's insufficient, Tier 2
retrieves raw spans and a **read step** answers from them (and writes the belief back). Because raw is
always durable, a missed extraction is never an unrecoverable miss (I23). Eager extraction (§16) is a
speed/precision optimization, not the recall mechanism.

### 2.3 Capture is cheap and durable; understanding is deferred
Hermes hooks drive capture (§12). `sync_turn` appends a durable `observed` event and returns
immediately (no network) — that is the durability anchor (I12). Heavy work (extraction, curation,
inference) runs in the background. Because hooks are unreliable (a session may end via crash, idle
reaping, or a gateway bug — never via a clean `on_session_end`), a **reaper** (§12.4) finalizes stale
sessions independently, making the system crash-only (I13).

### 2.4 Working memory = the Context Engine
The Context Engine (§13) replaces Hermes's compressor and owns the live window. It compresses
**memory-aware**: it can evict spans it knows are durable (recoverable by retrieval) and re-inject
relevant long-term memory toward the current topic. The durability anchor (I12) is what makes
aggressive eviction lossless (I17). Directives (always/never rules) are never evicted.

### 2.5 Beliefs, revision, and inference
Beliefs carry provenance, calibrated confidence, lifecycle state, and justifications. A
truth-maintenance system (§9) makes revision complete: retract a premise and everything depending on
it is recomputed. A **guarded derivation layer** (§9.4) produces *scoped, defeasible* compositional
inferences (it concludes "your office is downtown," never the over-broad "the company is downtown").

### 2.6 Federation and multi-agent
External authoritative stores are referenced, not copied, through a runtime **capability registry**
(§14): anything declaring "use me for X" becomes capability X's source of record. Each agent is a
**principal** with its own partition; within a user, agents read each other's and the user's memory by
default, with explicit user-set restrictions (§15). Cross-principal reads return references, never
copies — the same no-duplication rule as federation.

### 2.7 Self-improvement, bounded
A learning loop (§22) attributes outcomes back to retrievals and tunes policy via champion/challenger,
within hard bounds (capped active deltas, whitelisted dimensions) so the system can't drift.

### 2.8 Diagram
```
            Hermes hooks ─► Memory Provider ─┐                 ┌─ Context Engine ◄─ Hermes
              (§12)                          ▼                 ▼     (§13, working memory)
   ┌───────────────────────── ChronicleCore (§11) ─────────────────────────┐
   │  EVENT LOG ──reduce(§7)──► BELIEF STORE ──┐                            │
   │  (immutable,     │                         │ retrieval §18 (dual-tier) │
   │   content-addr   │  TMS + DERIVATION §9     │   tier1 beliefs           │──► answer
   │   §6; raw layer) │                         │   tier2 raw + read (I23)  │   (+ promote-on-read)
   │      │ git mirror §26      ACCESS CONTROL §15 (ACL filter every read)  │
   │      ▼                                     │                            │
   │  GIT MIRROR        CAPABILITY FEDERATION §14 ──► Weave·Taste·MCP("use me for X")  [reference, not own]
   └──────────────────────────────────────────────────────────────────────┘
   background: REAPER §12.4 · EXTRACTION §16 · CURATION §17 · SELF-HEAL §21 · LEARNING §22 · REASONING §23
```

---

## 3. Concepts & terminology

Defined before first use to keep the rest unambiguous.

| Term | Definition |
|------|------------|
| **Event** | An immutable, content-addressed record appended to the log (§6). The unit of truth. |
| **Belief** | A derived statement materialized from events (§8): a fact, episode, note, reference, relationship, entity, procedure, user-knowledge item, or **derived** (inferred) belief. Mutable, disposable. |
| **Observed (raw) layer** | The durable `observed` events + session transcripts; ground truth; indexed for Tier-2 retrieval (§8.6). |
| **Belief layer** | The interpreted structured beliefs; the Tier-1 retrieval surface. |
| **Reducer / Projection** | The pure function `(events) → beliefs` / its materialized output (§7). |
| **memory `domain`** | A belief's lifecycle class: **`user` \| `agent` \| `general`** (governs decay & contradiction policy, §8.4). *Distinct from* a capability (below). |
| **Capability** | A data area a **CapabilityProvider** authoritatively owns (`contacts`, `calendar`, `preferences`, …), claimed at runtime via "use me for X" (§14). Chronicle references it, never owns it. |
| **Principal** | A **user** or an **agent**; the unit of memory ownership and access (§15). Hermes supplies a principal's *identity*, never its *sensitivity*. |
| **Owner / read_acl** | The principal that owns a belief / its per-belief read policy (default `user_agents`, §15). |
| **Pointer (`external_ref`/`pointers`)** | A reference into a capability provider (or sibling principal); stored with an optional thin TTL cache, never the dataset (I20/I21). |
| **Salience** | Write-time priority hint: `pinned \| high \| normal \| incidental` (drives context selection & decay). |
| **Criticality** | Cost-of-forgetting tier: `normal \| high \| critical` (drives retention; §20). |
| **Trust level** | Integer rank of a source (0–4); caps a belief's confidence (§10). |
| **Calibration** | Map from raw confidence to empirically-correct probability (§10.5). |
| **Directive** | An always/never rule; a high-criticality norm that is always in context and never evicted (§13). |
| **Derived belief** | A conclusion from a guarded derivation rule (§9.4): `source_type=inference`, scoped, defeasible, ≤ inference trust ceiling. |
| **Eager extraction** | Background `observed → asserted` (§16); a speed/precision optimization, not the recall mechanism (I23). |
| **Read-and-answer** | Query-time retrieval over raw spans + a model read that answers and emits beliefs (§18.4). |

---

## 4. Invariants (the contract)

These MUST hold; §31 maps acceptance tests to each. (Terms are defined in §3.)

- **I1 Append-only.** `events` rows are never updated or deleted; corrections are new events.
- **I2 Identity = content.** `event_id` hashes canonical content (§5); identical events store once.
- **I3 Derived beliefs.** The belief store holds nothing not derivable from the log; drop + rebuild yields the identical state.
- **I4 Bitemporal monotonicity.** `recorded_at` is non-decreasing in event order; `occurred_at` is arbitrary.
- **I5 Justified beliefs.** Every active belief has ≥1 justification; an unjustified belief is retracted.
- **I6 Trust ceiling.** `confidence ≤ C(trust_level)` without independent corroboration.
- **I7 Durable enqueue.** A belief, its git-mirror entry, and its triggered curation jobs commit in one transaction.
- **I8 Calibrated surface.** Confidence returned to the agent is the calibrated value.
- **I9 Extraction reproducibility.** Belief state is reproducible from `observed` events at a pinned `extractor_version`.
- **I10 Asymmetric retention.** No `high`/`critical` belief is lost to passive decay (only explicit forget/consent-withdrawal).
- **I11 Purpose confinement.** No belief is returned for a purpose outside its `purpose_scope`, nor after consent withdrawal/expiry.
- **I12 Capture durability.** Content passed to `sync_turn` is a durable `observed` event before the call returns.
- **I13 Trigger independence.** A session's observed events are fully extracted regardless of whether `on_session_end`/`on_pre_compress` fire (reaper + startup recovery).
- **I14 Rescue before loss.** When the active compression path returns, every high-criticality span in the discarded window is a durable belief.
- **I16 Branch isolation.** Observed events after a rewind point are never promoted to active belief.
- **I17 Non-lossy eviction.** The Context Engine evicts a span only if it is (or is first made) a durable event.
- **I18 Source independence.** Functional on Hermes hooks alone; absence of any source/capability/sibling changes no invariant.
- **I19 Bounded learning.** Active learned policy deltas are capped in count/magnitude; self-tuning touches only whitelisted dimensions.
- **I20 Reference, don't own (capabilities).** A capability claimed by a provider is referenced + thin-cached, never stored as authoritative; degrades when the provider is unavailable.
- **I21 Reference, don't copy (principals).** Cross-principal access is by reference only; a principal never persists another's belief.
- **I22 Scoped default-allow.** Within one user, reads among that user's agents are allowed by default; denied only by an explicit user-set restriction; cross-user never; nothing inferred from Hermes.
- **I23 Recall floor.** A fact present in a durable `observed` event is answerable at query time even if eager extraction missed it (raw tier + read).
- **I24 Guarded, scoped, defeasible derivation.** A derived belief fires only when its entity/cardinality/temporal guards hold; is scoped via reification (no over-generalization); has `confidence ≤ C(inference)` and is hedged; is retracted by the TMS when any premise is; and the system never eagerly materializes full transitive closure.

*(I15 intentionally retired during consolidation; numbering preserved for stable references.)*

---

# Part II — Data plane

## 5. Serialization & content addressing

Content addressing (dedup, tamper-evidence, idempotency) requires byte-deterministic serialization.
**Normative.**

**5.1 Canonical JSON (CJSON).** UTF-8, no BOM; object keys sorted by Unicode code point, no
duplicates; no insignificant whitespace; only mandatory string escapes, non-ASCII emitted as raw
UTF-8; integers decimal (no leading zeros, no `+`, no `-0`); **non-integer numbers are forbidden in
hashed content** (encode reals as fixed-scale decimal strings per field); booleans/null literal; array
order preserved.

**5.2 Hash.** `hash(bytes) = BLAKE3-256`, lowercase hex (64 chars).

**5.3 Ids.**
```
event_id  = "ev_" + hash(CJSON({type, payload, parents(sorted), actor, occurred_at}))
belief_id = "b_"  + hash(CJSON({kind, key(§8.2), supports(sorted justifying event_ids)}))
```
`recorded_at`, `seq`/`order_key`, `prev_head`, `sig` are assigned at append and **excluded** from hashes.

**5.4 Timestamps.** RFC3339, UTC, millisecond precision, `Z` suffix. Other forms rejected in hashed content.

---

## 6. Event log

**6.1 Schema.**
```sql
CREATE TABLE events (
    event_id    TEXT PRIMARY KEY,             -- §5.3
    seq         INTEGER NOT NULL UNIQUE,        -- local monotonic order (single node)
    order_key   TEXT,                           -- distributed total order (§24.5); NULL single-node
    type        TEXT NOT NULL,                  -- §6.2
    payload     TEXT NOT NULL,                  -- CJSON
    parents     TEXT NOT NULL DEFAULT '[]',     -- CJSON array of event_ids (causal DAG)
    actor       TEXT NOT NULL CHECK(actor IN ('user','agent','curator','system')),
    owner       TEXT NOT NULL,                  -- writing principal (§15)
    trust_level INTEGER NOT NULL,
    session_id  TEXT,
    branch_id   TEXT,                            -- = session_id unless rewound (§12.5)
    occurred_at TEXT NOT NULL,                   -- valid time
    recorded_at TEXT NOT NULL,                   -- transaction time
    prev_head   TEXT,                            -- hash chain
    sig         TEXT
);
CREATE INDEX idx_events_seq      ON events(seq);
CREATE INDEX idx_events_recorded ON events(recorded_at);
CREATE INDEX idx_events_type     ON events(type, seq);
CREATE INDEX idx_events_session  ON events(session_id, seq);
```

**6.2 Event types & required payload fields.**
| type | payload (required) |
|------|--------------------|
| `observed` | `source_type`, `excerpt`, `source_ref`, `document_id?` |
| `asserted` | `kind`, `key`, `body`, `confidence`, `source_event`, `extractor_version?` |
| `confirmed` | `belief_id`, `source_event` |
| `contradicted` | `belief_id`, `conflicting_event`, `detail` |
| `corrected` | `belief_id`, `reason`, `new_body?`, `source_ref?` |
| `retracted` | `belief_id`, `reason` |
| `forbidden` | `content_hash`, `scope` |
| `merged` / `unmerged` | `from_entity`, `into_entity`, `evidence` |
| `decayed` | `belief_id`, `from_fidelity`, `to_fidelity` |
| `rehearsed` / `verified` | `belief_id` (+ `status,method` for verified) |
| `informed` | `proposition`, `about_belief?`, `session_ref` (§19) |
| `compressed` | `session_id`, `evicted_spans`, `retained`, `summary_ref` (§13) |
| `signal` | `signal_type`, `body`, `source_event` (§16.2) |
| `derived` | `kind`, `key`, `body`, `rule_id`, `premises`, `confidence` (§9.4) |
| `grant` / `revoke` | `belief_id|scope`, `principal|group` (§15) |
| `distilled` | `cluster`, `adapter_ref` (deferred, §20.4) |

`kind ∈ fact | episode | note | reference | relationship | entity | user_knowledge | procedure`.

**6.3 Append (the only write entrypoint).**
```
append_event(type, payload, *, parents=[], actor, owner, occurred_at, trust_level, session_id=None):
  1. validate payload against the type schema               -> E_SCHEMA
  2. event_id = §5.3
  3. if event_id exists: return it (idempotent, I2)
  4. assign seq (and order_key §24.5), recorded_at=now, prev_head=current head
  5. INSERT event; update head pointer
  6. within the SAME transaction: incremental reduce (§7) + git_queue row + triggered curation jobs   (I7)
  7. COMMIT; return event_id
```

---

## 7. Projection (the reducer)

**7.1 Watermark.** `meta.projection_seq` = highest `seq` applied. Incremental projection applies
`(projection_seq, head]` in order.

**7.2 Reducer.** Pure; **no clock, network, or RNG**; ties break by event order (`seq`/`order_key`),
never wall clock or hash.
```
reduce(state, e):
  observed     -> persist raw + index it (§8.6); enqueue extract (§16). No belief.
  asserted     -> upsert belief(kind,key); set body/confidence/qualifiers; add justification;
                  apply fact conflict policy (§8.5); classify criticality (§20.1); set owner/read_acl (§15.2)
  confirmed    -> confirm_count++; last_confirmed_at; recompute confidence (§10.4); add justification
  contradicted -> open a contradiction record; apply memory-domain policy (§8.4)
  corrected    -> new_body ? supersede : retract; revision cascade (§9.3)
  retracted    -> status=retracted; drop justifications; cascade (§9.3)
  forbidden    -> tombstone(content_hash); delete matches incl. raw index; flag unlearning (§20.5)
  merged       -> union-find add; merged_into derived; recompute counts
  unmerged     -> union-find remove; split class; re-home facts (§17)
  decayed      -> fidelity transition (§20)
  rehearsed    -> last_seen_at=now
  verified     -> verification = {status, method, at}
  informed     -> upsert user_knowledge (§19)
  signal       -> route the typed learning signal (§16.2)
  derived      -> upsert derived belief; justifications = premises + rule_id (§9.4)
  grant/revoke -> update read_acl
  compressed   -> audit only (beliefs already durable, §13)
```

**7.3 Rebuild.** `rebuild(from_seq=0, as_of_recorded=None, reextract=False, rederive=False)`: truncate
the projection; replay events in order (optionally filtered by `recorded_at ≤ as_of_recorded`);
optionally re-run extraction (§16) and/or derivation (§9.4) at current versions; rebuild FTS + raw
index; enqueue re-embedding; set `projection_seq`. Snapshot+delta optional for large logs.

**7.4 Bitemporal queries.** As-known-at `T`: replay events `recorded_at ≤ T`. As-true-at `S`: filter
`valid_from ≤ S < valid_until`. Combined `as_of(world=S, knowledge=T)`: both.

---

## 8. Belief store schema

The read model. Every row is derived (I3).

**8.1 Common envelope** (present on every belief table):
```
belief_id, domain, owner, read_acl, status, salience, criticality, criticality_reason,
confidence, trust_level, valid_from, valid_until, superseded_by, created_at, last_seen_at,
fidelity, utility, purpose_scope, consent, provenance, verification
-- domain      ∈ user|agent|general            (memory domain, §3)
-- status      ∈ draft|active|superseded|expired|retracted|forbidden
-- salience    ∈ pinned|high|normal|incidental
-- criticality ∈ normal|high|critical
-- fidelity    ∈ verbatim|gist|parametric_only|tombstone
-- read_acl    default 'user_agents' (§15)
```

**8.2 Natural keys (for `belief_id`, §5.3):**
| kind | key |
|------|-----|
| fact | `{entity_id, predicate_canonical, qualifiers_hash, owner, domain}` |
| episode | `{title, occurred_at, owner, domain}` |
| note | `{note_type, subject, body_hash, owner, domain}` |
| reference | `{topic, owner, domain}` |
| relationship | `{source_id, predicate, target_id, owner, domain}` |
| entity | `{type, normalized_name, owner, domain}` (or `external_ref` when federated, §14) |
| user_knowledge | `{proposition_hash, owner, domain}` |
| procedure | `{name, owner, domain}` |

**8.3 Tables.**
```sql
CREATE TABLE principals (                       -- §15
    principal_id TEXT PRIMARY KEY, type TEXT CHECK(type IN ('user','agent')), display TEXT,
    default_visibility TEXT CHECK(default_visibility IN ('shared','private')) DEFAULT 'shared',
    key_ref TEXT, created_at TEXT );

CREATE TABLE entities (
    belief_id TEXT PRIMARY KEY, type TEXT, name TEXT, normalized_name TEXT, aliases TEXT DEFAULT '[]',
    domain TEXT, owner TEXT, read_acl TEXT, merged_into TEXT,
    external_ref TEXT, external_provider TEXT, cache_ttl TEXT,      -- federation pointer (§14, I20)
    fact_count INTEGER DEFAULT 0, relationship_count INTEGER DEFAULT 0, created_at TEXT, last_seen_at TEXT );
CREATE INDEX idx_entities_name  ON entities(domain, normalized_name);
CREATE INDEX idx_entities_owner ON entities(owner);
CREATE INDEX idx_entities_ext   ON entities(external_provider, external_ref);

CREATE TABLE pointers (                          -- generic capability pointer (non-entity data)
    id TEXT PRIMARY KEY, capability TEXT, provider TEXT, external_id TEXT,
    cached_projection TEXT, cache_ttl TEXT, created_at TEXT, UNIQUE(capability, provider, external_id) );

CREATE TABLE facts (
    belief_id TEXT PRIMARY KEY, entity_id TEXT NOT NULL,
    attribute TEXT NOT NULL, predicate_canonical TEXT,
    value TEXT NOT NULL, value_type TEXT DEFAULT 'string', value_num REAL, value_ts TEXT,
    qualifiers TEXT NOT NULL DEFAULT '{}', qualifiers_hash TEXT NOT NULL DEFAULT '',
    pointer_id TEXT, confirm_count INTEGER DEFAULT 0, last_confirmed_at TEXT, extractor_version TEXT,
    -- envelope:
    domain TEXT, owner TEXT, read_acl TEXT, status TEXT DEFAULT 'active', salience TEXT DEFAULT 'normal',
    criticality TEXT DEFAULT 'normal', criticality_reason TEXT, confidence REAL DEFAULT 0.8 CHECK(confidence BETWEEN 0 AND 1),
    trust_level INTEGER, valid_from TEXT, valid_until TEXT, superseded_by TEXT,
    created_at TEXT, last_seen_at TEXT, fidelity TEXT DEFAULT 'verbatim', utility REAL DEFAULT 0,
    purpose_scope TEXT NOT NULL DEFAULT '["*"]', consent TEXT,
    provenance TEXT NOT NULL, verification TEXT DEFAULT '{"status":"unverified"}',
    source_type  TEXT GENERATED ALWAYS AS (json_extract(provenance,'$.source_type')) VIRTUAL,
    verif_status TEXT GENERATED ALWAYS AS (json_extract(verification,'$.status')) VIRTUAL );
CREATE INDEX idx_facts_active     ON facts(entity_id, predicate_canonical) WHERE status='active';
CREATE INDEX idx_facts_owner      ON facts(owner, domain);
CREATE INDEX idx_facts_crit       ON facts(criticality) WHERE criticality!='normal';
CREATE INDEX idx_facts_unverified ON facts(verif_status) WHERE verif_status='unverified';
CREATE INDEX idx_facts_valnum     ON facts(entity_id, predicate_canonical, value_num) WHERE value_num IS NOT NULL;

CREATE TABLE episodes (
    belief_id TEXT PRIMARY KEY, title TEXT, summary TEXT, participants TEXT DEFAULT '[]',
    occurred_at TEXT, session_ref TEXT, derived_facts TEXT DEFAULT '[]', pointer_id TEXT,
    domain TEXT, owner TEXT, read_acl TEXT, status TEXT, salience TEXT, criticality TEXT DEFAULT 'normal',
    confidence REAL, trust_level INTEGER, valid_from TEXT, valid_until TEXT, created_at TEXT, last_seen_at TEXT,
    fidelity TEXT, utility REAL DEFAULT 0, purpose_scope TEXT DEFAULT '["*"]', consent TEXT, provenance TEXT );
CREATE INDEX idx_episodes_time ON episodes(occurred_at);

CREATE TABLE notes (
    belief_id TEXT PRIMARY KEY, note_type TEXT CHECK(note_type IN ('procedure','norm','belief')),
    subject TEXT, body TEXT, body_hash TEXT,
    imperative INTEGER DEFAULT 0,            -- 1 = directive (always/never rule)
    always_inject INTEGER DEFAULT 0,         -- 1 = never evict from context (§13)
    risk_tier TEXT DEFAULT 'low' CHECK(risk_tier IN ('low','high')),   -- §16.4
    domain TEXT, owner TEXT, read_acl TEXT, status TEXT, salience TEXT, criticality TEXT DEFAULT 'normal',
    confidence REAL, trust_level INTEGER, valid_from TEXT, valid_until TEXT, created_at TEXT, last_seen_at TEXT,
    fidelity TEXT, utility REAL DEFAULT 0, purpose_scope TEXT DEFAULT '["*"]', consent TEXT, provenance TEXT );
CREATE INDEX idx_notes_directive ON notes(always_inject) WHERE always_inject=1;

CREATE TABLE refs (
    belief_id TEXT PRIMARY KEY, topic TEXT, retrieval_url TEXT, retrieved_at TEXT,
    ttl_days INTEGER DEFAULT 30, cached_summary TEXT, stale_after TEXT,
    domain TEXT, owner TEXT, read_acl TEXT, status TEXT, trust_level INTEGER, created_at TEXT,
    purpose_scope TEXT DEFAULT '["*"]', consent TEXT, provenance TEXT );
CREATE INDEX idx_refs_stale ON refs(stale_after);

CREATE TABLE relationships (                     -- knowledge relations; person↔person social federates to a contacts provider
    belief_id TEXT PRIMARY KEY, source_id TEXT, predicate TEXT, target_id TEXT, external_ref TEXT,
    domain TEXT, owner TEXT, read_acl TEXT, status TEXT, confidence REAL, trust_level INTEGER,
    valid_from TEXT, valid_until TEXT, created_at TEXT, provenance TEXT );
CREATE INDEX idx_rel_source ON relationships(source_id) WHERE status='active';
CREATE INDEX idx_rel_target ON relationships(target_id) WHERE status='active';

CREATE TABLE procedures (                        -- named, parameterized procedures (§23)
    belief_id TEXT PRIMARY KEY, name TEXT, params TEXT, steps TEXT, success_criteria TEXT,
    derived_from TEXT DEFAULT '[]',
    domain TEXT, owner TEXT, read_acl TEXT, status TEXT, confidence REAL, trust_level INTEGER,
    created_at TEXT, last_seen_at TEXT, purpose_scope TEXT DEFAULT '["*"]', consent TEXT, provenance TEXT );

CREATE TABLE predicates ( surface TEXT PRIMARY KEY, canonical TEXT NOT NULL,
    cardinality TEXT NOT NULL DEFAULT 'single' CHECK(cardinality IN ('single','multi')), confidence REAL, created_at TEXT );
CREATE TABLE documents  ( id TEXT PRIMARY KEY, type TEXT, created_at TEXT, agent TEXT, abstract TEXT, file_path TEXT );
CREATE TABLE tombstones ( content_hash TEXT PRIMARY KEY, scope TEXT, created_at TEXT );

-- FTS5 mirrors over facts(value,attribute), episodes(title,summary), notes(body) via insert/delete/update
-- triggers; rebuilt during §7.3. Every retrieval view applies the ACL filter (§15.3).
```
Derived (inferred) beliefs are ordinary `facts`/`relationships` rows with `source_type=inference` and
`provenance.rule_id`/`provenance.premises` (§9.4).

**8.4 Lifecycle & memory-domain policy.**
`draft → active → {superseded | expired | retracted | forbidden}`; transitions only via the reducer.
Per-domain decay/contradiction policy:
| domain | auto-decay | contradiction |
|---|---|---|
| user | never | flag for review |
| agent | 90d stale | newer wins |
| general | 30d stale (per-source TTL) | re-fetch |

**8.5 Fact conflict policy** (new `asserted` for an active `(entity_id, predicate_canonical, overlapping qualifiers, domain)`):
| condition | action |
|---|---|
| value equal | no new row; `confirm_count++`; raise confidence (§10.4) |
| differs, new conf ≥ old, user domain | supersede old (`valid_until=now, superseded_by`); new active |
| differs, new conf < old, user domain | new belief `status=draft`; open contradiction |
| differs, agent domain | newer wins: supersede |
| general domain | not stored as fact; refresh `refs` |
Facts with **non-overlapping** time/context qualifiers do not conflict (both true).

**8.6 Raw-content index (enables I23).**
```sql
CREATE VIRTUAL TABLE observed_fts USING fts5(excerpt, content='', contentless_delete=1);  -- keyed by event_id
CREATE TABLE observed_vectors ( event_id TEXT PRIMARY KEY, embedding BLOB, model TEXT, owner TEXT, created_at TEXT );
CREATE TABLE session_index    ( session_id TEXT PRIMARY KEY, summary TEXT, embedding BLOB, owner TEXT, occurred_at TEXT );
```
The reducer indexes each `observed` excerpt (FTS + vector) on append; a cold task writes per-session
summaries. Raw-index rows carry the owning principal and are ACL-filtered identically (§15).

---

## 9. Truth maintenance & derivation

**9.1 Tables.**
```sql
CREATE TABLE justifications ( belief_id TEXT, support TEXT, support_kind TEXT CHECK(support_kind IN ('event','belief','assumption')),
    rule TEXT, PRIMARY KEY(belief_id, support, rule) );
CREATE INDEX idx_just_support ON justifications(support);
CREATE TABLE nogoods ( nogood_id TEXT PRIMARY KEY, assumptions TEXT );     -- resolved inconsistent assumption sets
CREATE TABLE corrections ( id TEXT PRIMARY KEY, belief_id TEXT, reason TEXT, correction_ref TEXT,
    propagated TEXT DEFAULT '[]', created_at TEXT );
CREATE TABLE derivation_rules ( rule_id TEXT PRIMARY KEY, name TEXT, enabled INTEGER DEFAULT 1,
    pattern TEXT NOT NULL, guards TEXT NOT NULL, conclusion TEXT NOT NULL, scope TEXT NOT NULL,
    materialize TEXT DEFAULT 'high_value' );    -- always | high_value | never(read-only)
```

**9.2 Justification.** Every belief records its supports (events/beliefs/assumptions + the rule that
introduced it). Derived beliefs depend on their premises, so revision cascades reach them (9.3, I24d).

**9.3 Revision cascade** (on `corrected`/`retracted`):
```
revise(belief_id):
  mark retracted/superseded
  for each d where justifications.support = belief_id:
     if d's remaining supports still satisfy its rule: keep
     else: revise(d)                       # complete transitive cascade (I5)
  record correction(propagated=[…]); adjust the originating source's trust prior (§10.5)
```

**9.4 Derivation (guarded compositional inference).** Chronicle derives beliefs via a small set of
**guarded join rules**, never eager transitive closure.
- **Guards (a rule fires for a binding only if all hold):** **(1) entity-grounded** — premises are
  resolved entities/reified nodes, not raw strings; **(2) cardinality** — required predicates are
  single-valued for the subject (`predicates.cardinality`), else not asserted (optionally flagged);
  **(3) temporal overlap** — premises' validity windows & qualifiers intersect; **(4) ACL/domain** —
  premises share a scope readable by the active principal.
- **Conclusion:** emitted as a `derived` event → a belief **bound to the reified `scope` node** (so it
  states "*the user's workplace* is in L," never "*the org* is in L," I24b), `source_type=inference`,
  `confidence = aggregate(premise confidences)` (default `min × rule_factor`) clamped to
  `C(inference)=0.75`, `status=draft` (user domain → review) or `active` (agent domain) per
  `behavior_change` risk, `justifications = premises + rule_id` (defeasible via 9.3).
- **Execution:** the `derive` curation task (§17) materializes `materialize=high_value` rules during
  consolidation, bounded by `max_depth`/`max_fanout` (never full closure, I24e); the read step (§18.4)
  applies enabled rules to the retrieved subgraph so query-time composition is consistent and
  explainable.
- **Safety:** derivations are auditable (`explain(belief_id)`); unsound ones are caught by the
  consistency sweep → `nogoods` and the rule is penalized/disabled (§21, §22). Rules beyond a vetted
  starter set ship disabled; the set is user/operator-editable.

---

## 10. Provenance, trust, calibration

**10.1 Provenance** mirrors the supporting events (`source_type, source_ref, excerpt, extracted_by,
extracted_at`); always reproducible from justifications + events.

**10.2 Sources.** `sources(source_id, source_type, trust_level, info_label)`; `info_label ∈
public|private|secret`.

**10.3 Trust ceiling `C(level)`** (no corroboration): `0→0.40, 1→0.60, 2→0.75 (inference), 3→0.90,
4→1.00`. Belief trust = min over its provenance chain; independent corroboration (a `confirmed`/
`asserted` from a different source of ≥ trust) raises the ceiling one band.

**10.4 Confidence.** `raw = base(source_type) + 0.05·min(confirm_count,5) − 0.10·contradiction_count`,
clamped to `C(effective_trust)` (I6). Surfaced to the agent as the calibrated
`confidence_summary = {score: calibrate(raw, source_type), sources, user_confirmed, ever_contradicted,
last_confirmed_at, staleness_days}` (I8).

**10.5 Calibration.** `calibration_obs(source_type, predicted_bucket, n, correct)`; `calibrate` =
isotonic regression per source_type (identity until `min_obs`), refit by the learning loop (§22). A
source whose top-bucket empirical correctness falls below threshold has its trust prior decremented.

---

# Part III — Capture, integration & access

## 11. Hermes plugins & shared core
`ChronicleCore` (log, store, retrieval, scoring, curation, capability registry, principals/ACL) is a
process-singleton keyed by `hermes_home`. Both plugins obtain the same instance at `initialize` and
record their presence (`has_memory_provider` / `has_context_engine`); each queries the other's to pick
its mode (§13.4). `initialize(session_id, *, hermes_home, principal_id)` sets the **active principal**
(the agent's id from Hermes) → writes default `owner = active principal` (or `user` for shared user
facts), reads are ACL-filtered (§15). Cooperation between the plugins is an optimization, never a
correctness dependency.

## 12. Capture policy (hooks → durable events)
Guiding rule: **durability at capture; every hook best-effort; a reaper guarantees the work.**

**12.1 Durability anchor.** `sync_turn(user, assistant, *, session_id, messages)` appends a durable
`observed` event and returns — satisfying the non-blocking/no-network contract (the append is one
local txn; heavy work is enqueued). This is I12, and it underwrites both lossless eviction (I17) and
the recall floor (I23).

**12.2 Sessions table.**
```sql
CREATE TABLE sessions ( session_id TEXT PRIMARY KEY, parent_session_id TEXT, domain TEXT,
    status TEXT CHECK(status IN ('active','idle','ended','reaped')), started_at TEXT, last_activity_at TEXT,
    last_extracted_seq INTEGER NOT NULL DEFAULT 0, branch_point_seq INTEGER, ended_via TEXT, ended_at TEXT );
```

**12.3 Hook → action** (hot = synchronous, bounded, no network; warm = background; cold = sweep):
| Hook | Tier | Action |
|---|---|---|
| `sync_turn` | hot | append `observed`; bump `last_activity_at`; enqueue async extract |
| `on_pre_compress(messages)→str` | hot | rescue-extract critical/high-salience spans → durable `asserted(draft)`; return summary — **but return `""` when the Chronicle Context Engine is active** (it owns this, §13) |
| `on_session_end(messages)` | warm | mark ended; enqueue final extraction + episode + reflection; **idempotent vs reaper** |
| `on_memory_write(action,target,content,meta)` | hot | `asserted`, `salience=high`, `source_type=agent_memory_write`, no confidence discount (highest-precision signal) |
| `on_delegation(task,result,…)` | warm | episode (task→result) + outcome → reflection (§23) |
| `on_turn_start(n,message)` | hot | drain a bounded curation slice; refresh scope; decay tick |
| `on_session_switch(new,*,parent,reset,rewound)` | hot | set scope/domain; `rewound`→`branch_point_seq` (§12.5) |
| `prefetch(query,…)→str` | hot | bounded `get_context`; serve warm cache |
| `queue_prefetch(query,…)` | warm | predictive prefetch; warm semantic cache |
| `system_prompt_block()→str` | hot | directives (always_inject) + pinned/critical + open contradictions + active goals |
| `get_tool_schemas`/`handle_tool_call` | — | expose tools (§ tools list, end of Part IV) |
| `initialize`/`is_available`/`shutdown` | — | lifecycle; `shutdown` flushes best-effort (not relied upon); `is_available` no network |

**12.4 Reaper (guarantees I13).**
```
reaper():   # cfg schedule + at startup
  for s in sessions where status in (active,idle):
     idle = now - s.last_activity_at
     if idle > idle_threshold and s.status='active': s.status='idle'
     if idle > reap_threshold: finalize_session(s, 'reaped')
finalize_session(s, via):
  enqueue extract for observed events of s where seq > s.last_extracted_seq    # idempotent (§16)
  enqueue episode_synthesis + reflection; s.status='ended'|'reaped'; s.ended_via=via; s.ended_at=now
on_startup(): for s where status='active': finalize_session(s,'crash_recovered'); drain curation_jobs; reaper()
```
Every uncovered termination path (gateway reaping, a missing `on_session_end`, SIGKILL, OOM, idle)
leaves observed events past `last_extracted_seq`; the reaper + startup recovery finalize them.

**12.5 Scope, rewind, branching.** `on_session_switch`: `reset`→fresh scope; `rewound`→set
`branch_point_seq`, mark later observed events `branch_abandoned` (extraction skips them, I16; kept for
audit). `parent_session_id` records delegation lineage.

**12.6 Two-speed rescue** (shared by `on_pre_compress` and the engine's `compress`): segment → keep
spans with `rules_criticality ≥ high or quick_salience ≥ high` → `fast_extract` → durable
`asserted(draft, salience=high)` → enqueue full async extract → return summary. Rescue + full collapse
via content addressing (I2). Whoever owns compression calls this before discarding the window (I14).

**12.7 Memory Provider adapter** (skeleton; methods map 1:1 to §12.3):
```python
class ChronicleMemoryProvider(MemoryProvider):
    name = "chronicle"
    def is_available(self): return self.core.local_ok()                       # no network
    def initialize(self, session_id, *, hermes_home, principal_id="default", **kw):
        self.core=ChronicleCore.get(hermes_home); self.core.has_memory_provider=True
        self.core.on_startup_recovery(); self.core.start_sources(); self.core.bind_capabilities()
        self.p=principal_id; self.scope=self.core.open_scope(session_id, principal_id)
    def sync_turn(self,u,a,*,session_id="",messages=None): self.core.capture.observe(self.scope,u,a,messages)
    def on_pre_compress(self,m): return "" if self.core.has_context_engine else self.core.capture.rescue(self.scope,m)[1]
    def on_session_end(self,m): self.core.capture.finalize(self.scope,m,'clean_exit')
    def on_memory_write(self,act,tgt,content,meta=None): self.core.capture.agent_explicit(self.scope,act,tgt,content,meta)
    def on_delegation(self,task,res,*,child_session_id="",**k): self.core.capture.delegation(self.scope,task,res,child_session_id)
    def on_turn_start(self,n,msg,**k): self.core.capture.tick(); self.core.touch(self.scope)
    def on_session_switch(self,new,*,parent_session_id="",reset=False,rewound=False,**k): self.scope=self.core.switch_scope(new,parent_session_id,reset,rewound,self.p)
    def prefetch(self,q,*,session_id=""): return self.core.recall.context(self.p,q,budget=self.core.cfg.prefetch_budget)
    def queue_prefetch(self,q,*,session_id=""): self.core.recall.predict(self.p,q)
    def system_prompt_block(self): return self.core.recall.static_block(self.p)
    def get_tool_schemas(self): return CHRONICLE_TOOL_SCHEMAS
    def handle_tool_call(self,n,args,**k): return self.core.tools.dispatch(self.p,n,args)
    def shutdown(self): self.core.capture.flush_best_effort()                  # not relied upon
```

## 13. Context Engine (working memory)
Replaces Hermes's `ContextCompressor`; owns the live context window — the top memory tier.
- `should_compress(prompt_tokens=None) -> bool`: token threshold OR memory pressure (a critical
  capture needs room) OR focus shift.
- `compress(messages, current_tokens=None, focus_topic=None) -> list`:
  ```
  1. rescue(messages) — durably extract critical/high-salience spans (§12.6, I14)
  2. score each span: keep = w_rel·relevance(focus) + w_rec·recency + w_sal·salience
                            + w_crit·criticality − w_red·redundancy_vs_store
     directives / always_inject spans: keep = +∞ (never evicted)
  3. evict only spans that are durable events (they are — sync_turn; else append first)  (I17)
  4. re-retrieve long-term memory toward focus_topic (ACL/info_label/purpose filtered, §15/§18)
  5. append `compressed` (audit); return assemble(kept, injected) as OpenAI-format messages
  ```
- Memory-aware behaviours: evict-what's-stored (redundancy), keep-what's-unconsolidated, the window as
  a re-retrieved working set, directives never evicted (archive = the event log).
- `update_from_response(usage)` maintains token counters; `on_session_*`/`update_model` map to scope +
  budget; may expose `pin_context`/`drop_context`/`focus` tools.

**13.4 Cooperation modes.** *Both (default/multiplier):* memory-aware non-lossy compression +
re-retrieval; provider `on_pre_compress` returns `""`; shared scoring + one token-budget authority.
*Provider only:* advisory `on_pre_compress`; a foreign compressor owns the window. *Engine only:*
degrades to a competent token+recency+salience compressor (no redundancy/re-retrieval without the
store), still emitting local events so the window is rebuildable.

## 14. Sources & capability federation
Chronicle integrates external data behind adapters; the core schema/hooks/invariants never name a
specific external skill (I18/I20). Three kinds:

**14.1 Input source adapters → produce `observed` events.** `HermesHooks` (always present, §12).
`OCASJournals` (optional): a cold `journal_ingest` task watches configured journal paths; each entry
becomes `observed` (`source_type=ocas_journal`), deduped by content addressing. Chronicle reads
journals, never writes them; self-disables if paths absent.

**14.2 Capability federation (reference, never own; I20).** Any skill/MCP/plugin declaring "use me for
X" becomes **capability X's** source of record.
- **Registry.** `capability_providers: capability → {provider, declared_by, precedence, status ∈
  active|unavailable}`. Discovered at init and on every plugin load/unload and **MCP
  connect/disconnect**, scanning capability declarations from Hermes plugin manifests, MCP server
  instructions, agentskills.io skill descriptions, and config pins. Updated live; pointers stay valid
  across a provider's absence.
- **Interface.** `CapabilityProvider { name; capability; is_available(); resolve(query|ref) -> Record;
  query(params) -> [Record] }`. Weave (`contacts`) and Taste (`preferences`) are ordinary instances.
- **Routing.** When extraction yields data in a claimed capability, Chronicle does **not** own it — it
  creates a pointer (`entities.external_ref` for entity-shaped data, else a `pointers` row) and keeps
  only the genuinely-Chronicle part: the *belief about* it (linked by `pointer_id`). Reads resolve
  from the provider on demand; only a thin TTL cache is kept.
- **Precedence/conflict.** config pin > most-specific > most-recent; a federated detail disagreeing
  with a Chronicle belief surfaces as a contradiction (provider wins for its capability, Chronicle for
  belief), never a silent overwrite. Identity resolution (§17) defers to a bound provider's id.
- **Degradation.** Provider `unavailable` → pointers remain valid, serve cache/stub, re-bind on
  return; with no providers, Chronicle uses internal entity stubs and is fully functional.

**14.3 Output adapters.** Optional OCAS-format signal emission from learning (§22)/health (§21) to a
sink if configured; else internal. Best-effort, never on a hot path.

## 15. Access control & multi-agent

**15.1 Identity vs policy.** Hermes supplies agent **identity** (the active principal) but **no notion
of an agent being sensitive vs general**. Chronicle therefore never infers restriction; access policy
is Chronicle-owned and **user-set**, default-open. A user owns ≥1 agent (each a principal);
cross-*user* isolation is absolute.

**15.2 Ownership & default visibility (allow-by-default).** Every belief has `owner` (principal) +
`read_acl`, **default `user_agents`** — every one of the user's agents may read it. Restriction is
explicit, two ways only: **per-memory** (`visibility: private`/custom acl on the write, or `set_acl`),
or **per-agent default** the user sets (`set_agent_privacy(agent, private)` / config
`default_visibility: private`). The user always reads all their own data.

**15.3 Access rule (default-allow within a user, I22).** Agent P (of user U) may read belief B iff B
belongs to U **and** B is not explicitly restricted from P — i.e. `read_acl=user_agents` (default) ∨
`owner==P` ∨ explicit `allow[P]` — and no explicit `deny[P]`/owner-only mark excludes P. Else
`E_ACCESS_DENIED` (only for explicitly-restricted memory). Enforced on **every** read/retrieval/
context/reasoning/learning path; writes set `owner=active principal` (contributing agent in
provenance). `grant`/`revoke` events change `read_acl`.

**15.4 Cross-agent read = reference, never copy (I21).** A permitted cross-principal read returns the
belief by reference; the reader records a `cross_ref` pointer (one source of truth; corrections
propagate). Mechanically this reuses §14 federation — each agent's memory is a read authority to
siblings, ACL-gated.

**15.5 Restricted memory & optional isolation.** A user-marked-private agent or memory is owner-only,
unexposed to siblings, and **may** be encrypted under a separate `key_ref` (defense-in-depth: siblings
can't read the bytes even if ACL were bypassed). Entirely opt-in; the user may still read/grant.

**15.6 Other security.** Per-domain (+ per-principal for restricted partitions) encryption at rest;
IFC via `info_label` (min over chain) enforced on retrieval, engine re-injection, federated calls, and
cross-agent reads; purpose/consent (I11) on read with withdrawal → unlearning (§20.5); poisoning
defenses (trust ceiling, quarantine of untrusted+unverified, curation sanity bounds, trust decrement).

**15.7 Deployment shapes (same access model).** *Shared multi-principal core* (default): one Chronicle
per user; partitions by `owner`; ACL at query time; cross-agent read = local ACL'd query (no copy).
*Per-agent isolated cores:* each agent its own Chronicle; cross-agent read via federation; restricted
cores independently encrypted/unfederated. I21/I22 hold in both.

---

# Part IV — Processing

## 16. Extraction (recall-oriented, versioned, replayable; I9)
Tuned for recall and common-case speed — the raw tier (§18) covers the tail, so extraction need not
anticipate every future question.
```sql
CREATE TABLE extractions ( id TEXT PRIMARY KEY, observed_event TEXT, extractor_version TEXT,
    produced TEXT, ambiguous INTEGER DEFAULT 0, route TEXT, created_at TEXT,
    UNIQUE(observed_event, extractor_version) );          -- idempotent; replay = re-run at a new version
```
- **16.0 Multi-granularity, over-extract not skip.** Emit atomic facts, entities, and per-session
  summaries; over-extract (content-addressing dedups). `skip` is *safe* — skipped content stays
  raw-indexed, so skip affects belief-store cleanliness only, never recall.
- **16.1 Route gate:** `promote` (own belief) · `structure` (relationship) · `signal` (§16.2) ·
  `delegate` (capability pointer, §14) · `skip` (noise). Route recorded; skip ≠ delete.
- **16.2 Typed learning signals:** `directive` → `note[norm]` with `imperative=1, always_inject=1`,
  criticality ≥ high (never-evict); `methodology`/`breakthrough` → procedure; `correction`/
  `stop_signal` → negative (trigger `correct()`/retract + raise criticality); `course_change` →
  supersession. Same path for Hermes turns and OCAS journals.
- **16.3 Chain resolution:** link recurring real-world event chains (booking→reminder→cancellation); a
  later negating observation supersedes the earlier rather than asserting both.
- **16.4 Risk-tiered application:** behavior-changing beliefs (directive/norm/procedure) carry
  `risk_tier`; `low`→active, `high`→draft + review.
- **16.5 Replay:** `reextract` on extractor upgrade, prioritized by criticality/salience/utility; lazy
  per-read fallback; processing advances `sessions.last_extracted_seq`.
- **16.6 Precision:** self-consistency (N prompt variants, vote; losers kept as multi-hypothesis
  drafts) + verification of high-criticality facts against the source span.
- **16.7 Promote-on-read:** facts produced by the read path (§18.4) are written back as beliefs, so the
  store grows to cover the actual question distribution.
- **16.8 Grounding:** ground natural-language time → `valid_from`/`value_ts`/qualifiers and link
  mentions to entities (also enables derivation guards, §9.4).

## 17. Curation pipeline
```sql
CREATE TABLE curation_jobs ( id INTEGER PRIMARY KEY AUTOINCREMENT,
    task TEXT CHECK(task IN ('extract','route','criticality','canonicalize','consolidate','contradiction',
                             'identity','derive','verify','decay','consistency','health','reextract',
                             'journal_ingest','session_summarize')),
    payload TEXT, depends_on INTEGER REFERENCES curation_jobs(id),
    status TEXT CHECK(status IN ('pending','running','done','failed')) DEFAULT 'pending',
    attempts INTEGER DEFAULT 0, created_at TEXT, started_at TEXT, finished_at TEXT, error TEXT );
CREATE INDEX idx_jobs_ready ON curation_jobs(status, id) WHERE status='pending';
```
A worker claims the lowest-id `pending` job whose `depends_on` is done; results write via
`append_event` (no special path). **DAG:** `extract → route → criticality → canonicalize → consolidate
→ contradiction → identity → derive → consistency`. `verify` triggers on read of unverified beliefs;
`decay/consistency/health/reextract/journal_ingest/session_summarize` run on cold schedules. Single
local model; heuristics are a pre-filter + sanity bound, never a silent writer.
- **canonicalize:** predicate schema induction (cluster surface predicates → `surface→canonical` +
  infer `cardinality`); auto in agent domain, review in user.
- **identity:** exact name/alias match → reuse, else create (never fuzzy-merge at write); fuzzy merges
  proposed at write + sweep; `unmerge(entity_id)` reverses; defers to a bound capability provider's id.
- **derive:** materialize high-value derivations (§9.4).

## 18. Retrieval (dual-tier + read-and-answer)
**18.1 Components.** *Tier 1 (belief layer):* FTS5 + ANN (§24.4) + graph, fused by Reciprocal Rank
Fusion `score(d)=Σ_r w_r/(rrf_k+rank_r(d))` (defaults fts 0.4, vector 0.6, k 60) + optional learned
reranker (identity default). *Tier 2 (raw layer):* FTS + ANN over `observed_fts`/`observed_vectors`
(spans) and `session_index` (sessions) — the recall floor (I23). Every path applies, in order: **ACL
(active principal, §15)**, status, trust/info-label, purpose (I11), temporal validity, domain.

**18.2 Query understanding.** Decompose multi-hop questions; expand with predicate synonyms
(`canonicalize` map) + a hypothetical-answer (HyDE) embedding.

**18.3 Structured lookups** (Tier-1, fast): `search`, `ask_about`, `around(entity,depth)`, `timeline`,
`history` (walk `superseded_by`), `as_of(world,knowledge)`, `changes_since`.

**18.4 Read-and-answer** (question-shaped reads; the recall floor + derivation in action):
```
answer(query, *, read_budget):
  q*   = query_understanding(query)
  t1   = retrieve_beliefs(q*)
  if confident(t1): return read(q*, t1, apply_derivation_rules=true)      # common case, fast
  t2   = retrieve_raw(q*)                                                  # spans + session summaries (I23)
  cand = rerank(t1 ∪ t2, budget=read_budget)
  ans  = model.read_and_extract(q*, cand, apply_derivation_rules=true)    # reads raw, answers, emits asserts
  promote(ans.facts)                                                       # §16.7 backfill
  if t1 insufficient: log_miss → targeted reextract (§16.5)
  return ans   # provenance to spans/beliefs/rules used; calibrated → may abstain (§19)
```
`get_context` and the reasoning layer use this path for question-shaped needs; `prefetch` stays
Tier-1/bounded. A `secret`/private context never reads across an ACL boundary (§15.6).

**18.5 Context assembly (`get_context`).** `union(search(hint), directives, pinned,
open_contradictions, critical)`; priority `w_rel·rel + w_rec·rec + w_sal·sal + w_pin·pin`, adjusted by
user-epistemic state (§19); greedy-fill `token_budget` with directives/pinned/critical always
included; annotate each with `why` + `confidence_summary`. Shares one budget authority with the
Context Engine in multiplier mode.

**18.6 Advanced (optional):** multi-vector/late-interaction; hierarchical summary index; multi-hop
retrieve-read-retrieve; semantic cache (warmed by `queue_prefetch`, invalidated on writes to matched
entities).

**18.7 Miss logging.** `search_misses(query, domain, top_score, resolved)` — logged when Tier-1 top
score < `miss_threshold` and the read path fell back; the sweep re-extracts the raw spans that answered.

## 19. User epistemic model
`user_knowledge(belief_id, proposition, about_belief, state ∈ told|stated_by_user|assumed_known,
last_communicated, times_communicated, owner, read_acl, domain, created_at)`. The harness calls
`note_informed(...)` → `informed` event. `get_context` suppresses re-explaining recently-told
propositions, boosts told-long-ago/high-importance (`why=likely_forgotten`) and never-told/high-
importance (`why=never_told`). Tool `what_user_knows(topic)`. **Abstention:** when no Tier-1/Tier-2/
derivation support exists, report "no belief," don't fabricate (calibrated, I8).

## 20. Forgetting & compaction
- **20.1 Criticality:** rules floor (safety/medical/legal/financial/boundary/identity/security) +
  learned refinement that may *raise* but never lower; `critical` surfaces a one-time confirmation.
- **20.2 Asymmetric decay:** `eligible = age > threshold·salience_mult·utility_factor ∧ salience≠pinned
  ∧ criticality=normal` (I10). Emits `decayed` (fidelity transition), never a delete.
- **20.3 Fidelity ladder:** `verbatim → gist → parametric_only → tombstone`. The raw layer follows the
  ladder but is retained longer where it underwrites the recall floor (`raw_retention`).
- **20.4 Parametric (deferred, gated):** L0 observations → L1 facts → L2 procedures/norms → **L3
  adapters** (off by default; eval-gated; `parametric_provenance` for unlearning). A conforming build
  MAY stop at L2.
- **20.5 Unlearning:** `forbidden`/`retracted` of a distilled belief → tombstone (reaching the raw
  index) + retrain-without affected adapters + quarantine until retrained.

## 21. Health & self-healing
`health_runs(...)`, `issue_fingerprints(fingerprint PK, pattern, tier, repair_action, occurrences,
last_seen, auto)`. **Auditor (cold):** calibration drift (ECE trend), contradiction-rate trend,
**ghost facts** (`confidence≥τ ∧ confirm_count=0 ∧ age>τ_age`), unjustified count (I5 must be 0), decay
anomalies, **extraction-recall gap** (raw-fallback rate), **bad-derivation rate**. **Self-healing
(Custodian pattern):** fingerprint recurring issues → tier + action; **Tier-1 auto-repair**
(non-destructive, bounded: rebuild FTS, retract orphan justification, re-embed, `unmerge` known-bad);
**Tier-2/3 surface**; never delete events; all repairs via `append_event`. **Consistency sweep
(CSP):** single-cardinality predicate with >1 active value (overlapping qualifiers, no supersession) →
`contradicted`; relationship-cardinality violations; orphan repair; **unsound derivations → `nogoods`
+ rule penalty/disable**.

## 22. Learning loop (bounded)
`retrieval_log, usage_log, eval_baselines(capability,domain,metric,baseline), eval_runs,
policies(version PK, kind, params, parent_version, active)`. Credit assignment →
`utility = EWMA(used ? outcome : small_neg)` feeds ranking, decay, engine keep-score. The reranker
trains on read-and-answer outcomes; calibration refits (§10.5); self-eval (recall@k, MRR, ECE,
contradiction rate, p99) runs per capability vs `eval_baselines`. **Champion/challenger:** a proposed
policy must beat champion on the harness with no regression before activation; champion kept for
rollback; full lineage via `parent_version`. **Bounded (I19):** ≤ `max_active_deltas` active, each ≤
`max_delta_magnitude`, only `mutable_dimensions` tunable. Derivation rules accrue precision stats →
low-precision rules auto-disable. Restricted-partition signals don't train shared policy. Proposals →
optional OCAS sink (§14.3) or internal.

## 23. Reasoning layer
`goals(...)`, `reflections(situation,action,outcome,lesson,applicability,…)`. Working memory =
the Context Engine's window when active (the live window *is* the blackboard). **Named procedures**
(`procedures`, §8.3) recalled by name/similarity, instantiated with `params`, verified by
`success_criteria`. `plan_context(goal, budget)` bundles facts + procedures + `recall_similar_situations`
(case-based episodic) + blockers + standing goals + applicable derivations + federated data, each
annotated with `why` + calibrated confidence. **Loop:** retrieve → plan → act → reflect, with a
**metacognitive gate** — low calibrated-confidence or contradicted ⇒ insert VERIFY/ask rather than act
(this is the abstention behaviour). **Reflection:** per-task (→ `reflection`; durable lessons →
`note[procedure]`/`procedure`) + periodic "sleep" consolidation. Defeasible reasoning via the TMS +
derivation layer (§9).

**Tool surface (exposed via `get_tool_schemas`):** `remember`/`remember_episode`/`remember_note`/
`remember_reference`/`remember_procedure`/`stage`/`promote`; `correct`/`forget`/`expire`/`set_purpose`/
`withdraw_consent`; `search`/`ask_about`/`around`/`timeline`/`history`/`as_of`/`changes_since`/`verify`/
`answer`/`get_context`/`what_user_knows`/`get_procedure`/`list_directives`; `explain`/
`list_derivation_rules`/`set_rule_enabled`; `resolve`/`query_capability`/`list_capabilities`/
`read_sibling`; `grant_read`/`revoke_read`/`set_acl`/`set_agent_privacy`/`list_principals`; `unmerge`/
`merge_entities`/`list_merge_proposals`/`approve_merge`/`reject_merge`; `pin_context`/`drop_context`/
`focus`; `list_contradictions`/`resolve_contradiction`/`report_usage`; `plan_context`/`reflect`/
`remember_goal`/`update_goal`/`active_goals`/`note_informed`.

---

# Part V — Platform

## 24. Storage abstraction & tiering
**24.1 Interface.** `MemoryStore`: `append_event/head/events`, `upsert_belief/get_belief/query_beliefs`,
`fts_search/vector_search/graph_neighbors`, `begin/commit/rollback`. `ChronicleCore` is built on it.
**24.2 Single-node (primary).** `SqliteStore`: WAL; FTS5; sqlite-vec or brute-force; recursive-CTE
graph; single writer. Correct through ~1M beliefs. **24.3 Tier triggers** (migrate a subsystem when
sustained): writer-lock contention >20%, write p99 > target, vector count >5M, graph p99 > target, db
> `sqlite_max_gb`; each subsystem migrates independently behind the interface. **24.4 Vectors.**
`memory_vectors(belief_id, kind, embedding, model, created_at)` + `observed_vectors` + `session_index`;
ANN backend mirrors; brute-force ≤ ~100K; model upgrade = dual-index online re-embed. **24.5 Distributed
tier (deferred).** Same interface, CRDT-backed: HLC `order_key=(wall,ctr,node,event_id)`, content-
addressed G-Set log (I2 → idempotent merge), belief = composed CRDTs (MV-Register value / monotone
status lattice / OR-Set justifications / union-find merge) → Strong Eventual Consistency; Merkle
anti-entropy; sharding by entity; a small Raft CP group for tombstones; causal-token reads.

## 25. Concurrency & consistency
Single-node: WAL (many readers + one writer, shared via the core); the §6.3 write transaction is the
consistency unit; readers never see a belief without its justifications. Distributed (§24.5):
MVCC/CRDT merge; `order_key` from the serialization point; deterministic tie-break (§7.2); idempotency
everywhere makes retries/replays safe.

## 26. Git mirror & recovery
`git_queue(id, event_id, committed, committed_at, git_commit, created_at)`. A flusher streams pending
entries (cap `max_commit_rows`/commit, loop to drain) → `events/YYYY-MM-DD/HHMMSS.jsonl` → commit →
mark → best-effort push (optional remote); entity snapshots + derived records mirror periodically.
**Recovery:** belief-store loss → `rebuild()` (§7.3). SQLite-file loss → replay `events/*.jsonl` from
git, then `rebuild()` (re-indexes raw; can rederive). **Bounded loss:** because `git_queue` commits in
the write txn (I7), only events newer than the last flush (≤ `max_lag_minutes`) can be lost.
Restricted-partition events are mirrored encrypted.

---

# Part VI — Delivery

## 27. Configuration reference
```yaml
memory:
  provider: chronicle ; store: sqlite ; db_path: ~/.hermes/commons/db/chronicle/chronicle.db
  git_repo: ~/.hermes/commons/db/chronicle/git ; git_remote: null
  embeddings: { model: embeddinggemma-300m, dimensions: 768 }
  vector_index: { backend: sqlite-vec, bruteforce_ceiling: 100000 }

  principals:                                   # §15 — default OPEN
    deployment: shared_core                      # shared_core | per_agent_isolated
    default_cross_agent_read: allow
    agents: [ { id: assistant }, { id: health, default_visibility: private } ]
    encryption: { restricted_partition_keys: true }

  sources:
    hermes_hooks: { enabled: true }
    ocas_journals: { enabled: auto, paths: [~/.hermes/commons/journals/] }   # auto = on iff present
  federation:                                   # §14 capability registry (reference, not own)
    mode: dynamic ; discover: [hermes_plugins, mcp, skills, config] ; rebind_on_change: true
    precedence: [config_pin, most_specific, most_recent] ; cache_ttl: "24h"
    pins: { contacts: weave, preferences: taste } ; provider_trust: { default: 2 }
  outputs: { ocas_signal_emit: { enabled: auto, sink: ~/.hermes/commons/signals/ } }

  extraction:
    version: "extractor-v1@<hash>" ; multi_hypothesis_threshold: 0.6 ; signal_confidence_min: 0.7
    granularities: [atomic, entity, session_summary] ; self_consistency: { passes: 2, vote: true }
    promote_on_read: true ; reextract: { mode: eager, read_budget_per_query: 2 }
  derivation:                                   # §9.4
    enabled: true ; rules_path: ~/.hermes/commons/chronicle/derivation_rules.yaml
    materialize: high_value ; max_depth: 2 ; max_fanout: 32
    confidence: { aggregate: min, rule_factor: 0.9, ceiling: 0.75 }
    default_status: { user: draft, agent: active } ; auto_disable_precision_below: 0.6
  retrieval:
    fts_weight: .4 ; vector_weight: .6 ; rrf_k: 60 ; overfetch: 4 ; default_limit: 10 ; max_limit: 50
    miss_threshold: .15 ; reranker_version: identity ; prefetch_budget: 1200 ; predictive_prefetch: true
    raw_tier: { enabled: true, span_index: true, session_index: true }
    read_and_answer: { enabled: true, confidence_gate: .55, read_budget_tokens: 4000, max_hops: 2, apply_derivation_rules: true }
    query_understanding: { decompose: true, expand_synonyms: true, hyde: true }
  context: { default_token_budget: 1500, weights: { relevance: .4, recency: .25, salience: .25, pinned: .1 } }
  capture: { sync_turn: { mode: observe_only }, precompress: { budget_ms: 400 }, agent_memory_write: { salience: high, confidence_discount: 0 } }
  reaper: { enabled: true, schedule: "*/5 * * * *", idle_threshold: "20m", reap_threshold: "45m", startup_recovery: true }
  confidence: { base: { user_direct: .85, session_transcript: .7, agent_memory_write: .85, ocas_journal: .7, tool_output: .5, web_retrieval: .4, inference: .6 },
                trust_ceiling: { 0: .40, 1: .60, 2: .75, 3: .90, 4: 1.0 } }
  calibration: { min_obs: 50, refit_every: 100 }
  forgetting: { criticality_rules_path: ~/.hermes/commons/chronicle/criticality_rules.yaml, confirm_critical: true, raw_retention: { keep_verbatim_days: 365, then: gist } }
  salience: { decay_multipliers: { pinned: 0, high: .25, normal: 1.0, incidental: 4.0 } }
  representation: { canonicalize: { enabled: true, similarity_threshold: .8, auto_apply_domain: [agent] } }
  behavior_change: { risk_tier_default: low, high_risk_requires_review: true }
  epistemic: { redundant_window: "48h", forgot_window: "30d" }
  domains: { user: { auto_decay: false, contradiction_policy: flag_for_review }, agent: { auto_decay: true, decay_days: 90, contradiction_policy: newer_wins }, general: { auto_decay: true, decay_days: 30, contradiction_policy: refetch } }
  curation: { mode: event_driven, sweep_schedule: "0 * * * *", identity_threshold: .85, consolidate_min_facts: 50 }
  consolidation: { enable_parametric: false }
  health: { schedule: "0 4 * * *", ghost_fact: { confidence_min: .8, age_days: 14 }, consistency_sweep: { enabled: true }, self_heal: { tier1_auto: true } }
  learning: { max_active_deltas: 8, max_delta_magnitude: .15, mutable_dimensions: [rrf_weights, context_weights, decay_multipliers, reranker, calibration, read_confidence_gate, derivation_rule_enable] }
  consent: { default_scope: ["*"], enforce_purpose: true } ; security: { encrypt_at_rest: true }
  git: { max_commit_rows: 1000, max_lag_minutes: 30, snapshot_interval: "0 * * * *" }
  tier_triggers: { write_lock_contention: .20, vector_count: 5000000, sqlite_max_gb: 20 }
context:
  engine: chronicle
  keep_weights: { relevance: .35, recency: .20, salience: .20, criticality: .20, redundancy_vs_store: .30 }
  never_evict: directives ; should_compress: { on_memory_pressure: true, on_focus_shift: true }
  reinject: { enabled: true } ; standalone_fallback: heuristic
```

## 28. Observability
Metrics + structured logs per subsystem: write (events/s, append p50/p99, idempotent-hit, rollback);
capture (sync_turn latency, observed/s); reaper (reaped, crash-recovered, extraction lag); projection
(head−projection_seq lag, rebuild duration); retrieval (Tier-1/Tier-2 hit, read-and-answer rate +
latency, promote-on-read, **extraction-recall gap**, cache hit, reranker version); derivation (rules
fired, materialized vs read-time, precision per rule, auto-disabled); access control (per-principal
read/write, ACL denials, cross-agent refs, restricted-partition attempts); federation (providers
active/unavailable, route promote|delegate|skip, resolve latency, cache hit, rebinds); quality
(recall@k, MRR, ECE, contradiction rate, ghost-fact count); curation (queue depth, per-task latency/
failure); learning (active deltas vs cap); git (mirror lag, push failures); storage (db size, vector
count, lock contention). Each curation pass writes `derived/runs/<ts>.json`.

## 29. Formal verification
**TLA⁺** (`Chronicle.tla`): vars `log, belief, just, constraints`; actions `Append, Gossip,
Materialize, Forbid, Retract`; safety invariants encoding I2/I5/I6 + Convergence (`∀n,m: log[n]=log[m]
⇒ belief[n]=belief[m]`) + `NoForbidden`; temporal `EventualConsistency`, `RevisionCompleteness`,
`ForbidGlobal`. Discharge CRDT ACI obligations with Apalache; check system invariants with TLC over
small symmetric instances. **Property tests (CI):** P1 idempotency · P2 convergence (random
delivery/partition → byte-equal beliefs) · P3 rebuild equivalence · P4 reducer determinism · P5
justification (no orphan active) · P6 trust ceiling · P7 revision completeness · P8 durable enqueue
(crash-injected) · P9 calibration monotonicity · P10 merge algebra · P11 capture durability (SIGKILL →
no loss) · P12 trigger independence (disable `on_session_end` → reaper extracts) · P13 rescue-before-
loss · P14 non-lossy eviction · P15 standalone engine window · P16 source independence (disable
adapters → invariants/acceptance hold) · P17 bounded learning · P18 reference-don't-own (capability
bind/unbind mid-run loses no belief, re-routes) · P19 access control (default-allow; explicit
restriction denies + isolates; cross-agent = reference) · P20 recall floor (missed-eager fact still
answered; abstains with no support) · P21 derivation (guards gate firing; scoped conclusion; premise
retraction retracts). **Deterministic simulation:** seeded; inject drop/reorder/partition/crash/
clock-skew; live invariant checks; linearizability (Porcupine/Knossos) for the CP path.

## 30. Migration (from a legacy store)
Backfill → delta-replay → freeze → cutover: (1) stand up `events` + schema alongside; (2) synthesize
`observed`+`asserted` events from legacy records (old ids → aliases; provenance → legacy source); index
legacy raw into the raw tier even where facts aren't pre-extracted (recall floor covers the rest);
**map records in a claimed capability to pointers, don't import the dataset**; assign `owner`/
`read_acl`; (3) delta-replay until small; (4) freeze legacy briefly, replay the final delta; (5) verify
(per-domain counts, `PRAGMA foreign_key_check`, FTS/vector counts, sample provenance round-trips,
`rebuild()` determinism, ACL + recall-floor + derivation guards); (6) cut reads over; decommission
after a verification window.

## 31. Implementation phases & acceptance
Each phase ships independently; "done" = its acceptance tests pass.

**Phase 1 — Data plane + capture + principals + sources/federation.** §5–§8, §11, §12, §14, §15.1–15.3,
§26. *Accept:* idempotent append (I2); rebuild reproduces + re-indexes raw (I3); SIGKILL mid-session →
reaper extracts the rest (I12/I13, P11/P12); adapters/providers disabled → fully functional
(I18/I20, P16/P18); **default-allow: any agent reads user + sibling memory with no config (I22)**.

**Phase 2 — Recall-oriented extraction + dual-tier retrieval + read-and-answer.** §16, §18. *Accept:*
re-extract at same version is a no-op; ambiguous source → ≥2 drafts collapsing on corroboration; **a
fact present in `observed` but missed by eager extraction is still answered via the raw tier + read
(I23, P20); abstains with no support; promote-on-read backfills**; query decomposition/expansion lift
multi-hop recall; `as_of` correct on a scripted timeline.

**Phase 3 — TMS + derivation + provenance/trust/criticality/consent/ACL.** §9, §10, §15.4–15.7, §20.1–2.
*Accept:* retraction cascade leaves no orphan (I5); confidence ≤ ceiling (I6); calibration monotone;
`high/critical` never decays (I10); purpose confinement + withdrawal→unlearning (I11); private agent
unreadable by siblings + cipher-isolated, cross-agent read = reference (I21, P19); **the Innovaccer
case derives the scoped "your workplace is downtown" (not "Innovaccer is downtown"), hedged, and
retracts on premise correction; does not fire if temporally disjoint or `works_at` multi-valued
(I24, P21)**.

**Phase 4 — Curation + representation + health/self-heal.** §17, §8.5, §21. *Accept:* DAG order
honored; qualified fact stored once; synonyms unify; ghost facts + extraction-recall-gap + bad-
derivation rate reported; a fingerprinted Tier-1 issue auto-repairs; an unsound rule is disabled; bad
auto-merge reversed by `unmerge`.

**Phase 5 — Context Engine + learning + reasoning + epistemic + procedures.** §13, §22, §23, §19.
*Accept:* both plugins → memory-aware compression, directives never evicted, every evicted span
retrievable (I17, P14); engine alone returns a valid window (P15); bounded learning holds (I19, P17);
a trained reranker beating identity is auto-promoted with rollback; low-precision derivation rules
auto-disable; metacognitive abstention; named procedure recalled + instantiated.

**Phase 6 — Scale & verification (as needed).** §24.5, §29, §20.4 (gated). *Accept:* runs unchanged
through `MemoryStore` (stub tiered store); property suite incl. P2/P11/P12/P14–P21 green; per-agent
isolated cores satisfy the same access model.

## 32. Error codes
| code | meaning |
|------|---------|
| `E_SCHEMA` | payload/input failed validation |
| `E_NOT_FOUND` | id does not exist |
| `E_FORBIDDEN_CONTENT` | write matches a tombstone |
| `E_TRUST_CEILING` | requested confidence exceeds ceiling without corroboration |
| `E_INFO_LABEL` | context lacks clearance for a belief's info_label |
| `E_PURPOSE` | belief not permitted for the requested purpose / consent withdrawn/expired |
| `E_CONFLICT` | concurrent write conflict not resolvable by idempotency (tiered only) |
| `E_BUDGET` | token budget too small to include pinned/critical items |
| `E_EVICT_UNSAFE` | engine asked to evict a non-durable span (append first; I17) |
| `E_RISK_REVIEW` | high-risk behavior change pending review (§16.4) |
| `E_LEARN_BOUND` | delta cap / mutation-surface exceeded (I19) |
| `E_AUTHORITY_UNAVAILABLE` | federated/capability call with no active provider — caller degrades, not a user error |
| `E_ACCESS_DENIED` | read of an explicitly-restricted memory not permitted for the active principal (§15.3) |
| `E_READ_BUDGET` | read-and-answer exceeded its budget; returns best-effort + partial |
| `E_DERIVATION_GUARD` | rule asked to fire with guards unmet — suppressed, not asserted (I24) |
| `E_STORE` | underlying store error (I/O, lock timeout) |

## 33. Worked examples
**B.1 Crash capture.** `sync_turn` appends `observed` durably; SIGKILL before extraction; on restart,
startup recovery + reaper extract everything past `last_extracted_seq`. No loss, no `on_session_end`
needed (I12/I13).
**B.2 Recall floor.** Eager extraction stored only `sister: Mara` (missed "vet in Denver"). Weeks
later "what does my sister do?" → Tier-1 thin/low-confidence → Tier-2 retrieves the session span →
read answers "a vet in Denver" and promote-on-read writes the facts, so it's Tier-1 next time (I23, P20).
**B.3 Abstention.** "My sister's dog's name?" — no support in either tier or via derivation → "I don't
have that," not a fabrication (I8).
**B.4 Guarded derivation.** `user works_in downtown` + `user works_at Innovaccer` (single-valued,
temporally overlapping) → the `derive` rule fires **scoped to the reified workplace**: "your Innovaccer
office is downtown," **not** "Innovaccer is downtown" (I24b); `source_type=inference`, conf ≤ 0.75,
draft+hedged, justified by both premises + rule. Correcting the employer retracts it (I24d). Temporally
disjoint or multi-valued `works_at` → it does not fire (`E_DERIVATION_GUARD`).
**B.5 Multi-agent (default-open).** `assistant` and `research` read the user's and each other's memory
freely, by reference (I21). The user then marks `health` private → `assistant` querying `health` gets
`E_ACCESS_DENIED` and `health` is cipher-isolated; `grant_read` shares one summary.
**B.6 Dynamic capability.** An MCP connects declaring "use me for calendar" → registered; calendar data
is captured as **pointers + beliefs about events** (not owned rows); details resolve live; on
disconnect, pointers stay valid against cache and re-bind on reconnect.

*End of specification.*
