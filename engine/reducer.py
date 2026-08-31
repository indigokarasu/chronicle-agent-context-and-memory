"""
Chronicle — Reducer / Projection engine (§7).

A pure fold over the event log: (state, event) → state. No clock, network, or
RNG enters a derived value; ties break by event order (seq), never wall-clock or
hash (§7.2). Every active belief it writes gets ≥1 justification in the same
transaction (I5), so readers never see an unjustified belief. Drop the projection
and replay the log → byte-identical state (I3).
"""

from __future__ import annotations

import datetime
import json
import logging
import re

from . import access
from . import doc2query
from . import identity
from .criticality import classify as classify_criticality
from .embeddings import EmbeddingsUnavailable, cosine, pack, unpack
from .serialize import belief_id as compute_belief_id
from .serialize import hash_str
from .store import BELIEF_TABLES, KIND_TABLE, now_iso
from .trust import base_confidence, clamp_to_ceiling, raw_confidence

logger = logging.getLogger("chronicle.reducer")

DOMAIN_POLICY = {
    "user": {"contradiction": "flag_for_review"},
    "agent": {"contradiction": "newer_wins"},
    "general": {"contradiction": "refetch"},
}

# Core identity predicates about the user — always-known, elevated so they enter the
# injected/static block regardless of their value text (a phone number or city name
# matches no criticality keyword on its own).
_IDENTITY_PREDICATES = {
    "name", "phone", "email", "lives_in", "address", "home_address",
    "works_at", "works_in", "birthday", "located_in", "owns_property",
}

# Belief kinds that get a memory vector on assert (§24.4). Named once so
# vector_text() and _on_asserted cannot disagree about what gets embedded.
_VECTORED_KINDS = ("fact", "episode", "note", "reference", "procedure")

# E5: how many nearest same-kind neighbours a novelty / near-duplicate scan
# keeps (config: curation.novelty_top_k). The scan itself always covers EVERY
# same-kind vector — K bounds only what comes back, not what is examined — so
# novelty and dup detection stay exact however large the corpus gets. Novelty
# needs the single nearest neighbour and the merge check needs the nearest
# same-subject one; K=25 leaves headroom for a caller that wants a ranked
# shortlist without a second pass, at a cost of 25 (float, id) pairs.
NOVELTY_TOP_K = 25


def _embed_document(embedder, text):
    """embedder.embed_document(text), falling back to embed() when the object
    predates E1's document/query split.

    Not cosmetic. The fallback keeps a non-conforming embedder on the path that
    RAISES EmbeddingsUnavailable, which is what _safe_vec catches to queue a
    deferred embed job (§24.4/I12). Calling a missing embed_document() would
    raise AttributeError instead, get swallowed by the generic handler, and
    silently drop the retry -- turning "the backend is down, try later" into
    "this vector is gone forever"."""
    fn = getattr(embedder, "embed_document", None)
    return fn(text) if callable(fn) else embedder.embed(text)


def _normalize_value(s):
    """§8.5: Normalize fact values for NOOP-dedup (mem0-style update).

    casefold, collapse whitespace, strip punctuation + leading articles."""
    if not s:
        return ""
    # Lowercase + collapse whitespace
    norm = " ".join(s.casefold().split())
    # Strip leading articles (a, an, the)
    norm = re.sub(r'^\b(a|an|the)\s+', '', norm)
    # Strip punctuation
    norm = re.sub(r'[^\w\s]', '', norm)
    return norm.strip()


class Reducer:
    def __init__(self, store, embedder=None, cfg=None):
        self.store = store
        self.embedder = embedder
        self.cfg = cfg
        self._vec_cache = {}      # one-shot prefetch window; see prefetch_vectors
        # E2/H1: host-model doc2query generation slot. None (default) means
        # Tier-1 templates only; H1 sets this to a callable(kind, key, body)
        # -> list[str] once host-model piggyback plumbing lands. See
        # doc2query.generate_questions for the fallback contract.
        self.doc2query_callback = None

    # -- batched embedding (pure optimisation) -----------------------------

    def vector_text(self, event_type, payload) -> str:
        """The exact text this reducer embeds for an event, or '' if none.

        One definition, so a prefetch can never embed something subtly different
        from what the handler then looks up (a cache keyed on text is only useful
        if both sides derive the key the same way)."""
        if event_type == "observed":
            return payload.get("excerpt", "") or ""
        if event_type == "asserted" and payload.get("kind", "fact") in _VECTORED_KINDS:
            key = payload.get("key") or {}
            return payload.get("body", "") or key.get("name", "") or key.get("topic", "") or ""
        return ""

    def doc2query_text(self, event_type, payload) -> list:
        """E2: the exact question strings this event's write will try to embed
        as doc2query proxies (Tier 1 template, or the H1 callback slot — see
        engine/doc2query.py), or [] if doc2query is disabled/not applicable.

        Mirrors vector_text's contract exactly: ONE definition, so
        prefetch_vectors' batch and _write_doc2query_proxies'/
        _write_doc2query_excerpt_proxies' live lookups can never generate
        something different for the same event — a cache keyed on question
        text is only a cache hit if both sides derive it identically."""
        if event_type == "asserted":
            kind = payload.get("kind", "fact")
            if kind not in _VECTORED_KINDS:
                return []
            if self.cfg is not None and not self.cfg.get("embeddings.doc2query.beliefs", True):
                return []
            key = payload.get("key") or {}
            # u2 digest notes restate facts already indexed under subject=
            # 'digest:<entity_id>' — an internal id, not a topic a user would
            # ever ask a question about (and retrieval already excludes
            # digests from the vector channel outright, §u2/R12).
            if kind == "note" and str(key.get("subject") or "").startswith("digest:"):
                return []
            body = payload.get("body", "") or ""
            try:
                qs = doc2query.generate_questions(kind, key, body, callback=self.doc2query_callback)
            except Exception:
                return []
            return qs[:doc2query.MAX_PROXIES]
        if event_type == "observed":
            if self.cfg is not None and not self.cfg.get("embeddings.doc2query.excerpts", False):
                return []
            excerpt = payload.get("excerpt", "") or ""
            try:
                qs = doc2query.generate_questions("observed", {}, excerpt, callback=self.doc2query_callback)
            except Exception:
                return []
            return qs[:doc2query.MAX_PROXIES]
        return []

    def prefetch_vectors(self, events) -> int:
        """Embed a known run of events' texts in ONE round trip, into a one-shot cache.

        No semantic effect whatsoever: _safe_vec still decides what gets written
        and writes the same bytes for the same text — this only changes how many
        times the process blocks on the network to get them. That matters because
        a networked embedder answers a single embed in ~50ms regardless of size,
        so a bulk ingest spends essentially all of its wall clock waiting one
        item at a time; `embeddings.embed_batch` was written for exactly this and
        had no caller.

        The cache is REPLACED on every call, so it never holds more than one
        window, and a hit is correct by construction (same embedder, same text).
        A backend with no batch API — the offline hashing embedder, where there
        is no round trip to amortise — leaves it empty and every embed takes the
        ordinary path. Failures are swallowed for the same reason _safe_vec
        swallows them: an optimisation must not be able to fail a capture (I12).
        Returns how many vectors were cached.
        """
        self._vec_cache = {}
        batch = getattr(self.embedder, "embed_batch", None)
        if batch is None:
            return 0
        texts, seen = [], set()
        for ev in events:
            payload = _payload(ev)
            text = self.vector_text(ev.get("type"), payload)
            if text and text not in seen:
                seen.add(text)
                texts.append(text)
            # E2: fold doc2query proxy questions into the SAME round trip —
            # otherwise every proxy would cost its own single embed, one per
            # question per item, defeating the whole point of prefetching.
            for q in self.doc2query_text(ev.get("type"), payload):
                if q and q not in seen:
                    seen.add(q)
                    texts.append(q)
        if len(texts) < 2:
            return 0                      # nothing to amortise
        try:
            vecs = batch(texts)
        except Exception as e:            # incl. EmbeddingsUnavailable (degraded)
            logger.debug("embedding prefetch skipped (%s)", e)
            return 0
        if len(vecs) != len(texts):
            return 0
        self._vec_cache = dict(zip(texts, vecs))
        return len(self._vec_cache)

    # -- dispatch ----------------------------------------------------------

    def reduce(self, event: dict):
        handler = self._HANDLERS.get(event["type"])
        if handler is None:
            logger.warning("Unknown event type: %s", event.get("type"))
            return
        handler(self, event)

    def reduce_many(self, events):
        for e in events:
            self.reduce(e)

    def rebuild(self, from_seq: int = 0, as_of_recorded: str | None = None):
        """Truncate the projection and replay the log in order (§7.3, I3).

        Uses iter_events_since for memory-safe batched streaming — never holds
        the full event store in memory (critical for 394k+ event stores on a
        7.7GB box)."""
        self.store.truncate_projection()
        if as_of_recorded:
            stream = (e for e in self.store.get_events_as_of(as_of_recorded) if e["seq"] > from_seq)
        else:
            stream = self.store.iter_events_since(from_seq)
        count = 0
        max_seq = 0
        for e in stream:
            self.reduce(e)
            count += 1
            max_seq = max(max_seq, e["seq"])
        if count:
            self.store.set_projection_seq(max_seq)
        logger.info("Rebuilt projection from %d events", count)

    # -- handlers ----------------------------------------------------------

    def _on_observed(self, event):
        p = _payload(event)
        excerpt = p.get("excerpt", "")
        eid = event["event_id"]
        # Check if session_id is excluded from embedding (§27 embeddings.exclude_session_prefixes).
        excluded = (self.cfg.get("embeddings.exclude_session_prefixes", []) if self.cfg else [])
        sid = event.get("session_id") or ""  # observed events may carry no session_id at all
        skip_vec = any(sid.startswith(prefix) for prefix in excluded)
        if excerpt:
            self.store.fts_index_observed(eid, excerpt)
            if self.embedder is not None and not skip_vec:
                blob = self._safe_vec(excerpt, target_id=eid, kind="observed")
                if blob is not None:
                    self.store.add_observed_vector(eid, blob, self.embedder.model_with_prefix_marker(),
                                                   event.get("owner", "default"))
                self._write_doc2query_excerpt_proxies(eid, excerpt)
        # Skip extraction for branch-abandoned spans (I16).
        if event.get("branch_id") == "__abandoned__":
            return
        # Do NOT promote operational exhaust into durable memory. The assistant's own
        # autonomous turns (no user content) and tool-output / run-log content are
        # raw-indexed above for recall, but must not become facts/notes/episodes:
        # memory is about the user and their world, not the assistant running itself.
        if _is_operational(event, p, excerpt):
            return
        self.store.enqueue_curation("extract", {"event_id": eid, "session_id": event.get("session_id")})

    def _on_asserted(self, event):
        p = _payload(event)
        kind = p.get("kind", "fact")
        key = p.get("key", {})
        body = p.get("body", "")
        source_event = p.get("source_event", event["event_id"])
        owner = event.get("owner", "default")
        domain = event.get("domain") or p.get("domain", "general")
        event["domain"] = domain  # carry resolved domain to _insert_belief/_apply_fact_conflict
        trust = event.get("trust_level", 2)
        source_type = p.get("source_type") or _provenance_source(event)

        raw = p.get("confidence", base_confidence(source_type))
        confidence = clamp_to_ceiling(raw, trust)

        b_id = compute_belief_id(kind, key, [source_event])
        existing = self._find_existing(kind, key, owner, domain)

        if kind == "fact" and existing:
            self._apply_fact_conflict(existing, kind, key, body, confidence, event, source_event, source_type)
            return
        if kind != "fact" and existing:
            # An identical re-assertion of a non-fact belief (same _find_existing match)
            # is still a NEW observation of the same thing, not silence: it must leave
            # its own provenance entry, not just bump confirm_count (E5 acceptance).
            self._confirm_with_provenance(existing["belief_id"], _table_for(kind), source_event, event,
                                          source_type)
            self.store.add_justification(existing["belief_id"], source_event, "event", "extraction")
            return

        status = p.get("status", "active")
        stored_id = self._insert_belief(kind, b_id, key, body, confidence, event, status=status,
                                        source_type=source_type, extras=p.get("extras", {}))
        # stored_id, not b_id: a near-duplicate merge means no row named b_id
        # exists, and this event supports the item it was merged into.
        self.store.add_justification(stored_id or b_id, source_event, "event", "extraction")

    def _on_confirmed(self, event):
        p = _payload(event)
        b_id = p.get("belief_id")
        if not b_id:
            return
        found = self.store.find_belief(b_id)
        if found:
            src = p.get("source_event", event["event_id"])
            self._confirm(b_id, found[0], src, event)
            self.store.add_justification(b_id, src, "event", "confirmation")

    def _on_contradicted(self, event):
        p = _payload(event)
        b_id = p.get("belief_id")
        if not b_id:
            return
        found = self.store.find_belief(b_id)
        if not found:
            return
        table, row = found
        if "contradiction_count" in row:
            self.store.update_belief(table, b_id,
                                     contradiction_count=(row.get("contradiction_count") or 0) + 1)
        self._recompute_confidence(table, b_id)
        self.store.open_contradiction(b_id, p.get("conflicting_event", ""), p.get("detail", ""))

    def _on_corrected(self, event):
        p = _payload(event)
        b_id = p.get("belief_id")
        if not b_id:
            return
        new_body = p.get("new_body")
        if new_body:
            found = self.store.find_belief(b_id)
            if found:
                table, row = found
                # Mark the old belief as superseded.
                self.store.update_belief(table, b_id, status="superseded",
                                         valid_until=event.get("recorded_at"))
                # Extract kind from table name; reconstruct key from existing belief.
                kind_map = {"facts": "fact", "episodes": "episode", "notes": "note",
                            "refs": "reference", "relationships": "relationship", "procedures": "procedure"}
                kind = kind_map.get(table)
                if kind:
                    # Rebuild key from the existing belief row.
                    if kind == "fact":
                        key = {"entity_id": row.get("entity_id", ""),
                               "predicate_canonical": row.get("predicate_canonical", ""),
                               "attribute": row.get("attribute", ""),
                               "qualifiers_hash": row.get("qualifiers_hash", ""),
                               "qualifiers": json.loads(row.get("qualifiers", "{}")),
                               "owner": row.get("owner", ""), "domain": row.get("domain", "")}
                    elif kind == "note":
                        key = {"note_type": row.get("note_type", "belief"),
                               "subject": row.get("subject", "")}
                    elif kind == "episode":
                        participants = json.loads(row.get("participants", "[]")) if row.get("participants") else []
                        key = {"title": new_body[:60], "participants": participants,
                               "occurred_at": row.get("occurred_at", ""),
                               "session_ref": row.get("session_ref", "")}
                    else:
                        # For other kinds, use a minimal key.
                        key = {}
                    # Compute new belief_id and insert the corrected belief.
                    correction_event_id = event.get("event_id", "")
                    b_id_new = compute_belief_id(kind, key, [correction_event_id])
                    # Insert the replacement belief as active, sourced from user_direct correction.
                    stored_id = self._insert_belief(kind, b_id_new, key, new_body,
                                                    row.get("confidence", 0.8), event,
                                                    status="active", source_type="user_direct")
                    # Record the correction event as justification for the new belief.
                    self.store.add_justification(stored_id or b_id_new, correction_event_id,
                                                 "event", "correction")
        else:
            self._retract(b_id)
        self._cascade(b_id)
        self.store.record_correction(b_id, p.get("reason", "corrected"), p.get("source_ref", ""), [])

    def _on_retracted(self, event):
        p = _payload(event)
        b_id = p.get("belief_id")
        if b_id:
            self._retract(b_id)
            self._cascade(b_id)

    def _on_forbidden(self, event):
        p = _payload(event)
        ch = p.get("content_hash", "")
        if not ch:
            return
        self.store.add_tombstone(ch, p.get("scope", "*"))
        for ev in self.store.get_events_by_type("observed"):
            if hash_str(_payload(ev).get("excerpt", "")) == ch:
                self.store.fts_delete_observed(ev["event_id"])
                self.store.delete_observed_vector(ev["event_id"])
        for bid in self._beliefs_matching_hash(ch):
            self._retract(bid)

    def _on_derived(self, event):
        p = _payload(event)
        kind = p.get("kind", "fact")
        key = p.get("key", {})
        body = p.get("body", "")
        rule_id = p.get("rule_id", "")
        premises = p.get("premises", [])
        confidence = clamp_to_ceiling(p.get("confidence", 0.6), 2)  # C(inference)=0.75
        status = p.get("status", "draft")
        event["domain"] = p.get("domain", "general")
        b_id = compute_belief_id(kind, key, sorted(premises) + [rule_id])
        stored_id = self._insert_belief(kind, b_id, key, body, confidence, event, status=status,
                                        source_type="inference",
                                        extras={"rule_id": rule_id, "premises": json.dumps(premises)})
        stored_id = stored_id or b_id
        for prem in premises:
            self.store.add_justification(stored_id, prem, "belief", rule_id)
        self.store.add_justification(stored_id, rule_id, "assumption", rule_id)

    def _on_informed(self, event):
        p = _payload(event)
        proposition = p.get("proposition", "")
        if not proposition:
            return
        b_id = "uk_" + hash_str(proposition + event.get("owner", "default"))[:32]
        now = event.get("recorded_at") or now_iso()
        existing = self.store.query_user_knowledge("belief_id=?", (b_id,), limit=1)
        times = (existing[0]["times_communicated"] + 1) if existing else 1
        self.store.upsert_user_knowledge({
            "belief_id": b_id, "proposition": proposition, "about_belief": p.get("about_belief", ""),
            "state": "told", "last_communicated": now, "times_communicated": times,
            "importance": p.get("importance", 0.5), "owner": event.get("owner", "default"),
            "read_acl": access.DEFAULT_ACL, "domain": event.get("domain", "user"), "created_at": now})

    def _on_grant(self, event):
        p = _payload(event)
        b_id, principal = p.get("belief_id"), p.get("principal")
        if b_id and principal:
            found = self.store.find_belief(b_id)
            if found:
                self.store.update_belief(found[0], b_id,
                                         read_acl=access.grant(found[1].get("read_acl"), principal))

    def _on_revoke(self, event):
        p = _payload(event)
        b_id, principal = p.get("belief_id"), p.get("principal")
        if b_id and principal:
            found = self.store.find_belief(b_id)
            if found:
                self.store.update_belief(found[0], b_id,
                                         read_acl=access.revoke(found[1].get("read_acl"), principal))

    def _on_adjudicated(self, event):
        """Ladder-9 F4d: a durable identity-candidate adjudication outcome.

        identity_candidates is projection state (§E7) -- truncate_projection
        wipes it and a full replay re-derives fresh 'pending' rows from the
        SAME mention events, with no memory of what a reviewer already
        decided, because MemoryStore.resolve_identity_candidate was a direct
        projection write with nothing in the event log to replay. This event
        is the fix: it names the candidate's DEDUPE KEY (kind, entity_id,
        other_id, mention_ref) rather than its row id, because the id is a
        fresh uuid4 minted only when enqueue_identity_candidate's INSERT OR
        IGNORE actually inserts -- which happens again, with a NEW id, when
        replay starts from an empty (truncated) table. The dedupe key is
        stable across that; the id is not.
        """
        p = _payload(event)
        kind, entity_id = p.get("kind"), p.get("entity_id")
        if kind and entity_id:
            self.store.resolve_identity_candidate_by_key(
                kind, entity_id, p.get("other_id") or "", p.get("mention_ref") or "",
                p.get("status"), event.get("recorded_at") or "")

    def _on_decayed(self, event):
        p = _payload(event)
        b_id = p.get("belief_id")
        if b_id:
            self.store.update_belief_all_tables(b_id, fidelity=p.get("to_fidelity", "gist"))

    def _on_rehearsed(self, event):
        p = _payload(event)
        b_id = p.get("belief_id")
        if b_id:
            self.store.update_belief_all_tables(b_id, last_seen_at=event.get("recorded_at"))

    def _on_verified(self, event):
        p = _payload(event)
        b_id = p.get("belief_id")
        if not b_id:
            return
        ver = json.dumps({"status": p.get("status", "verified"), "method": p.get("method", "manual"),
                          "at": event.get("recorded_at")})
        found = self.store.find_belief(b_id)
        if found and "verification" in found[1]:
            self.store.update_belief(found[0], b_id, verification=ver)

    def _on_merged(self, event):
        p = _payload(event)
        frm, into = p.get("from_entity"), p.get("into_entity")
        if frm and into:
            self.store.update_belief("entities", frm, merged_into=into)

    def _on_unmerged(self, event):
        p = _payload(event)
        frm = p.get("from_entity")
        if frm:
            self.store.update_belief("entities", frm, merged_into=None)

    def _on_compressed(self, event):
        pass  # audit only — beliefs already durable (§13)

    def _on_checkpoint_digest(self, event):
        pass  # audit only (§R7) — the digest is derived from spans _on_observed already made durable

    def _on_folded(self, event):
        pass  # audit only (R4) — the durable chunks _ensure_durable wrote are
        # already indexed via their own `observed` events; this event is only
        # the span_id/digest -> chunk_ids pointer chronicle_expand resolves.

    def _on_signal(self, event):
        logger.debug("signal: %s", _payload(event).get("signal_type"))

    def _on_distilled(self, event):
        pass  # deferred (§20.4)

    def _on_federated(self, event):
        """Federation writes (§14, I20). Two kinds, only one of which projects.

        kind="sweep" is AUDIT ONLY: the pointer and its cached projection are a
        cache, durable in `pointers` (which truncate_projection deliberately does
        not clear) and rebuildable from the provider at any time. The event
        carries the content hash so provenance chains — pointer → this event →
        provider + external_id + hash — without copying external attributes into
        the permanent log.

        kind="link_adjudicated" is the ONE path that may bind an entity to an
        external row, and it exists precisely because that decision is made by a
        person, never inferred from a resemblance. It projects (an entity is a
        belief, wiped and replayed by rebuild), so the decision survives a
        rebuild exactly as it was made.
        """
        p = _payload(event)
        if p.get("kind") != "link_adjudicated":
            return
        entity_id = p.get("entity_id") or ""
        if not self.store.get_belief("entities", entity_id):
            return
        if p.get("decision") == "link":
            self.store.update_belief("entities", entity_id,
                                     external_provider=p.get("provider"),
                                     external_ref=p.get("external_id"),
                                     cache_ttl=p.get("cache_ttl"))
        elif p.get("decision") == "unlink":
            self.store.update_belief("entities", entity_id,
                                     external_provider=None, external_ref=None)

    _HANDLERS = {
        "observed": _on_observed, "asserted": _on_asserted, "confirmed": _on_confirmed,
        "contradicted": _on_contradicted, "corrected": _on_corrected, "retracted": _on_retracted,
        "forbidden": _on_forbidden, "derived": _on_derived, "informed": _on_informed,
        "grant": _on_grant, "revoke": _on_revoke, "decayed": _on_decayed,
        "rehearsed": _on_rehearsed, "verified": _on_verified, "merged": _on_merged,
        "unmerged": _on_unmerged, "compressed": _on_compressed, "signal": _on_signal,
        "distilled": _on_distilled, "federated": _on_federated, "folded": _on_folded,
        "checkpoint_digest": _on_checkpoint_digest, "adjudicated": _on_adjudicated,
    }

    # -- fact conflict policy (§8.5) --------------------------------------

    def _apply_fact_conflict(self, existing, kind, key, body, confidence, event, source_event, source_type):
        old_val = existing.get("value", "")
        domain = event.get("domain") or "general"
        b_id_new = compute_belief_id(kind, key, [source_event])
        now = event.get("recorded_at") or now_iso()
        if old_val == body:
            # Identical re-assertion: same belief, but a NEW observation of it — the
            # provenance trail must show two sightings, not collapse to one (E5
            # acceptance; was _confirm, which bumps confirm_count but drops provenance).
            self._confirm_with_provenance(existing["belief_id"], "facts", source_event, event, source_type)
            self.store.add_justification(existing["belief_id"], source_event, "event", "extraction")
            return
        # §8.5: NOOP-dedup on normalized values (mem0-style update).
        if _normalize_value(old_val) == _normalize_value(body):
            self._confirm_with_provenance(existing["belief_id"], "facts", source_event, event, source_type)
            self.store.add_justification(existing["belief_id"], source_event, "event", "extraction")
            self.store.update_belief("facts", existing["belief_id"], last_seen_at=now)
            return
        policy = DOMAIN_POLICY.get(domain, DOMAIN_POLICY["general"])["contradiction"]
        old_conf = existing.get("confidence", 0.8)
        if policy == "newer_wins":
            # Supersede FIRST: it takes the old row out of status='active', which
            # is what keeps the near-duplicate scan below from merging the new
            # value straight back into the row it is replacing.
            self.store.update_belief("facts", existing["belief_id"], status="superseded",
                                     valid_until=now, superseded_by=b_id_new)
            stored_id = self._insert_belief(kind, b_id_new, key, body, confidence, event,
                                            status="active",
                                            source_type=_provenance_source(event)) or b_id_new
            if stored_id != b_id_new:
                # Merged into some other same-subject row: point superseded_by at
                # the row that actually exists, never at an id nothing wrote.
                self.store.update_belief("facts", existing["belief_id"], superseded_by=stored_id)
            self.store.add_justification(stored_id, source_event, "event", "extraction")
        elif policy == "flag_for_review":
            if confidence >= old_conf:
                self.store.update_belief("facts", existing["belief_id"], status="superseded",
                                         valid_until=now, superseded_by=b_id_new)
                stored_id = self._insert_belief(kind, b_id_new, key, body, confidence, event,
                                                status="active",
                                                source_type=_provenance_source(event)) or b_id_new
                if stored_id != b_id_new:
                    self.store.update_belief("facts", existing["belief_id"], superseded_by=stored_id)
            else:
                stored_id = self._insert_belief(kind, b_id_new, key, body, confidence, event,
                                                status="draft",
                                                source_type=_provenance_source(event)) or b_id_new
            self.store.add_justification(stored_id, source_event, "event", "extraction")
            if stored_id != existing["belief_id"]:
                # Skipped only when the near-duplicate merge folded the new value
                # INTO this very row — a belief cannot contradict itself.
                self.store.open_contradiction(existing["belief_id"], stored_id, "value conflict")
                self.store.update_belief(
                    "facts", existing["belief_id"],
                    contradiction_count=(existing.get("contradiction_count") or 0) + 1)
            self._recompute_confidence("facts", existing["belief_id"])
        else:  # general → refresh, not a conflicting fact
            self.store.update_belief("facts", existing["belief_id"], last_seen_at=now)

    # -- helpers -----------------------------------------------------------

    def _find_existing(self, kind, key, owner, domain):
        table = _table_for(kind)
        if table is None:
            return None
        if kind == "fact":
            rows = self.store.query_beliefs(
                "facts",
                "entity_id=? AND predicate_canonical=? AND qualifiers_hash=? AND owner=? AND domain=? "
                "AND status='active'",
                (key.get("entity_id", ""), key.get("predicate_canonical", ""),
                 key.get("qualifiers_hash", ""), owner, domain), limit=1)
            return rows[0] if rows else None
        if kind == "note":
            bh = hash_str(key["body"]) if "body" in key else key.get("body_hash", "")
            rows = self.store.query_beliefs(
                "notes", "note_type=? AND subject=? AND body_hash=? AND owner=? AND domain=? "
                "AND status='active'",
                (key.get("note_type", "belief"), key.get("subject", ""), bh, owner, domain), limit=1)
            return rows[0] if rows else None
        if kind == "entity":
            rows = self.store.query_beliefs(
                "entities", "normalized_name=? AND type=? AND owner=? AND domain=?",
                (key.get("normalized_name", key.get("name", "").lower()),
                 key.get("entity_type", key.get("type", "")), owner, domain), limit=1)
            return rows[0] if rows else None
        return None

    def _ensure_entity(self, entity_id, name, owner, domain, event):
        if not entity_id:
            return
        ent = self.store.get_belief("entities", entity_id)
        if ent:
            self.store.update_belief("entities", entity_id, fact_count=(ent.get("fact_count", 0) + 1))
            return
        now = event.get("recorded_at") or now_iso()
        self.store.upsert_belief("entities", {
            "belief_id": entity_id, "type": "", "name": name or entity_id,
            "normalized_name": (name or entity_id).lower(), "aliases": "[]", "domain": domain,
            "owner": owner, "read_acl": access.DEFAULT_ACL, "fact_count": 1, "relationship_count": 0,
            "created_at": now, "last_seen_at": now})

    def _embed_once(self, text):
        """This write's ONE embedding of `text`: prefetch-cache hit, else a
        single embed, else None (degraded backend or any other failure — an
        embedding may never fail a durable capture, I12).

        Both the novelty scan and the memory-vector write need the same vector
        for the same text. Computing it twice doubles the embed round trips on
        the ingest path, which is exactly what the batching regression test
        counts, so it is computed here once and passed to both.

        Document-side (E1): this vector is stored as the item's memory vector --
        tagged model_with_prefix_marker() -- and is scanned against other stored
        document vectors. The prefetch cache is filled by embed_batch(), which
        already prefixes "search_document: ", so a bare embed() here would make
        the cache-hit and cache-miss paths disagree and would tag a bare vector
        as [prefixed]. It must go through embed_document().
        """
        cached = self._vec_cache.get(text)
        if cached is not None:
            return cached
        try:
            return _embed_document(self.embedder, text)
        except EmbeddingsUnavailable:
            return None
        except Exception as e:
            logger.debug("embedding skipped (%s)", e)
            return None

    def _calculate_novelty(self, query_embedding, kind, key, body, owner, domain):
        """Score this write's novelty and find its ONE legal merge candidate.

        Takes the already-computed embedding (see _embed_once) and returns
        `(novelty, dup_belief_id, dup_similarity)`; `(None, None, None)` when
        the kind is not stored in a belief table (§E5: "no embedder → store as
        today" is handled by the caller, which never gets a vector at all).

        Two DIFFERENT questions, deliberately answered by two different scans:

        novelty  — the spec's definition verbatim: 1 − max cosine against
            existing same-KIND vectors (owner+domain scoped), so an episode is
            scored against every episode, a fact against every fact. Scoping it
            to the same SUBJECT instead — what the first pass did — left it NULL
            on nearly every write, because the overwhelmingly common case is the
            first item of its subject. A first-ever item of its kind scores 1.0
            (maximally novel), never NULL: NULL means "not computed", and
            conflating the two makes the column unreadable.

        dup_belief_id — the nearest neighbour that ALSO matches this item's
            subject / natural key EXACTLY, restricted in SQL (see _merge_scope).
            Never a bare owner+domain neighbour: merging discards the incoming
            body and keeps only its provenance, so a cross-subject merge is
            silent data loss. Kinds with no natural key never merge at all.

        `dup_similarity` is that candidate's OWN cosine — not `1 − novelty`,
        which is the global maximum and may belong to a different subject
        entirely; comparing the global max against the threshold would fire a
        merge on the strength of an item the merge is not allowed to touch.

        Candidate retrieval goes through store.nearest_memory_vectors (top-K by
        cosine over every same-kind vector, paged), not a rowid-ordered
        `LIMIT 100` scan, so behaviour does not silently degrade past 100 items.
        """
        if not query_embedding or KIND_TABLE.get(kind) not in BELIEF_TABLES:
            return None, None, None

        k = NOVELTY_TOP_K
        if self.cfg:
            try:
                k = max(1, int(self.cfg.get("curation.novelty_top_k", NOVELTY_TOP_K)))
            except (TypeError, ValueError):
                k = NOVELTY_TOP_K

        try:
            neighbours = self.store.nearest_memory_vectors(kind, query_embedding, owner, domain, k)
        except Exception as e:
            logger.debug("novelty scan skipped (%s)", e)
            return None, None, None
        # Clamp at 0: an anti-correlated neighbour is not "more than new".
        top = max(0.0, neighbours[0][1]) if neighbours else 0.0
        novelty = 1.0 - top

        scope = _merge_scope(kind, key, body)
        if scope is None:
            return novelty, None, None       # no natural key → never merges
        try:
            same = self.store.nearest_memory_vectors(kind, query_embedding, owner, domain, k,
                                                     scope[0], scope[1])
        except Exception as e:
            logger.debug("duplicate scan skipped (%s)", e)
            return novelty, None, None
        if not same:
            return novelty, None, None
        return novelty, same[0][0], same[0][1]

    def _append_provenance(self, existing, source_event, source_type, now=None):
        """Append a new provenance entry to an existing belief's provenance JSON.

        On the FIRST append, the belief's original (single-object) provenance is
        preserved as provenances[0] before the new entry is added — the RHS
        `existing.get("provenance", ...)` copy is taken before "provenances" is
        written into it, so the original entry is captured whole, not nested
        inside itself. Every later observation of the same belief (a near-
        duplicate merge OR an identical re-assertion) just appends, so a belief
        confirmed N times carries N provenance entries — an actual audit trail,
        not a single overwritten source_type. Pure w.r.t. the store: callers
        (_merge_duplicate, _confirm_with_provenance) persist the returned JSON.
        """
        now = now or now_iso()
        old_prov = existing.get("provenance", "{}")
        try:
            prov_obj = json.loads(old_prov) if isinstance(old_prov, str) else (old_prov or {})
        except Exception:
            prov_obj = {"source_type": "unknown"}
        if "provenances" not in prov_obj:
            prov_obj["provenances"] = [prov_obj.copy()]
        prov_obj["provenances"].append({
            "source_type": source_type,
            "source_event": source_event,
            "extracted_by": "chronicle-v5",
            "extracted_at": now
        })
        return json.dumps(prov_obj)

    def _merge_duplicate(self, existing_id, existing_table, event, source_event, source_type):
        """Merge a near-duplicate assertion into the existing belief: append
        provenance and increment its occurrence count, instead of inserting a
        second near-identical row (§ novelty scoring, E5).

        The occurrence count is `occurrence_count`, which schema_version 7 gives
        to ALL SIX belief tables. Counting via `confirm_count` alone — the first
        pass's approach — worked for facts and silently dropped the count for
        every other kind, because facts are the only table that ever had that
        column: a duplicate episode or reference merged away leaving nothing to
        say it had been seen twice. Facts still bump confirm_count as well, so
        the corroboration signal _recompute_confidence reads is unchanged.

        Returns the surviving belief_id, so the caller can attach the new
        source_event's justification to a row that actually exists (I5).
        """
        existing = self.store.get_belief(existing_table, existing_id)
        if not existing:
            return None
        now = event.get("recorded_at") or now_iso()
        new_prov = self._append_provenance(existing, source_event, source_type, now)

        updates = {"provenance": new_prov, "last_seen_at": now}
        if "occurrence_count" in existing:
            updates["occurrence_count"] = (existing.get("occurrence_count") or 1) + 1
        if "confirm_count" in existing:
            updates["confirm_count"] = (existing.get("confirm_count") or 0) + 1

        self.store.update_belief(existing_table, existing_id, **updates)
        return existing_id

    def _insert_belief(self, kind, b_id, key, body, confidence, event, status="active",
                       source_type="extraction", extras=None):
        """Write the belief and return the belief_id that ACTUALLY holds it.

        Normally that is `b_id`. When the E5 near-duplicate check fires, no row
        with `b_id` is ever created and the id of the item merged into is
        returned instead. Callers must justify the returned id: attaching the
        justification to `b_id` regardless (the first pass) left a justification
        row pointing at a belief that does not exist — an orphan, and a direct
        violation of I5's "every active belief carries ≥1 justification, and
        every justification supports a real belief".
        """
        now = event.get("recorded_at") or now_iso()
        owner = event.get("owner", "default")
        domain = event.get("domain") or "general"
        trust = event.get("trust_level", 2)
        extras = extras or {}
        p = _payload(event)
        source_event = event.get("event_id", "")

        # E5: Calculate novelty and check for near-duplicates (if embedder available)
        text_to_embed = self.vector_text("asserted", p)
        novelty = None
        dup_similarity_threshold = (self.cfg.get("curation.dup_similarity", 0.95)
                                     if self.cfg else 0.95)

        write_vec = None

        if self.embedder is not None and text_to_embed and kind in _VECTORED_KINDS:
            write_vec = self._embed_once(text_to_embed)
            novelty, dup_candidate_id, dup_similarity = self._calculate_novelty(
                write_vec, kind, key, body, owner, domain)
            # Merge only on the candidate's OWN similarity: `1 - novelty` is the
            # nearest neighbour of ANY subject, which is exactly the item the
            # merge is forbidden to touch.
            if dup_candidate_id and dup_similarity is not None \
                    and dup_similarity >= dup_similarity_threshold:
                table = _table_for(kind)
                if table:
                    merged_into = self._merge_duplicate(dup_candidate_id, table, event,
                                                        source_event, source_type)
                    if merged_into:
                        return merged_into

        prov = {"source_type": source_type, "source_event": source_event,
                "extracted_by": "chronicle-v5", "extracted_at": now}
        # §H1c: an asserted payload may declare where its CONTENT came from, as
        # opposed to what kind of source it is. Today the only producer is the
        # host-model piggyback ("host_model"). The key is added ONLY when the
        # payload carries it, so every heuristic write still serializes the exact
        # four-key object it always did — that absence is what makes the
        # disabled-by-default path byte-identical rather than merely equivalent.
        prov_source = p.get("provenance_source")
        if prov_source:
            prov["source"] = str(prov_source)[:40]
        provenance = json.dumps(prov)
        crit, crit_reason = classify_criticality(body, kind, key.get("note_type", ""))
        # Core identity facts about the user are always-known: elevate so they enter
        # the injected/static block (their value text alone — a phone number, a city —
        # matches no criticality keyword).
        if kind == "fact" and domain == "user" \
                and key.get("predicate_canonical", "") in _IDENTITY_PREDICATES \
                and crit == "normal":
            crit, crit_reason = "high", "identity"
        salience = event.get("salience") or key.get("salience", "normal")

        if kind == "fact":
            self._ensure_entity(key.get("entity_id", ""), key.get("entity_name"), owner, domain, event)
            vnum, vts = _typed_value(body)
            self.store.upsert_belief("facts", {
                "belief_id": b_id, "entity_id": key.get("entity_id", ""),
                "attribute": key.get("attribute", key.get("predicate_canonical", "")),
                "predicate_canonical": key.get("predicate_canonical", ""), "value": body,
                "value_type": "number" if vnum is not None else "string", "value_num": vnum, "value_ts": vts,
                "qualifiers": json.dumps(key.get("qualifiers", {})),
                "qualifiers_hash": key.get("qualifiers_hash", ""),
                "extractor_version": p.get("extractor_version", ""), "domain": domain, "owner": owner,
                "read_acl": access.DEFAULT_ACL, "status": status, "salience": salience, "criticality": crit,
                "criticality_reason": crit_reason, "confidence": confidence, "trust_level": trust,
                "valid_from": p.get("valid_from", now), "created_at": now, "last_seen_at": now,
                "fidelity": "verbatim", "utility": 0,
                "purpose_scope": json.dumps(p.get("purpose_scope", ["*"])), "provenance": provenance,
                "novelty": novelty, "verification": '{"status":"unverified"}', "rule_id": extras.get("rule_id"),
                "premises": extras.get("premises")})
        elif kind == "episode":
            self.store.upsert_belief("episodes", {
                "belief_id": b_id, "title": key.get("title", body[:60]), "summary": body,
                "participants": json.dumps(key.get("participants", [])),
                "occurred_at": key.get("occurred_at", now), "session_ref": key.get("session_ref", ""),
                "domain": domain, "owner": owner, "read_acl": access.DEFAULT_ACL, "status": status,
                "salience": salience, "criticality": crit, "criticality_reason": crit_reason,
                "confidence": confidence, "trust_level": trust, "valid_from": now, "created_at": now,
                "last_seen_at": now, "fidelity": "verbatim", "utility": 0, "purpose_scope": '["*"]',
                "novelty": novelty, "provenance": provenance})
        elif kind == "note":
            note_type = key.get("note_type", "belief")
            always = 1 if (note_type == "norm" or key.get("always_inject")) else 0
            self.store.upsert_belief("notes", {
                "belief_id": b_id, "note_type": note_type, "subject": key.get("subject", ""),
                "body": body, "body_hash": hash_str(body),
                "imperative": 1 if note_type == "norm" else key.get("imperative", 0),
                "always_inject": always, "risk_tier": key.get("risk_tier", "low"), "domain": domain,
                "owner": owner, "read_acl": access.DEFAULT_ACL, "status": status,
                "salience": "pinned" if always else salience,
                "criticality": "high" if always and crit == "normal" else crit,
                "criticality_reason": crit_reason or ("directive" if always else ""),
                "confidence": confidence, "trust_level": trust, "valid_from": now, "created_at": now,
                "last_seen_at": now, "fidelity": "verbatim", "utility": 0, "purpose_scope": '["*"]',
                "novelty": novelty, "provenance": provenance})
        elif kind == "entity":
            self.store.upsert_belief("entities", {
                "belief_id": b_id, "type": key.get("entity_type", key.get("type", "")),
                "name": key.get("name", body),
                "normalized_name": key.get("normalized_name", key.get("name", body).lower()),
                "aliases": json.dumps(key.get("aliases", [])), "domain": domain, "owner": owner,
                "read_acl": access.DEFAULT_ACL, "external_ref": key.get("external_ref"),
                "external_provider": key.get("external_provider"), "fact_count": 0,
                "relationship_count": 0, "created_at": now, "last_seen_at": now})
        elif kind == "relationship":
            self.store.upsert_belief("relationships", {
                "belief_id": b_id, "source_id": key.get("source_id", ""),
                "predicate": key.get("predicate", ""), "target_id": key.get("target_id", ""),
                "external_ref": key.get("external_ref"), "domain": domain, "owner": owner,
                "read_acl": access.DEFAULT_ACL, "status": status, "salience": salience,
                "confidence": confidence, "trust_level": trust, "valid_from": now, "created_at": now,
                "last_seen_at": now, "purpose_scope": '["*"]', "provenance": provenance,
                "novelty": novelty, "rule_id": extras.get("rule_id"), "premises": extras.get("premises")})
        elif kind == "procedure":
            self.store.upsert_belief("procedures", {
                "belief_id": b_id, "name": key.get("name", ""), "params": json.dumps(key.get("params", [])),
                "steps": json.dumps(key.get("steps", [])),
                "success_criteria": json.dumps(key.get("success_criteria", [])), "domain": domain,
                "owner": owner, "read_acl": access.DEFAULT_ACL, "status": status, "salience": salience,
                "confidence": confidence, "trust_level": trust, "valid_from": now, "created_at": now,
                "last_seen_at": now, "purpose_scope": '["*"]', "provenance": provenance, "novelty": novelty})
        elif kind == "reference":
            ttl_days = key.get("ttl_days", 30)
            self.store.upsert_belief("refs", {
                "belief_id": b_id, "topic": key.get("topic", ""), "retrieval_url": key.get("retrieval_url"),
                "retrieved_at": now, "cached_summary": body,
                "ttl_days": ttl_days, "stale_after": _add_days_iso(now, ttl_days), "domain": domain,
                "owner": owner, "read_acl": access.DEFAULT_ACL, "status": status, "confidence": confidence,
                "trust_level": trust, "valid_from": now, "created_at": now, "last_seen_at": now,
                "purpose_scope": '["*"]', "provenance": provenance, "novelty": novelty})

        if self.embedder is not None and kind in _VECTORED_KINDS:
            text = self.vector_text("asserted", p)
            blob = self._safe_vec(text, target_id=b_id, kind=kind, vec=write_vec)
            if blob is not None:
                self.store.add_memory_vector(b_id, kind, blob, self.embedder.model_with_prefix_marker())
                # §E7: this fact's own vector IS the mention context for the
                # entity it is about — reused, never re-embedded. `blob is not
                # None` is also the degradation gate: no embedder and a degraded
                # backend (§24.4) both land here with nothing, so the identity
                # feature stays entirely inert instead of guessing.
                if kind == "fact":
                    self._identity_evidence(key.get("entity_id", ""), b_id, blob, now)
                    self._detect_supersede_candidate(b_id, key, body, blob, owner, domain)
            self._write_doc2query_proxies(b_id, kind, key, body)
        return b_id

    def _identity_evidence(self, entity_id, mention_ref, blob, now):
        """Fold a mention into its entity's centroid and queue split/merge
        CANDIDATES (§E7). Proposes only: no entity is merged or split here, or
        anywhere else in this codebase — identity is adjudicated, never inferred.

        `now` is the event's own timestamp, so a replay writes identical rows
        (§7.2, I3). Failures are swallowed inside identity.observe_mention for
        the same reason _safe_vec swallows its own (I12).

        The model tag is model_with_prefix_marker(), not the bare model name
        (E1). observe_mention keys the running centroid on it and RESETS the
        accumulator when it changes, precisely because a sum of vectors from
        one geometry cannot be compared against another. Flipping task
        prefixes is exactly such a geometry change -- the vectors folded in
        afterwards carry a "search_document: " prefix -- but it does NOT change
        embedder.model, so tagging with the bare name would let the centroid
        silently average across both geometries and never trip its own reset."""
        if not entity_id:
            return
        marker_fn = getattr(self.embedder, "model_with_prefix_marker", None)
        model = marker_fn() if callable(marker_fn) else getattr(self.embedder, "model", "")
        identity.observe_mention(self.store, self.cfg, model,
                                 entity_id, mention_ref, unpack(blob), now)

    def _detect_supersede_candidate(self, b_id, key, body, new_blob, owner, domain):
        """Ladder 9 E4 (§issue-8): nearest-neighbor update detection.

        Additive-only signal, never a side effect on the write it rides along
        with (I12 in spirit): on ANY failure -- no embedder, a bad vector, a
        query error -- this simply records nothing and the durable fact write
        above is already committed either way. It never changes belief status,
        never deletes, never auto-supersedes; that stays exactly the exact-key
        conflict policy's job in `_apply_fact_conflict`, which has already run
        (or not) before `_insert_belief` -- and therefore this -- is reached.

        Candidate pool is same-subject (this fact's entity_id) first; only when
        that is empty (no entity_id, or a lone fact for it) does it fall back to
        a global scan across this owner/domain's other active facts. Reuses the
        vector this write already computed/stored (no extra embed() calls) and
        the candidates' already-stored memory_vectors (no extra embeds for them
        either) -- purely a DB read + cosine, same cost shape as E5's novelty
        check.
        """
        try:
            new_vec = unpack(new_blob)
        except Exception:
            return
        if not new_vec:
            return
        threshold = self.cfg.get("curation.supersede_similarity", 0.82) if self.cfg else 0.82
        try:
            threshold = float(threshold)
        except (TypeError, ValueError):
            threshold = 0.82
        entity_id = key.get("entity_id", "")

        candidates = []
        if entity_id:
            candidates = self.store.query_beliefs(
                "facts", "entity_id=? AND owner=? AND domain=? AND status='active' AND belief_id!=?",
                (entity_id, owner, domain, b_id), limit=50)
        if not candidates:
            candidates = self.store.query_beliefs(
                "facts", "owner=? AND domain=? AND status='active' AND belief_id!=?",
                (owner, domain, b_id), limit=200)
        if not candidates:
            return

        best_id, best_sim, best_row = None, 0.0, None
        for row in candidates:
            vec_row = self.store._conn().execute(
                "SELECT embedding FROM memory_vectors WHERE belief_id=? AND kind='fact'",
                (row["belief_id"],)).fetchone()
            if vec_row is None:
                continue
            try:
                sim = cosine(new_vec, unpack(vec_row["embedding"]))
            except Exception:
                continue
            if sim > best_sim:
                best_sim, best_id, best_row = sim, row["belief_id"], row

        if best_id is None or best_sim < threshold:
            return
        if _normalize_value(best_row.get("value", "")) == _normalize_value(body):
            return  # same claim re-asserted, not an update -- nothing to chain
        try:
            self.store.add_supersede_candidate(b_id, best_id, best_sim, new_value=body,
                                               old_value=best_row.get("value", ""))
        except Exception as e:
            logger.debug("supersede candidate not recorded for %s (%s)", b_id, e)

    def _write_doc2query_proxies(self, b_id, kind, key, body):
        """E2 doc2query: embed up to doc2query.MAX_PROXIES question strings
        this belief can answer (doc2query_text — Tier 1 template, or the H1
        callback slot, see engine/doc2query.py) as `query_proxy_vectors` rows
        linked back to `b_id`. A silent no-op without an embedder — same
        contract as the memory vector it rides beside. Never fails the
        capture (I12): a failed embed just means fewer (or zero) proxies for
        this write, the same swallow-everything contract _safe_vec already
        gives its other callers. `_safe_vec` is called with no target_id/kind
        (a missed proxy is a candidate for re-generation on the next write,
        not a durable gap like the belief's own content vector, so it is
        never requeued as a curation job).

        DELETE-THEN-WRITE, not upsert. query_proxy_vectors is keyed
        (belief_id, proxy_idx), so re-generating N proxies over a previous run
        of M only overwrites indices 0..N-1: with N < M the tail M-N rows
        survive as orphans carrying the OLD questions, and retrieval scores
        them equally with the fresh ones. The count really does shrink -- a
        belief re-asserted with a thinner key yields fewer templates, and H1's
        generation callback returns a variable number by design -- so the
        stale tail is reachable, not theoretical. Clearing first makes the
        stored proxy set exactly this generation's output.

        §H2: a host model's own questions for this item (host_model_proxies,
        written by the doc2query drain) are merged in AHEAD of the templates
        under doc2query.MERGE_RULE. That lookup is what makes the host set
        survive delete-then-write: without it, the very next re-assertion of
        this belief would regenerate templates only and silently throw the
        host's work away. On a default store the table is empty, merge_questions
        returns the template list unchanged, and nothing about this write moves."""
        if self.embedder is None:
            return
        questions = self.doc2query_text("asserted", {"kind": kind, "key": key, "body": body})
        questions = doc2query.merge_questions(self.store.host_proxy_questions(b_id), questions)
        self.store_proxies(b_id, kind, questions)
        self._offer_doc2query(b_id, kind, body)

    def store_proxies(self, b_id, kind, questions):
        """Delete-then-write ONE item's proxy set (§E2, integration fix D).

        The single write path for query_proxy_vectors, shared verbatim by the
        Tier-1 template path above and by the §H2 host-model drain
        (engine/hostmodel.apply_result) — same delete-before-regenerate rule,
        same MAX_PROXIES ceiling, same swallow-everything embed contract — so
        the two sources cannot drift into two different lifecycles."""
        if self.embedder is None:
            return 0
        self.store.delete_query_proxy_vectors(b_id)
        written = 0
        for idx, q in enumerate(questions[:doc2query.MAX_PROXIES]):
            blob = self._safe_vec(q)
            if blob is not None:
                self.store.add_query_proxy_vector(b_id, idx, kind, q, blob,
                                                  self.embedder.model_with_prefix_marker())
                written += 1
        return written

    def _offer_doc2query(self, b_id, kind, body):
        """§H2: register this item as doc2query work a host model could do.

        Gated on host_model.piggyback, which is a plain dict lookup — on the
        default path this method reaches no SQL at all, so it cannot move the
        inertness dump. The registry's own queue cap (oldest-expire at
        host_model.max_pending) is what bounds the offers; a bulk ingest that
        writes ten thousand beliefs leaves 32 pending requests, the freshest.
        Failures are swallowed for the usual reason: an enrichment side channel
        may never fail a durable write (I12)."""
        if self.cfg is None or not self.cfg.get("host_model.piggyback", False):
            return
        text = (body or "").strip()
        if not text:
            return
        try:
            from .hostmodel import HostModelRegistry
            HostModelRegistry(self.store, self.cfg).enqueue(
                "doc2query", {"belief_id": b_id, "kind": kind, "text": text[:400]})
        except Exception as e:
            logger.debug("doc2query host-model offer not enqueued for %s (%s)", b_id, e)

    def _write_doc2query_excerpt_proxies(self, event_id, excerpt):
        """E2 doc2query, raw-excerpt path (§27 embeddings.doc2query.excerpts,
        default OFF — see engine/config.py for why). Same contract as
        _write_doc2query_proxies, just keyed by event_id/kind='observed'
        instead of a belief_id/belief-kind.

        FUNCTIONAL SINCE §H2, STILL OFF BY DEFAULT. Until H2 these rows were
        written and then dropped at the point of use: they store an EVENT id
        under kind='observed', retrieval resolved a proxy hit with
        `add(bid, _table_of_kind(kind), ...)`, and _table_of_kind has no entry
        for 'observed' so it fell through to its "facts" default — an event_id
        looked up in the facts table finds no row and returns. H2 wires the
        missing resolution path: kind='observed' proxies are now excluded from
        the belief-tier scan (RetrievalEngine._vector_proxies) and credited
        through the RAW channel instead (RetrievalEngine._observed_proxies,
        consumed by retrieve_raw), where an event id actually means something.

        The DEFAULT IS STILL OFF (§E2/§H2.4): Tier-1 generation for free text is
        only a lead-clause recast, so the flag now does what it says rather than
        being worth turning on blind. Flip it with a recall measurement, or with
        a host model (H1/H2) generating the excerpt questions.

        The flag is checked HERE as well as inside doc2query_text so that the
        whole method — including the host-question lookup — is skipped outright
        when it is off. Every observed event reaches this call, and the default
        path must not spend a SELECT per event on a table that only the enabled
        path can ever populate."""
        if self.embedder is None:
            return
        if self.cfg is not None and not self.cfg.get("embeddings.doc2query.excerpts", False):
            return
        questions = doc2query.merge_questions(
            self.store.host_proxy_questions(event_id),
            self.doc2query_text("observed", {"excerpt": excerpt}))
        if not questions:
            return
        self.store_proxies(event_id, "observed", questions)

    def _safe_vec(self, text, target_id=None, kind=None, vec=None):
        """Pack an embedding, or return None on ANY failure — so the embedding
        backend can never roll back a durable capture (I12).

        When the backend is DEGRADED (unreachable, §24.4) the vector is not merely
        skipped: an `embed` job is queued in this same transaction so the write is
        replayed once a model appears (§17.3). It is queued, never hashed — a hash
        vector is indistinguishable from a real one downstream and would poison
        retrieval silently.

        `vec` is an already-computed embedding OF THIS SAME TEXT (E5's novelty
        scan makes one); passing it keeps a write to a single embed instead of
        two. None means "not computed, or computing it failed" — either way the
        ordinary path below runs, so a failure still reaches the degraded
        handling rather than being swallowed upstream.

        A prefetch window (prefetch_vectors) is consulted first. A miss costs only
        the ordinary single embed, so no caller depends on the cache being warm."""
        try:
            if vec is not None:
                return pack(vec)
            cached = self._vec_cache.get(text)
            return pack(cached if cached is not None else _embed_document(self.embedder, text))
        except EmbeddingsUnavailable:
            try:
                if target_id and kind and text:
                    self.store.enqueue_embed_job(target_id, kind, text)
            except Exception as e:  # I12 again: not even the queue may roll back a capture
                logger.warning("deferred embed not queued for %s (%s)", target_id, e)
            return None
        except Exception as e:
            logger.debug("embedding skipped (%s)", e)
            return None

    def _confirm(self, b_id, table, source_event, event):
        row = self.store.get_belief(table, b_id)
        if not row:
            return
        if "confirm_count" in row:
            self.store.update_belief(table, b_id, confirm_count=(row.get("confirm_count") or 0) + 1,
                                     last_confirmed_at=event.get("recorded_at"))
        self._recompute_confidence(table, b_id)

    def _confirm_with_provenance(self, b_id, table, source_event, event, source_type):
        """Like _confirm, but also appends a provenance entry (shared _append_provenance
        helper, §E5). Used wherever an identical re-assertion resolves to an EXISTING
        belief via _find_existing — both the fact and non-fact branches of _on_asserted
        — so a repeated observation stays visible in the audit trail instead of being
        silently folded into confirm_count alone (the defect the review caught: 1 item
        but only 1 provenance entry after a real re-assertion).

        Guards on "provenance" being a real column the same way _confirm guards on
        "confirm_count" — entities carry neither, and must degrade exactly like
        _confirm always has, not raise on an UPDATE naming a column they don't have.
        """
        row = self.store.get_belief(table, b_id)
        if not row:
            return
        updates = {}
        if "confirm_count" in row:
            updates["confirm_count"] = (row.get("confirm_count") or 0) + 1
            updates["last_confirmed_at"] = event.get("recorded_at")
        # Same occurrence count the near-duplicate merge maintains: an identical
        # re-assertion and a 0.96-similar one are both "seen again", and a count
        # that only one of the two paths increments is not a count.
        if "occurrence_count" in row:
            updates["occurrence_count"] = (row.get("occurrence_count") or 1) + 1
        if "provenance" in row:
            now = event.get("recorded_at") or now_iso()
            updates["provenance"] = self._append_provenance(row, source_event, source_type, now)
        if updates:
            self.store.update_belief(table, b_id, **updates)
        self._recompute_confidence(table, b_id)

    def _recompute_confidence(self, table, b_id):
        row = self.store.get_belief(table, b_id)
        if not row or "confidence" not in row:
            return
        st = json.loads(row.get("provenance") or "{}").get("source_type", "session_transcript")
        corroborated = (row.get("confirm_count") or 0) >= 1
        raw = raw_confidence(st, row.get("confirm_count") or 0, row.get("contradiction_count") or 0)
        conf = clamp_to_ceiling(raw, row.get("trust_level") or 2, corroborated)
        self.store.update_belief(table, b_id, confidence=conf)

    def _retract(self, b_id):
        found = self.store.find_belief(b_id)
        if found and found[0] in BELIEF_TABLES:
            self.store.update_belief(found[0], b_id, status="retracted")
        else:
            self.store.update_belief_all_tables(b_id, status="retracted")
        self.store.delete_justifications(b_id)

    def _cascade(self, b_id):
        """Revision cascade (§9.3, I5, I24d): retract dependents that lose support.

        A rule-derived belief is a conjunction of its premises, so losing ANY one
        premise retracts it. An ordinary belief with several independent supports
        survives while ≥1 real support remains."""
        for dep in self.store.get_dependents(b_id):
            dep_id = dep["belief_id"]
            if dep_id == b_id:
                continue
            rule = dep.get("rule") or ""
            derived_dep = rule not in ("", "extraction", "confirmation")
            if derived_dep:
                self._retract(dep_id)
                self.store.record_correction(dep_id, "cascade_premise_retracted", b_id, [b_id])
                self._cascade(dep_id)
                continue
            remaining = [j for j in self.store.get_justifications(dep_id) if j["support"] != b_id]
            real = [j for j in remaining if j["support_kind"] != "assumption"]
            if not real:
                self._retract(dep_id)
                self.store.record_correction(dep_id, "cascade_from_retraction", b_id, [b_id])
                self._cascade(dep_id)

    def _beliefs_matching_hash(self, content_hash):
        out = [r["belief_id"] for r in self.store.query_beliefs("notes", "body_hash=?", (content_hash,), limit=1000)]
        for row in self.store.query_beliefs("facts", "1=1", (), limit=5000):
            if hash_str(row.get("value", "")) == content_hash:
                out.append(row["belief_id"])
        return out


# -- module helpers -------------------------------------------------------

def _payload(event) -> dict:
    p = event.get("payload", "{}")
    if isinstance(p, str):
        try:
            return json.loads(p)
        except Exception:
            return {}
    return p or {}


def _provenance_source(event) -> str:
    p = _payload(event)
    if p.get("source_type"):
        return p["source_type"]
    actor = event.get("actor", "agent")
    return {"user": "user_direct", "agent": "session_transcript",
            "curator": "inference", "system": "session_transcript"}.get(actor, "session_transcript")


# Markers of operational exhaust (run-logs / tool output) that must never be promoted
# into durable memory. Conservative: anything not matched still flows through normally.
_OP_MARKERS = ("mentor-light", "dispatch.draft", "dispatch_triage", "light-scan",
               '"run_id"', '"run_type"', '"schema":')


def _is_operational(event, p, excerpt) -> bool:
    """True when an observed event is the assistant operating itself rather than the
    user/world. Such events stay raw-indexed (FTS + vector) for recall but are NOT
    promoted into facts/notes/episodes."""
    src = p.get("source_type", "")
    if src == "agent_memory_write":
        return False  # an explicit, intentional save — keep it
    # An autonomous agent turn: a session transcript with no user content
    # (capture.observe tags actor='agent' exactly when user_content is empty).
    if src == "session_transcript" and event.get("actor") == "agent":
        return True
    head = (excerpt or "")[:400]
    low = head.lstrip().lower()
    if low.startswith(("tool:", "assistant: tool:")):
        return True
    return bool(any(m in head for m in _OP_MARKERS))


def _add_days_iso(iso_str: str, days) -> str:
    """`iso_str` (now_iso() format) shifted forward by `days`, same fixed-width
    format so it string-compares like every other stored timestamp.

    Anchored on the EVENT's own timestamp, never wall-clock now() (§7.2, I3):
    the reducer is a pure fold over the log, so a derived field computed from
    the live clock would break byte-identical replay.
    """
    try:
        t = datetime.datetime.fromisoformat((iso_str or "").replace("Z", "+00:00"))
    except (ValueError, TypeError):
        t = datetime.datetime.now(datetime.timezone.utc)
    try:
        delta_days = max(0.0, float(days))
    except (TypeError, ValueError):
        delta_days = 30.0
    t += datetime.timedelta(days=delta_days)
    return t.strftime("%Y-%m-%dT%H:%M:%S.%fZ")[:-4] + "Z"


def _table_for(kind):
    return KIND_TABLE.get(kind)


def _merge_scope(kind, key, body):
    """The exact-match scope inside which a near-duplicate merge is legal, as
    `(sql_fragment, params)` over the belief table's own columns — or None,
    meaning this kind can never merge and both items get stored.

    A merge keeps ONE row: the incoming body is discarded and only its
    provenance is folded into an item that already exists. It is therefore only
    ever legal between two items that denote the same thing, and this is where
    that is decided — in a SQL predicate handed to nearest_memory_vectors, so
    the restriction is structural. A candidate from another subject cannot be
    returned and then rejected downstream; it cannot be returned at all.

    Kinds that HAVE a subject (fact: entity+predicate; note: type+subject) use
    it. Kinds that don't use their natural key: an episode's title+session, a
    reference's topic+URL, a procedure's name, a relationship's triple. Anything
    else, or an empty natural key, returns None.

    Selecting candidates on owner+domain alone — what the first E5 pass did for
    every kind lacking a subject column — is silent, unrecoverable data loss.
    Two different sessions' episodes run 0.95+ cosine whenever the turns are
    phrased alike ("Monday standup" vs "Friday retro": 0.9574), and an episode
    is emitted for EVERY turn over 60 characters, so the highest-volume write
    path in the system was destroying unrelated content by default.
    """
    if kind == "fact":
        return ("entity_id=? AND predicate_canonical=?",
                (key.get("entity_id", "") or "", key.get("predicate_canonical", "") or ""))
    if kind == "note":
        return ("note_type=? AND subject=?",
                (key.get("note_type", "belief") or "belief", key.get("subject", "") or ""))
    if kind == "episode":
        # Mirrors _insert_belief's own title default, so the scope matches the
        # value that actually lands in the column.
        title = key.get("title") or (body or "")[:60]
        if not title:
            return None
        return ("title=? AND COALESCE(session_ref,'')=?",
                (title, key.get("session_ref", "") or ""))
    if kind == "reference":
        topic = key.get("topic", "") or ""
        url = key.get("retrieval_url") or ""
        if not topic and not url:
            return None
        return ("COALESCE(topic,'')=? AND COALESCE(retrieval_url,'')=?", (topic, url))
    if kind == "procedure":
        name = key.get("name", "") or ""
        if not name:
            return None
        return ("name=?", (name,))
    if kind == "relationship":
        return ("source_id=? AND predicate=? AND target_id=?",
                (key.get("source_id", "") or "", key.get("predicate", "") or "",
                 key.get("target_id", "") or ""))
    return None


def _typed_value(body):
    s = (body or "").strip()
    try:
        if s and s.replace(".", "", 1).replace("-", "", 1).isdigit():
            return (float(s), None)
    except Exception:
        pass
    return (None, None)


from .config import TRUST_CEILING  # noqa: F401  (back-compat for tests)
