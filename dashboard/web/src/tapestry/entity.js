// One entity, in full: what memory says about it now, what it used to say, the
// events it appears in, and every captured turn that names it.
//
// Every row carries where it came from, and a captured turn carries who was
// speaking in it (engine/speaker.py): a hit inside a cron job's output says
// "automation", so nothing here reads as something the user said when it was
// not. "Provenance" opens the log at that event.

import { h, hooks, fetchJSON, API, fmt, when } from "../common.js";

const { useState, useEffect } = hooks;

const SPEAKER_LABEL = {
  human: "you", automation: "automation", assistant: "the assistant",
  tool: "a tool", system: "the host", unknown: "unknown",
};

function Facts({ title, rows, onOpenProvenance }) {
  if (!rows || !rows.length) return null;
  return h("div", { className: "tap-sec" },
    h("div", { className: "tap-sec-h" }, title),
    h("div", { className: "tap-facts" },
      rows.map((f) =>
        h("div", { key: f.belief_id, className: "tap-fact" },
          h("span", { className: "tap-pred" }, (f.predicate_canonical || "").replace(/_/g, " ")),
          h("span", { className: "tap-val" }, f.value),
          f.valid_from ? h("span", { className: "tap-when" }, String(f.valid_from).slice(0, 10)) : null,
          h("span", { className: "tap-src" }, f.src || "unknown source"),
          f.src_event
            ? h("button", {
                className: "atl-link", title: "Where this came from",
                onClick: () => onOpenProvenance({ event_id: f.src_event, seq: f.src_seq }),
              }, "provenance")
            : null))));
}

function Events({ rows, onOpenProvenance }) {
  if (!rows || !rows.length) return null;
  return h("div", { className: "tap-sec" },
    h("div", { className: "tap-sec-h" }, "Events (" + fmt(rows.length) + ")"),
    h("div", { className: "tap-events" },
      rows.slice(0, 200).map((e) =>
        h("div", { key: e.id, className: "tap-event" },
          h("span", { className: "tap-when" }, e.when || "undated"),
          h("span", { className: "tap-ev-kind" }, e.subtype),
          h("span", { className: "tap-val", title: e.value }, e.name),
          h("span", { className: "tap-src" }, e.src || "")))));
}

function Mentions({ rows, onOpenProvenance }) {
  if (!rows || !rows.length) return null;
  return h("div", { className: "tap-sec" },
    h("div", { className: "tap-sec-h" }, "Mentioned in " + fmt(rows.length) + " captured turn(s)"),
    h("div", { className: "tap-mentions" },
      rows.map((m) =>
        h("div", { key: m.event_id, className: "tap-mention" },
          h("div", { className: "tap-mention-h" },
            h("span", { className: "tap-when" }, when(m.when)),
            h("span", { className: "tap-who" },
              "spoken by " + (m.speakers && m.speakers.length
                ? m.speakers.map((s) => (Object.hasOwn(SPEAKER_LABEL, s) ? SPEAKER_LABEL[s] : s)).join(", ")
                : "an unrecorded speaker")),
            h("span", { className: "tap-src" }, m.source || ""),
            h("button", {
              className: "atl-link",
              onClick: () => onOpenProvenance({ event_id: m.event_id, seq: m.seq }),
            }, "in the log")),
          h("div", { className: "tap-excerpt" }, m.excerpt)))));
}

export function EntityDetail({ item, onOpenProvenance, onPickEntity, nameOf }) {
  const [detail, setDetail] = useState(null);
  const [error, setError] = useState(null);

  useEffect(() => {
    setDetail(null); setError(null);
    if (!item) return undefined;
    if (item.origin === "fact") return undefined;   // a derived event: the index row IS the detail
    let cancelled = false;
    fetchJSON(API + "/tapestry/entity?id=" + encodeURIComponent(item.id))
      .then((d) => { if (!cancelled) { if (d.error) setError(d.error); else setDetail(d); } })
      .catch((e) => !cancelled && setError(e.message));
    return () => { cancelled = true; };
  }, [item && item.id]);

  if (!item) {
    return h("div", { className: "tap-detail tap-empty chr-quiet" },
      "Pick something on the left, or a knot in the weave above.");
  }

  if (item.origin === "fact") {
    return h("div", { className: "tap-detail" },
      h("div", { className: "tap-head" },
        h("div", { className: "tap-title" }, item.name),
        h("div", { className: "tap-sub" },
          [item.kind, item.subtype, item.when].filter(Boolean).join(" · "))),
      h("div", { className: "tap-sec" },
        h("div", { className: "tap-sec-h" }, "Recorded as"),
        h("div", { className: "chr-quiet" },
          "A fact of the memory it belongs to" +
          ((item.sources || []).length ? ", from " + item.sources.filter(Boolean).join(", ") : "")),
        (item.participants || []).length
          ? h("div", { className: "tap-parts" },
              "Names ",
              item.participants.map((p) =>
                h("button", { key: p, className: "atl-link", onClick: () => onPickEntity(p) },
                  (nameOf && nameOf(p)) || p)))
          : null),
      h("div", { className: "tap-sec" },
        h("button", {
          className: "atl-link",
          onClick: () => onOpenProvenance({ belief_id: item.id }),
        }, "Open the log")));
  }

  if (error) return h("div", { className: "chr-err" }, error);
  if (!detail) return h("div", { className: "tap-detail chr-quiet" }, "Reading…");

  const store = detail.people_store;
  return h("div", { className: "tap-detail" },
    h("div", { className: "tap-head" },
      h("div", { className: "tap-title" }, detail.name),
      h("div", { className: "tap-sub" },
        [detail.kind, detail.subtype].filter(Boolean).join(" · "))),
    store
      ? h("div", { className: "tap-sec" },
          h("div", { className: "tap-sec-h" }, "From your people store"),
          h("div", { className: "tap-store" },
            Object.keys(store).filter((k) => k !== "name" && k !== "is_company").map((k) =>
              h("span", { key: k, className: "tap-store-kv" },
                h("i", null, k.replace(/_/g, " ")), " ", String(store[k])))))
      : null,
    h(Facts, { title: "What memory says", rows: detail.current, onOpenProvenance }),
    h(Events, { rows: detail.events, onOpenProvenance }),
    h(Facts, { title: "What it used to say", rows: detail.past, onOpenProvenance }),
    h(Mentions, { rows: detail.mentions, onOpenProvenance }),
    (!detail.current.length && !detail.events.length && !detail.mentions.length)
      ? h("div", { className: "chr-quiet" }, "Memory holds this name and nothing else about it.")
      : null);
}
