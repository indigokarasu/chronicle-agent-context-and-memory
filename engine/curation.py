"""
Chronicle — Curation pipeline (§17).

A worker claims the lowest-id ready job and writes every result via
`append_event` (no special path). DAG: extract → route → criticality →
canonicalize → consolidate → contradiction → identity → derive → consistency.
Heuristics are a pre-filter + sanity bound, never a silent writer.
"""

from __future__ import annotations

import json
import logging
import os

from .embeddings import EmbeddingsUnavailable, pack
from .serialize import belief_id as compute_belief_id
from .store import now_iso, KIND_TABLE

logger = logging.getLogger("chronicle.curation")

# Deferred-retry backoff for a job that asked to run later: 30s, 60s, … 30m (§17.3).
_BACKOFF_BASE = 30
_BACKOFF_CAP = 1800
# A job failing for a REASON THAT MAY NEVER CLEAR (a poison payload, a model that
# rejects the text) is bounded; "the backend is down" is not — see _task_embed.
_EMBED_MAX_ATTEMPTS = 20
# Digest thresholds (§u2): below _DIGEST_MIN_FACTS a "profile" is just the facts
# again, so the handler no-ops; _DIGEST_MAX_ATTRS keeps one note from becoming a
# second copy of the facts table.
_DIGEST_MIN_FACTS = 3
_DIGEST_MAX_ATTRS = 12


def _backoff_seconds(attempt: int) -> int:
    return min(_BACKOFF_CAP, _BACKOFF_BASE * (2 ** max(0, attempt - 1)))


class JobDeferred(Exception):
    """A task asking to be retried later instead of completed or failed (§17.3).

    run_once turns it into a future run_after; the job stays pending and claimable,
    just invisible until then. `max_attempts` bounds the retries (None = retry for
    as long as it takes, for outages that are recoverable and operator-visible)."""

    def __init__(self, reason: str = "", max_attempts=None):
        super().__init__(reason or "deferred")
        self.max_attempts = max_attempts


# source_type → memory domain (governs decay/contradiction, §8.4)
_DOMAIN = {"user_direct": "user", "session_transcript": "user", "rescue_extraction": "user",
           "agent_memory_write": "agent", "delegation": "agent", "ocas_journal": "user",
           "inference": "user"}


def domain_for(source_type: str) -> str:
    return _DOMAIN.get(source_type, "general")


class CurationWorker:
    def __init__(self, core):
        self.core = core
        self.store = core.store
        self.cfg = core.cfg

    # -- loop --------------------------------------------------------------

    def run_once(self) -> bool:
        job = self.store.claim_curation_job()
        if job is None:
            return False
        try:
            handler = getattr(self, f"_task_{job['task']}", None)
            if handler is None:
                self.store.complete_curation_job(job["id"], error="no_handler")
                return True
            payload = json.loads(job["payload"] or "{}")
            handler(payload)
            self.store.complete_curation_job(job["id"])
        except JobDeferred as d:
            # attempts on the claimed row is pre-increment; this run is attempt+1.
            attempt = (job["attempts"] or 0) + 1
            if d.max_attempts and attempt >= d.max_attempts:
                logger.warning("curation job %s (%s) giving up after %d attempts: %s",
                               job["id"], job["task"], attempt, d)
                self.store.complete_curation_job(job["id"], error=str(d)[:300])
            else:
                delay = _backoff_seconds(attempt)
                self.store.defer_curation_job(job["id"], delay, error=str(d)[:300])
                logger.info("curation job %s (%s) deferred %ds (attempt %d): %s",
                            job["id"], job["task"], delay, attempt, d)
        except Exception as e:  # sanity bound: a failed job never corrupts state
            logger.exception("curation job %s failed", job["id"])
            self.store.complete_curation_job(job["id"], error=str(e)[:300])
        return True

    def drain(self, max_jobs: int = 1000) -> int:
        n = 0
        while n < max_jobs and self.run_once():
            n += 1
        return n

    # -- tasks -------------------------------------------------------------

    def _task_extract(self, payload):
        eid = payload.get("event_id")
        ev = self.store.get_event(eid) if eid else None
        if not ev:
            return
        version = self.core.extractor.version
        if self.store.has_extraction(eid, version):
            return  # idempotent (I9)
        # I16: never promote observed events from an abandoned branch (kept for audit).
        sid = ev.get("session_id")
        s = self.store.get_session(sid) if sid else None
        if s and s.get("branch_point_seq") is not None and ev["seq"] > s["branch_point_seq"]:
            self.store.record_extraction(eid, version, {"skipped": "branch_abandoned"}, 0, "skip")
            return
        p = json.loads(ev["payload"]) if isinstance(ev["payload"], str) else ev["payload"]
        excerpt = p.get("excerpt", "")
        source_type = p.get("source_type", "session_transcript")
        domain = domain_for(source_type)
        owner = ev["owner"]
        result = self.core.extractor.extract(excerpt, source_event=eid, owner=owner,
                                             domain=domain, session_id=ev.get("session_id") or "")
        # Every item that survives routing becomes an `asserted` event whose reduce
        # embeds its body — one blocking round trip each against a networked
        # backend, which is where this job spends nearly all of its wall clock. The
        # items are all in hand here, so fetch their vectors together. Cache only:
        # _emit_item and the reduce are unchanged, and a miss just embeds singly.
        self.core.reducer.prefetch_vectors(
            [{"type": "asserted", "payload": it} for it in result.items
             if it.get("route") != "skip"])
        subjects = set()
        for item in result.items:
            if item.get("route") == "skip":
                continue
            if self._maybe_delegate(item, owner, domain):
                continue
            self._emit_item(item, ev, owner, domain, source_type, version)
            if item.get("kind") == "fact":
                subjects.add(item["key"].get("entity_id"))
        self.store.record_extraction(eid, version,
                                     {"n": len(result.items)}, 1 if result.ambiguous else 0, result.route)
        self._advance_watermark(ev)
        # Inline derive for touched subjects (guarded; §9.4).
        for subj in subjects:
            if subj:
                self.core.derivation.derive_for_subject(subj, self.core.active_principal)
                # Consolidation digest (§u2), enqueued unconditionally: the handler
                # owns the >=3-fact threshold, so extraction never counts facts.
                self.store.enqueue_curation("digest", {"entity_id": subj})
        # Canonicalize newly seen predicates.
        self.store.enqueue_curation("canonicalize", {"subjects": list(subjects)})

    def _emit_item(self, item, ev, owner, domain, source_type, version):
        kind = item.get("kind", "fact")
        risk = item.get("key", {}).get("risk_tier", "low")
        # Risk-tiered application (§16.4): behavior-changing high-risk → draft + review.
        status = item.get("status", "active")
        if kind == "note" and item.get("key", {}).get("note_type") in ("norm", "procedure"):
            if risk == "high":
                status = "draft"
        ext = {"extractor_version": version, "valid_from": ev.get("occurred_at")}
        if "_entity_id" in item:
            ext["entity_token"] = item["_entity_id"]
        self.core.capture.append("asserted", {
            "kind": kind, "key": item["key"], "body": item["body"], "domain": domain,
            "confidence": item.get("confidence", 0.8), "source_event": item["source_event"],
            "source_type": source_type, "status": status,
            "extractor_version": version, "valid_from": ev.get("occurred_at")},
            parents=[ev["event_id"]],
            actor="curator", owner=owner, session_id=ev.get("session_id"),
            trust_level=ev.get("trust_level", 2))
        # Typed learning signal audit (§16.2)
        if item.get("signal_type"):
            self.core.capture.append("signal", {"signal_type": item["signal_type"],
                                                "body": item["body"][:200], "source_event": item["source_event"]},
                                     actor="curator", owner=owner)

    def _maybe_delegate(self, item, owner, domain) -> bool:
        """Route into a claimed capability as a pointer, not an owned belief (§14, I20)."""
        fed = self.core.federation
        if fed is None or item.get("kind") != "fact":
            return False
        predicate = item["key"].get("predicate_canonical", "")
        cap = fed.capability_for_predicate(predicate)
        if not cap:
            return False
        fed.route_delegate(capability=cap, entity_id=item["key"].get("entity_id"),
                           predicate=predicate, value=item["body"], owner=owner)
        return True

    def _advance_watermark(self, ev):
        sid = ev.get("session_id")
        if not sid:
            return
        s = self.store.get_session(sid)
        if s and ev["seq"] > (s.get("last_extracted_seq") or 0):
            self.store.upsert_session({"session_id": sid, "last_extracted_seq": ev["seq"]})

    def _task_derive(self, payload):
        subjects = payload.get("subjects")
        if subjects:
            for s in subjects:
                self.core.derivation.derive_for_subject(s, self.core.active_principal)
        else:
            self.core.derivation.materialize_all(self.core.active_principal)

    def _task_canonicalize(self, payload):
        """Predicate schema induction (§17): ensure predicates table + infer cardinality."""
        rows = self.store.query_beliefs("facts", "status='active'", (), limit=5000)
        by_pred = {}
        for r in rows:
            by_pred.setdefault(r["predicate_canonical"], {}).setdefault(r["entity_id"], set()).add(r["value"])
        for pred, ents in by_pred.items():
            if not pred:
                continue
            multi = any(len(vals) > 1 for vals in ents.values())
            from .extraction import canonical_predicate
            _, seed_card = canonical_predicate(pred)
            cardinality = "multi" if (multi and seed_card != "single") else seed_card
            if self.store.get_predicate(pred) is None:
                self.store.upsert_predicate(pred, pred, cardinality)

    def _task_consolidate(self, payload):
        self._task_canonicalize(payload)
        self.core.derivation.materialize_all(self.core.active_principal)

    def _task_contradiction(self, payload):
        self.core.health.consistency_sweep()

    def _task_identity(self, payload):
        """Exact name/alias dedup → merge (§17). Fuzzy is proposed, never auto."""
        ents = self.store.query_beliefs("entities", "merged_into IS NULL", (), limit=5000)
        by_name = {}
        for e in ents:
            by_name.setdefault((e["normalized_name"], e["owner"], e["domain"]), []).append(e)
        for group in by_name.values():
            if len(group) > 1:
                keep = group[0]
                for dup in group[1:]:
                    self.core.capture.append("merged", {"from_entity": dup["belief_id"],
                                                        "into_entity": keep["belief_id"],
                                                        "evidence": "exact_name_match"},
                                             actor="curator", owner=keep["owner"])

    def _task_verify(self, payload):
        """Verify a high-criticality fact against its source span (§16.6)."""
        bid = payload.get("belief_id")
        f = self.store.get_belief("facts", bid) if bid else None
        if not f:
            return
        prov = json.loads(f.get("provenance") or "{}")
        src = self.store.get_event(prov.get("source_event", ""))
        ok = False
        if src:
            sp = json.loads(src["payload"]) if isinstance(src["payload"], str) else src["payload"]
            ok = f["value"].lower() in (sp.get("excerpt", "").lower())
        self.core.capture.append("verified", {"belief_id": bid, "status": "verified" if ok else "refuted",
                                              "method": "source_span"}, actor="curator", owner=f["owner"])
        self.store.bump_calibration(prov.get("source_type", "session_transcript"),
                                    _bucket(f.get("confidence", 0.5)), ok)

    def _task_decay(self, payload):
        self.core.forgetting.decay_sweep()

    def _task_consistency(self, payload):
        self.core.health.consistency_sweep()

    def _task_health(self, payload):
        self.core.health.run()

    def _task_reextract(self, payload):
        """Replay extraction at the current version, criticality-prioritized (§16.5)."""
        events = self.store.get_events_by_type("observed")
        version = self.core.extractor.version
        prioritized = sorted(events, key=lambda e: e["seq"])
        for ev in prioritized[: payload.get("limit", 200)]:
            if not self.store.has_extraction(ev["event_id"], version):
                self.store.enqueue_curation("extract", {"event_id": ev["event_id"],
                                                        "session_id": ev.get("session_id")})

    def _task_embed(self, payload):
        """Deferred vector write (§24.4): the backend was unreachable when this
        event/belief was reduced, so the work was queued instead of hashed.

        Idempotent — a vector already present means an earlier pass (or a rebuild)
        won the race, so this is a no-op. While the backend is still down the job
        is deferred again, UNBOUNDED: an outage is recoverable and visible in the
        job queue, and dropping the vector would leave a permanent hole no later
        pass looks for. Errors from a reachable model are bounded instead — they
        may never clear, and a poison payload must not churn forever."""
        target, kind = payload.get("target_id"), payload.get("kind")
        text = payload.get("text") or ""
        emb = self.core.embedder
        if not target or not kind or not text or emb is None:
            return
        provider = external_id = None
        if kind == "observed":
            if self.store.has_observed_vector(target):
                return
        elif kind == "projection":
            # External-DB projection (§g5a): no belief table backs this — identity
            # is the (provider, external_id) pair carried alongside target_id,
            # never inferred by re-parsing the namespaced id.
            provider, external_id = payload.get("provider"), payload.get("external_id")
            if not provider or not external_id:
                return
            if self.store.has_projection_vector(provider, external_id):
                return
        else:
            if self.store.has_memory_vector(target, kind):
                return
            table = KIND_TABLE.get(kind)
            # Retracted/forgotten between capture and retry: no vector to write back.
            if not table or self.store.get_belief(table, target) is None:
                return
        # A degraded embedder re-probes ONLY here: this is the backoff path, so a
        # dead endpoint costs a connection refusal per job, never a user query.
        recheck = getattr(emb, "recheck", None)
        if recheck is not None:
            recheck()
        try:
            blob = pack(emb.embed(text))
        except EmbeddingsUnavailable as e:
            raise JobDeferred(str(e))
        except Exception as e:
            raise JobDeferred(f"embed failed: {e}", max_attempts=_EMBED_MAX_ATTEMPTS)
        if kind == "observed":
            ev = self.store.get_event(target)
            self.store.add_observed_vector(target, blob, emb.model, (ev or {}).get("owner", "default"))
        elif kind == "projection":
            owner = payload.get("owner") or "default"
            self.store.add_projection_vector(provider, external_id, blob, emb.model, owner)
        else:
            self.store.add_memory_vector(target, kind, blob, emb.model)

    def _task_digest(self, payload):
        """Entity consolidation digest (§u2): one note per entity, re-rendered in
        place, so context reads a profile instead of re-deriving it from scattered
        facts on every query.

        Identity is the ENTITY, never a snapshot of its content. The key carries
        only subject='digest:<entity_id>' and `source_event` anchors on the
        earliest OBSERVED turn the entity was ever seen in, so both halves of
        `belief_id = hash(kind, key, [source_event])` (§7) hold still and a
        re-digest UPSERTS the same row. Anchoring on the entity's belief_id would
        be stabler yet, but reducer._on_asserted files that support as kind
        'event' — a justification pointing at a belief that no event lookup
        resolves. Stability is not left to the hash alone either: an anchor CAN
        move (re-extraction at a new version may mint a fact off an OLDER event
        and lower the minimum), so any digest that survives under a different id
        is retracted here. Exactly one active digest per entity is the contract.

        The note is note_type='belief' with no always_inject in the key, so
        _insert_belief leaves always_inject=0 (§18.5): a digest is a consolidation
        of durable facts, not a directive, and it is excluded from search() —
        ask_about/get_context are its surface, and it must never outrank the very
        facts it restates.
        """
        entity_id = payload.get("entity_id")
        if not entity_id:
            return
        entity = self.store.get_belief("entities", entity_id)
        if not entity:
            return
        # Oldest-first and explicitly ordered: on an entity big enough to hit the
        # limit the slice is still the one holding the earliest event, so the
        # anchor below stays the anchor instead of drifting with SQLite's whim.
        rows = self.store.query_beliefs("facts", "entity_id=?", (entity_id,), limit=500,
                                        order="created_at, belief_id")
        active = [r for r in rows if r.get("status") == "active"]
        if len(active) < _DIGEST_MIN_FACTS:
            return  # the enqueue is unconditional; this is the gate
        # One provenance pass over EVERY fact, superseded included — superseding
        # flips status, it never deletes the row, so the minimum below survives a
        # value change that the active set alone would not. provenance.source_event
        # names the ASSERTED event that wrote the fact, and the observed turn it
        # came from is that event's parent (_emit_item), so real lineage is one hop
        # up; facts share source events heavily, hence the resolve-once cache.
        parents, sessions, cache = set(), set(), {}

        def resolve(eid):
            if eid not in cache:
                cache[eid] = self.store.get_event(eid)
            return cache[eid]

        anchor, anchor_seq = "", None
        for r in rows:
            src = json.loads(r.get("provenance") or "{}").get("source_event") or ""
            ev = resolve(src) if src else None
            if ev is None:
                continue  # e.g. 'read_and_answer' — a marker, not an event id
            live = r.get("status") == "active"
            for origin in ([src] if ev["type"] == "observed" else json.loads(ev["parents"] or "[]")):
                oev = resolve(origin)
                if oev is None or oev["type"] != "observed":
                    continue
                if anchor_seq is None or oev["seq"] < anchor_seq:
                    anchor, anchor_seq = origin, oev["seq"]
                if live:
                    parents.add(origin)   # real lineage for the line being written
                    if oev.get("session_id"):
                        sessions.add(oev["session_id"])
        if not anchor:
            return  # no observed lineage → no stable anchor → refuse to write
        # "NAME: attr=value; … (episodes: N)". Sorted so the same fact set always
        # renders the same bytes — an unstable order would look like a content
        # change and churn the log. N counts the distinct sessions behind the
        # rendered facts (a session is Chronicle's episode unit, §8.3).
        attrs = sorted({"%s=%s" % (r.get("attribute") or r.get("predicate_canonical") or "", r["value"])
                        for r in active if (r.get("attribute") or r.get("predicate_canonical"))
                        and r.get("value")})
        if not attrs:
            return
        shown = attrs[:_DIGEST_MAX_ATTRS]
        if len(attrs) > len(shown):
            shown.append("…(+%d more)" % (len(attrs) - len(shown)))
        line = "%s: %s (episodes: %d)" % (entity.get("name") or entity_id,
                                          "; ".join(shown), len(sessions))

        subject = "digest:%s" % entity_id
        key = {"note_type": "belief", "subject": subject}
        b_id = compute_belief_id("note", key, [anchor])
        owner = entity.get("owner", "default")
        prior = self.store.query_beliefs(
            "notes", "note_type='belief' AND subject=? AND status='active'", (subject,), 50)
        if len(prior) == 1 and prior[0]["belief_id"] == b_id and prior[0]["body"] == line:
            return  # unchanged: re-draining must not append an event either
        for d in prior:
            if d["belief_id"] != b_id:
                self.core.capture.append("retracted", {"belief_id": d["belief_id"]},
                                         actor="curator", owner=d.get("owner") or owner)
        self.core.capture.append("asserted", {
            "kind": "note", "key": key, "body": line, "domain": entity.get("domain", "user"),
            "confidence": 0.95, "source_event": anchor, "source_type": "inference",
            "status": "active"},
            parents=sorted(parents), actor="curator", owner=owner)

    def _task_session_summarize(self, payload):
        sid = payload.get("session_id")
        if not sid:
            return
        # Check if session_id is excluded from embedding (§27 embeddings.exclude_session_prefixes).
        excluded = self.cfg.get("embeddings.exclude_session_prefixes", [])
        if any(sid.startswith(prefix) for prefix in excluded):
            return
        events = self.store.get_events_by_session(sid)
        excerpts = []
        for ev in events:
            if ev["type"] == "observed":
                p = json.loads(ev["payload"]) if isinstance(ev["payload"], str) else ev["payload"]
                excerpts.append(p.get("excerpt", ""))
        if not excerpts:
            return
        summary = " ".join(excerpts)[:1000]
        owner = events[0]["owner"] if events else "default"
        vec = b""
        if self.core.embedder is not None:
            try:
                vec = pack(self.core.embedder.embed(summary))
            except Exception:
                vec = b""  # incl. degraded: the summary row still indexes, unvectored
        self.store.add_session_vector(sid, summary, vec, owner, events[0].get("occurred_at", now_iso()))

    def _task_journal_ingest(self, payload):
        """OCAS journals → observed events, deduped by content addressing (§14.1)."""
        paths = self.cfg.get("sources.ocas_journals.paths", [])
        for path in paths:
            path = os.path.expanduser(path)
            if not os.path.isdir(path):
                continue
            for fn in sorted(os.listdir(path)):
                fp = os.path.join(path, fn)
                if not os.path.isfile(fp):
                    continue
                try:
                    with open(fp, "r", encoding="utf-8") as fh:
                        text = fh.read()
                except OSError:
                    continue
                self.core.capture.append("observed",
                                         {"source_type": "ocas_journal", "excerpt": text[:4000],
                                          "source_ref": fp}, actor="user", trust_level=2)


def _bucket(score: float) -> str:
    return f"{int(max(0.0, min(0.999, score)) * 10) / 10:.1f}"
