"""
Chronicle — Identity evidence: split / merge CANDIDATES (§E7, issue #8).

Identity is adjudicated, never inferred — the same hard rule the federation
sweep already obeys (§14.2, I20). One real-world name can be two people (split
risk) and two different-looking records can be one person (merge risk), so this
module treats BOTH directions as questions, never answers. Everything it writes
is a row in `identity_candidates` waiting for a human or a host model to decide.
It never merges an entity, never splits one, never sets `merged_into`, and never
touches a belief row. Adjudication itself is out of scope.

What it maintains
-----------------
Per entity, a RUNNING centroid of mention-context vectors — the vector Chronicle
already embeds on the write path for the belief that mentioned the entity. The
persisted state is (sum vector, n), so folding a mention in costs one O(dims)
add and the centroid is NEVER recomputed over all mentions.

The state is keyed to the embedding model that produced it: a model change makes
the accumulated sum incomparable geometry (§24.4's "hash vectors live in an
incomparable geometry" problem), so the row is reset rather than mixed.

What it proposes
----------------
* split — the new mention's cosine to the entity's centroid-so-far is BELOW
  `identity.split_below` (default 0.30): evidence that one entity id is carrying
  two different subjects. The mention is folded in anyway — withholding it would
  be deciding the question this row exists to ask.
* merge — two entities' centroids are ABOVE `identity.merge_above` (default
  0.90): evidence that two entity ids are carrying one subject.

Bounding the pairwise check
---------------------------
A merge check comparing every entity against every other would be O(N²) per
write. This one compares the ONE entity just touched against at most
`identity.merge_scan_limit` (default 50) OTHER centroids, chosen as the most
recently updated ones — the working set of the batch currently being processed,
ordered deterministically (updated_at DESC, entity_id DESC) so a replay sees the
same candidate set. Cost per write is O(merge_scan_limit · dims) regardless of
how many entities the store holds. An entity never co-active with its twin is
never compared: this queue is evidence, not a completeness proof.

Degradation
-----------
No embedder — or a degraded one (§24.4) — means no mention vector ever reaches
this module, so no centroid row and no candidate row is written and nothing
raises. The feature is entirely inert, as every Ladder-9 feature must be.
"""

from __future__ import annotations

import logging

from .embeddings import _l2_normalize, cosine, pack, unpack

logger = logging.getLogger("chronicle.identity")

SPLIT = "split"
MERGE = "merge"

# Defaults, mirrored in config.DEFAULTS["identity"]. Named here too so the module
# is usable with cfg=None (the bare Reducer(store) construction used by tests).
DEFAULT_SPLIT_BELOW = 0.30
DEFAULT_MERGE_ABOVE = 0.90
DEFAULT_MERGE_SCAN_LIMIT = 50


def _cfg(cfg, path, default):
    if cfg is None:
        return default
    try:
        val = cfg.get(path, default)
    except Exception:  # a config object of an unexpected shape must not break a write
        return default
    return default if val is None else val


def observe_mention(store, cfg, model, entity_id, mention_ref, vec, now):
    """Fold ONE mention-context vector into `entity_id`'s centroid and record any
    identity candidates it implies.

    Returns a summary dict — `{"split": sim|None, "merges": [(other_id, sim)],
    "n": mentions_after}` — purely for tests and debug; callers on the write path
    ignore it. Never raises: an identity signal must not be able to roll back a
    durable capture (I12), so every failure degrades to "no candidate".

    `now` is the EVENT's timestamp, never wall-clock: the reducer is a pure fold
    over the log (§7.2, I3), so replaying the log reproduces the same centroid
    sums and the same candidate SET at the same timestamps.

    Not literally byte-for-byte, though, and the difference is worth stating.
    identity_candidates.id is a uuid4 (see store.enqueue_identity_candidate), so
    the id column differs on every replay; what is stable is the dedupe key the
    UNIQUE index is built on — (kind, entity_id, other_id, mention_ref) — which
    is what any consumer should join on. And `status`/`resolved_at` record an
    ADJUDICATION, which is not in the event log at all: resolving a candidate is
    a projection-only edit, so replaying from scratch returns every row to
    'pending'. Adjudication outcomes must be preserved outside this projection
    if they need to survive a rebuild.
    """
    out = {"split": None, "merges": [], "n": 0}
    if not entity_id or not vec:
        return out
    if not _cfg(cfg, "identity.enabled", True):
        return out
    try:
        return _observe(store, cfg, model, entity_id, mention_ref, vec, now, out)
    except Exception as e:  # I12: identity evidence is never worth failing a capture
        logger.debug("identity evidence skipped for %s (%s)", entity_id, e)
        return out


def _observe(store, cfg, model, entity_id, mention_ref, vec, now, out):
    split_below = float(_cfg(cfg, "identity.split_below", DEFAULT_SPLIT_BELOW))
    merge_above = float(_cfg(cfg, "identity.merge_above", DEFAULT_MERGE_ABOVE))
    scan_limit = int(_cfg(cfg, "identity.merge_scan_limit", DEFAULT_MERGE_SCAN_LIMIT))

    v = _l2_normalize([float(x) for x in vec])
    dims = len(v)
    if not dims:
        return out
    model = model or ""

    prior = store.get_entity_centroid(entity_id)
    # A different model (or width) means the accumulated sum is in another
    # geometry; comparing across it is meaningless, so start over rather than
    # silently mixing incomparable vectors.
    if prior and (prior.get("model") != model or int(prior.get("dims") or 0) != dims):
        logger.info("identity: centroid for %s reset (model %r -> %r)",
                    entity_id, prior.get("model"), model)
        prior = None

    total = [0.0] * dims
    n = 0
    if prior:
        prior_sum = unpack(prior.get("sum_vec"))
        if len(prior_sum) == dims:
            total = list(prior_sum)
            n = int(prior.get("n") or 0)

    # -- split evidence: does this mention look like the same subject? --------
    if n > 0:
        sim = cosine(v, _l2_normalize(total))
        if sim < split_below:
            out["split"] = sim
            store.enqueue_identity_candidate(SPLIT, entity_id, "", mention_ref, sim, now)

    # -- fold it in (running sum + count; no recomputation over mentions) -----
    for i in range(dims):
        total[i] += v[i]
    n += 1
    out["n"] = n
    store.put_entity_centroid(entity_id, pack(total), n, dims, model, now)

    # -- merge evidence: bounded scan over the recently-touched working set ---
    centroid = _l2_normalize(total)
    for row in store.recent_entity_centroids(exclude_id=entity_id, model=model, dims=dims,
                                             limit=scan_limit):
        other_sum = unpack(row.get("sum_vec"))
        if len(other_sum) != dims or not int(row.get("n") or 0):
            continue
        sim = cosine(centroid, _l2_normalize(list(other_sum)))
        if sim <= merge_above:
            continue
        other_id = row.get("entity_id") or ""
        if not other_id or _is_merged(store, other_id) or _is_merged(store, entity_id):
            continue  # an entity already folded into another is not a proposal
        # Canonical pair order, so (A,B) and (B,A) are ONE queue row.
        a, b = sorted([entity_id, other_id])
        out["merges"].append((other_id, sim))
        store.enqueue_identity_candidate(MERGE, a, b, "", sim, now)
    return out


def _is_merged(store, entity_id) -> bool:
    ent = store.get_belief("entities", entity_id)
    return bool(ent and ent.get("merged_into"))
