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
   currently says. Nothing here writes a fact, an entity, or a link (I20). A
   name that matches is a candidate for adjudication, and candidates go to
   `pending_candidates` for a human/curation decision — never to an edge.
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
        """Record the row as an unadjudicated identity candidate (never a link)."""
        if len(self.pending_candidates) >= MAX_PENDING_CANDIDATES:
            return
        try:
            self.pending_candidates.append(provider.identity_candidate(hit))
        except Exception as e:
            logger.warning("federated: candidate capture failed: %s", e)

    def drain_candidates(self) -> List[Dict]:
        """Take the pending candidates (for a reviewer / curation job)."""
        out, self.pending_candidates = self.pending_candidates, []
        return out

    def enqueue_candidates_for_review(self, store) -> int:
        """Hand pending candidates to the curation queue for adjudication.

        Deliberately NOT called from `get_context`: retrieval is a read path.
        A caller that wants the review queue populated (a curation pass, a
        maintenance tool) calls this explicitly. Either way, nothing links an
        external row to a Chronicle entity without a decision.
        """
        n = 0
        for candidate in self.drain_candidates():
            try:
                store.enqueue_curation("federated_identity_review", candidate)
                n += 1
            except Exception as e:
                logger.warning("federated: enqueue candidate failed: %s", e)
        return n
