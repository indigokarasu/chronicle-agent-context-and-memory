// dist/atlas.js — the Atlas memory navigator. Loaded by dist/index.js when the
// Atlas tab first opens; registers window.__CHRONICLE_ATLAS__ = { Atlas }.

import { h, hooks, fetchJSON, API, fmt, relTime, injectCSS } from "../common.js";
import { EventModel, loadEvents, pollEvents, typeStyle } from "./data.js";
import { createCanvas } from "./canvas.js";
import { Inspector, Lenses } from "./panels.js";

const { useState, useEffect, useRef, useCallback } = hooks;
const POLL_MS = 10000;
const SUMMARY_MS = 60000;

function injectAtlasCSS() {
  injectCSS();
  if (document.getElementById("atl-css")) return;
  const s = document.createElement("style");
  s.id = "atl-css";
  s.textContent = [
    ".atl{display:flex;flex-direction:column;gap:.75rem}",
    ".atl-stats{display:flex;flex-wrap:wrap;align-items:baseline;gap:.35rem 1.1rem;font-size:.8rem;color:var(--muted)}",
    ".atl-stats b{color:var(--tx);font-weight:500;font-variant-numeric:tabular-nums}",
    ".atl-live{margin-left:auto;display:flex;align-items:center;gap:.4rem}",
    ".atl-dot{width:.45rem;height:.45rem;border-radius:9999px;background:var(--ok)}",
    ".atl-dot.is-off{background:var(--muted)}",
    ".atl-body{display:grid;grid-template-columns:minmax(0,1fr) 370px;gap:.75rem;align-items:start}",
    ".atl-main{display:flex;flex-direction:column;gap:.6rem;min-width:0}",
    ".atl-canvas{position:relative;height:560px;border:1px solid var(--bd);border-radius:.6rem;background:var(--panel);overflow:hidden}",
    ".atl-canvas-root,.atl-deck{position:absolute;inset:0}",
    ".atl-labels{position:absolute;left:0;bottom:0;overflow:hidden;border-right:1px solid var(--bd);pointer-events:auto}",
    ".atl-label{position:absolute;left:0;right:0;transform:translateY(-50%);display:flex;gap:.4rem;align-items:center;padding:0 .55rem;font-size:.7rem;line-height:1;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;cursor:pointer;color:var(--tx)}",
    ".atl-label span{margin-left:auto;color:var(--muted);font-variant-numeric:tabular-nums;font-size:.64rem}",
    ".atl-label:hover,.atl-label.is-sel{color:var(--accent)}",
    ".atl-axis{position:absolute;right:0;border-top:1px solid var(--bd);border-bottom:1px solid var(--bd);pointer-events:none}",
    ".atl-tick{position:absolute;top:4px;transform:translateX(-50%);font-size:.66rem;color:var(--muted);white-space:nowrap}",
    ".atl-bar{position:absolute;top:.35rem;right:.6rem;display:flex;gap:.7rem;align-items:center;font-size:.7rem;color:var(--muted);pointer-events:auto;background:rgba(10,10,20,.6);border-radius:.3rem;padding:.1rem .4rem;z-index:2}",
    ".atl-actlabel{position:absolute;left:0;top:0;display:flex;align-items:flex-end;padding:.5rem .55rem;font-size:.7rem;color:var(--muted);border-right:1px solid var(--bd);pointer-events:none}",
    ".atl-tip{background:#12121f;border:1px solid var(--bd2);border-radius:.4rem;padding:.35rem .5rem;font-size:.72rem;color:#e7e5f1;line-height:1.35}",
    ".atl-tip span{color:#9b97b8}",
    ".atl-legend{display:flex;flex-wrap:wrap;gap:.3rem .9rem;font-size:.72rem;color:var(--muted)}",
    ".atl-legend i{display:inline-block;width:.55rem;height:.55rem;border-radius:9999px;margin-right:.3rem;vertical-align:-1px}",
    ".atl-progress{position:absolute;inset:auto 0 0 0;padding:.4rem .7rem;font-size:.72rem;color:var(--muted);background:linear-gradient(transparent,rgba(10,10,20,.85))}",
    ".atl-side{border:1px solid var(--bd);border-radius:.6rem;background:var(--panel);max-height:calc(560px + 18rem);overflow:auto;padding:.7rem .8rem;position:sticky;top:.5rem}",
    ".atl-pad{padding:.5rem .2rem}.atl-pad-s{padding:.35rem 0 .5rem}",
    ".atl-pad p{margin:0 0 .6rem;font-size:.8rem;line-height:1.45}",
    ".atl-head{display:flex;flex-wrap:wrap;align-items:center;gap:.4rem;font-size:.9rem;margin-bottom:.45rem}",
    ".atl-text{font-size:.82rem;line-height:1.45;white-space:pre-wrap;word-break:break-word;background:var(--panel2);border-radius:.4rem;padding:.5rem .6rem;margin:.4rem 0}",
    ".atl-links{display:flex;flex-wrap:wrap;gap:.4rem;margin:.3rem 0}",
    ".atl-link,.atl-inline{background:none;border:0;padding:0;color:var(--accent);font-size:.76rem;cursor:pointer;text-decoration:underline;text-underline-offset:2px}",
    ".atl-facts{display:flex;flex-wrap:wrap;gap:.25rem .8rem;font-size:.74rem;color:var(--muted);margin:.3rem 0}",
    ".atl-warn{color:var(--warn)}",
    ".atl-chips{display:flex;flex-wrap:wrap;gap:.3rem;margin:.4rem 0}",
    ".atl-chip{font-size:.68rem;background:var(--panel2);border-radius:9999px;padding:.1rem .45rem;font-variant-numeric:tabular-nums}",
    ".atl-sec{margin-top:.75rem}",
    ".atl-sec-t{font-size:.72rem;text-transform:uppercase;letter-spacing:.04em;color:var(--muted);margin-bottom:.3rem}",
    ".atl-row{display:grid;grid-template-columns:1fr auto;gap:.1rem .5rem;width:100%;text-align:left;background:none;border:0;border-top:1px solid var(--bd);padding:.4rem .15rem;color:var(--tx);cursor:pointer}",
    ".atl-row:hover{background:var(--panel2)}",
    ".atl-row-k{grid-column:1/2;font-size:.68rem;color:var(--muted);white-space:nowrap;overflow:hidden;text-overflow:ellipsis}",
    ".atl-row-m{grid-column:2/3;grid-row:1/2;font-size:.68rem;color:var(--muted);white-space:nowrap;text-align:right}",
    ".atl-row-x{grid-column:1/3;font-size:.78rem;line-height:1.35;display:-webkit-box;-webkit-line-clamp:3;-webkit-box-orient:vertical;overflow:hidden}",
    ".atl-sub{font-size:.7rem;padding:0 .15rem .3rem}",
    ".atl-lenses{border:1px solid var(--bd);border-radius:.6rem;background:var(--panel);padding:.2rem .7rem .7rem}",
    ".atl-lens{max-height:22rem;overflow:auto}",
    ".atl-pair{display:grid;grid-template-columns:1fr auto 1fr;gap:.5rem;align-items:start;border-top:1px solid var(--bd);padding:.25rem 0}",
    ".atl-pair .atl-row{border-top:0}",
    ".atl-vs{font-size:.66rem;color:var(--danger);padding-top:.55rem}",
    ".atl-hist{display:grid;grid-template-columns:14rem 1fr;gap:.2rem .7rem;align-items:center;border-top:1px solid var(--bd);padding:.4rem 0}",
    ".atl-hist-l{font-size:.74rem;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}",
    ".atl-hist-bar{position:relative;height:.7rem;background:var(--panel2);border-radius:3px}",
    ".atl-seg{position:absolute;top:0;bottom:0;border:0;padding:0;border-radius:2px;cursor:pointer;background:var(--muted);opacity:.55}",
    ".atl-seg-active{background:var(--ok);opacity:1}.atl-seg-draft{background:var(--warn);opacity:.9}",
    ".atl-seg:hover{outline:1px solid #fff}",
    ".atl-hist-v{grid-column:2/3;font-size:.7rem;color:var(--muted);white-space:nowrap;overflow:hidden;text-overflow:ellipsis}",
    ".atl-dup{grid-template-columns:3.2rem 6rem 1fr auto}",
    ".atl-dup .atl-row-x{grid-column:3/4;-webkit-line-clamp:1}",
    ".atl-dup .atl-row-m{grid-column:4/5}",
    ".atl-dup-n{font-size:.78rem;align-self:center}",
    ".atl-dup-bar{align-self:center;height:.35rem;background:var(--panel2);border-radius:9999px;overflow:hidden}",
    ".atl-dup-bar span{display:block;height:100%;background:var(--warn)}",
    "@media(max-width:1100px){.atl-body{grid-template-columns:1fr}.atl-side{position:static;max-height:none}}",
  ].join("");
  document.head.appendChild(s);
}

function Atlas() {
  const hostRef = useRef(null);
  const modelRef = useRef(null);
  const canvasRef = useRef(null);
  const [summary, setSummary] = useState(null);
  const [progress, setProgress] = useState({ loaded: 0, total: 0, done: false });
  const [error, setError] = useState(null);
  const [cronNames, setCronNames] = useState({});
  const [sel, setSel] = useState(null);
  const [live, setLive] = useState({ ok: false, at: null });
  const [, setTick] = useState(0);

  useEffect(() => { injectAtlasCSS(); }, []);

  // initial load: summary, lane names, then the whole log in chunks
  useEffect(() => {
    let cancelled = false;
    const model = new EventModel();
    modelRef.current = model;
    const abort = { aborted: false };
    fetchJSON(API + "/atlas/lanes").then((d) => !cancelled && setCronNames(d.cron_names || {})).catch(() => {});
    fetchJSON(API + "/atlas/summary").then(async (s) => {
      if (cancelled) return;
      if (s.error) throw new Error(s.error);
      setSummary(s);
      let shown = false;
      await loadEvents(model, s.events, (loaded, total) => {
        if (cancelled) return;
        if (!shown && loaded) {
          model.orderLanes(false);
          canvasRef.current = createCanvas(hostRef.current, model, handlersRef.current);
          canvasRef.current.fitAll();
          shown = true;
        } else if (shown) {
          model.orderLanes(false);
          canvasRef.current.modelChanged();
          canvasRef.current.fitAll();
        }
        setProgress({ loaded, total, done: false });
      }, abort);
      if (cancelled) return;
      model.orderLanes(false);
      if (!canvasRef.current && model.n) {
        canvasRef.current = createCanvas(hostRef.current, model, handlersRef.current);
      }
      if (canvasRef.current) { canvasRef.current.modelChanged(); canvasRef.current.fitAll(); }
      setProgress({ loaded: model.n, total: model.n, done: true });
      setLive({ ok: true, at: Date.now() });
    }).catch((e) => !cancelled && setError((e && e.message) || "failed to load"));
    return () => {
      cancelled = true;
      abort.aborted = true;
      if (canvasRef.current) canvasRef.current.destroy();
      canvasRef.current = null;
    };
  }, []);

  useEffect(() => { if (canvasRef.current) canvasRef.current.setCronNames(cronNames); }, [cronNames, progress.done]);

  // live: new events every POLL_MS while the page is visible, the summary less often
  useEffect(() => {
    if (!progress.done) return undefined;
    const poll = () => {
      if (document.visibilityState !== "visible" || !modelRef.current) return;
      pollEvents(modelRef.current)
        .then((added) => { if (added && canvasRef.current) canvasRef.current.modelChanged(); setLive({ ok: true, at: Date.now() }); })
        .catch(() => setLive((l) => ({ ok: false, at: l.at })));
    };
    const refreshSummary = () => {
      if (document.visibilityState !== "visible") return;
      fetchJSON(API + "/atlas/summary").then((s) => { if (!s.error) setSummary(s); }).catch(() => {});
    };
    const a = setInterval(poll, POLL_MS);
    const b = setInterval(refreshSummary, SUMMARY_MS);
    const c = setInterval(() => setTick((x) => x + 1), 15000);    // keeps "updated … ago" honest
    return () => { clearInterval(a); clearInterval(b); clearInterval(c); };
  }, [progress.done]);

  // selection -> canvas highlight
  const select = useCallback((next) => {
    setSel(next);
    const model = modelRef.current, canvas = canvasRef.current;
    if (!model || !canvas || !next) { if (canvas) canvas.setSelection(null, []); return; }
    if (next.kind === "event") {
      const k = model.indexOfSeq(next.seq);
      const row = k >= 0 ? model.rowOfLane[model.lane[k]] : null;
      canvas.setSelection({ ...next, laneRow: row }, k >= 0 ? [k] : []);
      if (k >= 0 && next.focus) canvas.focusEvent(k);
    } else if (next.kind === "session") {
      const s = model.sessionIx.get(next.id);
      const idx = s == null ? [] : model.indicesWhere((k) => model.session[k] === s, 5000);
      const row = s == null ? null : model.rowOfLane[model.sessions[s].lane];
      canvas.setSelection({ ...next, laneRow: row }, idx);
      if (idx.length) canvas.focusEvent(idx[0]);
    } else if (next.kind === "lane") {
      const row = model.rowOfLane[next.lane];
      canvas.setSelection({ ...next, laneRow: row }, []);
      canvas.focusRow(row);
    } else {
      canvas.setSelection({ ...next, laneRow: null }, []);
    }
  }, []);

  const handlersRef = useRef(null);
  handlersRef.current = {
    onEvent: (k) => select({ kind: "event", seq: modelRef.current.seq[k] }),
    onLane: (lane) => select({ kind: "lane", lane }),
  };

  const onBelief = useCallback((id) => select({ kind: "belief", id }), [select]);
  const onEventSeq = useCallback((seq) => select({ kind: "event", seq, focus: true }), [select]);
  const onSession = useCallback((id) => select({ kind: "session", id }), [select]);
  const onLane = useCallback((lane) => select({ kind: "lane", lane }), [select]);

  if (error) return h("div", { className: "chr-err" }, "The Atlas could not read the store: " + error);

  const model = modelRef.current;
  const b = (summary && summary.beliefs) || {};
  const facts = b.fact || {};
  const notes = b.note || {};
  const legendTypes = model && model.types.length ? model.types : [];

  return h("div", { className: "atl" },
    h("div", { className: "atl-stats" },
      summary ? [
        h("span", { key: "e" }, h("b", null, fmt(summary.events)), " events"),
        model && progress.done ? h("span", { key: "w" }, h("b", null, fmt(model.lanes.length)), " writers") : null,
        h("span", { key: "f" }, h("b", null, fmt(facts.active)), " facts in force"),
        facts.superseded ? h("span", { key: "fs" }, h("b", null, fmt(facts.superseded)), " replaced") : null,
        facts.draft ? h("span", { key: "fd" }, h("b", null, fmt(facts.draft)), " pending review") : null,
        h("span", { key: "n" }, h("b", null, fmt(notes.active)), " notes"),
        h("span", { key: "c" }, h("b", null, fmt(summary.contradictions_open)), " open contradictions"),
      ] : h("span", null, "Reading the store…"),
      h("span", { className: "atl-live" },
        h("span", { className: "atl-dot" + (live.ok ? "" : " is-off") }),
        progress.done ? (live.ok ? "Live · checked " + relTime(new Date(live.at).toISOString()) : "Not updating · last checked " + relTime(live.at ? new Date(live.at).toISOString() : null)) : "Loading")),
    h("div", { className: "atl-body" },
      h("div", { className: "atl-main" },
        h("div", { className: "atl-canvas", ref: hostRef },
          !progress.done ? h("div", { className: "atl-progress" },
            progress.total ? "Loaded " + fmt(progress.loaded) + " of " + fmt(progress.total) + " events" : "Loading events…") : null),
        h("div", { className: "atl-legend" }, legendTypes.map((t) => {
          const st = typeStyle(t);
          return h("span", { key: t }, h("i", { style: { background: "rgb(" + st.color.join(",") + ")" } }), st.label);
        })),
        model ? h(Lenses, { model, onBelief }) : null),
      h("div", { className: "atl-side" },
        model ? h(Inspector, { sel, model, cronNames, onBelief, onEventSeq, onSession, onLane }) : null)));
}

window.__CHRONICLE_ATLAS__ = { Atlas };
