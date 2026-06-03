# Chronicle Memory System — Build Spec

> **Status**: Design complete. Implementation pending.
> **Target**: Local-only, git-backed agent memory system for Hermes Agent.
> **Repository**: `indigokarasu/chronicle-plugin`

---

## 1. Design Goals

| Goal | Constraint |
|------|------------|
| Local-only | Zero network calls for operation |
| Git-backed | Git is the audit trail and sync mechanism |
| No dedicated LLM | All maintenance uses the main agent model via cron |
| Provenance-first | Every fact answers: why do I know this? can I confirm it? is it still valid? |
| Domain separation | User / Agent / General knowledge managed differently |
| Graceful degradation | Three-tier fallback: dedicated model → main model → heuristics |

## 2. Architecture

### 2.1 Storage Model

```
SQLite (source of truth) ←──→ Git (audit trail + sync)
     │                              │
     ├── facts table                ├── facts/YYYY-MM-DD/HHMMSS.jsonl (batched)
     ├── entities table             ├── entities/latest.jsonl (periodic snapshot)
     ├── relationships table        ├── documents/sessions/YYYY-MM-DD-NNN/
     ├── documents table            ├── derived/runs/
     ├── fact_vectors table         ├── derived/contradictions/
     └── git_queue table            └── derived/merges/
```

**SQLite is the operational database.** All reads hit SQLite. All writes hit SQLite first.

**Git is the append-only audit trail.** Writes are batched into JSONL files and committed asynchronously. Git never blocks reads.

**The git_queue table** tracks which facts need git commits. A background process flushes the queue. If git fails, the queue entry stays pending for retry.

### 2.2 Write Path

```
Agent calls remember()
    │
    ├─ 1. Validate input
    ├─ 2. Check for existing active fact (same entity+attribute, valid_until IS NULL)
    ├─ 3. If conflict: expire old fact, create new fact
    ├─ 4. Insert into SQLite (transactional)
    ├─ 5. Add to git_queue
    └─ 6. Return fact (queryable immediately)
    
Background: git_commit_pending()
    │
    ├─ 1. Read uncommitted git_queue entries (batch of 100)
    ├─ 2. Write JSONL file: facts/YYYY-MM-DD/HHMMSS.jsonl
    ├─ 3. git add + git commit
    ├─ 4. Mark git_queue entries as committed
    └─ 5. git push (best-effort, async)
```

### 2.3 Read Path

```
Agent calls search() / ask_about() / verify()
    │
    └─ SQLite query (FTS5 + vector + graph)
         │
         └─ Return facts with provenance
```

Git is never involved in reads. Zero latency impact from git.

## 3. Data Model

### 3.1 Fact

```json
{
  "id": "fact_abc123",
  "entity_id": "alice-chen",
  "attribute": "employer",
  "value": "Google",
  "value_type": "string",
  "confidence": 0.95,
  "domain": "user",
  "provenance": {
    "source_type": "session_transcript",
    "source_ref": "sessions/2026-05-15-003/transcript.md",
    "source_excerpt": "Alice: 'I've been at Google for 3 years now'",
    "extracted_by": "agent",
    "extracted_at": "2026-05-15T14:32:00Z"
  },
  "verification": {
    "status": "confirmed",
    "confirmed_ref": "sessions/2026-06-01-007/transcript.md",
    "confirmed_at": "2026-06-01T09:15:00Z"
  },
  "temporal": {
    "valid_from": "2026-05-15T14:32:00Z",
    "valid_until": null,
    "superseded_by": null
  }
}
```

### 3.2 Lightweight Fact (for simple observations)

```json
{
  "id": "fact_def456",
  "entity_id": "user",
  "attribute": "preference",
  "value": "dark mode",
  "domain": "user",
  "provenance": {
    "source_type": "session_transcript",
    "source_excerpt": "I prefer dark mode",
    "extracted_at": "2026-06-03T10:00:00Z"
  }
}
```

Full schema is used for: user domain facts, high-confidence claims, verified/contradicted facts, facts that supersede other facts.

### 3.3 Entity

```json
{
  "id": "alice-chen",
  "type": "person",
  "name": "Alice Chen",
  "aliases": ["Alice C.", "ach@google.com"],
  "domain": "user",
  "created_at": "2026-05-15T14:32:00Z",
  "last_seen_at": "2026-06-01T09:15:00Z",
  "fact_count": 12,
  "relationship_count": 3
}
```

### 3.4 Relationship

```json
{
  "id": "rel_abc123",
  "source_id": "alice-chen",
  "predicate": "spouse_of",
  "target_id": "jared-zimmerman",
  "confidence": 0.99,
  "domain": "user",
  "provenance": { "source_type": "session_transcript", ... },
  "valid_from": "2024-01-01T00:00:00Z",
  "valid_until": null
}
```

## 4. Domain Separation

| Property | User | Agent | General |
|----------|------|-------|---------|
| Auto-delete | Never | After 90 days stale | After 30 days stale |
| Contradiction | Flag for user review | Newer wins | Re-fetch from source |
| Provenance | Required | Required | Required |
| Curator can modify | Flag only | Freely | Re-fetch only |
| Session context | Always included | When relevant | On demand |
| Git audit | Full provenance | Lightweight | Reference only |
| Storage | Facts + relationships | Facts + relationships | Retrieval instructions only |

**General knowledge is never stored as facts.** It is stored as retrieval instructions (URL + retrieval date + cached summary with TTL). When the TTL expires, re-fetch.

## 5. SQLite Schema

```sql
PRAGMA journal_mode=WAL;
PRAGMA foreign_keys=ON;

CREATE TABLE entities (
    id TEXT PRIMARY KEY,
    type TEXT NOT NULL CHECK(type IN ('person', 'place', 'event', 'concept', 'thing')),
    name TEXT NOT NULL,
    domain TEXT NOT NULL CHECK(domain IN ('user', 'agent', 'general')),
    aliases TEXT DEFAULT '[]',
    created_at TEXT NOT NULL,
    last_seen_at TEXT NOT NULL,
    fact_count INTEGER DEFAULT 0,
    relationship_count INTEGER DEFAULT 0
);

CREATE TABLE facts (
    id TEXT PRIMARY KEY,
    entity_id TEXT NOT NULL,
    attribute TEXT NOT NULL,
    value TEXT NOT NULL,
    value_type TEXT DEFAULT 'string',
    confidence REAL DEFAULT 0.8 CHECK(confidence >= 0 AND confidence <= 1),
    domain TEXT NOT NULL CHECK(domain IN ('user', 'agent', 'general')),
    provenance TEXT NOT NULL,  -- JSON
    verification TEXT DEFAULT '{"status": "unverified"}',  -- JSON
    valid_from TEXT NOT NULL,
    valid_until TEXT,
    superseded_by TEXT,
    git_commit TEXT,
    committed_at TEXT,
    FOREIGN KEY (entity_id) REFERENCES entities(id),
    FOREIGN KEY (superseded_by) REFERENCES facts(id)
);

CREATE TABLE relationships (
    id TEXT PRIMARY KEY,
    source_id TEXT NOT NULL,
    predicate TEXT NOT NULL,
    target_id TEXT NOT NULL,
    confidence REAL DEFAULT 0.8,
    domain TEXT NOT NULL,
    provenance TEXT NOT NULL,
    valid_from TEXT NOT NULL,
    valid_until TEXT,
    git_commit TEXT,
    FOREIGN KEY (source_id) REFERENCES entities(id),
    FOREIGN KEY (target_id) REFERENCES entities(id)
);

CREATE TABLE documents (
    id TEXT PRIMARY KEY,
    type TEXT NOT NULL CHECK(type IN ('session_transcript', 'session_summary', 'reference', 'web_retrieval')),
    created_at TEXT NOT NULL,
    agent TEXT,
    abstract TEXT,
    entity_count INTEGER DEFAULT 0,
    fact_count INTEGER DEFAULT 0,
    file_path TEXT
);

CREATE TABLE fact_vectors (
    fact_id TEXT PRIMARY KEY,
    embedding BLOB NOT NULL,
    model TEXT NOT NULL,
    created_at TEXT NOT NULL,
    FOREIGN KEY (fact_id) REFERENCES facts(id) ON DELETE CASCADE
);

CREATE TABLE git_queue (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    fact_id TEXT NOT NULL,
    operation TEXT NOT NULL CHECK(operation IN ('insert', 'update', 'delete')),
    created_at TEXT NOT NULL,
    committed INTEGER DEFAULT 0,
    committed_at TEXT,
    git_commit TEXT,
    FOREIGN KEY (fact_id) REFERENCES facts(id)
);

-- FTS5 with triggers for automatic sync
CREATE VIRTUAL TABLE facts_fts USING fts5(
    entity_id, attribute, value,
    content='facts', content_rowid='rowid'
);

CREATE TRIGGER facts_ai AFTER INSERT ON facts BEGIN
    INSERT INTO facts_fts(rowid, entity_id, attribute, value)
    VALUES (NEW.rowid, NEW.entity_id, NEW.attribute, NEW.value);
END;

CREATE TRIGGER facts_ad AFTER DELETE ON facts BEGIN
    INSERT INTO facts_fts(facts_fts, rowid, entity_id, attribute, value)
    VALUES ('delete', OLD.rowid, OLD.entity_id, OLD.attribute, OLD.value);
END;

CREATE TRIGGER facts_au AFTER UPDATE ON facts BEGIN
    INSERT INTO facts_fts(facts_fts, rowid, entity_id, attribute, value)
    VALUES ('delete', OLD.rowid, OLD.entity_id, OLD.attribute, OLD.value);
    INSERT INTO facts_fts(rowid, entity_id, attribute, value)
    VALUES (NEW.rowid, NEW.entity_id, NEW.attribute, NEW.value);
END;

-- Indexes
CREATE INDEX idx_facts_entity ON facts(entity_id);
CREATE INDEX idx_facts_domain ON facts(domain);
CREATE INDEX idx_facts_valid ON facts(valid_until) WHERE valid_until IS NULL;
CREATE INDEX idx_facts_entity_attr ON facts(entity_id, attribute);
CREATE INDEX idx_rel_source ON relationships(source_id);
CREATE INDEX idx_rel_target ON relationships(target_id);
CREATE INDEX idx_git_queue_pending ON git_queue(committed) WHERE committed = 0;
```

## 6. Agent Tools

| Tool | Purpose |
|------|---------|
| `remember()` | Store a fact with provenance |
| `search()` | Hybrid search (FTS5 + vector, RRF merge) |
| `ask_about()` | Get all facts and relationships for an entity |
| `timeline()` | Chronological facts for an entity |
| `verify()` | Full provenance chain for a fact |
| `contradicts()` | Check if a new fact contradicts existing facts |
| `get_context()` | Session-start context injection |
| `expire_fact()` | Mark a fact as expired |
| `merge_entities()` | Merge duplicate entities (manual review) |
| `list_contradictions()` | List contradictions flagged for review |
| `resolve_contradiction()` | Resolve a flagged contradiction |

## 7. Curatorial Pipeline

### 7.1 Tasks

| Task | Frequency | Model Fallback |
|------|-----------|----------------|
| Extract | Daily (3am) | Main → Heuristics |
| Consolidate | Daily (3am) | Main → Heuristics |
| Contradictions | Daily (3am) | Main → Heuristics |
| Identity | Daily (3am) | Main → Heuristics |
| Decay | Daily (3am) | Main → Heuristics |

### 7.2 Three-Tier Fallback

Every curatorial task tries models in order:
1. **Dedicated model** (if configured): Small, fine-tuned, cheap
2. **Main model** (fallback): Same quality, higher cost
3. **Heuristics** (last resort): Regex + rules, zero cost

### 7.3 Curatorial Write Path

Curatorial output goes through the **same remember() → SQLite → git_queue** path as agent writes. No special curatorial write path. This ensures consistency and auditability.

### 7.4 Run Records

Every curatorial run produces a record in `derived/runs/`:

```json
{
  "timestamp": "2026-06-04T03:00:00Z",
  "model": "main",
  "duration_seconds": 45.2,
  "tasks": {
    "extract": { "status": "ok", "facts_extracted": 12, "model_used": "main" },
    "consolidate": { "status": "ok", "consolidations_made": 2, "model_used": "main" },
    "contradictions": { "status": "ok", "contradictions_found": 1, "model_used": "main" },
    "identity": { "status": "ok", "merge_candidates": 1, "model_used": "heuristics", "fallback_used": true },
    "decay": { "status": "ok", "facts_expired": 3, "model_used": "main" }
  },
  "git_commit": "abc123..."
}
```

## 8. Git Integration

### 8.1 Storage Strategy

- **Facts**: Batched JSONL files (one per write session), not per-fact files
- **Entities**: Periodic full snapshots (`entities/latest.jsonl`)
- **Documents**: Session transcripts as individual files
- **Derived**: Run records, contradiction flags, merge records

### 8.2 Recovery

If SQLite corrupts, rebuild from git:
1. Read all `facts/*.jsonl` files in git log order
2. Reconstruct facts table
3. Rebuild FTS5 index (via `INSERT INTO facts_fts(facts_fts) VALUES('rebuild')`)
4. Rebuild vector index (re-embed all facts)

This is a rare operation. SQLite corruption is uncommon.

### 8.3 Git Push

Best-effort async. If offline, commits accumulate locally. Push retries on next attempt.

## 9. Migration from Current System

### 9.1 Strategy: Backfill then Cutover

**Not dual-write.** Dual-write is the hardest migration strategy.

1. Build new system alongside old
2. Backfill historical data via one-time migration script
3. Verify data integrity (counts match, spot-check provenance)
4. Cut over reads to new system
5. Decommission old system after verification period

### 9.2 Migration Script

```python
def migrate():
    """
    1. Export Chronicle entities → new entities table
    2. Export Chronicle facts → new facts table (provenance points to Chronicle)
    3. Export MemPalace documents → new documents table + git/documents/
    4. Export Weave relationships → new relationships table
    5. Rebuild FTS5 index
    6. Rebuild vector index
    7. Initial git commit
    8. Verify counts match
    """
```

## 10. Configuration

```yaml
# ~/.hermes/config.yaml
memory:
  provider: chronicle
  db_path: ~/.hermes/memory/memory.db
  git_repo: ~/.hermes/memory/git
  git_remote: null  # Optional: git@github.com:user/memory-backup.git

  embeddings:
    model: BGE-small-en-v1.5
    model_path: ~/.hermes/memory/embeddings/
    dimensions: 384

  curatorial:
    schedule: "0 3 * * *"
    model: main  # or "curator-lama-7b" in future
    tasks:
      extract: { enabled: true, since: "24h" }
      consolidate: { enabled: true, min_facts: 50 }
      contradictions: { enabled: true }
      identity: { enabled: true, threshold: 0.85 }
      decay: { enabled: true, stale_days: 30, domains: ["agent", "general"] }

  domains:
    user:
      auto_decay: false
      contradiction_policy: flag_for_review
    agent:
      auto_decay: true
      decay_days: 90
      contradiction_policy: newer_wins
    general:
      auto_decay: true
      decay_days: 30
      contradiction_policy: refetch
      store_as_reference: true

  retrieval:
    fts_weight: 0.4
    vector_weight: 0.6
    rrf_k: 60
    default_limit: 10
    max_limit: 50
```

## 11. Implementation Phases

### Phase 1: Core Storage
- SQLite schema (facts, entities, relationships, documents, fact_vectors, git_queue)
- FTS5 triggers
- Basic CRUD operations (remember, search, ask_about, verify)
- Git queue + async commit

### Phase 2: Hybrid Retrieval
- Vector index (sqlite-vec)
- RRF merge
- Domain filtering
- Temporal validity filtering

### Phase 3: Provenance
- Full provenance schema
- Verification tracking
- Contradiction detection (heuristic)
- Timeline queries

### Phase 4: Curatorial Pipeline
- Extraction task (heuristic fallback)
- Consolidation task (heuristic fallback)
- Contradiction detection task
- Identity resolution task
- Decay task
- Run records

### Phase 5: Migration
- Chronicle → new system migration script
- MemPalace → new system migration script
- Weave → new system migration script
- Verification and cutover

### Phase 6: Polish
- Context injection (session start)
- Merge review workflow
- Git recovery tools
- Performance optimization

## 12. Open Questions

1. **sqlite-vec stability**: Is it production-ready? Alternative: brute-force vector search in Python (fast enough for <100K vectors).

2. **Embedding model**: BGE-small (384d, English-only, ~300MB) vs embeddinggemma-300m (multilingual, ~600MB). Start with BGE-small.

3. **Session transcript storage**: Full transcripts + summaries, or summaries only? Start with both.

4. **General knowledge TTL**: Should vary by source type (API docs change faster than Wikipedia).

5. **Conflict resolution workflow**: How does the agent review flagged contradictions? Via conversation? Via CLI? Defer to implementation.

6. **Dedicated curatorial model**: Which model? Fine-tuned? This is a future decision. The interface is model-agnostic.

---

*This is a living document. Update as design decisions are made during implementation.*
