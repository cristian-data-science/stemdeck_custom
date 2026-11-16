// Score view, pure part (static/js/score/model.js): note labels, what sounds
// at a time, the cursor between noteheads, and every edit operation.
//
// Notes are shaped as GET /api/jobs/{id}/score/{stem} sends them
// (tests/test_score_api.py).
//
// Run:  node tests/js/score-model.test.mjs

import {
  History,
  SmoothClock,
  monotoneTimeline,
  activeAt,
  buildTimeIndex,
  cleanupTargets,
  cursorAt,
  deleteNotes,
  mergeRepeats,
  moveNotes,
  heldEnd,
  midiName,
  scaleShift,
  shiftInScale,
  playEnd,
  keyChoices,
  neighbour,
  nextBarShift,
  noteLabel,
  pitchName,
  resizeNotes,
  previousOnKey,
  joinNotes,
  moveStart,
  addNote,
  newNoteId,
  snapToOnset,
  pitchOnStaff,
  SAVED_FIELDS,
  savedNotes,
  soundEnd,
  splitChoices,
  toggleHand,
  transpose,
  upperBound,
} from "../../static/js/score/model.js";

let pass = 0,
  fail = 0;
const check = (name, cond, detail = "") => {
  if (cond) {
    pass++;
  } else {
    fail++;
    console.error(`FAIL ${name}`, detail);
  }
};
const eq = (a, b) => JSON.stringify(a) === JSON.stringify(b);

const note = (id, midi, start, end, extra = {}) => ({
  id,
  midi,
  start,
  end,
  velocity: 80,
  hand: null,
  staff: midi >= 60 ? 1 : 2,
  q_start: start,
  q_end: end,
  step_sec: 0.125,
  letter: "C",
  alter: 0,
  octave: 4,
  ...extra,
});

// ── labels ──
check("solfege label", noteLabel({ letter: "G" }) === "sol");
check("letters label", noteLabel({ letter: "G" }, "letters") === "G");
check("label carries its accidental (a key-signature flat is not drawn by the note)", noteLabel({ letter: "B", alter: -1, midi: 70 }) === "si♭");
check("sharp label", noteLabel({ letter: "F", alter: 1, midi: 66 }) === "fa♯" && noteLabel({ letter: "F", alter: 1, midi: 66 }, "letters") === "F♯");
check("C-flat is named by the key it plays: si", noteLabel({ letter: "C", alter: -1, midi: 71 }) === "si");
check("E-sharp says fa, B-sharp says do", noteLabel({ letter: "E", alter: 1, midi: 65 }) === "fa" && noteLabel({ letter: "B", alter: 1, midi: 72 }) === "do");
check("double flat names its key", noteLabel({ letter: "B", alter: -2, midi: 69 }) === "la" && noteLabel({ letter: "E", alter: -2, midi: 62 }, "letters") === "D");
check("Porz Goret: B and B-flat in E-flat minor read si and si♭", noteLabel({ letter: "C", alter: -1, midi: 59 }) === "si" && noteLabel({ letter: "B", alter: -1, midi: 58 }) === "si♭");
check("pitch name flat", pitchName({ letter: "B", alter: -1, octave: 4 }) === "Si♭4");
check("pitch name sharp letters", pitchName({ letter: "C", alter: 1, octave: 5 }, "letters") === "C#5");
check("split choices span C2..C6", splitChoices().length === 49 && splitChoices()[24].label === "do4");

// ── time ──
check("upperBound", upperBound([0, 1, 1, 2], 1) === 3 && upperBound([0, 1], -1) === 0);
const notes = [note("a", 60, 0, 1), note("b", 64, 0.5, 0.75), note("c", 67, 1, 2), note("d", 48, 0, 4)];
const idx = buildTimeIndex(notes);
check("active at 0.6", eq(activeAt(idx, 0.6).sort(), ["a", "b", "d"]));
check("active at 1.0 (end is exclusive)", eq(activeAt(idx, 1.0).sort(), ["c", "d"]));
check("active at 3.9 finds a long note", eq(activeAt(idx, 3.9), ["d"]));
check("active after the end", activeAt(idx, 9).length === 0);

const sysA = {};
const sysB = {};
const tl = [
  { t: 0, x: 100, sys: sysA },
  { t: 1, x: 200, sys: sysA },
  { t: 2, x: 50, sys: sysB },
];
check("cursor interpolates on a system", cursorAt(tl, 0.5).x === 150);
check("cursor holds before a system break", cursorAt(tl, 1.5).x === 200 && cursorAt(tl, 1.5).sys === sysA);
check("cursor jumps to the next system", cursorAt(tl, 2.1).sys === sysB);
check("cursor before the start", cursorAt(tl, -1).x === 100);
check("cursor with no timeline", cursorAt([], 1) === null);

// ── edits ──
const before = JSON.stringify(notes);
check("delete", eq(deleteNotes(notes, ["a", "c"]).map((n) => n.id), ["b", "d"]));
check("transpose up", transpose(notes, ["a"], 1)[0].midi === 61);
check("transpose clamps", transpose([note("x", 107, 0, 1)], ["x"], 12)[0].midi === 108);
const moved = moveNotes(notes, ["a"], 2)[0];
check("move by two steps", moved.start === 0.25 && moved.end === 1.25, moved);
check("move keeps q_* in step for the next press", moved.q_start === 0.25 && moved.q_end === 1.25);
check("move cannot go before zero", moveNotes(notes, ["a"], -5)[0].start === 0);
const twice = moveNotes(moveNotes(notes, ["b"], 1), ["b"], 1)[0 + 1];
check("two presses before the server answers add up", twice.start === 0.75, twice);
check("lengthen", resizeNotes(notes, ["b"], 1)[1].end === 0.875);
check("shorten never below one step", resizeNotes(notes, ["b"], -10)[1].end === 0.625);
check("toggle hand treble -> L", toggleHand(notes, ["a"])[0].hand === "L");
check("toggle hand bass -> R", toggleHand(notes, ["d"])[3].hand === "R");
check("edits never mutate their input", JSON.stringify(notes) === before);
check(
  "saved notes keep only saved fields",
  eq(Object.keys(savedNotes(notes)[0]).sort(), ["end", "hand", "held", "id", "midi", "start", "velocity"]),
);

// ── clean-up ──
const noisy = [note("a", 60, 0, 1), note("b", 61, 1, 1.02, { velocity: 90 }), note("c", 62, 2, 3, { velocity: 10 })];
check("cleanup by duration", eq(cleanupTargets(noisy, { minDurationMs: 50 }), ["b"]));
check("cleanup by velocity", eq(cleanupTargets(noisy, { minVelocity: 20 }), ["c"]));
check("cleanup with zero thresholds removes nothing", cleanupTargets(noisy).length === 0);
const rep = [note("a", 60, 0, 1), note("b", 60, 1.02, 2), note("c", 60, 3, 4)];
const merged = mergeRepeats(rep);
check("merge repeats", eq(merged.map((n) => [n.id, n.end]), [["a", 2], ["c", 4]]), merged);

const dup = [note("a", 60, 0, 0.5), note("b", 60, 0.01, 1)];
check("merge a duplicate at the same onset", eq(mergeRepeats(dup).map((n) => [n.id, n.end]), [["a", 1]]));

// ── navigation & history ──
check("next note in time", neighbour(notes, "a", 1) === "d" || neighbour(notes, "a", 1) === "b");
check("previous from first stays", neighbour(notes, "d", -1) === "d" || neighbour(notes, "d", -1) === "a");
const h = new History(3);
h.push([1]);
h.push([2]);
check("undo returns the previous state", eq(h.undo([3]), [2]));
check("redo returns the undone state", eq(h.redo([2]), [3]));
h.push([4]);
check("a new edit clears redo", !h.canRedo);
for (let i = 0; i < 10; i++) h.push([i]);
check("history is bounded", h.undoStack.length === 3);

// ── key and meter selectors ──
const keys = keyChoices();
check("24 keys", keys.length === 24);
check("B-flat major, not A-sharp", keys.find((k) => k.id === "10:major").label === "Si♭ mayor");
check("B minor id", keys.find((k) => k.id === "11:minor").label === "Si menor");
check("letters", keyChoices("letters").find((k) => k.id === "6:minor").label === "F# minor");
check("bar shift wraps", nextBarShift(0, -1, 4) === 3 && nextBarShift(3, 1, 4) === 0 && nextBarShift(1, 1, 3) === 2);

// ── sound = what is drawn ──
const held = note("h", 43, 0, 6, { draw_end: 1, q_end: 6 });
check("sound end is the drawn end", soundEnd(held) === 1);
check("no draw_end falls back to the raw end", soundEnd(note("x", 60, 0, 2)) === 2);
// ── pedal: a share of the way to where the pedal comes up ──
const ped = note("p", 60, 0, 6, { draw_end: 1, pedal_end: 3 });
check("pedal 0 % plays the drawn note", heldEnd(ped, 0) === 1);
check("pedal 50 % rings half the way", heldEnd(ped, 50) === 2);
check("pedal 100 % rings to the pedal", heldEnd(ped, 100) === 3);
check("a note the pedal does not hold", heldEnd(note("q", 60, 0, 2, { draw_end: 1, pedal_end: null }), 100) === 1);
// ── playback sounds the heard release, not the one-voice drawn cut ──
const arp = note("a", 64, 1.49, 2.09, { draw_end: 1.58, sound_end: 2.09, pedal_end: 2.6 });
check("an arpeggio note rings as the pianist held it", playEnd(arp) === 2.09 && heldEnd(arp, 0) === 2.09);
check("the pedal starts from the heard release", Math.abs(heldEnd(arp, 50) - 2.345) < 1e-9);
check("without sound_end, the drawn end", playEnd(note("o", 60, 0, 6, { draw_end: 1 })) === 1);
const hIdx = buildTimeIndex([held]);
check("a 6 s tail is not lit after its drawn end", activeAt(hIdx, 0.5).length === 1 && activeAt(hIdx, 3).length === 0);
check("lengthen starts from the drawn end", resizeNotes([held], ["h"], 1)[0].end === 1.125);
check("shorten trims the hidden tail", resizeNotes([held], ["h"], -1)[0].end === 0.875);
check("move carries draw_end", moveNotes([held], ["h"], 1)[0].draw_end === 1.125);

// ── cursor: never back within a system, a clock that flows ──
{
  const A = {}, B = {};
  // A measure end drawn past the next measure's start (bbox swollen by a chord name).
  const tl = monotoneTimeline([
    { t: 1.2, x: 3744, sys: A }, { t: 1.199, x: 3893, sys: A }, { t: 1.56, x: 4696, sys: A }, { t: 2.0, x: 100, sys: B },
  ]);
  check("timeline sorted by time", tl.map((p) => p.t).join() === "1.199,1.2,1.56,2");
  check("x never goes back within a system", tl[1].x === 3893 && tl[2].x === 4696);
  check("a new system starts where it starts", tl[3].x === 100);
  let last = -1, back = false;
  for (let t = 1.0; t < 2.2; t += 0.01) {
    const c = cursorAt(tl, t);
    if (c.sys === A && c.x < last) back = true;
    last = c.sys === A ? c.x : -1;
  }
  check("sampled cursor never moves back", !back);

  const clock = new SmoothClock();
  // The audio reports time every 250 ms; frames come every 16 ms.
  let ms = 0, prev = -1, mono = true, maxErr = 0;
  for (let f = 0; f < 600; f++, ms += 16) {
    const real = ms / 1000;
    const reported = Math.floor(real / 0.25) * 0.25;
    const t = clock.update(reported, ms, true, 1);
    if (t < prev) mono = false;
    prev = t;
    if (f > 30) maxErr = Math.max(maxErr, Math.abs(t - real));
  }
  check("smooth clock never runs back while playing", mono);
  check("smooth clock stays within a report step of real time", maxErr < 0.3, maxErr);
  const seek = clock.update(42, ms + 16, true, 1);
  check("a seek is taken as is", seek === 42);
  check("paused: the clock is the audio's", clock.update(10, ms + 32, false) === 10);
}

// ── falling notes (fall.js) ──
{
  const { keyRange, keyboard, octaveLabel, fallingBars, barColor, isBlack, barEnd, nextStrikes } = await import("../../static/js/score/fall.js");
  const k88 = keyboard(21, 108);
  check("88 keys: 52 white, 36 black", k88.keys.length === 88 && k88.whites === 52 && k88.keys.filter((k) => k.black).length === 36);
  check("song range widened to whole octaves C..B", JSON.stringify(keyRange([{ midi: 47 }, { midi: 75 }])) === JSON.stringify([36, 83]));
  check("full range is the 88 keys", JSON.stringify(keyRange([{ midi: 60 }], "full")) === JSON.stringify([21, 108]));
  check("song range stays on the piano", JSON.stringify(keyRange([{ midi: 22 }, { midi: 108 }])) === JSON.stringify([21, 108]));
  check("middle C is C4", octaveLabel(60) === "C4" && octaveLabel(24) === "C1");
  const kb = keyboard(60, 71);
  check("a black key sits between its whites", (() => { const c = kb.byMidi.get(61); return c.black && c.x > 0.5 && c.x + c.w < 1.5; })());
  check("black keys", isBlack(61) && isBlack(70) && !isBlack(64) && !isBlack(72));
  const fn = [
    note("a", 60, 1, 2, { draw_end: 2, sound_end: 2, pedal_end: 3 }),
    note("b", 64, 10, 11, { draw_end: 11, sound_end: 11 }),
  ];
  const at = fallingBars(fn, 0.5);
  check("a note 0.5 s ahead is on screen, not yet sounding", at.length === 1 && Math.abs(at[0].y0 - 0.125) < 1e-9 && !at[0].sounding);
  check("sounding while its key is down", fallingBars(fn, 1.5)[0].sounding);
  // Bars as the score draws the note, not as long as it rings.
  const rung = note("r", 60, 0, 1.2, { draw_end: 0.5, sound_end: 1.2, pedal_end: 3 });
  check("a bar ends where the note is drawn, not where it stops ringing", barEnd(rung) === 0.5 && fallingBars([rung], 0.8).length === 0);
  const rep1 = note("p", 62, 0, 0.5, { draw_end: 0.5, sound_end: 0.5 });
  const rep2 = note("q", 62, 0.5, 1, { draw_end: 1, sound_end: 1 });
  const nx = nextStrikes([rep1, rep2]);
  check("a repeated key reads as two bars, with a gap", Math.abs(barEnd(rep1, nx.get("p")) - 0.44) < 1e-9 && !fallingBars([rep1, rep2], 0.47, nx).find((b) => b.note.id === "p"));
  check("a very short note still shows", barEnd(note("s", 60, 1, 1.001, { draw_end: 1.001 })) === 1.05);
  check("one colour by default, by hand on request", barColor({ staff: 2 }).bar === barColor({ staff: 1 }).bar && barColor({ staff: 2 }, "hands").bar !== barColor({ staff: 1 }, "hands").bar);
  const { paletteFrom, handOf, HAND_COLORS } = await import("../../static/js/score/fall.js");
  check("a hand the user set shows before the server re-engraves", handOf({ staff: 2, hand: "R" }) === "R" && handOf({ staff: 1, hand: "L" }) === "L" && handOf({ staff: 2, hand: null }) === "L");
  check("hand colour follows the user's hand, not the old staff", barColor({ staff: 2, hand: "R" }, "hands").bar === HAND_COLORS.R);
  const pal = paletteFrom("#ff0000");
  check("own colours: a palette from one colour", pal.bar === "#ff0000" && pal.glow === "255,0,0" && pal.hi !== pal.bar && pal.lo !== pal.bar && paletteFrom("nope") === null);
  check("own colours: dark text on a light colour, white on a dark one", paletteFrom("#ffff80").text === "#111111" && paletteFrom("#202060").text === "#ffffff");
  const custom = { R: paletteFrom("#ff0000"), L: paletteFrom("#0000ff") };
  check("own colours are used for each hand", barColor({ staff: 1 }, "hands", custom).bar === "#ff0000" && barColor({ staff: 2 }, "hands", custom).bar === "#0000ff");
  const paint = { hand: "L", ids: new Set(["p1"]) };
  check("a note being painted shows the brush's hand", barColor({ id: "p1", staff: 1 }, "hands", null, paint).bar === HAND_COLORS.L && barColor({ id: "p2", staff: 1 }, "hands", null, paint).bar === HAND_COLORS.R);
  check("painting «Auto» shows the engraved staff, not the user's hand", barColor({ id: "p1", staff: 1, hand: "L" }, "hands", null, { hand: null, ids: new Set(["p1"]) }).bar === HAND_COLORS.R);
}

// ── dragging a note up/down the staff moves it along the key's scale ──
check("C major: E up one is F, down two is C", scaleShift(64, 1, "0:major") === 65 && scaleShift(64, -2, "0:major") === 60);
check("E-flat minor: B-flat up one is C-flat (the key B)", scaleShift(70, 1, "3:minor") === 71);
check("a note outside the scale lands on the next scale note", scaleShift(61, 1, "0:major") === 62 && scaleShift(61, -1, "0:major") === 60);
check("zero steps changes nothing", scaleShift(61, 0, "0:major") === 61);
check("shiftInScale moves only the chosen notes", (() => { const out = shiftInScale([note("a", 60, 0, 1), note("b", 64, 0, 1)], ["b"], 1, "0:major"); return out[0].midi === 60 && out[1].midi === 65; })());
check("deleted-note names", midiName(70, { flats: true }) === "Si♭4" && midiName(70) === "La♯4" && midiName(60, { names: "letters" }) === "C4");
// ── joining two notes on one key (falling-notes view: drag a start down) ──
{
  const two = [
    { ...note("a", 64, 1.0, 1.4), draw_end: 1.4, q_end: 1.4, step_sec: 0.25 },
    { ...note("x", 67, 1.0, 2.0) },
    { ...note("b", 64, 1.5, 2.6), draw_end: 2.5, q_end: 2.5, step_sec: 0.25 },
  ];
  check("the note before on the same key", previousOnKey(two, "b")?.id === "a" && previousOnKey(two, "a") === null);
  const one = joinNotes(two, "a", "b");
  const a = one.find((n) => n.id === "a");
  check("joined: one note, from the first start to the last end", one.length === 2 && !one.some((n) => n.id === "b") && a.start === 1.0 && a.end === 2.6 && a.draw_end === 2.5 && a.q_end === 2.5);
  check("join is the same whichever order it is asked in", JSON.stringify(joinNotes(two, "b", "a")) === JSON.stringify(one));
  check("notes on different keys are not joined", joinNotes(two, "a", "x") === two);
  const moved = moveStart(two, "b", -1);
  check("a start moves by grid steps, its end stays", moved[2].start === 1.25 && moved[2].end === 2.6);
  check("a start never passes its end", moveStart(two, "b", 20)[2].start === 2.25);
}
// ── a length the user set is kept whole ("held") ──
{
  const cut = { ...note("a", 62, 1.0, 2.5), draw_end: 1.3 }; // its hand plays on at 1.3
  check("a note ends where the score draws it", soundEnd(cut) === 1.3);
  check("a held note ends where it was set", soundEnd({ ...cut, held: true }) === 2.5);
  const two = [{ ...note("a", 62, 1.0, 1.4), draw_end: 1.3 }, { ...note("b", 62, 1.5, 2.6), draw_end: 2.0 }];
  const one = joinNotes(two, "a", "b")[0];
  check("joined notes are held, so the join is not cut back", one.held === true && soundEnd(one) === 2.6);
  check("held is saved", SAVED_FIELDS.includes("held"));
}

// ── adding a note ──
{
  const base = [note("a", 60, 1.0, 2.0, { velocity: 60 }), note("b", 64, 1.0, 2.0, { velocity: 100 })];
  const id = newNoteId(base, 1000);
  check("a new id: nu + base 36, never one taken", id === "nu" + (1000).toString(36) && newNoteId([{ id }], 1000) !== id);
  check("the id passes the server's check", /^n[A-Za-z0-9_]{1,24}$/.test(newNoteId(base)));
  const more = addNote(base, { midi: 67, start: 1.0, end: 1.5, hand: "R", id: "nuX" });
  const n = more[2];
  check("added: key, times, hand, held", more.length === 3 && n.midi === 67 && n.start === 1 && n.end === 1.5 && n.hand === "R" && n.held);
  check("added: the loudness of the notes around it", n.velocity === 80 && addNote([], { midi: 60, start: 0, end: 1 })[0].velocity === 80);
  check("added: never shorter than 50 ms", addNote([], { midi: 60, start: 2, end: 1 })[0].end === 2.05);
  check("a tap near a chord joins it", snapToOnset(base, 1.05) === 1.0 && snapToOnset(base, 1.3) === 1.3);
  // Staff positions: steps of half a space above the bottom line.
  check("treble bottom line E4, middle B4, top F5", pitchOnStaff(1, 0) === 64 && pitchOnStaff(1, 4) === 71 && pitchOnStaff(1, 8) === 77);
  check("bass bottom line G2, middle D3; middle C below the treble", pitchOnStaff(2, 0) === 43 && pitchOnStaff(2, 4) === 50 && pitchOnStaff(1, -2) === 60);
  check("the key signature: B♭ in F major, F♯ in G major", pitchOnStaff(1, 4, "5:major") === 70 && pitchOnStaff(1, 8, "7:major") === 78);
  check("A minor: naturals", pitchOnStaff(1, 4, "9:minor") === 71);
}

// ── 3D falling notes: perspective ──
{
  const { depthScale, depthY, depthAt } = await import("../../static/js/score/fall.js");
  check("near notes full size, far ones smaller", depthScale(0) === 1 && depthScale(1) < 0.5);
  check("depth 0 at the keys, depth 1 at the top", depthY(0, 500) === 0 && Math.abs(depthY(1, 500) - 500) < 1e-9);
  check("notes speed up as they come near", depthY(0.1, 500) - depthY(0, 500) > depthY(1, 500) - depthY(0.9, 500));
  check("height <-> depth round trip", [0, 0.2, 0.5, 0.9, 1].every((u) => Math.abs(depthAt(depthY(u, 500), 500) - u) < 1e-9));
}
// ── practice (static/js/score/practice.js) ──
{
  const P = await import("../../static/js/score/practice.js");
  const M = [
    { number: 1, start: 0, end: 2, meter: 4 },
    { number: 2, start: 2, end: 4, meter: 4 },
    { number: 3, start: 4, end: 5.5, meter: 3 },
  ];
  check("bar at a time: inside, on a barline, before the first", P.measureAt(M, 1.9) === 0 && P.measureAt(M, 2) === 1 && P.measureAt(M, -1) === -1);
  const L = P.loopOver(M, 2, 1);
  check("loop over bars in either order", L.a === 2 && L.b === 5.5 && L.from === 2 && L.to === 3);
  check("loop over the selection's bars", JSON.stringify(P.loopOverNotes(M, [{ start: 4.2 }, { start: 0.5 }])) === JSON.stringify(P.loopOver(M, 0, 2)));
  check("loop: back to A only past B, and only when on", P.loopJump({ ...L, on: true }, 5.6) === 2 && P.loopJump({ ...L, on: true }, 5) === null && P.loopJump({ ...L, on: false }, 6) === null);
  check("speeds: only 25, 50, 70 and 100 %", P.SPEEDS.join() === "25,50,70,100");
  check("speeds: a speed saved before is snapped to the nearest", P.snapSpeed(85) === 70 || P.snapSpeed(85) === 100);
  check("speeds: snapped", P.snapSpeed(40) === 50 && P.snapSpeed(60) === 50 && P.snapSpeed(65) === 70 && P.snapSpeed(125) === 100 && P.snapSpeed(10) === 25 && P.snapSpeed("x") === 100);
  check("speed ramp: one step up every N loops, never past 100", P.rampSpeed(25, 1, 1) === 50 && P.rampSpeed(50, 1, 2) === 70 && P.rampSpeed(70, 1, 3) === 100 && P.rampSpeed(100, 1, 4) === 100);
  check("speed ramp: every 2 loops; 0 keeps the speed", P.rampSpeed(50, 2, 1) === 50 && P.rampSpeed(50, 2, 2) === 70 && P.rampSpeed(70, 0, 5) === 70);
  const beats = P.beatsOf(M);
  check("beats: 4 + 4 + 3, the first of each bar accented", beats.length === 11 && beats.filter((b) => b.down).length === 3 && Math.abs(beats[9].t - 4.5) < 1e-9);
  check("seconds of a beat where the song is", P.beatSecondsAt(M, 1) === 0.5 && P.beatSecondsAt(M, 4.5) === 0.5 && P.beatSecondsAt([], 1) === 0.5);
  // In start order, as the page's time index has them.
  const notes = [
    { id: "a", midi: 60, start: 1, staff: 1 },
    { id: "c", midi: 48, start: 1.01, staff: 2 },
    { id: "b", midi: 64, start: 1.03, staff: 1 },
    { id: "d", midi: 62, start: 2, staff: 1 },
  ];
  const c = P.nextChord(notes, 0);
  check("the next chord: notes struck together", c.start === 1 && [...c.keys].sort().join() === "48,60,64");
  check("the next chord of one hand", [...P.nextChord(notes, 0, "R").keys].sort().join() === "60,64" && [...P.nextChord(notes, 0, "L").keys].join() === "48");
  check("the chord after the one played", P.nextChord(notes, 0, null, 1).start === 2 && P.nextChord(notes, 2.5) === null);
  check("a chord is played when every key was struck or is held", P.chordDone(c, new Set([60, 64]), new Map([[48, 90]])) && !P.chordDone(c, new Set([60]), new Map()));
  check("free play: a key on time hits its note, once", P.hitNote(notes, 62, 2.1) === "d" && P.hitNote(notes, 62, 2.5) === null && P.hitNote(notes, 62, 2, null, 0.18, new Set(["d"])) === null);
  check("free play: the other hand's note is not a hit", P.hitNote(notes, 48, 1, "R") === null && P.hitNote(notes, 48, 1, "L") === "c");
  check("where to open: ?t= first, else where it was left, else 0", P.startTime("42.5", 100, 300) === 42.5 && P.startTime(null, 100, 300) === 98 && P.startTime(null, 1, 300) === 0 && P.startTime(null, 299, 300) === 0 && P.startTime("999", 0, 300) === 300);
  const mem = new Map();
  const storage = { getItem: (k) => mem.get(k) ?? null, setItem: (k, v) => mem.set(k, v) };
  P.writeSongPrefs(storage, "abc", "piano", { speed: 70, source: "pianoteq" });
  check("each song remembers its own settings", P.readSongPrefs(storage, "abc", "piano").speed === 70 && JSON.stringify(P.readSongPrefs(storage, "xyz", "piano")) === "{}");
  mem.set("stemdeck.score.song.bad.piano", "{nope");
  check("unreadable prefs are no prefs", JSON.stringify(P.readSongPrefs(storage, "bad", "piano")) === "{}");
  const { gridLines } = await import("../../static/js/score/fall.js");
  const lines = gridLines(M, 1.5, 3);
  check("falling notes: a line per beat in view, numbered on each bar", lines.length === 7 && lines.filter((l) => l.number != null).map((l) => l.number).join() === "2,3" && lines.every((l) => l.u >= 0 && l.u <= 1));
  const { videoKeyHeight } = await import("../../static/js/score/fall.js");
  check("video: 88 keys on 1080p, a key 5.5 times as long as wide (19 % of the screen)", videoKeyHeight(1920, 1080, 52) === Math.round((1920 / 52) * 5.5));
  check("video: the keyboard stays between 12 % and 22 % of the screen", videoKeyHeight(1920, 1080, 15) === Math.round(1080 * 0.22) && videoKeyHeight(800, 1080, 52) === Math.round(1080 * 0.12));
}
// ── undo / redo name what they act on (the buttons, the saved history) ──
{
  const h = new History();
  h.push(["a"], "Movida");
  h.push(["b"], "Borrada");
  check("history: undo is named after the last edit", h.undoLabel === "Borrada" && !h.redoLabel);
  const back = h.undo(["c"]);
  check("history: undo returns the state before it and names it", back.join() === "b" && h.label === "Borrada" && h.redoLabel === "Borrada" && h.undoLabel === "Movida");
  const fwd = h.redo(back);
  check("history: redo the same", fwd.join() === "c" && h.label === "Borrada" && h.undoLabel === "Borrada");
  h.undo(fwd);
  h.push(["d"], "Nota añadida");
  check("history: a new edit clears what could be redone, names and all", !h.canRedo && !h.redoLabel && h.undoLabel === "Nota añadida");
}
// ── «Notas a la vista»: the slider's log scale, 1-20 s ──
{
  const { clampAhead, sliderFromAhead, aheadFromSlider, aheadLabel, AHEAD_MIN, AHEAD_MAX } = await import("../../static/js/score/fall.js");
  check("notas a la vista: the slider's ends are 1 s and 20 s", aheadFromSlider(0) === AHEAD_MIN && aheadFromSlider(100) === AHEAD_MAX);
  check("notas a la vista: 4 s (the default) goes to the slider and back", Math.abs(aheadFromSlider(sliderFromAhead(4)) - 4) <= 0.15);
  check("notas a la vista: every second from 1 to 20 survives the round trip within 4 %", [1, 2, 3, 5, 8, 12, 20].every((v) => Math.abs(aheadFromSlider(sliderFromAhead(v)) - v) / v < 0.04));
  check("notas a la vista: a log scale (1→2 s as wide as 10→20 s)", Math.abs((sliderFromAhead(2) - sliderFromAhead(1)) - (sliderFromAhead(20) - sliderFromAhead(10))) <= 1);
  check("notas a la vista: out of range or nonsense is kept in it", clampAhead(0.2) === 1 && clampAhead(99) === 20 && clampAhead("x") === 4 && clampAhead(undefined) === 4);
  check("notas a la vista: labelled as read", aheadLabel(4) === "4 s" && aheadLabel(2.5) === "2,5 s" && aheadLabel(12.4) === "12 s");
}
// ── edits sound where they now are (before the server answers) ──
{
  const n = { id: "x", midi: 60, start: 1, end: 2, q_start: 1, q_end: 2, draw_end: 2, sound_end: 2.4, pedal_end: 3, step_sec: 0.5 };
  const [m] = moveNotes([n], ["x"], 2);
  check("a moved note's heard end and pedal move with it", m.sound_end === 3.4 && m.pedal_end === 4 && playEnd(m) === 3.4);
  const [r] = resizeNotes([n], ["x"], 1);
  check("a lengthened note sounds as long as it is drawn", r.sound_end === 2.5 && playEnd(r) === 2.5);
}
console.log(`score-model: ${pass} passed, ${fail} failed`);
if (fail) process.exit(1);
