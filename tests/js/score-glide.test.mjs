// The glide after a flick on the falling notes (static/js/score/glide.js).
import assert from "node:assert/strict";
import { test } from "node:test";

import { GLIDE_START, GLIDE_TAU, flickSpeed, glideStep, trackFlick } from "../../static/js/score/glide.js";

/** A drag at `v` song s/s sampled every 16 ms for `ms`. */
function drag(v, ms, t0 = 10) {
  const trail = [];
  for (let at = 0; at <= ms; at += 16) trackFlick(trail, at, t0 + (v * at) / 1000);
  return trail;
}

test("a flick's speed is the finger's over its last moves", () => {
  const trail = drag(12, 400);
  assert.ok(Math.abs(flickSpeed(trail, 400) - 12) < 0.01);
  assert.ok(Math.abs(flickSpeed(drag(-8, 300), 300) + 8) < 0.01); // backwards too
  assert.ok(trail.length <= 8, "only the last ~100 ms are kept");
});

test("a finger that stopped before lifting does not glide", () => {
  const trail = drag(12, 400);
  assert.equal(flickSpeed(trail, 400 + 120), 0);
  assert.equal(flickSpeed([{ at: 0, t: 5 }], 0), 0);
});

test("the glide slows down, travels about v * TAU and stops", () => {
  let t = 10;
  let v = 20;
  let frames = 0;
  for (;;) {
    const s = glideStep(t, v, 1 / 60);
    t = s.t;
    v = s.v;
    frames++;
    if (s.done) break;
  }
  assert.ok(Math.abs(t - 10 - 20 * GLIDE_TAU) < 0.5, `travelled ${t - 10}`);
  assert.ok(frames < 60 * 4, "stops within a few seconds");
  assert.ok(GLIDE_START > 0);
});

test("the glide stops at either end of the song", () => {
  assert.deepEqual(glideStep(0.1, -30, 0.05).done, true);
  assert.equal(glideStep(0.1, -30, 0.05).t, 0);
  const s = glideStep(99.9, 30, 0.05, 100);
  assert.equal(s.done, true);
  assert.equal(s.t, 99.95);
});
