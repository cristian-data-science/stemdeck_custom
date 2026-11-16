// The glide after a flick on the falling notes: let go while moving and the
// song keeps going, slowing down, like a feed scrolled with a flick. Pure (no
// DOM): main.js runs it on requestAnimationFrame. Speeds in song seconds per
// second of real time.

export const GLIDE_SAMPLE_MS = 100; // the finger's speed over its last this-many ms
export const GLIDE_STILL_MS = 80; // the finger stood still this long before letting go: no glide
export const GLIDE_START = 1.5; // slower than this, letting go just stops
export const GLIDE_MIN = 0.4; // the glide ends below this
export const GLIDE_MAX = 60;
export const GLIDE_TAU = 0.6; // s: the speed falls to 37 % in this time (travel ≈ v * TAU)

/** Keep the trail of a drag ([{at: ms, t: song s}]) to its last moves. */
export function trackFlick(trail, at, t) {
  trail.push({ at, t });
  while (trail.length > 2 && at - trail[0].at > GLIDE_SAMPLE_MS) trail.shift();
  return trail;
}

/** The song's speed under the finger when it let go, from its last moves;
 *  0 if it had stopped before lifting or moved too little to tell. */
export function flickSpeed(trail, now) {
  if (trail.length < 2) return 0;
  const last = trail[trail.length - 1];
  if (now - last.at > GLIDE_STILL_MS) return 0;
  const first = trail.find((p) => last.at - p.at <= GLIDE_SAMPLE_MS);
  const ms = last.at - first.at;
  if (ms < 10) return 0;
  const v = ((last.t - first.t) / ms) * 1000;
  return Math.max(-GLIDE_MAX, Math.min(GLIDE_MAX, v));
}

/** One frame of the glide: from song time `t` at speed `v`, `dt` seconds
 *  later. Ends (done) when slow enough or at either end of the song. */
export function glideStep(t, v, dt, end = Infinity) {
  const next = Math.max(0, Math.min(end - 0.05, t + v * dt));
  const nv = v * Math.exp(-dt / GLIDE_TAU);
  return { t: next, v: nv, done: Math.abs(nv) < GLIDE_MIN || next <= 0 || next >= end - 0.05 };
}
