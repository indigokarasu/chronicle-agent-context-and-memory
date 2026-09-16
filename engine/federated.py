"""
Chronicle — Federated query channel (§g3).

When a query yields focus tokens, ask every declared local database the one
generic question Chronicle can ask any schema it has never seen: "does any text
column of any table LIKE any of these tokens?" Matching rows come back as
*projections with pointers*, and `RetrievalEngine.get_context` renders them as

    [FEDERATED <db>] <table>:<row_id> | col=val; col=val

after all Chronicle-native evidence, out of whatever budget is left over.

Four properties this module exists to preserve:

1. Generic. No deployment's database name, table name or column name appears
   here or in localdb.py. Databases are declared in config
   (`federation.local_dbs`); everything else is introspected at runtime.
2. Bounded. <=3 databases, <=5 tables each, <=5 rows per table, ONE statement
   per table. A federated read happens on the retrieval hot path against a
   database Chronicle does not own and cannot index, so the cost is bounded by
   construction, not by hope.
3. Never authoritative. A projection is a cache of what the external authority
   currently says. Nothing here writes a fact, an entity, or a link (I20) —
   nothing here writes AT ALL, because `query()` runs on the retrieval read
   path. A name that matches is noted in the in-memory `pending_candidates`
   list and never becomes an edge. The DURABLE adjudication queue is
   `link_candidates`, written by the federation sweep (`_task_federate_sweep`),
   which is the path that has an entity to adjudicate against; see
   `_note_candidate` for why this one does not.
4. Access-checked. Every read goes through `access.can_read` with the DB's
   declared read_acl, so a principal from another user gets nothing, and a
   database declared owner_only stays owner_only.
"""

from __future__ import annotations

import logging
from typing import Dict, List, Optional

from .localdb import (LocalDBProvider, MAX_ROWS_PER_TABLE, MAX_TABLES,
                      providers_from_config)

logger = logging.getLogger("chronicle.federated")

MAX_DBS = 3
MAX_PENDING_CANDIDATES = 200


class FederatedChannel:
    """Generic, bounded, read-only query fan-out across declared local DBs."""

    def __init__(self, cfg=None, providers: Optional[List[LocalDBProvider]] = None):
        self.cfg = cfg
        # Providers are built once and reused: each caches its introspected
        # schema, so a warm channel spends one statement per searched table.
        if providers is None:
            providers = providers_from_config(cfg)
        self.providers = list(providers)[:MAX_DBS]
        # Adjudication inbox (rule: identity is decided, never inferred). Bounded
        # and in-memory: get_context is a READ path and does not write.
        self.pending_candidates: List[Dict] = []

    def query(self, focus_tokens, principal: str, owner: str,
              max_dbs: int = MAX_DBS) -> List[Dict]:
        """Search every available DB for rows matching any focus token.

        Returns pointer-shaped hits, in declaration order:
            {provider, table, row_id, external_id, projection, block}
        `block` is the render-ready body for a [FEDERATED <provider>] line.
        """
        hits: List[Dict] = []
        tokens = [t for t in (focus_tokens or []) if t]
        if not tokens or not self.providers:
            return hits
        for provider in self.providers[:max_dbs]:
            if not provider.is_available():
                logger.info("federated: %s unavailable (%s)", provider.name, provider.db_path)
                continue
            try:
                found = provider.search(tokens, owner=owner, principal=principal,
                                        max_tables=MAX_TABLES, max_rows=MAX_ROWS_PER_TABLE)
            except Exception as e:
                # One bad database never breaks retrieval for the others.
                logger.warning("federated: %s search failed: %s", provider.name, e)
                continue
            for hit in found:
                if not hit.get("projection"):
                    continue
                hit = dict(hit)
                hit["block"] = self.render_block(hit)
                hits.append(hit)
                self._note_candidate(provider, hit)
        return hits

    @staticmethod
    def render_block(hit: Dict) -> str:
        """The body of a [FEDERATED <db>] line: `<table>:<row_id> | col=val; ...`.

        The identity prefix is the point: a projection without it names a
        database, not a row, so it can be neither re-read nor adjudicated. When
        the row has no addressable identity at all the prefix says so rather
        than quietly implying one.
        """
        pointer = hit.get("external_id") or ("%s:?" % (hit.get("table") or "?"))
        return "%s | %s" % (pointer, hit.get("projection") or "")

    def _note_candidate(self, provider: LocalDBProvider, hit: Dict):
        """Record the row as an unadjudicated identity candidate (never a link).

        In-memory, bounded, and READ-ONLY with respect to the store, because the
        only caller is `query()` and `query()` is on the retrieval hot path.

        There is deliberately no durable queue behind this. A hit here is a row
        whose text matched a focus token; it carries `entity_id: None` by
        construction (LocalDBProvider.identity_candidate) because nothing has
        proposed WHICH Chronicle entity it might be — so there is no pair for a
        reviewer to accept or reject. The durable adjudication queue is
        `link_candidates`, fed by the federation sweep (`_task_federate_sweep`),
        which matches an EXISTING entity against an external row and therefore
        has both halves of the decision to offer.

        A13 note: an `enqueue_candidates_for_review(store)` used to sit here and
        push these into curation as a `federated_identity_review` job. The task
        name was not in the curation_jobs CHECK and no handler existed, so the
        method could only ever raise IntegrityError; it had no caller. It was
        removed rather than completed, because completing it would have built a
        second review queue holding half a decision.
        """
        if len(self.pending_candidates) >= MAX_PENDING_CANDIDATES:
            return
        try:
            self.pending_candidates.append(provider.identity_candidate(hit))
        except Exception as e:
            logger.warning("federated: candidate capture failed: %s", e)
