// Inspector (right column) and lenses (below the canvas). Plain React through
// the plugin SDK; every value shown comes from an /atlas endpoint.

import { h, hooks, C, fetchJSON, API, fmt, when } from "../common.js";
import { typeStyle, laneLabel } from "./data.js";

const { useState, useEffect } = hooks;

const STATUS_TONE = { active: "success", superseded: "outline", draft: "warning", retracted: "destructive", forgotten: "destructive" };
const KIND_LABEL = { fact: "Fact", note: "Note", episode: "Episode", reference: "Reference", procedure: "Procedure", entity: "Entity", relationship: "Relationship" };

function Status({ status }) {
  const Badge = C.Badge;
  return h(Badge, { tone: STATUS_TONE[status] || "outline" }, status === "superseded" ? "replaced" : status === "draft" ? "pending review" : status || "active");
}

function Section({ title, children, count }) {
  return h("div", { className: "atl-sec" },
    h("div", { className: "atl-sec-t" }, title, count != null ? h("span", { className: "chr-num" }, " " + fmt(count)) : null),
    children);
}

function BeliefRow({ b, onBelief }) {
  if (!b) return null;
  return h("button", { className: "atl-row", onClick: () => onBelief(b.belief_id) },
    h("span", { className: "atl-row-k" }, KIND_LABEL[b.kind] || b.kind, b.label ? " · " + b.label : ""),
    h("span", { className: "atl-row-x" }, b.text || "(empty)"),
    h("span", { className: "atl-row-m" }, h(Status, { status: b.status }), b.created_at ? " " + when(b.created_at) : ""));
}

function useFetch(url) {
  const [state, setState] = useState({ loading: true, data: null, error: null });
  useEffect(() => {
    let live = true;
    setState({ loading: true, data: null, error: null });
    fetchJSON(url).then((data) => live && setState({ loading: false, data, error: data && data.error ? data.error : null }))
      .catch((e) => live && setState({ loading: false, data: null, error: (e && e.message) || "failed" }));
    return () => { live = false; };
  }, [url]);
  return state;
}

function Loading({ state, children }) {
  if (state.loading) return h("div", { className: "chr-quiet atl-pad" }, "Loading…");
  if (state.error) return h("div", { className: "chr-err" }, state.error);
  if (state.data && state.data.found === false) return h("div", { className: "chr-quiet atl-pad" }, "Not found in the store.");
  return children(state.data);
}

export function Inspector({ sel, model, cronNames, onBelief, onEventSeq, onSession, onLane }) {
  if (!sel) {
    return h("div", { className: "atl-pad chr-quiet" },
      h("p", null, "Every point is one event in the log, on the row of whatever wrote it: a cron job, a chat session, or a background process."),
      h("p", null, "Click a point, a row label, or anything in the lists below to see where it came from and what memory it produced. Drag across the chart above to zoom to a time range; double-click it to see everything."));
  }
  if (sel.kind === "event") return h(EventInspector, { seq: sel.seq, model, cronNames, onBelief, onEventSeq, onSession, onLane });
  if (sel.kind === "session") return h(SessionInspector, { id: sel.id, model, cronNames, onBelief, onEventSeq, onLane });
  if (sel.kind === "belief") return h(BeliefInspector, { id: sel.id, onBelief, onEventSeq, onSession });
  if (sel.kind === "lane") return h(LaneInspector, { lane: sel.lane, model, cronNames, onSession });
  return null;
}

function EventInspector({ seq, model, cronNames, onBelief, onEventSeq, onSession, onLane }) {
  const st = useFetch(API + "/atlas/event?seq=" + seq);
  return h(Loading, { state: st }, (e) => {
    const style = typeStyle(e.type);
    const laneIx = model.laneIx.get(e.lane);
    return h("div", null,
      h("div", { className: "atl-head" },
        h("span", { className: "chr-mark", style: { background: "rgb(" + style.color.join(",") + ")" } }),
        h("span", null, style.label),
        h("span", { className: "chr-quiet" }, " · " + e.actor + " · " + when(e.recorded_at))),
      h("div", { className: "atl-text" }, e.text || h("span", { className: "chr-quiet" }, "This event carries no readable text.")),
      h("div", { className: "atl-links" },
        laneIx != null ? h("button", { className: "atl-link", onClick: () => onLane(laneIx) }, laneLabel(e.lane, cronNames)) : null,
        e.session_id ? h("button", { className: "atl-link", onClick: () => onSession(e.session_id) }, "Open this run") : null),
      e.source ? h(Section, { title: "Extracted from" },
        h("button", { className: "atl-row", onClick: () => onEventSeq(e.source.seq) },
          h("span", { className: "atl-row-k" }, typeStyle(e.source.type).label + " · " + e.source.actor),
          h("span", { className: "atl-row-x" }, e.source.text || "—"),
          h("span", { className: "atl-row-m" }, when(e.source.recorded_at)))) : null,
      e.source_beliefs && e.source_beliefs.length ? h(Section, { title: "Memory extracted from that turn", count: e.source_beliefs.length },
        e.source_beliefs.map((b) => h(BeliefRow, { key: b.belief_id, b, onBelief }))) : null,
      e.beliefs.length || !e.source ? h(Section, { title: "Memory citing this event", count: e.beliefs.length },
        e.beliefs.length ? e.beliefs.map((b) => h(BeliefRow, { key: b.belief_id, b, onBelief }))
          : h("div", { className: "chr-quiet" }, "No belief cites this event.")) : null);
  });
}

function SessionInspector({ id, model, cronNames, onBelief, onEventSeq, onLane }) {
  const st = useFetch(API + "/atlas/session?id=" + encodeURIComponent(id));
  return h(Loading, { state: st }, (s) => {
    const laneIx = model.laneIx.get(s.lane);
    return h("div", null,
      h("div", { className: "atl-head" }, h("span", null, laneLabel(s.lane, cronNames)),
        h("span", { className: "chr-quiet" }, " · " + fmt(s.events) + " events · " + when(s.first_at))),
      laneIx != null ? h("div", { className: "atl-links" }, h("button", { className: "atl-link", onClick: () => onLane(laneIx) }, "All runs of this writer")) : null,
      s.summary ? h("div", { className: "atl-text" }, s.summary) : null,
      h("div", { className: "atl-chips" }, Object.entries(s.types).map(([t, n]) =>
        h("span", { key: t, className: "atl-chip" }, typeStyle(t).label + " " + fmt(n)))),
      h(Section, { title: "Memory formed from this run", count: s.beliefs.length },
        s.beliefs.length ? s.beliefs.map((b) => h(BeliefRow, { key: b.belief_id, b, onBelief }))
          : h("div", { className: "chr-quiet" }, "No belief cites this run.")),
      h(Section, { title: s.events > s.turns.length ? "First " + s.turns.length + " events" : "Events", count: s.events },
        s.turns.map((t) => h("button", { key: t.seq, className: "atl-row", onClick: () => onEventSeq(t.seq) },
          h("span", { className: "atl-row-k" }, typeStyle(t.type).label + " · " + t.actor),
          h("span", { className: "atl-row-x" }, t.text || "—"),
          h("span", { className: "atl-row-m" }, when(t.recorded_at))))));
  });
}

function BeliefInspector({ id, onBelief, onEventSeq, onSession }) {
  const st = useFetch(API + "/atlas/belief?id=" + encodeURIComponent(id));
  return h(Loading, { state: st }, (b) => h("div", null,
    h("div", { className: "atl-head" },
      h("span", null, (KIND_LABEL[b.kind] || b.kind) + (b.label ? " · " + b.label : "")),
      h(Status, { status: b.status })),
    b.entity_name ? h("div", { className: "chr-quiet" }, "About: " + b.entity_name) : null,
    h("div", { className: "atl-text" }, b.text || "(empty)"),
    h("div", { className: "atl-facts" },
      b.confidence != null ? h("span", null, "Confidence " + Number(b.confidence).toFixed(2)) : null,
      b.created_at ? h("span", null, "Written " + when(b.created_at)) : null,
      b.valid_until ? h("span", null, "Held until " + when(b.valid_until)) : null,
      b.provenance && b.provenance.sightings > 1 ? h("span", null, "Seen " + fmt(b.provenance.sightings) + " times") : null,
      b.identical_active > 1 ? h("span", { className: "atl-warn" }, fmt(b.identical_active) + " identical active copies") : null),
    b.replaced.length ? h(Section, { title: "Replaced" }, b.replaced.map((v) => h(BeliefRow, { key: v.belief_id, b: v, onBelief }))) : null,
    b.replaced_by.length ? h(Section, { title: "Replaced by" }, b.replaced_by.map((v) => h(BeliefRow, { key: v.belief_id, b: v, onBelief }))) : null,
    b.contradictions.length ? h(Section, { title: "Contradicted by", count: b.contradictions.length },
      b.contradictions.map((c) => h("div", { key: c.id }, h(BeliefRow, { b: c.other, onBelief }),
        c.detail ? h("div", { className: "chr-quiet atl-sub" }, c.detail + " · " + c.status) : null))) : null,
    h(Section, { title: "Where it came from", count: b.supports_total },
      b.supports.length ? b.supports.map((s) => h("button", { key: s.seq, className: "atl-row", onClick: () => onEventSeq(s.seq) },
        h("span", { className: "atl-row-k" }, typeStyle(s.type).label + " · " + s.actor + (s.rule ? " · " + s.rule : "")),
        h("span", { className: "atl-row-x" }, s.text || "—"),
        h("span", { className: "atl-row-m" }, when(s.recorded_at), s.session_id ? " " : null,
          s.session_id ? h("a", { className: "atl-inline", onClick: (ev) => { ev.stopPropagation(); onSession(s.session_id); } }, "run") : null)))
        : h("div", { className: "chr-quiet" }, "No event in the log is cited as this belief's source."))));
}

function LaneInspector({ lane, model, cronNames, onSession }) {
  const L = model.lanes[lane];
  if (!L) return null;
  const runs = [...L.sessions].map((s) => model.sessions[s]).sort((a, b) => b.first - a.first);
  const typeCounts = new Map();
  for (let k = 0; k < model.n; k++) if (model.lane[k] === lane) {
    const name = model.types[model.type[k]];
    typeCounts.set(name, (typeCounts.get(name) || 0) + 1);
  }
  return h("div", null,
    h("div", { className: "atl-head" }, h("span", null, laneLabel(L.key, cronNames))),
    h("div", { className: "atl-facts" },
      h("span", null, fmt(L.count) + " events"),
      runs.length ? h("span", null, fmt(runs.length) + " runs") : null,
      h("span", null, when(L.first) + " → " + when(L.last))),
    h("div", { className: "atl-chips" }, [...typeCounts.entries()].sort((a, b) => b[1] - a[1]).map(([t, n]) =>
      h("span", { key: t, className: "atl-chip" }, typeStyle(t).label + " " + fmt(n)))),
    runs.length ? h(Section, { title: runs.length > 60 ? "Latest 60 runs" : "Runs", count: runs.length },
      runs.slice(0, 60).map((r) => h("button", { key: r.id, className: "atl-row", onClick: () => onSession(r.id) },
        h("span", { className: "atl-row-x" }, when(r.first)),
        h("span", { className: "atl-row-m" }, fmt(r.count) + " events")))) : null);
}

// -- lenses ---------------------------------------------------------------------
export function Lenses({ model, onBelief }) {
  const [tab, setTab] = useState("contradictions");
  const tabs = [["contradictions", "Contradictions"], ["histories", "Replaced facts"], ["duplicates", "Duplicate notes"]];
  return h("div", { className: "atl-lenses" },
    h("div", { className: "chr-tabs", role: "tablist" }, tabs.map(([k, label]) =>
      h("button", { key: k, className: "chr-tab", role: "tab", "aria-selected": tab === k, onClick: () => setTab(k) }, label))),
    tab === "contradictions" ? h(ContradictionsLens, { onBelief })
      : tab === "histories" ? h(HistoriesLens, { model, onBelief })
        : h(DuplicatesLens, { onBelief }));
}

function ContradictionsLens({ onBelief }) {
  const st = useFetch(API + "/atlas/contradictions?limit=100");
  return h(Loading, { state: st }, (d) => h("div", { className: "atl-lens" },
    h("div", { className: "chr-quiet atl-pad-s" }, fmt(d.total) + " open. Pairs of beliefs the store holds that cannot both be true; newest first."),
    d.items.map((c) => h("div", { key: c.id, className: "atl-pair" },
      h(BeliefRow, { b: c.a, onBelief }), h("div", { className: "atl-vs" }, "vs"), h(BeliefRow, { b: c.b, onBelief })))));
}

function HistoriesLens({ model, onBelief }) {
  const st = useFetch(API + "/atlas/histories?limit=100");
  return h(Loading, { state: st }, (d) => {
    const [x0, x1] = model.extentX();
    const span = Math.max(1e-6, x1 - x0);
    const pos = (iso) => {
      const t = Date.parse(iso) / 1000;
      return isFinite(t) ? Math.max(0, Math.min(1, (model.xOf(t) - x0) / span)) : null;
    };
    return h("div", { className: "atl-lens" },
      h("div", { className: "chr-quiet atl-pad-s" }, fmt(d.total) + " facts whose value changed. Each bar spans the whole log; each segment is one value, from when it was written until the next."),
      d.items.map((it) => h("div", { key: it.entity_id + "/" + it.predicate, className: "atl-hist" },
        h("div", { className: "atl-hist-l" }, it.entity + " · " + it.predicate),
        h("div", { className: "atl-hist-bar" }, it.versions.map((v, i) => {
          const a = pos(v.created_at);
          const next = it.versions[i + 1];
          const b = next ? pos(next.created_at) : 1;
          if (a == null) return null;
          return h("button", { key: v.belief_id, title: v.value + " (" + v.status + ")", className: "atl-seg atl-seg-" + (v.status || "active"),
            style: { left: (a * 100).toFixed(3) + "%", width: Math.max(0.4, ((b == null ? 1 : b) - a) * 100).toFixed(3) + "%" },
            onClick: () => onBelief(v.belief_id) });
        })),
        h("div", { className: "atl-hist-v" }, it.versions.map((v) => v.value).join(" → ")))));
  });
}

function DuplicatesLens({ onBelief }) {
  const st = useFetch(API + "/atlas/duplicates?limit=50");
  return h(Loading, { state: st }, (d) => {
    const max = d.items.length ? d.items[0].copies : 1;
    return h("div", { className: "atl-lens" },
      h("div", { className: "chr-quiet atl-pad-s" }, fmt(d.redundant) + " extra copies across " + fmt(d.groups) + " notes stored more than once with identical text. New repeats merge; these predate that."),
      d.items.map((g) => h("button", { key: g.example_id, className: "atl-row atl-dup", onClick: () => onBelief(g.example_id) },
        h("span", { className: "atl-dup-n chr-num" }, fmt(g.copies) + "×"),
        h("span", { className: "atl-dup-bar" }, h("span", { style: { width: ((g.copies / max) * 100).toFixed(1) + "%" } })),
        h("span", { className: "atl-row-x" }, g.text),
        h("span", { className: "atl-row-m" }, g.subject + " · " + when(g.first_at) + " → " + when(g.last_at)))));
  });
}
