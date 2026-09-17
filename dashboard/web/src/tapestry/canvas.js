// The Tapestry canvas: two deck.gl orthographic views on one time axis.
//
//   activity  events per time bin, stacked by type; drag across it to zoom to a range
//   writers   every event as a point, one row per writer (cron job, session,
//             background actor); wheel zooms time, drag pans
//
// Plain DOM overlays carry the text a GPU layer renders poorly: the row labels
// and the time axis. They are redrawn from the view state on every change.

import { Deck, OrthographicView } from "@deck.gl/core";
import { ScatterplotLayer, SolidPolygonLayer, LineLayer } from "@deck.gl/layers";
import { typeStyle, laneLabel } from "./data.js";

export const LABEL_W = 190;
export const ACT_H = 84;
export const AXIS_H = 22;
const ROW_PX = 9;          // default pixels per writer row
const MIN_ROW_PX = 2;
const MAX_ROW_PX = 28;

const DAY = 24;
const TICK_STEPS = [0.25, 0.5, 1, 2, 3, 6, 12, DAY, 2 * DAY, 7 * DAY, 14 * DAY, 30 * DAY]; // hours

export function createCanvas(container, model, handlers) {
  const root = document.createElement("div");
  root.className = "atl-canvas-root";
  const deckHost = document.createElement("div");
  deckHost.className = "atl-deck";
  const labels = document.createElement("div");
  labels.className = "atl-labels";
  labels.style.top = ACT_H + AXIS_H + "px";
  labels.style.width = LABEL_W + "px";
  const axis = document.createElement("div");
  axis.className = "atl-axis";
  axis.style.top = ACT_H + "px";
  axis.style.left = LABEL_W + "px";
  axis.style.height = AXIS_H + "px";
  const actLabel = document.createElement("div");
  actLabel.className = "atl-actlabel";
  actLabel.style.width = LABEL_W + "px";
  actLabel.style.height = ACT_H + "px";
  actLabel.textContent = "Events over time";
  const bar = document.createElement("div");
  bar.className = "atl-bar";
  const rangeText = document.createElement("span");
  const wholeBtn = document.createElement("button");
  wholeBtn.className = "atl-link";
  wholeBtn.textContent = "Whole log";
  bar.append(rangeText, wholeBtn);
  root.append(deckHost, labels, axis, actLabel, bar);
  container.appendChild(root);

  let cronNames = {};
  let selection = null;          // {kind:'event'|'session'|'lane'|'belief', ...}
  let highlight = [];            // event indices to ring
  let brush = null;              // [x0, x1] while dragging on the activity strip
  let hoverRow = -1;
  let size = { w: container.clientWidth || 800, h: container.clientHeight || 560 };

  const plotW = () => Math.max(50, size.w - LABEL_W);
  const writersH = () => Math.max(50, size.h - ACT_H - AXIS_H);

  let viewState = {
    writers: { target: [0, 0, 0], zoomX: 0, zoomY: Math.log2(ROW_PX), zoomAxis: "X" },
    activity: { target: [0, ACT_H / 2, 0], zoomX: 0, zoomY: 0 },
  };

  const views = [
    new OrthographicView({ id: "activity", x: LABEL_W, y: 0, width: `calc(100% - ${LABEL_W}px)`, height: ACT_H, flipY: true, controller: false }),
    new OrthographicView({ id: "writers", x: LABEL_W, y: ACT_H + AXIS_H, width: `calc(100% - ${LABEL_W}px)`, height: `calc(100% - ${ACT_H + AXIS_H}px)`, flipY: true,
      controller: { dragPan: true, scrollZoom: { speed: 0.02, smooth: false }, doubleClickZoom: false, inertia: false, keyboard: false } }),
  ];

  function visibleX() {
    const w = viewState.writers;
    const half = plotW() / 2 / Math.pow(2, w.zoomX);
    return [w.target[0] - half, w.target[0] + half];
  }

  function rowPx() { return Math.pow(2, viewState.writers.zoomY); }

  function constrain(ws) {
    const [x0, x1] = model.extentX();
    const span = Math.max(1 / 60, x1 - x0);
    const minZoomX = Math.log2(plotW() / (span * 1.04));
    const maxZoomX = Math.log2(plotW() / (5 / 60));       // five minutes across the plot
    const zoomX = Math.min(maxZoomX, Math.max(minZoomX, ws.zoomX));
    const half = plotW() / 2 / Math.pow(2, zoomX);
    const pad = span * 0.02;
    let cx = ws.target[0];
    cx = Math.max(x0 - pad + half, Math.min(x1 + pad - half, cx));
    if (x1 - x0 + 2 * pad < 2 * half) cx = (x0 + x1) / 2;
    const zoomY = Math.log2(Math.min(MAX_ROW_PX, Math.max(MIN_ROW_PX, Math.pow(2, ws.zoomY))));
    const rows = model.lanes.length;
    const halfRows = writersH() / 2 / Math.pow(2, zoomY);
    let cy = ws.target[1];
    cy = rows <= 2 * halfRows ? halfRows : Math.max(halfRows, Math.min(rows - halfRows, cy));
    return { ...ws, target: [cx, cy, 0], zoomX, zoomY, zoomAxis: "X" };
  }

  function setWriters(ws) {
    const w = constrain(ws);
    viewState = { writers: w, activity: { target: [w.target[0], ACT_H / 2, 0], zoomX: w.zoomX, zoomY: 0 } };
    render();
  }

  // -- layers ------------------------------------------------------------------
  function activityLayers() {
    const [x0, x1] = visibleX();
    const bins = Math.max(10, Math.floor(plotW() / 3));
    const { counts, nt, width, max } = model.bin(x0, x1, bins);
    const order = model.types.map((name, i) => i);
    const polys = [];
    if (max > 0) {
      for (let b = 0; b < bins; b++) {
        let base = 0;
        const bx0 = x0 + b * width, bx1 = bx0 + width * 0.86;
        for (const j of order) {
          const c = counts[b * nt + j];
          if (!c) continue;
          const y1 = ACT_H - 2 - ((base) / max) * (ACT_H - 10);
          base += c;
          const y0 = ACT_H - 2 - ((base) / max) * (ACT_H - 10);
          polys.push({ polygon: [[bx0, y1], [bx1, y1], [bx1, y0], [bx0, y0]], color: typeStyle(model.types[j]).color });
        }
      }
    }
    const layers = [new SolidPolygonLayer({ id: "activity-bars", data: polys, getPolygon: (d) => d.polygon, getFillColor: (d) => [...d.color, 220] })];
    if (brush) {
      const [a, b] = brush[0] < brush[1] ? brush : [brush[1], brush[0]];
      layers.push(new SolidPolygonLayer({ id: "activity-brush", data: [{ polygon: [[a, 0], [b, 0], [b, ACT_H], [a, ACT_H]] }], getPolygon: (d) => d.polygon, getFillColor: [167, 139, 250, 60] }));
    }
    return layers;
  }

  function writersLayers() {
    const rows = model.lanes.length;
    const [x0, x1] = model.extentX();
    const bands = [];
    for (let r = 0; r < rows; r += 2) bands.push(r);
    const layers = [
      new SolidPolygonLayer({ id: "writers-bands", data: bands, getPolygon: (r) => [[x0 - 1e5, r], [x1 + 1e5, r], [x1 + 1e5, r + 1], [x0 - 1e5, r + 1]], getFillColor: [255, 255, 255, 7], updateTriggers: { getPolygon: [rows, x1] } }),
    ];
    const selRow = selection && selection.laneRow != null ? selection.laneRow : -1;
    if (selRow >= 0 || hoverRow >= 0) {
      const marked = [selRow, hoverRow].filter((r) => r >= 0);
      layers.push(new SolidPolygonLayer({ id: "writers-rowmark", data: marked, getPolygon: (r) => [[x0 - 1e5, r], [x1 + 1e5, r], [x1 + 1e5, r + 1], [x0 - 1e5, r + 1]], getFillColor: (r) => (r === selRow ? [167, 139, 250, 38] : [255, 255, 255, 18]), updateTriggers: { getFillColor: [selRow] } }));
    }
    if (selection && selection.kind === "lane" && selection.lane != null) {
      const L = model.lanes[selection.lane];
      const segs = [...L.sessions].map((s) => model.sessions[s]);
      layers.push(new LineLayer({ id: "writers-runs", data: segs, getSourcePosition: (s) => [model.xOf(s.first), selRow + 0.5], getTargetPosition: (s) => [model.xOf(s.last) + 1 / 120, selRow + 0.5], getColor: [205, 198, 245, 150], getWidth: 5, widthUnits: "pixels" }));
    }
    layers.push(new ScatterplotLayer({
      id: "writers-events",
      data: { length: model.n, attributes: { getPosition: { value: model.positions, size: 2 }, getFillColor: { value: model.colors, size: 4, normalized: true } } },
      radiusUnits: "pixels", getRadius: 1.7, radiusMinPixels: 1.2, pickable: true, stroked: false,
      updateTriggers: { getPosition: model.version, getFillColor: model.version },
    }));
    if (highlight.length) {
      layers.push(new ScatterplotLayer({
        id: "writers-highlight", data: highlight, getPosition: (k) => [model.positions[2 * k], model.positions[2 * k + 1]],
        radiusUnits: "pixels", getRadius: highlight.length > 400 ? 2.4 : 4.5, stroked: true, filled: false, lineWidthUnits: "pixels", getLineWidth: 1.4, getLineColor: [255, 255, 255, 230],
        updateTriggers: { getPosition: model.version },
      }));
    }
    return layers;
  }

  function tooltip({ layer, index }) {
    if (!layer || layer.id !== "writers-events" || index < 0) return null;
    const lane = model.lanes[model.lane[index]];
    const d = new Date(model.t[index] * 1000);
    return {
      text: typeStyle(model.types[model.type[index]]).label + "\n" + laneLabel(lane.key, cronNames) + "\n" +
        d.toLocaleString([], { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit", second: "2-digit" }),
      className: "atl-tip",
      style: { whiteSpace: "pre", background: "#12121f", color: "#e7e5f1", border: "1px solid rgba(150,130,230,.3)", borderRadius: "6px", padding: "6px 8px", fontSize: "12px", lineHeight: "1.35" },
    };
  }

  const deck = new Deck({
    parent: deckHost,
    width: "100%",
    height: "100%",
    views,
    viewState,
    controller: true,
    pickingRadius: 5,
    layerFilter: ({ layer, viewport }) => layer.id.startsWith(viewport.id),
    getTooltip: tooltip,
    onViewStateChange: ({ viewId, viewState: vs }) => {
      if (viewId === "writers") setWriters(vs);
      return viewState[viewId];
    },
    onHover: (info) => {
      const row = info.viewport && info.viewport.id === "writers" && info.coordinate ? Math.floor(info.coordinate[1]) : -1;
      const next = row >= 0 && row < model.lanes.length ? row : -1;
      if (next !== hoverRow) { hoverRow = next; render(); }
    },
    onClick: (info, event) => {
      if (!info.viewport) return;
      if (info.viewport.id === "writers") {
        if (info.layer && info.layer.id === "writers-events" && info.index >= 0) handlers.onEvent(info.index);
        else if (info.coordinate) {
          const row = Math.floor(info.coordinate[1]);
          if (row >= 0 && row < model.lanes.length) handlers.onLane(model.laneAtRow[row]);
        }
      } else if (info.viewport.id === "activity" && event && event.tapCount === 2) {
        fitAll();
      }
    },
    onDragStart: (info) => {
      if (info.viewport && info.viewport.id === "activity" && info.coordinate) { brush = [info.coordinate[0], info.coordinate[0]]; render(); }
    },
    onDrag: (info) => {
      if (brush && info.coordinate) { brush = [brush[0], info.coordinate[0]]; render(); }
    },
    onDragEnd: () => {
      if (!brush) return;
      const [a, b] = brush[0] < brush[1] ? brush : [brush[1], brush[0]];
      brush = null;
      if (b - a > 1 / 60) zoomTo(a, b); else render();
    },
  });

  // -- overlays ------------------------------------------------------------------
  // Overlays are built as DOM nodes with textContent: lane names come from the
  // store and from the cron registry, and nothing read from either is markup.
  function drawLabels() {
    const px = rowPx();
    const top = viewState.writers.target[1] - writersH() / 2 / px;
    const first = Math.max(0, Math.floor(top));
    const last = Math.min(model.lanes.length - 1, Math.ceil(top + writersH() / px));
    const every = px >= 11 ? 1 : Math.ceil(11 / px);
    const frag = document.createDocumentFragment();
    for (let r = first; r <= last; r++) {
      if ((r % every) !== 0) continue;
      const lane = model.lanes[model.laneAtRow[r]];
      if (!lane) continue;
      const el = document.createElement("div");
      el.className = "atl-label" + (selection && selection.laneRow === r ? " is-sel" : "");
      el.dataset.row = String(r);
      el.style.top = ((r - top) * px + px / 2).toFixed(1) + "px";
      el.textContent = laneLabel(lane.key, cronNames);
      const count = document.createElement("span");
      count.textContent = lane.count.toLocaleString();
      el.appendChild(count);
      frag.appendChild(el);
    }
    labels.replaceChildren(frag);
  }

  function drawAxis() {
    const [x0, x1] = visibleX();
    const hoursPerPx = (x1 - x0) / plotW();
    const step = TICK_STEPS.find((st) => st / hoursPerPx >= 90) || TICK_STEPS[TICK_STEPS.length - 1];
    const e0 = model.epochOf(x0), e1 = model.epochOf(x1);
    const stepS = step * 3600;
    // align to local midnight so day ticks sit on day boundaries
    const d0 = new Date(e0 * 1000);
    d0.setHours(0, 0, 0, 0);
    let t = d0.getTime() / 1000;
    while (t < e0) t += stepS;
    const frag = document.createDocumentFragment();
    for (let guard = 0; t <= e1 && guard < 200; t += stepS, guard++) {
      const d = new Date(t * 1000);
      const el = document.createElement("div");
      el.className = "atl-tick";
      el.style.left = ((model.xOf(t) - x0) / hoursPerPx).toFixed(1) + "px";
      el.textContent = step >= DAY || (d.getHours() === 0 && d.getMinutes() === 0)
        ? d.toLocaleDateString([], { month: "short", day: "numeric" })
        : d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
      frag.appendChild(el);
    }
    axis.replaceChildren(frag);
  }

  labels.addEventListener("click", (ev) => {
    const el = ev.target.closest(".atl-label");
    if (el) handlers.onLane(model.laneAtRow[+el.dataset.row]);
  });

  let raf = 0;
  function render() {
    if (raf) return;
    raf = requestAnimationFrame(() => {
      raf = 0;
      deck.setProps({ viewState, layers: [...activityLayers(), ...writersLayers()] });
      drawLabels();
      drawAxis();
      drawRange();
    });
  }

  function drawRange() {
    const [x0, x1] = visibleX();
    const [e0, e1] = model.extentX();
    const whole = x0 <= e0 + 1e-6 && x1 >= e1 - 1e-6;
    const fmt = (x) => new Date(model.epochOf(x) * 1000).toLocaleString([], { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" });
    rangeText.textContent = fmt(Math.max(x0, e0)) + " → " + fmt(Math.min(x1, e1));
    wholeBtn.style.visibility = whole ? "hidden" : "visible";
  }

  function zoomTo(a, b) {
    const zoomX = Math.log2(plotW() / Math.max(1 / 60, b - a));
    setWriters({ ...viewState.writers, target: [(a + b) / 2, viewState.writers.target[1], 0], zoomX });
  }

  function fitAll() {
    const [x0, x1] = model.extentX();
    setWriters({ ...viewState.writers, target: [(x0 + x1) / 2, 0, 0], zoomX: -Infinity });
  }

  const ro = new ResizeObserver(() => {
    size = { w: container.clientWidth, h: container.clientHeight };
    setWriters(viewState.writers);
  });
  ro.observe(container);

  return {
    fitAll,
    zoomTo,
    modelChanged() { setWriters(viewState.writers); },
    setCronNames(names) { cronNames = names || {}; render(); },
    setSelection(sel, indices) { selection = sel; highlight = indices || []; render(); },
    /** Center the view on an event's time and row, keeping the current time zoom. */
    focusEvent(k) {
      const x = model.positions[2 * k], y = model.positions[2 * k + 1];
      const zoomX = Math.max(viewState.writers.zoomX, Math.log2(plotW() / 24));   // at most a day across
      setWriters({ ...viewState.writers, target: [x, y, 0], zoomX });
    },
    focusRow(row) { setWriters({ ...viewState.writers, target: [viewState.writers.target[0], row + 0.5, 0] }); },
    destroy() { ro.disconnect(); if (raf) cancelAnimationFrame(raf); deck.finalize(); root.remove(); },
  };
}

