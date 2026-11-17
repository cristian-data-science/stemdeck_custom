// «🎷 Saxo»: part of a song (one stem, or several: voice and piano...) turned
// into a saxophone line. The notes fly in from the right along a staff
// written for the chosen saxophone; the horn on the left lights the keys of
// the note sounding (and rings the next one's); the next notes are named on
// top. It plays with a synthesised saxophone over the rest of the song.
//
// /sax/?job=<id>&stems=vocals,piano   (the first stem leads; the others fill
// its silences). Notes from the score module (GET /api/jobs/{id}/score/{stem},
// transcribed on demand); the rest of the song from /api/jobs/{id}/sax/backing.flac.

import { SmoothClock } from "../score/model.js";
import { buildChart } from "./chart.js";
import { buildHorn } from "./horn.js";
import { HIT_X, SaxLane } from "./lane.js";
import { barGrid, barSpanAt, beatIndexAt, beatSecondsAt } from "./beats.js";
import { SAXES, around, breaths, fingering, concertRange, fitRange, melodyFrom, noteGroups, noteName, phrase, phrasingOf, pitchColor, skyline, slur, staffStep, written } from "./melody.js";
import { MicPitch, judge } from "./mic.js";
import { SaxSampler, SaxSynth } from "./synth.js";

const $ = (id) => document.getElementById(id);
const params = new URLSearchParams(location.search);
const JOB = params.get("job");
const LS = "stemdeck.sax";
// Stems the score module transcribes (app/score/engines.py), the voice first.
const SAXABLE = ["vocals", "lead_vocals", "backing_vocals", "piano", "guitar", "other", "bass"];
const STEM_NAMES = { vocals: "Voz", lead_vocals: "Voz principal", backing_vocals: "Coros", piano: "Piano", guitar: "Guitarra", other: "Otros", bass: "Bajo" };
const STEM_TIPS = {
  other: "Otros: aquí quedan el saxo, los vientos, las cuerdas y los sintetizadores (el separador no tiene un stem propio para ellos). Su instrumento principal se sigue nota a nota, como una voz",
};
// Stems whose line the server tracks (/sax/line): the voices, and "other"
// (its lead instrument: a saxophone, a trumpet... with RMVPE).
const TRACKED = new Set(["vocals", "lead_vocals", "backing_vocals", "other"]);
const MIN_PRESENCE = 20; // a voice quieter than this (stem_presence %): an instrumental

const prefs = { engine: "swam", horn: "chart", sax: "alto", names: "solfege", view: "written", phrasing: "clean", expression: "expressive", sound: "sax-rest", volSax: 80, volRest: 70, ahead: 5, speed: 100, ...readPrefs() };
const state = {
  stems: (params.get("stems") || "").split(",").filter((s) => SAXABLE.includes(s)),
  available: [],
  scores: new Map(), // stem -> notes
  notes: [],
  playing: false,
  scheduledUntil: 0,
  shown: "", // the note shown in the readout and strip (redrawn on change only)
};
window.__sax = state;

const audio = $("sx-audio");
const lane = new SaxLane($("sx-lane"));
// «Digitación»: the big chart (chart.js), or the photograph (horn.js, the
// first one) to go back to.
let horn = null;
function makeHorn() {
  const chart = prefs.horn !== "photo";
  horn = chart ? buildChart($("sx-horn")) : buildHorn($("sx-horn"));
  document.body.classList.toggle("sx-horn-chart", chart);
  // One button between the two: the chart by default, the photograph (the
  // first view) to go back to.
  $("sx-horn-switch").textContent = chart ? "🖼 Ver foto" : "▦ Ver diagrama";
  $("sx-horn-switch").setAttribute("aria-pressed", String(!chart));
  state.shown = "";
}
makeHorn();
const clock = new SmoothClock();
let ctx = null;
let synth = null; // the synthesised saxophone: only while the recorded one loads
let sampler = null; // the recorded saxophone (University of Iowa MIS)
let singer = null; // the same, without vibrato: «Expresivo» plays the voice's own
const instrument = () => (sampler?.ready ? sampler : synth);

function readPrefs() {
  try {
    return JSON.parse(localStorage.getItem(LS) || "{}");
  } catch {
    return {};
  }
}
const savePrefs = () => localStorage.setItem(LS, JSON.stringify(prefs));

async function api(url, opts = {}) {
  const res = await fetch(url, opts);
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data.detail || res.statusText);
  return data;
}

const formatTime = (s) => `${Math.floor((s || 0) / 60)}:${String(Math.floor((s || 0) % 60)).padStart(2, "0")}`;

function status(text) {
  $("sx-status").hidden = !text;
  $("sx-status").textContent = text || "";
}

// ── which stems ─────────────────────────────────────────────────────────

function renderStems() {
  const box = $("sx-stems");
  box.innerHTML = "";
  for (const stem of state.available) {
    const b = document.createElement("button");
    b.type = "button";
    b.dataset.stem = stem;
    b.textContent = STEM_NAMES[stem] || stem;
    if (STEM_TIPS[stem]) b.title = STEM_TIPS[stem];
    const i = state.stems.indexOf(stem);
    b.setAttribute("aria-pressed", String(i >= 0));
    if (i >= 0 && state.stems.length > 1) b.dataset.order = String(i + 1);
    b.onclick = () => {
      state.stems = i >= 0 ? state.stems.filter((s) => s !== stem) : [...state.stems, stem];
      renderStems();
      const url = new URL(location.href);
      url.searchParams.set("stems", state.stems.join(","));
      history.replaceState(null, "", url);
      load();
    };
    box.append(b);
  }
}

const VOICES = new Set(["vocals", "lead_vocals", "backing_vocals"]);

/** A stem's line: {notes, cents}. Transcribed now if the score module has
 *  not yet; a voice's notes then checked against a pitch tracker on the
 *  server (/sax/line: a transcription model alone misread 15 % of a sung
 *  line), and the stem's tuning, which the saxophone plays at. */
async function scoreOf(stem, say) {
  if (TRACKED.has(stem)) {
    // Straight to the voice's line: the server transcribes and tracks it at
    // once (~15 s the first time; made in the background after a separation).
    say(`Sacando la melodía de ${STEM_NAMES[stem] || stem}… (la primera vez, unos segundos)`);
    try {
      const line = await api(`/api/jobs/${JOB}/sax/line/${stem}`);
      return { notes: line.notes || [], cents: line.cents || 0, contour: line.contour || null, engine: line.engine, tracked: true };
    } catch {
      /* the score's transcription below */
    }
  }
  const url = `/api/jobs/${JOB}/score/${stem}`;
  let data = await api(url);
  if (data.status?.state === "none" || data.status?.state === "error") {
    data = await api(url, { method: "POST" });
  }
  while (data.status && data.status.state !== "done") {
    if (data.status.state === "error") throw new Error(data.status.error || "no se pudo transcribir");
    const pct = Math.round((data.status.progress || 0) * 100);
    say(`Escuchando ${STEM_NAMES[stem] || stem} para sacar sus notas… ${pct ? `${pct} %` : ""}`);
    await new Promise((r) => setTimeout(r, 1500));
    data = await api(url);
  }
  if (VOICES.has(stem)) {
    say(`Afinando la línea de ${STEM_NAMES[stem] || stem} nota por nota… (la primera vez, menos de un minuto)`);
    try {
      const line = await api(`/api/jobs/${JOB}/sax/line/${stem}`);
      return { notes: line.notes || [], cents: line.cents || 0 };
    } catch {
      /* the transcription alone, as before */
    }
  }
  // A piano's melody is in its right hand (the treble staff, from the hands
  // model): the top note of both hands let the left hand's bass and chords in
  // (on «Y dime» 48 strays, 10 with the right hand alone).
  let notes = data.notes || [];
  if (stem === "piano" && notes.some((n) => n.staff === 1) && notes.some((n) => n.staff === 2)) {
    notes = notes.filter((n) => n.staff === 1);
  }
  return { notes, cents: data.stats?.tuning?.cents || 0 };
}

let loadTicket = 0;
async function load() {
  const ticket = ++loadTicket;
  stopSound();
  if (!state.stems.length) {
    state.notes = [];
    lane.set([]);
    status("Elige arriba qué parte de la canción toca el saxo (por ejemplo Voz, o Voz y Piano).");
    updateBacking();
    return;
  }
  try {
    for (const stem of state.stems) {
      if (!state.scores.has(stem)) state.scores.set(stem, await scoreOf(stem, status));
      if (ticket !== loadTicket) return;
    }
  } catch (e) {
    status(`No se pudieron sacar las notas: ${e.message}`);
    return;
  }
  status("");
  rebuild();
  updateBacking();
}

/** The line for the stems chosen and the saxophone: one note at a time, in
 *  its range, with breath marks. */
function rebuild() {
  // «Ligado»: each stem phrased as a saxophonist would (one held note, not
  // its pieces; no grace notes or strays; small gaps slurred), then the
  // stems together, slurred again. «Todas las notas»: as transcribed.
  const clean = prefs.phrasing !== "all";
  const parts = state.stems.map((stem) => {
    const notes = state.scores.get(stem)?.notes || [];
    return { stem, notes: clean ? phrase(skyline(notes), phrasingOf(stem, state.scores.get(stem)?.tracked)) : notes };
  });
  let line = melodyFrom(parts);
  if (clean) line = slur(line, phrasingOf(state.stems[0], state.scores.get(state.stems[0])?.tracked).legato);
  state.notes = applyEdits(fitRange(line, prefs.sax));
  // The saxophone plays at the song's tuning (the lead stem's): at A440 it
  // sounded out of tune against a recording a few cents off.
  state.cents = state.scores.get(state.stems[0])?.cents || 0;
  for (const inst of [synth, sampler]) if (inst) inst.cents = state.cents;
  lane.set(state.notes, { sax: prefs.sax, names: prefs.names, breaths: breaths(state.notes), lookahead: prefs.ahead, concert: prefs.view === "concert" });
  state.groups = noteGroups(state.notes);
  state.version = (state.version || 0) + 1;
  state.shown = "";
  const moved = state.notes.filter((n) => n.octave).length;
  const w = state.notes.map((n) => written(n.midi, prefs.sax));
  $("sx-stats").textContent = state.notes.length
    ? `${state.notes.length} notas · de ${noteName(Math.min(...w), { names: prefs.names })} a ${noteName(Math.max(...w), { names: prefs.names })}` +
      (moved ? ` · ${moved} movidas de octava (8↑/8↓) para que entren en el saxo` : "")
    : "";
  $("sx-sub").textContent = `${SAXES[prefs.sax].name} · toca ${state.stems.map((s) => STEM_NAMES[s] || s).join(" + ")}` + (state.hint ? ` · ${state.hint}` : "");
  showEdit();
  // A part that leaps all the time is an accompaniment (chords, arpeggios),
  // not a melody: said, so nobody practises it as one.
  const lead = state.stems[0];
  const own = state.notes.filter((n) => n.stem === lead);
  const leaps = own.slice(1).filter((n, i) => Math.abs(n.concert - own[i].concert) >= 7).length;
  const leapy = own.length > 20 ? leaps / (own.length - 1) : 0;
  $("sx-warn").hidden = leapy < 0.35;
  $("sx-warn").textContent = `⚠ ${STEM_NAMES[lead] || lead} salta mucho (${Math.round(leapy * 100)} % de saltos grandes): parece acompañamiento, no melodía.` +
    (state.available.some((s) => VOICES.has(s)) && !VOICES.has(lead) ? " La melodía suele estar en la Voz." : "");
  if (!state.notes.length) status("Esta parte no tiene notas que el saxo pueda tocar.");
  swamSoon();
}

// ── sound ───────────────────────────────────────────────────────────────

/** What plays under the saxophone: the song without the stems it plays
 *  (or the whole song to compare). Without anything else (a solo piano), the
 *  song plays silent, as the clock. */
function updateBacking() {
  const t = audio.currentTime || state.t || 0;
  // Changing the source stops the audio without a "pause" event, and a time
  // set before the new file loads is lost: the page went on as if playing
  // (its clock running on its own) and ▶ no longer answered. Remembered,
  // and resumed once the new file can play.
  const wasPlaying = !audio.paused;
  const original = prefs.sound === "original";
  const mix = `/api/jobs/${JOB}/score/audio/mix.flac`;
  // In order: what is asked for; then the whole song, silent; then the
  // stem itself, silent (a song with only a piano has neither of the others).
  const urls = [
    original || !state.stems.length ? mix : `/api/jobs/${JOB}/sax/backing.flac?without=${encodeURIComponent(state.stems.join(","))}`,
    mix,
    ...state.stems.map((s) => `/api/jobs/${JOB}/score/audio/${s}.flac`),
  ];
  let k = 0;
  state.backingSilent = false;
  const tryNext = () => {
    if (k >= urls.length) return status("No hay audio de esta canción para reproducir.");
    const url = urls[k++];
    state.backingSilent = k > 1;
    applyVolumes();
    if (!audio.src.endsWith(url)) {
      stopSound();
      audio.src = url;
      audio.addEventListener(
        "loadedmetadata",
        () => {
          // A seek asked for while it loaded wins over where it was.
          const at = state.pendingT ?? (audio.currentTime || t);
          state.pendingT = null;
          audio.currentTime = Math.min(at, Math.max(0, (audio.duration || at) - 0.05));
          if (wasPlaying || state.wantPlay) audio.play().catch(() => {});
          state.wantPlay = false;
        },
        { once: true },
      );
    }
  };
  audio.onerror = tryNext;
  tryNext();
}

function applyVolumes() {
  const original = prefs.sound === "original";
  audio.volume = state.backingSilent ? 0 : original ? 1 : prefs.sound === "sax" ? 0 : prefs.volRest / 100;
  for (const inst of [synth, sampler, singer]) if (inst) inst.volume = original ? 0 : prefs.volSax / 100;
}

/** The audio graph, made at once (it starts suspended until a tap) so the
 *  recorded saxophone loads while the page opens. */
function ensureAudio({ resume = true } = {}) {
  if (!ctx) {
    ctx = new (window.AudioContext || window.webkitAudioContext)();
    synth = new SaxSynth(ctx);
    sampler = new SaxSampler(ctx);
    singer = new SaxSampler(ctx);
    synth.cents = sampler.cents = state.cents || 0;
    applyVolumes();
    loadSamples();
  }
  if (resume && ctx.state === "suspended") ctx.resume();
}

let samplesFor = "";
async function loadSamples() {
  if (!sampler || samplesFor === prefs.sax) return;
  samplesFor = prefs.sax;
  const el = $("sx-sound-state");
  try {
    await sampler.load(prefs.sax, (f) => {
      el.textContent = `Cargando el saxo real… ${Math.round(f * 100)} %`;
    });
    await singer.load(prefs.sax, (f) => {
      el.textContent = `Cargando el saxo expresivo… ${Math.round(f * 100)} %`;
    }, "-novib");
    el.textContent = `🎷 Saxo real (grabado)${prefs.sax === "tenor" || prefs.sax === "baritone" ? " · voz de alto transpuesta" : ""}`;
    el.title = "Grabaciones nota por nota de un saxofón (Michael Giles, University of Iowa Musical Instrument Samples): con vibrato, en tres intensidades";
    stopSound(); // what was scheduled on the synthesiser goes on with the recording
  } catch (e) {
    samplesFor = "";
    el.textContent = "Saxo sintetizado (no se pudo cargar el grabado)";
  }
}

function stopSound() {
  synth?.stopAll();
  sampler?.stopAll();
  singer?.stopAll();
  state.scheduledUntil = audio.currentTime || 0;
  state.resume = true;
}

const expressive = () => prefs.expression !== "exact" && singer?.ready;

/** «Expresivo»: a sung note's pitch and loudness as the voice did them
 *  (from the server's contour, every 20 ms), moved by the octaves the line
 *  was (fitRange), held within 2 semitones of the note (a tracker glitch
 *  never becomes a wild bend). null for a note without a contour (a piano). */
function curveOf(n, rate) {
  const c = state.scores.get(n.stem)?.contour;
  if (!c?.midi?.length) return null;
  // An edited note: the contour where it was sung, moved where it was put.
  const base = n.orig?.concert ?? n.concert ?? n.midi;
  const from = n.orig?.start ?? n.start;
  const shift = n.midi - base;
  const steps = Math.max(2, Math.ceil((n.end - n.start) / c.hop) + 1);
  // A note made longer: past where it was played the recording goes on to
  // a rest or the next notes; the note is held there instead (its pitch
  // settling on the note, its last level), one long note, not pieces.
  const own = Math.max(1, Math.round(((n.orig?.end ?? n.end) - from) / c.hop) + 1);
  const midi = new Float32Array(steps);
  const level = new Float32Array(steps);
  let last = base;
  let lastLevel = 0.6;
  for (let k = 0; k < steps; k++) {
    if (k >= own) {
      last = base + (last - base) * 0.8;
      midi[k] = last + shift;
      level[k] = lastLevel;
      continue;
    }
    const i = Math.min(c.midi.length - 1, Math.round((from + k * c.hop) / c.hop));
    const m = c.midi[i];
    if (m != null) last = Math.min(base + 2, Math.max(base - 2, m));
    midi[k] = last + shift;
    level[k] = lastLevel = c.level[i] ?? 0.6;
  }
  return { midi, level, step: c.hop / rate };
}

/** The saxophone, scheduled a little ahead of the song's clock. After a
 *  play or a seek (state.resume) a note already sounding plays its rest. */
function schedule(t) {
  const synth = instrument();
  if (!synth || !state.playing) return;
  if (swamActive()) {
    state.scheduledUntil = t;
    return;
  }
  const rate = audio.playbackRate || 1;
  const from = state.scheduledUntil;
  const until = t + 0.3 * rate;
  for (const n of state.notes) {
    if (n.end <= from) continue;
    if (n.start >= until) break;
    if (n.start < from) {
      if (state.resume && n.end > t + 0.05) synth.play(n.midi, ctx.currentTime, (n.end - t) / rate, n.velocity);
      continue;
    }
    const when = ctx.currentTime + Math.max(0, (n.start - t) / rate);
    // Slurred notes run into each other (no gap, no new attack).
    const dur = ((n.end - n.start) / rate) * (n.legato || state.notes[state.notes.indexOf(n) + 1]?.legato ? 1 : 0.98);
    const curve = expressive() ? curveOf(n, rate) : null;
    if (curve) singer.playCurve(n.midi, when, dur, curve, { legato: !!n.legato });
    else synth.play(n.midi, when, dur, n.velocity, { legato: !!n.legato });
  }
  state.resume = false;
  state.scheduledUntil = Math.max(from, until);
}

async function togglePlay() {
  ensureAudio();
  if (!audio.paused) {
    audio.pause();
    return;
  }
  // ▶ again during the count: called off.
  if ($("sx-play").textContent === "…") {
    metro.counting += 1;
    $("sx-play").textContent = "▶";
    return;
  }
  // ▶ while the song's audio is still being found (a missing backing, then
  // the next file): it plays once loaded, not "no supported source".
  if (audio.readyState < 1) {
    state.wantPlay = !state.wantPlay;
    return;
  }
  try {
    if (!(await countIn())) return;
    await audio.play();
  } catch (e) {
    status(`No se pudo reproducir: ${e.message}`);
  }
}

audio.addEventListener("play", () => {
  state.playing = true;
  state.scheduledUntil = audio.currentTime;
  state.resume = true;
  document.body.classList.add("sx-playing");
  $("sx-play").textContent = "❚❚";
});
audio.addEventListener("pause", () => {
  state.playing = false;
  stopSound();
  document.body.classList.remove("sx-playing");
  $("sx-play").textContent = "▶";
});
// A new source: whatever was playing has stopped (no "pause" event for it).
audio.addEventListener("emptied", () => {
  state.playing = false;
  stopSound();
  document.body.classList.remove("sx-playing");
  $("sx-play").textContent = "▶";
});
audio.addEventListener("seeking", () => {
  stopSound();
  state.scheduledUntil = audio.currentTime;
  state.resume = true;
});
audio.addEventListener("loadedmetadata", () => {
  $("sx-total").textContent = formatTime(audio.duration);
  audio.preservesPitch = true;
  audio.playbackRate = prefs.speed / 100;
});

function setSpeed(pct) {
  prefs.speed = [25, 50, 70, 100].includes(pct) ? pct : 100;
  savePrefs();
  audio.preservesPitch = true;
  audio.playbackRate = prefs.speed / 100;
  stopSound();
  swamSoon(); // SWAM plays the line at this speed itself (another render)
  for (const b of document.querySelectorAll("[data-speed]")) b.setAttribute("aria-pressed", String(Number(b.dataset.speed) === prefs.speed));
}

function seek(t) {
  if (audio.readyState < 1) {
    state.pendingT = Math.max(0, t); // applied once the file is loaded (updateBacking)
    return;
  }
  audio.currentTime = Math.max(0, Math.min((audio.duration || 0) - 0.05, t));
}

// ── picture ─────────────────────────────────────────────────────────────

/** The readout under the horn, the keys, and the strip of next notes: only
 *  when the note changes. */
function showNotes(t) {
  const { current, next } = around(state.notes, t, 9);
  const upcoming = next.filter((n) => n !== current);
  const key = `${current?.start ?? "-"}|${upcoming[0]?.start ?? "-"}|${prefs.sax}|${prefs.names}|${prefs.view}`;
  if (key === state.shown) return;
  state.shown = key;
  const nextKeys = upcoming[0] ? fingering(written(upcoming[0].midi, prefs.sax)) : null;
  const concert = prefs.view === "concert";
  const shown = (midi) => (concert ? midi : written(midi, prefs.sax));
  if (current) {
    const w = written(current.midi, prefs.sax);
    horn.set(fingering(w) || [], pitchColor(shown(current.midi), 62), nextKeys);
    $("sx-now-name").textContent = noteName(shown(current.midi), { names: prefs.names });
    $("sx-now-name").style.color = prefs.horn === "photo" ? pitchColor(shown(current.midi), 66) : "#f4b740";
    $("sx-now-sub").textContent = concert
      ? `en tu saxo: ${noteName(w, { names: prefs.names })}`
      : `suena ${noteName(current.midi, { names: prefs.names })}`;
  } else {
    horn.set(null, null, nextKeys);
    $("sx-now-name").textContent = upcoming[0] ? "·" : "—";
    $("sx-now-name").style.color = "#8ea6d8";
    $("sx-now-sub").textContent = upcoming[0] ? `prepara ${noteName(shown(upcoming[0].midi), { names: prefs.names })}` : "";
  }
  showStrip(current || upcoming[0] || null, current, shown);
}

/** The strip on top: the group of notes being played (a phrase, up to a
 *  breath; see noteGroups), all of it at once, in one colour: the one
 *  sounding lit, the ones played dimmed, a little higher or lower as the
 *  tune goes; then the start of the next group, faint. It is made again only
 *  when the group changes. Before: the next nine notes, each in its own
 *  colour, sliding by one at every note: too much to follow. */
function showStrip(focus, current, shown) {
  const strip = $("sx-next");
  const g = focus?.g ?? -1;
  const sig = `${state.version}|${g}|${prefs.sax}|${prefs.names}|${prefs.view}`;
  if (strip.dataset.sig !== sig) {
    strip.dataset.sig = sig;
    strip.innerHTML = "";
    const group = state.groups?.[g] || [];
    const rest = document.createElement("span");
    rest.className = "sx-rest";
    rest.textContent = "’ respira";
    strip.append(rest);
    const ws = group.map((n) => shown(n.midi));
    const mid = (Math.min(...ws) + Math.max(...ws)) / 2;
    const chip = (n, cls) => {
      const w = shown(n.midi);
      const c = document.createElement("span");
      c.className = `sx-chip ${cls}`;
      c.style.setProperty("--dy", `${Math.max(-9, Math.min(9, (mid - w) * 1.2))}px`);
      c.innerHTML = "<span></span><small></small>";
      c.firstChild.textContent = noteName(w, { names: prefs.names, octave: false });
      c.lastChild.textContent = String(Math.floor(w / 12) - 1);
      return c;
    };
    group.forEach((n, i) => {
      const c = chip(n, "");
      c.dataset.i = String(i);
      strip.append(c);
    });
    const later = state.groups?.[g + 1] || [];
    if (later.length) {
      const sep = document.createElement("span");
      sep.className = "sx-later-sep";
      sep.textContent = "luego";
      strip.append(sep);
      for (const n of later.slice(0, 4)) strip.append(chip(n, "later"));
    }
  }
  const group = state.groups?.[g] || [];
  const at = current ? group.indexOf(current) : -1;
  strip.querySelector(".sx-rest").hidden = !!current || !focus;
  for (const c of strip.querySelectorAll(".sx-chip[data-i]")) {
    const i = Number(c.dataset.i);
    c.classList.toggle("now", i === at);
    c.classList.toggle("done", at >= 0 ? i < at : group[i] && group[i].end <= (state.t ?? 0));
  }
}

// ── «✏️ Editar» ─────────────────────────────────────────────────────────
//
// A quick correction of the line: a note taken out, moved a semitone or an
// octave, earlier or later; ↶ undoes. Kept per line (its stems and its
// phrasing) on the server (/sax/edits), each note named by its stem, its
// start and its concert pitch as the line made it, so a correction outlives
// a change of saxophone and is there on the next visit.

const edit = { on: false, sets: {}, undo: [], redo: [], selected: null, drag: null, scrub: null, scrubbedAt: 0, dirty: new Set(), timer: 0 };
// A drag of the lane just ended: its click is not a tap.
const scrubbed = () => performance.now() - edit.scrubbedAt < 300;
window.__saxEdit = edit;
window.__saxLane = lane;
const lineSet = () => `${state.stems.join(",")}|${prefs.phrasing}`;
const keyOf = (n) => `${n.stem}|${n.start.toFixed(2)}|${n.concert ?? n.midi}`;

/** The line with its corrections (a moved note keeps where it was in
 *  `orig`: its contour, for «Expresivo»). Still one note at a time: a note
 *  moved over the next one ends where that one starts. */
function applyEdits(notes) {
  const ed = edit.sets[lineSet()] || {};
  const out = [];
  for (const n0 of notes) {
    const key = keyOf(n0);
    const e = ed[key];
    if (e?.del) continue;
    const n = { ...n0, key };
    if (e?.dm || e?.dt || e?.dd) {
      const dm = e.dm || 0;
      const dt = e.dt || 0;
      n.orig = { start: n0.start, end: n0.end, concert: n0.concert ?? n0.midi };
      n.midi += dm;
      n.concert = (n0.concert ?? n0.midi) + dm;
      n.start += dt;
      n.end = Math.max(n.start + MIN_EDIT_SEC, n.end + dt + (e.dd || 0));
      n.grown = (e.dd || 0) > 0;
      n.edited = true;
    }
    out.push(n);
  }
  // The notes put in by hand («＋ Nota»): "add|start|pitch" (the pitch as it
  // sounds), moved and stretched like the others.
  const { low, high } = concertRange(prefs.sax);
  for (const [key, e] of Object.entries(ed)) {
    if (!e.add || !key.startsWith("add|")) continue;
    const [, at, pitch] = key.split("|");
    const start = Number(at) + (e.dt || 0);
    let midi = Number(pitch) + (e.dm || 0);
    while (midi < low) midi += 12;
    while (midi > high) midi -= 12;
    out.push({ stem: "add", key, start, end: start + Math.max(MIN_EDIT_SEC, (e.len || 0.4) + (e.dd || 0)), midi, concert: midi, velocity: 95, legato: false, octave: 0, added: true, edited: true, grown: true });
  }
  out.sort((a, b) => a.start - b.start);
  // One note at a time: a note made longer covers the start of the next
  // (gone if nothing is left of it); otherwise a note ends where the next
  // one starts.
  const kept = [];
  for (const n of out) {
    const prev = kept[kept.length - 1];
    if (prev && prev.end > n.start) {
      if (prev.grown) {
        n.start = prev.end;
        if (n.end - n.start < MIN_EDIT_SEC) continue;
      } else prev.end = Math.max(prev.start + MIN_EDIT_SEC, n.start);
    }
    kept.push(n);
  }
  return kept;
}
const MIN_EDIT_SEC = 0.05;

/** One correction: `fn` changes this line's edits; undoable. */
function change(fn) {
  const set = lineSet();
  const before = edit.sets[set] || {};
  const after = structuredClone(before);
  fn(after);
  if (JSON.stringify(after) === JSON.stringify(before)) return;
  edit.undo.push({ set, edits: before });
  if (edit.undo.length > 300) edit.undo.shift();
  edit.redo = [];
  commit(set, after);
}

function commit(set, edits) {
  edit.sets[set] = edits;
  stopSound();
  rebuild();
  edit.dirty.add(set);
  clearTimeout(edit.timer);
  edit.timer = setTimeout(saveEdits, 400);
}

async function saveEdits() {
  for (const set of [...edit.dirty]) {
    edit.dirty.delete(set);
    try {
      await api(`/api/jobs/${JOB}/sax/edits`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ set, edits: edit.sets[set] || {} }),
      });
    } catch (e) {
      edit.dirty.add(set);
      // An older server (not restarted since this page was updated) has no
      // /sax/edits: the PUT falls on the static files ("Method Not Allowed").
      const old = /method not allowed|not found/i.test(e.message);
      status(old ? "No se pudo guardar la edición: reinicia el servidor de StemDeck (sigue con una versión anterior) y vuelve a intentarlo." : `No se pudo guardar la edición: ${e.message}`);
      setTimeout(() => status(""), old ? 6000 : 3000);
    }
  }
}

function undo(redo = false) {
  const from = redo ? edit.redo : edit.undo;
  const to = redo ? edit.undo : edit.redo;
  const step = from.pop();
  if (!step) return;
  to.push({ set: step.set, edits: edit.sets[step.set] || {} });
  commit(step.set, step.edits);
  if (!state.notes.some((n) => n.key === edit.selected)) select(null);
}

const selectedNote = () => (edit.selected ? state.notes.find((n) => n.key === edit.selected) : null);

/** A note picked: the song stops, and the note sounds. */
function select(key, { sound = true } = {}) {
  edit.selected = key;
  lane.selected = key;
  if (key) {
    if (!audio.paused) audio.pause();
    if (sound) hear();
  }
  showEdit();
}

function hear(n = selectedNote()) {
  if (!n) return;
  ensureAudio();
  instrument()?.play(n.midi, ctx.currentTime + 0.01, Math.min(0.6, Math.max(0.25, n.end - n.start)), 90);
}

function moveSelected(dm, dt = 0, dd = 0) {
  const key = edit.selected;
  if (!key) return;
  change((ed) => {
    const e = { ...(ed[key] || {}) };
    delete e.del;
    e.dm = (e.dm || 0) + dm;
    e.dt = Math.round(((e.dt || 0) + dt) * 1000) / 1000;
    e.dd = Math.round(((e.dd || 0) + dd) * 1000) / 1000;
    if (!e.dm) delete e.dm;
    if (!e.dt) delete e.dt;
    if (!e.dd) delete e.dd;
    if (Object.keys(e).length) ed[key] = e;
    else delete ed[key];
  });
  hear();
}

function deleteSelected() {
  const key = edit.selected;
  if (!key) return;
  const n = selectedNote();
  const after = n ? state.notes[state.notes.indexOf(n) + 1] : null;
  change((ed) => {
    if (key.startsWith("add|")) delete ed[key]; // a note put in by hand: just gone
    else ed[key] = { del: true };
  });
  // The next note picked: a run of wrong notes goes with one tap each.
  select(after?.key || null, { sound: false });
}

/** «＋ Nota»: a note put in at `t` (where the song is) and `midi` (as it
 *  sounds; by default the pitch of the note picked, or of the nearest one),
 *  picked at once to be moved, stretched or dragged into place. */
function addNote(t = state.t ?? audio.currentTime ?? 0, midi = null) {
  if (!state.stems.length) return;
  const { low, high } = concertRange(prefs.sax);
  if (midi == null) {
    const near = selectedNote() || state.notes.reduce((b, n) => (!b || Math.abs(n.start - t) < Math.abs(b.start - t) ? n : b), null);
    midi = near ? near.midi : Math.round((low + high) / 2);
  }
  midi = Math.max(low, Math.min(high, Math.round(midi)));
  const start = Math.max(0, Math.round(t * 100) / 100);
  const key = `add|${start.toFixed(2)}|${midi}`;
  if ((edit.sets[lineSet()] || {})[key]) return select(key);
  if (!edit.on) toggleEdit(true);
  change((ed) => {
    ed[key] = { add: true, len: 0.4 };
  });
  select(key);
}

function showEdit() {
  const n = selectedNote();
  const count = Object.keys(edit.sets[lineSet()] || {}).length;
  $("sx-undo").disabled = !edit.undo.length;
  $("sx-redo").disabled = !edit.redo.length;
  for (const id of ["sx-del", "sx-up", "sx-down", "sx-oct-up", "sx-oct-down", "sx-earlier", "sx-later", "sx-shorter", "sx-longer"]) $(id).disabled = !n;
  $("sx-reset").disabled = !count;
  $("sx-edit-count").textContent = count ? `${count} ${count === 1 ? "cambio" : "cambios"}` : "";
  const shown = (m) => (prefs.view === "concert" ? m : written(m, prefs.sax));
  $("sx-edit-info").textContent = n
    ? `${noteName(shown(n.midi), { names: prefs.names })} · ${formatTime(n.start)} · ${(n.end - n.start).toFixed(2).replace(".", ",")} s${n.edited ? " ✎" : ""}`
    : "Toca una nota";
}

function toggleEdit(on = !edit.on) {
  edit.on = on;
  $("sx-edit").setAttribute("aria-pressed", String(on));
  $("sx-editbar").hidden = !on;
  document.body.classList.toggle("sx-editing", on);
  if (!on) select(null);
  $("sx-lane").style.cursor = "";
  showEdit();
  lane.resize(); // the bar is a row above the staff: the staff is that much lower
}

/** The lane in «Editar»: a tap picks a note (or none); a note dragged up or
 *  down moves by semitones, to the sides in time (one or the other: the
 *  first 8 px decide). */
function wireEditing() {
  const canvas = $("sx-lane");
  const at = (e) => {
    const r = canvas.getBoundingClientRect();
    return { x: e.clientX - r.left, y: e.clientY - r.top };
  };
  const hitAt = (e) => {
    const { x, y } = at(e);
    return lane.hits.find((h) => x >= h.x - 4 && x <= h.x + h.w + 4 && y >= h.y - 6 && y <= h.y + h.h + 6) || null;
  };
  // The right end of a note (the last 10 px, or a third of a short one):
  // dragged, it makes the note longer or shorter.
  const edgeAt = (e) => {
    const { x, y } = at(e);
    return lane.hits.find((h) => y >= h.y - 6 && y <= h.y + h.h + 6 && x >= h.x + h.w - Math.min(10, h.w / 3) && x <= h.x + h.w + 6) || null;
  };
  const pps = () => (lane.size.w - HIT_X) / prefs.ahead;
  canvas.addEventListener("pointerdown", (e) => {
    if (e.button !== 0) return;
    if (edit.on) {
      const edge = edgeAt(e);
      const hit = edge || hitAt(e);
      if (hit) {
        select(hit.key);
        const n = selectedNote();
        if (!n) return;
        canvas.setPointerCapture?.(e.pointerId);
        edit.drag = { id: e.pointerId, x: e.clientX, y: e.clientY, axis: edge ? "len" : null, dm: 0, dt: 0, dd: 0, n, base: { midi: n.midi, start: n.start, end: n.end } };
        return;
      }
      select(null);
    }
    // On empty lane (or anywhere, not editing): the song moves with the
    // pointer, as the falling notes of the piano do.
    canvas.setPointerCapture?.(e.pointerId);
    edit.scrub = { id: e.pointerId, x: e.clientX, t0: state.t ?? audio.currentTime ?? 0, wasPlaying: !audio.paused, moved: false };
  });
  canvas.addEventListener("pointermove", (e) => {
    const s = edit.scrub;
    if (s && s.id === e.pointerId) {
      const dx = e.clientX - s.x;
      if (!s.moved && Math.abs(dx) < 6) return;
      if (!s.moved) {
        s.moved = true;
        if (s.wasPlaying) audio.pause(); // held while dragged, so it does not run off under the pointer
        canvas.classList.add("grabbing");
      }
      // The note under the pointer stays under it: pull the notes left to
      // go on, push them right to go back.
      seek(Math.max(0, s.t0 - dx / pps()));
      return;
    }
    const d = edit.drag;
    if (!d || d.id !== e.pointerId) {
      if (edit.on) canvas.style.cursor = edgeAt(e) ? "ew-resize" : hitAt(e) ? "pointer" : "";
      return;
    }
    const dx = e.clientX - d.x;
    const dy = e.clientY - d.y;
    if (!d.axis && Math.max(Math.abs(dx), Math.abs(dy)) > 8) d.axis = Math.abs(dy) >= Math.abs(dx) ? "y" : "x";
    if (d.axis === "y") {
      const semitone = (lane.geometry().hs * 7) / 12; // an octave is 7 staff steps
      const dm = Math.max(-24, Math.min(24, Math.round(-dy / semitone)));
      if (dm !== d.dm) {
        d.dm = dm;
        d.n.midi = d.base.midi + dm;
        hear(d.n);
      }
    } else if (d.axis === "x") {
      d.dt = Math.round((dx / pps()) * 100) / 100;
      d.n.start = d.base.start + d.dt;
      d.n.end = d.base.end + d.dt;
    } else if (d.axis === "len") {
      const dd = Math.round((dx / pps()) * 100) / 100;
      d.dd = Math.max(MIN_EDIT_SEC - (d.base.end - d.base.start), dd);
      d.n.end = d.base.end + d.dd;
      showEdit();
    }
  });
  const end = (e) => {
    const s = edit.scrub;
    if (s && s.id === e.pointerId) {
      edit.scrub = null;
      canvas.classList.remove("grabbing");
      if (s.moved) {
        edit.scrubbedAt = performance.now();
        if (s.wasPlaying) audio.play().catch(() => {});
      }
      return;
    }
    const d = edit.drag;
    if (!d || d.id !== e.pointerId) return;
    edit.drag = null;
    Object.assign(d.n, d.base); // the preview undone: the edit makes it again
    if (d.dm || d.dt || d.dd) moveSelected(d.dm, d.dt, d.dd);
  };
  canvas.addEventListener("pointerup", end);
  canvas.addEventListener("pointercancel", end);
  $("sx-edit").onclick = () => toggleEdit();
  $("sx-undo").onclick = () => undo();
  $("sx-redo").onclick = () => undo(true);
  $("sx-del").onclick = deleteSelected;
  $("sx-up").onclick = () => moveSelected(1);
  $("sx-down").onclick = () => moveSelected(-1);
  $("sx-oct-up").onclick = () => moveSelected(12);
  $("sx-oct-down").onclick = () => moveSelected(-12);
  $("sx-earlier").onclick = () => moveSelected(0, -0.05);
  $("sx-later").onclick = () => moveSelected(0, 0.05);
  $("sx-shorter").onclick = () => moveSelected(0, 0, -0.1);
  $("sx-longer").onclick = () => moveSelected(0, 0, 0.1);
  $("sx-add").onclick = () => addNote();
  // A double tap on the empty lane: a note there, at that moment and height.
  canvas.addEventListener("dblclick", (e) => {
    if (!edit.on || hitAt(e)) return;
    const { x, y } = at(e);
    const g = lane.geometry();
    const step = Math.round((g.y(0) - y) / g.hs);
    // The natural note on that line or space, as read; then as it sounds.
    let read = 60;
    for (let m = 40; m <= 100; m++) if (![1, 3, 6, 8, 10].includes(m % 12) && staffStep(m) === step) read = m;
    const sounding = prefs.view === "concert" ? read : read - written(0, prefs.sax);
    addNote((state.t ?? 0) + (x - HIT_X) / pps(), sounding);
  });
  $("sx-reset").onclick = () => {
    change((ed) => {
      for (const k of Object.keys(ed)) delete ed[k];
    });
    select(null);
  };
}

/** Keys of «Editar» (true when one was used). Ctrl+Z / Ctrl+Y always. */
function editKey(e) {
  const mod = e.ctrlKey || e.metaKey;
  if (mod && (e.key === "z" || e.key === "Z")) {
    undo(e.shiftKey);
    return true;
  }
  if (mod && (e.key === "y" || e.key === "Y")) {
    undo(true);
    return true;
  }
  if (edit.on && !mod && (e.key === "n" || e.key === "N")) {
    addNote();
    return true;
  }
  if (!edit.on || !edit.selected) return false;
  if (e.key === "Delete" || e.key === "Backspace") deleteSelected();
  else if (e.key === "ArrowUp") moveSelected(e.shiftKey ? 12 : 1);
  else if (e.key === "ArrowDown") moveSelected(e.shiftKey ? -12 : -1);
  else if (e.key === "ArrowLeft" && e.altKey) moveSelected(0, 0, -0.1);
  else if (e.key === "ArrowRight" && e.altKey) moveSelected(0, 0, 0.1);
  else if (e.key === "ArrowLeft") moveSelected(0, -0.05);
  else if (e.key === "ArrowRight") moveSelected(0, 0.05);
  else if (e.key === "Escape") select(null);
  else return false;
  return true;
}


// ── SWAM Saxophones (app/score/swam.py) ────────────────────────────────
//
// With SWAM installed, the line is played by it: the page sends the line as
// it plays it (phrased, in range, with its edits; «Expresivo»: each note's
// curve), the server renders it (~15 s a song) and it plays here in an
// <audio> of its own, kept on the song's clock (its speed too, the pitch
// kept). Until it is back the recorded saxophone plays; after an edit, the
// render before it goes on until the new one is there (as Pianoteq does).

const swam = { info: null, key: "", base: "", loadedKey: "", loadedBase: "", state: "", timer: 0, poll: 0, resyncAt: 0 };
window.__swam = swam;
const swamAudio = new Audio();
swamAudio.preload = "auto";
swamAudio.preservesPitch = true;
window.__swamAudio = swamAudio;

const swamWanted = () => prefs.engine !== "iowa" && !!swam.info?.available && swam.info.saxes.includes(prefs.sax);
// What a render is of, but for the edits: the stems, phrasing, saxophone
// and expression. An edit keeps the render before playing meanwhile; any
// of these changed, it would be another line.
const swamBase = () => `${lineSet()}|${prefs.sax}|${prefs.expression}`;
/** The SWAM render is what sounds (not the recorded saxophone). */
const swamActive = () => swamWanted() && !!swam.loadedKey && swam.loadedBase === swamBase() && swamAudio.readyState >= 1;

/** The speed a render is asked at: the practice speed (25, 50, 70 %: SWAM
 *  plays the line that slow itself, its attacks and transitions in their
 *  own time), or 1. Meanwhile the render there is plays, stretched. */
const swamSpeed = () => (prefs.speed < 100 ? prefs.speed / 100 : 1);

function swamPayload() {
  const exact = prefs.expression === "exact";
  const last = state.notes.length ? state.notes[state.notes.length - 1].end : 0;
  const r2 = (x) => Math.round(x * 100) / 100;
  return {
    sax: prefs.sax,
    duration: Math.round((last + 3) * 10) / 10,
    cents: Math.round((state.cents || 0) * 10) / 10,
    room: ["dry", "large"].includes(prefs.room) ? prefs.room : "medium",
    tone: ["soft", "growl"].includes(prefs.tone) ? prefs.tone : "clean",
    stem: state.stems[0], // as loud as this part is in the song
    speed: swamSpeed(), // SWAM itself plays at the practice speed
    notes: state.notes.map((n) => {
      const out = { start: r2(n.start), end: r2(n.end), midi: n.midi, velocity: Math.max(1, Math.min(127, Math.round(n.velocity ?? 80))), legato: !!n.legato };
      const c = exact ? null : curveOf(n, 1);
      if (c) out.curve = { step: c.step, midi: Array.from(c.midi, r2), level: Array.from(c.level, r2) };
      return out;
    }),
  };
}

/** The line changed (or the saxophone, the expression): a render asked
 *  for, a moment later (a run of edits makes one request). */
function swamSoon() {
  clearTimeout(swam.timer);
  if (!swamWanted() || !state.notes.length) return showSwam();
  // Asked, not yet answered: the render may well be there already (it is
  // looked for, not made, until the server says it is being made).
  swam.state = "asking";
  // Opening the page: asked at once. After an edit: a moment later, so a
  // run of edits makes one request.
  swam.timer = setTimeout(swamRequest, swam.loadedKey ? 700 : 50);
  showSwam();
}

async function swamRequest() {
  const base = swamBase();
  const speed = swamSpeed();
  swam.speed = speed;
  try {
    const r = await api(`/api/jobs/${JOB}/sax/swam`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(swamPayload()),
    });
    swam.key = r.key;
    swam.base = base;
    swam.state = r.state;
    if (r.state === "done") swamLoad(r.url, r.key, base, speed);
    else swamPoll(r.key, base, speed);
  } catch (e) {
    swam.state = "error";
    swam.error = e.message;
  }
  showSwam();
}

function swamPoll(key, base, speed) {
  clearTimeout(swam.poll);
  swam.poll = setTimeout(async () => {
    if (key !== swam.key) return; // a newer line asked for since
    try {
      const r = await api(`/api/jobs/${JOB}/sax/swam/${key}`);
      swam.state = r.state;
      if (r.state === "done") swamLoad(r.url, key, base, speed);
      else if (r.state === "error") swam.error = r.error;
      else swamPoll(key, base, speed);
    } catch {
      swamPoll(key, base, speed);
    }
    showSwam();
  }, 1500);
}

function swamLoad(url, key, base, speed = 1) {
  if (key !== swam.key) return;
  swamAudio.src = url;
  swamAudio.addEventListener(
    "loadedmetadata",
    () => {
      swam.loadedKey = key;
      swam.loadedBase = base;
      swam.loadedSpeed = speed;
      swam.resyncAt = 0;
      stopSound(); // the recorded saxophone stops: SWAM takes over from here
      showSwam();
    },
    { once: true },
  );
}

/** Each frame: the SWAM audio on the song's clock. */
function syncSwam() {
  const on = swamActive() && prefs.sound !== "original";
  if (!on) {
    if (!swamAudio.paused) swamAudio.pause();
    return;
  }
  swamAudio.volume = prefs.volSax / 100;
  // The render was made at `made` of the song's speed (1, or the practice
  // speed it was asked at): the song's second t is its second t / made, and
  // it runs at the song's rate / made (1 when it was made for this speed).
  const made = swam.loadedSpeed || 1;
  const rate = audio.playbackRate / made;
  if (Math.abs(swamAudio.playbackRate - rate) > 1e-3) swamAudio.playbackRate = rate;
  const at = audio.currentTime / made;
  const playing = !audio.paused && !audio.ended;
  const drift = Math.abs(swamAudio.currentTime - at) * made; // in the song's seconds
  const now = performance.now();
  if (playing) {
    if (drift > 0.06 && now - swam.resyncAt > 400 && at < (swamAudio.duration || Infinity)) {
      swam.resyncAt = now;
      swamAudio.currentTime = at;
    }
    if (swamAudio.paused && at < (swamAudio.duration || Infinity)) swamAudio.play().catch(() => {});
  } else {
    if (!swamAudio.paused) swamAudio.pause();
    if (drift > 0.03 && now - swam.resyncAt > 150) {
      swam.resyncAt = now;
      swamAudio.currentTime = Math.min(at, swamAudio.duration || at);
    }
  }
}

function showSwam() {
  const el = $("sx-swam-state");
  const wanted = swamWanted();
  el.hidden = !wanted;
  $("sx-sound-state").hidden = wanted && swamActive();
  for (const f of document.querySelectorAll(".sx-swam-only")) f.hidden = !wanted;
  if (!wanted) return;
  const fresh = swam.loadedKey && swam.loadedKey === swam.key;
  const asking = swam.state === "asking" || (swam.state === "done" && !fresh);
  el.className = `sx-swam-state ${swam.state === "error" ? "error" : fresh || (asking && swamActive()) ? "ok" : "busy"}`;
  el.textContent =
    swam.state === "error"
      ? `SWAM no pudo grabar la línea: ${swam.error || "error"}`
      : fresh || (asking && swamActive())
        ? "🎷 SWAM (modelado físico)"
        : asking
          ? "⟳ SWAM: cargando la grabación…"
          : swamActive()
            ? (swam.speed || 1) !== (swam.loadedSpeed || 1)
              ? `🎷 SWAM · ⟳ grabando al ${Math.round((swam.speed || 1) * 100)} %…`
              : "🎷 SWAM · ⟳ grabando tus cambios…"
            : "⟳ SWAM grabando la línea… (mientras, el saxo grabado)";
}

// ── «🎤 Practicar» ──────────────────────────────────────────────────────

const practice = { mic: null, wait: false, waiting: null, steady: 0, trail: [], judged: 0, hit: 0 };
window.__saxPractice = practice;

async function toggleMic() {
  ensureAudio();
  if (practice.mic?.on) {
    practice.mic.stop();
    practice.mic = null;
    lane.you = null;
  } else {
    try {
      practice.mic = new MicPitch(ctx);
      await practice.mic.start();
    } catch (e) {
      practice.mic = null;
      status(`No se pudo usar el micrófono: ${e.message}`);
      setTimeout(() => status(""), 4000);
    }
  }
  const on = !!practice.mic?.on;
  $("sx-mic").setAttribute("aria-pressed", String(on));
  $("sx-wait").hidden = !on;
  $("sx-you").hidden = !on;
  $("sx-score").hidden = !on;
  practice.judged = practice.hit = 0;
  for (const n of state.notes) delete n.heard;
  showScore();
}

function showScore() {
  $("sx-score").textContent = practice.judged ? `Aciertos ${practice.hit}/${practice.judged} (${Math.round((100 * practice.hit) / practice.judged)} %)` : "Aciertos —";
}

/** The microphone against the note sounding: the meter, the trail on the
 *  lane, each note scored once it has passed, and «Esperarme». */
function listen(t, now) {
  if (!practice.mic?.on) return;
  const r = practice.mic.read();
  const { current } = around(state.notes, t, 1);
  const target = current || practice.waiting;
  const shown = (m) => (prefs.view === "concert" ? m : written(m, prefs.sax));
  let verdict = null;
  if (r) {
    practice.trail.push({ at: now, midi: shown(r.midi) });
    if (target) {
      verdict = judge(r.midi, target.midi);
      target.heard ??= { frames: 0, ok: 0 };
      target.heard.frames++;
      if (verdict.ok) target.heard.ok++;
    }
  }
  practice.trail = practice.trail.filter((p) => now - p.at < 600);
  const state_ = !r || !verdict ? "" : verdict.ok ? "ok" : Math.abs(verdict.cents) < 100 ? "near" : "off";
  lane.you = {
    midi: r ? shown(r.midi) : null,
    state: state_,
    trail: practice.trail.map((p) => ({ age: (now - p.at) / 1000, midi: p.midi })),
  };
  // The meter: ±100 cents across.
  const cents = verdict ? Math.max(-100, Math.min(100, verdict.octave ? 0 : verdict.cents)) : 0;
  $("sx-you-needle").style.left = `${50 + cents / 2}%`;
  const el = $("sx-you-text");
  el.className = `sx-you-text ${state_}`;
  el.textContent = !r
    ? "🎤 toca…"
    : !verdict
      ? `🎤 ${noteName(Math.round(shown(r.midi)), { names: prefs.names })}`
      : verdict.octave
        ? `🎤 ${noteName(Math.round(shown(r.midi)), { names: prefs.names })} · una octava ${verdict.octave > 0 ? "arriba" : "abajo"}`
        : verdict.ok
          ? `✓ ${noteName(Math.round(shown(r.midi)), { names: prefs.names })} ${verdict.cents >= 0 ? "+" : ""}${verdict.cents} cents`
          : `${verdict.cents > 0 ? "↓ baja" : "↑ sube"} · ${noteName(Math.round(shown(r.midi)), { names: prefs.names })} ${verdict.cents > 0 ? "+" : ""}${verdict.cents} cents`;
  // A note passed: scored (in tune 40 % of the time it lasted).
  for (const n of state.notes) {
    if (n.start > t) break;
    if (n.end < t && n.heard && n.scored == null) {
      n.scored = n.heard.ok / Math.max(1, n.heard.frames) >= 0.4;
      practice.judged++;
      if (n.scored) practice.hit++;
      showScore();
    }
  }
  // «Esperarme»: stopped on a note until it is played (a moment in tune).
  if (practice.wait) {
    if (practice.waiting) {
      practice.steady = verdict?.ok && target === practice.waiting ? practice.steady + 1 : 0;
      if (practice.steady >= 6) {
        practice.waiting = null;
        practice.steady = 0;
        audio.play().catch(() => {});
      }
    } else if (state.playing && current && t - current.start < 0.12 && current.waited !== true) {
      current.waited = true;
      if (!verdict?.ok) {
        practice.waiting = current;
        audio.pause();
      }
    }
  }
}

// ── «Metrónomo» and «Cuenta» ────────────────────────────────────────────
//
// A click on each of the song's beats (the first of a bar higher), and a
// count of one or two bars before ▶ starts the song, at the tempo there.

const metro = { until: 0, counting: 0, clicks: [] }; // clicks: the last ones scheduled (tests)
window.__saxMetro = metro;

/** A click at the audio clock's `when`: a short tick, higher on a bar's first beat. */
function click(when, accent) {
  const o = ctx.createOscillator();
  const g = ctx.createGain();
  o.type = "square";
  o.frequency.value = accent ? 1760 : 1175;
  g.gain.setValueAtTime(0.0001, when);
  g.gain.exponentialRampToValueAtTime(accent ? 0.22 : 0.14, when + 0.002);
  g.gain.exponentialRampToValueAtTime(0.0001, when + 0.05);
  o.connect(g).connect(ctx.destination);
  o.start(when);
  o.stop(when + 0.06);
}

/** The beats coming in the next moment, clicked (scheduled a little ahead). */
function metronome(t) {
  const g = state.bars;
  if (!prefs.metronome || !g || !ctx || !state.playing) {
    metro.until = t;
    return;
  }
  const rate = audio.playbackRate || 1;
  if (metro.until < t - 0.5 || metro.until > t + 1) metro.until = t; // a seek, a loop
  const until = t + 0.25 * rate;
  for (let i = Math.max(0, beatIndexAt(g.times, metro.until) + 1); i < g.times.length && g.times[i] <= until; i++) {
    if (g.times[i] <= metro.until) continue;
    click(ctx.currentTime + Math.max(0, (g.times[i] - t) / rate), g.down[i]);
    metro.clicks.push({ t: g.times[i], accent: g.down[i] });
    if (metro.clicks.length > 64) metro.clicks.shift();
  }
  metro.until = until;
}

/** «Cuenta»: the clicks of one or two bars, then the song. Resolves false
 *  when ▶ is pressed again meanwhile (the count is called off). */
function countIn() {
  const bars = prefs.countIn === "2bar" ? 2 : prefs.countIn === "bar" ? 1 : 0;
  if (!bars || !ctx) return Promise.resolve(true);
  const t = audio.currentTime || 0;
  const g = state.bars;
  const per = (g && g.per[Math.max(0, beatIndexAt(g.times, t))]) || 4;
  const beat = beatSecondsAt(g, t, 0.5) / (audio.playbackRate || 1);
  const n = bars * per;
  const ticket = ++metro.counting;
  for (let k = 0; k < n; k++) click(ctx.currentTime + 0.05 + k * beat, k % per === 0);
  metro.counted = n;
  $("sx-play").textContent = "…";
  return new Promise((resolve) => {
    setTimeout(() => resolve(ticket === metro.counting), (0.05 + n * beat) * 1000);
  });
}

// ── «Bucle» ─────────────────────────────────────────────────────────────
//
// A part of the song repeated to study it: A at the start of the bar that
// is sounding, B at its end (or of a later bar); past B the song goes back
// to A. Without a beat grid, A and B are the moment itself. Kept per song.

const loop = { a: null, b: null, on: false };
window.__saxLoop = loop;
const LOOP_LS = `stemdeck.sax.loop.${JOB}`;

function readLoop() {
  try {
    const l = JSON.parse(localStorage.getItem(LOOP_LS) || "null");
    if (l && l.b > l.a) Object.assign(loop, { a: l.a, b: l.b, on: !!l.on });
  } catch {
    /* none kept */
  }
}

function showLoop() {
  const set = loop.a != null && loop.b != null;
  if (set) localStorage.setItem(LOOP_LS, JSON.stringify(loop));
  else localStorage.removeItem(LOOP_LS);
  lane.loop = set && loop.on ? { a: loop.a, b: loop.b } : null;
  $("sx-loop-a").setAttribute("aria-pressed", String(loop.a != null));
  $("sx-loop-b").setAttribute("aria-pressed", String(loop.b != null));
  $("sx-loop-on").setAttribute("aria-pressed", String(set && loop.on));
  $("sx-loop-on").disabled = !set;
  $("sx-loop-clear").disabled = loop.a == null && loop.b == null;
  const g = state.bars;
  const barOf = (t) => (g ? g.bar[Math.max(0, beatIndexAt(g.times, t + 0.01))] : 0);
  $("sx-loop-info").textContent = !set
    ? loop.a != null
      ? `desde ${formatTime(loop.a)}…`
      : ""
    : g && barOf(loop.a) > 0
      ? barOf(loop.a) === barOf(loop.b - 0.05)
        ? `compás ${barOf(loop.a)}`
        : `compases ${barOf(loop.a)}–${barOf(loop.b - 0.05)}`
      : `${formatTime(loop.a)}–${formatTime(loop.b)}`;
}

/** «A» / «B»: the loop's start or end, at the bar that is sounding. */
function setLoopPoint(which) {
  const t = state.t ?? audio.currentTime ?? 0;
  const span = barSpanAt(state.bars, t, audio.duration || Infinity) || [t, t];
  if (which === "a") {
    loop.a = span[0];
    if (loop.b != null && loop.b <= loop.a) loop.b = null;
  } else {
    loop.b = Math.max(span[1], t);
    // B alone: that bar, repeated.
    if (loop.a == null || loop.a >= loop.b) loop.a = Math.min(span[0], loop.b - 0.2);
  }
  loop.on = loop.a != null && loop.b != null;
  showLoop();
}

function clearLoop() {
  Object.assign(loop, { a: null, b: null, on: false });
  showLoop();
}

function frame() {
  const now = performance.now();
  // What the audio says, not what the page last thought: never runs on alone.
  const playing = !audio.paused && !audio.ended;
  if (state.playing && !playing) stopSound();
  state.playing = playing;
  let t = clock.update(audio.currentTime || 0, now, playing && audio.readyState >= 3, audio.playbackRate || 1);
  // «Bucle»: past B, back to A.
  if (playing && loop.on && loop.b > loop.a && t >= loop.b) {
    stopSound();
    seek(loop.a);
    swam.resyncAt = 0; // SWAM's audio goes back with it at once
    t = clock.update(loop.a, now, false, audio.playbackRate || 1);
  }
  state.t = t;
  schedule(t);
  metronome(t);
  listen(t, now);
  lane.draw(t, state.playing);
  showNotes(t);
  syncSwam();
  $("sx-now-t").textContent = formatTime(t);
  if (audio.duration && document.activeElement !== $("sx-seek")) $("sx-seek").value = String(Math.round((t / audio.duration) * 1000));
  requestAnimationFrame(frame);
}

// ── controls ────────────────────────────────────────────────────────────

function wire() {
  $("sx-play").onclick = togglePlay;
  $("sx-seek").oninput = () => seek((Number($("sx-seek").value) / 1000) * (audio.duration || 0));
  for (const b of document.querySelectorAll("[data-speed]")) b.onclick = () => setSpeed(Number(b.dataset.speed));
  $("sx-type").value = prefs.sax;
  $("sx-type").onchange = () => {
    prefs.sax = $("sx-type").value;
    savePrefs();
    rebuild();
    loadSamples();
  };
  $("sx-metronome").checked = !!prefs.metronome;
  $("sx-metronome").onchange = () => {
    prefs.metronome = $("sx-metronome").checked;
    savePrefs();
    ensureAudio();
  };
  $("sx-countin").value = ["bar", "2bar"].includes(prefs.countIn) ? prefs.countIn : "0";
  $("sx-countin").onchange = () => {
    prefs.countIn = $("sx-countin").value;
    savePrefs();
  };
  $("sx-loop-a").onclick = () => setLoopPoint("a");
  $("sx-loop-b").onclick = () => setLoopPoint("b");
  $("sx-loop-on").onclick = () => {
    loop.on = !loop.on;
    showLoop();
  };
  $("sx-loop-clear").onclick = clearLoop;
  readLoop();
  showLoop();
  $("sx-mic").onclick = toggleMic;
  $("sx-wait").onclick = () => {
    practice.wait = !practice.wait;
    $("sx-wait").setAttribute("aria-pressed", String(practice.wait));
    for (const n of state.notes) delete n.waited;
    if (!practice.wait && practice.waiting) {
      practice.waiting = null;
      audio.play().catch(() => {});
    }
  };
  $("sx-horn-switch").onclick = () => {
    prefs.horn = prefs.horn === "photo" ? "chart" : "photo";
    savePrefs();
    makeHorn();
  };
  $("sx-expression").value = prefs.expression;
  $("sx-expression").onchange = () => {
    prefs.expression = $("sx-expression").value;
    savePrefs();
    stopSound();
    swamSoon();
  };
  // «Sala»: SWAM's room (another render; the one before plays meanwhile).
  $("sx-room").value = ["dry", "large"].includes(prefs.room) ? prefs.room : "medium";
  $("sx-room").onchange = () => {
    prefs.room = $("sx-room").value;
    savePrefs();
    swamSoon();
  };
  // «Tono»: how SWAM's saxophone is blown (another render, as «Sala»).
  $("sx-tone").value = ["soft", "growl"].includes(prefs.tone) ? prefs.tone : "clean";
  $("sx-tone").onchange = () => {
    prefs.tone = $("sx-tone").value;
    savePrefs();
    swamSoon();
  };
  $("sx-engine").value = prefs.engine === "iowa" ? "iowa" : "swam";
  $("sx-engine").onchange = () => {
    prefs.engine = $("sx-engine").value;
    savePrefs();
    stopSound();
    swamSoon();
  };
  $("sx-phrasing").value = prefs.phrasing;
  $("sx-phrasing").onchange = () => {
    prefs.phrasing = $("sx-phrasing").value;
    savePrefs();
    stopSound();
    rebuild();
  };
  $("sx-view").value = prefs.view;
  $("sx-view").onchange = () => {
    prefs.view = $("sx-view").value;
    savePrefs();
    rebuild();
  };
  $("sx-names").value = prefs.names;
  $("sx-names").onchange = () => {
    prefs.names = $("sx-names").value;
    savePrefs();
    rebuild();
  };
  $("sx-sound").value = prefs.sound;
  $("sx-sound").onchange = () => {
    prefs.sound = $("sx-sound").value;
    savePrefs();
    updateBacking();
  };
  $("sx-vol-sax").value = prefs.volSax;
  $("sx-vol-sax").oninput = () => {
    prefs.volSax = Number($("sx-vol-sax").value);
    savePrefs();
    applyVolumes();
  };
  $("sx-vol-rest").value = prefs.volRest;
  $("sx-vol-rest").oninput = () => {
    prefs.volRest = Number($("sx-vol-rest").value);
    savePrefs();
    applyVolumes();
  };
  const ahead = (v) => {
    prefs.ahead = Math.max(2, Math.min(12, v));
    savePrefs();
    $("sx-ahead").textContent = `${prefs.ahead} s`;
    lane.set(state.notes, { lookahead: prefs.ahead });
  };
  $("sx-ahead-less").onclick = () => ahead(prefs.ahead - 1);
  $("sx-ahead-more").onclick = () => ahead(prefs.ahead + 1);
  ahead(prefs.ahead);
  // A tap on the lane: the song goes to that moment (a note there starts there).
  $("sx-lane").addEventListener("click", (e) => {
    if (edit.on || scrubbed()) return; // «Editar»: a tap picks a note; a drag moved the song
    const r = $("sx-lane").getBoundingClientRect();
    const x = e.clientX - r.left;
    const pps = (r.width - HIT_X) / prefs.ahead;
    const hit = lane.hits.find((h) => x >= h.x && x <= h.x + h.w && e.clientY - r.top >= h.y - 6 && e.clientY - r.top <= h.y + h.h + 6);
    seek(hit ? hit.start : lane.lastT + (x - HIT_X) / pps);
  });
  wireEditing();
  document.addEventListener("keydown", (e) => {
    if (e.target.closest("input, select")) return;
    if (editKey(e)) {
      e.preventDefault();
      return;
    }
    if (e.key === " ") {
      e.preventDefault();
      togglePlay();
    } else if (e.key === "ArrowLeft") seek(audio.currentTime - 5);
    else if (e.key === "ArrowRight") seek(audio.currentTime + 5);
  });
  window.addEventListener("resize", () => lane.resize());
  // The staff takes what the bars around it leave (the edit bar wraps to two
  // rows on a narrow screen).
  new ResizeObserver(() => lane.resize()).observe($("sx-lane"));
  setSpeed(prefs.speed);
}

/** The part the saxophone plays when none is asked for: the voice; in a
 *  song with (almost) no voice, "other", where the separator leaves a
 *  saxophone, the winds, the strings (it has no stem of their own). */
function defaultPart() {
  const voice = state.available.find((s) => VOICES.has(s));
  const quiet = voice && (state.presence?.[voice] ?? 100) < MIN_PRESENCE;
  if ((!voice || quiet) && state.available.includes("other")) {
    state.hint = voice ? "la voz casi no suena: el instrumento principal está en Otros" : "el instrumento principal está en Otros";
    return "other";
  }
  return voice || state.available[0];
}

async function start() {
  wire();
  ensureAudio({ resume: false });
  lane.resize();
  requestAnimationFrame(frame);
  if (!JOB) {
    status("Abre el saxo desde el 🎷 de un stem en el estudio.");
    return;
  }
  try {
    const job = await api(`/api/jobs/${JOB}`);
    $("sx-title").textContent = job.title || JOB;
    document.title = `Saxo — ${job.title || JOB}`;
    const have = new Set((job.stems || []).map((s) => s.name));
    state.available = SAXABLE.filter((s) => have.has(s));
    swam.info = await api("/api/sax/swam").catch(() => null);
    $("sx-engine-field").hidden = !swam.info?.available;
    state.presence = job.stem_presence || {};
    // The song's beats and bars (the studio's beat grid), when it has them.
    state.bars = barGrid(await api(`/api/jobs/${JOB}/beats`).catch(() => null));
    lane.bars = state.bars; // drawn on the staff: beats, bars and their numbers
    showLoop(); // a loop kept from before, named by its bars
    for (const f of document.querySelectorAll(".sx-beats-only")) f.hidden = !state.bars; // the metronome needs the song's beats
  } catch (e) {
    status(`No se encontró la canción: ${e.message}`);
    return;
  }
  state.stems = state.stems.filter((s) => state.available.includes(s));
  if (!state.stems.length && state.available.length) state.stems = [defaultPart()];
  try {
    edit.sets = (await api(`/api/jobs/${JOB}/sax/edits`)).sets || {};
  } catch {
    edit.sets = {};
  }
  renderStems();
  const at = Number(params.get("t"));
  if (at > 0) audio.addEventListener("loadedmetadata", () => seek(at), { once: true });
  await load();
}

start();
