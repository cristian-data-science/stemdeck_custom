// «🎷 Saxo», the pure part (static/js/sax/melody.js): stems to one line, in
// the saxophone's range, written for it, with its fingering.
//
// Run:  node tests/js/sax-melody.test.mjs

import {
  PHRASING,
  SAXES,
  absorbShort,
  dropStrays,
  joinRepeats,
  phrase,
  phrasingOf,
  slur,
  around,
  breaths,
  concertRange,
  fingering,
  fitRange,
  melodyFrom,
  noteGroups,
  noteName,
  phrases,
  pitchColor,
  skyline,
  staffStep,
  written,
} from "../../static/js/sax/melody.js";

let pass = 0;
let fail = 0;
function check(name, ok) {
  if (ok) pass++;
  else {
    fail++;
    console.error(`FAIL ${name}`);
  }
}
const n = (start, end, midi, extra = {}) => ({ start, end, midi, velocity: 80, ...extra });

// ── one line out of chords ──
{
  const line = skyline([n(0, 1, 60), n(0.01, 1, 64), n(0.005, 1, 67), n(0.5, 1.5, 72), n(2, 2.02, 70)]);
  check("skyline: a chord gives its top note", line[0].midi === 67);
  check("skyline: each note ends where the next begins", line[0].end === 0.5 && line[1].start === 0.5);
  check("skyline: a blip is not a note", line.length === 2);
  check("skyline: the drawn length when the model's is longer", skyline([{ start: 0, end: 6, sound_end: 1, midi: 60 }])[0].end === 1);
}

// ── several stems: the first leads, the others fill its silences ──
{
  const voice = [n(0, 1, 72), n(3, 4, 74)];
  const piano = [n(0, 1, 60), n(1.2, 2.5, 64), n(3.5, 5, 65)];
  const m = melodyFrom([{ stem: "vocals", notes: voice }, { stem: "piano", notes: piano }]);
  check("melody: the lead's notes", m.filter((x) => x.stem === "vocals").length === 2);
  check("melody: another stem only where the lead is silent", m.some((x) => x.stem === "piano" && x.midi === 64) && !m.some((x) => x.stem === "piano" && x.midi === 60));
  check("melody: a fill that runs into the lead is cut before it", !m.some((x) => x.stem === "piano" && x.midi === 65 && x.start < 4));
  check("melody: one note at a time", m.every((x, i) => i === 0 || x.start >= m[i - 1].end));
}

// ── the saxophone's range, by phrase ──
{
  check("alto: written a major sixth up (Eb)", written(60, "alto") === 69 && SAXES.alto.shift === 9);
  check("tenor: a major ninth up (Bb)", written(60, "tenor") === 74);
  const { low, high } = concertRange("alto");
  check("alto: sounds Db3 to D6... written Bb3 to F6", low === 49 && high === 80);
  // A phrase two octaves too low: moved up as a whole (its shape kept).
  const low2 = [n(0, 0.5, 30), n(0.5, 1, 34), n(1, 1.5, 37)];
  const f = fitRange(low2, "alto");
  check("range: a whole phrase moves by the same octaves", f.every((x) => x.octave === f[0].octave) && f[0].midi - f[1].midi === -4);
  check("range: inside the saxophone after", f.every((x) => x.midi >= low && x.midi <= high));
  check("range: the sounding pitch kept", f[0].concert === 30);
  // Two phrases far apart move each on their own.
  const two = fitRange([n(0, 0.5, 30), n(5, 5.5, 72)], "alto");
  check("range: each phrase on its own", two[0].octave >= 2 && two[1].octave === 0);
  check("phrases: a gap of 0.6 s ends one", phrases([n(0, 1, 60), n(1.2, 2, 62), n(3, 4, 64)]).length === 2);
  check("breaths: where a gap is", breaths([n(0, 1, 60), n(1.1, 2, 62), n(2.5, 3, 64)]).join() === "2");
}

// ── names, the staff, colours ──
{
  check("names: solfège and letters", noteName(67) === "Sol4" && noteName(70, { names: "letters" }) === "B♭4" && noteName(61, { octave: false }) === "Do♯");
  check("staff: E4 on the bottom line, F5 on the top one", staffStep(64) === 0 && staffStep(77) === 8);
  check("staff: C♯ on C, E♭ on E", staffStep(61) === staffStep(60) && staffStep(63) === staffStep(64));
  check("staff: middle C one ledger line below", staffStep(60) === -2);
  check("colours: one per pitch class, the same in any octave", pitchColor(60) === pitchColor(72) && pitchColor(60) !== pitchColor(62));
}

// ── fingering ──
{
  check("fingering: G4 is the left hand", fingering(67).join() === "L1,L2,L3");
  check("fingering: low Bb, every key down", fingering(58).join() === "L1,L2,L3,Bb,R1,R2,R3,C");
  check("fingering: C#5 is all open", fingering(73).length === 0);
  check("fingering: the upper octave adds the octave key", fingering(79).join() === "oct,L1,L2,L3");
  check("fingering: high F with the palm keys", fingering(89).join() === "oct,pD,pEb,sE,pF");
  check("fingering: Bb4 with the bis key", fingering(70).join() === "L1,bis");
  check("fingering: every written note in the range has one", Array.from({ length: 32 }, (_, i) => 58 + i).every((w) => Array.isArray(fingering(w))));
  check("fingering: none outside it", fingering(57) === null && fingering(90) === null);
}

// ── what sounds now, and next ──
{
  const notes = [n(0, 1, 60), n(1, 2, 62), n(3, 4, 64)];
  const a = around(notes, 1.5, 3);
  check("around: the note sounding, first of the next ones", a.current.midi === 62 && a.next.map((x) => x.midi).join() === "62,64");
  const b = around(notes, 2.5, 3);
  check("around: in a rest nothing sounds, the next one is coming", b.current === null && b.next[0].midi === 64);
}

// ── phrasing: a line a saxophonist would play ──
{
  const held = [n(0, 0.3, 64), n(0.35, 0.6, 64), n(0.62, 1.0, 64), n(1.4, 1.8, 64)];
  check("phrasing: one held note, not its pieces", joinRepeats(held, 0.16).map((x) => [x.start, x.end].join("-")).join() === "0-1,1.4-1.8");
  const stray = [n(0, 0.5, 62), n(0.5, 0.65, 77), n(0.65, 1.2, 64), n(1.2, 1.4, 52), n(1.4, 2, 65)];
  const kept = dropStrays(stray, PHRASING.voice);
  check("phrasing: a short note far above the line goes", !kept.some((x) => x.midi === 77));
  check("phrasing: an octave slip below comes back up", kept.some((x) => x.midi === 64 && x.start === 1.2));
  check("phrasing: a long note far away stays (a real leap)", dropStrays([n(0, 0.5, 62), n(0.5, 1.5, 77), n(1.5, 2, 64)], PHRASING.voice).length === 3);
  const grace = absorbShort([n(0, 0.5, 60), n(0.5, 0.56, 61), n(0.56, 1, 62), n(3, 3.05, 70)], 0.11);
  check("phrasing: a grace note joins the note before; one on its own goes", grace.length === 2 && grace[0].end === 0.56);
  const sl = slur([n(0, 0.5, 60), n(0.58, 1, 62), n(1.5, 2, 64)], 0.12);
  check("phrasing: a small gap is slurred, a breath is not", sl[0].end === 0.58 && sl[1].legato === true && sl[1].end === 1 && !sl[2].legato);
  check("phrasing: voices slur less than a keyboard's comping", phrasingOf("vocals").join < phrasingOf("piano").join);
  const scoop = absorbShort([n(0, 0.5, 65), n(0.5, 0.6, 68), n(0.6, 1.2, 69)], 0.13);
  check("phrasing: a scoop up into a note is that note's start, not the end of the one before", scoop.length === 2 && scoop[0].end === 0.5 && scoop[1].start === 0.5 && scoop[1].midi === 69);
  {
    const run = [n(0, 0.2, 60), n(0.2, 0.4, 62), n(1.2, 1.4, 64)];
    for (let i = 0; i < 23; i++) run.push(n(2 + i * 0.2, 2 + i * 0.2 + (i === 15 ? 0.05 : 0.18), 60 + (i % 5)));
    const gs = noteGroups(run);
    check("strip: a breath starts a new group", gs[0].length === 2 && gs[1].length === 1);
    check("strip: a long run is cut, never more than 10 at once", gs.every((g) => g.length <= 10) && gs.flat().length === run.length);
    check("strip: each note knows its group", run.every((x) => gs[x.g].includes(x)));
  }
  check("phrasing: a tracked line (a saxophone in Otros) is phrased as a voice", phrasingOf("other", true) === PHRASING.voice && phrasingOf("other") === PHRASING.other);
  const choppy = [];
  for (let i = 0; i < 20; i++) choppy.push(n(i * 0.2, i * 0.2 + 0.15, i < 10 ? 67 : 69));
  const p = phrase(choppy, PHRASING.voice);
  check("phrasing: a stuttered phrase becomes its two notes, slurred", p.length === 2 && p[1].legato === true);
}

// ── the microphone: YIN on a saxophone-like tone ──
{
  const { yin, hzToMidi, judge } = await import("../../static/js/sax/mic.js");
  const sr = 48000;
  const tone = (hz, n = 2048, noise = 0) => Float32Array.from({ length: n }, (_, i) => {
    let v = 0;
    for (let k = 1; k <= 8; k++) v += Math.sin((2 * Math.PI * hz * k * i) / sr) / k; // reedy: rich in harmonics
    return 0.3 * v + noise * (Math.random() * 2 - 1);
  });
  for (const hz of [138.59, 233.08, 440, 698.46, 1046.5]) {
    const r = yin(tone(hz), sr);
    check(`mic: ${hz} Hz read within 5 cents`, r && Math.abs(1200 * Math.log2(r.hz / hz)) < 5);
  }
  check("mic: with some breath noise still right", Math.abs(hzToMidi(yin(tone(440, 2048, 0.05), sr).hz) - 69) < 0.1);
  check("mic: silence is no pitch", yin(new Float32Array(2048), sr) === null);
  check("mic: 20 cents sharp is right, 70 is not", judge(69.2, 69).ok && !judge(69.7, 69).ok);
  check("mic: the right note an octave up is said so", judge(81.1, 69).octave === 1 && !judge(81.1, 69).ok);
}

console.log(`sax-melody: ${pass} passed, ${fail} failed`);
if (fail) process.exit(1);
