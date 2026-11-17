// Score view: drawing. Verovio engraves the MEI the server sends; this module
// then decorates its SVG in place:
//   * a pill with the note's name over every notehead (the reference look:
//     black pill, white "do"; hollow pill for half and whole notes);
//   * a cursor rectangle that follows the audio;
//   * classes for playing / selected / about-to-be-deleted notes.
// Every notehead keeps the xml:id of its note (app/score/mei.py), so a DOM
// element always leads back to a note id: "n00042", or "n00042-1" for the
// second head of a note tied across a barline.

import createVerovioModule from "/vendor/verovio/verovio-module.mjs";
import { VerovioToolkit } from "/vendor/verovio/verovio.mjs";
import { monotoneTimeline, noteLabel } from "./model.js";

const SVG_NS = "http://www.w3.org/2000/svg";
let _tk = null;

async function toolkit() {
  if (!_tk) {
    const module = await createVerovioModule();
    _tk = new VerovioToolkit(module);
  }
  return _tk;
}

export const noteIdOf = (elId) => (elId || "").split("-")[0];

/** Engrave `mei` into `container`. Returns the render context the other
 *  functions take. */
export async function renderScore(container, mei, { zoom = 42 } = {}) {
  const tk = await toolkit();
  const width = Math.max(480, container.clientWidth - 16);
  tk.setOptions({
    scale: zoom,
    pageWidth: Math.round((width * 100) / zoom),
    pageHeight: 60000,
    adjustPageHeight: true,
    breaks: "auto",
    header: "none",
    footer: "none",
    svgViewBox: true,
    pageMarginLeft: 40,
    pageMarginRight: 40,
    pageMarginTop: 40,
    spacingSystem: 14,
  });
  const t0 = performance.now();
  tk.loadData(mei);
  const pages = tk.getPageCount();
  let html = "";
  for (let p = 1; p <= pages; p++) html += tk.renderToSVG(p);
  container.innerHTML = html;
  const ms = Math.round(performance.now() - t0);
  return { container, pages, ms, notes: new Map(), timeline: [], cursor: null, cursorSys: null };
}

function makePill(noteEl, head, label) {
  const box = head.getBBox();
  if (!box.width) return null;
  const href = head.querySelector("use")?.getAttribute("href") || head.querySelector("use")?.getAttribute("xlink:href") || "";
  // SMuFL: E0A2 whole, E0A3 half, E0A4 black notehead.
  const hollow = href.includes("E0A2") || href.includes("E0A3");
  // No taller than a staff space: stacked thirds must not overlap.
  const h = box.height * 1.0;
  const textW = label.length * h * 0.56;
  const w = Math.max(box.width * 1.5, textW + h * 0.45);
  const cx = box.x + box.width / 2;
  const cy = box.y + box.height / 2;
  const g = document.createElementNS(SVG_NS, "g");
  g.setAttribute("class", `sd-pill${hollow ? " hollow" : ""}`);
  const rect = document.createElementNS(SVG_NS, "rect");
  rect.setAttribute("x", cx - w / 2);
  rect.setAttribute("y", cy - h / 2);
  rect.setAttribute("width", w);
  rect.setAttribute("height", h);
  rect.setAttribute("rx", h / 2);
  rect.setAttribute("stroke-width", h * 0.1);
  g.appendChild(rect);
  if (label) {
    const text = document.createElementNS(SVG_NS, "text");
    text.setAttribute("x", cx);
    text.setAttribute("y", cy);
    text.setAttribute("font-size", h * 0.74);
    text.textContent = label;
    g.appendChild(text);
  }
  noteEl.appendChild(g);
  return g;
}

/** Without names: an invisible target over the head, so a hollow (half or
 *  whole) note is as easy to click in its middle as a pill is. */
function makeHit(noteEl, head) {
  const box = head.getBBox();
  if (!box.width) return null;
  const rect = document.createElementNS(SVG_NS, "rect");
  rect.setAttribute("class", "sd-hit");
  rect.setAttribute("x", box.x - box.width * 0.15);
  rect.setAttribute("y", box.y);
  rect.setAttribute("width", box.width * 1.3);
  rect.setAttribute("height", box.height);
  noteEl.appendChild(rect);
  return rect;
}

/** Pills, the note index and the cursor timeline. `notes`: payload notes. */
export function decorate(ctx, notes, measures, { names = "solfege", labels = true } = {}) {
  const byId = new Map(notes.map((n) => [n.id, n]));
  const index = new Map();
  for (const el of ctx.container.querySelectorAll("g.note")) {
    const id = noteIdOf(el.id);
    const note = byId.get(id);
    if (!note) continue;
    if (!index.has(id)) index.set(id, []);
    index.get(id).push(el);
    const head = el.querySelector(".notehead");
    if (head && labels) makePill(el, head, noteLabel(note, names));
    else if (head) makeHit(el, head);
  }
  for (const el of ctx.container.querySelectorAll("g.harm")) {
    if (el.id && el.dataset) el.dataset.chord = el.id;
  }
  ctx.notes = index;
  ctx.timeline = buildTimeline(ctx, notes, measures);
  return ctx;
}

function systemOf(el) {
  return el.closest("g.system");
}

/** [x1, x2] of a measure from its staff lines (barline to barline). Its
 *  bounding box is no good: chord names and ties stick out of it. */
function measureSpan(el) {
  const line = el.querySelector("g.staff > path");
  const m = line && /M\s*([-\d.]+)[ ,]+[-\d.]+\s*L\s*([-\d.]+)/.exec(line.getAttribute("d") || "");
  if (m) return [Number(m[1]), Number(m[2])];
  const b = el.getBBox();
  return [b.x, b.x + b.width];
}

/** Where the cursor enters a measure. At its barline -- except on the first
 *  measure of a system, where the clef and key signature come first: there it
 *  is the first note, chord or rest. A whole-measure rest is drawn centred,
 *  so it never counts as the start (it made the cursor leap from the barline
 *  to mid-measure, 600-800 px in a frame). */
function measureEntry(el, x1) {
  const first = el.parentNode?.querySelector(":scope > g.measure") === el;
  if (!first) return x1;
  let x = Infinity;
  for (const item of el.querySelectorAll("g.layer > g")) {
    if (item.classList.contains("mRest")) continue;
    const b = item.getBBox();
    if (b.width) x = Math.min(x, b.x - 20);
  }
  return Number.isFinite(x) ? x : x1;
}

function buildTimeline(ctx, notes, measures) {
  const points = new Map(); // t -> point; a note beats a barline at the same time
  for (const m of measures) {
    const el = ctx.container.querySelector(`g.measure[id="m${m.number}"]`) || document.getElementById(`m${m.number}`);
    if (!el) continue;
    const [x1, x2] = measureSpan(el);
    const sys = systemOf(el);
    const t = Math.round(m.start * 1000) / 1000;
    if (!points.has(t)) points.set(t, { t, x: measureEntry(el, x1), sys, kind: "bar", measure: m.number });
    const te = Math.round(m.end * 1000) / 1000 - 0.001;
    if (!points.has(te)) points.set(te, { t: te, x: x2, sys, kind: "end", measure: m.number });
  }
  for (const n of notes) {
    const els = ctx.notes.get(n.id);
    if (!els || !els.length) continue;
    const head = els[0].querySelector(".notehead") || els[0];
    const box = head.getBBox();
    const t = Math.round(n.q_start * 1000) / 1000;
    const sys = systemOf(els[0]);
    const prev = points.get(t);
    if (!prev || prev.kind !== "note" || box.x < prev.x) {
      points.set(t, { t, x: box.x - box.width * 0.4, sys, kind: "note" });
    }
  }
  return monotoneTimeline([...points.values()]);
}

/** Move the cursor to x (the score's SVG units) on system `sys`.
 *
 *  A layer of its own over the score (an HTML box moved by a transform),
 *  not a rectangle inside the SVG: moving that one every frame repainted
 *  the whole engraving (tens of thousands of elements), and the score ran
 *  at 20 frames a second while it played. Where the system is, and how SVG
 *  units become pixels, is read once per system (and again if the score's
 *  width changes). Its "x" attribute keeps the position in SVG units. */
export function placeCursor(ctx, x, sys) {
  if (!sys) return;
  const host = ctx.container;
  if (!ctx.cursor || !ctx.cursor.isConnected) {
    ctx.cursor?.remove();
    ctx.cursor = document.createElement("div");
    ctx.cursor.className = "sd-cursor";
    host.insertBefore(ctx.cursor, host.firstChild);
    ctx.cursorSys = null;
  }
  const width = host.clientWidth;
  if (ctx.cursorSys !== sys || !ctx.cursorMap || ctx.cursorMap.width !== width) {
    const g = sys.closest("g.page-margin") || sys.parentNode;
    const m = g.getScreenCTM();
    const c = host.getBoundingClientRect();
    const b = sys.getBBox();
    const k = m.a; // px per SVG unit
    ctx.cursorMap = { width, k, ox: m.e - c.left, top: m.f + m.d * (b.y - 60) - c.top };
    ctx.cursor.style.width = `${90 * k}px`;
    ctx.cursor.style.height = `${(b.height + 120) * m.d}px`;
    ctx.cursorSys = sys;
  }
  const w = 90;
  const { ox, k, top } = ctx.cursorMap;
  ctx.cursor.style.transform = `translate3d(${ox + k * (x - w / 2)}px, ${top}px, 0)`;
  ctx.cursor.setAttribute("x", x - w / 2);
}

/** The bar sounding, lit with a soft band behind it (a layer of its own,
 *  as the cursor; moved only when the bar changes). `number`: the bar's
 *  number (its SVG group is "m<number>"); null takes the band away. */
export function placeBar(ctx, number) {
  const host = ctx.container;
  const width = host.clientWidth;
  if (ctx.barShown === number && ctx.barWidth === width && ctx.bar?.isConnected) return;
  ctx.barShown = number;
  ctx.barWidth = width;
  const el = number != null ? host.querySelector(`g.measure[id="m${number}"]`) : null;
  if (!el) {
    if (ctx.bar) ctx.bar.hidden = true;
    return;
  }
  if (!ctx.bar || !ctx.bar.isConnected) {
    ctx.bar = document.createElement("div");
    ctx.bar.className = "sd-bar-now";
    host.insertBefore(ctx.bar, host.firstChild);
  }
  const r = el.getBoundingClientRect();
  const c = host.getBoundingClientRect();
  const pad = 6;
  ctx.bar.hidden = false;
  ctx.bar.style.transform = `translate3d(${r.left - c.left - pad / 2}px, ${r.top - c.top - pad}px, 0)`;
  ctx.bar.style.width = `${r.width + pad}px`;
  ctx.bar.style.height = `${r.height + 2 * pad}px`;
  ctx.bar.dataset.bar = String(number);
}

export function hideCursor(ctx) {
  ctx.cursor?.remove();
  ctx.cursor = null;
  ctx.cursorSys = null;
  ctx.cursorMap = null;
}

/** Replace the set of elements carrying `cls` by those of `ids`. */
export function markNotes(ctx, cls, ids, previous) {
  const next = new Set(ids);
  if (previous) {
    for (const id of previous) {
      if (next.has(id)) continue;
      for (const el of ctx.notes.get(id) || []) el.classList.remove(cls);
    }
  } else {
    for (const el of ctx.container.querySelectorAll(`g.note.${cls}`)) el.classList.remove(cls);
  }
  for (const id of next) {
    for (const el of ctx.notes.get(id) || []) el.classList.add(cls);
  }
  return next;
}

/** Ids whose drawn note intersects a client-space rectangle. */
export function notesInRect(ctx, rect) {
  const out = [];
  for (const [id, els] of ctx.notes) {
    for (const el of els) {
      const target = el.querySelector(".sd-pill") || el.querySelector(".notehead") || el;
      const b = target.getBoundingClientRect();
      if (b.right >= rect.left && b.left <= rect.right && b.bottom >= rect.top && b.top <= rect.bottom) {
        out.push(id);
        break;
      }
    }
  }
  return out;
}
