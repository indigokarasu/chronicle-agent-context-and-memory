"""
Chronicle — Reducer / Projection engine (§7).

Pure function: (state, event) → state.
Folds the event log into the belief store.
"""

from __future__ import annotations

import json
import logging
from typing import Any, Optional

from .serialize import belief_id as compute_belief_id

logger = logging.getLogger("chronicle.reducer")

# Trust ceiling C(level) (§10.3)
TRUST_CEILING = {0: 0.40, 1: 0.60, 2: 0.75, 3: 0.90, 4: 1.00}

# Fact conflict policy (§8.5)
DOMAIN_DECAY = {
    "user": {"auto_decay": False, "contradiction": "flag_for_review"},
    "agent": {"auto_decay": True, "decay_days": 90, "contradiction": "newer_wins"},
    "general": {"auto_decay": True, "decay_days": 30, "contradiction": "refetch"},
}


class Reducer:
    """Pure reducer: events → belief store."""

    def __init__(self, store):
        self.store = store

    def reduce(self, event: dict):
        """Apply a single event to the belief store."""
        handler = self._HANDLERS.get(event["type"])
        if handler is None:
            logger.warning(f"Unknown event type: {event['type']}")
            return
        try:
            handler(self, event)
        except Exception as e:
            logger.error(f"Reducer error for {event['type']}/{event.get('event_id','?')}: {e}")
            raise

    def reduce_many(self, events: list[dict]):
        """Apply multiple events in order."""
        for e in events:
            self.reduce(e)

    def rebuild(self, from_seq: int = 0):
        """Rebuild the entire belief store from the event log (§7.3)."""
        # Truncate belief tables
        with self.store.transaction() as conn:
            for table in ["facts", "episodes", "notes", "refs", "relationships",
                          "procedures", "entities", "user_knowledge", "justifications",
                          "corrections", "nogoods"]:
                conn.execute(f"DELETE FROM {table}")
            conn.execute("DELETE FROM observed_fts")
            conn.execute("DELETE FROM observed_vectors")
            conn.execute("DELETE FROM session_index")
            conn.execute("DELETE FROM memory_vectors")

        # Replay events
        events = self.store.get_events_since(from_seq)
        for e in events:
            self.reduce(e)

        # Set projection seq
        if events:
            max_seq = max(e["seq"] for e in events)
            self.store.set_projection_seq(max_seq)

        logger.info(f"Rebuilt belief store from {len(events)} events (seq > {from_seq})")

    # -- Event handlers -----------------------------------------------------

    def _on_observed(self, event: dict):
        """Persist raw + index it. No belief created."""
        payload = self._parse_payload(event)
        excerpt = payload.get("excerpt", "")

        # Index in FTS
        if excerpt:
            self.store.fts_index(event["event_id"], excerpt)

        # Enqueue extraction
        self.store.enqueue_curation("extract", {
            "event_id": event["event_id"],
            "excerpt": excerpt,
            "session_id": event.get("session_id"),
        })

    def _on_asserted(self, event: dict):
        """Upsert belief from extraction."""
        payload = self._parse_payload(event)
        kind = payload.get("kind", "fact")
        key = payload.get("key", {})
        body = payload.get("body", "")
        confidence = payload.get("confidence", 0.8)
        source_event = payload.get("source_event", event["event_id"])
        extractor_version = payload.get("extractor_version", "")

        # Trust ceiling check
        trust = event.get("trust_level", 2)
        ceiling = TRUST_CEILING.get(trust, 0.75)
        confidence = min(confidence, ceiling)

        # Compute belief_id
        b_id = compute_belief_id(kind, key, [source_event])

        # Check for existing belief with same key
        existing = self._find_existing(kind, key, event.get("owner", "default"),
                                        event.get("domain", "general"))

        if existing:
            # Fact conflict policy (§8.5)
            existing_val = existing.get("value", existing.get("body", ""))
            if existing_val == body:
                # Equal: confirm
                self._confirm_belief(existing, event)
            else:
                # Differ: apply domain policy
                domain = event.get("domain", "general")
                policy = DOMAIN_DECAY.get(domain, DOMAIN_DECAY["general"])
                if policy["contradiction"] == "newer_wins":
                    self._supersede_belief(existing, b_id, event)
                elif policy["contradiction"] == "flag_for_review":
                    # New belief as draft, open contradiction
                    self._insert_belief(kind, b_id, key, body, confidence, event,
                                        status="draft")
                    self._open_contradiction(existing["belief_id"], b_id, event)
                else:
                    self._insert_belief(kind, b_id, key, body, confidence, event)
        else:
            self._insert_belief(kind, b_id, key, body, confidence, event)

        # Add justification
        self.store.add_justification(b_id, source_event, "event", "extraction")

    def _on_confirmed(self, event: dict):
        """Increment confirm_count, recompute confidence."""
        payload = self._parse_payload(event)
        b_id = payload.get("belief_id")
        source_event = payload.get("source_event")
        if b_id:
            self._confirm_belief_by_id(b_id, source_event, event)

    def _on_contradicted(self, event: dict):
        """Open a contradiction record."""
        payload = self._parse_payload(event)
        b_id = payload.get("belief_id")
        if b_id:
            logger.info(f"Contradiction opened for belief {b_id}")

    def _on_corrected(self, event: dict):
        """Supersede or retract + cascade."""
        payload = self._parse_payload(event)
        b_id = payload.get("belief_id")
        new_body = payload.get("new_body")
        if b_id and new_body:
            self._supersede_belief_by_id(b_id, event)
            # Cascade (§9.3)
            self._cascade_revision(b_id)

    def _on_retracted(self, event: dict):
        """Retract + cascade."""
        payload = self._parse_payload(event)
        b_id = payload.get("belief_id")
        if b_id:
            with self.store.transaction() as conn:
                for table in ["facts", "episodes", "notes", "refs", "relationships", "procedures"]:
                    conn.execute(f"UPDATE {table} SET status='retracted' WHERE belief_id=?", (b_id,))
            self._cascade_revision(b_id)

    def _on_forbidden(self, event: dict):
        """Tombstone content."""
        payload = self._parse_payload(event)
        content_hash = payload.get("content_hash", "")
        scope = payload.get("scope", "*")
        if content_hash:
            self.store.add_tombstone(content_hash, scope)

    def _on_derived(self, event: dict):
        """Insert derived belief."""
        payload = self._parse_payload(event)
        kind = payload.get("kind", "fact")
        key = payload.get("key", {})
        body = payload.get("body", "")
        rule_id = payload.get("rule_id", "")
        premises = payload.get("premises", [])
        confidence = payload.get("confidence", 0.6)

        # Clamp to inference ceiling
        confidence = min(confidence, TRUST_CEILING[2])

        b_id = compute_belief_id(kind, key, premises + [rule_id])
        self._insert_belief(kind, b_id, key, body, confidence, event,
                            source_type="inference")

        # Justifications = premises + rule_id
        for p in premises:
            self.store.add_justification(b_id, p, "belief", rule_id)
        self.store.add_justification(b_id, rule_id, "assumption", rule_id)

    def _on_informed(self, event: dict):
        """Upsert user_knowledge."""
        payload = self._parse_payload(event)
        proposition = payload.get("proposition", "")
        import hashlib
        prop_hash = hashlib.blake2b(proposition.encode(), digest_size=16).hexdigest()
        b_id = f"b_{prop_hash}"

        now = event.get("recorded_at", "")
        uk = {
            "belief_id": b_id,
            "proposition": proposition,
            "about_belief": payload.get("about_belief", ""),
            "state": "told",
            "last_communicated": now,
            "times_communicated": 1,
            "owner": event.get("owner", "default"),
            "read_acl": "user_agents",
            "domain": event.get("domain", "user"),
            "created_at": now,
        }
        self.store.upsert_belief("user_knowledge", uk)

    def _on_grant(self, event: dict):
        """Update read_acl to grant access."""
        payload = self._parse_payload(event)
        b_id = payload.get("belief_id")
        principal = payload.get("principal")
        if b_id and principal:
            with self.store.transaction() as conn:
                for table in ["facts", "episodes", "notes", "refs", "relationships", "procedures"]:
                    conn.execute(
                        f"UPDATE {table} SET read_acl=read_acl||? WHERE belief_id=?",
                        (f",{principal}", b_id)
                    )

    def _on_revoke(self, event: dict):
        """Update read_acl to revoke access."""
        payload = self._parse_payload(event)
        b_id = payload.get("belief_id")
        principal = payload.get("principal")
        if b_id and principal:
            with self.store.transaction() as conn:
                for table in ["facts", "episodes", "notes", "refs", "relationships", "procedures"]:
                    conn.execute(
                        f"UPDATE {table} SET read_acl=REPLACE(read_acl,?,?) WHERE belief_id=?",
                        (f",{principal}", "", b_id)
                    )

    def _on_decayed(self, event: dict):
        """Fidelity transition."""
        payload = self._parse_payload(event)
        b_id = payload.get("belief_id")
        to_fidelity = payload.get("to_fidelity", "gist")
        if b_id:
            with self.store.transaction() as conn:
                for table in ["facts", "episodes", "notes"]:
                    conn.execute(f"UPDATE {table} SET fidelity=? WHERE belief_id=?",
                                 (to_fidelity, b_id))

    def _on_rehearsed(self, event: dict):
        """Update last_seen_at."""
        payload = self._parse_payload(event)
        b_id = payload.get("belief_id")
        now = event.get("recorded_at", "")
        if b_id:
            with self.store.transaction() as conn:
                for table in ["facts", "episodes", "notes", "refs", "relationships", "procedures"]:
                    conn.execute(f"UPDATE {table} SET last_seen_at=? WHERE belief_id=?",
                                 (now, b_id))

    def _on_verified(self, event: dict):
        """Update verification status."""
        payload = self._parse_payload(event)
        b_id = payload.get("belief_id")
        status = payload.get("status", "verified")
        method = payload.get("method", "manual")
        now = event.get("recorded_at", "")
        if b_id:
            ver = json.dumps({"status": status, "method": method, "at": now})
            with self.store.transaction() as conn:
                for table in ["facts", "episodes", "notes"]:
                    conn.execute(f"UPDATE {table} SET verification=? WHERE belief_id=?",
                                 (ver, b_id))

    def _on_merged(self, event: dict):
        """Entity merge."""
        payload = self._parse_payload(event)
        from_entity = payload.get("from_entity")
        into_entity = payload.get("into_entity")
        if from_entity and into_entity:
            with self.store.transaction() as conn:
                conn.execute("UPDATE entities SET merged_into=? WHERE belief_id=?",
                             (into_entity, from_entity))

    def _on_unmerged(self, event: dict):
        """Entity unmerge."""
        payload = self._parse_payload(event)
        from_entity = payload.get("from_entity")
        if from_entity:
            with self.store.transaction() as conn:
                conn.execute("UPDATE entities SET merged_into=NULL WHERE belief_id=?",
                             (from_entity,))

    def _on_compressed(self, event: dict):
        """Audit only — beliefs already durable."""
        pass

    def _on_signal(self, event: dict):
        """Route learning signal."""
        payload = self._parse_payload(event)
        signal_type = payload.get("signal_type", "")
        logger.info(f"Learning signal: {signal_type}")

    def _on_distilled(self, event: dict):
        """Deferred — gated."""
        pass

    # -- Helpers ------------------------------------------------------------

    _HANDLERS = {
        "observed": _on_observed,
        "asserted": _on_asserted,
        "confirmed": _on_confirmed,
        "contradicted": _on_contradicted,
        "corrected": _on_corrected,
        "retracted": _on_retracted,
        "forbidden": _on_forbidden,
        "derived": _on_derived,
        "informed": _on_informed,
        "grant": _on_grant,
        "revoke": _on_revoke,
        "decayed": _on_decayed,
        "rehearsed": _on_rehearsed,
        "verified": _on_verified,
        "merged": _on_merged,
        "unmerged": _on_unmerged,
        "compressed": _on_compressed,
        "signal": _on_signal,
        "distilled": _on_distilled,
    }

    def _parse_payload(self, event: dict) -> dict:
        p = event.get("payload", "{}")
        if isinstance(p, str):
            return json.loads(p)
        return p

    def _find_existing(self, kind: str, key: dict, owner: str,
                       domain: str) -> Optional[dict]:
        """Find an existing active belief matching the natural key."""
        table_map = {
            "fact": "facts", "episode": "episodes", "note": "notes",
            "reference": "refs", "relationship": "relationships",
            "entity": "entities", "user_knowledge": "user_knowledge",
            "procedure": "procedures",
        }
        table = table_map.get(kind)
        if table is None:
            return None

        if kind == "fact":
            entity_id = key.get("entity_id", "")
            pred = key.get("predicate_canonical", "")
            qh = key.get("qualifiers_hash", "")
            rows = self.store.query_beliefs(
                table,
                "entity_id=? AND predicate_canonical=? AND qualifiers_hash=? AND owner=? AND domain=? AND status='active'",
                (entity_id, pred, qh, owner, domain)
            )
            return rows[0] if rows else None

        return None

    def _insert_belief(self, kind: str, b_id: str, key: dict, body: str,
                       confidence: float, event: dict, status: str = "active",
                       source_type: str = "extraction"):
        """Insert a belief into the appropriate table."""
        now = event.get("recorded_at", "")
        owner = event.get("owner", "default")
        domain = event.get("domain", "general")
        trust = event.get("trust_level", 2)
        provenance = json.dumps({
            "source_type": source_type,
            "source_event": event.get("event_id", ""),
            "extracted_by": "chronicle-v5",
            "extracted_at": now,
        })

        if kind == "fact":
            belief = {
                "belief_id": b_id,
                "entity_id": key.get("entity_id", ""),
                "attribute": key.get("attribute", ""),
                "predicate_canonical": key.get("predicate_canonical", ""),
                "value": body,
                "value_type": "string",
                "qualifiers": json.dumps(key.get("qualifiers", {})),
                "qualifiers_hash": key.get("qualifiers_hash", ""),
                "domain": domain, "owner": owner, "read_acl": "user_agents",
                "status": status, "salience": "normal",
                "criticality": "normal", "confidence": confidence,
                "trust_level": trust, "valid_from": now,
                "created_at": now, "last_seen_at": now,
                "fidelity": "verbatim", "utility": 0,
                "purpose_scope": '["*"]', "provenance": provenance,
                "verification": '{"status":"unverified"}',
            }
            self.store.upsert_belief("facts", belief)
        elif kind == "episode":
            belief = {
                "belief_id": b_id, "title": key.get("title", ""),
                "summary": body, "occurred_at": key.get("occurred_at", now),
                "session_ref": key.get("session_ref", ""),
                "domain": domain, "owner": owner, "read_acl": "user_agents",
                "status": status, "salience": "normal",
                "criticality": "normal", "confidence": confidence,
                "trust_level": trust, "valid_from": now,
                "created_at": now, "last_seen_at": now,
                "fidelity": "verbatim", "utility": 0,
                "purpose_scope": '["*"]', "provenance": provenance,
            }
            self.store.upsert_belief("episodes", belief)
        elif kind == "note":
            import hashlib
            body_hash = hashlib.blake2b(body.encode(), digest_size=16).hexdigest()
            belief = {
                "belief_id": b_id,
                "note_type": key.get("note_type", "belief"),
                "subject": key.get("subject", ""),
                "body": body, "body_hash": body_hash,
                "imperative": key.get("imperative", 0),
                "always_inject": key.get("always_inject", 0),
                "risk_tier": key.get("risk_tier", "low"),
                "domain": domain, "owner": owner, "read_acl": "user_agents",
                "status": status, "salience": "normal",
                "criticality": "normal", "confidence": confidence,
                "trust_level": trust, "valid_from": now,
                "created_at": now, "last_seen_at": now,
                "fidelity": "verbatim", "utility": 0,
                "purpose_scope": '["*"]', "provenance": provenance,
            }
            self.store.upsert_belief("notes", belief)
        elif kind == "entity":
            belief = {
                "belief_id": b_id,
                "type": key.get("entity_type", ""),
                "name": key.get("name", ""),
                "normalized_name": key.get("normalized_name", key.get("name", "").lower()),
                "aliases": json.dumps(key.get("aliases", [])),
                "domain": domain, "owner": owner, "read_acl": "user_agents",
                "fact_count": 0, "relationship_count": 0,
                "created_at": now, "last_seen_at": now,
            }
            self.store.upsert_belief("entities", belief)
        elif kind == "relationship":
            belief = {
                "belief_id": b_id,
                "source_id": key.get("source_id", ""),
                "predicate": key.get("predicate", ""),
                "target_id": key.get("target_id", ""),
                "domain": domain, "owner": owner, "read_acl": "user_agents",
                "status": status, "confidence": confidence,
                "trust_level": trust, "valid_from": now,
                "created_at": now, "provenance": provenance,
            }
            self.store.upsert_belief("relationships", belief)
        elif kind == "procedure":
            belief = {
                "belief_id": b_id,
                "name": key.get("name", ""),
                "params": json.dumps(key.get("params", [])),
                "steps": json.dumps(key.get("steps", [])),
                "success_criteria": json.dumps(key.get("success_criteria", [])),
                "domain": domain, "owner": owner, "read_acl": "user_agents",
                "status": status, "confidence": confidence,
                "trust_level": trust, "created_at": now, "last_seen_at": now,
                "purpose_scope": '["*"]', "provenance": provenance,
            }
            self.store.upsert_belief("procedures", belief)
        elif kind == "reference":
            belief = {
                "belief_id": b_id,
                "topic": key.get("topic", ""),
                "domain": domain, "owner": owner, "read_acl": "user_agents",
                "status": status, "trust_level": trust,
                "created_at": now, "purpose_scope": '["*"]',
                "provenance": provenance,
            }
            self.store.upsert_belief("refs", belief)

    def _confirm_belief(self, existing: dict, event: dict):
        """Increment confirm_count and raise confidence."""
        b_id = existing["belief_id"]
        new_count = existing.get("confirm_count", 0) + 1
        old_conf = existing.get("confidence", 0.8)
        # raw = base + 0.05 * min(confirm_count, 5)
        new_conf = min(old_conf + 0.05 * min(new_count, 5), 1.0)
        now = event.get("recorded_at", "")
        with self.store.transaction() as conn:
            conn.execute(
                "UPDATE facts SET confirm_count=?, confidence=?, last_confirmed_at=? WHERE belief_id=?",
                (new_count, new_conf, now, b_id)
            )

    def _confirm_belief_by_id(self, b_id: str, source_event: str, event: dict):
        row = self.store.get_belief("facts", b_id)
        if row:
            self._confirm_belief(row, event)

    def _supersede_belief(self, existing: dict, new_b_id: str, event: dict):
        """Supersede old belief with new."""
        old_id = existing["belief_id"]
        now = event.get("recorded_at", "")
        with self.store.transaction() as conn:
            conn.execute(
                "UPDATE facts SET status='superseded', valid_until=?, superseded_by=? WHERE belief_id=?",
                (now, new_b_id, old_id)
            )

    def _supersede_belief_by_id(self, b_id: str, event: dict):
        now = event.get("recorded_at", "")
        with self.store.transaction() as conn:
            conn.execute(
                "UPDATE facts SET status='superseded', valid_until=? WHERE belief_id=?",
                (now, b_id)
            )

    def _open_contradiction(self, existing_id: str, new_id: str, event: dict):
        """Open a contradiction record."""
        logger.info(f"Contradiction: existing={existing_id} vs new={new_id}")

    def _cascade_revision(self, b_id: str):
        """Retraction cascade (§9.3): retract all beliefs depending on b_id."""
        dependents = self.store.get_dependents(b_id)
        for dep in dependents:
            dep_b_id = dep["belief_id"]
            # Check if remaining supports still satisfy the rule
            remaining = self.store.get_justifications(dep_b_id)
            remaining_supports = [r for r in remaining if r["support"] != b_id]
            if not remaining_supports:
                # Retract
                with self.store.transaction() as conn:
                    for table in ["facts", "episodes", "notes", "refs", "relationships", "procedures"]:
                        conn.execute(f"UPDATE {table} SET status='retracted' WHERE belief_id=?",
                                     (dep_b_id,))
                # Record correction
                import datetime, uuid
                now = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")
                with self.store.transaction() as conn:
                    conn.execute(
                        "INSERT INTO corrections(id, belief_id, reason, correction_ref, propagated, created_at) "
                        "VALUES(?,?,?,?,?,?)",
                        (str(uuid.uuid4()), dep_b_id, "cascade_from_retraction", b_id,
                         json.dumps([b_id]), now)
                    )
                # Recurse
                self._cascade_revision(dep_b_id)
