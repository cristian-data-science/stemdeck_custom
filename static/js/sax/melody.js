// «🎷 Saxo»: one or more stems turned into a line a saxophone can play.
//
// Pure (tested by tests/js/sax-melody.test.mjs): from the notes the score
// module transcribed for each stem (GET /api/jobs/{id}/score/{stem}) to one
// monophonic line, moved into the chosen saxophone's range by phrase, written
// for it (a saxophone reads transposed), with its fingering.

/** The saxophones: what a written note sounds (concert = written − shift) and
 *  the written range every saxophone shares, Bb3 (58) to F6 (89). */
export const SAXES = {
  alto: { name: "Alto (Mi♭)", shift: 9 },
  tenor: { name: "Tenor (Si♭)", shift: 14 },
  soprano: { name: "Soprano (Si♭)", shift: 2 },
  baritone: { name: "Barítono (Mi♭)", shift: 21 },
};
export const WRITTEN_LOW = 58; // Bb3
export const WRITTEN_HIGH = 89; // F6

/** The concert range of a saxophone (MIDI). */
export function concertRange(sax) {
  const s = SAXES[sax] || SAXES.alto;
  return { low: WRITTEN_LOW - s.shift, high: WRITTEN_HIGH - s.shift };
}

/** The note a saxophonist reads for a concert pitch. */
export function written(midi, sax) {
  return midi + (SAXES[sax] || SAXES.alto).shift;
}

const CHORD_SEC = 0.03; // notes starting this close are one chord: the top one is the melody
const MIN_SEC = 0.06; // shorter than this after trimming: a blip, not a note

const endOf = (n) => n.sound_end ?? n.draw_end ?? n.end;

/** One stem's notes as a single line: at each onset the highest note (the
 *  melody sits on top of the chords), each one cut where the next begins. */
export function skyline(notes) {
  const sorted = [...notes]
    .filter((n) => Number.isFinite(n.start) && endOf(n) > n.start)
    .sort((a, b) => a.start - b.start || b.midi - a.midi);
  const line = [];
  for (const n of sorted) {
    const last = line[line.length - 1];
    if (last && n.start - last.start < CHORD_SEC) {
      if (n.midi > last.midi) Object.assign(last, { midi: n.midi, velocity: n.velocity ?? last.velocity });
      continue;
    }
    line.push({ start: n.start, end: endOf(n), midi: n.midi, velocity: n.velocity ?? 80 });
  }
  for (let i = 0; i < line.length - 1; i++) line[i].end = Math.min(line[i].end, line[i + 1].start);
  return line.filter((n) => n.end - n.start >= MIN_SEC);
}

/** Several stems as one line: the first part leads; the others fill only
 *  where the lead (and every part before them) is silent. `parts`:
 *  [{stem, notes}] in priority order. */
export function melodyFrom(parts) {
  let taken = [];
  for (const { stem, notes } of parts) {
    for (const n of skyline(notes || [])) {
      const over = taken.filter((m) => m.start < n.end && m.end > n.start);
      if (!over.length) {
        taken.push({ ...n, stem });
        continue;
      }
      // Partly free: keep the free stretch before the first note it meets.
      const firstStart = Math.min(...over.map((m) => m.start));
      if (firstStart - n.start >= MIN_SEC * 2 && over.every((m) => m.start >= n.start)) {
        taken.push({ ...n, end: firstStart, stem });
      }
    }
    taken = taken.sort((a, b) => a.start - b.start);
  }
  for (let i = 0; i < taken.length - 1; i++) taken[i].end = Math.min(taken[i].end, taken[i + 1].start);
  return taken.filter((n) => n.end - n.start >= MIN_SEC);
}

const PHRASE_GAP = 0.6; // s of silence that ends a phrase

/** Phrases: runs of notes with less than PHRASE_GAP between them. */
export function phrases(notes) {
  const out = [];
  for (const n of notes) {
    const cur = out[out.length - 1];
    if (cur && n.start - cur[cur.length - 1].end < PHRASE_GAP) cur.push(n);
    else out.push([n]);
  }
  return out;
}

/** The line moved into the saxophone's range: each phrase by the octaves
 *  that keep most of it playable (a whole phrase moves, so its shape stays),
 *  then a note still outside by its own octave. Each note gets `octave`
 *  (how many octaves it moved). */
export function fitRange(notes, sax) {
  const { low, high } = concertRange(sax);
  const out = [];
  for (const ph of phrases(notes)) {
    let best = 0;
    let bestIn = -1;
    for (const k of [0, 1, -1, 2, -2, 3, -3]) {
      const inside = ph.filter((n) => n.midi + 12 * k >= low && n.midi + 12 * k <= high).length;
      if (inside > bestIn) {
        best = k;
        bestIn = inside;
      }
    }
    for (const n of ph) {
      let midi = n.midi + 12 * best;
      while (midi < low) midi += 12;
      while (midi > high) midi -= 12;
      out.push({ ...n, concert: n.midi, midi, octave: Math.round((midi - n.midi) / 12) });
    }
  }
  return out;
}

/** Where to breathe: gaps of at least `gap` s (the time the gap starts). */
export function breaths(notes, gap = 0.35) {
  const out = [];
  for (let i = 0; i < notes.length - 1; i++) {
    if (notes[i + 1].start - notes[i].end >= gap) out.push(notes[i].end);
  }
  return out;
}

// ── names ────────────────────────────────────────────────────────────────

const LETTERS = ["C", "C♯", "D", "E♭", "E", "F", "F♯", "G", "G♯", "A", "B♭", "B"];
const SOLFEGE = ["Do", "Do♯", "Re", "Mi♭", "Mi", "Fa", "Fa♯", "Sol", "Sol♯", "La", "Si♭", "Si"];
// The letter each name is written on (for its line or space on the staff).
const LETTER_OF = [0, 0, 1, 2, 2, 3, 3, 4, 4, 5, 6, 6]; // C C D E E F F G G A B B

/** "Sol4" / "G4" (octave by default; `octave: false` without it). */
export function noteName(midi, { names = "solfege", octave = true } = {}) {
  const pc = ((midi % 12) + 12) % 12;
  const base = (names === "letters" ? LETTERS : SOLFEGE)[pc];
  return octave ? `${base}${Math.floor(midi / 12) - 1}` : base;
}

/** The note's place on the treble staff, in steps above E4 (its bottom
 *  line): 0 = E4 line, 1 = F4 space, 8 = F5 top line. Sharps sit on their
 *  letter (C♯ on C), flats on theirs (E♭ on E). */
export function staffStep(midi) {
  const pc = ((midi % 12) + 12) % 12;
  const oct = Math.floor(midi / 12) - 1;
  return oct * 7 + LETTER_OF[pc] - (4 * 7 + 2);
}

/** A colour per pitch class (a full turn of the hue wheel from C): the same
 *  note always has the same colour, on the lane, the next-notes strip and
 *  the keys. */
export function pitchColor(midi, light = 60) {
  const pc = ((midi % 12) + 12) % 12;
  return `hsl(${Math.round((pc * 360) / 12)}, 85%, ${light}%)`;
}

// ── fingering ────────────────────────────────────────────────────────────
//
// The standard saxophone fingering of every written note from Bb3 to F6.
// Keys: oct (octave, left thumb); L1 L2 L3 (left hand B, A, G) and bis
// (the small B♭ key between L1 and L2); R1 R2 R3 (right hand F, E, D);
// left pinky G♯, C♯ (low), B (low), Bb (low); right pinky Eb, C (low);
// palm keys D, Eb, F; side E (high E); front F.
// Alternatives exist (side Bb, fork F♯...); these are the first ones taught.

const LOW = {
  58: ["L1", "L2", "L3", "Bb", "R1", "R2", "R3", "C"], // Bb3
  59: ["L1", "L2", "L3", "B", "R1", "R2", "R3", "C"], // B3
  60: ["L1", "L2", "L3", "R1", "R2", "R3", "C"], // C4
  61: ["L1", "L2", "L3", "Cs", "R1", "R2", "R3", "C"], // C#4
  62: ["L1", "L2", "L3", "R1", "R2", "R3"], // D4
  63: ["L1", "L2", "L3", "R1", "R2", "R3", "Eb"], // Eb4
  64: ["L1", "L2", "L3", "R1", "R2"], // E4
  65: ["L1", "L2", "L3", "R1"], // F4
  66: ["L1", "L2", "L3", "R2"], // F#4
  67: ["L1", "L2", "L3"], // G4
  68: ["L1", "L2", "L3", "Gs"], // G#4
  69: ["L1", "L2"], // A4
  70: ["L1", "bis"], // Bb4
  71: ["L1"], // B4
  72: ["L2"], // C5
  73: [], // C#5
};
const HIGH = {
  86: ["oct", "pD"], // D6
  87: ["oct", "pD", "pEb"], // Eb6
  88: ["oct", "pD", "pEb", "sE"], // E6
  89: ["oct", "pD", "pEb", "sE", "pF"], // F6
};

/** The keys pressed for a written note, or null outside the range. */
export function fingering(writtenMidi) {
  if (LOW[writtenMidi]) return LOW[writtenMidi];
  if (writtenMidi >= 74 && writtenMidi <= 85) return ["oct", ...LOW[writtenMidi - 12]]; // D5..C#6
  return HIGH[writtenMidi] || null;
}

/** The note sounding at t, and the next ones (the current one first). */
export function around(notes, t, count = 8) {
  let lo = 0;
  let hi = notes.length;
  while (lo < hi) {
    const mid = (lo + hi) >> 1;
    if (notes[mid].end <= t) lo = mid + 1;
    else hi = mid;
  }
  const current = notes[lo] && notes[lo].start <= t ? notes[lo] : null;
  return { current, next: notes.slice(lo, lo + count) };
}

// ── phrasing: a line a saxophonist would play ──────────────────────────
//
// A transcription cuts a sung note wherever a syllable or the volume dips,
// keeps every grace note and the stray notes the band leaves in a stem, and
// a keyboard's comping gives a top note per stab. Played as is, the
// saxophone sounded choppy ("picado") and full of notes that did not
// belong. Measured on «Y dime» (Agrupación Marilyn): the voice 407 notes,
// 130 of them one held note cut in pieces, 22 strays; the piano 568, 30 %
// shorter than 0.15 s, 48 strays.

/** How each kind of stem is phrased. `join`: the same note again after a
 *  gap this short is one note; `min`: shorter notes are grace notes or
 *  blips; `legato`: gaps this short are slurred over; `stray`: semitones
 *  away from the notes around for a short note not to belong. */
export const PHRASING = {
  voice: { join: 0.16, min: 0.11, legato: 0.12, stray: 7, strayMax: 0.3 },
  other: { join: 0.28, min: 0.13, legato: 0.16, stray: 7, strayMax: 0.35 },
};
const VOICE_STEMS = new Set(["vocals", "lead_vocals", "backing_vocals"]);
/** `tracked`: a line from the pitch tracker (a voice, or a lead instrument
 *  in "other"): its notes are already one per note, phrased as a voice. */
export const phrasingOf = (stem, tracked = false) => (tracked || VOICE_STEMS.has(stem) ? PHRASING.voice : PHRASING.other);

const CONTEXT_SEC = 1.0; // the notes within this of a note are its context

/** The same note again soon after: one note (held through a syllable). */
export function joinRepeats(notes, gap) {
  const out = [];
  for (const n of notes) {
    const prev = out[out.length - 1];
    if (prev && prev.midi === n.midi && n.start - prev.end <= gap) prev.end = Math.max(prev.end, n.end);
    else out.push({ ...n });
  }
  return out;
}

/** Short notes far from every note around them: strays (the band left in
 *  the stem, an octave slip). An octave away from its context it is moved
 *  back by octaves; otherwise it goes. */
export function dropStrays(notes, { stray, strayMax }) {
  const out = [];
  for (let i = 0; i < notes.length; i++) {
    const n = notes[i];
    const around = notes.filter(
      (m, j) => j !== i && m.end > n.start - CONTEXT_SEC && m.start < n.end + CONTEXT_SEC,
    );
    if (!around.length || n.end - n.start > strayMax) {
      out.push(n);
      continue;
    }
    const mids = around.map((m) => m.midi).sort((a, b) => a - b);
    const med = mids[Math.floor(mids.length / 2)];
    const d = n.midi - med;
    if (Math.abs(d) < stray) {
      out.push(n);
      continue;
    }
    const folded = n.midi - 12 * Math.round(d / 12);
    if (Math.abs(folded - med) < stray) out.push({ ...n, midi: folded });
  }
  return out;
}

/** Notes too short to be notes: a grace note right before or after
 *  another is absorbed into it; on its own it goes. Touching both, it goes
 *  to the nearer in pitch: a scoop (a saxophone or a singer coming up into
 *  a note from a semitone under it) is the start of the note it leads to,
 *  not the end of the one before. */
export function absorbShort(notes, min) {
  const out = [];
  const src = notes.map((n) => ({ ...n }));
  for (let i = 0; i < src.length; i++) {
    const n = src[i];
    if (n.end - n.start >= min) {
      out.push(n);
      continue;
    }
    const prev = out[out.length - 1];
    const next = src[i + 1];
    const toPrev = prev && n.start - prev.end < 0.06;
    const toNext = next && next.start - n.end < 0.06;
    if (toPrev && (!toNext || Math.abs(prev.midi - n.midi) <= Math.abs(next.midi - n.midi))) prev.end = Math.max(prev.end, n.end);
    else if (toNext) next.start = Math.min(next.start, n.start);
  }
  return out;
}

/** Gaps shorter than `legato` slurred over (the note before holds until the
 *  next one), and each note says whether it is slurred from the one before
 *  (`legato`: played without a new attack). */
export function slur(notes, legato) {
  const out = notes.map((n) => ({ ...n }));
  for (let i = 0; i < out.length - 1; i++) {
    const gap = out[i + 1].start - out[i].end;
    if (gap >= 0 && gap < legato) out[i].end = out[i + 1].start;
    out[i + 1].legato = out[i + 1].start - out[i].end < 0.03;
  }
  return out;
}

/** A line phrased for the saxophone (see PHRASING). */
export function phrase(notes, opts = PHRASING.voice) {
  let line = joinRepeats(notes, opts.join);
  line = dropStrays(line, opts);
  line = absorbShort(line, opts.min);
  line = joinRepeats(line, opts.join);
  return slur(line, opts.legato);
}

/** The line in short groups for the strip of next notes: a phrase (up to a
 *  breath) at a time, cut where it pauses most if it runs long. The strip
 *  then changes once per group, not at every note: a fast passage read as
 *  one row instead of chips sliding past. Sets `n.g` (the group's index). */
export function noteGroups(notes, { gap = 0.35, max = 10 } = {}) {
  const groups = [];
  let cur = [];
  const close = () => {
    if (cur.length) groups.push(cur);
    cur = [];
  };
  for (let i = 0; i < notes.length; i++) {
    const n = notes[i];
    const prev = notes[i - 1];
    if (prev && n.start - prev.end >= gap) close();
    cur.push(n);
    if (cur.length >= max) {
      // Too long: cut after its widest pause in the second half (else here).
      let at = cur.length - 1;
      let widest = -1;
      for (let k = Math.floor(cur.length / 2); k < cur.length - 1; k++) {
        const w = cur[k + 1].start - cur[k].end;
        if (w > widest) {
          widest = w;
          at = k;
        }
      }
      const rest = cur.slice(at + 1);
      cur = cur.slice(0, at + 1);
      close();
      cur = rest;
    }
  }
  close();
  groups.forEach((g, i) => {
    for (const n of g) n.g = i;
  });
  return groups;
}
