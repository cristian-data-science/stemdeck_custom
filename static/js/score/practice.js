// Score view: practising a song. Pure helpers (tested in node,
// tests/js/score-model.test.mjs) for the loop over bars, the metronome's
// beats, the MIDI keyboard's "wait for me" mode and what each song remembers.

/** Index of the bar sounding at song time t (the last one started), or -1. */
export function measureAt(measures, t) {
  let lo = 0;
  let hi = measures.length - 1;
  let found = -1;
  while (lo <= hi) {
    const mid = (lo + hi) >> 1;
    if (measures[mid].start <= t + 1e-6) {
      found = mid;
      lo = mid + 1;
    } else hi = mid - 1;
  }
  return found;
}

/** A loop over bars i..j (in either order): {a, b, from, to} in seconds and
 *  bar numbers; null if there are no such bars. */
export function loopOver(measures, i, j) {
  if (!measures.length) return null;
  const lo = Math.max(0, Math.min(i, j));
  const hi = Math.min(measures.length - 1, Math.max(i, j));
  const first = measures[lo];
  const last = measures[hi];
  if (!first || !last || !(last.end > first.start)) return null;
  return { a: first.start, b: last.end, from: first.number ?? lo + 1, to: last.number ?? hi + 1 };
}

/** The loop over the bars of some notes (the selection), or null. */
export function loopOverNotes(measures, notes) {
  if (!notes.length || !measures.length) return null;
  const starts = notes.map((n) => measureAt(measures, n.start)).filter((i) => i >= 0);
  if (!starts.length) return null;
  return loopOver(measures, Math.min(...starts), Math.max(...starts));
}

/** Where playback goes at song time t with a loop on: back to its start once
 *  past its end (null: keep going). */
export function loopJump(loop, t) {
  if (!loop || !loop.on || !(loop.b > loop.a)) return null;
  return t >= loop.b ? loop.a : null;
}

/** The practice speeds, in %: the only ones offered (the «Velocidad»
 *  buttons). The server renders Pianoteq at each of them beforehand, for
 *  each hand (app/api/score.py PT_SPEEDS), so choosing one plays at once. */
export const SPEEDS = [25, 50, 70, 100];

/** The practice speed nearest to `pct` (a speed saved before, e.g. 85). */
export function snapSpeed(pct) {
  const v = Number(pct);
  if (!Number.isFinite(v)) return 100;
  return SPEEDS.reduce((best, s) => (Math.abs(s - v) < Math.abs(best - v) ? s : best), 100);
}

/** The next practice speed up from `current` (the loop ramp), up to 100. */
export function nextSpeed(current) {
  return SPEEDS.find((s) => s > snapSpeed(current)) ?? 100;
}

/** The speed after `loops` times round the loop with the ramp: one step up
 *  every `every` loops (0: the same speed). */
export function rampSpeed(current, every, loops) {
  if (!every || loops % every !== 0) return snapSpeed(current);
  return nextSpeed(current);
}

/** Beats of the bars, evenly spaced within each one: [{t, down}] in time
 *  order (down: the bar's first beat, accented by the metronome). */
export function beatsOf(measures) {
  const out = [];
  for (const m of measures) {
    const n = Math.max(1, m.meter || 4);
    const span = (m.end - m.start) / n;
    if (!(span > 0)) continue;
    for (let k = 0; k < n; k++) out.push({ t: m.start + k * span, down: k === 0 });
  }
  return out;
}

/** Seconds of one beat at song time t (for a count-in before it). */
export function beatSecondsAt(measures, t, fallback = 0.5) {
  const i = Math.max(0, measureAt(measures, t));
  const m = measures[i];
  if (!m) return fallback;
  const s = (m.end - m.start) / Math.max(1, m.meter || 4);
  return s > 0.05 && s < 4 ? s : fallback;
}

/** Notes the player plays themself, by hand: "R" the treble staff (1), "L"
 *  the bass staff (2), anything else both. */
export function playsHand(note, hand) {
  if (hand === "R") return note.staff !== 2;
  if (hand === "L") return note.staff === 2;
  return true;
}

export const CHORD_SEC = 0.06; // notes struck this close together are one chord to play

/** The next chord to play from song time t on (its notes start within
 *  CHORD_SEC of the first): {start, keys: Set<midi>, ids}, or null at the end.
 *  `sorted`: notes in start order; `hand` as playsHand. */
export function nextChord(sorted, t, hand = null, after = -Infinity) {
  let lo = 0;
  let hi = sorted.length;
  while (lo < hi) {
    const mid = (lo + hi) >> 1;
    if (sorted[mid].start < t - 1e-6) lo = mid + 1;
    else hi = mid;
  }
  for (let i = lo; i < sorted.length; i++) {
    const n = sorted[i];
    // Notes of the chord just played (struck up to CHORD_SEC after its first)
    // are that chord, not the next one.
    if (n.start <= after + CHORD_SEC || !playsHand(n, hand)) continue;
    const keys = new Set();
    const ids = [];
    for (let j = i; j < sorted.length && sorted[j].start - n.start <= CHORD_SEC; j++) {
      if (!playsHand(sorted[j], hand)) continue;
      keys.add(sorted[j].midi);
      ids.push(sorted[j].id);
    }
    return { start: n.start, keys, ids };
  }
  return null;
}

/** Whether a chord is played: every one of its keys struck since it became
 *  the one to play (`struck`), or held down now (`down`). */
export function chordDone(chord, struck, down) {
  for (const k of chord.keys) if (!struck.has(k) && !down.has(k)) return false;
  return true;
}

/** A key struck freely (no waiting): a hit when a note of the hands
 *  practised starts on that key within `tol` s; returns its id or null. */
export function hitNote(sorted, midi, t, hand = null, tol = 0.18, used = new Set()) {
  let best = null;
  let gap = tol;
  for (const n of sorted) {
    if (n.start > t + tol) break;
    if (n.midi !== midi || used.has(n.id) || !playsHand(n, hand)) continue;
    const d = Math.abs(n.start - t);
    if (d <= gap) [best, gap] = [n.id, d];
  }
  return best;
}

// ── what each song remembers (this browser) ──

const songKey = (job, stem) => `stemdeck.score.song.${job}.${stem}`;

/** The song's own practice settings: where it was left, the source heard,
 *  speed, loop, the hand practised. {} when none. */
export function readSongPrefs(storage, job, stem) {
  try {
    const v = JSON.parse(storage.getItem(songKey(job, stem)) || "{}");
    return v && typeof v === "object" ? v : {};
  } catch {
    return {};
  }
}

export function writeSongPrefs(storage, job, stem, prefs) {
  try {
    storage.setItem(songKey(job, stem), JSON.stringify(prefs));
  } catch {
    /* storage full or off: the song just does not remember */
  }
}

/** Where to start: the moment asked for in the address (?t=, from the
 *  mixer), else where the song was left (a few seconds back, to get into
 *  it), else 0. Never past the end. */
export function startTime(param, saved, duration = Infinity) {
  const asked = Number(param);
  if (param != null && param !== "" && Number.isFinite(asked) && asked >= 0) return Math.min(asked, duration);
  const left = Number(saved);
  if (Number.isFinite(left) && left > 3 && left < duration - 3) return Math.max(0, left - 2);
  return 0;
}
