// Score view: the same notes as a piano roll falling onto a keyboard
// ("notas cayendo"). Same player and clock as the score, so it sounds and
// moves exactly like it; only the picture changes.
//
// The geometry (keyboard, where each note falls) is pure and tested in node
// (tests/js/score-model.test.mjs); FallView only paints it on a canvas.

import { noteLabel, soundEnd } from "./model.js";

export const FULL_RANGE = [21, 108]; // A0..C8, the 88 keys
export const LOOKAHEAD_SEC = 4; // song seconds between a note appearing and its key
// «Notas a la vista»: how many seconds of the song the lane shows, 1-20. More
// seconds: the notes fall slower and closer together (more of what is coming
// is on screen); fewer: they fall faster, spread out (fast passages).
export const AHEAD_MIN = 1;
export const AHEAD_MAX = 20;
const AHEAD_STEPS = 100; // the slider's 0-100, on a log scale: 1 s to 2 s is as wide as 10 s to 20 s

/** Seconds within the range (a non-number is the default). */
export function clampAhead(sec) {
  const s = Number(sec);
  if (!Number.isFinite(s) || s <= 0) return LOOKAHEAD_SEC;
  return Math.min(AHEAD_MAX, Math.max(AHEAD_MIN, s));
}

/** The slider's position (0-100) for `sec`, and back. */
export function sliderFromAhead(sec) {
  return Math.round((AHEAD_STEPS * Math.log(clampAhead(sec) / AHEAD_MIN)) / Math.log(AHEAD_MAX / AHEAD_MIN));
}
export function aheadFromSlider(v) {
  const x = Math.min(AHEAD_STEPS, Math.max(0, Number(v) || 0)) / AHEAD_STEPS;
  return Math.round(AHEAD_MIN * (AHEAD_MAX / AHEAD_MIN) ** x * 10) / 10;
}

/** "4 s", "2,5 s": as the lane's label shows it. */
export function aheadLabel(sec) {
  const s = clampAhead(sec);
  return `${(s < 10 ? Math.round(s * 10) / 10 : Math.round(s)).toString().replace(".", ",")} s`;
}
const BLACK = new Set([1, 3, 6, 8, 10]);
// Where a black key sits over the boundary between its two white keys, as a
// fraction of a white key: C#/D# lean left/right of centre, F#/G#/A# likewise.
const BLACK_OFFSET = { 1: -0.1, 3: 0.1, 6: -0.12, 8: 0, 10: 0.12 };
const BLACK_WIDTH = 0.6; // of a white key
const REPEAT_GAP_SEC = 0.06; // a bar ends this long before its key is struck again
const MIN_BAR_SEC = 0.05;

export const isBlack = (midi) => BLACK.has(((midi % 12) + 12) % 12);

/** [lo, hi] of keys to draw: the 88 keys, or the song's own range widened to
 *  whole octaves (C to B), so every octave on screen is complete and starts
 *  on a labelled C. */
export function keyRange(notes, mode = "song") {
  if (mode === "full" || !notes.length) return [...FULL_RANGE];
  let lo = Infinity;
  let hi = -Infinity;
  for (const n of notes) {
    lo = Math.min(lo, n.midi);
    hi = Math.max(hi, n.midi);
  }
  lo = Math.max(FULL_RANGE[0], lo - (((lo % 12) + 12) % 12));
  hi = Math.min(FULL_RANGE[1], hi + (11 - (((hi % 12) + 12) % 12)));
  return [lo, hi];
}

/** Keys lo..hi with x and width in white-key units: [{midi, black, x, w}]. */
export function keyboard(lo, hi) {
  const keys = [];
  let white = 0;
  for (let m = lo; m <= hi; m++) {
    if (isBlack(m)) {
      const pc = m % 12;
      keys.push({ midi: m, black: true, x: white - BLACK_WIDTH / 2 + BLACK_OFFSET[pc], w: BLACK_WIDTH });
    } else {
      keys.push({ midi: m, black: false, x: white, w: 1 });
      white += 1;
    }
  }
  return { keys, whites: white, byMidi: new Map(keys.map((k) => [k.midi, k])) };
}

/** Octave name of a C key, as on the score's pitch names: C4 is middle C. */
export const octaveLabel = (midi) => `C${Math.floor(midi / 12) - 1}`;

/** note id -> start of the next strike of the same key (none: absent). */
export function nextStrikes(notes) {
  const byKey = new Map();
  for (const n of notes) {
    if (!byKey.has(n.midi)) byKey.set(n.midi, []);
    byKey.get(n.midi).push(n);
  }
  const out = new Map();
  for (const list of byKey.values()) {
    list.sort((a, b) => a.start - b.start);
    for (let i = 0; i + 1 < list.length; i++) out.set(list[i].id, list[i + 1].start);
  }
  return out;
}

/** Where a falling bar ends, and its key goes dark: the note as the score
 *  draws it, not as long as it rings. What sounds (the key as held, the
 *  pedal) runs longer: drawn that long, 65 % of the repeated keys of Porz
 *  Goret ran into their next strike as one column, and 5-7 keys stayed lit at
 *  once in an arpeggio. As drawn, the bars are about half as long and 3 keys
 *  are lit at a time. A bar also stops a moment before its key is struck
 *  again, so a repeated note reads as two. */
export function barEnd(n, next) {
  let end = soundEnd(n);
  if (next != null) end = Math.min(end, next - REPEAT_GAP_SEC);
  return Math.max(end, n.start + MIN_BAR_SEC);
}

/** Notes on screen at song time t, as falling bars: y is how far above the
 *  keys (0 = at the keys, 1 = top of the window). */
export function fallingBars(notes, t, next = new Map(), window = LOOKAHEAD_SEC) {
  const out = [];
  for (const n of notes) {
    const end = barEnd(n, next.get(n.id));
    if (end < t || n.start > t + window) continue;
    out.push({ note: n, y0: (n.start - t) / window, y1: (end - t) / window, sounding: n.start <= t && t < end });
  }
  return out;
}

// ── 3D: the lane seen in perspective ──
// A note u of the way to the far end (0 = at the keys, 1 = LOOKAHEAD_SEC
// ahead) is drawn at scale s(u) = 1 / (1 + FAR * u) around the middle of the
// screen, and as high above the keys as that scale has shrunk: far notes are
// small and slow, near ones large and quick, like See Music.
export const FAR = 1.15; // 1.7 crowded the far notes into the middle
export const depthScale = (u) => 1 / (1 + FAR * Math.max(0, u));

/** How bright a note is at depth u (3D): whole up to FADE_FROM, then
 *  fading to FADE_TO at the far end. */
export const FADE_FROM = 0.55;
export const FADE_TO = 0.35;
export const depthFade = (u) => (u <= FADE_FROM ? 1 : 1 - ((Math.min(1, u) - FADE_FROM) / (1 - FADE_FROM)) * (1 - FADE_TO));

/** Height above the keys (px) of depth u, for a lane fallH px tall. */
export function depthY(u, fallH) {
  const s1 = depthScale(1);
  return (fallH * (1 - depthScale(u))) / (1 - s1);
}

/** The inverse: depth u at dy px above the keys. */
export function depthAt(dy, fallH) {
  const s1 = depthScale(1);
  const s = 1 - (Math.max(0, dy) / fallH) * (1 - s1);
  return (1 / s - 1) / FAR;
}

const COLORS = {
  one: { bar: "#f5b417", lit: "#f5b417", text: "#1a1206", hi: "#ffe08a", lo: "#b77f06", glow: "245,180,23" },
  right: { bar: "#4f9dff", lit: "#4f9dff", text: "#ffffff", hi: "#a9cdff", lo: "#2a6ed1", glow: "79,157,255" },
  left: { bar: "#3ecf8e", lit: "#3ecf8e", text: "#0b1f16", hi: "#9cf0c9", lo: "#219461", glow: "62,207,142" },
};
export const HAND_COLORS = { R: COLORS.right.bar, L: COLORS.left.bar };

/** A bar's colours from one base colour (#rrggbb): lighter edge, darker
 *  side, its glow, and dark or white text, whichever reads on it. */
export function paletteFrom(hex) {
  const m = /^#?([0-9a-f]{6})$/i.exec(hex || "");
  if (!m) return null;
  const v = parseInt(m[1], 16);
  const rgb = [(v >> 16) & 255, (v >> 8) & 255, v & 255];
  const mix = (to, k) => `#${rgb.map((c) => Math.round(c + (to - c) * k).toString(16).padStart(2, "0")).join("")}`;
  const lum = (0.2126 * rgb[0] + 0.7152 * rgb[1] + 0.0722 * rgb[2]) / 255;
  return { bar: `#${m[1]}`, lit: `#${m[1]}`, text: lum > 0.6 ? "#111111" : "#ffffff", hi: mix(255, 0.45), lo: mix(0, 0.3), glow: rgb.join(",") };
}

/** The hand a bar is drawn in: the one the user set wins over the staff it
 *  was engraved on (an edit shows before the server's answer). */
export function handOf(note) {
  if (note.hand === "L" || note.hand === "R") return note.hand;
  return note.staff === 2 ? "L" : "R";
}

export function barColor(note, mode = "one", palette = null, paint = null) {
  if (mode !== "hands") return COLORS.one;
  const h = paint && paint.ids.has(note.id) ? paint.hand || handOf({ ...note, hand: null }) : handOf(note);
  if (h === "L") return palette?.L || COLORS.left;
  return palette?.R || COLORS.right;
}

export class FallView {
  constructor(host) {
    this.host = host;
    this.canvas = document.createElement("canvas");
    this.canvas.className = "sc-fall-canvas";
    host.appendChild(this.canvas);
    this.ctx = this.canvas.getContext("2d");
    this.notes = [];
    // lookahead: song seconds on screen above the keys (Anticipación);
    // dimStaff: the staff drawn faint and outlined dashed: the hand silenced
    // («Silenciar», the player plays it).
    this.opts = { keys: "song", colors: "one", names: "letters", style: "3d", lookahead: LOOKAHEAD_SEC, dimStaff: 0 };
    this.measures = []; // [{number, start, end, meter}]: bar lines across the lane
    this.loop = null; // {a, b, on}: the practice loop, marked on the lane
    this.pressed = new Map(); // midi -> "ok" | "wrong" | "": keys held on a MIDI keyboard
    this.waiting = null; // Set of keys the song waits for (MIDI keyboard «Esperarme»)
    this.sparks = []; // particles thrown up where a note hits its key
    this.sounding = new Set(); // ids sounding in the last frame, to spot new hits
    this.lastWall = 0;
    this.next = new Map();
    this.selection = new Set();
    // Experimental (app/experimental/sheet): note id -> {f: 1-5, src: "score" |
    // "user" | "auto"}, drawn on the bars and on the keys when present.
    this.fingers = null;
    this.preview = null; // {ids: Set, semis, sec}: notes being dragged
    this.palette = null; // {R, L}: the hands' colours when the user chose their own
    this.paint = null; // «Corregir manos»: {hand, ids} being painted
    this.marks = false; // dot on notes whose hand the user set
    this.hits = []; // [{id, x, y, w, h}] of the last frame, for taps
    this.size = { w: 0, h: 0 };
    new ResizeObserver(() => this.resize()).observe(host);
  }

  setNotes(notes) {
    this.notes = notes;
    this.next = nextStrikes(notes);
    this.layout = null;
    this.redraw(); // paused, the frame loop would not draw an edit
  }

  setMeasures(measures) {
    this.measures = measures || [];
    this.redraw();
  }

  setLoop(loop) {
    this.loop = loop;
    this.redraw();
  }

  /** Keys held on a MIDI keyboard (midi -> "ok" | "wrong" | ""), and the
   *  keys the song is waiting for. */
  setPressed(pressed, waiting = null) {
    this.pressed = pressed;
    this.waiting = waiting;
    this.redraw();
  }

  get lookahead() {
    return this.opts.lookahead || LOOKAHEAD_SEC;
  }

  /** Bar lines (and beat lines, fainter) between t and t + the lookahead:
   *  [{u, number, down}] with u 0 at the keys, 1 at the far end. */
  gridLines(t) {
    return gridLines(this.measures, t, this.lookahead);
  }

  setFingers(fingers) {
    this.fingers = fingers;
    this.redraw();
  }

  fingerOf(note) {
    return this.opts.fingers === false ? null : this.fingers?.[note.id] || null;
  }

  setSelection(ids) {
    this.selection = ids;
    this.redraw();
  }

  /** Bar colours of each hand ({R: "#rrggbb", L: ...}; null = defaults). */
  setHandColors(colors) {
    this.palette = colors ? { R: paletteFrom(colors.R) || COLORS.right, L: paletteFrom(colors.L) || COLORS.left } : null;
    this.redraw();
  }

  /** «Corregir manos»: notes being painted ({hand: "R"|"L"|null, ids: Set})
   *  are drawn in the hand they will get; `marks` shows which notes have a
   *  hand set by the user (a dot), only while painting. */
  setPaint(paint, marks = false) {
    this.paint = paint;
    this.marks = marks;
    this.redraw();
  }

  colorOf(note) {
    return barColor(note, this.opts.colors, this.palette, this.paint);
  }

  /** The notes along a stroke from one point to another (client
   *  coordinates), sampled every few pixels so a quick drag misses none. */
  hitsAlong(x0, y0, x1, y1) {
    const out = new Set();
    const steps = Math.max(1, Math.ceil(Math.hypot(x1 - x0, y1 - y0) / 4));
    for (let i = 0; i <= steps; i++) {
      const id = this.hitTest(x0 + ((x1 - x0) * i) / steps, y0 + ((y1 - y0) * i) / steps);
      if (id) out.add(id);
    }
    return out;
  }

  setPreview(preview) {
    this.preview = preview;
    this.redraw();
  }

  redraw() {
    if (this.lastT != null) this.draw(this.lastT);
  }

  /** The note under a point (client coordinates), black-key bars first, as
   *  they are drawn on top. */
  hitTest(clientX, clientY) {
    const r = this.canvas.getBoundingClientRect();
    const x = clientX - r.left;
    const y = clientY - r.top;
    for (let i = this.hits.length - 1; i >= 0; i--) {
      const h = this.hits[i];
      if (x >= h.x - 3 && x <= h.x + h.w + 3 && y >= h.y - 3 && y <= h.y + h.h + 3) return h.id;
    }
    return null;
  }

  /** The note whose start edge (the bar's bottom, nearest the keys) is under
   *  the pointer: drag it down onto the note before to join them. */
  edgeTest(clientX, clientY, band = 7) {
    const r = this.canvas.getBoundingClientRect();
    const x = clientX - r.left;
    const y = clientY - r.top;
    for (let i = this.hits.length - 1; i >= 0; i--) {
      const h = this.hits[i];
      // a short bar keeps most of its body for moving it
      const b = Math.min(band, Math.max(3, h.h / 3));
      if (x >= h.x - 2 && x <= h.x + h.w + 2 && Math.abs(y - (h.y + h.h)) <= b) return h.id;
    }
    return null;
  }

  /** The key and song time at a point (client coordinates) of the lane: in
   *  3D through the perspective; black keys win where they overlap whites,
   *  as their bars are drawn on top. Null off the lane or the keyboard. */
  pointAt(clientX, clientY) {
    if (!this.layout || this.lastT == null) return null;
    const r = this.canvas.getBoundingClientRect();
    const { w, h } = this.size;
    const fallH = this.laneHeight();
    const y = clientY - r.top;
    let x = clientX - r.left;
    if (y < 0 || y > fallH || x < 0 || x > w) return null;
    let u = (fallH - y) / fallH;
    if (this.opts.style === "3d") {
      u = depthAt(fallH - y, fallH);
      x = w / 2 + (x - w / 2) / depthScale(u);
    }
    const kx = x / (w / this.layout.whites);
    const keys = this.layout.keys;
    const key = keys.find((k) => k.black && kx >= k.x && kx < k.x + k.w) || keys.find((k) => !k.black && kx >= k.x && kx < k.x + k.w);
    if (!key) return null;
    return { midi: key.midi, sec: this.lastT + Math.max(0, u) * this.lookahead };
  }

  /** Pixels per semitone (average across the keyboard) and per song second. */
  scale() {
    const whites = this.layout?.whites || 52;
    return { perSemitone: (this.size.w / whites) * (7 / 12), perSecond: this.laneHeight() / this.lookahead };
  }

  /** Height of the lane the notes fall down (above the keys and, in
   *  «video», the felt strip). */
  laneHeight() {
    const keyH = this.keyHeight();
    return this.size.h - keyH - (this.opts.style === "video" ? videoFelt(keyH) : 0);
  }

  keyHeight() {
    if (this.opts.style === "video") return videoKeyHeight(this.size.w, this.size.h, this.layout?.whites || 52);
    return Math.min(170, Math.max(70, this.size.h * 0.2));
  }

  /** A drag from (x0, y0) to (x1, y1), client px, as semitones and song
   *  seconds: in 3D through the perspective (a far note moves less per px
   *  across and more per px along). */
  dragDelta(x0, y0, x1, y1) {
    const sc = this.scale();
    if (this.opts.style !== "3d") {
      return { semis: (x1 - x0) / sc.perSemitone, sec: -(y1 - y0) / sc.perSecond };
    }
    const r = this.canvas.getBoundingClientRect();
    const fallH = this.laneHeight();
    const u0 = depthAt(fallH - (y0 - r.top), fallH);
    const u1 = depthAt(fallH - (y1 - r.top), fallH);
    return { semis: (x1 - x0) / (sc.perSemitone * depthScale(u0)), sec: (u1 - u0) * this.lookahead };
  }

  setOptions(opts) {
    this.opts = { ...this.opts, ...opts };
    this.layout = null;
  }

  resize() {
    const r = this.host.getBoundingClientRect();
    const dpr = window.devicePixelRatio || 1;
    this.size = { w: r.width, h: r.height };
    this.canvas.width = Math.max(1, Math.round(r.width * dpr));
    this.canvas.height = Math.max(1, Math.round(r.height * dpr));
    this.canvas.style.width = `${r.width}px`;
    this.canvas.style.height = `${r.height}px`;
    this.ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    if (this.lastT != null) this.draw(this.lastT);
  }

  draw(t) {
    this.lastT = t;
    const { w, h } = this.size;
    if (!w || !h) return;
    if (!this.layout) {
      const [lo, hi] = keyRange(this.notes, this.opts.keys);
      this.layout = keyboard(lo, hi);
    }
    if (this.opts.style === "3d") return this.draw3d(t);
    if (this.opts.style === "video") return this.drawVideo(t);
    this.drawFlat(t);
  }

  /** Notes as shown: the ones being dragged where the drag puts them. */
  shownNotes() {
    const pv = this.preview;
    if (pv?.add) return [...this.notes, pv.add]; // a note being added
    if (pv?.start) {
      // Its start being dragged (the note keeps its end).
      return this.notes.map((n) => (n.id === pv.start.id ? { ...n, start: pv.start.at } : n));
    }
    return pv
      ? this.notes.map((n) => (pv.ids.has(n.id) ? { ...n, midi: n.midi + pv.semis, start: n.start + pv.sec, draw_end: (n.draw_end ?? n.end) + pv.sec } : n))
      : this.notes;
  }

  drawFlat(t) {
    const { w, h } = this.size;
    const { keys, whites, byMidi } = this.layout;
    const g = this.ctx;
    const unit = w / whites;
    const keyH = this.keyHeight();
    const fallH = h - keyH;

    g.fillStyle = "#101014";
    g.fillRect(0, 0, w, fallH);
    // Octaves: a faint band every other octave and a line on each C.
    for (const k of keys) {
      if (k.black || k.midi % 12 !== 0) continue;
      const x = k.x * unit;
      if (Math.floor(k.midi / 12) % 2 === 0) {
        g.fillStyle = "rgba(255,255,255,0.025)";
        g.fillRect(x, 0, 7 * unit, fallH);
      }
      g.fillStyle = "rgba(255,255,255,0.12)";
      g.fillRect(x, 0, 1, fallH);
    }
    // Bars and beats: a line across the lane where each starts, the bar's number.
    for (const l of this.gridLines(t)) {
      const y = fallH - l.u * fallH;
      g.fillStyle = l.down ? "rgba(255,255,255,0.22)" : "rgba(255,255,255,0.07)";
      g.fillRect(0, y, w, l.down ? 1.5 : 1);
      if (l.number != null) this.barNumber(g, l.number, 4, y - 3, 11);
    }
    this.drawLoopFlat(g, t, w, fallH);

    const bars = fallingBars(this.shownNotes(), t, this.next, this.lookahead);
    this.hits = [];
    const lit = new Map();
    g.textAlign = "center";
    g.textBaseline = "bottom";
    // White-key notes first, black-key notes on top, as on the keyboard.
    bars.sort((a, b) => isBlack(a.note.midi) - isBlack(b.note.midi));
    for (const b of bars) {
      const key = byMidi.get(b.note.midi);
      if (!key) continue;
      const color = this.colorOf(b.note);
      const x = key.x * unit + 1;
      const bw = Math.max(2, key.w * unit - 2);
      const yBottom = fallH - Math.max(0, b.y0) * fallH;
      const yTop = fallH - Math.min(1, b.y1) * fallH;
      const bh = Math.max(3, yBottom - yTop);
      g.fillStyle = color.bar;
      g.globalAlpha = (b.sounding ? 1 : 0.85) * this.fade(b.note);
      roundRect(g, x, yBottom - bh, bw, bh, Math.min(5, bw / 3));
      g.fill();
      g.globalAlpha = 1;
      if (this.muted(b.note)) mutedOutline(g, color);
      if (this.selection.has(b.note.id)) {
        g.strokeStyle = "#ffffff";
        g.lineWidth = 3;
        g.stroke();
      }
      if (this.marks && b.note.hand) handMark(g, x + bw / 2, yBottom - bh + 6, Math.min(4, bw / 4));
      this.hits.push({ id: b.note.id, x, y: yBottom - bh, w: bw, h: bh });
      const fing = this.fingerOf(b.note);
      let labelY = yBottom - 3;
      if (fing && bh > 10) {
        const r = Math.min(12, Math.max(7, bw * 0.42));
        fingerBadge(g, x + bw / 2, yBottom - r - 3, r, fing);
        labelY = yBottom - 2 * r - 6;
      }
      if (this.opts.names !== "none" && labelY - (yBottom - bh) > 12 && bw > 12) {
        const label = noteLabel(b.note, this.opts.names);
        g.textAlign = "center";
        g.textBaseline = "bottom";
        g.font = `600 ${Math.min(13, Math.max(9, bw * 0.45))}px Inter, system-ui, sans-serif`;
        g.fillStyle = color.text;
        g.fillText(label, x + bw / 2, labelY);
      }
      if (b.sounding) lit.set(b.note.midi, color.lit);
    }

    this.sounding = new Set(bars.filter((b) => b.sounding).map((b) => b.note.id));
    // The keyboard.
    g.fillStyle = "#3a3a42";
    g.fillRect(0, fallH, w, keyH);
    for (const k of keys) {
      if (k.black) continue;
      const x = k.x * unit;
      g.fillStyle = lit.get(k.midi) || "#f4f1ea";
      g.fillRect(x + 0.5, fallH + 2, unit - 1, keyH - 3);
      if (k.midi % 12 === 0) {
        g.fillStyle = lit.has(k.midi) ? "#1a1206" : "#6b6b74";
        g.font = `600 ${Math.min(13, Math.max(8, unit * 0.42))}px Inter, system-ui, sans-serif`;
        g.textBaseline = "bottom";
        g.fillText(octaveLabel(k.midi), x + unit / 2, fallH + keyH - 5);
      }
    }
    for (const k of keys) {
      if (!k.black) continue;
      g.fillStyle = lit.get(k.midi) || "#16161a";
      g.fillRect(k.x * unit, fallH + 2, k.w * unit, keyH * 0.62);
    }
    this.drawPressed(g, unit, fallH + 2, keyH);
    // The line the notes land on.
    g.fillStyle = "#e4572e";
    g.fillRect(0, fallH - 1, w, 2);
  }

  // ── Video: the proportions of a falling-notes video (Synthesia on YouTube) ──
  // A flat lane, notes as wide as their keys, a keyboard whose keys have a
  // real key's shape (a white key about 5.5 times as long as it is wide) at
  // about a fifth of the screen, a felt strip where the notes land. The 3D
  // lane and the plain one kept a 170 px keyboard whatever the screen: on a
  // full 1080p screen the keys were squat and the lane a tall empty column.
  drawVideo(t) {
    const { w, h } = this.size;
    const { keys, whites, byMidi } = this.layout;
    const g = this.ctx;
    const unit = w / whites;
    const keyH = this.keyHeight();
    const felt = videoFelt(keyH);
    const fallH = h - keyH - felt;
    const win = this.lookahead;
    const yOf = (sec) => fallH - ((sec - t) / win) * fallH;

    // The lane: near black, a little lighter towards the keys.
    const bg = g.createLinearGradient(0, 0, 0, fallH);
    bg.addColorStop(0, "#0b0c10");
    bg.addColorStop(1, "#16181f");
    g.fillStyle = bg;
    g.fillRect(0, 0, w, fallH);
    // A line between B and C and between E and F, as on the videos: the
    // octaves (and the two groups of black keys) readable at a glance.
    for (const k of keys) {
      if (k.black || (k.midi % 12 !== 0 && k.midi % 12 !== 5)) continue;
      g.fillStyle = k.midi % 12 === 0 ? "rgba(255,255,255,0.10)" : "rgba(255,255,255,0.045)";
      g.fillRect(Math.round(k.x * unit), 0, 1, fallH);
    }
    for (const l of this.gridLines(t)) {
      const y = Math.round(fallH - l.u * fallH);
      g.fillStyle = l.down ? "rgba(255,255,255,0.14)" : "rgba(255,255,255,0.04)";
      g.fillRect(0, y, w, 1);
      if (l.number != null) this.barNumber(g, l.number, 6, y - 3, Math.max(10, Math.min(13, unit * 0.4)));
    }
    this.drawLoopFlat(g, t, w, fallH);

    // The notes: white-key notes first, black-key ones over them, narrower.
    const bars = fallingBars(this.shownNotes(), t, this.next, win);
    bars.sort((a, b) => isBlack(a.note.midi) - isBlack(b.note.midi));
    this.hits = [];
    const lit = new Map();
    const litNote = new Map();
    for (const b of bars) {
      const key = byMidi.get(b.note.midi);
      if (!key) continue;
      const color = this.colorOf(b.note);
      const kw = key.w * unit;
      const bw = Math.max(3, key.black ? kw * 0.92 : kw * 0.84);
      const x = key.x * unit + (kw - bw) / 2;
      const yBottom = Math.min(fallH, yOf(b.note.start));
      const yTop = Math.max(-8, yOf(barEnd(b.note, this.next.get(b.note.id))));
      const bh = Math.max(4, yBottom - yTop);
      const r = Math.min(6, bw / 3, bh / 2);
      g.globalAlpha = this.fade(b.note);
      const body = g.createLinearGradient(x, 0, x + bw, 0);
      body.addColorStop(0, color.hi);
      body.addColorStop(0.25, color.bar);
      body.addColorStop(1, color.lo);
      g.fillStyle = body;
      roundRect(g, x, yBottom - bh, bw, bh, r);
      g.fill();
      if (this.muted(b.note)) {
        g.globalAlpha = 1;
        mutedOutline(g, color);
        g.globalAlpha = this.fade(b.note);
      } else {
        g.strokeStyle = b.sounding ? "rgba(255,255,255,0.85)" : "rgba(0,0,0,0.35)";
        g.lineWidth = b.sounding ? 1.5 : 1;
        g.stroke();
      }
      if (this.selection.has(b.note.id)) {
        g.strokeStyle = "#ffffff";
        g.lineWidth = 3;
        g.stroke();
      }
      if (this.marks && b.note.hand) handMark(g, x + bw / 2, yBottom - bh + 6, Math.min(4, bw / 4));
      g.globalAlpha = 1;
      this.hits.push({ id: b.note.id, x, y: yBottom - bh, w: bw, h: bh });
      const fing = this.fingerOf(b.note);
      let labelY = yBottom - 4;
      if (fing && bh > 14) {
        const rr = Math.min(12, Math.max(7, bw * 0.4));
        fingerBadge(g, x + bw / 2, yBottom - rr - 4, rr, fing);
        labelY = yBottom - 2 * rr - 8;
      }
      const size = Math.min(14, Math.max(8, bw * 0.5));
      if (this.opts.names !== "none" && labelY - (yBottom - bh) > size + 2 && bw > 10) {
        g.font = `700 ${size}px Inter, system-ui, sans-serif`;
        g.textAlign = "center";
        g.textBaseline = "bottom";
        g.fillStyle = color.text;
        g.fillText(noteLabel(b.note, this.opts.names), x + bw / 2, labelY);
      }
      if (b.sounding) {
        lit.set(b.note.midi, color);
        litNote.set(b.note.midi, b.note);
      }
    }
    this.sounding = new Set(bars.filter((b) => b.sounding).map((b) => b.note.id));

    // Where the notes land: a felt strip, glowing over the keys that sound.
    const top = fallH + felt;
    const strip = g.createLinearGradient(0, fallH, 0, top);
    strip.addColorStop(0, "#5c1416");
    strip.addColorStop(1, "#a32a2a");
    g.fillStyle = strip;
    g.fillRect(0, fallH, w, felt);
    g.globalCompositeOperation = "lighter";
    for (const [m, color] of lit) {
      const k = byMidi.get(m);
      const cx = (k.x + k.w / 2) * unit;
      const glow = g.createRadialGradient(cx, fallH, 0, cx, fallH, unit * 1.6);
      glow.addColorStop(0, `rgba(${color.glow},0.75)`);
      glow.addColorStop(1, `rgba(${color.glow},0)`);
      g.fillStyle = glow;
      g.fillRect(cx - unit * 1.6, fallH - unit * 1.6, unit * 3.2, unit * 1.6 + felt);
    }
    g.globalCompositeOperation = "source-over";

    // The keyboard: white keys with a gap between them and a shaded front,
    // black keys 0.63 of their length, glossy; a key that sounds takes its
    // note's colour.
    g.fillStyle = "#0d0d10";
    g.fillRect(0, top, w, keyH);
    const gap = Math.max(1, unit * 0.05);
    for (const k of keys) {
      if (k.black) continue;
      const x = k.x * unit;
      const c = lit.get(k.midi);
      const face = g.createLinearGradient(0, top, 0, top + keyH);
      face.addColorStop(0, c ? c.hi : "#f2f0eb");
      face.addColorStop(0.85, c ? c.bar : "#ffffff");
      face.addColorStop(1, c ? c.lo : "#c9c5bd");
      g.fillStyle = face;
      roundRect(g, x + gap / 2, top, unit - gap, keyH - 1, Math.min(4, unit * 0.12));
      g.fill();
      if (k.midi % 12 === 0) {
        g.fillStyle = c ? "#1a1206" : "#8b8794";
        g.font = `600 ${Math.min(13, Math.max(8, unit * 0.36))}px Inter, system-ui, sans-serif`;
        g.textAlign = "center";
        g.textBaseline = "bottom";
        g.fillText(octaveLabel(k.midi), x + unit / 2, top + keyH - 6);
      }
    }
    const bh = keyH * 0.63;
    for (const k of keys) {
      if (!k.black) continue;
      const x = k.x * unit;
      const bw = k.w * unit;
      const c = lit.get(k.midi);
      g.fillStyle = "rgba(0,0,0,0.45)"; // its shadow on the white keys
      g.fillRect(x + bw * 0.12, top, bw, bh + 3);
      const face = g.createLinearGradient(x, 0, x + bw, 0);
      face.addColorStop(0, c ? c.lo : "#050506");
      face.addColorStop(0.5, c ? c.bar : "#2a2a30");
      face.addColorStop(1, c ? c.lo : "#050506");
      g.fillStyle = face;
      roundRect(g, x, top - 1, bw, bh, Math.min(3, bw * 0.15));
      g.fill();
      g.fillStyle = c ? "rgba(255,255,255,0.35)" : "rgba(255,255,255,0.14)"; // the shine near its front
      g.fillRect(x + bw * 0.2, top + bh - bh * 0.12, bw * 0.6, Math.max(2, bh * 0.05));
    }
    this.drawPressed(g, unit, top, keyH);
    // The name on each key that sounds (the falling bar may be too short).
    if (this.opts.names !== "none") {
      g.textAlign = "center";
      g.textBaseline = "middle";
      g.font = `800 ${Math.min(14, Math.max(9, unit * 0.4))}px Inter, system-ui, sans-serif`;
      for (const [m, note] of litNote) {
        const k = byMidi.get(m);
        if (!k || this.fingerOf(note)) continue;
        const cx = (k.x + k.w / 2) * unit;
        g.fillStyle = k.black ? "#ffffff" : "#1a1206";
        g.fillText(noteLabel(note, this.opts.names), cx, k.black ? top + bh * 0.72 : top + keyH * 0.78);
      }
    }
  }

  /** How strongly a note is drawn: faint on the silenced hand (dimStaff). */
  fade(note) {
    return this.muted(note) ? 0.32 : 1;
  }

  /** On the silenced hand («Silenciar»): it does not sound, the player plays it. */
  muted(note) {
    const staff = note.staff === 2 || (note.staff == null && note.hand === "L") ? 2 : 1;
    return !!this.opts.dimStaff && staff === this.opts.dimStaff;
  }

  barNumber(g, number, x, y, size) {
    g.font = `600 ${size}px Inter, system-ui, sans-serif`;
    g.textAlign = "left";
    g.textBaseline = "bottom";
    g.fillStyle = "rgba(255,255,255,0.45)";
    g.fillText(String(number), x, y);
  }

  drawLoopFlat(g, t, w, fallH) {
    const L = this.loop;
    if (!L || !(L.b > L.a)) return;
    const win = this.lookahead;
    const y = (sec) => fallH - ((sec - t) / win) * fallH;
    const top = Math.max(0, y(L.b));
    const bottom = Math.min(fallH, y(L.a));
    if (bottom > top) {
      g.fillStyle = L.on ? "rgba(245,180,23,0.07)" : "rgba(255,255,255,0.03)";
      g.fillRect(0, top, w, bottom - top);
    }
    for (const [sec, label] of [[L.a, "A"], [L.b, "B"]]) {
      const yy = y(sec);
      if (yy < 0 || yy > fallH) continue;
      g.fillStyle = L.on ? "#f5b417" : "rgba(245,180,23,0.5)";
      g.fillRect(0, yy - 1, w, 2);
      g.font = "800 12px Inter, system-ui, sans-serif";
      g.textAlign = "right";
      g.textBaseline = "bottom";
      g.fillText(label, w - 6, yy - 3);
    }
  }

  /** Keys held on a MIDI keyboard: a band on each (green when it is a note
   *  of the song, red when not, white in free play), and a dashed outline on
   *  the keys the song waits for. */
  drawPressed(g, unit, top, keyH) {
    const { byMidi } = this.layout;
    if (this.waiting?.size) {
      g.strokeStyle = "rgba(245,180,23,0.95)";
      g.lineWidth = 3;
      g.setLineDash([5, 4]);
      for (const m of this.waiting) {
        const k = byMidi.get(m);
        if (!k || this.pressed.has(m)) continue;
        const h = k.black ? keyH * 0.6 : keyH - 4;
        g.strokeRect(k.x * unit + 2, top + 1, k.w * unit - 4, h - 2);
      }
      g.setLineDash([]);
      g.lineWidth = 1;
    }
    for (const [m, kind] of this.pressed) {
      const k = byMidi.get(m);
      if (!k) continue;
      const h = k.black ? keyH * 0.6 : keyH - 4;
      g.fillStyle = kind === "wrong" ? "rgba(240,80,110,0.6)" : kind === "ok" ? "rgba(62,207,142,0.6)" : "rgba(255,255,255,0.4)";
      g.fillRect(k.x * unit + 1, top + h * 0.45, k.w * unit - 2, h * 0.55);
    }
  }

  // ── 3D ──────────────────────────────────────────────────────────────────
  draw3d(t) {
    const { w, h } = this.size;
    const { keys, whites, byMidi } = this.layout;
    const g = this.ctx;
    const unit = w / whites;
    const keyH = this.keyHeight();
    const fallH = h - keyH;
    const cx = w / 2;
    const X = (x, u) => cx + (x - cx) * depthScale(u); // a flat x seen at depth u
    const Y = (u) => fallH - depthY(u, fallH);

    // Sky: deep blue-black, a soft horizon glow, octave lanes converging.
    const sky = g.createLinearGradient(0, 0, 0, fallH);
    sky.addColorStop(0, "#07070d");
    sky.addColorStop(0.55, "#0d0f1c");
    sky.addColorStop(1, "#171a2c");
    g.fillStyle = sky;
    g.fillRect(0, 0, w, fallH);
    const horizon = g.createRadialGradient(cx, Y(1), 0, cx, Y(1), w * 0.45);
    horizon.addColorStop(0, "rgba(120,140,255,0.16)");
    horizon.addColorStop(1, "rgba(120,140,255,0)");
    g.fillStyle = horizon;
    g.fillRect(0, 0, w, fallH);
    g.lineWidth = 1;
    for (const k of keys) {
      if (k.black || k.midi % 12 !== 0) continue;
      const x = k.x * unit;
      g.strokeStyle = "rgba(160,170,255,0.13)";
      g.beginPath();
      g.moveTo(X(x, 0), fallH);
      g.lineTo(X(x, 1), Y(1));
      g.stroke();
    }
    // Floor lines across the lane on every beat, brighter on each bar with its
    // number (every second when the song has no bars), receding. They were
    // one a second, which says nothing about the music's rhythm.
    const lines = this.gridLines(t);
    if (!this.measures.length) {
      for (let sec = Math.ceil(t); sec < t + this.lookahead; sec++) lines.push({ u: (sec - t) / this.lookahead, down: false, number: null });
    }
    for (const l of lines) {
      g.strokeStyle = l.down ? "rgba(190,200,255,0.26)" : "rgba(160,170,255,0.08)";
      g.lineWidth = l.down ? 1.5 : 1;
      g.beginPath();
      g.moveTo(X(0, l.u), Y(l.u));
      g.lineTo(X(w, l.u), Y(l.u));
      g.stroke();
      if (l.number != null) this.barNumber(g, l.number, X(0, l.u) + 4, Y(l.u) - 2, Math.max(8, Math.round(12 * depthScale(l.u))));
    }
    g.lineWidth = 1;
    // The practice loop: its two ends across the lane, the span between tinted.
    const L = this.loop;
    if (L && L.b > L.a) {
      const ua = (L.a - t) / this.lookahead;
      const ub = (L.b - t) / this.lookahead;
      if (ub > 0 && ua < 1) {
        const u0 = Math.max(0, ua);
        const u1 = Math.min(1, ub);
        g.fillStyle = L.on ? "rgba(245,180,23,0.07)" : "rgba(255,255,255,0.03)";
        quad(g, X(0, u0), Y(u0), X(w, u0), Y(u0), X(w, u1), Y(u1), X(0, u1), Y(u1));
        g.fill();
      }
      for (const [u, label] of [[ua, "A"], [ub, "B"]]) {
        if (u < 0 || u > 1) continue;
        const c = L.on ? "#f5b417" : "rgba(245,180,23,0.5)";
        g.strokeStyle = c;
        g.lineWidth = 2;
        g.beginPath();
        g.moveTo(X(0, u), Y(u));
        g.lineTo(X(w, u), Y(u));
        g.stroke();
        g.lineWidth = 1;
        g.fillStyle = c;
        g.font = "800 12px Inter, system-ui, sans-serif";
        g.textAlign = "right";
        g.textBaseline = "bottom";
        g.fillText(label, X(w, u) - 6, Y(u) - 3);
      }
    }

    // Falling notes, far ones first so near ones cover them.
    const bars = fallingBars(this.shownNotes(), t, this.next, this.lookahead);
    bars.sort((a, b) => b.y0 - a.y0 || isBlack(a.note.midi) - isBlack(b.note.midi));
    this.hits = [];
    const lit = new Map();
    const litFinger = new Map(); // midi -> finger of the note sounding on it
    const litName = new Map(); // midi -> the note sounding on it (its name on the key)
    const nowSounding = new Set();
    for (const b of bars) {
      const key = byMidi.get(b.note.midi);
      if (!key) continue;
      const color = this.colorOf(b.note);
      const u0 = Math.max(0, b.y0);
      const u1 = Math.min(1, b.y1);
      const x0 = key.x * unit + 1.5;
      const x1 = x0 + Math.max(2, key.w * unit - 3);
      const yb = Y(u0);
      const yt = Math.min(Y(u1), yb - 3);
      const bl = X(x0, u0), br = X(x1, u0), tl = X(x0, u1), tr = X(x1, u1);
      // Glow under the sounding ones.
      if (b.sounding) {
        g.fillStyle = `rgba(${color.glow},0.28)`;
        quad(g, bl - 6, yb + 2, br + 6, yb + 2, tr + 4, yt - 4, tl - 4, yt - 4);
        g.fill();
      }
      // The block: lit from the left, a lighter cap on top, a darker side.
      const grad = g.createLinearGradient(bl, 0, br, 0);
      grad.addColorStop(0, color.hi);
      grad.addColorStop(0.35, color.bar);
      grad.addColorStop(1, color.lo);
      g.fillStyle = grad;
      // Far off, the perspective squeezes the time ~5 times: short notes
      // there are thin dashes piled up. They come in faint and brighten as
      // they near, so the near ones (the ones to play) stand out.
      const far = depthFade(u0);
      g.globalAlpha = (b.sounding ? 1 : 0.92) * this.fade(b.note) * far;
      quad(g, bl, yb, br, yb, tr, yt, tl, yt);
      g.fill();
      g.globalAlpha = far;
      if (this.muted(b.note)) mutedOutline(g, color);
      const capH = Math.max(2, (yb - yt) > 10 ? 3 * depthScale(u1) + 1 : 1);
      g.fillStyle = "rgba(255,255,255,0.45)";
      quad(g, tl, yt + capH, tr, yt + capH, tr, yt, tl, yt);
      g.fill();
      g.globalAlpha = 1;
      if (this.selection.has(b.note.id)) {
        g.strokeStyle = "#ffffff";
        g.lineWidth = 3;
        quad(g, bl, yb, br, yb, tr, yt, tl, yt);
        g.stroke();
      }
      if (this.marks && b.note.hand) handMark(g, (tl + tr) / 2, yt + 6, Math.min(4, (tr - tl) / 4));
      const left = Math.min(bl, tl), right = Math.max(br, tr);
      this.hits.push({ id: b.note.id, x: left, y: yt, w: right - left, h: yb - yt });
      const bw = br - bl;
      const fing = this.fingerOf(b.note);
      let labelY = yb - 3;
      if (fing && yb - yt > 10) {
        const r = Math.min(13, Math.max(7, bw * 0.42));
        fingerBadge(g, (bl + br) / 2, yb - r - 3, r, fing);
        labelY = yb - 2 * r - 6;
      }
      const size = Math.min(14, Math.max(8, bw * 0.45));
      if (this.opts.names !== "none" && labelY - yt > size + 1 && bw > 9) {
        g.textAlign = "center";
        g.textBaseline = "bottom";
        g.font = `700 ${size}px Inter, system-ui, sans-serif`;
        g.fillStyle = color.text;
        g.fillText(noteLabel(b.note, this.opts.names), (bl + br) / 2, labelY);
      }
      if (b.sounding) {
        lit.set(b.note.midi, color);
        if (fing) litFinger.set(b.note.midi, fing);
        else litName.set(b.note.midi, b.note);
        nowSounding.add(b.note.id);
      }
    }

    // Sparks where a note has just landed, flying up and fading.
    const wall = performance.now();
    const dt = Math.min(0.05, Math.max(0, (wall - (this.lastWall || wall)) / 1000));
    this.lastWall = wall;
    for (const b of bars) {
      if (!b.sounding || this.sounding.has(b.note.id) || b.y0 < -0.06) continue;
      const key = byMidi.get(b.note.midi);
      if (!key) continue;
      const color = this.colorOf(b.note);
      const x = (key.x + key.w / 2) * unit;
      for (let i = 0; i < 14 && this.sparks.length < 400; i++) {
        const a = -Math.PI / 2 + (Math.random() - 0.5) * 1.6;
        const v = 90 + Math.random() * 220;
        this.sparks.push({ x: x + (Math.random() - 0.5) * unit * 0.6, y: fallH - 2, vx: Math.cos(a) * v, vy: Math.sin(a) * v, life: 1, decay: 1.4 + Math.random() * 1.2, rgb: color.glow, r: 1 + Math.random() * 2 });
      }
    }
    this.sounding = nowSounding;
    g.globalCompositeOperation = "lighter";
    for (const p of this.sparks) {
      p.x += p.vx * dt;
      p.y += p.vy * dt;
      p.vy += 420 * dt; // gravity
      p.life -= p.decay * dt;
      if (p.life <= 0) continue;
      g.fillStyle = `rgba(${p.rgb},${p.life.toFixed(3)})`;
      g.beginPath();
      g.arc(p.x, p.y, p.r * (0.5 + p.life), 0, Math.PI * 2);
      g.fill();
    }
    this.sparks = this.sparks.filter((p) => p.life > 0 && p.y < h);
    // The impact line: a glow, brighter over the keys that sound.
    const line = g.createLinearGradient(0, fallH - 10, 0, fallH + 2);
    line.addColorStop(0, "rgba(255,120,80,0)");
    line.addColorStop(1, "rgba(255,120,80,0.55)");
    g.fillStyle = line;
    g.fillRect(0, fallH - 10, w, 12);
    for (const [m, color] of lit) {
      const key = byMidi.get(m);
      const x = (key.x + key.w / 2) * unit;
      const flare = g.createRadialGradient(x, fallH, 0, x, fallH, unit * 2.2);
      flare.addColorStop(0, `rgba(${color.glow},0.85)`);
      flare.addColorStop(1, `rgba(${color.glow},0)`);
      g.fillStyle = flare;
      g.fillRect(x - unit * 2.2, fallH - unit * 2.2, unit * 4.4, unit * 2.6);
    }
    g.globalCompositeOperation = "source-over";

    // The keyboard: white keys with a front edge, black keys raised; a key
    // that sounds goes down a little and takes the note's colour.
    const front = Math.max(6, keyH * 0.1);
    const top = fallH + 1;
    g.fillStyle = "#1b1b22";
    g.fillRect(0, fallH, w, keyH);
    for (const k of keys) {
      if (k.black) continue;
      const x = k.x * unit;
      const c = lit.get(k.midi);
      const down = c ? 2 : 0;
      const face = g.createLinearGradient(0, top, 0, top + keyH - front);
      face.addColorStop(0, c ? c.hi : "#ffffff");
      face.addColorStop(1, c ? c.bar : "#e7e3da");
      g.fillStyle = face;
      g.fillRect(x + 0.5, top + down, unit - 1, keyH - front - 1);
      g.fillStyle = c ? c.lo : "#b9b4a8"; // front edge
      g.fillRect(x + 0.5, top + down + keyH - front - 1, unit - 1, front - down);
      if (k.midi % 12 === 0) {
        g.fillStyle = c ? "#1a1206" : "#77737f";
        g.font = `600 ${Math.min(13, Math.max(8, unit * 0.42))}px Inter, system-ui, sans-serif`;
        g.textAlign = "center";
        g.textBaseline = "bottom";
        g.fillText(octaveLabel(k.midi), x + unit / 2, top + keyH - front - 5);
      }
    }
    for (const k of keys) {
      if (!k.black) continue;
      const x = k.x * unit;
      const bw = k.w * unit;
      const bh = keyH * 0.6;
      const c = lit.get(k.midi);
      const down = c ? 2 : 0;
      g.fillStyle = "rgba(0,0,0,0.35)"; // shadow on the white keys
      g.fillRect(x + 2, top, bw, bh + 4);
      const face = g.createLinearGradient(0, top, 0, top + bh);
      face.addColorStop(0, c ? c.bar : "#2b2b33");
      face.addColorStop(1, c ? c.lo : "#0c0c10");
      g.fillStyle = face;
      g.fillRect(x, top + down, bw, bh - down);
      g.fillStyle = c ? c.hi : "rgba(255,255,255,0.12)"; // highlight on its front
      g.fillRect(x + bw * 0.15, top + down + bh - 7, bw * 0.7, 3);
    }
    this.drawPressed(g, unit, top, keyH);
    // The name on each key that sounds (far bars are too thin for it), unless
    // its finger goes there.
    if (this.opts.names !== "none") {
      g.textAlign = "center";
      g.textBaseline = "middle";
      g.font = `800 ${Math.min(14, Math.max(9, unit * 0.42))}px Inter, system-ui, sans-serif`;
      for (const [m, note] of litName) {
        const k = byMidi.get(m);
        if (!k) continue;
        const x = (k.x + k.w / 2) * unit;
        const y = k.black ? top + keyH * 0.42 : top + keyH * 0.7;
        g.fillStyle = k.black ? "#ffffff" : "#1a1206";
        g.fillText(noteLabel(note, this.opts.names), x, y);
      }
    }
    // The finger on each key that sounds.
    for (const [m, fing] of litFinger) {
      const k = byMidi.get(m);
      if (!k) continue;
      const r = Math.min(12, Math.max(7, unit * 0.36));
      const x = (k.x + k.w / 2) * unit;
      const y = k.black ? top + keyH * 0.6 - r - 8 : top + keyH * 0.72;
      fingerBadge(g, x, y, r, fing);
    }
  }
}

export const videoFelt = (keyH) => Math.max(3, Math.round(keyH * 0.035));

/** The keyboard's height in the «video» proportions: a white key about 5.5
 *  times as long as it is wide (a real key is 23 x 150 mm; the videos draw it
 *  a little shorter), kept between 12 % and 22 % of the screen -- 88 keys on
 *  a 1920 x 1080 screen: 37 px keys, a 203 px keyboard (19 %). */
export function videoKeyHeight(w, h, whites) {
  const unit = w / Math.max(1, whites);
  return Math.round(Math.max(h * 0.12, Math.min(h * 0.22, unit * 5.5)));
}

/** Bar lines (and beat lines) between t and t + win: [{u, number, down}],
 *  u 0 at the keys and 1 at the far end; number only on a bar's first beat. */
export function gridLines(measures, t, win = LOOKAHEAD_SEC) {
  const out = [];
  for (const m of measures) {
    if (m.end < t) continue;
    if (m.start > t + win) break;
    const n = Math.max(1, m.meter || 4);
    const span = (m.end - m.start) / n;
    for (let k = 0; k < n; k++) {
      const at = m.start + k * span;
      if (at < t || at > t + win) continue;
      out.push({ u: (at - t) / win, number: k === 0 ? m.number : null, down: k === 0 });
    }
  }
  return out;
}

/** The dot on a note whose hand the user set («Corregir manos»). */
function handMark(g, x, y, r) {
  if (r < 1.5) return;
  g.beginPath();
  g.arc(x, y, r, 0, Math.PI * 2);
  g.fillStyle = "#ffffff";
  g.fill();
  g.lineWidth = 1;
  g.strokeStyle = "rgba(0,0,0,0.55)";
  g.stroke();
}

/** The outline of a note on the silenced hand: dashed, in the hand's colour
 *  (the current path is the bar). Faint fill + dashes = "not sounding". */
function mutedOutline(g, color) {
  g.save();
  g.setLineDash([5, 4]);
  g.lineWidth = 1.5;
  g.strokeStyle = color.hi || color.bar;
  g.stroke();
  g.restore();
}

/** A finger number in a disc: white when printed on the score or set by hand
 *  (a gold ring when by hand), grey when only suggested. */
function fingerBadge(g, x, y, r, fing) {
  const suggested = fing.src === "auto";
  g.beginPath();
  g.arc(x, y, r, 0, Math.PI * 2);
  g.fillStyle = suggested ? "rgba(70,70,82,0.92)" : "#ffffff";
  g.fill();
  g.lineWidth = fing.src === "user" ? 2.5 : 1;
  g.strokeStyle = fing.src === "user" ? "#f5b417" : suggested ? "rgba(255,255,255,0.35)" : "rgba(0,0,0,0.35)";
  g.stroke();
  g.fillStyle = suggested ? "#e8e8ee" : "#111111";
  g.font = `800 ${Math.round(r * 1.25)}px Inter, system-ui, sans-serif`;
  g.textAlign = "center";
  g.textBaseline = "middle";
  g.fillText(String(fing.f), x, y + 0.5);
}

function quad(g, x1, y1, x2, y2, x3, y3, x4, y4) {
  g.beginPath();
  g.moveTo(x1, y1);
  g.lineTo(x2, y2);
  g.lineTo(x3, y3);
  g.lineTo(x4, y4);
  g.closePath();
}

function roundRect(g, x, y, w, h, r) {
  g.beginPath();
  g.moveTo(x + r, y);
  g.arcTo(x + w, y, x + w, y + h, r);
  g.arcTo(x + w, y + h, x, y + h, r);
  g.arcTo(x, y + h, x, y, r);
  g.arcTo(x, y, x + w, y, r);
  g.closePath();
}
