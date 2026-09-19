// Shared by dist/index.js and dist/tapestry.js. Everything the plugin needs from the
// dashboard comes through the Hermes plugin SDK; nothing here imports React.

export const SDK = window.__HERMES_PLUGIN_SDK__;
export const PLUGINS = window.__HERMES_PLUGINS__;
export const React = SDK && SDK.React;
export const h = React && React.createElement;
export const hooks = (SDK && SDK.hooks) || {};
export const C = (SDK && SDK.components) || {};
export const fetchJSON = SDK && SDK.fetchJSON;
export const API = "/api/plugins/chronicle";

export const cn = (SDK && SDK.utils && SDK.utils.cn) ||
  function () { return Array.prototype.filter.call(arguments, Boolean).join(" "); };

export function fmt(n) {
  return Number(n || 0).toLocaleString();
}

export function relTime(iso) {
  if (!iso) return "never";
  const t = typeof iso === "number" ? iso * 1000 : new Date(iso).getTime();
  if (!isFinite(t)) return String(iso);
  const m = Math.floor((Date.now() - t) / 60000);
  if (m < 1) return "just now";
  if (m < 60) return m + "m ago";
  const hr = Math.floor(m / 60);
  if (hr < 24) return hr + "h ago";
  return Math.floor(hr / 24) + "d ago";
}

export function when(iso) {
  if (iso == null || iso === "") return "";
  const d = typeof iso === "number" ? new Date(iso * 1000) : new Date(iso);
  if (!isFinite(d.getTime())) return String(iso);
  return d.toLocaleString([], { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" });
}

// One scoped stylesheet for both bundles. Tokens follow the Chronicle skin the
// overview has always used, so the two tabs read as one page.
export function injectCSS() {
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
    "@media(max-width:900px){.chr-grid{grid-template-columns:1fr}.chr-kpis{grid-template-columns:repeat(2,minmax(0,1fr))}}",
  ].join("");
  document.head.appendChild(s);
}
