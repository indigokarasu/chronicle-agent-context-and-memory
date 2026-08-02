"""
Chronicle — Reducer / Projection engine (§7).

A pure fold over the event log: (state, event) → state. No clock, network, or
RNG enters a derived value; ties break by event order (seq), never wall-clock or
hash (§7.2). Every active belief it writes gets ≥1 justification in the same
transaction (I5), so readers never see an unjustified belief. Drop the projection
and replay the log → byte-identical state (I3).
"""

from __future__ import annotations

import json
import logging
import re

from . import access
from .criticality import classify as classify_criticality
from .embeddings import EmbeddingsUnavailable, pack
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
            text = self.vector_text(ev.get("type"), _payload(ev))
            if text and text not in seen:
                seen.add(text)
                texts.append(text)
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
                    self.store.add_observed_vector(eid, blob, self.embedder.model,
                                                   event.get("owner", "default"))
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
            self._apply_fact_conflict(existing, kind, key, body, confidence, event, source_event)
            return
        if kind != "fact" and existing:
            self._confirm(existing["belief_id"], _table_for(kind), source_event, event)
            self.store.add_justification(existing["belief_id"], source_event, "event", "extraction")
            return

        status = p.get("status", "active")
        self._insert_belief(kind, b_id, key, body, confidence, event, status=status,
                            source_type=source_type, extras=p.get("extras", {}))
        self.store.add_justification(b_id, source_event, "event", "extraction")

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
                    self._insert_belief(kind, b_id_new, key, new_body, row.get("confidence", 0.8), event,
                                       status="active", source_type="user_direct")
                    # Record the correction event as justification for the new belief.
                    self.store.add_justification(b_id_new, correction_event_id, "event", "correction")
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
        self._insert_belief(kind, b_id, key, body, confidence, event, status=status,
                            source_type="inference",
                            extras={"rule_id": rule_id, "premises": json.dumps(premises)})
        for prem in premises:
            self.store.add_justification(b_id, prem, "belief", rule_id)
        self.store.add_justification(b_id, rule_id, "assumption", rule_id)

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

    def _on_signal(self, event):
        logger.debug("signal: %s", _payload(event).get("signal_type"))

    def _on_distilled(self, event):
        pass  # deferred (§20.4)

    _HANDLERS = {
        "observed": _on_observed, "asserted": _on_asserted, "confirmed": _on_confirmed,
        "contradicted": _on_contradicted, "corrected": _on_corrected, "retracted": _on_retracted,
        "forbidden": _on_forbidden, "derived": _on_derived, "informed": _on_informed,
        "grant": _on_grant, "revoke": _on_revoke, "decayed": _on_decayed,
        "rehearsed": _on_rehearsed, "verified": _on_verified, "merged": _on_merged,
        "unmerged": _on_unmerged, "compressed": _on_compressed, "signal": _on_signal,
        "distilled": _on_distilled,
    }

    # -- fact conflict policy (§8.5) --------------------------------------

    def _apply_fact_conflict(self, existing, kind, key, body, confidence, event, source_event):
        old_val = existing.get("value", "")
        domain = event.get("domain") or "general"
        b_id_new = compute_belief_id(kind, key, [source_event])
        now = event.get("recorded_at") or now_iso()
        if old_val == body:
            self._confirm(existing["belief_id"], "facts", source_event, event)
            self.store.add_justification(existing["belief_id"], source_event, "event", "extraction")
            return
        # §8.5: NOOP-dedup on normalized values (mem0-style update).
        if _normalize_value(old_val) == _normalize_value(body):
            self._confirm(existing["belief_id"], "facts", source_event, event)
            self.store.add_justification(existing["belief_id"], source_event, "event", "extraction")
            self.store.update_belief("facts", existing["belief_id"], last_seen_at=now)
            return
        policy = DOMAIN_POLICY.get(domain, DOMAIN_POLICY["general"])["contradiction"]
        old_conf = existing.get("confidence", 0.8)
        if policy == "newer_wins":
            self.store.update_belief("facts", existing["belief_id"], status="superseded",
                                     valid_until=now, superseded_by=b_id_new)
            self._insert_belief(kind, b_id_new, key, body, confidence, event, status="active",
                                source_type=_provenance_source(event))
            self.store.add_justification(b_id_new, source_event, "event", "extraction")
        elif policy == "flag_for_review":
            if confidence >= old_conf:
                self.store.update_belief("facts", existing["belief_id"], status="superseded",
                                         valid_until=now, superseded_by=b_id_new)
                self._insert_belief(kind, b_id_new, key, body, confidence, event, status="active",
                                    source_type=_provenance_source(event))
            else:
                self._insert_belief(kind, b_id_new, key, body, confidence, event, status="draft",
                                    source_type=_provenance_source(event))
            self.store.add_justification(b_id_new, source_event, "event", "extraction")
            self.store.open_contradiction(existing["belief_id"], b_id_new, "value conflict")
            self.store.update_belief("facts", existing["belief_id"],
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

    def _insert_belief(self, kind, b_id, key, body, confidence, event, status="active",
                       source_type="extraction", extras=None):
        now = event.get("recorded_at") or now_iso()
        owner = event.get("owner", "default")
        domain = event.get("domain") or "general"
        trust = event.get("trust_level", 2)
        extras = extras or {}
        p = _payload(event)
        provenance = json.dumps({"source_type": source_type, "source_event": event.get("event_id", ""),
                                 "extracted_by": "chronicle-v5", "extracted_at": now})
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
                "verification": '{"status":"unverified"}', "rule_id": extras.get("rule_id"),
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
                "provenance": provenance})
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
                "provenance": provenance})
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
                "rule_id": extras.get("rule_id"), "premises": extras.get("premises")})
        elif kind == "procedure":
            self.store.upsert_belief("procedures", {
                "belief_id": b_id, "name": key.get("name", ""), "params": json.dumps(key.get("params", [])),
                "steps": json.dumps(key.get("steps", [])),
                "success_criteria": json.dumps(key.get("success_criteria", [])), "domain": domain,
                "owner": owner, "read_acl": access.DEFAULT_ACL, "status": status, "salience": salience,
                "confidence": confidence, "trust_level": trust, "valid_from": now, "created_at": now,
                "last_seen_at": now, "purpose_scope": '["*"]', "provenance": provenance})
        elif kind == "reference":
            self.store.upsert_belief("refs", {
                "belief_id": b_id, "topic": key.get("topic", ""), "cached_summary": body,
                "ttl_days": key.get("ttl_days", 30), "domain": domain, "owner": owner,
                "read_acl": access.DEFAULT_ACL, "status": status, "confidence": confidence,
                "trust_level": trust, "valid_from": now, "created_at": now, "last_seen_at": now,
                "purpose_scope": '["*"]', "provenance": provenance})

        if self.embedder is not None and kind in _VECTORED_KINDS:
            text = self.vector_text("asserted", p)
            blob = self._safe_vec(text, target_id=b_id, kind=kind)
            if blob is not None:
                self.store.add_memory_vector(b_id, kind, blob, self.embedder.model)

    def _safe_vec(self, text, target_id=None, kind=None):
        """Pack an embedding, or return None on ANY failure — so the embedding
        backend can never roll back a durable capture (I12).

        When the backend is DEGRADED (unreachable, §24.4) the vector is not merely
        skipped: an `embed` job is queued in this same transaction so the write is
        replayed once a model appears (§17.3). It is queued, never hashed — a hash
        vector is indistinguishable from a real one downstream and would poison
        retrieval silently.

        A prefetch window (prefetch_vectors) is consulted first. A miss costs only
        the ordinary single embed, so no caller depends on the cache being warm."""
        try:
            cached = self._vec_cache.get(text)
            return pack(cached if cached is not None else self.embedder.embed(text))
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


def _table_for(kind):
    return KIND_TABLE.get(kind)


def _typed_value(body):
    s = (body or "").strip()
    try:
        if s and s.replace(".", "", 1).replace("-", "", 1).isdigit():
            return (float(s), None)
    except Exception:
        pass
    return (None, None)


from .config import TRUST_CEILING  # noqa: F401  (back-compat for tests)
