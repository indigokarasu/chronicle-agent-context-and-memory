// Chronicle dashboard plugin entry (dist/index.js).
//
// Two tabs. Overview: store counts, embedding coverage, recent activity and the
// extraction queue action (ported from the hand-written bundle this replaces,
// now versioned with the plugin). Atlas: the memory navigator, whose bundle
// (dist/atlas.js, with deck.gl) is loaded only when the tab is first opened so
// every other dashboard page pays nothing for it.

import { SDK, PLUGINS, h, hooks, C, fetchJSON, API, fmt, relTime, injectCSS } from "./common.js";

function main() {
  const { useState, useEffect, useCallback } = hooks;
  const { Card, CardHeader, CardTitle, CardContent, Badge, Button } = C;

  const KIND_COLORS = { event: "#3b82f6", note: "#ab47bc", episode: "#f9a825", fact: "#f57c00", document: "#43a047", entity: "#9b59b6" };
  const LABELS = { event: "Events", note: "Notes", episode: "Episodes", fact: "Facts", document: "Documents", entity: "Entities" };

  function Kpi(label, value, unit) {
    return h("div", { className: "chr-kpi" },
      h("div", { className: "chr-kpi-l" }, label),
      h("div", { className: "chr-kpi-v" }, value, unit ? h("span", { className: "chr-kpi-u" }, unit) : null));
  }

  function CompositionCard(store) {
    const segs = ["event", "note", "episode", "fact", "document", "entity"]
      .map((k) => ({ kind: k, name: LABELS[k], count: store[k + "s"] || 0, color: KIND_COLORS[k] }))
      .filter((s) => s.count > 0)
      .sort((a, b) => b.count - a.count);
    const total = segs.reduce((a, s) => a + s.count, 0);
    let acc = 0;
    const stops = segs.map((s) => {
      const a = (acc / total) * 100;
      acc += s.count;
      return s.color + " " + a.toFixed(2) + "% " + ((acc / total) * 100).toFixed(2) + "%";
    });
    const gradient = total > 0 ? "conic-gradient(" + stops.join(", ") + ")" : "conic-gradient(var(--bd) 0 100%)";
    return h(Card, null,
      h(CardHeader, { className: "pb-2" }, h(CardTitle, { className: "text-sm" }, "Memory composition")),
      h(CardContent, null,
        h("div", { className: "chr-comp" },
          h("div", { className: "chr-donut", style: { "--g": gradient } },
            h("div", { className: "ctr" },
              h("span", { className: "text-xl font-light chr-num" }, fmt(total)),
              h("span", { className: "text-xs text-muted-foreground" }, "items"))),
          h("div", { className: "chr-legend" }, segs.map((s) =>
            h("div", { key: s.kind, className: "chr-leg-row" },
              h("span", { className: "chr-sw", style: { background: s.color } }),
              h("span", { className: "chr-leg-name" }, s.name),
              h("span", { className: "chr-leg-ct" }, fmt(s.count)),
              h("span", { className: "chr-leg-pct" }, (total ? Math.round((s.count / total) * 100) : 0) + "%")))))));
  }

  function CoverageCard(emb, store) {
    const rows = ["event", "note", "episode", "fact", "document"]
      .map((k) => ({ kind: k, ...(emb[k] || {}) }))
      .filter((r) => (r.total || 0) > 0)
      .sort((a, b) => (store[b.kind + "s"] || 0) - (store[a.kind + "s"] || 0));
    return h(Card, null,
      h(CardHeader, { className: "pb-2" }, h(CardTitle, { className: "text-sm" }, "Embedding coverage by type")),
      h(CardContent, null, rows.length === 0
        ? h("span", { className: "chr-quiet" }, "No embeddable items yet.")
        : rows.map((r) => h("div", { key: r.kind, className: "chr-cov" },
            h("span", { className: "chr-cov-l" }, LABELS[r.kind]),
            h("span", { className: "chr-track" },
              h("span", { className: "chr-fill", style: { width: Math.max(0, Math.min(100, r.pct || 0)) + "%", background: KIND_COLORS[r.kind] } })),
            h("span", { className: "chr-cov-v", style: (r.pct || 0) >= 100 ? null : { color: "var(--warn)" } }, fmt(r.pct || 0) + "%")))));
  }

  function ActivityCard(events) {
    return h(Card, null,
      h(CardHeader, { className: "pb-2" }, h(CardTitle, { className: "text-sm" }, "Recent activity")),
      h(CardContent, null, !events || events.length === 0
        ? h("span", { className: "chr-quiet" }, "No recent events.")
        : h("div", null, events.map((e, i) =>
            h("div", { key: e.id || i, className: "chr-act" },
              h("span", { className: "chr-mark", style: { background: KIND_COLORS[e.kind] || "var(--muted)" } }),
              h(Badge, { tone: "outline" }, e.verb || e.kind),
              h("span", { className: "chr-act-sum" }, e.summary || e.kind),
              e.source ? h("span", { className: "chr-act-time" }, e.source) : null,
              h("span", { className: "chr-act-time" }, relTime(e.created_at)))))));
  }

  function Overview() {
    const [data, setData] = useState(null);
    const [recent, setRecent] = useState(null);
    const [err, setErr] = useState(null);
    const [busy, setBusy] = useState(false);
    const [note, setNote] = useState(null);

    const load = useCallback(() => {
      Promise.all([
        fetchJSON(API + "/status"),
        fetchJSON(API + "/recent?limit=12").catch(() => null),
      ]).then(([s, r]) => { setData(s); setRecent(r); setErr(null); })
        .catch((e) => setErr((e && e.message) || "Failed to load"));
    }, []);

    useEffect(() => { load(); const iv = setInterval(load, 60000); return () => clearInterval(iv); }, [load]);

    // POST /enqueue-extractions: queues an `extract` job for every observed event
    // that has none. (The bundle this replaces still called /process-embeddings,
    // which A13 renamed; its button had been failing since.)
    const enqueue = useCallback(() => {
      setBusy(true);
      fetchJSON(API + "/enqueue-extractions?limit=500", { method: "POST" })
        .then((r) => { setNote(r && r.ok ? "Queued " + fmt(r.enqueued) + " extractions." : "Nothing queued: " + ((r && r.error) || "unknown error")); load(); })
        .catch((e) => setNote("Queueing failed: " + ((e && e.message) || "error")))
        .finally(() => setBusy(false));
    }, [load]);

    if (err && !data) {
      return h("div", { className: "chr-err", role: "alert" }, "Could not load Chronicle: " + err + " ",
        h(Button, { size: "sm", variant: "outline", onClick: load }, "Retry"));
    }
    if (!data) return h("div", { className: "chr-quiet", style: { padding: "2rem" } }, "Loading Chronicle…");
    if (data.status === "no_db") return h("div", { className: "chr-quiet", style: { padding: "2rem" } }, "No Chronicle database found.");

    const store = data.store || {};
    const emb = data.embeddings || {};
    let sumE = 0, sumT = 0;
    for (const k of ["event", "session", "episode", "note", "fact", "reference", "procedure", "projection", "document"]) {
      sumE += (emb[k] || {}).embedded || 0;
      sumT += (emb[k] || {}).total || 0;
    }
    const candidates = store.enqueue_candidates || 0;
    return h("div", { className: "chr", style: { gap: "1rem" } },
      h("div", { className: "chr-kpis" },
        Kpi("Events", fmt(store.events)),
        Kpi("Embedded", sumT ? Math.round((100 * sumE) / sumT) : 0, "%"),
        Kpi("Pending jobs", fmt(store.pending_jobs)),
        Kpi("Facts", fmt(store.facts)),
        Kpi("Episodes", fmt(store.episodes))),
      h("div", { className: "chr-grid" }, CompositionCard(store), CoverageCard(emb, store)),
      candidates > 0
        ? h(Card, null,
            h(CardHeader, { className: "pb-2" }, h(CardTitle, { className: "text-sm" }, fmt(candidates) + " turns not yet extracted")),
            h(CardContent, null,
              h("div", { className: "chr-act" },
                h(Button, { size: "sm", variant: "outline", disabled: busy, onClick: enqueue }, busy ? "Queueing…" : "Queue up to 500 extractions"),
                note ? h("span", { className: "chr-quiet" }, note) : null)))
        : null,
      ActivityCard(recent && recent.events));
  }

  // -- Atlas: load dist/atlas.js next to this file, once --------------------------
  let atlasPromise = null;
  function loadAtlas() {
    if (window.__CHRONICLE_ATLAS__) return Promise.resolve(window.__CHRONICLE_ATLAS__);
    if (atlasPromise) return atlasPromise;
    atlasPromise = new Promise((resolve, reject) => {
      const self = document.querySelector('script[data-hermes-plugin="chronicle"]');
      // dist/atlas.js sits next to the dist/index.js the host loaded
      const src = self && self.src ? self.src.split("?")[0] : "";
      const base = src ? src.slice(0, src.lastIndexOf("/") + 1) : "";
      if (!base) { reject(new Error("could not locate the Chronicle plugin bundle")); return; }
      const s = document.createElement("script");
      s.src = base + "atlas.js";
      s.async = true;
      s.onload = () => window.__CHRONICLE_ATLAS__ ? resolve(window.__CHRONICLE_ATLAS__) : reject(new Error("atlas.js loaded but registered nothing"));
      s.onerror = () => { atlasPromise = null; reject(new Error("could not load " + s.src)); };
      document.head.appendChild(s);
    });
    return atlasPromise;
  }

  function AtlasTab() {
    const [mod, setMod] = useState(window.__CHRONICLE_ATLAS__ || null);
    const [err, setErr] = useState(null);
    useEffect(() => { if (!mod) loadAtlas().then(setMod).catch((e) => setErr(e.message)); }, []);
    if (err) return h("div", { className: "chr-err" }, "The Atlas could not load: " + err);
    if (!mod) return h("div", { className: "chr-quiet", style: { padding: "2rem" } }, "Loading the Atlas…");
    return h(mod.Atlas, null);
  }

  function ChronicleDashboard() {
    const initial = (() => { try { return sessionStorage.getItem("chr-tab") || "overview"; } catch (e) { return "overview"; } })();
    const [tab, setTab] = useState(initial);
    useEffect(() => { injectCSS(); }, []);
    const choose = (t) => { setTab(t); try { sessionStorage.setItem("chr-tab", t); } catch (e) { /* private mode */ } };
    return h("div", { className: "chr", style: { padding: "1rem", gap: ".75rem" } },
      h("div", { className: "chr-tabs", role: "tablist" },
        h("button", { className: "chr-tab", role: "tab", "aria-selected": tab === "overview", onClick: () => choose("overview") }, "Overview"),
        h("button", { className: "chr-tab", role: "tab", "aria-selected": tab === "atlas", onClick: () => choose("atlas") }, "Atlas")),
      tab === "atlas" ? h(AtlasTab) : h(Overview));
  }

  PLUGINS.register("chronicle", ChronicleDashboard);
}

if (SDK && PLUGINS) main();
else console.error("[chronicle] Hermes plugin SDK not available.");
