// The lane of «🎷 Saxo»: the line travelling right to left along a treble
// staff (written for the chosen saxophone) into the hit line by the
// saxophone. Each note a glowing bar in its pitch colour, its name on it,
// ledger lines where it needs them, a breath mark in the rests, sparks
// thrown back toward the horn while a note sounds.

import { beatIndexAt } from "./beats.js";
import { noteName, staffStep, written } from "./melody.js";

// One colour for the notes coming and gold for the one sounding (as the
// strip above and the fingering chart): a colour per pitch made the lane a
// rainbow to decode; what matters is which note is now. Its height on the
// staff and its name say which note it is.
const tone = (sounding, light) => (sounding ? `hsl(41, 92%, ${light}%)` : `hsl(224, 78%, ${light}%)`);

const MIN_STEP = -6; // A3 (below the low Bb, ledger room)
const MAX_STEP = 17; // A6
export const HIT_X = 64; // css px from the lane's left edge

export class SaxLane {
  constructor(canvas) {
    this.canvas = canvas;
    this.ctx = canvas.getContext("2d");
    this.notes = [];
    this.breaths = [];
    this.sax = "alto";
    this.names = "solfege";
    this.lookahead = 5;
    this.sparks = [];
    this.lastT = 0;
    this.lastNow = 0;
    this.size = { w: 1, h: 1 };
    this.hits = []; // [{id, x, y, w, h}] last drawn: tests, taps
    this.selected = null; // «✏️ Editar»: the key of the note picked
    this.selectedMore = new Set(); // ...and of the others picked with it
    this.band = null; // a box being dragged to pick several: {x0, y0, x1, y1}
    this.bars = null; // the song's beats and bars (beats.js barGrid), or none
    this.barMarks = []; // [{x, bar}] the bar lines last drawn: tests
    this.loop = null; // «Bucle»: {a, b} s, or none
    this.you = null; // «🎤 Practicar»: {midi (as shown), state: ok|near|off, trail: [{age s, midi}]}
  }

  set(notes, { sax, names, breaths, lookahead, concert } = {}) {
    this.notes = notes;
    if (concert !== undefined) this.concert = concert;
    if (sax) this.sax = sax;
    if (names) this.names = names;
    if (breaths) this.breaths = breaths;
    if (lookahead) this.lookahead = lookahead;
  }

  resize() {
    const r = this.canvas.getBoundingClientRect();
    const dpr = window.devicePixelRatio || 1;
    this.size = { w: Math.max(1, r.width), h: Math.max(1, r.height) };
    this.canvas.width = Math.round(this.size.w * dpr);
    this.canvas.height = Math.round(this.size.h * dpr);
    this.ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  }

  /** Half the distance between two staff lines, and the y of a step. */
  geometry() {
    const { h } = this.size;
    const pad = 18;
    const hs = (h - 2 * pad) / (MAX_STEP - MIN_STEP);
    return { hs, y: (step) => h - pad - (step - MIN_STEP) * hs };
  }

  draw(t, playing = false) {
    const ctx = this.ctx;
    const { w, h } = this.size;
    const now = performance.now();
    const dt = Math.min(0.1, (now - this.lastNow) / 1000 || 0);
    this.lastNow = now;
    const { hs, y } = this.geometry();
    const pps = (w - HIT_X) / this.lookahead;
    const xOf = (sec) => HIT_X + (sec - t) * pps;

    // Night stage, a slow glow behind the staff.
    const bg = ctx.createLinearGradient(0, 0, w, h);
    bg.addColorStop(0, "#0b0f1d");
    bg.addColorStop(1, "#161226");
    ctx.fillStyle = bg;
    ctx.fillRect(0, 0, w, h);
    const glow = ctx.createRadialGradient(HIT_X, h / 2, 10, HIT_X, h / 2, w * 0.6);
    glow.addColorStop(0, "rgba(255, 190, 80, 0.10)");
    glow.addColorStop(1, "rgba(255, 190, 80, 0)");
    ctx.fillStyle = glow;
    ctx.fillRect(0, 0, w, h);

    this.barMarks = [];
    if (this.bars) {
      // The song's rhythm: a faint line at each beat, a clearer one where a
      // bar starts, with its number (the time, read as on a score).
      const g = this.bars;
      ctx.font = "700 11px Inter, sans-serif";
      ctx.textAlign = "left";
      ctx.textBaseline = "top";
      for (let i = Math.max(0, beatIndexAt(g.times, t)); i < g.times.length; i++) {
        const sec = g.times[i];
        if (sec > t + this.lookahead) break;
        if (sec < t) continue;
        const x = Math.round(xOf(sec)) + 0.5;
        ctx.strokeStyle = g.down[i] ? "rgba(200, 215, 255, 0.22)" : "rgba(255, 255, 255, 0.055)";
        ctx.lineWidth = g.down[i] ? 1.5 : 1;
        ctx.beginPath();
        ctx.moveTo(x, 0);
        ctx.lineTo(x, h);
        ctx.stroke();
        if (g.down[i]) {
          ctx.fillStyle = "rgba(200, 215, 255, 0.5)";
          ctx.fillText(String(g.bar[i]), x + 5, 6);
          this.barMarks.push({ x, bar: g.bar[i] });
        }
      }
    } else {
      // No beat grid: seconds, faint.
      ctx.strokeStyle = "rgba(255,255,255,0.04)";
      ctx.lineWidth = 1;
      for (let s = Math.ceil(t); s < t + this.lookahead; s++) {
        const x = Math.round(xOf(s)) + 0.5;
        ctx.beginPath();
        ctx.moveTo(x, 0);
        ctx.lineTo(x, h);
        ctx.stroke();
      }
    }

    // «Bucle»: the part repeated, lit; its ends marked A and B.
    if (this.loop) {
      const xa = Math.max(HIT_X, xOf(this.loop.a));
      const xb = Math.min(w, xOf(this.loop.b));
      if (xb > xa) {
        ctx.fillStyle = "rgba(244, 183, 64, 0.07)";
        ctx.fillRect(xa, 0, xb - xa, h);
      }
      ctx.font = "800 12px Inter, sans-serif";
      ctx.textBaseline = "top";
      for (const [sec, label, align] of [[this.loop.a, "A", "left"], [this.loop.b, "B", "right"]]) {
        const x = xOf(sec);
        if (x < HIT_X || x > w) continue;
        ctx.fillStyle = "rgba(244, 183, 64, 0.85)";
        ctx.fillRect(Math.round(x) - 1, 0, 2, h);
        ctx.textAlign = align;
        ctx.fillText(label, x + (align === "left" ? 5 : -5), 22);
      }
    }

    // The staff: E4 G4 B4 D5 F5 (steps 0..8), and the clef.
    ctx.strokeStyle = "rgba(220, 225, 255, 0.28)";
    ctx.lineWidth = 1.2;
    for (let s = 0; s <= 8; s += 2) {
      const yy = Math.round(y(s)) + 0.5;
      ctx.beginPath();
      ctx.moveTo(0, yy);
      ctx.lineTo(w, yy);
      ctx.stroke();
    }
    ctx.fillStyle = "rgba(220, 225, 255, 0.22)";
    ctx.font = `${Math.round(hs * 7.2)}px serif`;
    ctx.textBaseline = "alphabetic";
    ctx.fillText("𝄞", HIT_X + 8, y(-1.6));

    // Breath marks in the rests.
    ctx.fillStyle = "rgba(160, 200, 255, 0.75)";
    ctx.font = `600 ${Math.round(hs * 2.4)}px Inter, sans-serif`;
    for (const b of this.breaths) {
      const x = xOf(b);
      if (x < HIT_X - 10 || x > w) continue;
      ctx.fillText("’", x + 2, y(12));
    }

    // The notes.
    this.hits = [];
    const barH = hs * 1.8;
    let sounding = null;
    let prev = null;
    for (const n of this.notes) {
      const first = !prev || prev.octave !== n.octave || n.start - prev.end > 0.6;
      prev = n;
      const x0 = xOf(n.start);
      const x1 = xOf(n.end);
      if (x1 < HIT_X - 2) continue;
      if (x0 > w) break;
      const wr = this.concert ? n.midi : written(n.midi, this.sax); // as read on the staff
      const step = staffStep(wr);
      const yy = y(step);
      const active = n.start <= t && t < n.end;
      if (active) sounding = { n, yy, wr };
      // Ledger lines it needs.
      ctx.strokeStyle = "rgba(220, 225, 255, 0.3)";
      ctx.lineWidth = 1.2;
      const ledgers = [];
      for (let s = -2; s >= step; s -= 2) ledgers.push(s);
      for (let s = 10; s <= step; s += 2) ledgers.push(s);
      for (const s of ledgers) {
        const ly = Math.round(y(s)) + 0.5;
        ctx.beginPath();
        ctx.moveTo(Math.max(HIT_X, x0) - 6, ly);
        ctx.lineTo(Math.max(HIT_X, x1) + 6, ly);
        ctx.stroke();
      }
      // The bar: what has not reached the hit line yet.
      const left = Math.max(HIT_X, x0);
      const width = Math.max(4, x1 - left);
      const near = Math.max(0, 1 - (x0 - HIT_X) / (pps * 0.6)); // brighter as it arrives
      const col = tone(active, active ? 62 : 58);
      ctx.save();
      ctx.shadowColor = tone(active, 60);
      ctx.shadowBlur = active ? 26 : 6 + near * 12;
      const grad = ctx.createLinearGradient(0, yy - barH / 2, 0, yy + barH / 2);
      grad.addColorStop(0, tone(active, active ? 76 : 72));
      grad.addColorStop(1, col);
      ctx.fillStyle = grad;
      roundRect(ctx, left, yy - barH / 2, width, barH, Math.min(barH / 2, 9));
      ctx.fill();
      if ((this.selected && n.key === this.selected) || this.selectedMore.has(n.key)) {
        ctx.shadowColor = "#fff";
        ctx.shadowBlur = 14;
        ctx.strokeStyle = "#fff";
        ctx.lineWidth = 2.5;
        ctx.setLineDash([6, 4]);
        roundRect(ctx, left - 3, yy - barH / 2 - 3, width + 6, barH + 6, Math.min(barH / 2 + 3, 12));
        ctx.stroke();
        ctx.setLineDash([]);
      }
      ctx.restore();
      // Moved an octave to fit the saxophone: said once, where it starts.
      if (n.octave && first && x0 >= HIT_X) {
        ctx.fillStyle = "rgba(200, 215, 255, 0.7)";
        ctx.font = "700 11px Inter, sans-serif";
        ctx.fillText(n.octave > 0 ? "8va ↑" : "8va ↓", x0, yy - barH / 2 - 5);
      }
      if (width > 30) {
        ctx.font = `800 ${Math.round(Math.min(barH * 0.62, 15))}px Inter, sans-serif`;
        ctx.textBaseline = "middle";
        ctx.lineWidth = 3;
        ctx.strokeStyle = "rgba(0, 0, 0, 0.55)";
        const label = noteName(wr, { names: this.names, octave: false });
        ctx.strokeText(label, left + 7, yy + 0.5);
        ctx.fillStyle = "#fff";
        ctx.fillText(label, left + 7, yy + 0.5);
        ctx.textBaseline = "alphabetic";
      }
      this.hits.push({ key: n.key, start: n.start, midi: n.midi, x: left, y: yy - barH / 2, w: width, h: barH });
    }

    // The box being dragged to pick several notes.
    if (this.band) {
      const { x0, y0, x1, y1 } = this.band;
      ctx.save();
      ctx.fillStyle = "rgba(255, 255, 255, 0.08)";
      ctx.strokeStyle = "rgba(255, 255, 255, 0.7)";
      ctx.lineWidth = 1;
      ctx.setLineDash([5, 4]);
      ctx.fillRect(Math.min(x0, x1), Math.min(y0, y1), Math.abs(x1 - x0), Math.abs(y1 - y0));
      ctx.strokeRect(Math.min(x0, x1) + 0.5, Math.min(y0, y1) + 0.5, Math.abs(x1 - x0), Math.abs(y1 - y0));
      ctx.restore();
    }

    // The hit line by the horn.
    const hl = ctx.createLinearGradient(HIT_X - 10, 0, HIT_X + 10, 0);
    const c = sounding ? tone(true, 62) : "rgba(255, 200, 100, 0.6)";
    hl.addColorStop(0, "rgba(0,0,0,0)");
    hl.addColorStop(0.5, c);
    hl.addColorStop(1, "rgba(0,0,0,0)");
    ctx.fillStyle = hl;
    ctx.fillRect(HIT_X - 10, 0, 20, h);

    // Sparks: thrown back toward the horn while a note sounds.
    if (sounding && playing) {
      for (let i = 0; i < 3; i++) {
        this.sparks.push({
          x: HIT_X,
          y: sounding.yy + (Math.random() - 0.5) * barH,
          vx: -40 - Math.random() * 120,
          vy: (Math.random() - 0.5) * 120,
          life: 0.6 + Math.random() * 0.5,
          color: tone(true, 70),
        });
      }
    }
    if (sounding) {
      ctx.save();
      ctx.shadowColor = tone(true, 60);
      ctx.shadowBlur = 30;
      ctx.fillStyle = tone(true, 75);
      ctx.beginPath();
      ctx.arc(HIT_X, sounding.yy, barH * 0.55, 0, Math.PI * 2);
      ctx.fill();
      ctx.restore();
    }
    // The player (microphone): where they are, against the line.
    if (this.you) {
      const col = { ok: "#3ecf8e", near: "#f4b740", off: "#e5484d" }[this.you.state] || "#c9d1e3";
      ctx.save();
      for (const p of this.you.trail || []) {
        const x = HIT_X - p.age * pps;
        if (x < 0) continue;
        ctx.globalAlpha = Math.max(0.1, 1 - p.age * 2);
        ctx.fillStyle = col;
        ctx.beginPath();
        ctx.arc(x, y(staffStep(Math.round(p.midi)) + (p.midi - Math.round(p.midi)) * 0.6), 3, 0, Math.PI * 2);
        ctx.fill();
      }
      ctx.globalAlpha = 1;
      if (this.you.midi != null) {
        const yy = y(staffStep(Math.round(this.you.midi)) + (this.you.midi - Math.round(this.you.midi)) * 0.6);
        ctx.shadowColor = col;
        ctx.shadowBlur = 22;
        ctx.strokeStyle = col;
        ctx.lineWidth = 3;
        ctx.beginPath();
        ctx.arc(HIT_X, yy, barH * 0.62, 0, Math.PI * 2);
        ctx.stroke();
        ctx.fillStyle = "#fff";
        ctx.font = "700 11px Inter, sans-serif";
        ctx.fillText("tú", HIT_X + barH * 0.7, yy + 4);
      }
      ctx.restore();
    }
    const alive = [];
    for (const s of this.sparks) {
      s.life -= dt;
      if (s.life <= 0) continue;
      s.x += s.vx * dt;
      s.y += s.vy * dt;
      s.vy += 60 * dt;
      ctx.globalAlpha = Math.min(1, s.life * 1.6);
      ctx.fillStyle = s.color;
      ctx.fillRect(s.x, s.y, 3, 3);
      alive.push(s);
    }
    ctx.globalAlpha = 1;
    this.sparks = alive.slice(-400);
    this.lastT = t;
    return sounding;
  }
}

function roundRect(ctx, x, y, w, h, r) {
  ctx.beginPath();
  ctx.moveTo(x + r, y);
  ctx.arcTo(x + w, y, x + w, y + h, r);
  ctx.arcTo(x + w, y + h, x, y + h, r);
  ctx.arcTo(x, y + h, x, y, r);
  ctx.arcTo(x, y, x + w, y, r);
  ctx.closePath();
}
