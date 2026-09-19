"""
Chronicle — Forgetting & compaction (§20).

Asymmetric decay: ordinary beliefs fade by fidelity (verbatim → gist →
parametric_only → tombstone), but no `high`/`critical` or `pinned` belief is ever
lost to passive decay (I10) — only explicit forget/consent-withdrawal removes
those. Decay emits a `decayed` event (a fidelity transition), never a delete.
Unlearning (§20.5) tombstones forbidden/distilled beliefs and reaches the raw
index.
"""

from __future__ import annotations

import datetime
import logging

from . import sweeps

logger = logging.getLogger("chronicle.forgetting")

_LADDER = {"verbatim": "gist", "gist": "parametric_only", "parametric_only": "tombstone"}


class ForgettingEngine:
    def __init__(self, store, cfg, append_fn):
        self.store = store
        self.cfg = cfg
        self.append = append_fn

    def decay_sweep(self, *, now: datetime.datetime | None = None) -> dict:
        """One bounded, resumable pass over the active belief tables (§A9).

        Was `query_beliefs(table, "status='active'", limit=5000)`: no ORDER BY,
        no cursor, so on a store with more than 5000 active facts this read the
        same prefix on every run and beliefs past it never aged at all — while
        the sweep returned normally and health recorded success. Now each table
        carries its own rowid cursor, so consecutive runs walk the whole table
        and the lap restarts when it ends.

        Decay is ROW-shaped — each belief's ladder step depends only on that
        row — so rowid paging is exactly right here; nothing is grouped, and a
        page boundary cannot split a decision.

        The budget is per TABLE, not per run: one run touches at most 3 × the
        decay budget (`sweeps.budgets.decay` if set, else the shared
        `sweeps.row_budget`). Returned rather than discarded so the
        `decay` curation job and `health.run()` can state how far behind the
        sweep is instead of implying it finished."""
        now = now or datetime.datetime.now(datetime.timezone.utc)
        mults = self.cfg.get("salience.decay_multipliers",
                             {"pinned": 0, "high": 0.25, "normal": 1.0, "incidental": 4.0})
        tables, decayed = {}, 0
        for table in ("facts", "episodes", "notes"):
            page = sweeps.next_row_page(self.store, self.cfg, "decay:" + table,
                                        table, "status='active'", (),
                                        budget=sweeps.sweep_budget(self.cfg, "decay"))
            for row in page.rows:
                if not self._eligible(row, now, mults):
                    continue
                nxt = _LADDER.get(row.get("fidelity") or "verbatim")
                if not nxt:
                    continue
                decayed += 1
                self.append("decayed", {"belief_id": row["belief_id"],
                                        "from_fidelity": row.get("fidelity") or "verbatim",
                                        "to_fidelity": nxt}, actor="curator", owner=row.get("owner", "default"))
            tables[table] = sweeps.commit(self.store, page)
        return {"decayed": decayed,
                "scanned": sum(t["processed"] for t in tables.values()),
                "remaining": sum(t["remaining"] for t in tables.values()),
                "bounded": any(t["bounded"] for t in tables.values()),
                "tables": tables}

    def _eligible(self, row, now, mults) -> bool:
        # I10: critical/high never decays; pinned never decays.
        if row.get("criticality") in ("high", "critical"):
            return False
        if row.get("salience") == "pinned":
            return False
        domain = row.get("domain") or "general"
        dom = self.cfg.get(f"domains.{domain}", {})
        if not dom.get("auto_decay", domain != "user"):
            return False
        decay_days = dom.get("decay_days", 30 if domain == "general" else 90)
        age_days = _age_days(row.get("last_seen_at") or row.get("created_at"), now)
        salience_mult = mults.get(row.get("salience") or "normal", 1.0)
        utility_factor = max(0.25, 1.0 - (row.get("utility") or 0.0))
        threshold = decay_days * max(salience_mult, 0.01) * utility_factor
        return age_days > threshold

    def unlearn(self, belief_id: str, reason: str = "unlearn"):
        """§20.5: forbid + tombstone (reaching the raw index) + quarantine."""
        found = self.store.find_belief(belief_id)
        if not found:
            return
        row = found[1]
        from .serialize import hash_str
        content = row.get("value") or row.get("body") or row.get("summary") or ""
        self.append("forbidden", {"content_hash": hash_str(content), "scope": "*"},
                    actor="curator", owner=row.get("owner", "default"))
        self.append("retracted", {"belief_id": belief_id, "reason": reason},
                    actor="curator", owner=row.get("owner", "default"))


def _age_days(ts, now):
    if not ts:
        return 0.0
    try:
        t = datetime.datetime.fromisoformat(ts.replace("Z", "+00:00"))
        return (now - t).total_seconds() / 86400.0
    except (ValueError, AttributeError):
        return 0.0
