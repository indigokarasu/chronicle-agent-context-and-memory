// dist/atlas.js — the Atlas memory navigator. Loaded by dist/index.js when the
// Atlas tab first opens; registers window.__CHRONICLE_ATLAS__ = { Atlas }.

import { h, hooks, fetchJSON, API, fmt, relTime } from "../common.js";
import { injectAtlasCSS } from "./styles.js";
import { EventModel, loadEvents, pollEvents, typeStyle } from "./data.js";
import { createCanvas } from "./canvas.js";
import { Inspector, Lenses } from "./panels.js";

const { useState, useEffect, useRef, useCallback } = hooks;
const POLL_MS = 10000;
const SUMMARY_MS = 300000;   // the server caches it for 5 minutes too

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
    fetchJSON(API + "/atlas/lanes").then((d) => !cancelled && setCronNames(d.cron_names || {}))
      .catch((e) => console.warn("[chronicle] cron job names unavailable; rows keep their job ids", e));
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
      fetchJSON(API + "/atlas/summary").then((s) => { if (!s.error) setSummary(s); })
        .catch((e) => console.warn("[chronicle] summary refresh failed", e));
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

  if (error) return h("div", { className: "chr-err" }, "Tapestry could not read the store: " + error);

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
