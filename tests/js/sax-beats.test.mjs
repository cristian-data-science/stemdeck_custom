// «🎷 Saxo»: the song's beats and bars (static/js/sax/beats.js).
//
// Run:  node tests/js/sax-beats.test.mjs

import { barGrid, barSpanAt, beatIndexAt, beatSecondsAt } from "../../static/js/sax/beats.js";

let pass = 0;
let fail = 0;
function check(name, ok, detail = "") {
  if (ok) pass++;
  else {
    fail++;
    console.log(`FAIL  ${name}${detail ? `  -- ${detail}` : ""}`);
  }
}

// Beats every 0.5 s from 0.25; the first downbeat is the third beat (a
// pickup of two), bars of 4.
const beats = Array.from({ length: 14 }, (_, i) => 0.25 + i * 0.5);
const g = barGrid({ beats, bars: [{ beat: 2, beats_per_bar: 4 }] });
check("downbeats every 4 from the mark, the pickup counted backwards", g.down.map((d) => (d ? 1 : 0)).join("") === "00100010001000", g.down.join());
check("bar numbers: 0 for the pickup, then 1, 2, 3", g.bar.join("") === "00111122223333", g.bar.join());
check("each beat knows its bar's length", g.per.every((p) => p === 4));

// A change of metre: 3 beats a bar from the 10th beat.
const g2 = barGrid({ beats, bars: [{ beat: 2, beats_per_bar: 4 }, { beat: 10, beats_per_bar: 3 }] });
check("a second mark changes the bar length from there", g2.down.map((d) => (d ? 1 : 0)).join("") === "00100010001001", g2.down.join());

check("no bars: beats only, none a downbeat", barGrid({ beats }).down.every((d) => !d));
check("no beats: nothing", barGrid({ beats: [1] }) === null && barGrid(null) === null);

check("the beat at a time", beatIndexAt(beats, 0.1) === -1 && beatIndexAt(beats, 0.25) === 0 && beatIndexAt(beats, 1.3) === 2 && beatIndexAt(beats, 99) === 13);
const span = barSpanAt(g, 2.0);
check("the bar a moment is in: from its downbeat to the next", span[0] === 1.25 && span[1] === 3.25, span.join());
check("the last bar ends with the song", barSpanAt(g, 6.5, 8)[1] === 8);
check("without bars: the beat's own span", barSpanAt(barGrid({ beats }), 1.3).join() === "1.25,1.75");
check("the tempo there", beatSecondsAt(g, 3) === 0.5 && beatSecondsAt(null, 3, 0.6) === 0.6);

console.log(`sax-beats: ${pass} passed, ${fail} failed`);
if (fail) process.exit(1);
