"""
Chronicle — resumable, observably-bounded sweeps (§A9).

THE DEFECT THIS REMOVES. Every periodic sweep in the engine used to read its
work with `query_beliefs(table, where, limit=5000)`. That call has no ORDER BY
and no cursor, so it returns *a* prefix of the matching rows — in practice the
same prefix every time. Past 5000 matching rows the sweep therefore:

  * processes the prefix,
  * never reaches row 5001,
  * and returns normally, so `health.run()` records a success.

On the live store (108,581 memory vectors, 89,562 observed vectors, ~67k
historical extract jobs) that means the forgetting, consistency, canonicalize
and backfill sweeps have been permanently partial, and nothing anywhere said
so. It is the same shape as the A7 heal bug: a bound applied at the wrong
layer, so the work never progressed and the report never admitted it.

THE FIX has three parts, and all three are required — any two of them still
leave a sweep that lies:

  1. RESUMABLE. A cursor persisted in `meta` (`store.get_sweep_state`) means
     run N+1 starts where run N stopped. When a lap finishes the cursor wraps
     to the start, so edits to rows already swept are eventually revisited —
     the same ingest/rescan reasoning `_sweep_local_db` uses for federation.

  2. OBSERVABLE. Each run returns a `SweepPage` whose `report()` carries
     processed / remaining / bounded / wrapped. `bounded=True` with a nonzero
     `remaining` is the honest statement "there is outstanding work this run
     did not do", and it reaches `health.run()`'s snapshot. A sweep that is
     permanently behind now says so on every run.

  3. BOUNDED, but by CONFIG. The per-run budget stays — an unbounded sweep on
     a 2-core box is its own hazard, and the A7 drain exists precisely because
     one unbounded batch starved everything else. It is `sweeps.row_budget`
     with a per-sweep override under `sweeps.budgets.*`, not a literal.

TWO PAGING KEYS, because sweeps come in two shapes:

  * ROW-shaped (decay, ghost_facts, reextract): the unit of work is one row,
    rows are independent, so rowid paging is exactly right — `next_row_page`.

  * GROUP-shaped (consistency, canonicalize, identity, derive_subjects,
    backfill): the unit of work is every row sharing a key. Paging by rowid
    would bisect a group across two runs and the sweep would draw a wrong
    conclusion from half the evidence (a single-cardinality predicate looks
    consistent if you only see one of its two values). These page over the
    DISTINCT grouping column — `next_distinct_page`, then
    `store.beliefs_for_values` to load the named groups — so a group is always
    COMPLETE inside one page.

    The group cursor's start sentinel is None, not "": the scan is an exclusive
    `> after` and nothing sorts before "", so "" as a start would skip the
    ''-keyed group (the COALESCE'd NULL predicates and unnamed entities) on
    every run forever. That is this same defect, one group wide.

NOT EVERY CAP IS THIS BUG. `reducer._on_forbidden` and `_beliefs_matching_hash`
must reach *every* belief matching a forbidden hash; a run that did a prefix
would leave forbidden content live and readable while the event log recorded
that it was forbidden. Those get `iter_all_rows` — paged for memory, but
looping to exhaustion inside the single call. It costs more than the old cap
did (a full scan of `facts` instead of 5000 rows of it: measured at 1.14 s for
108,581 rows, against ~50 ms capped) and that is the right trade — a
`forbidden` event is rare, and a bound on a redaction is not a pace, it is a
leak.
"""

from __future__ import annotations

import logging

from .store import now_iso

logger = logging.getLogger("chronicle.sweeps")

# Fallback when neither `sweeps.budgets.<name>` nor `sweeps.row_budget` parses.
# Deliberately the old hard-coded 5000: with a cursor and a report attached,
# the same number stops being a silent truncation and becomes a stated pace.
DEFAULT_ROW_BUDGET = 5000

# Rows one SQL round trip may materialize inside `iter_all_rows`. This is a
# MEMORY bound, never a work bound: the loop keeps going until the table is
# exhausted.
DEFAULT_PAGE_ROWS = 1000


def sweep_budget(cfg, name: str, default: int | None = None) -> int:
    """Per-run row budget for sweep `name`.

    `sweeps.budgets.<name>` wins; `sweeps.row_budget` is the shared fallback;
    `default` (a caller's documented pace, e.g. derivation's fanout bound) is
    consulted before the module constant. Never returns < 1 — a zero budget
    would be a sweep that reports success while doing nothing, which is the
    defect wearing a different hat."""
    raw = cfg.get(f"sweeps.budgets.{name}", None) if cfg is not None else None
    if raw is None and cfg is not None:
        raw = cfg.get("sweeps.row_budget", None)
    if raw is None:
        raw = DEFAULT_ROW_BUDGET if default is None else default
    try:
        return max(1, int(raw))
    except (TypeError, ValueError):
        logger.warning("chronicle: sweeps budget for %s is not an int (%r); using %d",
                       name, raw, DEFAULT_ROW_BUDGET)
        return DEFAULT_ROW_BUDGET


def page_rows(cfg) -> int:
    """Memory page size for `iter_all_rows` (`sweeps.page_rows`).

    `cfg` is optional because the reducer is constructed with `cfg=None` in
    several call paths, and a fold that must be COMPLETE cannot be allowed to
    fail — or to silently shorten — just because nobody handed it a config."""
    if cfg is None:
        return DEFAULT_PAGE_ROWS
    try:
        return max(1, int(cfg.get("sweeps.page_rows", DEFAULT_PAGE_ROWS)))
    except (TypeError, ValueError):
        return DEFAULT_PAGE_ROWS


class SweepPage:
    """One run's worth of work, plus the arithmetic that makes it honest.

    `rows` is what to process. `remaining` is what this run did NOT do, counted
    against the cursor the next run will start from — so it is a fact about the
    store, not an estimate. `bounded` is `remaining > 0`: the budget bit, the
    thing a caller must surface rather than swallow."""

    __slots__ = ("name", "rows", "cursor_before", "cursor", "remaining",
                 "budget", "wrapped", "total")

    def __init__(self, name, rows, cursor_before, cursor, remaining, budget, wrapped, total):
        self.name = name
        self.rows = rows
        self.cursor_before = cursor_before
        self.cursor = cursor
        self.remaining = int(remaining)
        self.budget = int(budget)
        self.wrapped = bool(wrapped)
        self.total = int(total)

    @property
    def processed(self) -> int:
        return len(self.rows)

    @property
    def bounded(self) -> bool:
        return self.remaining > 0

    def report(self) -> dict:
        return {"sweep": self.name, "processed": self.processed,
                "remaining": self.remaining, "bounded": self.bounded,
                "budget": self.budget, "wrapped": self.wrapped,
                "total": self.total, "cursor": self.cursor, "at": now_iso()}


def _cursor_int(store, name: str) -> int:
    try:
        return int(store.get_sweep_state(name).get("cursor") or 0)
    except (TypeError, ValueError):
        return 0


def _cursor_text(store, name):
    """The group cursor, or None for "start of the lap".

    None and "" are DIFFERENT and the difference is load-bearing. The scan is an
    exclusive `> after`, and no string sorts before "", so a cursor of "" as the
    start sentinel would skip the ''-keyed group forever — and '' is exactly
    where the COALESCE'd NULL predicates and unnamed entities live. So the start
    is None ("no lower bound") and "" is a real position meaning "the ''-group is
    done"."""
    state = store.get_sweep_state(name)
    return state.get("cursor") if "cursor" in state else None


def next_row_page(store, cfg, name: str, table: str, where: str = "1=1",
                  params: tuple = (), budget: int | None = None) -> SweepPage:
    """Resume a ROW-shaped sweep: the next `budget` rows after the cursor.

    A short page means the lap is over, so the cursor wraps to 0 and the next
    run starts from the top of the table. Wrapping is what lets a sweep see
    rows that became eligible *behind* the cursor — without it a watermark
    sweep goes quiet forever once it reaches the end, which is the failure
    `get_sessions_needing_index_backfill` shipped with."""
    budget = sweep_budget(cfg, name) if budget is None else max(1, int(budget))
    start = _cursor_int(store, name)
    rows = store.scan_beliefs_after(table, where, params, start, budget)
    if rows:
        last = int(rows[-1]["_rowid"])
    else:
        last = start
    if len(rows) < budget:
        remaining, cursor, wrapped = 0, 0, True
    else:
        remaining = store.count_beliefs_after(table, where, params, last)
        # A page that exactly drained the tail still ends the lap.
        wrapped = remaining == 0
        cursor = 0 if wrapped else last
    total = store.count_beliefs_after(table, where, params, 0)
    return SweepPage(name, rows, start, cursor, remaining, budget, wrapped, total)


def next_distinct_page(store, cfg, name: str, table: str, column: str,
                       where: str = "1=1", params: tuple = (),
                       budget: int | None = None) -> SweepPage:
    """Resume a GROUP-shaped sweep: the next `budget` DISTINCT `column` values.

    `rows` here is a list of column values (entity ids, canonical predicates),
    not belief rows: the caller loads each group's members itself, which is the
    whole point — the group arrives complete."""
    budget = sweep_budget(cfg, name) if budget is None else max(1, int(budget))
    start = _cursor_text(store, name)
    values = store.scan_distinct_after(table, column, where, params, start, budget)
    last = values[-1] if values else start
    if len(values) < budget:
        remaining, cursor, wrapped = 0, None, True
    else:
        remaining = store.count_distinct_after(table, column, where, params, last)
        wrapped = remaining == 0
        cursor = None if wrapped else last
    total = store.count_distinct_after(table, column, where, params, None)
    return SweepPage(name, values, start, cursor, remaining, budget, wrapped, total)


def commit(store, page: SweepPage) -> dict:
    """Persist the cursor AND the report, and return the report.

    One write, both halves: a cursor saved without its report is the silent
    sweep this task exists to remove, so they cannot drift apart."""
    report = page.report()
    state = dict(report)
    state["cursor"] = page.cursor
    store.save_sweep_state(page.name, state)
    if page.bounded:
        logger.info("chronicle: sweep %s bounded — processed %d of %d, %d remaining",
                    page.name, page.processed, page.total, page.remaining)
    return report


def iter_all_rows(store, cfg, table: str, where: str = "1=1", params: tuple = ()):
    """Every matching row, paged for MEMORY only — never truncated.

    For the correctness folds (`_on_forbidden`) where a partial pass is worse
    than a slow one. Rows are yielded in rowid order; the page size is
    `sweeps.page_rows`."""
    size = page_rows(cfg)
    after = 0
    while True:
        rows = store.scan_beliefs_after(table, where, params, after, size)
        if not rows:
            return
        for r in rows:
            yield r
        after = int(rows[-1]["_rowid"])
        if len(rows) < size:
            return
