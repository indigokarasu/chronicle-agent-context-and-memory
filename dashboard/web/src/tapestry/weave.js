// The weave: what memory holds, over time.
//
// One thread per entity that has dated memory, and a knot on it for every event
// that involves it. An event that names two of them — "Pat Testley's birthday",
// an appointment with a doctor — is drawn as a link between their threads, so a
// life shows as threads crossing rather than as rows of machinery.
//
// deck.gl, orthographic: x is time, y is the thread. Text is DOM (labels, axis),
// which a GPU layer renders poorly, and is redrawn from the view state.

import { Deck, OrthographicView } from "@deck.gl/core";
import { ScatterplotLayer, LineLayer } from "@deck.gl/layers";

const LABEL_W = 170;
const AXIS_H = 20;
const ROW_PX = 14;
const MIN_ROW_PX = 4;
const MAX_ROW_PX = 34;
const LABEL_MIN_PX = 9;     // below this a name is a smear, so none are drawn
const MAX_THREADS = 24;     // the busiest; the rest are counted, not crammed at 2px
const DAY = 86400;

const KIND_COLOR = {
  person: [167, 139, 250], place: [79, 214, 166], thing: [240, 181, 78],
  event: [106, 166, 242], concept: [205, 198, 245], unclassified: [120, 118, 140],
};

function epoch(iso) {
  if (!iso) return null;
  const t = Date.parse(iso.length <= 10 ? iso + "T12:00:00Z" : iso);
  return isFinite(t) ? t / 1000 : null;
}

export function createWeave(container, handlers) {
  const root = document.createElement("div");
  root.className = "tap-weave-root";
  const deckHost = document.createElement("div");
  deckHost.className = "tap-deck";
  const labels = document.createElement("div");
  labels.className = "tap-threads";
  labels.style.width = LABEL_W + "px";
  const axis = document.createElement("div");
  axis.className = "tap-axis";
  axis.style.left = LABEL_W + "px";
  axis.style.height = AXIS_H + "px";
  const empty = document.createElement("div");
  empty.className = "tap-weave-empty chr-quiet";
  empty.textContent = "Nothing in memory carries a date yet.";
  empty.style.display = "none";
  root.append(deckHost, labels, axis, empty);
  container.appendChild(root);

  let threads = [];      // [{id, name, kind, y}]
  let hidden = 0;        // threads the panel is too short to draw
  let knots = [];        // [{x, y, item}]
  let links = [];        // [{x, y0, y1, color}]
  let extent = [0, 1];
  let selectedId = null;
  let size = { w: container.clientWidth || 800, h: container.clientHeight || 360 };
  let view = { target: [0, 0, 0], zoom: [0, 0] };

  const plotW = () => Math.max(60, size.w - LABEL_W);
  const plotH = () => Math.max(60, size.h - AXIS_H);

  // The view is the PLOT, not the canvas: sized "100%" it centres on the whole
  // canvas including the label column and the axis strip, which slides every
  // row half a row down from the name beside it — and a click then lands
  // between two threads.
  const weaveView = () => new OrthographicView({ id: "weave", x: LABEL_W, y: AXIS_H,
                                                 width: plotW(), height: plotH(), zoomAxis: "X" });

  const deck = new Deck({
    parent: deckHost,
    views: weaveView(),
    initialViewState: view,
    controller: { dragPan: true, scrollZoom: { smooth: false }, doubleClickZoom: false },
    // A knot is 2.6px: without a radius a click has to land on the pixel, and a
    // hover never resolves at all.
    pickingRadius: 6,
    onViewStateChange: ({ viewState }) => { view = viewState; deck.setProps({ viewState }); redrawText(); },
    getTooltip: ({ object }) => {
      if (!object || !object.item) return null;
      const it = object.item;
      return { text: [it.name, it.when || "", it.subtype || ""].filter(Boolean).join("\n") };
    },
    onClick: ({ object }) => { if (object && object.item && handlers.onPick) handlers.onPick(object.item); },
    layers: [],
  });

  function rowPx() {
    if (!threads.length) return ROW_PX;
    return Math.max(MIN_ROW_PX, Math.min(MAX_ROW_PX, plotH() / threads.length));
  }

  function build(items) {
    const dated = items.filter((it) => it.kind === "event" && epoch(it.when) != null);
    const byId = new Map(items.map((it) => [it.id, it]));
    // A thread for every entity a dated event involves, plus "You" if it has any.
    const order = [];
    const seen = new Set();
    const add = (id) => {
      if (!id || seen.has(id)) return;
      const ent = byId.get(id);
      if (!ent || ent.origin !== "entity") return;
      seen.add(id);
      order.push(ent);
    };
    add("user");
    dated.forEach((ev) => { (ev.participants || []).forEach(add); add(ev.of); });
    // Busiest first, so a fixed number of rows shows the most of a life; the
    // rest are counted in the corner rather than drawn 1px high.
    const weight = new Map();
    dated.forEach((ev) => {
      (ev.participants || []).forEach((p) => weight.set(p, (weight.get(p) || 0) + 1));
      if (ev.of) weight.set(ev.of, (weight.get(ev.of) || 0) + 1);
    });
    const ranked = order.slice().sort((a, b) =>
      (weight.get(b.id) || 0) - (weight.get(a.id) || 0) || (a.name || "").localeCompare(b.name || ""));
    hidden = Math.max(0, ranked.length - MAX_THREADS);
    threads = ranked.slice(0, MAX_THREADS)
      .map((ent, i) => ({ id: ent.id, name: ent.name, kind: ent.kind, y: i }));
    const rowOf = new Map(threads.map((t) => [t.id, t.y]));

    knots = [];
    links = [];
    let lo = Infinity, hi = -Infinity;
    dated.forEach((ev) => {
      const x = epoch(ev.when);
      lo = Math.min(lo, x); hi = Math.max(hi, x);
      const rows = [];
      (ev.participants || []).forEach((p) => { if (rowOf.has(p)) rows.push(rowOf.get(p)); });
      if (rowOf.has(ev.of)) rows.push(rowOf.get(ev.of));
      if (!rows.length) return;   // its threads are among the ones not drawn
      rows.forEach((y) => knots.push({ x, y, item: ev }));
      if (rows.length > 1) {
        const y0 = Math.min.apply(null, rows), y1 = Math.max.apply(null, rows);
        links.push({ x, y0, y1 });
      }
    });
    extent = isFinite(lo) && hi > lo ? [lo, hi] : [Date.now() / 1000 - 30 * DAY, Date.now() / 1000];
    empty.style.display = knots.length ? "none" : "";
  }

  function layers() {
    const px = rowPx();
    const spanX = Math.max(1, extent[1] - extent[0]);
    const sx = (t) => ((t - extent[0]) / spanX) * plotW();
    const sy = (y) => y * px + px / 2;
    const color = (item) => KIND_COLOR[item.kind] || KIND_COLOR.unclassified;
    return [
      new LineLayer({
        id: "threads",
        data: threads,
        getSourcePosition: (t) => [0, sy(t.y)],
        getTargetPosition: (t) => [plotW(), sy(t.y)],
        getColor: (t) => (t.id === selectedId ? [167, 139, 250, 150] : [150, 130, 230, 38]),
        getWidth: (t) => (t.id === selectedId ? 2 : 1),
        updateTriggers: { getColor: selectedId, getWidth: selectedId },
      }),
      new LineLayer({
        id: "crossings",
        data: links,
        getSourcePosition: (l) => [sx(l.x), sy(l.y0)],
        getTargetPosition: (l) => [sx(l.x), sy(l.y1)],
        getColor: [106, 166, 242, 90],
        getWidth: 1,
      }),
      new ScatterplotLayer({
        id: "knots",
        data: knots,
        pickable: true,
        radiusUnits: "pixels",
        getPosition: (k) => [sx(k.x), sy(k.y)],
        getRadius: (k) => (k.item.id === (selectedId || "") ? 4.5 : 2.6),
        getFillColor: (k) => color(k.item).concat([210]),
        updateTriggers: { getRadius: selectedId },
      }),
    ];
  }

  function redrawText() {
    const px = rowPx();
    labels.innerHTML = "";
    labels.style.top = AXIS_H + "px";
    if (px >= LABEL_MIN_PX) {
      threads.forEach((t) => {
        const el = document.createElement("div");
        el.className = "tap-thread" + (t.id === selectedId ? " is-sel" : "");
        el.style.height = px + "px";
        el.style.lineHeight = px + "px";
        el.textContent = t.name;
        el.title = t.name;
        el.onclick = () => handlers.onPick && handlers.onPick({ id: t.id, name: t.name, kind: t.kind,
                                                                origin: "entity" });
        labels.appendChild(el);
      });
    } else {
      const el = document.createElement("div");
      el.className = "tap-thread-note";
      el.textContent = threads.length + " threads";
      labels.appendChild(el);
    }
    if (hidden) {
      const more = document.createElement("div");
      more.className = "tap-thread-note";
      more.textContent = "+" + hidden + " quieter";
      labels.appendChild(more);
    }
    axis.innerHTML = "";
    const spanX = Math.max(1, extent[1] - extent[0]);
    const ticks = 6;
    for (let i = 0; i <= ticks; i++) {
      const t = extent[0] + (spanX * i) / ticks;
      const el = document.createElement("span");
      el.className = "tap-tick";
      el.style.left = ((i / ticks) * plotW()) + "px";
      el.textContent = new Date(t * 1000).toLocaleDateString([], { year: "numeric", month: "short" });
      axis.appendChild(el);
    }
  }

  function draw() {
    // An orthographic view puts world (0,0) at the CENTRE of its viewport, so a
    // plot laid out from (0,0) would start half a screen to the right. The
    // target is the middle of the content.
    view = { target: [plotW() / 2, plotH() / 2, 0], zoom: view.zoom || [0, 0] };
    deck.setProps({ views: weaveView(), layers: layers(), width: size.w, height: size.h,
                    viewState: view });
    redrawText();
  }

  const ro = typeof ResizeObserver === "function"
    ? new ResizeObserver(() => {
        size = { w: container.clientWidth || size.w, h: container.clientHeight || size.h };
        draw();
      })
    : null;
  if (ro) ro.observe(container);

  return {
    setData(items, selected) {
      selectedId = selected || null;
      build(items || []);
      draw();
    },
    destroy() {
      if (ro) ro.disconnect();
      deck.finalize();
      if (root.parentNode) root.parentNode.removeChild(root);
    },
  };
}
