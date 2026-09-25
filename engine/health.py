"""
Chronicle — Health & self-healing (§21).

An auditor (cold) computes drift/anomaly signals; the consistency sweep (CSP)
flags single-cardinality predicates with >1 active value and unsound derivations
→ `nogoods` + rule penalty; a Custodian fingerprints recurring issues and
applies bounded, non-destructive Tier-1 auto-repair (rebuild FTS, retract orphan
justifications, re-embed, unmerge known-bad). It never deletes events; all
repairs go through `append_event`.
"""

from __future__ import annotations

import datetime
import json
import logging
import sqlite3

from . import speaker as spk
from . import sweeps
from .embeddings import (
    VECTOR_TABLES,
    embedder_model_tag,
    expected_blob_len,
    is_usable_model_tag,
    split_model_tag,
    width_contradiction,
    wrong_dim_skipped,
)
from .reducer import (
    belief_vector_text,
    observed_vector_text,
    projection_vector_text,
    session_vector_text,
)
from .store import now_iso

logger = logging.getLogger("chronicle.health")


def _iso_age_seconds(stamp):
    """Seconds between `stamp` (now_iso format) and now, or None if unparseable.
    Never raises: an unreadable cache stamp reads as "stale", never as fresh."""
    if not stamp:
        return None
    try:
        t = datetime.datetime.strptime(str(stamp), "%Y-%m-%dT%H:%M:%S.%fZ").replace(
            tzinfo=datetime.timezone.utc)
    except (TypeError, ValueError):
        return None
    return (datetime.datetime.now(datetime.timezone.utc) - t).total_seconds()


class HealthEngine:
    # THE vector-identity scan set, bound (not re-typed) from embeddings.py so
    # this heal, scripts/migrate_vectors.py and scripts/requeue_hash_vectors.py
    # cannot disagree about what "every vector" means. A0e's defect was three
    # hand-typed copies of this list that each covered three of the five tables
    # with nothing comparing them. See embeddings.VECTOR_TABLES for the full
    # rationale and the one documented exemption (entity_centroids.sum_vec).
    VECTOR_TABLES = VECTOR_TABLES

    def __init__(self, core):
        self.core = core
        self.store = core.store
        self.cfg = core.cfg

    def run(self) -> dict:
        gf = self.cfg.get("health.ghost_fact", {"confidence_min": 0.8, "age_days": 14})
        ghosts, ghost_report = self._ghost_facts(gf)
        results = {
            "ghost_facts": ghosts,
            # §A9: what the ghost list did NOT show. A bounded list with no
            # count next to it is the whole defect in miniature.
            "ghost_facts_sweep": ghost_report,
            "unjustified": self.store.active_unjustified(),          # I5 must be empty
            "extraction_recall_gap": self._recall_gap(),
            "bad_derivation_rate": self._bad_derivation_rate(),
            "open_contradictions": len(self.store.get_open_contradictions(1000)),
            # Ladder-10 A8: entity merges this store's log made by INFERENCE (an
            # exact name match), before the `identity` sweep started proposing
            # candidates instead. Reported, never reversed — see
            # store.count_inferred_entity_merges. getattr so a HealthEngine on a
            # store stub (tests) still reports.
            "inferred_entity_merges": (
                self.store.count_inferred_entity_merges()
                if hasattr(self.store, "count_inferred_entity_merges") else 0),
            "lock_contention": round(self.store.lock_contention(), 4),
            # A0c: how many stored vectors this PROCESS has had to skip on the
            # read path because their blob width does not match the active
            # embedder. Monotone since process start, and the read-side
            # companion to vectors_wrong_dim below (which counts the rows that
            # are wrong, not the times a query tripped over them). Both exist
            # because the condition used to have no signal at all: a
            # wrong-width vector scored 0.0, fell under every floor, and simply
            # never appeared in a result.
            "vector_reads_skipped_wrong_dim": wrong_dim_skipped(),
            # Maintenance cadence (§17.4, A3): last run / next due per schedule
            # entry, and the tasks deliberately left unscheduled. getattr so a
            # HealthEngine built on a core stub (tests) still reports.
            "maintenance": (getattr(self.core, "scheduler", None).status()
                            if getattr(self.core, "scheduler", None) is not None else {}),
        }
        # Self-heal Tier-1: retract orphan (unjustified) active beliefs (I5).
        if self.cfg.get("health.self_heal.tier1_auto", True):
            for bid in results["unjustified"]:
                self._fingerprint("unjustified_active", "tier1", "retract_orphan", auto=1)
                self.core.capture.append("retracted", {"belief_id": bid, "reason": "unjustified_orphan"},
                                         actor="curator", owner="default")
        results["consistency_sweep"] = self.consistency_sweep()
        # Self-heal Tier-1: requeue vectors written by mismatched embedder.
        results.update(self._embedder_mismatch_heal())
        # Self-heal Tier-1 (§A7): recover jobs whose worker died, and keep the
        # job table bounded. Both are queue HYGIENE, not curation work, so they
        # run here rather than as jobs — a job that repairs the queue would
        # itself be subject to the queue's failure modes.
        results.update(self.queue_maintenance())
        # Enqueue one bounded federation sweep per health run (§14, g4). The
        # health sweep is the schedule: enqueue_curation collapses an identical
        # pending job, so a backlogged queue never stacks sweeps, and each run
        # picks up where the last one's cursors left off.
        if self.cfg.get("federation.local_dbs"):
            results["federate_sweep_queued"] = bool(
                self.store.enqueue_curation("federate_sweep", {}))
        # §A9: every sweep's last run, whether or not it ran in THIS health run.
        # A sweep that lives on the curation queue (decay, canonicalize,
        # identity, backfill) reports here too, so one snapshot answers "is any
        # sweep permanently behind?" — the question nobody could ask before.
        results["sweeps"] = self.store.list_sweep_states()
        results["sweeps_bounded"] = sorted(
            name for name, s in results["sweeps"].items() if s.get("bounded"))
        self.store.record_health_run(results)
        return results

    def queue_maintenance(self) -> dict:
        """Lease recovery + retention for `curation_jobs` (§A7).

        LEASES: `claim_curation_job` marks a row 'running'; nothing ever marked
        it back. A worker killed mid-job (OOM, a gateway restart draining and
        then killing in-flight work, a plain crash) left the row 'running'
        forever, invisible to every later claim — the live store had 245
        `extract` rows in exactly that state while 147 more had failed. A
        running row older than `curation.lease_seconds` is treated as abandoned
        and re-armed, or failed with a stated reason once it has burned
        `curation.max_attempts` claims.

        RETENTION: done/failed rows were never deleted, so `curation_jobs` grew
        for the life of the store and every enqueue's dedupe probe paid for the
        whole history. `curation.retention.*` bounds it by age AND by count.

        RETENTION (§S6): the same `curation.retention.enabled` switch also
        gates `prune_retracted_beliefs`, which bounds the long-retracted tail
        of notes/episodes/facts under its own `retracted_days` /
        `retracted_max_rows` keys — same problem shape (a status nothing ever
        deletes, growing every scan) on a different table.

        All are bounded per run and all report what they did."""
        out = {}
        try:
            lease = int(self.cfg.get("curation.lease_seconds", 900))
        except (TypeError, ValueError):
            lease = 900
        try:
            max_attempts = int(self.cfg.get("curation.max_attempts", 20))
        except (TypeError, ValueError):
            max_attempts = 20
        try:
            batch = int(self.cfg.get("curation.reclaim_batch", 200))
        except (TypeError, ValueError):
            batch = 200
        out["job_leases"] = self.store.reclaim_stale_jobs(
            lease_seconds=lease, max_attempts=max_attempts, limit=max(1, batch))
        if self.cfg.get("curation.retention.enabled", True):
            try:
                days = float(self.cfg.get("curation.retention.done_days", 7))
            except (TypeError, ValueError):
                days = 7.0
            try:
                cap = int(self.cfg.get("curation.retention.max_rows", 20000))
            except (TypeError, ValueError):
                cap = 20000
            try:
                pbatch = int(self.cfg.get("curation.retention.batch", 5000))
            except (TypeError, ValueError):
                pbatch = 5000
            out["job_retention"] = self.store.prune_curation_jobs(
                max_age_days=days, max_rows=cap, batch=max(1, pbatch))
        else:
            out["job_retention"] = {"pruned_age": 0, "pruned_cap": 0, "enabled": False}
        out["job_queue"] = self.store.pending_counts_by_task()
        # §S6: the same retention pattern as job_retention just above, applied
        # to the retracted tail of notes/episodes/facts instead of terminal
        # curation_jobs rows — almost all of both were retracted yet none was
        # ever removed, so they sat in belief_fts and every status='active'
        # scan forever. Gated by the same `curation.retention.enabled` switch
        # since it is the same retention mechanism.
        if self.cfg.get("curation.retention.enabled", True):
            try:
                retracted_days = float(self.cfg.get("curation.retention.retracted_days", 30))
            except (TypeError, ValueError):
                retracted_days = 30.0
            try:
                retracted_cap = int(self.cfg.get("curation.retention.retracted_max_rows", 50000))
            except (TypeError, ValueError):
                retracted_cap = 50000
            out["belief_retention"] = self.store.prune_retracted_beliefs(
                days=retracted_days, max_rows=retracted_cap, batch=max(1, pbatch))
        else:
            out["belief_retention"] = {"pruned": 0, "by_table": {}, "enabled": False}
        return out

    GHOST_WHERE = "status='active' AND confirm_count=0 AND confidence>=?"

    def _ghost_facts(self, gf) -> tuple:
        """High-confidence facts nothing ever confirmed — a REPORT, not a repair.

        The old shape scanned an arbitrary 5000-row prefix and then reported the
        first 200 of those, so a store with 40k ghosts and a store with 200 read
        exactly the same: a list of 200 ids, no count, no hint that anything was
        cut. Two changes: the returned window is now the sweep's budget (so what
        is scanned is what is reported — no second, hidden truncation), and it
        rotates on a cursor, so successive health runs surface different ghosts
        instead of the same head of the table forever.

        Returns (ids, report). The ids stay a plain list — that is the shape
        `health.run()["ghost_facts"]` has always had — and the report is what
        makes the cut visible."""
        page = sweeps.next_row_page(self.store, self.cfg, "ghost_facts", "facts",
                                    self.GHOST_WHERE, (gf.get("confidence_min", 0.8),))
        return [r["belief_id"] for r in page.rows], sweeps.commit(self.store, page)

    def _recall_gap(self) -> float:
        total = self.store.count_rows("retrieval_log")
        misses = self.store.count_rows("search_misses")
        return round(misses / total, 4) if total else 0.0

    def _bad_derivation_rate(self) -> float:
        rules = self.store.get_derivation_rules(enabled_only=False)
        n = sum(r["precision_n"] or 0 for r in rules)
        correct = sum(r["precision_correct"] or 0 for r in rules)
        return round(1 - correct / n, 4) if n else 0.0

    def consistency_sweep(self) -> dict:
        """CSP (§21): single-cardinality predicate with >1 active value → contradiction;
        unsound derivations → nogoods + rule penalty.

        GROUP-shaped, and that is why it does not page by rowid (§A9). The unit
        of work is every active fact sharing (entity, predicate, qualifiers,
        owner, domain); a rowid page that contained one of a group's two
        conflicting values and not the other would see a single value and
        conclude the store is consistent — a bounded sweep that returns a WRONG
        answer, which is worse than the silent truncation being fixed. So the
        cursor runs over DISTINCT entity_id (a group never spans two entities),
        and each page's entities are then loaded whole.

        Bound: `sweeps.budgets.consistency` entities per run, resuming where the
        last run stopped and wrapping at the end of a lap."""
        page = sweeps.next_distinct_page(self.store, self.cfg, "consistency", "facts",
                                         "entity_id", "status='active'", ())
        rows = self.store.beliefs_for_values("facts", "entity_id", page.rows,
                                             "status='active'", ())
        groups: dict[tuple, list] = {}
        for r in rows:
            groups.setdefault((r["entity_id"], r["predicate_canonical"], r["qualifiers_hash"],
                               r["owner"], r["domain"]), []).append(r)
        for (ent, pred, qh, owner, domain), facts in groups.items():
            if not pred:
                continue
            if self.store.get_predicate_cardinality(pred) != "single":
                continue
            distinct = {f["value"] for f in facts}
            non_derived = [f for f in facts if json.loads(f.get("provenance") or "{}").get("source_type") != "inference"]
            if len(distinct) > 1 and len(non_derived) > 1:
                # No supersession resolved them → open a contradiction (§21).
                a, b = sorted(facts, key=lambda f: f["created_at"])[:2]
                self.store.open_contradiction(a["belief_id"], b["belief_id"],
                                              f"{pred} single-cardinality has {len(distinct)} active values")
                self._fingerprint("cardinality_violation", "tier2", "review", auto=0)
        report = sweeps.commit(self.store, page)
        report["contradictions_settled"] = self.settle_dead_contradictions()
        return report

    def settle_dead_contradictions(self) -> int:
        """Close open contradictions whose beliefs are no longer both active.

        A contradiction is a pair the store cannot both hold. The reducer closes
        them as it retracts (reducer._retract), but a store repaired by an older
        build keeps whatever it opened: one production cleanup left 1,550 open
        rows naming beliefs that no longer exist, and "open contradictions" is
        the first number the memory view shows. Resolved, never deleted."""
        return self.store.resolve_contradictions_without_two_active()

    def _fingerprint(self, pattern, tier, action, auto):
        fp = f"{pattern}:{tier}"
        self.store.upsert_fingerprint(fp, pattern, tier, action, auto)

    def rebuild_fts(self):
        """Tier-1 auto-repair: rebuild FTS from the projection (non-destructive)."""
        self.core.reducer.rebuild()

    # There is NO belief-kind -> column map here any more. This class used to
    # carry one (`BELIEF_TEXT`), imported by scripts/requeue_hash_vectors.py and
    # scripts/migrate_vectors.py so the three "could not disagree" -- but it was
    # a SECOND definition of what reducer.vector_text() embeds, maintained by
    # hand next to it, and it had already drifted: it mapped `procedure` to
    # `procedures.name` (= content[:40] for a tool-written procedure) while the
    # reducer embedded the full body. All three consumers now call
    # reducer.belief_vector_text(), which rebuilds vector_text()'s own inputs
    # from the projection and evaluates vector_text() itself, and which REFUSES
    # (returns recoverable=False) rather than returning a near-miss.
    # tests/test_belief_text_authority.py pins that there is exactly one such
    # function and that every kind in reducer._VECTORED_KINDS round-trips
    # through it.

    # A tag that names no usable geometry ('degraded', 'auto', ''). Never used as
    # the comparison target: doing so would classify EVERY row in the store as
    # mismatched and requeue the whole corpus the moment the embedding backend is
    # briefly unreachable. The predicate lives in embeddings.py so the heal, the
    # migration tool and the curation write path all mean the same thing by it.

    def _mismatch_bound(self) -> int:
        """How many rows one health run may REQUEUE (§21 bounded Tier-1 repair).

        THROUGHPUT, stated plainly because the live store made it matter: this
        bounds the expensive action only. At the default 500/run on the default
        `health.schedule` of once a day, a store with 170k wrongly-embedded
        vectors takes ~340 days to converge through the heal alone. That is the
        heal doing its job (a trickle that never stalls the box), NOT a
        migration: a wholesale model change is what scripts/migrate_vectors.py
        exists for, and it does the same corpus in one bounded, resumable pass.
        Raise `health.self_heal.embedder_mismatch_max` to trade box load for
        convergence time.

        RE-TAGGING is deliberately NOT bounded by this: it is a metadata UPDATE
        with no model call, no queue and no I/O per row, so the same-model
        different-name case -- the one that produced the live 60-rows-in-9-days
        drip -- converges completely in a single run instead of dripping."""
        try:
            v = int(self.cfg.get("health.self_heal.embedder_mismatch_max", 500))
        except (TypeError, ValueError):
            v = 500
        return max(1, min(1000000, v))

    def _classify_tag(self, tag, blob_len, active_tag, active_id, active_marked, expect_len):
        """What to do with a vector row, given only its tag and blob length.

        A row is MISMATCHED when its canonical model id differs, OR its E1
        prefix marker differs, OR its blob is not `dimensions * 4` bytes. Those
        are three independent ways of being in a different geometry and all
        three are silent on the read path today.

        * "reembed" — a genuinely different model, a different prefix geometry,
          or a wrong-width blob. Only a real embed can fix it.
        * "retag"   — the SAME model under a different NAME, right marker, right
          width. The bytes are already correct; only the string is stale, so
          this is an UPDATE, never an embed. This is the case that used to be
          unfixable: re-embedding wrote the same bytes back under whichever
          name the writer happened to resolve, so the next scan found the
          mismatch again, forever.
        * "ok"      — already exactly the active tag.

        A NULL tag — every `session_index` row written before A0e gave that
        table a `model` column — is STALE, and it falls out of the FIRST rule
        rather than needing one of its own: `split_model_tag(None)`
        canonicalizes to the 'auto' placeholder, which is never a real model id,
        so `cid != active_id` and the row is re-embedded. That is the deliberate
        reading of NULL — "unknown geometry", not "assume it is fine" — and it
        is stale exactly ONCE: the re-embed stamps the canonical tag, after
        which the row classifies "ok" and a second run does nothing.
        """
        cid, marked = split_model_tag(tag)
        if cid != active_id:
            return "reembed"
        if expect_len and blob_len != expect_len:
            # Covers a NULL blob too (blob_len None): a row with no vector at
            # all is not "fine, just renamed", and re-tagging it would make it
            # look healthy forever. Same rule as scripts/migrate_vectors.classify.
            return "reembed"
        if marked != active_marked:
            return "reembed"
        return "ok" if tag == active_tag else "retag"

    @staticmethod
    def _reembed_predicate(rows):
        """(sql, params) selecting exactly the (tag, width) groups classified
        "reembed" — or ("", []) when there are none.

        `length(embedding) IS ?` rather than `=` because SQLite's IS is
        null-safe: a NULL-embedding group is selected by the same clause shape
        as every other, with no special case to get wrong. `IS` also stays
        index-usable against `idx_*_model_width` (store._VECTOR_CENSUS_INDEX_DDLS),
        so selecting a group's rows is a seek, not a scan."""
        clauses, params = [], []
        for tag, blen, _cnt, action in rows:
            if action != "reembed":
                continue
            clauses.append("(model IS ? AND length(embedding) IS ?)")
            params.extend([tag, blen])
        return (" OR ".join(clauses), params)

    # A row with nothing in it is not a vector in the wrong geometry. A
    # session-index row with no summary AND no vector (a session of nothing but
    # host framing, 5.7.9) has no text a re-embed could use -- the heal skips it
    # -- and no bytes a query could match. Counted, it was a permanent,
    # unrepairable "mismatch" in every census. A row with no summary but a
    # vector still stays counted: that vector is findable, in the wrong geometry.
    _CENSUS_FILTER = {"session_index": "COALESCE(summary, '') <> '' OR COALESCE(length(embedding), 0) > 0"}

    def _census_where(self, table, joiner="AND"):
        f = self._CENSUS_FILTER.get(table)
        return (" %s (%s)" % (joiner, f)) if f else ""

    def _tag_groups(self, table):
        """(tag, blob_len, count) for every distinct (model, length(embedding))
        pair in `table` — the WHOLE census, including the healthy majority.

        Kept because it is the only honest answer to "what is in this store"
        (scripts and the dashboard want the full histogram), but it is NOT what
        a health run uses: it reads every row. `_mismatched_groups` below is the
        heal's path."""
        try:
            return [(r[0], r[1], r[2]) for r in self.store._conn().execute(
                "SELECT model, length(embedding), COUNT(*) FROM %s%s "
                "GROUP BY model, length(embedding)" % (table, self._census_where(table, "WHERE"))
            ).fetchall()]
        except sqlite3.Error as e:                # table absent on an old store
            logger.debug("tag scan skipped for %s (%s)", table, e)
            return []

    # -- incremental census (§A7) -----------------------------------------
    #
    # A0 turned the heal from one query per VECTOR into one GROUP BY per table.
    # That is still O(all rows): the aggregate reads every blob's length, so a
    # store with NOTHING wrong with it paid for its entire corpus on every
    # health run. Measured on a synthetic 100k-row store: 489-1279 ms per run
    # for the un-indexed GROUP BY, against 0.09-0.11 ms for the seeks below.
    #
    # The fix is to ask the complementary question. "Which rows are wrong?" has
    # an answer that is O(wrong) if the store is indexed on the two things
    # `_classify_tag` decides from — the tag and the blob WIDTH — because
    # "wrong" is exactly:
    #     model < active_tag   OR   model > active_tag   OR   model IS NULL
    #     model = active_tag AND length(embedding) </>/IS NULL  expected
    # Every one of those is a range seek on `idx_<t>_model_width`, so on a
    # healthy store each returns nothing after a single index probe. The
    # inequality pair is written out rather than `model != ?` on purpose:
    # SQLite cannot use an index for `!=`, and that one detail is the whole
    # difference between 2.8s and a fraction of a millisecond.
    #
    # This is a REFORMULATION, not a sample: the union of those predicates is
    # the exact complement of "tag equals the active tag and width is right",
    # which is `_classify_tag`'s "ok". Nothing mismatched can hide from it.
    def _mismatched_groups(self, table, active_tag, expect_len):
        """(tag, blob_len, count) for every group that is NOT exactly the active
        tag at the expected width. Index-seeked; empty on a healthy store."""
        conn = self.store._conn()
        out = []
        also = self._census_where(table)
        try:
            for op in ("<", ">"):
                out.extend((r[0], r[1], r[2]) for r in conn.execute(
                    "SELECT model, length(embedding), COUNT(*) FROM %s WHERE model %s ?%s "
                    "GROUP BY model, length(embedding)" % (table, op, also), (active_tag,)).fetchall())
            # A NULL tag is ordered outside both ranges above, so it needs its
            # own probe -- and it is precisely the "written by something that
            # had no embedder identity" row, which must never read as healthy.
            out.extend((r[0], r[1], r[2]) for r in conn.execute(
                "SELECT model, length(embedding), COUNT(*) FROM %s WHERE model IS NULL%s "
                "GROUP BY length(embedding)" % (table, also)).fetchall())
            if expect_len:
                for op in ("<", ">"):
                    out.extend((r[0], r[1], r[2]) for r in conn.execute(
                        "SELECT model, length(embedding), COUNT(*) FROM %s WHERE model IS ? AND "
                        "length(embedding) %s ?%s GROUP BY model, length(embedding)"
                        % (table, op, also), (active_tag, expect_len)).fetchall())
                out.extend((r[0], r[1], r[2]) for r in conn.execute(
                    "SELECT model, length(embedding), COUNT(*) FROM %s WHERE model IS ? AND "
                    "length(embedding) IS NULL%s GROUP BY model, length(embedding)" % (table, also),
                    (active_tag,)).fetchall())
        except sqlite3.Error as e:                # table absent on an old store
            logger.debug("tag scan skipped for %s (%s)", table, e)
            return []
        return out

    # The reported DENOMINATOR ("N of M vectors are off-model") is the one part
    # of the census that cannot be answered by a seek: an exact COUNT(*) reads
    # every index entry. Warm that is ~0.05 ms for all three tables; COLD (a
    # health run in a freshly started process, which is the normal case for a
    # scheduled sweep) it is disk I/O — measured 160 ms on the same 100k-row
    # store. Paying that on a store with nothing wrong with it is the same
    # mistake as the full GROUP BY, one order of magnitude down.
    #
    # So the total is CACHED in meta with the timestamp it was measured at, and
    # recomputed only when (a) the cache is older than
    # `health.census_total_max_age_hours`, or (b) this run actually found
    # mismatched rows — i.e. exactly when the denominator is about to be used
    # for something. `vectors_total_at` is reported alongside it so the number
    # is never mistaken for a live one. The MISMATCH count is always live and
    # exact; only the denominator is cached.
    _CENSUS_KEY = "vector_census_total"
    # A7 cached the denominator for the three big vector tables. A0e's scope
    # rule says a table that is not counted is indistinguishable from a table
    # nobody looks at, so the cache covers the SAME list the census iterates.
    # An older cache written with only three keys simply fails the
    # completeness check in `_cached_totals` and is recounted once.
    _CENSUS_TABLES = VECTOR_TABLES

    def _census_max_age_seconds(self) -> float:
        try:
            h = float(self.cfg.get("health.census_total_max_age_hours", 24))
        except (TypeError, ValueError):
            h = 24.0
        return max(0.0, h) * 3600.0

    def _count_table(self, table) -> int:
        try:
            return int(self.store._conn().execute(
                "SELECT COUNT(*) FROM %s%s" % (table, self._census_where(table, "WHERE"))).fetchone()[0])
        except sqlite3.Error:
            return 0

    def _cached_totals(self, force: bool = False):
        """({table: n}, measured_at_iso). Recounts when stale or forced."""
        cached = None
        raw = self.store.get_meta(self._CENSUS_KEY)
        if raw:
            try:
                cached = json.loads(raw)
            except (TypeError, ValueError):
                cached = None
        if cached and not force:
            at = cached.get("at") or ""
            age = _iso_age_seconds(at)
            if age is not None and age <= self._census_max_age_seconds() \
                    and all(t in cached for t in self._CENSUS_TABLES):
                return ({t: int(cached[t]) for t in self._CENSUS_TABLES}, at)
        totals = {t: self._count_table(t) for t in self._CENSUS_TABLES}
        at = now_iso()
        payload = dict(totals)
        payload["at"] = at
        try:
            self.store.set_meta(self._CENSUS_KEY, json.dumps(payload, sort_keys=True))
        except sqlite3.Error:                      # a read-only store still reports
            logger.debug("could not cache the vector census total")
        return (totals, at)

    def _embedder_mismatch_heal(self) -> dict:
        """Tier-1 auto-repair: converge every stored vector onto the ACTIVE
        embedder's canonical tag (A0b).

        Mismatch is decided by IDENTITY + GEOMETRY, not by raw string equality:
        canonical id differs, or prefix marker differs, or blob length !=
        dimensions*4. That distinction is the whole fix. The pre-A0 heal
        compared tag strings, so one model reporting itself as
        "nomic-embed-text", "nomic-embed-text:latest" and
        "/opt/llama-embed/nomic-embed-text-v1.5.Q8_0.gguf" looked like three
        models: rows were requeued, re-embedded to identical bytes, written
        back under whichever name that writer resolved, and found mismatched
        again on the next pass (measured on the live store: 60 rows re-tagged
        in 9 days, converging on nothing).

        Returns the healing summary plus flat `vectors_*` counters so the
        condition is VISIBLE — health_runs rows are JSON, so a dashboard or
        plugin_api can read them without knowing this method exists. Before
        this, an 88%-mismatched store reported clean.

        SCOPE (A0e): every table in `VECTOR_TABLES`, which is every
        embedding-bearing table in the schema bar the one documented exemption.
        The counters name each table individually under `by_table`, at zero as
        well as non-zero, so "scanned and clean" is distinguishable from "not
        scanned" — the pre-A0e state, in which the two most degraded tables on
        the live store were simply absent from the loop and the store-wide
        `mismatched` number was computed over a corpus this heal had never
        looked at."""
        embedder = self.core.embedder
        zero = {"embedder_mismatch": {"mismatched": 0, "requeued": 0, "retagged": 0,
                                      "wrong_dim": 0, "outstanding": 0, "bounded": False,
                                      "active_tag": None,
                                      "queued_backlog": 0, "requeue_room": 0,
                                      "by_table": {t: {"total": 0, "mismatched": 0,
                                                       "wrong_dim": 0}
                                                   for t in self.VECTOR_TABLES}},
                "vectors_total": 0, "vectors_total_at": None, "vectors_by_table": {},
                "vectors_mismatched": 0, "vectors_wrong_dim": 0,
                # Flat, like the others, so a dashboard or plugin_api sees the
                # condition without knowing this method exists: a REFUSED heal
                # otherwise reports the same zeros as a clean store (A0g).
                "vectors_width_refused": 0}
        if embedder is None or not hasattr(embedder, "model"):
            return zero

        # Vectors are recorded through embeddings.embedder_model_tag(), not the
        # bare embedder.model. Reading the active tag through the SAME choke
        # point the writers use is what makes "this row matches" decidable.
        active_tag = embedder_model_tag(embedder)
        active_id, active_marked = split_model_tag(active_tag)
        if not is_usable_model_tag(active_tag):
            # Degraded / unresolved: there is no live geometry to converge ON.
            # Healing against it would requeue the entire corpus for a backend
            # that cannot embed, which is exactly the wrong move during an outage.
            logger.info("embedder mismatch heal skipped: active embedder tag %r names no geometry",
                        active_tag)
            zero["embedder_mismatch"]["active_tag"] = active_tag
            return zero
        expect_len = expected_blob_len(embedder)
        # WIDTH GUARD (A0g). `expect_len` is the width the ENDPOINT answered with,
        # and every classification below is made against it: rows of any other
        # width are "wrong_dim" and get requeued, and the drain then re-embeds them
        # at the endpoint's width under the canonical tag. If something STATES what
        # the width should be -- a declared `embeddings.dimensions`, or the
        # known-dimensions table for this canonical model -- and the endpoint
        # contradicts it, then it is the ENDPOINT that is wrong, and healing
        # against it would walk the store into the wrong geometry a few hundred
        # rows a day. Refuse the whole run: nothing re-tagged, nothing requeued, no
        # proxy dropped, and say so once per run so an operator sees it in the log
        # and in the health_runs row rather than discovering it in the vectors.
        contradiction = width_contradiction(embedder, self.cfg)
        if contradiction:
            logger.warning(
                "embedder mismatch heal REFUSED: %s. Nothing was re-tagged, requeued or "
                "dropped: the stored vectors are left exactly as they are, because a "
                "wrong-geometry vector that can still be found beats a store re-embedded "
                "into a geometry nobody declared. Fix the endpoint, or state the new width "
                "in embeddings.dimensions if it is intended.", contradiction)
            zero["embedder_mismatch"]["active_tag"] = active_tag
            zero["embedder_mismatch"]["width_refused"] = contradiction
            zero["vectors_width_refused"] = 1
            return zero
        budget = self._mismatch_bound()
        # A7: the bound is on the QUEUE, not on this call. Re-embedding happens
        # through curation_jobs, and the production embedder sustains ~0.5
        # texts/s — a 500-job backlog is ~17 minutes, far longer than the gap
        # between health runs. Pre-A7 every run re-selected the same first
        # `budget` rows and re-offered them to enqueue_embed_job, which deduped
        # every one: `budget` row reads and `budget` dedupe probes per run, for
        # as long as the backlog took to drain, achieving exactly nothing. So
        # the bound is spent on what is ALREADY queued first, and only the
        # remaining room is used. On a saturated queue that room is zero and the
        # requeue pass does not run at all — which is also the honest answer to
        # "should the heal add more work?" while the queue is already full.
        backlog = self.store.count_rows(
            "curation_jobs", "task='embed' AND status IN ('pending','running')")
        room = max(0, budget - int(backlog))

        total = mismatched = requeued = retagged = wrong_dim = 0
        conn = self.store._conn()

        # -- pass 1: census, O(mismatched) not O(all) (§A7) --------------------
        #
        # `_mismatched_groups` seeks only the groups that are NOT the active tag
        # at the expected width, so a healthy store's pass 1 is a handful of
        # empty index probes. The counts it returns are still EXACT and
        # store-wide -- this is the same aggregate as before, restricted to the
        # complement of "ok", plus one COUNT(*) per table for the total.
        plan = {}          # table -> list of (tag, blob_len, count, action)
        by_table = {}      # table -> {"total":, "mismatched":, "wrong_dim":}
        # ONE census (v5.7.0 integration of A0e's SCOPE with A7's COST).
        #
        # A0e widened the loop to every embedding-bearing table and made it
        # report each one individually; A7 made the loop O(mismatched) by asking
        # the complementary question and caching the denominator. Those are
        # orthogonal -- scope versus cost -- and taking either side alone loses a
        # measured fix, so both are kept: `_mismatched_groups` (A7's seek) runs
        # over `VECTOR_TABLES` (A0e's scope).
        #
        # NOTE ON INDEX COVERAGE: A7's `idx_{ov,mv,qpv}_model_width` cover three
        # of the five tables, so the seek is a true index probe there and an
        # (exact, still-complementary) scan on `session_index` and
        # `projection_vectors`. That is deliberate -- those two are the small
        # tables (one row per session / per federated projection, against one per
        # vector elsewhere) and A7's measurement that motivated the indexes was
        # taken on the big three. Correctness does not depend on the index; only
        # speed does.
        for table in self.VECTOR_TABLES:
            rows = []
            t_mismatched = t_wrong = 0
            for tag, blen, cnt in self._mismatched_groups(table, active_tag, expect_len):
                action = self._classify_tag(tag, blen, active_tag, active_id,
                                            active_marked, expect_len)
                if action == "ok":
                    # Only reachable for a tag that is a different STRING but
                    # the same canonical identity at the right width -- which
                    # _classify_tag calls "retag", never "ok". Kept as a guard
                    # so a future classifier change cannot make the census
                    # silently over-count.
                    continue
                mismatched += cnt
                t_mismatched += cnt
                if expect_len and blen and blen != expect_len:
                    wrong_dim += cnt
                    t_wrong += cnt
                rows.append((tag, blen, cnt, action))
            plan[table] = rows
            # Reported per table, ALWAYS, even at zero: a table that reports
            # nothing is indistinguishable from a table nobody is scanning, and
            # that indistinguishability is the whole A0e bug. An explicit
            # {"total": 0} says "scanned, clean"; an absent key says "not
            # covered by this heal at all". `total` is filled in below, from
            # the same cached denominator the store-wide number uses.
            by_table[table] = {"total": 0, "mismatched": t_mismatched,
                               "wrong_dim": t_wrong}
        # Denominator last, and forced to a live recount exactly when something
        # is wrong (see _cached_totals): a healthy run reports the cached total
        # with the timestamp it was taken at and never touches the corpus.
        totals, total_at = self._cached_totals(force=bool(mismatched))
        total = sum(totals.values())
        for table in self.VECTOR_TABLES:
            by_table[table]["total"] = int(totals.get(table, 0))

        # -- pass 2: re-tag in place (metadata only, unbounded, converges once) -
        for table, rows in plan.items():
            for tag, blen, cnt, action in rows:
                if action != "retag":
                    continue
                with self.store.transaction() as c:
                    if blen is None:
                        c.execute("UPDATE %s SET model=? WHERE model=? AND embedding IS NULL"
                                  % table, (active_tag, tag))
                    else:
                        c.execute("UPDATE %s SET model=? WHERE model=? AND length(embedding)=?"
                                  % table, (active_tag, tag, blen))
                retagged += cnt
                self._fingerprint("embedder_same_model_renamed", "tier1", "retag_in_place", auto=1)

        # -- pass 3: requeue what genuinely has to be re-embedded, bounded ------
        #
        # Selected by (tag, WIDTH) pair, never by tag alone. The active tag can
        # itself head a wrong-width group -- that is precisely the live
        # nemotron case, where correct-looking tags sat on 2048-dim blobs -- and
        # a tag-only WHERE would then sweep every HEALTHY row carrying that tag
        # into the requeue, spending the whole bound on rows that need nothing
        # and starving the ones that do.
        #
        # `.get` with an empty predicate below, never `[...]`: a table absent
        # from VECTOR_TABLES must make this heal do LESS, never raise. A repair
        # path that crashes when its coverage list shrinks is a worse failure
        # than the gap it was added to close.
        reembed = {t: self._reembed_predicate(rows) for t, rows in plan.items()}
        _NONE = ("", [])

        pred, params = reembed.get("observed_vectors", _NONE)
        skip_automation = self.cfg.get("embeddings.skip_automation", True)
        if pred and room > 0:
            for row in conn.execute(
                    "SELECT event_id FROM observed_vectors WHERE %s LIMIT ?" % pred,
                    (*params, room - requeued)).fetchall():
                event_id = row[0]
                # S5: an automation session's row (cron/batch/subagent) is left
                # exactly as it is -- never requeued -- so the mismatch heal does
                # not undo curation._task_embed's refusal to spend the embedder on
                # text every read path already excludes. The row stays counted as
                # "mismatched" (a wrong-geometry vector that can still be found),
                # the same trade-off `recoverable is False` below already makes.
                if skip_automation:
                    erow = conn.execute(
                        "SELECT session_id FROM events WHERE event_id=?", (event_id,)).fetchone()
                    if erow is not None and spk.is_automation_session(erow[0]):
                        continue
                # reducer.observed_vector_text, not a local re-derivation: the
                # job this queues must carry the SAME text the reducer embedded,
                # or the "repair" writes a vector of something else.
                text, recoverable = observed_vector_text(conn, event_id)
                if not recoverable:
                    continue
                if text and self.store.enqueue_embed_job(event_id, "observed", text) is not None:
                    requeued += 1
                    self._fingerprint("embedder_mismatch", "tier1", "requeue_embed", auto=1)

        pred, params = reembed.get("memory_vectors", _NONE)
        if pred and requeued < room:
            for row in conn.execute(
                    "SELECT belief_id, kind FROM memory_vectors WHERE %s LIMIT ?" % pred,
                    (*params, room - requeued)).fetchall():
                belief_id, kind = row[0], row[1]
                # THE belief-text authority (reducer), not a map maintained here.
                # `recoverable` False means the store cannot reconstruct what was
                # embedded (a pre-schema-12 procedure whose source event is gone,
                # say): the row is SKIPPED and left as it is, never requeued with
                # a near-miss like the 40-char `procedures.name`.
                text, recoverable = belief_vector_text(conn, kind, belief_id)
                if not recoverable:
                    continue
                if text and self.store.enqueue_embed_job(belief_id, kind, text) is not None:
                    requeued += 1
                    self._fingerprint("embedder_mismatch", "tier1", "requeue_embed", auto=1)

        # -- pass 3b: session summaries (A0e) ---------------------------------
        #
        # Requeueable exactly like an observed excerpt, and for the same reason:
        # the text that produced the vector is in the row itself (`summary`), so
        # a re-embed reproduces the same meaning rather than guessing at one.
        # Resolved through reducer.session_vector_text — the same authority the
        # migration tool uses — so the queued job carries the text the vector is
        # supposed to mean; `recoverable` False (row gone, or an empty summary)
        # SKIPS the row and leaves it untouched, per the A0fix refusal contract.
        # kind='session' routes curation._task_embed to update_session_vector,
        # which touches the embedding and the tag and nothing else.
        pred, params = reembed.get("session_index", _NONE)
        if pred and requeued < room:
            for row in conn.execute(
                    "SELECT session_id FROM session_index WHERE %s LIMIT ?" % pred,
                    (*params, room - requeued)).fetchall():
                session_id = row[0]
                text, recoverable = session_vector_text(conn, session_id)
                if not recoverable:
                    continue
                if self.store.enqueue_embed_job(session_id, "session", text) is not None:
                    requeued += 1
                    self._fingerprint("embedder_mismatch", "tier1", "requeue_embed", auto=1)

        # -- pass 3c: external projections (A0e) ------------------------------
        #
        # The one channel whose source text lives NOWHERE else in the store: a
        # projection's text is rendered by the caller of
        # enqueue_projection_embed out of an external database (§g5a). The embed
        # job's own payload is the only record of what those bytes meant, so
        # that is what reducer.projection_vector_text recovers. When no job
        # survives, the row is left ALONE and stays counted in `outstanding` --
        # a wrong-geometry vector that can still be found beats one silently
        # re-embedded from a text nobody wrote.
        pred, params = reembed.get("projection_vectors", _NONE)
        if pred and requeued < room:
            for row in conn.execute(
                    "SELECT provider, external_id, owner FROM projection_vectors WHERE %s LIMIT ?"
                    % pred, (*params, room - requeued)).fetchall():
                provider, external_id, owner = row[0], row[1], row[2]
                text, recoverable = projection_vector_text(conn, provider, external_id)
                if not recoverable:
                    continue
                if self.store.enqueue_projection_embed(
                        provider, external_id, text, owner=owner) is not None:
                    requeued += 1
                    self._fingerprint("embedder_mismatch", "tier1", "requeue_embed", auto=1)

        # -- pass 4: doc2query proxies that must be re-embedded are DROPPED ----
        #
        # A proxy is not requeueable the way a content vector is: the embed-job
        # queue is keyed (target, kind) and regenerates ONE vector from stored
        # text, whereas a proxy set is the variable-length output of doc2query
        # generation over the parent's key/body. Dropping is the convergent
        # move -- a stale proxy is worse than no proxy (it scores garbage
        # similarity into the fused ranking), the parent belief and its own
        # vector are untouched, and the reducer regenerates the set on that
        # belief's next write. Note that this now fires ONLY for a real
        # geometry difference: a same-model-renamed proxy is re-tagged in pass
        # 2 and keeps its vectors, where the pre-A0 heal deleted it.
        pred, params = reembed.get("query_proxy_vectors", _NONE)
        if pred:
            stale = [r[0] for r in conn.execute(
                "SELECT DISTINCT belief_id FROM query_proxy_vectors WHERE %s" % pred,
                tuple(params)).fetchall()]
            for belief_id in stale:
                self.store.delete_query_proxy_vectors(belief_id)
                self._fingerprint("embedder_mismatch", "tier1", "drop_stale_proxies", auto=1)

        # `outstanding` is what is still wrong after this run; `bounded` says
        # the REQUEUE BOUND is what stopped us, and nothing else. They are
        # separate because they call for different actions: outstanding-with-
        # bounded means "raise the bound or run the migration", while
        # outstanding-without-bounded means the remaining rows had no
        # recoverable source text or already had an identical job queued.
        outstanding = max(0, mismatched - retagged - requeued)
        # `bounded` means "the bound is what stopped us", which now includes the
        # case where the bound was already spent on the existing backlog (room
        # == 0): nothing was requeued this run because the queue is full, not
        # because the remaining rows are unfixable.
        bounded = outstanding > 0 and requeued >= room
        if mismatched:
            # `requeued 0` on a store with outstanding work reads as a stall
            # unless the line says the bound was already spent on the existing
            # backlog. State it rather than leaving an operator to infer it.
            why = ""
            if outstanding > 0:
                why = "; %d still outstanding" % outstanding
                if room <= 0:
                    why += " (nothing requeued: %d embed job(s) already queued, at the %d/run " \
                           "bound — this run waits for the queue to drain)" % (backlog, budget)
            logger.warning("embedder mismatch heal: %d/%d stored vectors are not on the active "
                           "embedder %r (%d wrong-dimension); re-tagged %d in place, requeued %d "
                           "(bound %d/run)%s", mismatched, total, active_tag, wrong_dim,
                           retagged, requeued, budget, why)
        return {"embedder_mismatch": {
                    "mismatched": mismatched, "requeued": requeued, "retagged": retagged,
                    "wrong_dim": wrong_dim, "outstanding": outstanding, "bounded": bounded,
                    # Embed jobs already queued when this run started. When it
                    # equals or exceeds the bound, `requeued` is 0 BY DESIGN and
                    # this is the reason -- stated, so it never reads as a stall.
                    "queued_backlog": int(backlog), "requeue_room": room,
                    "active_tag": active_tag, "by_table": by_table},
                "vectors_total": total,
                # When the denominator was actually counted. Never a live number
                # on a healthy run, and labelled so rather than implied (§A7).
                "vectors_total_at": total_at,
                "vectors_by_table": totals,
                "vectors_mismatched": mismatched,
                "vectors_wrong_dim": wrong_dim,
                "vectors_width_refused": 0}
