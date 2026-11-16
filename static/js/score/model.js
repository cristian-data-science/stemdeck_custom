// Score view: the pure part. No DOM, no network, so every rule the page
// applies to notes can be checked in node (tests/js/score-model.test.mjs).
//
// A note, as the server sends it (app/score/service.py payload):
//   { id, midi, start, end, velocity, hand,            <- what is saved
//     staff, q_start, q_end, step_sec, letter, alter,  <- engraving, read-only
//     octave, measure, heads }
// Edits only ever change the saved fields; the server engraves again.

export const SOLFEGE = { C: "do", D: "re", E: "mi", F: "fa", G: "sol", A: "la", B: "si" };
// held: a length the user set (joined two notes, lengthened one): drawn, lit
// and played to its end, not cut where its hand plays next (the score is one
// voice per staff).
export const SAVED_FIELDS = ["id", "midi", "start", "end", "velocity", "hand", "held"];
export const MIDI_MIN = 21;
export const MIDI_MAX = 108;

const LABEL_ACC = { "-2": "𝄫", "-1": "♭", 1: "♯", 2: "𝄪" };
// The name of each key on a piano, for spellings nobody reads by sight.
const FLAT_KEYS = [["C", 0], ["D", -1], ["D", 0], ["E", -1], ["E", 0], ["F", 0], ["G", -1], ["G", 0], ["A", -1], ["A", 0], ["B", -1], ["B", 0]];
const SHARP_KEYS = [["C", 0], ["C", 1], ["D", 0], ["D", 1], ["E", 0], ["F", 0], ["F", 1], ["G", 0], ["G", 1], ["A", 0], ["A", 1], ["B", 0]];

/** Text inside a notehead: "si♭" / "B♭", with its accidental. Not only the
 *  letter: an accidental of the key signature is never drawn next to the
 *  note, so in E-flat minor a B-flat said "si" and a C-flat (the key B)
 *  said "do", and the whole piece read one note off. Spellings that name
 *  another key than the one played (C♭, F♭, E♯, B♯, double accidentals) are
 *  named by the key that sounds: C♭ says "si". */
export function noteLabel(note, names = "solfege") {
  if (!note || !note.letter) return "";
  let letter = note.letter;
  let alter = note.alter ?? 0;
  const odd = Math.abs(alter) === 2 || (alter === -1 && (letter === "C" || letter === "F")) || (alter === 1 && (letter === "E" || letter === "B"));
  if (odd && Number.isInteger(note.midi)) [letter, alter] = (alter < 0 ? FLAT_KEYS : SHARP_KEYS)[((note.midi % 12) + 12) % 12];
  const base = names === "letters" ? letter : SOLFEGE[letter] || "";
  return base + (LABEL_ACC[alter] || "");
}

/** Full pitch name for the status line: "Si♭4" / "Bb4". */
export function pitchName(note, names = "solfege") {
  const acc = { "-2": "𝄫", "-1": "♭", 0: "", 1: "♯", 2: "𝄪" }[note.alter ?? 0] ?? "";
  const accL = { "-2": "bb", "-1": "b", 0: "", 1: "#", 2: "##" }[note.alter ?? 0] ?? "";
  if (names === "letters") return `${note.letter}${accL}${note.octave}`;
  const base = SOLFEGE[note.letter] || "?";
  return `${base[0].toUpperCase()}${base.slice(1)}${acc}${note.octave}`;
}

export function savedNote(n) {
  const out = {};
  for (const k of SAVED_FIELDS) out[k] = n[k] ?? null;
  return out;
}

export function savedNotes(notes) {
  return notes.map(savedNote);
}

// ── time ────────────────────────────────────────────────────────────────

/** Index of the first element whose key is > t (keys sorted ascending). */
export function upperBound(keys, t) {
  let lo = 0;
  let hi = keys.length;
  while (lo < hi) {
    const mid = (lo + hi) >> 1;
    if (keys[mid] <= t) lo = mid + 1;
    else hi = mid;
  }
  return lo;
}

/** Where a note stops sounding on the page: where its drawn note ends
 *  (draw_end, from the server), not the model's raw release. A staff has one
 *  voice, so a held note is drawn up to the next onset; the piano model also
 *  caps a release it never heard at 6 s. Playing and lighting the raw end left
 *  notes drawn as half notes sounding for bars. */
export const soundEnd = (n) =>
  n.held ? Math.max(n.end, n.start + 0.01) : n.draw_end != null ? Math.max(n.draw_end, n.start + 0.01) : n.end;

/** Where a note stops in playback without pedal: where the key came up
 *  (sound_end, from the server: the heard release, the drawn end only when
 *  the model never heard it). Not the drawn end: a staff is one voice, so a
 *  held note is drawn only up to its hand's next onset, and playing that made
 *  arpeggios and inner voices staccato. Lighting keeps the drawn end. */
export const playEnd = (n) => (n.sound_end != null ? Math.max(n.sound_end, n.start + 0.01) : soundEnd(n));

/** Where a note stops in playback with the Pedal slider at pct %: from where
 *  it sounds (playEnd) towards pedal_end (where the pedal fully down would
 *  stop it, from the server; null when the pedal does not hold it). */
export function heldEnd(n, pct) {
  const end = playEnd(n);
  if (!pct || n.pedal_end == null || n.pedal_end <= end) return end;
  return end + ((n.pedal_end - end) * Math.min(pct, 100)) / 100;
}

/** Index over notes sorted by start, for "what is sounding at t". */
export function buildTimeIndex(notes) {
  const sorted = [...notes].sort((a, b) => a.start - b.start);
  let longest = 0;
  for (const n of sorted) longest = Math.max(longest, soundEnd(n) - n.start);
  return { sorted, starts: sorted.map((n) => n.start), longest };
}

/** Ids of the notes sounding at time t (start <= t < sound end). */
export function activeAt(index, t) {
  const out = [];
  const hi = upperBound(index.starts, t);
  for (let j = hi - 1; j >= 0; j--) {
    const n = index.sorted[j];
    if (n.start < t - index.longest) break;
    if (soundEnd(n) > t) out.push(n.id);
  }
  return out;
}

/** Sort the cursor's points by time and never let x go back within a
 *  system. Measure boxes swell with what sticks out of them (chord names,
 *  ties), and a measure's "end" point used to land right of the next
 *  measure's start: the cursor stepped back 100-350 px at barlines (30 times
 *  in a waltz). Clamping makes that impossible whatever the drawing does. */
export function monotoneTimeline(points) {
  const sorted = [...points].sort((a, b) => a.t - b.t);
  let last = null;
  for (const p of sorted) {
    if (last && last.sys === p.sys && p.x < last.x) p.x = last.x;
    last = p;
  }
  return sorted;
}

/** A playback clock that moves every frame. The <audio> element reports
 *  currentTime in steps; drawn as is, the cursor stutters. Between reports
 *  the clock runs on from the last one at the playback rate; a report that
 *  lands close to it nudges it, and it never runs backwards while playing --
 *  only a real jump (a seek) is taken as is. */
export class SmoothClock {
  constructor({ snap = 0.3, pull = 0.15 } = {}) {
    this.snap = snap;
    this.pull = pull;
    this.t = 0;
    this.at = 0; // ms of the last update
  }

  update(reported, nowMs, playing, rate = 1) {
    if (!playing) {
      this.t = reported;
      this.at = nowMs;
      return this.t;
    }
    const run = this.t + ((nowMs - this.at) / 1000) * rate;
    if (Math.abs(reported - run) > this.snap) {
      this.t = reported; // a seek, or a long stall: believe the audio
    } else {
      // Ease toward the audio, but never back.
      this.t = Math.max(this.t, run + (reported - run) * this.pull);
    }
    this.at = nowMs;
    return this.t;
  }
}

/** Cursor x at time t over a timeline [{t, x, sys}] sorted by t: linear
 *  between two points of the same system, held at the last point when the
 *  next one is on another system. */
export function cursorAt(timeline, t) {
  if (!timeline.length) return null;
  const keys = timeline.map((p) => p.t);
  const k = upperBound(keys, t) - 1;
  if (k < 0) return { x: timeline[0].x, sys: timeline[0].sys, k: 0 };
  const a = timeline[k];
  const b = timeline[k + 1];
  if (!b || b.sys !== a.sys || b.t <= a.t) return { x: a.x, sys: a.sys, k };
  const f = Math.min(1, Math.max(0, (t - a.t) / (b.t - a.t)));
  return { x: a.x + f * (b.x - a.x), sys: a.sys, k };
}

// ── edits: each returns a new notes array; the input is never mutated ─────

const clampMidi = (m) => Math.min(MIDI_MAX, Math.max(MIDI_MIN, m));
const round4 = (x) => Math.round(x * 10000) / 10000;

export function deleteNotes(notes, ids) {
  const set = new Set(ids);
  return notes.filter((n) => !set.has(n.id));
}

export function transpose(notes, ids, semitones) {
  const set = new Set(ids);
  return notes.map((n) => (set.has(n.id) ? { ...n, midi: clampMidi(n.midi + semitones) } : n));
}

/** Move by whole grid steps. Starts from the quantized position, so one press
 *  is exactly one step once the server snaps it again. */
export function moveNotes(notes, ids, steps) {
  const set = new Set(ids);
  return notes.map((n) => {
    if (!set.has(n.id)) return n;
    const step = n.step_sec || 0.125;
    const qs = n.q_start ?? n.start;
    const qe = n.q_end ?? n.end;
    const shift = Math.max(steps * step, -qs);
    const start = round4(qs + shift);
    const end = round4(qe + shift);
    // q_* move too, so a second press before the server answers adds up.
    const moved = { ...n, start, end, q_start: start, q_end: end };
    // Everything the server placed moves with it, so it sounds where it now
    // is until the server answers: with sound_end left behind a note moved
    // later played as a 10 ms blip, one moved earlier rang on to its old end.
    for (const k of ["draw_end", "sound_end", "pedal_end"]) if (n[k] != null) moved[k] = round4(n[k] + shift);
    return moved;
  });
}

/** Lengthen (steps > 0) or shorten by whole grid steps, never below one step. */
export function resizeNotes(notes, ids, steps) {
  const set = new Set(ids);
  return notes.map((n) => {
    if (!set.has(n.id)) return n;
    const step = n.step_sec || 0.125;
    const qs = n.q_start ?? n.start;
    // From the end you can see: lengthening a note drawn as a half note must
    // not start from a 6 s release nobody drew.
    const qe = n.draw_end ?? n.q_end ?? n.end;
    const end = round4(Math.min(Math.max(qs + step, qe + steps * step), qs + 59));
    // Heard as long as it is now drawn (playEnd reads sound_end first).
    const pedal = n.pedal_end != null && n.pedal_end > end ? n.pedal_end : null;
    return { ...n, start: round4(qs), end, q_start: round4(qs), q_end: end, draw_end: end, sound_end: end, pedal_end: pedal, held: true };
  });
}

/** "Si♭4" / "Bb4" from a MIDI number alone (a deleted note has no spelling
 *  any more): flats in a flat key (fifths < 0), sharps otherwise. */
export function midiName(midi, { flats = false, names = "solfege" } = {}) {
  const pc = ((midi % 12) + 12) % 12;
  const [letter, alter] = (flats ? FLAT_KEYS : SHARP_KEYS)[pc];
  const base = names === "letters" ? letter : SOLFEGE[letter];
  const name = names === "letters" ? base : base[0].toUpperCase() + base.slice(1);
  return `${name}${LABEL_ACC[alter] || ""}${Math.floor(midi / 12) - 1}`;
}

const SCALES = { major: [0, 2, 4, 5, 7, 9, 11], minor: [0, 2, 3, 5, 7, 8, 10] };

/** midi moved k steps along the key's scale, as a note dragged up or down
 *  the staff moves line by line. keyId: "pc:major" | "pc:minor". A note
 *  outside the scale lands on the nearest scale note in that direction. */
export function scaleShift(midi, k, keyId = "0:major") {
  const [pcStr, mode] = String(keyId).split(":");
  const tonic = Number(pcStr) || 0;
  const pcs = new Set((SCALES[mode] || SCALES.major).map((d) => (tonic + d) % 12));
  let m = midi;
  const dir = Math.sign(k);
  for (let left = Math.abs(k); left > 0; left--) {
    do m += dir; while (!pcs.has(((m % 12) + 12) % 12));
  }
  return clampMidi(m);
}

/** Each note moved k scale steps (see scaleShift). */
export function shiftInScale(notes, ids, k, keyId) {
  if (!k) return notes;
  const set = new Set(ids);
  return notes.map((n) => (set.has(n.id) ? { ...n, midi: scaleShift(n.midi, k, keyId) } : n));
}

/** Treble <-> bass. Uses the staff the note is drawn on now. */
export function toggleHand(notes, ids) {
  const set = new Set(ids);
  return notes.map((n) => (set.has(n.id) ? { ...n, hand: n.staff === 2 || n.hand === "L" ? "R" : "L" } : n));
}

export function setHand(notes, ids, hand) {
  const set = new Set(ids);
  return notes.map((n) => (set.has(n.id) ? { ...n, hand } : n));
}

/** Notes a clean-up with these thresholds would remove. */
export function cleanupTargets(notes, { minVelocity = 0, minDurationMs = 0 } = {}) {
  return notes
    .filter((n) => n.velocity < minVelocity || (n.end - n.start) * 1000 < minDurationMs)
    .map((n) => n.id);
}

/** Same pitch, the second starting within gapSec of the first's end: one note. */
export function mergeRepeats(notes, gapSec = 0.04) {
  const byPitch = new Map();
  for (const n of [...notes].sort((a, b) => a.start - b.start)) {
    if (!byPitch.has(n.midi)) byPitch.set(n.midi, []);
    byPitch.get(n.midi).push(n);
  }
  const drop = new Set();
  const grown = new Map();
  for (const list of byPitch.values()) {
    let head = null;
    for (const n of list) {
      if (head && n.start - (grown.get(head.id) ?? head.end) <= gapSec) {
        grown.set(head.id, Math.max(grown.get(head.id) ?? head.end, n.end));
        drop.add(n.id);
      } else {
        head = n;
      }
    }
  }
  return notes
    .filter((n) => !drop.has(n.id))
    .map((n) => (grown.has(n.id) ? { ...n, end: round4(grown.get(n.id)) } : n));
}

/** The note on the same key just before `id` (the one its start can be
 *  dragged down onto, in the falling-notes view), or null. */
export function previousOnKey(notes, id) {
  const n = notes.find((x) => x.id === id);
  if (!n) return null;
  let best = null;
  for (const x of notes) {
    if (x.id === id || x.midi !== n.midi || x.start >= n.start) continue;
    if (!best || x.start > best.start) best = x;
  }
  return best;
}

/** Two notes on one key made one: `earlier` keeps its start and takes the
 *  later one's end (drawn, heard and quantized); the later one goes. For a
 *  key the transcription split in two (a held note re-struck by mistake). */
export function joinNotes(notes, earlierId, laterId) {
  const a = notes.find((x) => x.id === earlierId);
  const b = notes.find((x) => x.id === laterId);
  if (!a || !b || a.midi !== b.midi || a.id === b.id) return notes;
  const [first, second] = a.start <= b.start ? [a, b] : [b, a];
  const endOf = (n, k) => n[k] ?? n.end;
  const joined = {
    ...first,
    end: round4(Math.max(first.end, second.end)),
    q_end: round4(Math.max(endOf(first, "q_end"), endOf(second, "q_end"))),
    draw_end: round4(Math.max(endOf(first, "draw_end"), endOf(second, "draw_end"))),
    held: true, // one long note, though its hand plays on meanwhile
  };
  if (first.sound_end != null || second.sound_end != null) {
    joined.sound_end = round4(Math.max(endOf(first, "sound_end"), endOf(second, "sound_end")));
  }
  return notes.filter((x) => x.id !== second.id).map((x) => (x.id === first.id ? joined : x));
}

/** A note's start moved by whole grid steps (its end stays), never past
 *  one step before its end nor before 0:00. */
export function moveStart(notes, id, steps) {
  return notes.map((n) => {
    if (n.id !== id) return n;
    const step = n.step_sec || 0.125;
    const qs = n.q_start ?? n.start;
    const qe = n.draw_end ?? n.q_end ?? n.end;
    const start = round4(Math.max(0, Math.min(qs + steps * step, qe - step)));
    return { ...n, start, q_start: start };
  });
}

/** Next / previous note in time from the given one (for Tab navigation). */
export function neighbour(notes, id, dir = 1) {
  const sorted = [...notes].sort((a, b) => a.start - b.start || a.midi - b.midi);
  const i = sorted.findIndex((n) => n.id === id);
  if (i < 0) return sorted[dir > 0 ? 0 : sorted.length - 1]?.id ?? null;
  return sorted[i + dir]?.id ?? id;
}

// ── undo ────────────────────────────────────────────────────────────────

export class History {
  constructor(limit = 200) {
    this.limit = limit;
    this.undoStack = [];
    this.redoStack = [];
    // What each edit was («Movida»...), beside its state: the buttons and the
    // saved history name what an undo undoes.
    this.undoLabels = [];
    this.redoLabels = [];
    this.label = ""; // the edit the last undo / redo acted on
  }
  push(state, label = "") {
    this.undoStack.push(state);
    this.undoLabels.push(label);
    if (this.undoStack.length > this.limit) {
      this.undoStack.shift();
      this.undoLabels.shift();
    }
    this.redoStack = [];
    this.redoLabels = [];
  }
  undo(current) {
    if (!this.undoStack.length) return null;
    this.label = this.undoLabels.pop() ?? "";
    this.redoStack.push(current);
    this.redoLabels.push(this.label);
    return this.undoStack.pop();
  }
  redo(current) {
    if (!this.redoStack.length) return null;
    this.label = this.redoLabels.pop() ?? "";
    this.undoStack.push(current);
    this.undoLabels.push(this.label);
    return this.redoStack.pop();
  }
  /** What Undo / Redo would act on now ("" if unnamed or nothing). */
  get undoLabel() {
    return this.undoLabels[this.undoLabels.length - 1] ?? "";
  }
  get redoLabel() {
    return this.redoLabels[this.redoLabels.length - 1] ?? "";
  }
  get canUndo() {
    return this.undoStack.length > 0;
  }
  get canRedo() {
    return this.redoStack.length > 0;
  }
}

// ── formatting ─────────────────────────────────────────────────────────

export function formatTime(sec) {
  if (!Number.isFinite(sec) || sec < 0) sec = 0;
  const m = Math.floor(sec / 60);
  const s = Math.floor(sec % 60);
  return `${m}:${String(s).padStart(2, "0")}`;
}

/** Split-point choices for the hand selector: C2..C6 by semitone. */
export function splitChoices(names = "solfege") {
  const letters = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"];
  const out = [];
  for (let m = 36; m <= 84; m++) {
    const l = letters[m % 12];
    const oct = Math.floor(m / 12) - 1;
    const base = names === "letters" ? l : SOLFEGE[l[0]] + (l.length > 1 ? "♯" : "");
    out.push({ midi: m, label: `${base}${oct}` });
  }
  return out;
}

// ── keys and meters (for the selectors) ─────────────────────────────────

const MAJOR_TONICS = ["C", "Db", "D", "Eb", "E", "F", "F#", "G", "Ab", "A", "Bb", "B"];
const MINOR_TONICS = ["C", "C#", "D", "Eb", "E", "F", "F#", "G", "G#", "A", "Bb", "B"];

function tonicName(t, names) {
  if (names === "letters") return t;
  const acc = t.length > 1 ? (t[1] === "#" ? "♯" : "♭") : "";
  const base = SOLFEGE[t[0]];
  return base[0].toUpperCase() + base.slice(1) + acc;
}

/** The 24 keys as the score's key setting ids ("pc:mode") with names,
 *  spelled the conventional way (B-flat major, not A-sharp). */
export function keyChoices(names = "solfege") {
  const out = [];
  for (const minor of [false, true]) {
    const tonics = minor ? MINOR_TONICS : MAJOR_TONICS;
    tonics.forEach((t, pc) => {
      const mode = names === "letters" ? (minor ? "minor" : "major") : minor ? "menor" : "mayor";
      out.push({ id: `${pc}:${minor ? "minor" : "major"}`, label: `${tonicName(t, names)} ${mode}` });
    });
  }
  return out;
}

/** Next bar_shift for a nudge of dir beats, within the meter. */
export function nextBarShift(current, dir, meter) {
  const m = Math.max(1, meter || 4);
  return (((current || 0) + dir) % m + m) % m;
}

/** An id for a note the user adds: "nu" + the time in base 36 (never one a
 *  transcription uses, nor one in the deleted notes). */
export function newNoteId(notes, now = Date.now()) {
  const taken = new Set(notes.map((n) => n.id));
  let k = now;
  while (taken.has(`nu${k.toString(36)}`)) k++;
  return `nu${k.toString(36)}`;
}

/** The notes with one more: `start`..`end` on key `midi` (velocity: that of
 *  the notes around it, 80 when there are none). */
export function addNote(notes, { midi, start, end, hand = null, id = newNoteId(notes) }) {
  const s = round4(Math.max(0, start));
  const e = round4(Math.max(end, s + 0.05));
  const near = notes.filter((n) => Math.abs(n.start - s) < 2);
  const velocity = near.length ? Math.round(near.reduce((a, n) => a + (n.velocity || 80), 0) / near.length) : 80;
  const note = { id, midi: clampMidi(midi), start: s, end: e, velocity, hand, q_start: s, q_end: e, draw_end: e, held: true };
  return [...notes, note];
}

/** The start time snapped onto an onset already there within `tol` s (so an
 *  added note joins its chord), else as given. */
export function snapToOnset(notes, t, tol = 0.08) {
  let best = t;
  let gap = tol;
  for (const n of notes) {
    const d = Math.abs((n.q_start ?? n.start) - t);
    if (d <= gap) [best, gap] = [n.q_start ?? n.start, d];
  }
  return best;
}

/** The key written at a staff position: `steps` half staff spaces above the
 *  bottom line (staff 1: treble, E4; staff 2: bass, G2), with the key
 *  signature of keyId ("tonic:mode"): in F major the middle line is B♭4. */
export function pitchOnStaff(staff, steps, keyId = "0:major") {
  const d = (staff === 2 ? 2 * 7 + 4 : 4 * 7 + 2) + steps; // diatonic: C0 = 0
  const letter = ((d % 7) + 7) % 7;
  const octave = Math.floor(d / 7);
  const natural = (octave + 1) * 12 + [0, 2, 4, 5, 7, 9, 11][letter];
  const [pcStr, mode] = String(keyId).split(":");
  const major = ((Number(pcStr) || 0) + (mode === "minor" ? 3 : 0)) % 12; // its relative major
  const fifths = [0, -5, 2, -3, 4, -1, 6, 1, -4, 3, -2, 5][major];
  const order = fifths > 0 ? [3, 0, 4, 1, 5, 2, 6] : [6, 2, 5, 1, 4, 0, 3]; // F C G D A E B / B E A D G C F
  const altered = order.slice(0, Math.abs(fifths)).includes(letter);
  return clampMidi(natural + (altered ? Math.sign(fifths) : 0));
}
