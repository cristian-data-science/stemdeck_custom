// The song's beats and bars for «🎷 Saxo» (no DOM; tests/js/sax-beats.test.mjs):
// from the beat grid the studio keeps (GET /api/jobs/<id>/beats: the beats'
// times, and bar marks {beat: index of a downbeat, beats_per_bar}), which
// beats start a bar and the number of each bar.

/**
 * @param {{beats?: number[], bars?: {beat: number, beats_per_bar: number}[]}} grid
 * @returns {{times: number[], down: boolean[], bar: number[], per: number[]}|null}
 *   per beat: its time, whether it starts a bar, the bar it is in (1 = the
 *   first whole bar; 0 = the pickup before it) and that bar's beats.
 */
export function barGrid(grid) {
  const times = (grid?.beats || []).filter((t) => Number.isFinite(t));
  if (times.length < 2) return null;
  const marks = (grid.bars || [])
    .filter((b) => Number.isInteger(b?.beat) && Number.isInteger(b?.beats_per_bar) && b.beats_per_bar >= 1)
    .sort((a, b) => a.beat - b.beat);
  const down = new Array(times.length).fill(false);
  const per = new Array(times.length).fill(0);
  if (marks.length) {
    for (let i = 0; i < times.length; i++) {
      // The mark at or before this beat; before the first one, that one
      // counted backwards (the song's pickup).
      let mark = marks[0];
      for (const m of marks) {
        if (m.beat <= i) mark = m;
        else break;
      }
      const off = (((i - mark.beat) % mark.beats_per_bar) + mark.beats_per_bar) % mark.beats_per_bar;
      down[i] = off === 0;
      per[i] = mark.beats_per_bar;
    }
  }
  const bar = new Array(times.length).fill(0);
  let n = 0;
  for (let i = 0; i < times.length; i++) {
    if (down[i]) n += 1;
    bar[i] = n;
  }
  return { times, down, bar, per };
}

/** The index of the last beat at or before `t` (-1 before the first). */
export function beatIndexAt(times, t) {
  let lo = 0;
  let hi = times.length - 1;
  let at = -1;
  while (lo <= hi) {
    const mid = (lo + hi) >> 1;
    if (times[mid] <= t + 1e-6) {
      at = mid;
      lo = mid + 1;
    } else hi = mid - 1;
  }
  return at;
}

/** The start of the bar `t` is in and the start of the next one (the song's
 *  end after the last): [a, b]. Without bars, the beat's own span. */
export function barSpanAt(g, t, end = Infinity) {
  if (!g) return null;
  const i = Math.max(0, beatIndexAt(g.times, t));
  let a = i;
  while (a > 0 && !g.down[a]) a -= 1;
  let b = i + 1;
  while (b < g.times.length && !g.down[b]) b += 1;
  if (!g.down.some(Boolean)) {
    a = i;
    b = i + 1;
  }
  return [g.times[a], b < g.times.length ? g.times[b] : Math.max(end, g.times[g.times.length - 1])];
}

/** Seconds a beat lasts around `t` (the tempo there). */
export function beatSecondsAt(g, t, fallback = 0.5) {
  if (!g) return fallback;
  const i = Math.min(g.times.length - 2, Math.max(0, beatIndexAt(g.times, t)));
  const d = g.times[i + 1] - g.times[i];
  return d > 0.15 && d < 2 ? d : fallback;
}
