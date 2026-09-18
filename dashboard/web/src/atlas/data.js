// The Atlas event model: the whole log as typed arrays, one row per event,
// decoded from /atlas/events chunks and grown in place as live events arrive.

import { fetchJSON, API } from "../common.js";

export const TYPE_STYLE = {
  observed: { label: "Turn", color: [106, 166, 242] },
  asserted: { label: "Belief written", color: [240, 181, 78] },
  signal: { label: "Signal", color: [167, 139, 250] },
  folded: { label: "Folded", color: [79, 214, 166] },
  compressed: { label: "Compressed", color: [63, 184, 160] },
  checkpoint_digest: { label: "Checkpoint", color: [143, 211, 196] },
  decayed: { label: "Decayed", color: [124, 122, 147] },
  retracted: { label: "Retracted", color: [240, 112, 110] },
  corrected: { label: "Corrected", color: [255, 154, 118] },
  contradicted: { label: "Contradicted", color: [240, 112, 110] },
  confirmed: { label: "Confirmed", color: [155, 212, 122] },
  derived: { label: "Derived", color: [224, 192, 112] },
};
const OTHER = { label: "Other", color: [155, 151, 184] };

export function typeStyle(name) {
  return TYPE_STYLE[name] || { ...OTHER, label: name };
}

const SESSION_TS = /^(\d{4})(\d{2})(\d{2})_(\d{2})(\d{2})(\d{2})/;

export function laneLabel(key, cronNames) {
  const i = key.indexOf(":");
  const kind = key.slice(0, i);
  const rest = key.slice(i + 1);
  if (kind === "cron") return (cronNames && cronNames[rest]) || "Cron job " + rest.slice(0, 8);
  if (kind === "background") return rest.charAt(0).toUpperCase() + rest.slice(1) + " (no session)";
  const m = SESSION_TS.exec(rest);
  if (m) {
    const d = new Date(Date.UTC(+m[1], +m[2] - 1, +m[3], +m[4], +m[5], +m[6]));
    return "Session " + d.toLocaleString([], { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" });
  }
  return "Session " + rest.slice(0, 18);
}

export class EventModel {
  constructor() {
    this.n = 0;
    this.cap = 0;
    this.seq = new Int32Array(0);
    this.t = new Int32Array(0);
    this.type = new Uint8Array(0);
    this.lane = new Int32Array(0);
    this.session = new Int32Array(0);
    this.types = [];
    this.typeIx = new Map();
    this.lanes = [];          // {key, count, first, last, sessions:Set}
    this.laneIx = new Map();
    this.sessions = [];       // {id, lane, count, first, last}
    this.sessionIx = new Map();
    this.lastSeq = 0;
    this.t0 = null;           // epoch seconds of the first event: x is hours since t0
    this.version = 0;         // bumps on every change, for deck.gl update triggers
    this.rowOfLane = new Int32Array(0);
    this.positions = new Float32Array(0);
    this.colors = new Uint8Array(0);
  }

  _grow(extra) {
    const need = this.n + extra;
    if (need <= this.cap) return;
    let cap = Math.max(1024, this.cap);
    while (cap < need) cap *= 2;
    const g = (Ctor, old, width = 1) => { const a = new Ctor(cap * width); a.set(old.subarray(0, this.n * width)); return a; };
    this.seq = g(Int32Array, this.seq);
    this.t = g(Int32Array, this.t);
    this.type = g(Uint8Array, this.type);
    this.lane = g(Int32Array, this.lane);
    this.session = g(Int32Array, this.session);
    this.positions = g(Float32Array, this.positions, 2);
    this.colors = g(Uint8Array, this.colors, 4);
    this.cap = cap;
  }

  /** Decode one /atlas/events chunk and append it. Returns the number added. */
  append(ch) {
    if (!ch || !ch.n) return 0;
    this._grow(ch.n);
    const typeMap = ch.types.map((name) => {
      if (!this.typeIx.has(name)) { this.typeIx.set(name, this.types.length); this.types.push(name); }
      return this.typeIx.get(name);
    });
    const writerMap = ch.writers.map(([sid, laneKey]) => {
      if (!this.laneIx.has(laneKey)) {
        this.laneIx.set(laneKey, this.lanes.length);
        this.lanes.push({ key: laneKey, count: 0, first: null, last: null, sessions: new Set() });
      }
      const lane = this.laneIx.get(laneKey);
      let s = -1;
      if (sid) {
        if (!this.sessionIx.has(sid)) {
          this.sessionIx.set(sid, this.sessions.length);
          this.sessions.push({ id: sid, lane, count: 0, first: null, last: null });
        }
        s = this.sessionIx.get(sid);
      }
      return [lane, s];
    });
    let seq = ch.seq0, t = ch.t0;
    if (this.t0 === null) this.t0 = ch.t0;
    for (let i = 0; i < ch.n; i++) {
      seq += ch.dseq[i];
      t += ch.dt[i];
      const k = this.n + i;
      const [lane, s] = writerMap[ch.writer[i]];
      this.seq[k] = seq;
      this.t[k] = t;
      this.type[k] = typeMap[ch.type[i]];
      this.lane[k] = lane;
      this.session[k] = s;
      const L = this.lanes[lane];
      L.count++; if (L.first === null) L.first = t; L.last = t;
      if (s >= 0) {
        const S = this.sessions[s];
        S.count++; if (S.first === null) S.first = t; S.last = t;
        L.sessions.add(s);
      }
    }
    this.n += ch.n;
    this.lastSeq = seq;
    this.version++;
    return ch.n;
  }

  /** Order lanes heaviest-first. Called once after the initial load; lanes that
   *  appear later go to the bottom so a live update never reshuffles the view. */
  orderLanes(keepExisting) {
    const rows = new Int32Array(this.lanes.length).fill(-1);
    if (keepExisting && this.rowOfLane.length) {
      rows.set(this.rowOfLane.subarray(0, Math.min(this.rowOfLane.length, rows.length)));
      let next = this.rowOfLane.length ? Math.max(...this.rowOfLane) + 1 : 0;
      for (let i = 0; i < rows.length; i++) if (rows[i] < 0) rows[i] = next++;
    } else {
      this.lanes.map((l, i) => i).sort((a, b) => this.lanes[b].count - this.lanes[a].count)
        .forEach((lane, row) => { rows[lane] = row; });
    }
    this.rowOfLane = rows;
    this.laneAtRow = new Int32Array(rows.length);
    rows.forEach((row, lane) => { this.laneAtRow[row] = lane; });
    // Existing lanes keep their rows on a live append, so only a full re-order
    // has to rewrite every position; the caller fills the appended tail.
    if (!keepExisting) this.fillGeometry(0);
  }

  /** Positions (x = hours since t0, y = lane row) and colours from index `from`. */
  fillGeometry(from) {
    const palette = this.types.map((name) => typeStyle(name).color);
    for (let k = from; k < this.n; k++) {
      this.positions[2 * k] = (this.t[k] - this.t0) / 3600;
      this.positions[2 * k + 1] = this.rowOfLane[this.lane[k]] + 0.5;
      const c = palette[this.type[k]];
      this.colors[4 * k] = c[0]; this.colors[4 * k + 1] = c[1]; this.colors[4 * k + 2] = c[2]; this.colors[4 * k + 3] = 200;
    }
    this.version++;
  }

  xOf(epochSeconds) { return (epochSeconds - this.t0) / 3600; }
  epochOf(x) { return this.t0 + x * 3600; }
  extentX() { return this.n ? [0, (this.t[this.n - 1] - this.t0) / 3600] : [0, 1]; }

  /** Event counts per type in `bins` equal bins over [x0, x1). */
  bin(x0, x1, bins) {
    const nt = this.types.length;
    const counts = new Uint32Array(bins * nt);
    const width = (x1 - x0) / bins;
    if (width <= 0) return { counts, nt, width, max: 0 };
    for (let k = 0; k < this.n; k++) {
      const x = this.positions[2 * k];
      if (x < x0 || x >= x1) continue;
      counts[Math.floor((x - x0) / width) * nt + this.type[k]]++;
    }
    let max = 0;
    for (let b = 0; b < bins; b++) {
      let s = 0;
      for (let j = 0; j < nt; j++) s += counts[b * nt + j];
      if (s > max) max = s;
    }
    return { counts, nt, width, max };
  }

  indexOfSeq(seq) {
    let lo = 0, hi = this.n - 1;
    while (lo <= hi) {
      const mid = (lo + hi) >> 1;
      if (this.seq[mid] === seq) return mid;
      if (this.seq[mid] < seq) lo = mid + 1; else hi = mid - 1;
    }
    return -1;
  }

  indicesWhere(pred, cap = 200000) {
    const out = [];
    for (let k = 0; k < this.n && out.length < cap; k++) if (pred(k)) out.push(k);
    return out;
  }
}

export async function loadEvents(model, total, onProgress, signal) {
  let after = model.lastSeq;
  for (;;) {
    if (signal && signal.aborted) return;
    let ch;
    try {
      ch = await fetchJSON(API + "/atlas/events?after_seq=" + after + "&limit=50000");
    } catch (e) {
      throw new Error("loading events after seq " + after + " failed: " + ((e && e.message) || e));
    }
    if (ch.error) throw new Error(ch.error);
    model.append(ch);
    after = ch.next_after_seq;
    onProgress(model.n, total);
    if (ch.done) return;
  }
}

export async function pollEvents(model) {
  const before = model.n;
  const ch = await fetchJSON(API + "/atlas/events?after_seq=" + model.lastSeq + "&limit=50000");
  if (ch.error || !ch.n) return 0;
  model.append(ch);
  model.orderLanes(true);
  model.fillGeometry(before);
  return ch.n;
}
