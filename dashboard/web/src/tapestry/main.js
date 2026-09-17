// dist/tapestry.js — the Tapestry. Loaded by dist/index.js when the tab first
// opens; registers window.__CHRONICLE_TAPESTRY__ = { Tapestry }.
//
// Memory is browsed by what it is ABOUT: the people, places, things, events and
// ideas it holds. How a memory arrived — which job, which session, which event
// — is provenance, and provenance is a drill-down from the thing, never the way
// in. (log.js is that drill-down; it is the whole event stream, and it opens
// from a fact or a mention.)
//
// Three panes, one selection:
//   rail    the kinds, with counts, and a search box
//   list    the entities of the chosen kind, biggest first
//   detail  one entity: what memory says now, what it used to say, the events
//           it appears in, and every captured turn that names it
//   weave   the events on a time axis, with a thread per entity they involve

import { h, hooks, fetchJSON, API, fmt } from "../common.js";
import { injectTapestryCSS } from "./styles.js";
import { EntityDetail } from "./entity.js";
import { createWeave } from "./weave.js";
import { LogView } from "./log.js";

const { useState, useEffect, useMemo, useRef, useCallback } = hooks;

const KIND_ORDER = ["person", "place", "thing", "event", "concept", "unclassified"];
const KIND_LABEL = {
  person: "People", place: "Places", thing: "Things",
  event: "Events", concept: "Ideas", unclassified: "Unclassified",
};
const LIST_PAGE = 300;

function Rail({ kinds, active, onPick, query, onQuery, total }) {
  return h("div", { className: "tap-rail" },
    h("input", {
      className: "tap-search", type: "search", value: query, placeholder: "Search memory…",
      "aria-label": "Search entities", onChange: (e) => onQuery(e.target.value),
    }),
    h("div", { className: "tap-kinds", role: "tablist" },
      KIND_ORDER.filter((k) => kinds[k]).map((k) =>
        h("button", {
          key: k, className: "tap-kind", role: "tab", "aria-selected": k === active,
          onClick: () => onPick(k),
        }, h("span", { className: "tap-kind-n" }, KIND_LABEL[k]),
           h("span", { className: "tap-kind-c" }, fmt(kinds[k]))))),
    h("div", { className: "tap-total" }, fmt(total) + " in memory"));
}

function List({ items, selected, onPick, shown, onMore }) {
  if (!items.length) return h("div", { className: "chr-quiet", style: { padding: ".75rem" } }, "Nothing here yet.");
  return h("div", { className: "tap-list" },
    items.slice(0, shown).map((it) =>
      h("button", {
        key: it.id, className: "tap-row" + (selected === it.id ? " is-sel" : ""),
        onClick: () => onPick(it),
      },
        h("span", { className: "tap-row-name" }, it.name || it.id),
        it.when ? h("span", { className: "tap-row-when" }, it.when) : null,
        it.subtype ? h("span", { className: "tap-row-sub" }, it.subtype) : null,
        it.facts ? h("span", { className: "tap-row-n" }, fmt(it.facts)) : null)),
    items.length > shown
      ? h("button", { className: "atl-link tap-more", onClick: onMore },
          "Show more (" + fmt(items.length - shown) + " left)")
      : null);
}

export function Tapestry() {
  const [index, setIndex] = useState(null);
  const [error, setError] = useState(null);
  const [kind, setKind] = useState("person");
  const [query, setQuery] = useState("");
  const [shown, setShown] = useState(LIST_PAGE);
  const [sel, setSel] = useState(null);          // the selected index item
  const [provenance, setProvenance] = useState(null);  // {event_id} → the log view
  const weaveHost = useRef(null);
  const weaveRef = useRef(null);

  useEffect(() => { injectTapestryCSS(); }, []);

  useEffect(() => {
    let cancelled = false;
    fetchJSON(API + "/tapestry/index").then((d) => {
      if (cancelled) return;
      if (d.error) { setError(d.error); return; }
      setIndex(d);
      const first = KIND_ORDER.find((k) => (d.kinds || {})[k]);
      if (first) setKind((k) => ((d.kinds || {})[k] ? k : first));
    }).catch((e) => !cancelled && setError(e.message));
    return () => { cancelled = true; };
  }, []);

  const items = useMemo(() => {
    const all = (index && index.items) || [];
    const q = query.trim().toLowerCase();
    if (q) return all.filter((it) => (it.name || "").toLowerCase().includes(q)).slice(0, 2000);
    return all.filter((it) => it.kind === kind);
  }, [index, kind, query]);

  useEffect(() => { setShown(LIST_PAGE); }, [kind, query]);

  // the weave draws the dated events, threaded through whatever they involve
  useEffect(() => {
    if (!index || !weaveHost.current) return;
    if (!weaveRef.current) {
      weaveRef.current = createWeave(weaveHost.current, {
        onPick: (item) => setSel(item),
      });
    }
    weaveRef.current.setData(index.items || [], sel && sel.id);
    return undefined;
  }, [index, sel]);

  useEffect(() => () => { if (weaveRef.current) weaveRef.current.destroy(); }, []);

  const pick = useCallback((it) => setSel(it), []);

  if (error) return h("div", { className: "chr-err" }, "Tapestry could not load: " + error);
  if (!index) return h("div", { className: "chr-quiet", style: { padding: "2rem" } }, "Reading memory…");

  if (provenance) {
    return h("div", { className: "tap" },
      h("div", { className: "tap-crumb" },
        h("button", { className: "atl-link", onClick: () => setProvenance(null) }, "← Back to memory"),
        h("span", { className: "chr-quiet" }, "Provenance: every event in the log, and this one in it")),
      h(LogView, { focusEvent: provenance.event_id || provenance.seq || null }));
  }

  return h("div", { className: "tap" },
    h(Rail, {
      kinds: index.kinds || {}, active: kind, onPick: setKind, query, onQuery: setQuery,
      total: index.total || 0,
    }),
    h("div", { className: "tap-body" },
      h("div", { className: "tap-col-list" },
        h(List, {
          items, selected: sel && sel.id, onPick: pick, shown,
          onMore: () => setShown((n) => n + LIST_PAGE),
        })),
      h("div", { className: "tap-col-main" },
        h("div", { className: "tap-weave", ref: weaveHost }),
        h(EntityDetail, {
          item: sel, onOpenProvenance: setProvenance,
          nameOf: (id) => {
            const found = (index.items || []).find((x) => x.id === id);
            return found && found.name;
          },
          onPickEntity: (id) => {
            const found = (index.items || []).find((x) => x.id === id);
            if (found) setSel(found);
          },
        }))),
    index.truncated
      ? h("div", { className: "chr-quiet" },
          "Showing the first " + fmt((index.items || []).length) + " of " + fmt(index.total))
      : null);
}

window.__CHRONICLE_TAPESTRY__ = { Tapestry };
