(() => {
  // src/common.js
  var SDK = window.__HERMES_PLUGIN_SDK__;
  var PLUGINS = window.__HERMES_PLUGINS__;
  var React = SDK && SDK.React;
  var h = React && React.createElement;
  var hooks = SDK && SDK.hooks || {};
  var C = SDK && SDK.components || {};
  var fetchJSON = SDK && SDK.fetchJSON;
  var API = "/api/plugins/chronicle";
  var cn = SDK && SDK.utils && SDK.utils.cn || function() {
    return Array.prototype.filter.call(arguments, Boolean).join(" ");
  };
  function fmt(n) {
    return Number(n || 0).toLocaleString();
  }
  function relTime(iso) {
    if (!iso) return "never";
    const t = typeof iso === "number" ? iso * 1e3 : new Date(iso).getTime();
    if (!isFinite(t)) return String(iso);
    const m = Math.floor((Date.now() - t) / 6e4);
    if (m < 1) return "just now";
    if (m < 60) return m + "m ago";
    const hr = Math.floor(m / 60);
    if (hr < 24) return hr + "h ago";
    return Math.floor(hr / 24) + "d ago";
  }
  function injectCSS() {
    if (document.getElementById("chr-css")) return;
    const s = document.createElement("style");
    s.id = "chr-css";
    s.textContent = [
      ".chr{--panel:rgba(255,255,255,.025);--panel2:rgba(255,255,255,.05);--bd:rgba(150,130,230,.18);--bd2:rgba(150,130,230,.30);--title:#cdc6f5;--tx:#e7e5f1;--muted:#9b97b8;--accent:#a78bfa;--ok:#4fd6a6;--warn:#f0b54e;--danger:#f0706e;--info:#6aa6f2;--mono:ui-monospace,'SF Mono',Menlo,Consolas,monospace;--color-background:#0a0a14;--color-foreground:#e7e5f1;--color-card:#0e0e1a;--color-card-foreground:#e7e5f1;--color-popover:#12121f;--color-popover-foreground:#e7e5f1;--color-border:rgba(150,130,230,.18);--color-input:rgba(150,130,230,.22);--color-muted:#15151f;--color-muted-foreground:#9b97b8;--color-primary:#a78bfa;--color-primary-foreground:#0a0a14;--color-secondary:#17151f;--color-secondary-foreground:#cdc6f5;--color-accent:#1c1830;--color-accent-foreground:#cdc6f5;--color-destructive:#f0706e;--color-destructive-foreground:#0a0a14;--color-ring:#a78bfa;display:flex;flex-direction:column;gap:1rem;color:var(--tx)}",
      ".chr .text-muted-foreground{color:var(--muted)}",
      ".chr-tabs{display:flex;gap:.25rem;border-bottom:1px solid var(--bd);padding:0 .25rem}",
      ".chr-tab{background:none;border:0;border-bottom:2px solid transparent;color:var(--muted);padding:.45rem .75rem;font-size:.85rem;cursor:pointer}",
      ".chr-tab[aria-selected=true]{color:var(--tx);border-bottom-color:var(--accent)}",
      ".chr-kpis{display:grid;grid-template-columns:repeat(5,minmax(0,1fr));gap:.75rem}",
      ".chr-kpi{border:1px solid var(--bd);border-radius:.6rem;background:var(--panel);padding:.7rem .85rem}",
      ".chr-kpi-l{font-size:.72rem;color:var(--muted)}",
      ".chr-kpi-v{font-size:1.35rem;font-weight:300;font-variant-numeric:tabular-nums}",
      ".chr-kpi-u{font-size:.8rem;color:var(--muted);margin-left:.15rem}",
      ".chr-grid{display:grid;grid-template-columns:1fr 1fr;gap:1rem}",
      ".chr-comp{display:flex;align-items:center;gap:1.25rem}",
      ".chr-donut{width:7rem;height:7rem;border-radius:9999px;background:var(--g);display:grid;place-items:center;flex:0 0 auto}",
      ".chr-donut .ctr{width:4.8rem;height:4.8rem;border-radius:9999px;background:var(--color-card);display:flex;flex-direction:column;align-items:center;justify-content:center}",
      ".chr-legend{flex:1 1 auto;min-width:0}",
      ".chr-leg-row{display:flex;align-items:center;gap:.6rem;font-size:.8rem;padding:.18rem 0}",
      ".chr-sw{width:.6rem;height:.6rem;border-radius:2px;flex:0 0 auto}",
      ".chr-leg-name{flex:1 1 auto;min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}",
      ".chr-leg-ct,.chr-num{font-variant-numeric:tabular-nums}",
      ".chr-leg-pct{color:var(--muted);font-variant-numeric:tabular-nums;width:3.2em;text-align:right}",
      ".chr-cov{display:flex;align-items:center;gap:.6rem;font-size:.8rem;padding:.18rem 0}",
      ".chr-cov-l{flex:0 0 5.5rem}",
      ".chr-track{flex:1 1 auto;height:6px;border-radius:9999px;background:var(--bd);overflow:hidden}",
      ".chr-fill{display:block;height:100%;border-radius:9999px}",
      ".chr-cov-v{flex:0 0 auto;width:3.2em;text-align:right;font-variant-numeric:tabular-nums;color:var(--muted)}",
      ".chr-act{display:flex;align-items:center;gap:.5rem;font-size:.78rem;padding:.18rem 0}",
      ".chr-mark{width:.5rem;height:.5rem;border-radius:9999px;flex:0 0 auto}",
      ".chr-act-sum{flex:1 1 auto;min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}",
      ".chr-act-time{flex:0 0 auto;white-space:nowrap;font-size:.72rem;color:var(--muted)}",
      ".chr-err{padding:1rem;font-size:.85rem;color:var(--danger)}",
      ".chr-quiet{font-size:.8rem;color:var(--muted)}",
      "@media(max-width:900px){.chr-grid{grid-template-columns:1fr}.chr-kpis{grid-template-columns:repeat(2,minmax(0,1fr))}}"
    ].join("");
    document.head.appendChild(s);
  }

  // src/index.js
  function main() {
    const { useState, useEffect, useCallback } = hooks;
    const { Card, CardHeader, CardTitle, CardContent, Badge, Button } = C;
    const KIND_COLORS = { event: "#3b82f6", note: "#ab47bc", episode: "#f9a825", fact: "#f57c00", document: "#43a047", entity: "#9b59b6" };
    const LABELS = { event: "Events", note: "Notes", episode: "Episodes", fact: "Facts", document: "Documents", entity: "Entities" };
    function Kpi(label, value, unit) {
      return h(
        "div",
        { className: "chr-kpi" },
        h("div", { className: "chr-kpi-l" }, label),
        h("div", { className: "chr-kpi-v" }, value, unit ? h("span", { className: "chr-kpi-u" }, unit) : null)
      );
    }
    function CompositionCard(store) {
      const segs = ["event", "note", "episode", "fact", "document", "entity"].map((k) => ({ kind: k, name: LABELS[k], count: store[k + "s"] || 0, color: KIND_COLORS[k] })).filter((s) => s.count > 0).sort((a, b) => b.count - a.count);
      const total = segs.reduce((a, s) => a + s.count, 0);
      let acc = 0;
      const stops = segs.map((s) => {
        const a = acc / total * 100;
        acc += s.count;
        return s.color + " " + a.toFixed(2) + "% " + (acc / total * 100).toFixed(2) + "%";
      });
      const gradient = total > 0 ? "conic-gradient(" + stops.join(", ") + ")" : "conic-gradient(var(--bd) 0 100%)";
      return h(
        Card,
        null,
        h(CardHeader, { className: "pb-2" }, h(CardTitle, { className: "text-sm" }, "Memory composition")),
        h(
          CardContent,
          null,
          h(
            "div",
            { className: "chr-comp" },
            h(
              "div",
              { className: "chr-donut", style: { "--g": gradient } },
              h(
                "div",
                { className: "ctr" },
                h("span", { className: "text-xl font-light chr-num" }, fmt(total)),
                h("span", { className: "text-xs text-muted-foreground" }, "items")
              )
            ),
            h("div", { className: "chr-legend" }, segs.map((s) => h(
              "div",
              { key: s.kind, className: "chr-leg-row" },
              h("span", { className: "chr-sw", style: { background: s.color } }),
              h("span", { className: "chr-leg-name" }, s.name),
              h("span", { className: "chr-leg-ct" }, fmt(s.count)),
              h("span", { className: "chr-leg-pct" }, (total ? Math.round(s.count / total * 100) : 0) + "%")
            )))
          )
        )
      );
    }
    function CoverageCard(emb, store) {
      const rows = ["event", "note", "episode", "fact", "document"].map((k) => ({ kind: k, ...emb[k] || {} })).filter((r) => (r.total || 0) > 0).sort((a, b) => (store[b.kind + "s"] || 0) - (store[a.kind + "s"] || 0));
      return h(
        Card,
        null,
        h(CardHeader, { className: "pb-2" }, h(CardTitle, { className: "text-sm" }, "Embedding coverage by type")),
        h(CardContent, null, rows.length === 0 ? h("span", { className: "chr-quiet" }, "No embeddable items yet.") : rows.map((r) => h(
          "div",
          { key: r.kind, className: "chr-cov" },
          h("span", { className: "chr-cov-l" }, LABELS[r.kind]),
          h(
            "span",
            { className: "chr-track" },
            h("span", { className: "chr-fill", style: { width: Math.max(0, Math.min(100, r.pct || 0)) + "%", background: KIND_COLORS[r.kind] } })
          ),
          h("span", { className: "chr-cov-v", style: (r.pct || 0) >= 100 ? null : { color: "var(--warn)" } }, fmt(r.pct || 0) + "%")
        )))
      );
    }
    function ActivityCard(events) {
      return h(
        Card,
        null,
        h(CardHeader, { className: "pb-2" }, h(CardTitle, { className: "text-sm" }, "Recent activity")),
        h(CardContent, null, !events || events.length === 0 ? h("span", { className: "chr-quiet" }, "No recent events.") : h("div", null, events.map((e, i) => h(
          "div",
          { key: e.id || i, className: "chr-act" },
          h("span", { className: "chr-mark", style: { background: KIND_COLORS[e.kind] || "var(--muted)" } }),
          h(Badge, { tone: "outline" }, e.verb || e.kind),
          h("span", { className: "chr-act-sum" }, e.summary || e.kind),
          e.source ? h("span", { className: "chr-act-time" }, e.source) : null,
          h("span", { className: "chr-act-time" }, relTime(e.created_at))
        ))))
      );
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
          fetchJSON(API + "/recent?limit=12").catch(() => null)
        ]).then(([s, r]) => {
          setData(s);
          setRecent(r);
          setErr(null);
        }).catch((e) => setErr(e && e.message || "Failed to load"));
      }, []);
      useEffect(() => {
        load();
        const iv = setInterval(load, 6e4);
        return () => clearInterval(iv);
      }, [load]);
      const enqueue = useCallback(() => {
        setBusy(true);
        fetchJSON(API + "/enqueue-extractions?limit=500", { method: "POST" }).then((r) => {
          setNote(r && r.ok ? "Queued " + fmt(r.enqueued) + " extractions." : "Nothing queued: " + (r && r.error || "unknown error"));
          load();
        }).catch((e) => setNote("Queueing failed: " + (e && e.message || "error"))).finally(() => setBusy(false));
      }, [load]);
      if (err && !data) {
        return h(
          "div",
          { className: "chr-err", role: "alert" },
          "Could not load Chronicle: " + err + " ",
          h(Button, { size: "sm", variant: "outline", onClick: load }, "Retry")
        );
      }
      if (!data) return h("div", { className: "chr-quiet", style: { padding: "2rem" } }, "Loading Chronicle\u2026");
      if (data.status === "no_db") return h("div", { className: "chr-quiet", style: { padding: "2rem" } }, "No Chronicle database found.");
      const store = data.store || {};
      const emb = data.embeddings || {};
      let sumE = 0, sumT = 0;
      for (const k of ["event", "session", "episode", "note", "fact", "reference", "procedure", "projection", "document"]) {
        sumE += (emb[k] || {}).embedded || 0;
        sumT += (emb[k] || {}).total || 0;
      }
      const candidates = store.enqueue_candidates || 0;
      return h(
        "div",
        { className: "chr", style: { gap: "1rem" } },
        h(
          "div",
          { className: "chr-kpis" },
          Kpi("Events", fmt(store.events)),
          Kpi("Embedded", sumT ? Math.round(100 * sumE / sumT) : 0, "%"),
          Kpi("Pending jobs", fmt(store.pending_jobs)),
          Kpi("Facts", fmt(store.facts)),
          Kpi("Episodes", fmt(store.episodes))
        ),
        h("div", { className: "chr-grid" }, CompositionCard(store), CoverageCard(emb, store)),
        candidates > 0 ? h(
          Card,
          null,
          h(CardHeader, { className: "pb-2" }, h(CardTitle, { className: "text-sm" }, fmt(candidates) + " turns not yet extracted")),
          h(
            CardContent,
            null,
            h(
              "div",
              { className: "chr-act" },
              h(Button, { size: "sm", variant: "outline", disabled: busy, onClick: enqueue }, busy ? "Queueing\u2026" : "Queue up to 500 extractions"),
              note ? h("span", { className: "chr-quiet" }, note) : null
            )
          )
        ) : null,
        ActivityCard(recent && recent.events)
      );
    }
    let atlasPromise = null;
    function loadAtlas() {
      if (window.__CHRONICLE_ATLAS__) return Promise.resolve(window.__CHRONICLE_ATLAS__);
      if (atlasPromise) return atlasPromise;
      atlasPromise = new Promise((resolve, reject) => {
        const self = document.querySelector('script[data-hermes-plugin="chronicle"]');
        const src = self && self.src ? self.src.split("?")[0] : "";
        const base = src ? src.slice(0, src.lastIndexOf("/") + 1) : "";
        if (!base) {
          reject(new Error("could not locate the Chronicle plugin bundle"));
          return;
        }
        const s = document.createElement("script");
        s.src = base + "atlas.js";
        s.async = true;
        s.onload = () => window.__CHRONICLE_ATLAS__ ? resolve(window.__CHRONICLE_ATLAS__) : reject(new Error("atlas.js loaded but registered nothing"));
        s.onerror = () => {
          atlasPromise = null;
          reject(new Error("could not load " + s.src));
        };
        document.head.appendChild(s);
      });
      return atlasPromise;
    }
    function AtlasTab() {
      const [mod, setMod] = useState(window.__CHRONICLE_ATLAS__ || null);
      const [err, setErr] = useState(null);
      useEffect(() => {
        if (!mod) loadAtlas().then(setMod).catch((e) => setErr(e.message));
      }, []);
      if (err) return h("div", { className: "chr-err" }, "The Atlas could not load: " + err);
      if (!mod) return h("div", { className: "chr-quiet", style: { padding: "2rem" } }, "Loading the Atlas\u2026");
      return h(mod.Atlas, null);
    }
    function ChronicleDashboard() {
      const initial = (() => {
        try {
          return sessionStorage.getItem("chr-tab") || "overview";
        } catch (e) {
          return "overview";
        }
      })();
      const [tab, setTab] = useState(initial);
      useEffect(() => {
        injectCSS();
      }, []);
      const choose = (t) => {
        setTab(t);
        try {
          sessionStorage.setItem("chr-tab", t);
        } catch (e) {
        }
      };
      return h(
        "div",
        { className: "chr", style: { padding: "1rem", gap: ".75rem" } },
        h(
          "div",
          { className: "chr-tabs", role: "tablist" },
          h("button", { className: "chr-tab", role: "tab", "aria-selected": tab === "overview", onClick: () => choose("overview") }, "Overview"),
          h("button", { className: "chr-tab", role: "tab", "aria-selected": tab === "atlas", onClick: () => choose("atlas") }, "Atlas")
        ),
        tab === "atlas" ? h(AtlasTab) : h(Overview)
      );
    }
    PLUGINS.register("chronicle", ChronicleDashboard);
  }
  if (SDK && PLUGINS) main();
  else console.error("[chronicle] Hermes plugin SDK not available.");
})();
