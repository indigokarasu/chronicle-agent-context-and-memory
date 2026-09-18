"""
Chronicle — Curation pipeline (§17).

A worker claims the lowest-id ready job and writes every result via
`append_event` (no special path). Heuristics are a pre-filter + sanity bound,
never a silent writer.

Where the jobs come from, since a list of handlers reads like a pipeline that
runs itself and this one does not:
  * `extract` (and the `canonicalize`/`digest` it enqueues per subject),
    `session_summarize`, `journal_ingest`, `embed`, `verify` and
    `federate_sweep` are EVENT-DRIVEN — a capture, a session ending, a
    high-criticality fact, a deferred vector, a health run.
  * `decay`, `consistency`, `health`, `backfill_sweep` and `identity` are
    SCHEDULED, by engine/scheduler.py, on the hook cadence (§17.4). Before
    ladder-10 A3 nothing enqueued them at all; `identity` stayed unscheduled
    one rung longer because its handler auto-merged entities on an exact name
    match, and it joined the cadence in A8 once that became a candidate.
  * `derive`, `consolidate` and `reextract` have handlers and NO producer, on
    purpose; `scheduler.UNSCHEDULED` records the reason for each.

Every task name the curation_jobs CHECK admits has a handler here, and every
handler's name is admitted by the CHECK — asserted by
tests/test_task_check_handler_consistency.py, because for three values that was
not true. `route` and `criticality` were CHECK-listed with no handler in any
build (an enqueue completed as 'no_handler' and looked like maintenance);
`contradiction` was a second name for `consistency`. All three were retired from
the schema in ladder-10 A13 (store.RETIRED_CURATION_TASKS), which is why they
are no longer listed as merely-unscheduled above either.
"""

from __future__ import annotations

import json
import logging
import os
import urllib.parse

from . import access, sweeps
from . import entities as ents
from . import speaker as spk
from .embeddings import (
    EmbeddingsUnavailable,
    cosine,
    embedder_model_tag,
    expected_blob_len,
    is_usable_model_tag,
    pack,
    unpack,
)
from .reducer import (
    belief_vector_text,
    observed_vector_text,
    projection_vector_text,
    session_vector_text,
)
from .serialize import belief_id as compute_belief_id
from .store import (
    KIND_TABLE,
    TASK_CLASSES,
    drain_quotas,
    now_iso,
    tasks_in_class,
)

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
# Rows one federate_sweep run may READ from one provider — ingest and rescan
# share it, so a huge foreign table costs the same bounded work every run (§14).
_FEDERATE_ROW_BUDGET = 200
# Entities one name collision may propose for review. A name matching hundreds of
# entities is not evidence of anything; it is noise, and it is capped like noise.
_FEDERATE_MAX_CANDIDATES = 10
# Merge candidates ONE exact-name collision may propose for review (ladder-10 A8),
# for the same reason and with the same number as the federation cap above: a name
# shared by hundreds of entities is noise, and 200 pending questions nobody can
# answer is a queue nobody reads.
_IDENTITY_MAX_CANDIDATES_PER_NAME = 10
# Session-summary caps (§E6): per-episode line stays at the pre-E6 single-blob
# cap so a homogeneous (one-episode) session renders byte-identical to today.
# The whole-summary cap is raised past that so a genuinely multi-episode
# session isn't squeezed back down to one episode's worth of text.
_SESSION_EPISODE_MAX_CHARS = 1000
_SESSION_SUMMARY_MAX_CHARS = 4000


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


class _ProviderOffline(Exception):
    """A federated provider that cannot be read right now (§14.2, I18).

    Distinct from a failure on purpose: an absent provider is a NORMAL state for
    a system built to reference things it does not own. Pointers stay valid and
    serve from cache, the sweep skips that provider, and the run still succeeds —
    Chronicle degrades, it does not break."""


# source_type → memory domain (governs decay/contradiction, §8.4)
_DOMAIN = {"user_direct": "user", "session_transcript": "user", "rescue_extraction": "user",
           "agent_memory_write": "agent", "delegation": "agent", "ocas_journal": "user",
           "inference": "user"}


def domain_for(source_type: str) -> str:
    return _DOMAIN.get(source_type, "general")


def _accepts_lines(extractor) -> bool:
    """Whether a (possibly third-party) extractor takes the `lines` attribution.
    One written to the older interface still runs; the no-human gate in
    _task_extract has already kept automation-only events away from it."""
    import inspect
    try:
        params = inspect.signature(extractor.extract).parameters
    except (TypeError, ValueError):
        return False
    return "lines" in params or any(p.kind is inspect.Parameter.VAR_KEYWORD
                                    for p in params.values())


# -- topic-shift episode boundaries (§E6, curation.topic_shift_threshold) --
#
# Pure functions, kept free of CurationWorker/store so the boundary rule is
# directly unit-testable against hand-built vectors (no ChronicleCore, no
# embedder, no DB) the same way E3's _rerank blend is.

def session_episode_boundaries(vectors: list, threshold: float) -> list:
    """Split one session's ordered per-event embeddings into episodes.

    `vectors` holds one entry per event in session order: a list[float]
    embedding, or None where an event has no vector yet (deferred embed,
    forbidden-content redaction, etc.). Returns the 0-based start index of
    each episode, always beginning with 0 for any non-empty input.

    The comparison is against the nearest PRECEDING event that does have a
    vector, not strictly i-1 -- a lone missing vector must not silently
    collapse the run into one episode, and must not itself count as a shift
    either direction. Consecutive cosine similarity below `threshold` opens a
    new episode; the threshold is an absolute floor (§27), not a rolling
    baseline, so a single sharp topic change is caught but does not shift the
    baseline for what follows it.
    """
    if not vectors:
        return []
    boundaries = [0]
    prev = vectors[0]
    for i in range(1, len(vectors)):
        v = vectors[i]
        if v is not None:
            if prev is not None and cosine(prev, v) < threshold:
                boundaries.append(i)
            prev = v
    return boundaries


def group_by_boundaries(items: list, boundaries: list) -> list:
    """Slice `items` into consecutive runs starting at each index in
    `boundaries` (ascending, first entry 0). Empty/degenerate boundaries
    (falsy) yield one run -- the whole list -- matching the pre-E6 single-
    episode behavior."""
    if not items:
        return []
    bounds = boundaries or [0]
    return [items[start:(bounds[i + 1] if i + 1 < len(bounds) else len(items))]
            for i, start in enumerate(bounds)]


class CurationWorker:
    def __init__(self, core):
        self.core = core
        self.store = core.store
        self.cfg = core.cfg

    # -- loop --------------------------------------------------------------

    def run_once(self, tasks=None) -> bool:
        """Claim and run one job. `tasks` restricts the claim to one fairness
        class's task values (§A7); None means any task, the pre-A7 behavior
        every direct caller still gets."""
        job = self.store.claim_curation_job(tasks=tasks)
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

    # -- fair drain (§A7) --------------------------------------------------

    def _drain_budget(self, max_jobs) -> int:
        """The per-turn job budget. `max_jobs=None` reads
        `curation.drain.per_turn` (default 16), which is what core.tick() now
        passes; an explicit number (process_pending's 1000, a test's 5) wins."""
        if max_jobs is not None:
            return max(0, int(max_jobs))
        try:
            return max(0, int(self.cfg.get("curation.drain.per_turn", 16)))
        except (TypeError, ValueError):
            return 16

    @staticmethod
    def _share(raw, default: float) -> float:
        try:
            return max(0.0, float(raw))
        except (TypeError, ValueError):
            return default

    def _drain_shares(self) -> dict:
        """Declared per-class weights, read as three scalar config keys so each
        one is individually greppable and individually auditable (a nested dict
        read as one blob reports as unwired, and A12 audits config honesty).

        The `self.cfg.get("<key>", ...)` calls are written out literally rather
        than looped over a list of paths: scripts/audit_config.py finds a key by
        matching that exact form, so a loop — or a local helper taking the path
        — makes a wired key report as dormant. The audit is only worth having if
        the code stays in the shape it can see."""
        return {
            "write_path": self._share(
                self.cfg.get("curation.drain.share_write_path", 0.5), 0.5),
            "embed": self._share(
                self.cfg.get("curation.drain.share_embed", 0.3), 0.3),
            "maintenance": self._share(
                self.cfg.get("curation.drain.share_maintenance", 0.2), 0.2),
        }

    def drain(self, max_jobs=None) -> int:
        """Run up to `max_jobs` jobs, apportioned across task classes so no one
        class's backlog can starve another (§A7).

        THE FAILURE THIS REPLACES: `claim_curation_job` is strict FIFO by id and
        `drain` used to take whatever it handed back. One heal run enqueues an
        embed job per stale vector — 105k of them on the live store — and every
        `extract` enqueued afterwards sits behind all of them. At 16 jobs a turn
        that is ~6,500 turns before the next new turn is read at all. Extraction
        is the premise's write path; it stopping is not a slowdown, it is the
        system not working.

        THE SHAPE: weighted round-robin over classes, FIFO within a class.
        `drain_quotas` splits the budget by the configured shares with a
        one-job floor, then this loop serves the classes in rounds, taking at
        most one job per class per round. A class that runs dry hands its unused
        quota back: the second phase spends whatever is left on whoever still
        has work, in class order, so fairness never costs throughput on an
        uncontended queue — the common case, where this is exactly the old
        behavior.

        Round-robin rather than "drain class A's quota, then B's" because the
        two differ when a handler ENQUEUES: an extract that queues a digest
        should not have that digest wait behind the whole embed quota."""
        budget = self._drain_budget(max_jobs)
        if budget <= 0:
            return 0
        quotas = drain_quotas(budget, self._drain_shares())
        classes = [c for c in TASK_CLASSES if quotas.get(c, 0) > 0]
        tasks = {c: tasks_in_class(c) for c in TASK_CLASSES}
        left = dict(quotas)
        done = 0
        # Phase 1: rounds of at most one job per class, up to each class's quota.
        while done < budget:
            progressed = False
            for c in classes:
                if left[c] <= 0 or done >= budget:
                    continue
                if self.run_once(tasks=tasks[c]):
                    left[c] -= 1
                    done += 1
                    progressed = True
                else:
                    left[c] = 0          # class is empty for this drain
            if not progressed:
                break
        # Phase 2: work conservation. Unused quota is not thrown away — it goes
        # to whatever still has pending work, in class order. A class whose
        # share is 0 is DEPRIORITISED, not disabled: it drains here, after every
        # class with a positive share has had its own quota.
        if done < budget:
            for c in list(TASK_CLASSES):
                while done < budget and self.run_once(tasks=tasks[c]):
                    done += 1
        return done

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
        # Who said each line (engine/speaker.py): the spans recorded at capture,
        # or the legacy reading, which never assumes the user. Memory about the
        # user comes only from the user's own words, so an event with none of
        # them is left raw-indexed for recall and extracts nothing.
        lines = spk.attribute_lines(p, session_id=ev.get("session_id") or "",
                                    actor=ev.get("actor") or "")
        if source_type != "agent_memory_write" and not spk.has_human(lines):
            self.store.record_extraction(eid, version, {"skipped": "no_human_speaker"}, 0, "skip")
            self._advance_watermark(ev)
            return
        if source_type == "agent_memory_write":
            # An explicit save by the agent (on_memory_write) is the agent's own
            # deliberate record, kept under the agent domain; its text is read as
            # written.
            lines = [(ln, spk.HUMAN) for ln in excerpt.split("\n") if ln.strip()]
        domain = domain_for(source_type)
        owner = ev["owner"]
        kwargs = {"source_event": eid, "owner": owner, "domain": domain,
                  "session_id": ev.get("session_id") or ""}
        if _accepts_lines(self.core.extractor):
            kwargs["lines"] = lines
        result = self.core.extractor.extract(excerpt, **kwargs)
        # Every item that survives routing becomes an `asserted` event whose reduce
        # embeds its body — one blocking round trip each against a networked
        # backend, which is where this job spends nearly all of its wall clock. The
        # items are all in hand here, so fetch their vectors together. Cache only:
        # _emit_item and the reduce are unchanged, and a miss just embeds singly.
        self.core.reducer.prefetch_vectors(
            [{"type": "asserted", "payload": it} for it in result.items
             if it.get("route") != "skip"])
        # A15: a SET for dedupe, but never iterated as one -- see
        # `ordered_subjects` below. Membership is order-free; iteration is not.
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
        # A15 (determinism sibling of the F1 query-text bug): `subjects` is a
        # set, and CPython randomises string hashing per process, so ITERATING
        # it -- which both consumers below do -- ordered this function's writes
        # differently in every process:
        #
        #   * `derive_for_subject` appends `derived` events, so the seq and
        #     prev_head of everything downstream of them moved with the shuffle;
        #   * `enqueue_curation("digest", ...)` fixes the job ids that decide
        #     which entity is digested first;
        #   * `list(subjects)` is STORED, as the canonicalize job's payload, and
        #     `enqueue_curation` dedupes on `json.dumps(payload, sort_keys=True)`
        #     -- sort_keys orders the KEYS, not a list VALUE -- so the same
        #     extraction produced a different dedupe key in every process and the
        #     collapse that key exists for silently stopped collapsing.
        #
        # Measured on this tree before the fix: five PYTHONHASHSEED values over
        # one six-subject transcript gave five different digest orders and five
        # different canonicalize payloads.
        #
        # Sorted once, at the boundary, and both consumers read the SAME list --
        # two sorts could drift. The key tolerates a None entity_id (an item
        # whose subject grounding `_emit_item` rejected still lands here) rather
        # than filtering it, so the payload keeps exactly the members it always
        # had; only their order is now fixed.
        ordered_subjects = sorted(subjects, key=lambda s: (s is None, s or ""))
        # Inline derive for touched subjects (guarded; §9.4).
        for subj in ordered_subjects:
            if subj:
                self.core.derivation.derive_for_subject(subj, self.core.active_principal)
                # Consolidation digest (§u2), enqueued unconditionally: the handler
                # owns the >=3-fact threshold, so extraction never counts facts.
                self.store.enqueue_curation("digest", {"entity_id": subj})
        # Canonicalize newly seen predicates.
        self.store.enqueue_curation("canonicalize", {"subjects": ordered_subjects})

    def _emit_item(self, item, ev, owner, domain, source_type, version):
        kind = item.get("kind", "fact")
        key = item.get("key", {})
        if kind == "fact":
            # Subject hygiene invariant (§15.8, issue #5): reject before the
            # fact ever reaches the durable log -- never in the reducer's
            # replay fold, which must stay pure over whatever is already
            # logged (I3). A dropped item just doesn't get logged (I18: never
            # fails the whole extraction task over one bad item).
            try:
                access.validate_subject_grounding(
                    key.get("entity_id", ""), key.get("attribute", key.get("predicate_canonical", "")))
            except ValueError as e:
                logger.warning("chronicle: dropped fact with bad subject grounding: %s", e)
                return
        if kind == "entity":
            # The same bar the extractor applies, at the boundary that writes the
            # log: a pronoun or half a sentence is not an entity (engine/entities.py).
            name = key.get("name") or item.get("body") or ""
            if not ents.plausible_name(name):
                logger.warning("chronicle: dropped entity with an implausible name: %r", name[:80])
                return
        risk = item.get("key", {}).get("risk_tier", "low")
        # Risk-tiered application (§16.4): behavior-changing high-risk → draft + review.
        status = item.get("status", "active")
        if kind == "note" and item.get("key", {}).get("note_type") in ("norm", "procedure"):
            if risk == "high":
                status = "draft"
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
        """Predicate schema induction (§17): ensure predicates table + infer cardinality.

        Two §A9 changes, and the second is the one that matters:

        1. Resumable. Was a 5000-row unordered prefix of `facts`, so on a large
           store predicates whose facts sat past the prefix were never given a
           row in `predicates` — and the sweep reported success. It now pages
           over DISTINCT `predicate_canonical` with a persisted cursor, so a lap
           reaches every predicate in the store.

        2. Cardinality is asked of the DATABASE, not of the page. The old code
           inferred `multi` by grouping only the rows it had read; with any kind
           of paging that becomes actively wrong (a predicate's two values for
           one entity can land in different pages, and the sweep would write
           `single` — permanently, since the upsert is guarded on the predicate
           being absent). `predicate_has_multi_value` answers over all active
           facts and stops at the first witness."""
        from .extraction import canonical_predicate
        page = sweeps.next_distinct_page(self.store, self.cfg, "canonicalize", "facts",
                                         "predicate_canonical", "status='active'", ())
        for pred in page.rows:
            if not pred or self.store.get_predicate(pred) is not None:
                continue
            _, seed_card = canonical_predicate(pred)
            multi = self.store.predicate_has_multi_value(pred)
            cardinality = "multi" if (multi and seed_card != "single") else seed_card
            self.store.upsert_predicate(pred, pred, cardinality)
        return sweeps.commit(self.store, page)

    def _task_consolidate(self, payload):
        self._task_canonicalize(payload)
        self.core.derivation.materialize_all(self.core.active_principal)

    def _task_identity(self, payload):
        """Exact name collisions -> merge CANDIDATES, on a resumable page
        (§17, §E7, ladder-10 A8 x A9).

        A8 -- WHAT IT DOES. This handler used to MERGE. Every entity sharing
        (normalized_name, owner, domain) with another was folded into whichever
        one the scan happened to see first, by appending a `merged` event
        carrying `evidence: exact_name_match`. That is an identity decision
        INFERRED from a similarity, and the premise of this codebase is that
        identity is adjudicated, never inferred.

        The project's own worked example is the entire argument.
        "Robin Placeholder" is ONE person recorded twice — a split risk, if you
        assume difference.
        Two DIFFERENT people are both named "Pat Testley" — a merge risk, if
        you assume sameness. An exact name match is exactly the second case, and
        this sweep answered it in the wrong direction on a timer. Worse, the
        answer does not come back: supersession can reverse a belief because the
        old row survives with `status` flipped, but `merged_into` collapses two
        provenance chains into one, so the fact that the store ever held two
        distinct people is gone from the projection.

        A name is EVIDENCE, not identity. So the collision is routed into E7's
        existing adjudication queue (`identity_candidates`, kind='merge') and
        nothing is applied: no `merged` event, no `merged_into` write, no entity
        row touched. The queue row is a QUESTION.

        What stays: an explicit `merged` event still merges (reducer._on_merged),
        because that event records an adjudication a principal made. Only the
        INFERRED path is gone.

        This reuses E7's machinery whole rather than building a parallel queue —
        including its dedupe key (kind, entity_id, other_id, mention_ref). The
        pair goes in sorted order with an empty mention_ref, the same key
        identity.observe_mention's centroid-driven proposal uses, so ONE entity
        pair is ONE pending question however it was raised; and because
        enqueue_identity_candidate is INSERT OR IGNORE, re-running this sweep
        keeps the original row — decision included — instead of duplicating the
        question or resurrecting an answered one.

        A9 -- HOW MUCH IT LOOKS AT, and the two are orthogonal: A9 changed the
        SELECTION, A8 changed the VERDICT. It was
        `query_beliefs("entities", "merged_into IS NULL", limit=5000)` — an
        unordered 5000-row prefix, so on a store with more entities than that
        the same head was re-examined every run and duplicates further in were
        never even looked at, while the job completed successfully.

        Identity is GROUP-shaped: the unit of work is every entity sharing a
        normalized name, and a rowid page that split such a group would hide the
        very collision this sweep exists to notice — a bounded sweep returning a
        WRONG answer, which is worse than the silent truncation. So the cursor
        runs over DISTINCT `normalized_name` and each page's names are then
        loaded whole. Pace: `sweeps.budgets.identity` if set, else the shared
        `sweeps.row_budget`. The page's processed/remaining/bounded report is
        RETURNED, which is what tells a caller the sweep is still behind.

        Composing them matters more now than before A8: a bounded sweep that
        MERGED left a wrong, irreversible write behind on the rows it did reach.
        A bounded sweep that QUEUES leaves a question behind, and the cursor
        means the ones it has not reached yet are still coming.
        """
        page = sweeps.next_distinct_page(self.store, self.cfg, "identity", "entities",
                                         "normalized_name", "merged_into IS NULL", ())
        ents = self.store.beliefs_for_values("entities", "normalized_name", page.rows,
                                             "merged_into IS NULL", ())
        by_name = {}
        for e in ents:
            by_name.setdefault((e["normalized_name"], e["owner"], e["domain"]), []).append(e)
        queued = 0
        for group in by_name.values():
            if len(group) < 2:
                continue
            # Neither beliefs_for_values nor the old query_beliefs has an
            # ORDER BY, so which entity anchors the group must not be decided by
            # scan order: sort, then propose (anchor, other) pairs. Star, not
            # all-pairs — k-1 questions express "these k records may be one
            # subject" without an O(k^2) queue.
            ids = sorted(e["belief_id"] for e in group)
            anchor = ids[0]
            for other in ids[1:1 + _IDENTITY_MAX_CANDIDATES_PER_NAME]:
                a, b = sorted([anchor, other])
                # similarity=1.0: the NAMES are identical. It is a score on the
                # evidence, never a verdict on the entities.
                if self.store.enqueue_identity_candidate("merge", a, b, "", 1.0):
                    queued += 1
        if queued:
            logger.info("identity: queued %d exact-name merge candidate(s) for "
                        "adjudication (nothing merged)", queued)
        return sweeps.commit(self.store, page)

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
        """The two time-based sweeps: session reaping (§12.4) and belief decay (§20).

        `Reaper.run()` had no caller anywhere in the tree — only
        `startup_recovery()` was ever invoked — so a session that went quiet
        without a clean exit stayed 'active' forever and its observed events
        were never finalized. It runs here, as a curation job, on the same
        queue as every other piece of maintenance, rather than from a thread.

        `sweep` selects one half, because the two want very different cadences:
        a session is stale after ~45 minutes, while fidelity decay is supposed
        to take months and takes one rung off the ladder per sweep. An absent
        `sweep` runs both — that is what a hand-enqueued `decay` job (a
        dashboard button, a test) has always meant, and it stays true.

        The decay half's report is RETURNED, not swallowed: decay_sweep()'s
        processed/remaining/bounded is what tells a caller the ladder is still
        behind (§A9), and the persisted copy reaches health.run() via
        store.list_sweep_states(). A reaper-only run has no such report and
        returns None, which is the honest answer — the reaper is not a paced
        sweep and has no cursor to be behind on."""
        sweep = payload.get("sweep") or "all"
        if sweep in ("all", "reaper"):
            self.core.reaper.run()
        if sweep in ("all", "beliefs"):
            return self.core.forgetting.decay_sweep()
        return None

    def _task_consistency(self, payload):
        """The CSP sweep (§21). Also the only name for it: `contradiction` was a
        second task value whose handler made this identical call, so an operator
        could queue the same sweep under two names and a scheduler could run it
        twice for one answer. Retired in A13; existing `contradiction` rows are
        re-tasked to this one by the schema_version-13 migration."""
        self.core.health.consistency_sweep()

    def _task_health(self, payload):
        self.core.health.run()

    def _task_reextract(self, payload):
        """Replay extraction at the current version (§16.5), resumably (§A9).

        The old shape was the worst instance of this defect in the engine. It
        loaded EVERY observed event (89,562 of them on the live store), sorted
        the whole list in Python, sliced the first 200 — and those 200 are the
        oldest events, which have had an extraction at every version for years.
        So each run materialised ~90k rows, enqueued nothing, and completed
        successfully; every event that actually needed re-extraction sat past
        the slice and was unreachable. Exactly the A7 heal failure: re-select
        the same prefix, find it already done, achieve nothing, forever.
        Measured on a store shaped like the live one (89,562 observed events,
        67,000 of them already extracted at the current version): the old shape
        took 221 ms to select 0 events that needed work, out of 22,562 that did.

        Both halves are fixed. Eligibility ("no extraction at THIS version") is
        now a SQL predicate rather than a post-filter, so the page is 200 events
        that need work instead of 200 that don't; and the rowid cursor means run
        N+1 starts past run N. `remaining` is then the true size of the backlog
        — the number nobody could see before.

        `payload["limit"]` still wins when given (a caller asking for a specific
        batch), otherwise the pace is `sweeps.budgets.reextract`."""
        version = self.core.extractor.version
        page = sweeps.next_row_page(
            self.store, self.cfg, "reextract", "events",
            "type='observed' AND event_id NOT IN "
            "(SELECT observed_event FROM extractions WHERE extractor_version=?)",
            (version,), budget=payload.get("limit"))
        for ev in page.rows:
            self.store.enqueue_curation("extract", {"event_id": ev["event_id"],
                                                    "session_id": ev.get("session_id")})
        report = sweeps.commit(self.store, page)
        logger.info("reextract: enqueued %d event(s) at version %s, %d still awaiting",
                    report["processed"], version, report["remaining"])
        return report

    def _task_embed(self, payload):
        """Deferred vector write (§24.4): the backend was unreachable when this
        event/belief was reduced, so the work was queued instead of hashed.

        Idempotent — a vector already present means an earlier pass (or a rebuild)
        won the race, so this is a no-op. While the backend is still down the job
        is deferred again, UNBOUNDED: an outage is recoverable and visible in the
        job queue, and dropping the vector would leave a permanent hole no later
        pass looks for. Errors from a reachable model are bounded instead — they
        may never clear, and a poison payload must not churn forever.

        THE TEXT IS RE-RESOLVED HERE, FOR EVERY KIND (A0g N1), through the
        reducer's four `*_vector_text` accessors -- the same function objects the
        heal and scripts/migrate_vectors.py use -- and NEVER embedded from the job
        payload. The payload is a snapshot taken at enqueue time; the row is the
        thing the vector has to mean. Before this, only kind='session' re-resolved,
        while `observed` and the belief kinds embedded `payload["text"]`, which
        store.enqueue_embed_job had clamped to 8000 characters. The repair path
        therefore embedded a DIFFERENT string from the write path for any item over
        that length -- measured on the production shape (max_input_tokens 650,
        overflow chunk_mean, so every chunk of the input reaches the model): a
        9,736-character note re-embedded from 8,017 wire characters and a
        10,731-character excerpt from the same 8,017, each written back under the
        canonical model tag that declares the vector correct. Re-resolving also
        means a body edited between enqueue and drain is embedded as it now reads
        rather than as it read when the job was queued.

        `recoverable` False is the A0fix refusal contract: the store cannot say
        what this row's text is, so NOTHING is written and the row is left exactly
        as it is for the heal to count -- never re-embedded from a near-miss."""
        target, kind = payload.get("target_id"), payload.get("kind")
        text = payload.get("text") or ""
        emb = self.core.embedder
        if not target or not kind or not text or emb is None:
            return
        provider = external_id = None
        # The tag AS OF NOW, used only to answer "is this row already done".
        # It is deliberately NOT the tag that gets stamped: `recheck()` below may
        # adopt a live backend inside this very job, and this value would then be
        # the stale 'degraded' placeholder (D2). The stamped tag is re-resolved
        # after the embed succeeds.
        known_tag = embedder_model_tag(emb)
        # A0b: "already done" is TAG AND WIDTH, never the tag alone. A
        # wrong-dimension blob can carry a perfectly current tag -- that is
        # exactly what the live nemotron rows did -- and a tag-only check made
        # this handler a no-op on precisely the rows the heal requeued it for,
        # so the heal re-queued them again next run, forever. `want_len` is 0
        # when the embedder does not report a dimensionality, which means
        # "cannot check", not "everything is wrong": the tag-only behavior.
        want_len = expected_blob_len(emb)

        def _already_current(existing_model, existing_len):
            if existing_model is None or existing_model != known_tag:
                return False
            return not (want_len and existing_len and existing_len != want_len)

        if kind == "observed":
            if _already_current(self.store.get_observed_vector_model(target),
                                self.store.get_observed_vector_len(target)):
                return  # Vector exists, model matches AND width is right: no-op
            text, recoverable = observed_vector_text(self.store._conn(), target)
            if not recoverable:
                return
        elif kind == "projection":
            # External-DB projection (§g5a): no belief table backs this — identity
            # is the (provider, external_id) pair carried alongside target_id,
            # never inferred by re-parsing the namespaced id.
            provider, external_id = payload.get("provider"), payload.get("external_id")
            if not provider or not external_id:
                return
            if _already_current(self.store.get_projection_vector_model(provider, external_id),
                                self.store.get_projection_vector_len(provider, external_id)):
                return  # Vector exists, model matches AND width is right: no-op
            # The one channel whose text lives nowhere but the embed job itself
            # (§g5a): the authority reads it back out of the NEWEST job for this
            # target, so a re-rendered projection is embedded as it now reads and
            # this handler still never invents a text of its own.
            text, recoverable = projection_vector_text(self.store._conn(), provider, external_id)
            if not recoverable:
                return
        elif kind == "session":
            # Session summary vector (A0e). `target` is the session_id, and the
            # row already exists — the summarizer wrote it — so only its
            # embedding + tag are repaired here.
            if _already_current(self.store.get_session_vector_model(target),
                                self.store.get_session_vector_len(target)):
                return  # Vector exists, model matches AND width is right: no-op
            # Re-embed the SUMMARY THE ROW HOLDS, resolved through the reducer's
            # authority — never the job payload's copy of it. The payload is a
            # snapshot clamped at enqueue time; the row is the thing the vector
            # has to mean. `recoverable` False (no such session, or an empty
            # summary) is the A0fix refusal contract: leave the row exactly as
            # it is rather than embed something else.
            text, recoverable = session_vector_text(self.store._conn(), target)
            if not recoverable:
                return
        else:
            if _already_current(self.store.get_memory_vector_model(target, kind),
                                self.store.get_memory_vector_len(target, kind)):
                return  # Vector exists, model matches AND width is right: no-op
            table = KIND_TABLE.get(kind)
            # Retracted/forgotten between capture and retry: no vector to write back.
            if not table or self.store.get_belief(table, target) is None:
                return
            # THE belief-text authority, exactly as the heal and migrate_vectors
            # resolve it -- not this job's clamped copy of the body.
            text, recoverable = belief_vector_text(self.store._conn(), kind, target)
            if not recoverable:
                return
        # A degraded embedder re-probes ONLY here: this is the backoff path, so a
        # dead endpoint costs a connection refusal per job, never a user query.
        recheck = getattr(emb, "recheck", None)
        if recheck is not None:
            recheck()
        try:
            blob = pack(emb.embed_document(text))
        except EmbeddingsUnavailable as e:
            raise JobDeferred(str(e))
        except Exception as e:
            raise JobDeferred(f"embed failed: {e}", max_attempts=_EMBED_MAX_ATTEMPTS)
        # D2: resolve the tag AFTER recheck() and AFTER the embed succeeded. The
        # old code resolved it at the top of the handler, so the FIRST job drained
        # after a backend recovery stamped the pre-recheck 'degraded' placeholder
        # onto a perfectly good vector -- a row claiming a geometry that does not
        # exist, which the next heal then spends a re-embed undoing. Resolving it
        # here means the tag always names the embedder that actually produced
        # `blob`.
        model_name = embedder_model_tag(emb)
        if not is_usable_model_tag(model_name):
            # Belt and braces: an embed succeeded but the embedder still will not
            # name a geometry (a duck-typed embedder reporting 'auto', say).
            # Writing the vector under 'degraded'/'auto' would label it with a
            # non-geometry -- exactly what DegradedEmbedder.model_tag promises
            # never happens. The job stays queued instead, bounded, so the vector
            # is written as soon as the embedder can say what it is.
            raise JobDeferred(f"embedder reports no usable geometry ({model_name!r}); "
                              f"refusing to stamp it on a vector",
                              max_attempts=_EMBED_MAX_ATTEMPTS)
        if kind == "observed":
            ev = self.store.get_event(target)
            self.store.add_observed_vector(target, blob, model_name, (ev or {}).get("owner", "default"))
        elif kind == "projection":
            owner = payload.get("owner") or "default"
            self.store.add_projection_vector(provider, external_id, blob, model_name, owner)
        elif kind == "session":
            # UPDATE, never INSERT OR REPLACE: a re-embed has no authority over
            # the summary text, the owner or occurred_at, and re-deriving those
            # from an embed job's payload would let a vector repair rewrite
            # content.
            self.store.update_session_vector(target, blob, model_name)
        else:
            self.store.add_memory_vector(target, kind, blob, model_name)

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
        attrs = sorted({"{}={}".format(r.get("attribute") or r.get("predicate_canonical") or "", r["value"])
                        for r in active if (r.get("attribute") or r.get("predicate_canonical"))
                        and r.get("value")})
        if not attrs:
            return
        shown = attrs[:_DIGEST_MAX_ATTRS]
        if len(attrs) > len(shown):
            shown.append("…(+%d more)" % (len(attrs) - len(shown)))
        line = "%s: %s (episodes: %d)" % (entity.get("name") or entity_id,
                                          "; ".join(shown), len(sessions))

        subject = f"digest:{entity_id}"
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
        obs = []         # (event_id, text) for every observed event, in session order
        transcript = []  # the same, for the session's transcript captures only
        for ev in events:
            if ev["type"] == "observed":
                p = json.loads(ev["payload"]) if isinstance(ev["payload"], str) else ev["payload"]
                # The reader's copy, not the stored bytes (speaker.reader_text).
                # Built from the stored text, 24 of the 107 interactive session
                # summaries on the production store carried a "[CONTEXT
                # COMPACTION — REFERENCE ONLY]" handoff into the session vector.
                text = spk.reader_text(p, actor=ev.get("actor") or "")
                if not text.strip():
                    continue
                obs.append((ev["event_id"], text))
                if p.get("source_type") == "session_transcript":
                    transcript.append((ev["event_id"], text))
        # A session the provider captured is its transcript. The compressor's
        # eviction copies and the rescue copies repeat messages the transcript
        # already holds, and were what carried the handoffs in; they stand in
        # only for a session with no transcript at all.
        if transcript:
            obs = transcript
        if not obs:
            return
        owner = events[0]["owner"] if events else "default"

        # §E6: open a new episode wherever consecutive event embeddings show a
        # topic shift, then emit one summary line per episode instead of one
        # blob. Falls back to a single episode -- today's behavior, byte-
        # identical -- whenever fewer than two events have a usable vector
        # (no embedder, hashing not yet run, everything still queued for
        # _task_embed): session_episode_boundaries needs at least one
        # comparable neighbor pair to find anything to split on.
        threshold = self.cfg.get("curation.topic_shift_threshold", 0.35)
        vec_rows = self.store.get_observed_vectors_by_ids([eid for eid, _ in obs])
        vectors = []
        for eid, _ in obs:
            row = vec_rows.get(eid)
            blob = row.get("embedding") if row else None
            vectors.append(unpack(blob) if blob else None)
        boundaries = (session_episode_boundaries(vectors, threshold)
                      if sum(1 for v in vectors if v) >= 2 else [0])
        lines = []
        for episode in group_by_boundaries([ex for _, ex in obs], boundaries):
            line = " ".join(episode)[:_SESSION_EPISODE_MAX_CHARS]
            if line:
                lines.append(line)
        summary = "\n".join(lines)[:_SESSION_SUMMARY_MAX_CHARS]
        vec = b""
        model_name = None
        if self.core.embedder is not None:
            try:
                vec = pack(self.core.embedder.embed_document(summary))
                # A0e: stamped ONLY on the success path, and only through the
                # single choke point every other vector table goes through. A tag
                # written next to a failed embed would claim a geometry for bytes
                # that do not exist; NULL there says "no usable vector, unknown
                # model", which is the truth and is what the heal reads as stale.
                model_name = embedder_model_tag(self.core.embedder)
            except Exception:
                vec = b""  # incl. degraded: the summary row still indexes, unvectored
                model_name = None
        self.store.add_session_vector(sid, summary, vec, owner,
                                      events[0].get("occurred_at", now_iso()), model=model_name)

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
                # Skill journals are written by the agent's own runs, not by the
                # user: kept for recall, never read as the user's words.
                excerpt = text[:4000]
                self.core.capture.append("observed",
                                         {"source_type": "ocas_journal", "excerpt": excerpt,
                                          "source_ref": fp,
                                          "speakers": [[0, len(excerpt), spk.AUTOMATION]]
                                          if excerpt else []},
                                         actor="system", trust_level=2)

    # -- federation sweep (§14, g4) ----------------------------------------

    def _task_federate_sweep(self, payload):
        """Sweep every registered local database into pointers + cached projections.

        Chronicle references, it does not own (I20): a row of somebody else's
        database becomes a POINTER plus a thin cached projection plus, at most, a
        belief ABOUT it. Nothing here writes a fact, and nothing here attaches an
        external row to a Chronicle entity on a resemblance — an exact
        external_ref match refreshes an existing link, a name collision goes to
        the review queue and waits for a decision (hard rule: identity is
        adjudicated, never inferred).

        Generic by construction: which databases exist, and which of their
        columns matter, is entirely `federation.local_dbs` config —
        `[{name, path, read_only, table, id_column, content_columns,
        name_column?, capability?}]`. No database name, schema, or column
        belonging to any particular deployment appears in this file.

        Failure modes are deliberately different from one another:
          * provider offline (file gone, unreadable, locked) → SKIP it, this run
            is still a success; the pointers stay valid and serve from cache.
          * config that cannot be executed (no such table/column) → the job
            FAILS, loudly, because a silent no-op here looks exactly like a
            provider with nothing to say.
        """
        specs = self.cfg.get("federation.local_dbs", []) or []
        only = (payload or {}).get("db")
        errors = []
        for spec in specs:
            if not isinstance(spec, dict):
                errors.append("local_dbs entry is not a mapping: %r" % (spec,))
                continue
            name = str(spec.get("name") or "").strip()
            if only and name != only:
                continue
            try:
                self._federate_db(spec)
            except _ProviderOffline as off:
                logger.info("federate_sweep: provider %s offline, skipped (%s)", name or "?", off)
            except Exception as e:  # config/query error — surfaced, never swallowed
                logger.exception("federate_sweep: provider %s failed", name or "?")
                errors.append("%s: %s" % (name or "?", e))
        if errors:
            raise RuntimeError("federate_sweep: " + "; ".join(errors)[:280])

    def _federate_db(self, spec: dict):
        """Validate one provider's config against its LIVE schema, then sweep it."""
        name = str(spec.get("name") or "").strip()
        path = str(spec.get("path") or "").strip()
        if not name or not path:
            raise ValueError("local_dbs entry needs both name and path")
        table = str(spec.get("table") or "").strip()
        id_col = str(spec.get("id_column") or "id").strip()
        content_cols = [str(c).strip() for c in (spec.get("content_columns") or []) if str(c).strip()]
        name_col = str(spec.get("name_column") or "").strip()      # optional
        capability = str(spec.get("capability") or "federation").strip()
        if not table or not content_cols:
            raise ValueError("local db %r needs table and non-empty content_columns" % name)

        path = os.path.expanduser(path)
        if not os.path.isfile(path):
            raise _ProviderOffline("no database file at %s" % path)
        conn = self._open_local_db(path, bool(spec.get("read_only", True)))
        try:
            present = _local_columns(conn, table)
            wanted = [id_col] + ([name_col] if name_col else []) + content_cols
            missing = [c for c in wanted if c not in present]
            if missing:
                raise ValueError("local db %r: %s has no column(s) %s"
                                 % (name, table, ", ".join(sorted(set(missing)))))
            self._sweep_local_db(conn, provider=name, table=table, id_col=id_col,
                                 content_cols=content_cols, name_col=name_col,
                                 capability=capability)
        finally:
            conn.close()

    @staticmethod
    def _open_local_db(path: str, read_only: bool = True):
        """A sandboxed handle on a foreign database.

        read_only is enforced by the DRIVER, not by convention: the URI opens the
        file with mode=ro, so SQLite itself rejects a write — a `read_only: true`
        entry cannot be modified through this connection even by a bug on our
        side. The path is made absolute first because URI filename resolution of
        a relative "file:" path is not defined across platforms/versions, and
        percent-quoted because a '?' or '#' in a directory name would otherwise
        be parsed as the URI's query/fragment.

        Anything that stops us opening the file — missing, locked, corrupt,
        permission denied — is the provider being OFFLINE, which is a skip.
        """
        import sqlite3
        try:
            if read_only:
                uri = "file:" + urllib.parse.quote(os.path.abspath(path)) + "?mode=ro"
                conn = sqlite3.connect(uri, timeout=5, uri=True)
            else:
                conn = sqlite3.connect(path, timeout=5)
            conn.row_factory = sqlite3.Row
            conn.execute("SELECT 1")        # a lazy connect fails only on first use
            return conn
        except sqlite3.Error as e:
            raise _ProviderOffline("cannot open %s: %s" % (path, e))

    def _sweep_local_db(self, conn, *, provider, table, id_col, content_cols, name_col, capability):
        """One bounded pass: ingest new rows, then re-read already-ingested ones.

        The watermark alone cannot see an EDIT. An external row that changes
        keeps its id, so `WHERE id > watermark` would never look at it again and
        the cached projection would drift from the source forever. So a run does
        two things, sharing one budget of _FEDERATE_ROW_BUDGET rows:

          1. ingest — `id > last_row_id`, which advances the watermark;
          2. rescan — `rescan_cursor < id <= last_row_id`, paging back over rows
             already ingested and comparing each one's content hash. The cursor
             wraps to 0 at the end of a lap, so the whole table is revisited on a
             rolling basis without ever reading more than the budget in one run.

        Ingest goes first on purpose: data Chronicle has never seen matters more
        than data it has. On a table growing faster than the budget the rescan
        starves, which is the right way round — and visible, since the watermark
        stops keeping up.
        """
        state = self.store.get_federation_state(provider)
        watermark = state["last_row_id"]
        cursor = state["rescan_cursor"]
        budget = _FEDERATE_ROW_BUDGET

        # The select list is BUILT, never formatted with holes: name_column is
        # optional, and interpolating an empty one produced "SELECT id,,email".
        select = []
        for c in [id_col] + ([name_col] if name_col else []) + content_cols:
            if c not in select:
                select.append(c)
        # Every identifier here has just been checked against the live schema
        # (_federate_db), so this is quoting a known-good name, not trusting input.
        cols_sql = ", ".join(_quote_ident(c) for c in select)
        qtable, qid = _quote_ident(table), _quote_ident(id_col)
        row_kw = dict(provider=provider, capability=capability, id_col=id_col,
                      name_col=name_col, content_cols=content_cols)

        # 1. ingest
        rows = conn.execute(
            "SELECT %s FROM %s WHERE %s > ? ORDER BY %s LIMIT ?" % (cols_sql, qtable, qid, qid),
            (watermark, budget)).fetchall()
        for row in rows:
            self._federate_row(row, **row_kw)
        if rows:
            watermark = max([watermark] + [int(r[id_col]) for r in rows])
        budget -= len(rows)
        ingested = len(rows)

        # 2. rescan
        rescanned = 0
        ceiling = state["last_row_id"]           # rows ingested by EARLIER runs
        if budget > 0 and ceiling > 0:
            if cursor >= ceiling:
                cursor = 0                        # previous lap finished; start over
            rows = conn.execute(
                "SELECT %s FROM %s WHERE %s > ? AND %s <= ? ORDER BY %s LIMIT ?"
                % (cols_sql, qtable, qid, qid, qid),
                (cursor, ceiling, budget)).fetchall()
            for row in rows:
                self._federate_row(row, **row_kw)
            rescanned = len(rows)
            # A short page means the lap reached the ceiling: wrap.
            cursor = int(rows[-1][id_col]) if rows and len(rows) >= budget else 0

        self.store.set_federation_state(provider, last_row_id=watermark, rescan_cursor=cursor)
        logger.info("federate_sweep %s: %d ingested, %d rescanned, watermark=%d, cursor=%d",
                    provider, ingested, rescanned, watermark, cursor)

    def _federate_row(self, row, *, provider, capability, id_col, name_col, content_cols) -> bool:
        """Pointer + cached projection for one external row. True if it changed.

        The identity work runs on EVERY row examined, changed or not, because the
        collision can appear on the CHRONICLE side: a new entity named like a row
        that has sat untouched for months is exactly the case a change-gated
        check would miss. Only the pointer write and its event are hash-gated.
        """
        row_id = row[id_col]
        external_id = "%s:%s" % (provider, row_id)
        fields = {c: _as_text(row[c]) for c in content_cols}
        display = _as_text(row[name_col]) if name_col else ""
        content_hash = _content_hash(external_id, display, fields)

        # An exact external_ref match is the ONLY thing that may touch a link.
        linked = self._linked_entities(provider, external_id)
        if not linked and display:
            self._queue_link_candidates(provider, external_id, display)

        existing = self.store.find_pointer(capability, provider, external_id)
        cached = {}
        if existing and existing.get("cached_projection"):
            try:
                cached = json.loads(existing["cached_projection"])
            except ValueError:
                cached = {}                       # malformed cache → treat as changed
        if cached.get("content_hash") == content_hash:
            return False                          # unchanged: no write, no event

        ttl = self.cfg.get("federation.cache_ttl", "24h")
        projection = {"content_hash": content_hash, "source_row_id": row_id,
                      "display": display, "fields": fields, "refreshed_at": now_iso()}
        pointer_id = self.store.upsert_pointer({
            # Reuse the id: upsert_pointer would otherwise mint a new uuid and
            # INSERT OR REPLACE the natural key, orphaning every reference to it.
            "id": existing["id"] if existing else None,
            "capability": capability, "provider": provider, "external_id": external_id,
            "cached_projection": json.dumps(projection, sort_keys=True), "cache_ttl": ttl})
        for entity_id in linked:                  # refresh, not re-link
            self.store.update_belief("entities", entity_id, cache_ttl=ttl, last_seen_at=now_iso())

        # Every write is an event, so provenance chains: pointer/belief → this
        # event → provider + external_id + content_hash. The payload carries the
        # HASH, never the column values: the projection is a TTL cache that a
        # re-sweep can rebuild, while the log is permanent — copying external
        # attributes into it would be owning them (I20).
        self.core.capture.append("federated", {
            "source_type": "federation", "kind": "sweep", "capability": capability,
            "provider": provider, "external_id": external_id, "pointer_id": pointer_id,
            "content_hash": content_hash, "linked_entities": linked,
        }, actor="curator", owner=self.core.active_principal)
        return True

    def _linked_entities(self, provider: str, external_id: str):
        """Entities already bound to this exact external row, ACL-filtered (§15).

        Exact (external_provider, external_ref) only — this is the match the spec
        allows to refresh a link automatically, precisely because it is not a
        judgement about identity, it is a link somebody already adjudicated.
        """
        rows = self.store.query_beliefs(
            "entities", "external_provider=? AND external_ref=? AND merged_into IS NULL",
            (provider, external_id), limit=25)
        principal = self.core.active_principal
        return [r["belief_id"] for r in rows
                if access.can_read(r.get("read_acl"), r.get("owner"), principal)]

    def _queue_link_candidates(self, provider: str, external_id: str, display: str):
        """Name collision → REVIEW QUEUE. Never a link (hard rule, I20).

        A name is evidence, not identity: two people share one, and an external
        row saying "Pat Testley" tells us nothing about which Pat Testley
        Chronicle already knows. So the pair is parked for adjudication and the
        entity is left exactly as it was. Entities the sweeping principal may not
        read are not candidates and are not disclosed as ones (§15).
        """
        needle = display.strip()
        if not needle:
            return
        rows = self.store.query_beliefs(
            "entities", "merged_into IS NULL AND (name=? OR normalized_name=?) "
            "AND (external_provider IS NULL OR external_provider<>?)",
            (needle, needle.lower(), provider), limit=_FEDERATE_MAX_CANDIDATES)
        principal = self.core.active_principal
        for ent in rows:
            if not access.can_read(ent.get("read_acl"), ent.get("owner"), principal):
                continue
            score = 1.0 if (ent.get("name") or "") == needle else 0.9
            if self.store.enqueue_link_candidate(ent["belief_id"], external_id,
                                                 "name_collision", score, provider=provider):
                logger.info("federate_sweep: link candidate %s ↔ %s queued for review",
                            ent["belief_id"], external_id)

    def _task_backfill_sweep(self, payload):
        """Backfill session_index for ended/reaped sessions lacking an index row
        (issue #6).

        Deterministic batch job: takes one `sweeps.budgets.backfill` page of
        ended sessions without an index entry, enqueues session_summarize for
        each, and persists the cursor so the NEXT run starts past this one.

        §A9: the batch size was the literal 200 and the watermark never wrapped,
        so once the cursor reached the highest session id this job returned an
        empty list forever — including for sessions whose index row disappeared
        behind the cursor afterwards. It also reported nothing but a count, so a
        store 40k sessions behind and a store fully caught up logged the same
        line. The wrap and the processed/remaining/bounded report both live in
        `get_sessions_needing_index_backfill` now; this returns the report.
        """
        budget = sweeps.sweep_budget(self.cfg, "backfill", default=200)
        sids = self.store.get_sessions_needing_index_backfill(limit=budget)
        for sid in sids:
            self.store.enqueue_curation("session_summarize", {"session_id": sid})
        report = self.store.get_sweep_state("backfill")
        logger.info("backfill_sweep: enqueued %d sessions for summarization, %d remaining",
                    len(sids), report.get("remaining", 0))
        return report


def _quote_ident(name: str) -> str:
    return '"%s"' % str(name).replace('"', '""')


def _local_columns(conn, table: str):
    """Column names of a table/view in a foreign database, or ValueError.

    The table is confirmed through a BOUND query against sqlite_master before its
    name is ever spliced into SQL, so a config typo is a clean job error rather
    than a syntax error from a half-built statement."""
    row = conn.execute("SELECT name FROM sqlite_master WHERE type IN ('table','view') AND name=?",
                       (table,)).fetchone()
    if row is None:
        raise ValueError("no table or view named %r" % table)
    return [r["name"] for r in conn.execute("PRAGMA table_info(%s)" % _quote_ident(table)).fetchall()]


def _as_text(value) -> str:
    return "" if value is None else str(value)


def _content_hash(external_id: str, display: str, fields: dict) -> str:
    """Stable digest of everything the projection caches, so a change to ANY
    swept column (including the display name) is a change."""
    import hashlib
    body = json.dumps({"external_id": external_id, "display": display, "fields": fields},
                      sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(body.encode("utf-8")).hexdigest()


def _bucket(score: float) -> str:
    return f"{int(max(0.0, min(0.999, score)) * 10) / 10:.1f}"
