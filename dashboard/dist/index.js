/**
 * Chronicle Dashboard Plugin — real Hermes dashboard plugin (SDK / React IIFE).
 *
 * Renders live data from:
 *   GET  /api/plugins/chronicle/status  → store{events,facts,episodes,notes,procedures,
 *          entities,pending_jobs}, embeddings{document,note,episode,fact,event,entity →
 *          {total,embedded,pct}}, version, status
 *   GET  /api/plugins/chronicle/recent?limit=12 → events[{id,kind,created_at,source}], count
 *   POST /api/plugins/chronicle/process-embeddings → { ok, enqueued }
 *
 * Theme-native: dashboard tokens (var(--color-*)) + Tailwind classes + SDK components.
 * Principles: grid-first, quiet-by-default, real data only, no fabricated values.
 */
(function () {
  "use strict";

  var SDK = window.__HERMES_PLUGIN_SDK__;
  var PLUGINS = window.__HERMES_PLUGINS__;
  if (!SDK || !PLUGINS) { console.error("[chronicle] Hermes plugin SDK not available."); return; }

  var React = SDK.React;
  var h = React.createElement;
  var useState = SDK.hooks.useState;
  var useEffect = SDK.hooks.useEffect;
  var useCallback = SDK.hooks.useCallback;
  var fetchJSON = SDK.fetchJSON;
  var C = SDK.components;
  var Card = C.Card, CardHeader = C.CardHeader, CardTitle = C.CardTitle, CardContent = C.CardContent;
  var Badge = C.Badge, Button = C.Button;
  var Spinner = C.Spinner || function (p) { return h("span", { className: (p.className || "") + " animate-pulse" }, "…"); };
  var cn = (SDK.utils && SDK.utils.cn) || function () { return Array.prototype.filter.call(arguments, Boolean).join(" "); };

  // --- one-time scoped CSS injection (avoids manifest css dependency / restart) ---
  function injectCSS() {
    if (document.getElementById("chr-css")) return;
    var s = document.createElement("style");
    s.id = "chr-css";
    s.textContent = [
      // Hermes mockup skin, scoped to the plugin root — overriding the shadcn --color-* tokens re-skins SDK components.
      ".chr{--panel:rgba(255,255,255,.025);--panel2:rgba(255,255,255,.05);--bd:rgba(150,130,230,.18);--bd2:rgba(150,130,230,.30);--title:#cdc6f5;--tx:#e7e5f1;--muted:#9b97b8;--accent:#a78bfa;--ok:#4fd6a6;--warn:#f0b54e;--danger:#f0706e;--info:#6aa6f2;--mono:ui-monospace,'SF Mono',Menlo,Consolas,monospace;--color-background:#0a0a14;--color-foreground:#e7e5f1;--color-card:#0e0e1a;--color-card-foreground:#e7e5f1;--color-popover:#12121f;--color-popover-foreground:#e7e5f1;--color-border:rgba(150,130,230,.18);--color-input:rgba(150,130,230,.22);--color-muted:#15151f;--color-muted-foreground:#9b97b8;--color-primary:#a78bfa;--color-primary-foreground:#0a0a14;--color-secondary:#17151f;--color-secondary-foreground:#cdc6f5;--color-accent:#1c1830;--color-accent-foreground:#cdc6f5;--color-destructive:#f0706e;--color-destructive-foreground:#0a0a14;--color-ring:#a78bfa;display:flex;flex-direction:column;gap:1rem;color:var(--tx)}",
      ".chr .text-muted-foreground{color:var(--muted)}",
      ".chr .text-green-500{color:var(--ok)}.chr .text-yellow-500{color:var(--warn)}.chr .text-destructive{color:var(--danger)}",
      ".chr [data-slot=card],.chr .rounded-xl,.chr .rounded-lg{background:var(--panel)!important;border-color:var(--bd)!important;border-radius:11px!important}",
      ".chr [data-slot=card-title]{font-family:var(--mono);font-size:.72rem!important;letter-spacing:.13em;text-transform:uppercase;color:var(--muted)!important;font-weight:500}",
      ".chr-kpi{background:var(--panel);border:1px solid var(--bd);border-radius:11px;padding:14px 15px}",
      ".chr-kpi-l{font-family:var(--mono)}",
      ".chr-kpi-v{color:var(--title)}",
      ".chr-kpis{display:grid;grid-template-columns:repeat(5,minmax(0,1fr));gap:.75rem}",
      ".chr-kpi-l{font-size:.7rem;letter-spacing:.06em;text-transform:uppercase;color:var(--color-muted-foreground);min-height:2.4em;line-height:1.3}",
      ".chr-kpi-v{font-size:1.6rem;font-weight:300;line-height:1;margin-top:.35rem}",
      ".chr-kpi-u{font-size:.8rem;font-weight:400;color:var(--color-muted-foreground);margin-left:.15rem}",
      ".chr-grid{display:grid;grid-template-columns:1fr 1fr;gap:1rem;align-items:start}",
      ".chr-comp{display:flex;align-items:center;gap:1.25rem;flex-wrap:nowrap}",
      ".chr-donut{position:relative;width:140px;height:140px;flex:none}",
      ".chr-donut::before{content:\"\";position:absolute;inset:0;border-radius:50%;background:var(--g);-webkit-mask:radial-gradient(circle farthest-side,#0000 calc(100% - 20px),#000 calc(100% - 20px));mask:radial-gradient(circle farthest-side,#0000 calc(100% - 20px),#000 calc(100% - 20px))}",
      ".chr-donut .ctr{position:absolute;inset:0;display:flex;flex-direction:column;align-items:center;justify-content:center;text-align:center}",
      ".chr-legend{display:flex;flex-direction:column;gap:.4rem;flex:1 1 auto;min-width:0}",
      ".chr-leg-row{display:flex;align-items:center;gap:.5rem;font-size:.8rem}",
      ".chr-sw{width:.6rem;height:.6rem;border-radius:2px;flex:0 0 auto}",
      ".chr-leg-name{flex:1 1 auto;min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}",
      ".chr-leg-ct{font-variant-numeric:tabular-nums}",
      ".chr-leg-pct{color:var(--color-muted-foreground);font-variant-numeric:tabular-nums;width:3.2em;text-align:right}",
      ".chr-cov{display:flex;align-items:center;gap:.6rem;font-size:.8rem;padding:.18rem 0}",
      ".chr-cov-l{flex:0 0 5.5rem}",
      ".chr-track{flex:1 1 auto;height:6px;border-radius:9999px;background:var(--color-border);overflow:hidden}",
      ".chr-fill{display:block;height:100%;border-radius:9999px}",
      ".chr-cov-v{flex:0 0 auto;width:3.2em;text-align:right;font-variant-numeric:tabular-nums}",
      ".chr-act{display:flex;align-items:center;gap:.5rem;font-size:.78rem;padding:.18rem 0}",
      ".chr-mark{width:.5rem;height:.5rem;border-radius:9999px;flex:0 0 auto;background:var(--color-muted-foreground)}",
      ".chr-act-sum{flex:1 1 auto;min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}",
      ".chr-act-src{flex:0 0 auto;font-size:.72rem;max-width:8rem;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}",
      ".chr-act-time{flex:0 0 auto;white-space:nowrap;font-size:.72rem}",
      ".chr-chip{display:inline-flex;align-items:center;gap:.15rem;background:rgba(255,255,255,.08);border-radius:9999px;padding:.08rem .45rem;font-size:.68rem;font-variant-numeric:tabular-nums;line-height:1.4;color:var(--muted);flex:0 0 auto}",
      "@media(max-width:900px){.chr-grid{grid-template-columns:1fr}.chr-kpis{grid-template-columns:repeat(2,minmax(0,1fr))}}",
      "@media(max-width:520px){.chr-kpis{grid-template-columns:1fr}}",
    ].join("");
    document.head.appendChild(s);
  }

  function relTime(iso) {
    if (!iso) return "never";
    try {
      var diff = Date.now() - new Date(iso).getTime();
      var m = Math.floor(diff / 60000);
      if (m < 1) return "just now";
      if (m < 60) return m + "m ago";
      var hr = Math.floor(m / 60);
      if (hr < 24) return hr + "h ago";
      return Math.floor(hr / 24) + "d ago";
    } catch (e) { return iso; }
  }
  function clockTime(iso) {
    if (!iso) return "";
    try { return new Date(iso).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" }); }
    catch (e) { return ""; }
  }
  function fmt(n) { return Number(n || 0).toLocaleString(); }

  // Braun palette: Events=blue, Notes=lilac, Episodes=gold, Facts=orange, Docs=green, Entities=purple
  var SEG_COLORS = ["#3b82f6", "#ab47bc", "#f9a825", "#f57c00", "#43a047", "#9b59b6"];

  // Shared type -> color map (matches SEG_COLORS order: Events, Notes, Episodes, Facts, Documents, Entities).
  // Used by both the Memory composition donut and the Embedding coverage bars so the widgets stay consistent.
  var KIND_COLORS = {
    event: SEG_COLORS[0], note: SEG_COLORS[1], episode: SEG_COLORS[2],
    fact: SEG_COLORS[3], document: SEG_COLORS[4], entity: SEG_COLORS[5]
  };

  // --- KPI tile ---
  function Kpi(label, value, unit) {
    return h("div", { className: "chr-kpi" },
      h("div", { className: "chr-kpi-l" }, label),
      h("div", { className: "chr-kpi-v" },
        value,
        unit ? h("span", { className: "chr-kpi-u" }, unit) : null
      )
    );
  }

  // --- Memory composition: donut + legend ---
  function CompositionCard(store) {
    // content types by count (declared order matches SEG_COLORS)
    // Colour is bound to the KIND, not to array position, so ranking by count
    // cannot reassign colours. The coverage card reads the same KIND_COLORS map
    // and ranks by these same counts, keeping the two widgets in step.
    var segs = [
      { name: "Events", kind: "event", count: store.events || 0 },
      { name: "Notes", kind: "note", count: store.notes || 0 },
      { name: "Episodes", kind: "episode", count: store.episodes || 0 },
      { name: "Facts", kind: "fact", count: store.facts || 0 },
      { name: "Documents", kind: "document", count: store.documents || 0 },
      { name: "Entities", kind: "entity", count: store.entities || 0 },
    ].map(function (s) { s.color = KIND_COLORS[s.kind]; return s; })
     .sort(function (a, b) { return b.count - a.count; });

    var total = segs.reduce(function (a, s) { return a + s.count; }, 0);

    // build conic-gradient stops from cumulative percentages
    var stops = [];
    if (total > 0) {
      var acc = 0;
      for (var i = 0; i < segs.length; i++) {
        if (!segs[i].count) continue;
        var start = (acc / total) * 100;
        acc += segs[i].count;
        var end = (acc / total) * 100;
        stops.push(segs[i].color + " " + start.toFixed(2) + "% " + end.toFixed(2) + "%");
      }
    }
    var gradient = total > 0
      ? "conic-gradient(" + stops.join(", ") + ")"
      : "conic-gradient(var(--color-border) 0 100%)";

    var donut = h("div", { className: "chr-donut", style: { "--g": gradient } },
      h("div", { className: "ctr" },
        h("span", { className: "text-xl font-light tabular-nums leading-none" }, fmt(total)),
        h("span", { className: "text-xs text-muted-foreground" }, "items")
      )
    );

    var legend = h("div", { className: "chr-legend" },
      segs.map(function (s, i) {
        var pct = total > 0 ? Math.round((s.count / total) * 100) : 0;
        return h("div", { key: i, className: "chr-leg-row" },
          h("span", { className: "chr-sw", style: { background: s.color } }),
          h("span", { className: "chr-leg-name" }, s.name),
          h("span", { className: "chr-leg-ct" }, fmt(s.count)),
          h("span", { className: "chr-leg-pct" }, pct + "%")
        );
      })
    );

    return h(Card, null,
      h(CardHeader, { className: "pb-2" }, h(CardTitle, { className: "text-sm" }, "Memory composition")),
      h(CardContent, null,
        h("div", { className: "chr-comp" }, donut, legend)
      )
    );
  }

  // --- Embedding coverage by type ---
  function CoverageCard(emb, store) {
    store = store || {};
    var rank = { event: store.events || 0, note: store.notes || 0,
                 episode: store.episodes || 0, fact: store.facts || 0,
                 document: store.documents || 0, entity: store.entities || 0 };
    var order = ["event", "note", "episode", "fact", "document", "entity"];
    var labels = { event: "Events", note: "Notes", episode: "Episodes", fact: "Facts", document: "Documents", entity: "Entities" };
    // match the Memory composition donut palette (KIND_COLORS order: Events, Notes, Episodes, Facts, Documents, Entities)
    var kindColors = KIND_COLORS;
    var hasEntities = false;
    var rows = order
      .map(function (k) { var e = emb[k] || {}; var isEntity = (k === "entity"); if (isEntity) hasEntities = true; return { kind: k, total: e.total || 0, embedded: e.embedded || 0, pct: e.pct || 0, isEntity: isEntity }; })
      .filter(function (r) { return r.total > 0 || r.isEntity; })
      // rank by the composition counts so both lists read in the same order
      .sort(function (a, b) { return (rank[b.kind] || 0) - (rank[a.kind] || 0); });

    return h(Card, null,
      h(CardHeader, { className: "pb-2" }, h(CardTitle, { className: "text-sm" }, "Embedding coverage by type")),
      h(CardContent, null,
        rows.length === 0
          ? h("span", { className: "text-xs text-muted-foreground" }, "No embeddable items yet.")
          : h("div", { className: "flex flex-col" }, rows.map(function (r, i) {
              if (r.isEntity) {
                // Entities are not embedded — show N/A bar per Braun spec
                return h("div", { key: i, className: "chr-cov" },
                  h("span", { className: "chr-cov-l text-muted-foreground" }, labels[r.kind] || r.kind),
                  h("span", { className: "chr-track" },
                    h("span", { className: "chr-fill", style: { width: "0%", background: kindColors.entity, opacity: 0.5 } })
                  ),
                  h("span", { className: "chr-cov-v", style: { color: kindColors.entity } }, "0%")
                );
              }
              var full = r.pct >= 100;
              var deficit = r.total - r.embedded;
              var fillColor = kindColors[r.kind] || SEG_COLORS[0];
              return h("div", { key: i, className: "chr-cov" },
                h("span", { className: "chr-cov-l text-muted-foreground" }, labels[r.kind] || r.kind),
                h("span", { className: "chr-track" },
                  h("span", { className: "chr-fill", style: { width: Math.max(0, Math.min(100, r.pct)) + "%", background: fillColor } })
                ),
                full
                  ? h("span", { className: "chr-cov-v" }, r.pct + "%")
                  : h("span", { className: "chr-cov-v", style: { color: "var(--color-warning,#f0b54e)" } }, fmt(r.pct) + "%")
              );
            }))
      )
    );
  }

  // --- Recent activity ---
  function ActivityCard(events) {
    return h(Card, null,
      h(CardHeader, { className: "pb-2" }, h(CardTitle, { className: "text-sm" }, "Recent activity")),
      h(CardContent, null,
        (!events || events.length === 0)
          ? h("span", { className: "text-xs text-muted-foreground" }, "No recent events.")
          : h("div", { className: "flex flex-col" }, events.map(function (e, i) {
              var kind = e.kind || "event";
              var markColor = KIND_COLORS[kind] || "var(--color-border)";
              var verb = e.verb || (kind.charAt(0).toUpperCase() + kind.slice(1));
              var summary = e.summary || "";
              return h("div", { key: e.id != null ? e.id : i, className: "chr-act" },
                h("span", { className: "chr-mark", style: { background: markColor } }),
                h(Badge, { tone: "outline" }, verb),
                h("span", { className: "chr-act-sum" }, summary || kind),
                e.domain ? h("span", { className: "chr-chip" }, "domain: " + e.domain.substring(0, 14)) : null,
                e.confidence != null ? h("span", { className: "chr-chip" }, "conf: " + e.confidence) : null,
                e.source ? h("span", { className: "text-muted-foreground chr-act-src" }, e.source) : null,
                h("span", { className: "text-muted-foreground ml-auto chr-act-time" }, relTime(e.created_at))
              );
            }))
      )
    );
  }

  function ChronicleDashboard() {
    var st = useState(null), data = st[0], setData = st[1];
    var rs = useState(null), recent = rs[0], setRecent = rs[1];
    var ls = useState(true), loading = ls[0], setLoading = ls[1];
    var es = useState(null), err = es[0], setErr = es[1];
    var bs = useState(false), busy = bs[0], setBusy = bs[1];

    var load = useCallback(function () {
      Promise.all([
        fetchJSON("/api/plugins/chronicle/status"),
        fetchJSON("/api/plugins/chronicle/recent?limit=12").catch(function () { return null; })
      ]).then(function (res) {
        setData(res[0]);
        if (res[1]) setRecent(res[1]);
        setErr(null);
        setLoading(false);
      }).catch(function (e) {
        setErr((e && e.message) || "Failed to load");
        setLoading(false);
      });
    }, []);

    useEffect(function () { injectCSS(); load(); var iv = setInterval(load, 60000); return function () { clearInterval(iv); }; }, [load]);

    var process = useCallback(function () {
      setBusy(true);
      fetchJSON("/api/plugins/chronicle/process-embeddings", { method: "POST" })
        .then(function () { setTimeout(function () { load(); setBusy(false); }, 1200); })
        .catch(function (e) { setErr("Process failed: " + ((e && e.message) || "error")); setBusy(false); });
    }, [load]);

    if (loading && !data) {
      return h("div", { className: "flex items-center gap-2 p-8 text-sm text-muted-foreground" },
        h(Spinner, { className: "h-4 w-4" }), "Loading Chronicle…");
    }
    if (err && !data) {
      return h("div", { className: "p-4 text-sm text-destructive", role: "alert" },
        "Error: " + err, h(Button, { size: "sm", variant: "outline", className: "ml-2", onClick: load }, "Retry"));
    }
    if (!data) return null;

    var store = data.store || {};
    var emb = data.embeddings || {};

    // Total items = sum of content-type counts
    var totalItems = (store.events || 0) + (store.facts || 0) + (store.episodes || 0)
      + (store.notes || 0) + (store.entities || 0) + (store.documents || 0);

    // Overall embedded % across embedding kinds
    var sumEmbedded = 0, sumTotal = 0;
    // entity omitted: never embedded (rendered N/A), so it must not sit in the
    // denominator of the headline percentage.
    var embKinds = ["document", "note", "episode", "fact", "event"];
    for (var i = 0; i < embKinds.length; i++) {
      var e = emb[embKinds[i]] || {};
      sumEmbedded += e.embedded || 0;
      sumTotal += e.total || 0;
    }
    var overallPct = sumTotal > 0 ? Math.round((100 * sumEmbedded) / sumTotal) : 0;

    var kpis = h("div", { key: "kpis", className: "chr-kpis" },
      Kpi("Total items", fmt(totalItems)),
      Kpi("Embedded", overallPct, "%"),
      Kpi("Pending jobs", fmt(store.pending_jobs)),
      Kpi("Facts", fmt(store.facts)),
      Kpi("Episodes", fmt(store.episodes))
    );

    var pending = store.pending_jobs || 0;
    var queueCard = pending > 0
      ? h(Card, null,
          h(CardHeader, { className: "pb-2" }, h(CardTitle, { className: "text-sm" }, "Embedding queue · " + fmt(pending) + " items")),
          h(CardContent, null,
            h("div", { className: "flex items-center justify-between gap-3 flex-wrap" },
              h("span", { className: "text-xs text-muted-foreground" }, "Unembedded items waiting for the next curation pass."),
              h(Button, { size: "sm", variant: "outline", disabled: busy, onClick: process },
                busy ? "Queueing…" : "Queue up to 500 more")
            )
          )
        )
      : null;

    return h("div", { className: "chr p-4" },
      kpis,
      h("div", { className: "chr-grid" }, CompositionCard(store), CoverageCard(emb, store)),
      queueCard,
      ActivityCard(recent && recent.events)
    );
  }

  PLUGINS.register("chronicle", ChronicleDashboard);
})();
