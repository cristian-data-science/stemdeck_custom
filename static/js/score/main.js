// Score view: wiring. /score/?job=<id>&stem=piano
//
// Flow: GET the score -> (if not transcribed) offer to start, poll progress ->
// render the MEI with Verovio -> decorate -> follow the audio -> edit.
//
// Edits are saved on the server as they happen (PUT .../notes), one request
// in flight at a time with only the latest state queued behind it, so a burst
// of key presses costs two requests, not twenty. The server answers with the
// re-engraved score, which is what gets drawn: the page never engraves by
// itself, so what you see is always what is saved.

import {
  History,
  SmoothClock,
  activeAt,
  buildTimeIndex,
  cleanupTargets,
  cursorAt,
  deleteNotes,
  formatTime,
  midiName,
  keyChoices,
  mergeRepeats,
  moveNotes,
  neighbour,
  nextBarShift,
  pitchName,
  resizeNotes,
  savedNote,
  savedNotes,
  previousOnKey,
  joinNotes,
  moveStart,
  addNote,
  snapToOnset,
  pitchOnStaff,
  shiftInScale,
  soundEnd,
  splitChoices,
  toggleHand,
  setHand as setNoteHands,
  transpose,
} from "./model.js";
import { FallView, HAND_COLORS, aheadFromSlider, aheadLabel, clampAhead, sliderFromAhead } from "./fall.js";
import { Player } from "./player.js";
import { MidiInput } from "./midi-input.js";
import {
  beatSecondsAt,
  beatsOf,
  chordDone,
  hitNote,
  loopJump,
  loopOver,
  loopOverNotes,
  measureAt,
  nextChord,
  playsHand,
  rampSpeed,
  snapSpeed,
  readSongPrefs,
  startTime,
  writeSongPrefs,
} from "./practice.js";
import { wireSeparation } from "./separation.js";
import { GLIDE_START, flickSpeed, glideStep, trackFlick } from "./glide.js";
import { fingeringFeature, wireSheetImport } from "./sheet-fingering.js";
import { decorate, hideCursor, markNotes, noteIdOf, notesInRect, placeBar, placeCursor, renderScore } from "./render.js";

const $ = (id) => document.getElementById(id);
const params = new URLSearchParams(location.search);
const JOB = params.get("job");
const STEM = params.get("stem") || "piano";
const API = `/api/jobs/${JOB}/score/${STEM}`;
const CALIBRATION_JOB = "ca11b0000001";
// Stems with a transcription engine (app/score/engines.py), as the page names them.
const STEM_NAMES = {
  piano: "piano",
  bass: "bajo",
  guitar: "guitarra",
  vocals: "voz",
  lead_vocals: "voz principal",
  backing_vocals: "coros",
  other: "otros",
};
const stemName = (s) => STEM_NAMES[s] || s;
const LS = "stemdeck.score.view";
// ?t=<seconds>: where to open the song (the mixer's 𝄞 passes the moment it
// was playing, so the score opens there and not at 0:00).
const START_T = params.get("t");
// Opened (from the mixer's 𝄞, the list, a link): the score, its note names
// off; the piano with falling notes is one tap on «🎹 Piano». Only a reload
// (F5) comes back to the view it was in.
const RELOADED = performance.getEntriesByType?.("navigation")?.[0]?.type === "reload";

const state = {
  data: null,
  notes: [],
  index: buildTimeIndex([]),
  ctx: null,
  selection: new Set(),
  playing: new Set(),
  doomed: new Set(),
  history: new History(),
  pendingWhat: [], // the edits the next save carries, named (the saved history)
  // Note names inside the heads: off until asked for (Nombres, top panel).
  view: {
    noteNames: false,
    zoom: 42,
    follow: true,
    fall: false, // the piano with falling notes instead of the score
    fallKeys: "song",
    fallColors: "hands", // the two hands told apart (P8); «Un color» to choose
    fallNames: "letters",
    fallLabel: "name", // on the falling notes: "name", "finger" or "both" (songs with fingering)
    fallStyle: "3d",
    compact: false, // «Controles ▾»: only the playback line shown
    syncMs: 0, // the picture runs this much behind the audio clock (per device)
    fallAhead: 4, // «Anticipación»: song seconds on screen above the keys
    metronome: false,
    countIn: "0", // «Cuenta»: "0", "bar" or "2bar" before ▶
    ptSlow: true, // Pianoteq rendered at the practice speed when under 100 %
    midiSound: false,
    midiMode: "free",
    ...readView(),
    ...(RELOADED ? {} : { fall: false, noteNames: false }),
    // The hands in two colours became the default: a browser that kept the
    // old default («Un color», saved with the rest) gets it once; a choice
    // made after this is kept.
    ...(readView().handsDefault ? {} : { fallColors: "hands", handsDefault: 1 }),
  },
  // What this song remembers in this browser (practice.js): position, what
  // is heard, speed, the loop, the hand practised.
  song: JOB ? readSongPrefs(localStorage, JOB, STEM) : {},
  loop: null, // {a, b, from, to, on}: bars repeated
  hand: "", // the hand the player plays themself: "", "R" or "L"
  saving: false,
  pending: null,
  lastSys: null,
  adding: false, // «＋ Nota»: a tap on the score or the piano adds a note
  painting: false, // «🖌 Corregir manos»: a tap or a stroke on the piano sets notes' hand
  paintHand: "R", // the hand the brush paints: "R", "L" or "" (back to the program)
  handEdit: null, // a hand correction being saved: {ids, staff: id -> staff before}
};

const player = new Player($("sc-audio"));
const fall = new FallView($("sc-fall"));
window.__fall = fall; // inspection hooks for tests
window.__player = player;
// Experimental: fingers for songs made from a printed score (sheet-fingering.js).
const fingers = fingeringFeature({ $, api, API, fall, state, status: (t) => status(t), onShown: () => {
    fall.setOptions({ names: fallNames() });
    fall.redraw();
  },
});
window.__fingers = fingers;
// Pianoteq rendering (see "Pianoteq" below): wanted?, debounce, newest request,
// the pianos already rendered for these notes, the hand of the file playing.
const pt = { want: false, timer: 0, ticket: 0, key: "", setup: false, ready: new Set(), variants: new Set(), marksTimer: 0, hand: null, removing: 0 };
window.__score = state; // inspection hook for tests and debugging

function readView() {
  try {
    return JSON.parse(localStorage.getItem(LS) || "{}");
  } catch {
    return {};
  }
}

function writeView() {
  localStorage.setItem(LS, JSON.stringify(state.view));
}

/** Keep this song's practice settings (merged into what it had). */
function saveSong(patch) {
  if (!JOB) return;
  state.song = { ...state.song, ...patch };
  writeSongPrefs(localStorage, JOB, STEM, state.song);
}

async function api(path, opts = {}) {
  const res = await fetch(path, {
    headers: opts.body ? { "Content-Type": "application/json" } : {},
    ...opts,
    body: opts.body ? JSON.stringify(opts.body) : undefined,
  });
  if (!res.ok) {
    let detail = res.statusText;
    try {
      const j = await res.json();
      detail = typeof j.detail === "string" ? j.detail : JSON.stringify(j.detail);
    } catch {
      /* not JSON */
    }
    throw new Error(`${res.status}: ${detail}`);
  }
  return res.json();
}

function show(id) {
  for (const s of ["sc-landing", "sc-state", "sc-main"]) $(s).hidden = s !== id;
}

// ── landing ─────────────────────────────────────────────────────────────

/** The badges of a song in the list: score ready (edited), Pianoteq, practice. */
function libraryBadges(info) {
  const out = [];
  for (const [stem, s] of Object.entries(info || {})) {
    const who = stem === "piano" ? "" : ` (${stemName(stem)})`;
    if (s.state === "queued" || s.state === "running") out.push(["run", `extrayendo${who}…`]);
    else if (s.state === "error") out.push(["", `falló${who}`]);
    else if (s.state === "done") {
      out.push(["ok", `partitura${who}${s.edited ? " editada" : ""}`]);
      if (s.pianoteq) out.push(["ok", "Pianoteq ✓"]);
      const p = s.practice || {};
      const mins = Math.round((p.seconds || 0) / 60);
      const bits = [mins ? `${mins} min practicados` : "", p.best_speed ? `mejor ${p.best_speed} %` : "", p.best_accuracy ? `aciertos ${Math.round(p.best_accuracy * 100)} %` : ""].filter(Boolean);
      if (bits.length) out.push(["", bits.join(" · ")]);
    }
  }
  return out;
}

async function landing() {
  show("sc-landing");
  wireSheetImport({ $, api });
  $("sc-title").textContent = "Partitura";
  const list = $("sc-joblist");
  list.innerHTML = "";
  try {
    const lib = await api("/api/score/library").catch(() => ({}));
    const jobs = await api("/api/jobs");
    const items = (Array.isArray(jobs) ? jobs : jobs.jobs || []).filter((j) => j.status === "done");
    if (!items.length) list.innerHTML = '<li class="sc-muted">Todavía no hay canciones separadas.</li>';
    for (const j of items) {
      j.id = j.id || j.job_id;
      const stems = (j.stems || []).map((s) => s.name || s).filter((s) => STEM_NAMES[s]);
      if (!stems.length) continue;
      // Piano first: it has the dedicated engine.
      stems.sort((a, b) => (a === "piano" ? -1 : b === "piano" ? 1 : 0));
      const li = document.createElement("li");
      const a = document.createElement("a");
      a.href = `/score/?job=${encodeURIComponent(j.id)}&stem=${stems[0]}`;
      a.innerHTML = `<span></span><span class="sc-muted"></span>`;
      a.firstChild.textContent = j.title || j.id;
      const model = { demucs: "Demucs", roformer: "RoFormer", none: "Solo piano" }[j.separator];
      a.lastChild.textContent = [j.bpm && `${j.bpm} BPM`, j.key, stems.map(stemName).join(", "), model].filter(Boolean).join(" · ");
      for (const [kind, text] of libraryBadges(lib[j.id])) {
        const b = document.createElement("span");
        b.className = `sc-badge ${kind}`;
        b.textContent = text;
        a.firstChild.appendChild(b);
      }
      li.appendChild(a);
      list.appendChild(li);
    }
  } catch (e) {
    list.textContent = `No se pudo leer la biblioteca: ${e.message}`;
  }
  $("sc-make-calib").onclick = async () => {
    $("sc-make-calib").disabled = true;
    const r = await api("/api/score/calibration", { method: "POST" });
    location.href = `/score/?job=${r.job_id}&stem=piano`;
  };
}

// ── transcription state ─────────────────────────────────────────────────

const PHASES = {
  queued: "En cola (esperando a que termine otra tarea)…",
  download: "Descargando el modelo de piano (solo la primera vez, ~170 MB)…",
  load: "Cargando el audio y el modelo…",
  transcribe: "Escuchando el stem y extrayendo las notas…",
  "cpu-fallback": "La GPU falló; reintentando en la CPU (más lento)…",
  pulse: "Buscando el pulso y los compases en el audio…",
};

/** «Separar de nuevo» (experimental): under the start button before the
 *  score exists (a song whose piano stem is nearly empty needs it then), in
 *  «Diagnóstico» after. Wired once. */
function placeSeparation(where) {
  $(where).appendChild($("sc-resep"));
  if (!state.separationWired) {
    state.separationWired = true;
    wireSeparation({ $, api, job: JOB });
  }
}

/** «Las notas del video» in the source pickers, for a song with a video
 *  (a falling-notes video gives the exact keys; video_notes.py). */
async function offerVideoSource() {
  if (state.videoChecked) return;
  state.videoChecked = true;
  const job = await api(`/api/jobs/${JOB}`).catch(() => null);
  if (!job?.has_video || STEM !== "piano") return;
  for (const id of ["sc-source-pick", "sc-reextract-source"]) $(id).querySelector('[value="video"]').hidden = false;
}

function showState(status) {
  show("sc-state");
  offerVideoSource();
  placeSeparation("sc-state");
  const st = status.state;
  $("sc-state-title").textContent =
    st === "error" ? "La extracción falló" : st === "none" ? `Extraer MIDI: ${stemName(STEM)}` : "Extrayendo MIDI…";
  $("sc-state-text").textContent =
    st === "none"
      ? "Se escucha el stem, se detectan sus notas y se dibuja la partitura con clave de sol y de fa, los nombres de las notas y los acordes. Con GPU NVIDIA tarda segundos (una canción de 9 minutos, unos 30 s); en CPU, aproximadamente lo que dura la canción."
      : st === "error"
        ? "Puedes reintentar. Si vuelve a fallar, el detalle de abajo ayuda a diagnosticar."
        : PHASES[status.phase] || "Trabajando…";
  $("sc-progress").hidden = !(st === "queued" || st === "running");
  $("sc-progress-bar").style.width = `${Math.round((status.progress || 0) * 100)}%`;
  $("sc-start").hidden = st === "queued" || st === "running";
  $("sc-source-wrap").hidden = STEM !== "piano" || st === "queued" || st === "running";
  $("sc-start").textContent = st === "error" ? "Reintentar" : "Extraer MIDI y generar partitura";
  $("sc-error").hidden = st !== "error";
  $("sc-error").textContent = status.error || "";
}

async function poll() {
  for (;;) {
    const data = await api(API);
    if (data.status.state === "done") return data;
    showState(data.status);
    if (data.status.state === "error" || data.status.state === "none") return null;
    await new Promise((r) => setTimeout(r, 1000));
  }
}

/** Start (or redo) the transcription and load the result. */
async function extract(source, force = false) {
  const q = new URLSearchParams({ source });
  if (force) q.set("force", "true");
  const r = await fetch(`${API}?${q}`, { method: "POST" });
  const body = await r.json();
  if (r.status === 200 && body.status?.state === "done") return load(body);
  const data = await poll();
  if (data) await load(data);
}

$("sc-start").onclick = async () => {
  $("sc-start").disabled = true;
  try {
    await extract($("sc-source-pick").value);
  } catch (e) {
    showState({ state: "error", error: e.message });
  } finally {
    $("sc-start").disabled = false;
  }
};

// ── score ───────────────────────────────────────────────────────────────

async function load(data) {
  show("sc-main");
  apply(data);
  $("sc-chips").hidden = false;
  $("sc-export").hidden = false;
  const job = await api(`/api/jobs/${JOB}`).catch(() => null);
  // The song's length at once (it said 0:00 until the audio had loaded).
  state.songDuration = job?.duration || 0;
  if (state.songDuration && !player.duration) $("sc-total").textContent = formatTime(state.songDuration);
  const stems = (job?.stems || []).map((s) => s.name || s);
  player.setUrls({
    // FLAC (lossless, seeks to the sample): switching between the stem, the
    // song and Pianoteq keeps the exact moment. A VBR MP3 landed 40-170 ms
    // off on each switch while reporting the time asked for.
    stem: `/api/jobs/${JOB}/score/audio/${STEM}.flac`,
    mix: stems.length ? `/api/jobs/${JOB}/score/audio/mix.flac` : "",
  });
  const noMix = !stems.length || stems.length === 1;
  if (noMix) $("sc-source").querySelector('[value="mix"]').disabled = true;
  // Where to start: the moment the mixer was at (?t=), else where this song
  // was left. Lands with the file being loaded (player.pending).
  player.seek(startTime(START_T, state.song.t, data.measures?.at(-1)?.end ?? Infinity));
  const saved = state.song.source;
  if (saved && saved !== "pianoteq" && !(saved === "mix" && noMix)) {
    $("sc-source").value = saved;
    player.setSource(saved);
  } else if ((data.stats.audio_source === "original" || data.stats.audio_source === "video") && !noMix) {
    // Transcribed from the original audio (a solo piano): the separated piano
    // stem is the incomplete half of it, so play the whole song.
    $("sc-source").value = "mix";
    player.setSource("mix");
  }
  if (state.song.speed) setSpeed(state.song.speed);
  if (state.song.loop) setLoop(state.song.loop);
  setHand(state.song.hand || "");
  $("sc-view-actions").hidden = false;
  setBare(!!state.view.bare);
  if (JOB === CALIBRATION_JOB) calibrationCheck();
  pianoteqSetup();
  fingers.load();
  setFallView(!!state.view.fall);
}

/** Playback speed in %: one of the practice speeds (25, 50, 70, 100), pitch
 *  kept; remembered in this browser. The audio, the MIDI synth, Pianoteq and
 *  the cursor all follow it. */
function setSpeed(pct) {
  const v = snapSpeed(pct);
  const was = Math.round(player.rate * 100);
  for (const b of document.querySelectorAll("[data-speed]")) b.setAttribute("aria-pressed", String(Number(b.dataset.speed) === v));
  player.setRate(v / 100);
  state.view.speed = v;
  writeView();
  saveSong({ speed: v });
  // Pianoteq at the practice speed: a render made at it, asked for once the
  // speed settles (the one playing now keeps going, stretched, meanwhile).
  if (v !== was && pt.want && state.view.ptSlow && $("sc-source").value === "pianoteq") pianoteqSoon();
}

/** «Sincronía»: how far the picture is held behind the audio clock, in ms,
 *  for sound that reaches the ear later than the browser reports. */
function setSync(ms) {
  const v = Math.max(-100, Math.min(500, Math.round(ms / 10) * 10));
  $("sc-sync").value = v;
  $("sc-sync-val").textContent = `${v} ms`;
  state.view.syncMs = v;
  writeView();
  lastT = -1; // redraw now, even when paused
}

/** The Pedal slider: the synth follows it at once; the server keeps it (and
 *  Pianoteq renders with it) when the slider is let go. */
function setPedal(pct) {
  $("sc-pedal").value = pct;
  $("sc-pedal-val").textContent = `${pct} %`;
  player.pedal = pct;
  player.resetSynth();
  const src = $("sc-pedal-wrap").dataset.source;
  $("sc-pedal-wrap").title =
    "Cuánto sostiene el pedal al reproducir (MIDI y Pianoteq): 0 % cada nota lo que se sostuvo la tecla, 100 % " +
    (src === "transcription" ? "el pedal del pianista, tal como se oyó en el audio" : "el pedal cambiado en cada acorde");
}

// ── Pianoteq ────────────────────────────────────────────────────────────
// The server renders the score with Pianoteq (when installed) to a FLAC on
// the song's timeline; it plays as the clock, like the stem. Each edit makes
// the render stale: a new one is asked for after a short pause, and the old
// one keeps playing until the new one is ready.

const PT_STATUS_FADE_MS = 6000;
let ptStatusTimer = 0;
/** The floating Pianoteq status. `fade`: a «✓» that goes away by itself
 *  (it floats over the piano now: it must not stay there for good). */
function ptStatus(text, { fade = false } = {}) {
  clearTimeout(ptStatusTimer);
  $("sc-pt-status").hidden = !text;
  $("sc-pt-status").textContent = text;
  $("sc-pt-status").title = text || ""; // cut to one line: the whole of it
  if (text && fade) ptStatusTimer = setTimeout(() => ptStatus(""), PT_STATUS_FADE_MS);
}

/** The pianos in the select, those already rendered for these notes marked
 *  «✓» (they play at once, nothing is generated). */
function ptLabels() {
  for (const o of $("sc-pt-preset").options) o.textContent = pt.ready.has(o.value) ? `${o.value} ✓` : o.value;
}

async function ptRefreshReady() {
  const r = await api(`${API}/pianoteq/ready`).catch(() => null);
  if (!r) return null;
  pt.ready = new Set(r.ready || []);
  pt.variants = new Set(r.variants || []);
  ptLabels();
  ptSpeedMarks();
  return r;
}

/** ✓ on the speeds Pianoteq already has (both hands, right, left): those
 *  play at once. Asked again while some are missing (the server makes them
 *  in the background). */
function ptSpeedMarks() {
  let missing = 0;
  for (const b of document.querySelectorAll("[data-speed]")) {
    const v = b.dataset.speed;
    const have = ["both", "R", "L"].filter((h) => pt.variants.has(`${v}:${h}`));
    b.classList.toggle("sc-pt-ready", have.length === 3);
    b.title = have.length === 3
      ? `${v} %: Pianoteq listo (ambas manos, derecha e izquierda)`
      : `${v} %${pt.setup ? ` · Pianoteq: ${have.length ? `${have.length} de 3 listas` : "aún no"} (se genera en segundo plano)` : ""}`;
    if (have.length < 3) missing += 1;
  }
  clearTimeout(pt.marksTimer);
  if (pt.setup && missing) pt.marksTimer = setTimeout(ptRefreshReady, 20000);
}

async function pianoteqSetup() {
  // Once: «Volver a extraer» loads the score again, and the pianos were
  // added to the list a second time (every name twice).
  if (pt.setup) return ptRefreshReady();
  pt.setup = true;
  const info = await api("/api/score/pianoteq").catch(() => null);
  if (!info?.available) return;
  const sel = $("sc-pt-preset");
  sel.innerHTML = "";
  for (const name of info.presets) sel.add(new Option(name, name));
  // This song's own piano first (the one it was last heard with), then the
  // default piano (the server's: Bösendorfer VC Player when installed), then
  // one already rendered for these notes. The last piano chosen on any song
  // is no longer used: a song without its own piano took a Steinway chosen
  // elsewhere and rendered itself again.
  const own = state.data?.pianoteq?.preset;
  const ready = await ptRefreshReady();
  const firstReady = ready?.ready?.[0];
  sel.value = [own, info.default, firstReady].find((p) => p && info.presets.includes(p));
  ptLabels();
  $("sc-source").querySelector('[value="pianoteq"]').hidden = false;
  $("sc-pt-slow-wrap").hidden = false;
  $("sc-pt-slow").checked = state.view.ptSlow !== false;
  if (state.song.source === "pianoteq") {
    $("sc-source").value = "pianoteq";
    $("sc-pt-wrap").hidden = false;
    player.setSource("pianoteq"); // the synth plays until the file is there
    handHint();
  }
  // Always rendered, listened to or not (the server started it when the score
  // was made): choosing «Pianoteq» then plays at once, and edits re-render.
  pianoteqRender();
}

/** The hand Pianoteq plays (the other one is the player's), and its speed. */
function ptRequest() {
  const listening = $("sc-source").value === "pianoteq";
  // Rendered behind the scenes (not listened to): the whole score, the one
  // every other choice starts from.
  const hand = !listening ? null : state.hand === "R" ? "L" : state.hand === "L" ? "R" : null;
  const pct = Math.round(player.rate * 100);
  const speed = listening && state.view.ptSlow && pct < 100 ? pct / 100 : 1;
  return { preset: $("sc-pt-preset").value, hand, speed };
}

/** «Quitando N notas de Pianoteq», while the file playing still has them. */
function ptRemovingText(secs) {
  const n = pt.removing;
  return `⏳ Pianoteq: quitando ${n} nota${n === 1 ? "" : "s"}${secs ? `… ${secs} s` : "…"} (sigue sonando la pista actual)`;
}

function pianoteqSoon() {
  clearTimeout(pt.timer);
  ptStatus(
    pt.removing && !player.ptStale
      ? ptRemovingText()
      : player.ptStale
        ? "Pianoteq: actualizando tu edición (mientras, suena el MIDI)…"
        : "Pianoteq: cambios sin escuchar aún…",
  );
  pt.timer = setTimeout(pianoteqRender, 1200);
}

async function pianoteqRender() {
  pt.want = true;
  clearTimeout(pt.timer);
  const ticket = ++pt.ticket;
  const body = ptRequest();
  const { preset } = body;
  const what = `${preset}${body.hand ? ` (solo mano ${body.hand === "R" ? "derecha" : "izquierda"})` : ""}${body.speed !== 1 ? ` a ${Math.round(body.speed * 100)} %` : ""}`;
  try {
    let st = await api(`${API}/pianoteq`, { method: "POST", body });
    if (ticket !== pt.ticket) return;
    // Not ready: the file playing has the other hand(s) in it, the hand the
    // player is playing among them. The synth (which has the right hands)
    // plays until the new one is there. Ready (rendered beforehand: see
    // the server, in the background), the new file just takes over.
    if (st.state === "rendering") {
      if (pt.key && body.hand !== pt.hand) player.setPianoteqStale(true);
      ptStatus(`Pianoteq: generando con ${what}…`);
    }
    const started = performance.now();
    while (st.state === "rendering") {
      await new Promise((r) => setTimeout(r, 1000));
      if (ticket !== pt.ticket) return; // superseded by a newer edit or preset
      st = await api(`${API}/pianoteq/status/${st.key}`);
      // Skipped by the server for a newer one (another tab, the automatic
      // render): asked again, which starts it if it is still the one wanted.
      if (st.state === "none") st = await api(`${API}/pianoteq`, { method: "POST", body });
      const secs = Math.round((performance.now() - started) / 1000);
      if (pt.removing && !player.ptStale) {
        ptStatus(ptRemovingText(secs));
        continue;
      }
      const meanwhile = player.synthOnly ? " (mientras, suena el MIDI)" : pt.key ? " (mientras, suena el anterior)" : "";
      ptStatus(`Pianoteq: generando con ${what}… ${secs} s${meanwhile}`);
    }
    if (ticket !== pt.ticket || !pt.want) return;
    if (st.state !== "ready") throw new Error(st.error || "no se pudo generar");
    pt.key = st.key;
    pt.hand = body.hand;
    if (!body.hand && body.speed === 1) {
      pt.ready.add(preset);
      ptLabels();
    }
    player.setUrls({ pianoteq: st.url }, { ptSpeed: body.speed });
    player.setPianoteqStale(false);
    if ($("sc-source").value === "pianoteq") player.setSource("pianoteq");
    const gone = pt.removing;
    pt.removing = 0;
    ptStatus(gone ? `Pianoteq: ${gone === 1 ? "nota quitada" : `${gone} notas quitadas`} ✓` : `Pianoteq: ${what} ✓`, { fade: true });
    ptRefreshReady(); // the ✓ on the speeds
  } catch (e) {
    if (ticket === pt.ticket) ptStatus(`Pianoteq: ${e.message}`);
  }
}

function apply(data) {
  // Any new payload may change what Pianoteq plays; the same notes and preset
  // come back from the server's cache at once.
  if (pt.want && state.data && data !== state.data) pianoteqSoon();
  // The notes changed (an edit, the pedal): the pianos rendered for the old
  // ones are not the ones ready any more (compared before state.data moves on).
  const sig = (d) => `${d.version}:${d.settings?.pedal}`;
  if (pt.setup && state.data && sig(data) !== sig(state.data)) {
    pt.ready.clear();
    ptLabels();
  }
  state.data = data;
  state.notes = data.notes;
  state.index = buildTimeIndex(data.notes);
  player.setNotes(data.notes);
  fall.setNotes(data.notes);
  fall.setMeasures(data.measures);
  player.setBeats(beatsOf(data.measures));
  fingers.refresh();
  renderTrash();
  // A song off A440 was transcribed retuned; the synth plays at the song's
  // tuning so «Stem + MIDI» is in tune (Pianoteq gets a pitch bend).
  player.detune = data.stats.tuning?.corrected ? data.stats.tuning.cents : 0;
  const job = data.job || {};
  document.title = `Partitura — ${job.title || JOB}`;
  $("sc-title").textContent = job.title || JOB;
  const model = { demucs: "separado con Demucs", roformer: "separado con RoFormer", none: "solo piano, sin separar" }[job.separator];
  $("sc-sub").textContent = `Stem: ${stemName(STEM)}${model ? ` · ${model}` : ""} · motor: ${data.stats.engine || "?"}${data.edited ? " · editada" : ""}`;
  $("sc-bpm").textContent = data.bpm ?? "–";
  $("sc-meter").textContent = data.meter;
  $("sc-key").textContent = data.key.name;
  $("sc-count").textContent = data.notes.length;
  $("sc-dl-mid").href = `${API}/export.mid?quantized=true`;
  $("sc-dl-raw").href = `${API}/export.mid?quantized=false`;
  $("sc-dl-xml").href = `${API}/export.musicxml`;
  syncControls();
  diagnostics();
  showReviewed();
  return draw();
}

function syncControls() {
  const d = state.data;
  $("sc-grid").value = d.settings.grid;
  $("sc-tempo").value = d.settings.tempo;
  $("sc-chordrate").value = d.settings.chords ? d.settings.chord_rate : "off";
  $("sc-names").value = state.view.noteNames ? d.names : "none";
  $("sc-pedal-wrap").dataset.source = d.stats.pedal_source;
  if (!state.pedalDragging) setPedal(d.settings.pedal || 0);
  const split = $("sc-split");
  if (!split.options.length || split.dataset.names !== d.names) {
    split.innerHTML = "";
    for (const c of splitChoices(d.names)) split.add(new Option(c.label, c.midi));
    split.dataset.names = d.names;
  }
  split.value = d.settings.split;
  const keySel = $("sc-key-select");
  keySel.innerHTML = "";
  const k = d.key;
  keySel.add(new Option(`Auto${k.notes ? ` (notas: ${k.notes})` : ""}`, "auto"));
  if (k.song) keySel.add(new Option(`De la canción (${k.song})`, "song"));
  for (const c of keyChoices(d.names)) keySel.add(new Option(c.label, c.id));
  keySel.value = d.settings.key;
  $("sc-meter-select").value = d.settings.meter;
  $("sc-pulse-select").value = d.settings.pulse;
  $("sc-pulse-select").querySelector('[value="notes"]').disabled = !d.stats.pulse_notes_available;
  $("sc-hands-select").value = d.settings.hands;
  $("sc-pulse-select").querySelector('[value="audio"]').disabled = !d.stats.pulse_own_available;
  $("sc-zoom").value = state.view.zoom;
  $("sc-follow").checked = state.view.follow;
  for (const [id, can, label, verb, key] of [
    ["sc-undo", state.history.canUndo, state.history.undoLabel, "Deshacer", "Ctrl+Z"],
    ["sc-redo", state.history.canRedo, state.history.redoLabel, "Rehacer", "Ctrl+Y"],
    ["sc-undo2", state.history.canUndo, state.history.undoLabel, "Deshacer", "Ctrl+Z; en la tablet, toque con dos dedos sobre el piano"],
    ["sc-redo2", state.history.canRedo, state.history.redoLabel, "Rehacer", "Ctrl+Y; en la tablet, toque con tres dedos"],
  ]) {
    $(id).disabled = !can;
    $(id).title = `${verb}${label ? `: ${label}` : ""} (${key})`;
  }
}

async function draw() {
  const scroll = window.scrollY;
  const ctx = await renderScore($("sc-score"), state.data.mei, { zoom: state.view.zoom });
  decorate(ctx, state.data.notes, state.data.measures, {
    names: state.data.names,
    labels: state.view.noteNames,
  });
  state.ctx = ctx;
  state.lastSys = null;
  const ids = new Set(state.notes.map((n) => n.id));
  state.selection = new Set([...state.selection].filter((id) => ids.has(id)));
  markNotes(ctx, "sd-selected", state.selection);
  state.playing = markNotes(ctx, "sd-playing", []);
  updateDoomed();
  for (const h of ctx.container.querySelectorAll("g.harm")) {
    const c = state.data.chords.find((x) => x.id === h.id);
    if (c?.override) h.classList.add("sd-override");
  }
  window.scrollTo({ top: scroll });
  status();
  if (state.calibExpected) renderCalibrationAuto(state.calibExpected);
  document.body.dataset.rendered = String(Date.now());
  ctx.container.dataset.renderMs = ctx.ms;
}

function diagnostics() {
  const s = state.data.stats;
  const rows = [
    ["Notas en la partitura", s.notes],
    ["Notas detectadas por el modelo", s.raw_notes],
    ["Quitadas automáticamente (< 30 ms)", s.auto_removed],
    ["Quitadas por no tener ataque en el audio o venir de la voz (en «Notas borradas»)", s.ghosts_removed ?? 0],
    ["Compases", s.measures],
    ["Acordes", s.chords],
    ["BPM detectado al separar", s.detected_bpm ?? "–"],
    ["BPM de la partitura", state.data.bpm],
    ["Confianza del beat grid", s.beat_confidence != null ? `${s.beat_confidence}%` : "–", s.beat_confidence != null && s.beat_confidence < 50],
    ["Notas movidas > 40 ms al cuantizar", `${s.moved_over_40ms} (${s.moved_pct}%)`, s.moved_pct > 25],
    ["Notas duplicadas (misma nota, mismo inicio)", s.duplicates ?? 0, (s.duplicates ?? 0) > 0],
    ["Motor", s.engine],
    ["Audio transcrito", `${{ original: "el audio original", video: "las notas del video" }[s.audio_source] || "el stem"}${s.audio_source_reason ? ` (${s.audio_source_reason})` : ""}`],
    [
      "Afinación del audio",
      s.tuning?.cents == null
        ? "– (extraído antes de medirla)"
        : `${s.tuning.cents > 0 ? "+" : ""}${s.tuning.cents} cents respecto de La 440${s.tuning.corrected ? " — corregida antes de transcribir" : ""}`,
      s.tuning?.cents == null,
    ],
    ["Tonalidad", `${state.data.key.name} — ${{ notes: "estimada de las notas", song: "del análisis de la canción", manual: "elegida a mano", default: "por defecto" }[state.data.key.source] || ""}`],
    ["Tonalidad según las notas", state.data.key.notes ? `${state.data.key.notes} (correlación ${state.data.key.notes_confidence}, ventaja ${state.data.key.notes_margin})` : "–", state.data.key.notes_margin != null && state.data.key.notes_margin < 0.05],
    ["Tonalidad según la canción", state.data.key.song || "–"],
    ["Compás", `${state.data.meter} — ${{ auto: "uno para toda la canción", notes: "por dónde cae el bajo más grave", detected: "como lo halló el detector", manual: "elegido a mano", default: "por defecto (sin barras detectadas)" }[s.meter_source] || ""}`],
    ["Pulso", `${{ audio: "del audio transcrito", notes: "de las notas transcritas" }[s.pulse_source] || "de la canción"}${s.pulse_reason && s.pulse_reason !== "elegido" ? ` (${s.pulse_reason})` : ""}`],
    ["Pulsos insertados (tramos a medio tempo)", s.beats_inserted ?? 0],
    ["Dispositivo", s.device === "cuda" ? "GPU (CUDA)" : s.device === "cpu" ? "CPU" : s.device || "–"],
    [
      "Manos guardadas para reentrenar",
      (() => {
        const h = state.data.hand_labels || {};
        return `${h.corrected || 0} nota${h.corrected === 1 ? "" : "s"} corregida${h.corrected === 1 ? "" : "s"} por ti${h.reviewed ? ` · canción revisada (${h.reviewed_notes} notas)` : ""}`;
      })(),
    ],
    ["Versión guardada", state.data.version],
    ["Tiempo de dibujo", state.ctx ? `${state.ctx.ms} ms` : "–"],
  ];
  const tips = [];
  if (s.tuning?.cents == null && s.engine) tips.push("Esta partitura se extrajo antes de medir la afinación: si la canción no está en La 440 (versiones «slowed» o «sped up»), «Volver a extraer» la corrige.");
  if (s.duplicates > 0) tips.push(`${s.duplicates} notas están repetidas en el mismo instante y se dibujan como una: «Limpiar…» → «Unir notas repetidas» las fusiona.`);
  if (s.moved_pct > 25) tips.push("Muchas notas lejos de la rejilla: prueba Tempo × ½ / × 2 o una rejilla más fina. Si sigue igual, el beat grid de la canción no es fiable.");
  if (s.beat_confidence != null && s.beat_confidence < 50) tips.push("El beat grid tiene poca confianza: la cuantización puede fallar aunque las notas sean correctas (compruébalo con «Escuchar: MIDI extraído»).");
  $("sc-reextract").hidden = STEM !== "piano";
  placeSeparation("sc-diag");
  offerVideoSource();
  $("sc-diag-body").innerHTML =
    "<table>" +
    rows.map(([k, v, w]) => `<tr><td>${k}</td><td class="${w ? "warn" : ""}">${v}</td></tr>`).join("") +
    "</table>" +
    tips.map((t) => `<p class="warn">${t}</p>`).join("");
  if (tips.length) $("sc-diag").open = true;
}

async function calibrationCheck() {
  const r = await api("/api/score/calibration/expected").catch(() => null);
  if (!r) return;
  $("sc-calib-check").hidden = false;
  $("sc-calib-text").textContent = r.expected_text;
  renderCalibrationAuto(r.expected);
}

function renderCalibrationAuto(exp) {
  const d = state.data;
  if (!d || !exp) return;
  state.calibExpected = exp;
  const svg = $("sc-score");
  // [label, got, want, ok?]. Notes: the piano model cannot hear the F3 that
  // doubles F2 an octave up in the last chord, so 58 of 59 is a pass.
  const checks = [
    ["BPM", d.bpm, exp.bpm],
    ["Compás", d.meter, exp.meter],
    ["Tonalidad", d.key.name, exp.key],
    ["Compases", d.measures.length, exp.measures],
    ["Notas", d.notes.length, exp.notes, d.notes.length === exp.notes || d.notes.length === exp.notes - 1],
    ["Acordes", d.chords.map((c) => c.text).join(" "), exp.chords.join(" ")],
    ["Claves dibujadas (sol + fa)", svg.querySelectorAll("g.clef").length >= 2 ? "sí" : "no", "sí"],
    ["Etiquetas dentro de las notas", svg.querySelectorAll(".sd-pill").length, svg.querySelectorAll("g.note").length],
  ];
  $("sc-calib-auto").innerHTML =
    "<b>Comprobación automática:</b><br>" +
    checks
      .map(([k, got, want, pass]) => {
        const ok = pass ?? String(got) === String(want);
        return `<span class="${ok ? "ok" : "bad"}">${ok ? "✓" : "✗"} ${k}: ${got}${String(got) === String(want) ? "" : ` (esperado: ${want})`}</span>`;
      })
      .join("<br>") +
    '<br><span class="sc-muted">El modelo puede perder una nota doblada a la octava (el Fa3 del último acorde): 58 de 59 es un resultado normal.</span>';
}

function status(text) {
  if (text) {
    $("sc-status").textContent = text;
    return;
  }
  const sel = [...state.selection].map((id) => state.notes.find((n) => n.id === id)).filter(Boolean);
  const names = state.data.names;
  if (!sel.length) {
    // Short, so it fits beside the editing actions on a tablet; the rest on hover.
    $("sc-status").textContent = "Toca una nota para elegirla · ? atajos";
    $("sc-status").title = "Clic en una nota para elegirla (Mayús/Ctrl + clic: varias; arrastrar en vacío: un área). «?» muestra todos los atajos de teclado.";
  } else if (sel.length === 1) {
    const n = sel[0];
    $("sc-status").textContent =
      `${pitchName(n, names)} · ${n.staff === 1 ? "clave de sol (mano derecha)" : "clave de fa (mano izquierda)"}` +
      ` · compás ${n.measure ?? "?"} · empieza ${n.start.toFixed(2)} s · dura ${(soundEnd(n) - n.start).toFixed(2)} s` +
      (n.end - soundEnd(n) > 0.5 ? ` (el modelo la oyó ${(n.end - n.start).toFixed(1)} s; se dibuja y suena hasta la nota siguiente)` : "") +
      ` · velocidad ${n.velocity}` +
      fingers.describe(n.id);
  } else {
    $("sc-status").textContent = `${sel.length} notas seleccionadas`;
  }
}

// ── saving ──────────────────────────────────────────────────────────────

function saveState(kind, text) {
  const el = $("sc-save");
  el.className = `sc-save ${kind}`;
  el.textContent = text;
}

/** Record the current notes for undo, then save `next`. */
function edit(next, what) {
  state.history.push(state.notes, what);
  commit(next, what);
  status(`${what} · guardando…`);
}

/** How many notes `next` only takes away from `prev` (nothing else
 *  changed: the same note objects), else 0. */
function onlyRemoved(prev, next) {
  if (!prev || next.length >= prev.length) return 0;
  const before = new Set(prev);
  return next.every((n) => before.has(n)) ? prev.length - next.length : 0;
}

function commit(next, what = "") {
  // Named in the saved history (several edits saved at once: all of them).
  if (what && !state.pendingWhat.includes(what)) state.pendingWhat.push(what);
  // Notes deleted while Pianoteq plays: its current file keeps playing (an
  // extra note for a few seconds, not a jump to the MIDI synth's sound and
  // the rhythm lost) until the render without them takes over, said by the
  // floating status. Any other edit: the synth plays it at once, as before.
  const listening = $("sc-source").value === "pianoteq";
  const removed = pt.want && pt.key && listening && !player.ptStale ? onlyRemoved(state.notes, next) : 0;
  state.notes = next;
  fall.setNotes(next);
  // Heard at once, not after the server's answer: a deleted note scheduled
  // meanwhile still sounded. Pianoteq's file is behind until it re-renders.
  player.setNotes(next);
  if (removed) {
    pt.removing += removed;
    ptStatus(ptRemovingText());
  } else if (pt.want) {
    pt.removing = 0;
    player.setPianoteqStale(true);
  }
  state.pending = next;
  syncControls();
  flush();
}

async function flush() {
  if (state.saving || !state.pending) return;
  const notes = state.pending;
  const what = state.pendingWhat.join(" + ").slice(0, 160) || null;
  state.pending = null;
  state.pendingWhat = [];
  state.saving = true;
  saveState("", "Guardando…");
  try {
    const data = await api(`${API}/notes`, { method: "PUT", body: { notes: savedNotes(notes), what } });
    if (!$("sc-history").hidden) renderHistory();
    if (!state.pending) {
      await apply(data);
      saveState("ok", `Guardado ✓ (versión ${data.version})`);
      reportHandEdit(data);
    }
  } catch (e) {
    saveState("err", `No se pudo guardar: ${e.message}`);
    state.pending = state.pending || notes;
    setTimeout(flush, 2000);
  } finally {
    state.saving = false;
    if (state.pending) flush();
  }
}

async function putSettings(body) {
  saveState("", "Aplicando…");
  try {
    const data = await api(`${API}/settings`, { method: "PUT", body });
    await apply(data);
    saveState("ok", "Guardado ✓");
  } catch (e) {
    saveState("err", e.message);
  }
}

// ── selection & editing ─────────────────────────────────────────────────

function select(ids, { add = false } = {}) {
  const next = add ? new Set(state.selection) : new Set();
  for (const id of ids) {
    if (add && next.has(id) && ids.length === 1) next.delete(id);
    else next.add(id);
  }
  state.selection = markNotes(state.ctx, "sd-selected", next, state.selection);
  fall.setSelection(state.selection);
  status();
  updateEditBar();
}

/** «Borradas»: the deleted-notes history the server keeps (newest first),
 *  each one restorable, or all at once. */
function renderTrash() {
  const trash = state.data?.trash || [];
  $("sc-trash-toggle").hidden = !trash.length;
  $("sc-trash-count").textContent = String(trash.length);
  if (!trash.length) $("sc-trash").hidden = true;
  const flats = (state.data?.key?.fifths ?? 0) < 0;
  const names = state.data?.names === "letters" ? "letters" : "solfege";
  const list = $("sc-trash-list");
  list.innerHTML = "";
  const now = Date.now() / 1000;
  for (const t of trash.slice(0, 300)) {
    const li = document.createElement("li");
    const ago = Math.max(0, now - (t.deleted_at || now));
    const when = ago < 60 ? "recién" : ago < 3600 ? `hace ${Math.round(ago / 60)} min` : ago < 86400 ? `hace ${Math.round(ago / 3600)} h` : `hace ${Math.round(ago / 86400)} d`;
    li.innerHTML = `<b></b><span></span><span class="sc-muted"></span><button class="sc-btn" type="button">Restaurar</button>`;
    li.children[0].textContent = midiName(t.midi, { flats, names });
    li.children[1].textContent = `en ${formatTime(t.start)}`;
    li.children[2].textContent =
      { ghost: "sin ataque en el audio", bleed: "se oye en la voz, no en el piano" }[t.reason] || `borrada ${when}`;
    li.querySelector("button").onclick = () => restoreNotes([t]);
    list.appendChild(li);
  }
  if (trash.length > 300) {
    const li = document.createElement("li");
    li.className = "sc-muted";
    li.textContent = `… y ${trash.length - 300} más (Restaurar todas las devuelve)`;
    list.appendChild(li);
  }
}

function restoreNotes(entries) {
  const have = new Set(state.notes.map((n) => n.id));
  const back = entries.filter((t) => !have.has(t.id)).map((t) => savedNote(t));
  if (!back.length) return;
  edit([...state.notes, ...back], back.length === 1 ? "Nota restaurada" : `${back.length} notas restauradas`);
}

/** The floating bar for touch: how many notes are selected, and 🗑. */
function updateEditBar() {
  const n = state.selection.size;
  $("sc-editbar").hidden = !n;
  if (n) $("sc-editbar-n").textContent = n === 1 ? "1 nota" : `${n} notas`;
}

function deleteSelected() {
  const ids = selected();
  if (!ids.length) return;
  const next = deleteNotes(state.notes, ids);
  select([]);
  edit(next, `${ids.length} nota(s) borrada(s)`);
}

/** Apply a drag: `steps` grid steps in time, then pitch (semitones on the
 *  piano, scale steps on the staff). */
function applyDrag(ids, steps, { semis = 0, scaleSteps = 0 } = {}) {
  let next = state.notes;
  if (steps) next = moveNotes(next, ids, steps);
  if (semis) next = transpose(next, ids, semis);
  if (scaleSteps) next = shiftInScale(next, ids, scaleSteps, state.data.key.id);
  if (next !== state.notes) edit(next, "Movida");
}

const selected = () => [...state.selection];

function onKey(e) {
  if (e.target.closest("input, select, textarea, dialog")) return;
  const ctrl = e.ctrlKey || e.metaKey;
  const ids = selected();
  const k = e.key;
  if (k === " ") {
    e.preventDefault();
    togglePlay();
    return;
  }
  if (!ctrl && k.toLowerCase() === "l") return toggleLoop();
  if (!ctrl && k.toLowerCase() === "f") return toggleFullscreen();
  if (!ctrl && k.toLowerCase() === "p") return setBare(!state.view.bare);
  if (ctrl && k.toLowerCase() === "z" && !e.shiftKey) return (e.preventDefault(), undo());
  if (ctrl && (k.toLowerCase() === "y" || (k.toLowerCase() === "z" && e.shiftKey))) return (e.preventDefault(), redo());
  if (ctrl && k.toLowerCase() === "a") {
    e.preventDefault();
    return select(state.notes.map((n) => n.id));
  }
  if (k === "Escape") return state.adding ? setAdding(false) : state.painting ? setPainting(false) : select([]);
  if (!ctrl && k.toLowerCase() === "n") return setAdding(!state.adding);
  // The piano view: + shows fewer seconds (notes spread out), − more (closer
  // together: more of what is coming on screen).
  if (!ctrl && state.view.fall && ["+", "=", "-", "_"].includes(k)) {
    e.preventDefault();
    return setAhead(clampAhead(state.view.fallAhead) * (k === "+" || k === "=" ? 1 / AHEAD_FACTOR : AHEAD_FACTOR), { hint: true });
  }
  if (k === "Tab") {
    e.preventDefault();
    const id = neighbour(state.notes, ids[ids.length - 1], e.shiftKey ? -1 : 1);
    if (id) {
      select([id]);
      scrollToNote(id);
    }
    return;
  }
  if (!ids.length) return;
  // Experimental fingering: 1-5 sets the finger of the selected notes, 0 goes
  // back to the suggested one (only on songs that have fingering).
  if (fingers.available && !ctrl && /^[0-5]$/.test(k)) {
    e.preventDefault();
    fingers.set(ids, k === "0" ? null : Number(k));
    return;
  }
  let next = null;
  let what = "";
  if (k === "Delete" || k === "Backspace") {
    e.preventDefault();
    return deleteSelected();
  } else if (k === "ArrowUp" || k === "ArrowDown") {
    const d = (k === "ArrowUp" ? 1 : -1) * (ctrl ? 12 : 1);
    next = transpose(state.notes, ids, d);
    what = ctrl ? "Octava" : "Semitono";
  } else if (k === "ArrowLeft" || k === "ArrowRight") {
    const d = k === "ArrowRight" ? 1 : -1;
    next = e.shiftKey ? resizeNotes(state.notes, ids, d) : moveNotes(state.notes, ids, d);
    what = e.shiftKey ? "Duración" : "Movida";
  } else if (k.toLowerCase() === "h") {
    next = toggleHand(state.notes, ids);
    what = "Cambio de mano";
    noteHandEdit(ids);
  } else if (k.toLowerCase() === "a" && !ctrl) {
    const n = state.notes.find((x) => x.id === ids[0]);
    if (n) openChordDialog(Math.round(n.q_start * 1000), "");
    return;
  } else {
    return;
  }
  e.preventDefault();
  edit(next, what);
}

function undo() {
  const prev = state.history.undo(state.notes);
  if (prev) {
    const what = state.history.label;
    commit(prev, what ? `Deshacer: ${what}` : "Deshacer");
    status(`Deshecho${what ? `: ${what}` : ""} · guardando…`);
    toast(`↶ Deshecho${what ? `: ${what}` : ""}`);
  } else toast("Nada que deshacer");
}

function redo() {
  const next = state.history.redo(state.notes);
  if (next) {
    const what = state.history.label;
    commit(next, what ? `Rehacer: ${what}` : "Rehacer");
    status(`Rehecho${what ? `: ${what}` : ""} · guardando…`);
    toast(`↷ Rehecho${what ? `: ${what}` : ""}`);
  } else toast("Nada que rehacer");
}

/** «Volver al original»: the transcription, no edit. One more entry in the
 *  history (and Undo goes back to the edits). */
async function resetToOriginal() {
  if (!(await confirmDialog("¿Volver a la partitura como salió de la transcripción, sin ninguna edición? (Queda en el historial: se puede deshacer.)"))) return;
  const what = "Volver al original";
  state.history.push(state.notes, what);
  saveState("", "Restaurando…");
  await apply(await api(`${API}/notes`, { method: "DELETE" }));
  saveState("ok", "Original restaurado ✓");
  toast("Partitura sin ediciones ✓ (↶ para deshacer)");
  if (!$("sc-history").hidden) renderHistory();
}

/** How an entry of the history changed its notes, in a few words. */
function historyDetail(e) {
  const flats = (state.data?.key?.fifths ?? 0) < 0;
  const names = state.data?.names === "letters" ? "letters" : "solfege";
  const name = (n) => midiName(n.midi, { flats, names });
  const parts = (e.notes || []).map(({ from, to }) => {
    if (from && to) {
      if (from.midi !== to.midi) return `${name(from)} → ${name(to)} en ${formatTime(to.start)}`;
      if (Math.abs(from.start - to.start) > 0.005) return `${name(to)} ${formatTime(from.start)} → ${formatTime(to.start)}`;
      return `${name(to)} en ${formatTime(to.start)}`;
    }
    return from ? `−${name(from)} en ${formatTime(from.start)}` : `+${name(to)} en ${formatTime(to.start)}`;
  });
  const changed = Math.max(e.before, e.after);
  if (changed > parts.length) parts.push(`y ${changed - parts.length} más`);
  return parts.join(" · ");
}

/** «🕘 Historial»: every saved edit, newest first; any one can be gone back
 *  on (it and those after it are undone, as one more edit). */
async function renderHistory() {
  const list = $("sc-history-list");
  let h;
  try {
    h = await api(`${API}/history`);
  } catch (e) {
    list.innerHTML = `<li class="sc-muted"></li>`;
    list.firstChild.textContent = `No se pudo leer el historial: ${e.message}`;
    return;
  }
  list.innerHTML = "";
  if (!h.entries.length) {
    list.innerHTML = `<li class="sc-muted">Aún no hay ediciones guardadas en esta partitura.</li>`;
    return;
  }
  const now = Date.now() / 1000;
  h.entries.forEach((e, i) => {
    const li = document.createElement("li");
    const ago = Math.max(0, now - (e.at || now));
    const when = ago < 60 ? "recién" : ago < 3600 ? `hace ${Math.round(ago / 60)} min` : ago < 86400 ? `hace ${Math.round(ago / 3600)} h` : `hace ${Math.round(ago / 86400)} d`;
    li.innerHTML = `<span class="sc-history-list-what"></span><span></span><span class="sc-muted"></span><button class="sc-btn" type="button"></button>`;
    li.children[0].textContent = e.what || "Edición";
    li.children[1].textContent = historyDetail(e);
    li.children[2].textContent = when;
    const btn = li.querySelector("button");
    btn.textContent = i === 0 ? "↶ Deshacer esta" : "↶ Volver a antes de esta";
    btn.title = i === 0 ? "Deshace esta edición" : `Deshace esta edición y las ${i} posteriores (queda en el historial: se puede volver)`;
    btn.onclick = () => undoTo(e, i);
    list.appendChild(li);
  });
}

async function undoTo(entry, later) {
  if (later && !(await confirmDialog(`¿Volver a antes de «${entry.what || "Edición"}»? Se deshacen esa edición y las ${later} posteriores (queda en el historial: se puede volver).`))) return;
  const what = `Volver a antes de «${entry.what || "Edición"}»`;
  state.history.push(state.notes, what);
  saveState("", "Volviendo…");
  try {
    await apply(await api(`${API}/history/${entry.v}/undo`, { method: "POST" }));
    saveState("ok", "Guardado ✓");
    toast(`↶ ${what}`);
  } catch (e) {
    saveState("err", `No se pudo: ${e.message}`);
  }
  renderHistory();
}

let toastTimer = 0;
/** A short line over the page (the score's status line is hidden in the
 *  piano view, and on a tablet it is far from the finger). */
function toast(text) {
  const el = $("sc-toast");
  el.textContent = text;
  el.hidden = false;
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => (el.hidden = true), 2200);
}

function scrollToNote(id) {
  const el = state.ctx?.notes.get(id)?.[0];
  if (!el) return;
  const b = el.getBoundingClientRect();
  if (b.top < stickyBottom() + 10 || b.bottom > innerHeight - 40) window.scrollBy({ top: b.top - innerHeight / 2, behavior: "smooth" });
}

// pointer: click selects, drag on empty paper selects an area, dblclick plays
function wirePointer() {
  const score = $("sc-score");
  const band = $("sc-band");
  let drag = null;
  score.addEventListener("pointerdown", (e) => {
    if (e.button !== 0) return;
    if (state.adding) {
      e.preventDefault();
      addOnScore(e.clientX, e.clientY);
      return;
    }
    const harm = e.target.closest("g.harm");
    if (harm) {
      const c = state.data.chords.find((x) => x.id === harm.id);
      if (c) openChordDialog(Math.round(c.time * 1000), c.text);
      return;
    }
    const note = e.target.closest("g.note");
    if (note) {
      const id = noteIdOf(note.id);
      const add = e.shiftKey || e.ctrlKey || e.metaKey;
      // Pressing a note already selected keeps the group, to drag it whole.
      if (add || !state.selection.has(id)) select([id], { add });
      score.focus({ preventScroll: true });
      // Captured only once it moves: a capture here would take the
      // double click (play from this note) away from the note.
      drag = scoreNoteDrag(e, note, id);
      return;
    }
    drag = { x: e.clientX, y: e.clientY, add: e.shiftKey || e.ctrlKey || e.metaKey };
    score.setPointerCapture(e.pointerId);
  });
  score.addEventListener("pointermove", (e) => {
    if (!drag) return;
    if (drag.kind === "move") {
      const was = drag.moved;
      dragScoreNotes(drag, e);
      if (drag.moved && !was && !score.hasPointerCapture(e.pointerId)) score.setPointerCapture(e.pointerId);
      return;
    }
    const host = $("sc-scroll").getBoundingClientRect();
    const l = Math.min(drag.x, e.clientX);
    const t = Math.min(drag.y, e.clientY);
    band.hidden = false;
    band.style.left = `${l - host.left}px`;
    band.style.top = `${t - host.top}px`;
    band.style.width = `${Math.abs(e.clientX - drag.x)}px`;
    band.style.height = `${Math.abs(e.clientY - drag.y)}px`;
  });
  score.addEventListener("pointerup", (e) => {
    if (!drag) return;
    if (drag.kind === "move") {
      const d = drag;
      drag = null;
      if (!d.moved) {
        if (!d.add && state.selection.size > 1) select([d.id]); // a plain click on a group picks one
        return;
      }
      if (d.steps || d.k) applyDrag(d.ids, d.steps, { scaleSteps: d.k });
      else dragScoreNotes(d, null); // back where it was
      return;
    }
    band.hidden = true;
    const moved = Math.abs(e.clientX - drag.x) + Math.abs(e.clientY - drag.y);
    if (moved < 5) {
      if (!drag.add) select([]);
    } else {
      const rect = {
        left: Math.min(drag.x, e.clientX),
        right: Math.max(drag.x, e.clientX),
        top: Math.min(drag.y, e.clientY),
        bottom: Math.max(drag.y, e.clientY),
      };
      select(notesInRect(state.ctx, rect), { add: drag.add });
    }
    drag = null;
  });
  score.addEventListener("pointercancel", () => {
    if (drag?.kind === "move") dragScoreNotes(drag, null);
    drag = null;
    band.hidden = true;
  });
  wireFallPointer();
  $("sc-edit-del").onclick = deleteSelected;
  for (const b of document.querySelectorAll("[data-sethand]")) {
    b.onclick = () => setHands(selected(), b.dataset.sethand || null);
  }
  for (const b of document.querySelectorAll("[data-finger]")) {
    b.onclick = () => fingers.set(selected(), Number(b.dataset.finger) || null);
  }
  $("sc-fall-fingers-on").onclick = async () => {
    try {
      // Asked for: show the numbers straight away.
      state.view.fallLabel = state.view.fallLabel === "both" ? "both" : "finger";
      writeView();
      await fingers.enable();
    } catch (e) {
      status(`No se pudieron activar los dedos: ${e.message}`);
    }
  };
  $("sc-fall-fingers-off").onclick = async () => {
    const mine = fingers.counts?.user || 0;
    if (mine && !confirm(`Se quitan los dedos de esta canción, también los ${mine} que pusiste a mano. ¿Seguir?`)) return;
    try {
      await fingers.disable();
    } catch (e) {
      status(`No se pudieron quitar los dedos: ${e.message}`);
    }
  };
  $("sc-fall-fingers").onchange = () => {
    const v = $("sc-fall-fingers").value;
    if (v === "finger" || v === "both") {
      state.view.fallLabel = v;
      if (v === "both" && state.view.fallNames === "none") state.view.fallNames = "letters";
    } else {
      state.view.fallLabel = "name";
      state.view.fallNames = v; // letters, solfege or none
    }
    $("sc-fall-names").value = state.view.fallNames;
    writeView();
    fall.setOptions({ names: fallNames() });
    fall.setFingers(fingers.visible() ? fingers.fingers : null); // redraws
  };
  $("sc-trash-toggle").onclick = () => {
    $("sc-trash").hidden = !$("sc-trash").hidden;
  };
  $("sc-trash-close").onclick = () => {
    $("sc-trash").hidden = true;
  };
  $("sc-trash-all").onclick = () => restoreNotes(state.data?.trash || []);
  $("sc-edit-clear").onclick = () => select([]);
  score.addEventListener("dblclick", (e) => {
    const note = e.target.closest("g.note");
    if (!note) {
      // Not on a note (between notes, a bar of rests): from the start of
      // the bar under the pointer.
      const n = barAt(e.clientX, e.clientY);
      const m = n != null ? (state.data?.measures || []).find((x) => x.number === n) : null;
      if (!m) return;
      player.seek(Math.max(0, m.start - 0.02));
      if (!player.playing) togglePlay();
      return;
    }
    const n = state.notes.find((x) => x.id === noteIdOf(note.id));
    if (n) {
      player.seek(Math.max(0, n.start - 0.05));
      if (!player.playing) togglePlay();
    }
  });
}

/** The number of the bar drawn under a point of the screen (its staves and
 *  the room above and below them), or null. */
function barAt(x, y) {
  for (const g of $("sc-score").querySelectorAll("g.measure")) {
    const r = g.getBoundingClientRect();
    if (x >= r.left && x <= r.right && y >= r.top - 20 && y <= r.bottom + 20) {
      const n = Number(/^m(\d+)$/.exec(g.id)?.[1]);
      return Number.isFinite(n) ? n : null;
    }
  }
  return null;
}

// Dragging notes on the staff: across = grid steps in time (measured on this
// system's own spacing), up/down = one scale step per half staff space.
function scoreNoteDrag(e, el, id) {
  const n = state.notes.find((x) => x.id === id);
  const sys = el.closest("g.system");
  const pts = (state.ctx?.timeline || []).filter((p) => p.sys === sys);
  const head = el.querySelector(".notehead") || el;
  const box = head.getBBox();
  const toUser = 1 / (el.parentNode.getScreenCTM()?.a || 1); // client px -> SVG units
  let perSec = 0;
  if (pts.length > 1) {
    const a = pts[0];
    const b = pts[pts.length - 1];
    perSec = b.t > a.t ? (b.x - a.x) / (b.t - a.t) : 0;
  }
  return {
    kind: "move",
    id,
    add: e.shiftKey || e.ctrlKey || e.metaKey,
    ids: selected(),
    x: e.clientX,
    y: e.clientY,
    toUser,
    stepUser: Math.max(4, perSec * (n?.step_sec || 0.125)), // SVG units per grid step
    halfSpace: Math.max(2, box.height / 2),
    steps: 0,
    k: 0,
    moved: false,
  };
}

function dragScoreNotes(d, e) {
  const els = d.ids.flatMap((id) => state.ctx?.notes.get(id) || []);
  if (!e) {
    for (const el of els) el.removeAttribute("transform");
    status();
    return;
  }
  if (!d.moved && Math.abs(e.clientX - d.x) + Math.abs(e.clientY - d.y) < 5) return;
  d.moved = true;
  const dx = (e.clientX - d.x) * d.toUser;
  const dy = (e.clientY - d.y) * d.toUser;
  d.steps = Math.round(dx / d.stepUser);
  d.k = Math.round(-dy / d.halfSpace);
  for (const el of els) el.setAttribute("transform", `translate(${d.steps * d.stepUser},${-d.k * d.halfSpace})`);
  status(`Mover: ${d.steps >= 0 ? "+" : ""}${d.steps} paso(s) · ${d.k >= 0 ? "+" : ""}${d.k} nota(s) de la escala — suelta para aplicar`);
}

// «＋ Nota» ------------------------------------------------------------------

function setAdding(on) {
  if (on && state.painting) setPainting(false);
  state.adding = on;
  document.body.classList.toggle("sc-adding", on);
  for (const id of ["sc-add", "sc-fall-add"]) $(id).setAttribute("aria-pressed", String(on));
  if (!on) $("sc-fall").style.cursor = "";
  status(
    on
      ? "Añadir notas: toca donde va cada una (en la partitura, su línea o espacio en su lugar del compás; en el piano, su tecla a la altura de su momento). N o Esc para terminar."
      : undefined,
  );
}

const beatSec = () => 60 / (state.data?.bpm || 120);

function placeNote(spec) {
  const next = addNote(state.notes, { ...spec, end: Math.max(spec.end, spec.start + 0.05) });
  const n = next[next.length - 1];
  edit(next, `Nota añadida: ${midiName(n.midi, { names: state.data.names })}`);
  select([n.id]);
}

/** A tap on the score in «＋ Nota»: the staff under it (treble or bass), the
 *  line or space (a key of the key signature), and the time along its system
 *  (between the notes and barlines drawn there, then on the grid). */
function addOnScore(clientX, clientY) {
  const ctx = state.ctx;
  if (!ctx) return;
  const dist = (el) => {
    const r = el.getBoundingClientRect();
    return clientY < r.top ? r.top - clientY : clientY > r.bottom ? clientY - r.bottom : 0;
  };
  const systems = [...ctx.container.querySelectorAll("g.system")];
  const sys = systems.sort((a, b) => dist(a) - dist(b))[0];
  if (!sys || dist(sys) > 80) return;
  const measures = [...sys.querySelectorAll("g.measure")];
  const measure =
    measures.find((m) => {
      const r = m.getBoundingClientRect();
      return clientX >= r.left && clientX <= r.right;
    }) || measures[0];
  if (!measure) return;
  // The five lines of each staff, in the measure's own units.
  const staves = [...measure.querySelectorAll(":scope > g.staff")]
    .slice(0, 2)
    .map((el, i) => {
      const ys = [...el.querySelectorAll(":scope > path")]
        .map((p) => /M\s*[-\d.]+[ ,]+([-\d.]+)/.exec(p.getAttribute("d") || ""))
        .filter(Boolean)
        .map((m) => Number(m[1]))
        .sort((a, b) => a - b)
        .slice(0, 5);
      return { staff: i + 1, ys, el };
    })
    .filter((s) => s.ys.length === 5);
  if (!staves.length) return;
  const inv = staves[0].el.getScreenCTM()?.inverse();
  if (!inv) return;
  const pt = new DOMPoint(clientX, clientY).matrixTransform(inv);
  const mid = (s) => (s.ys[0] + s.ys[4]) / 2;
  const st = staves.sort((a, b) => Math.abs(mid(a) - pt.y) - Math.abs(mid(b) - pt.y))[0];
  const half = (st.ys[4] - st.ys[0]) / 8;
  const midi = pitchOnStaff(st.staff, Math.round((st.ys[4] - pt.y) / half), state.data.key.id);
  // The time: between the points of this system's timeline around x.
  const pts = (ctx.timeline || []).filter((p) => p.sys === sys).sort((a, b) => a.x - b.x);
  if (!pts.length) return;
  const i = Math.max(0, pts.findLastIndex((p) => p.x <= pt.x));
  const a = pts[i];
  const b = pts[Math.min(i + 1, pts.length - 1)];
  const t = b.x > a.x ? a.t + ((pt.x - a.x) / (b.x - a.x)) * (b.t - a.t) : a.t;
  let near = null;
  for (const n of state.notes) if (!near || Math.abs(n.start - t) < Math.abs(near.start - t)) near = n;
  const step = near?.step_sec || 0.125;
  let start = snapToOnset(state.notes, t, step / 2);
  if (start === t) start = a.t + Math.max(0, Math.round((t - a.t) / step)) * step;
  placeNote({ midi, start, end: start + beatSec(), hand: st.staff === 2 ? "L" : "R" });
}

// The piano view: tap a falling note to select it (playing or paused), drag
// it: across = semitones (key by key), up/down = grid steps in time (down is
// earlier, towards the keys). Tapping empty space clears the selection.
const AHEAD_FACTOR = 1.25; // one + / − press
const PINCH_START_PX = 14; // fingers this much closer or apart: a pinch, not a tap
const MULTI_TAP_MS = 400; // two (three) fingers down and up within this: undo (redo)
const DOUBLE_TAP_MS = 400;
const DOUBLE_TAP_PX = 40;

function wireFallPointer() {
  const host = $("sc-fall");
  let d = null;
  let edge = null; // a start edge being dragged: { id, y, step, steps, target }
  // The bar's bottom (its start) under the pointer: a resize cursor; drag it
  // down onto the note before on the same key and the two become one.
  let adding = null; // a note being placed: { midi, start, end, y }
  let scrub = null; // the song being moved by a drag up or down: { y, t0, wasPlaying, moved, trail }
  // Let go while moving, the song keeps going and slows down (a feed's
  // flick): { v (song s per s), at (ms), wasPlaying, raf }. A press stops it.
  let glide = null;
  const stopGlide = () => {
    const g = glide;
    glide = null;
    if (g) cancelAnimationFrame(g.raf);
    return g;
  };
  const glideFrame = (now) => {
    const g = glide;
    if (!g) return;
    // ▶ pressed meanwhile: it plays from here, the glide is over.
    if (player.playing) return void stopGlide();
    const dt = Math.min(0.05, (now - g.at) / 1000);
    g.at = now;
    const step = glideStep(player.time, g.v, dt, player.duration || Infinity);
    g.v = step.v;
    player.seek(step.t);
    status(`⇅ ${formatTime(step.t)}`);
    if (step.done) {
      stopGlide();
      status();
      if (g.wasPlaying) player.play();
      return;
    }
    g.raf = requestAnimationFrame(glideFrame);
  };
  // Two fingers: a pinch changes «Notas a la vista» (apart: fewer seconds,
  // the notes spread out; together: more, closer). Whatever the first finger
  // had started is dropped. Ctrl + wheel, and a trackpad pinch (the browser
  // sends it as one), do the same.
  const touches = new Map(); // pointerId -> {x, y}: touch pointers down
  let pinch = null; // { d0, ahead0 }
  const spread = () => {
    const [a, b] = [...touches.values()];
    return Math.hypot(a.x - b.x, a.y - b.y);
  };
  host.addEventListener(
    "wheel",
    (e) => {
      if (!e.ctrlKey && !e.metaKey) return;
      e.preventDefault(); // not the page's zoom
      setAhead(clampAhead(state.view.fallAhead) * Math.exp(e.deltaY * 0.004), { hint: true });
    },
    { passive: false },
  );
  let paint = null; // «Corregir manos»: a stroke painting notes: { ids: Set, x, y }
  const paintPreview = () => fall.setPaint({ hand: state.paintHand || null, ids: paint.ids }, true);
  const edgeCursor = (e) => {
    if (state.painting) {
      host.style.cursor = "crosshair";
      return;
    }
    if (d || edge || adding || scrub) return;
    if (state.adding) host.style.cursor = fall.pointAt(e.clientX, e.clientY) ? "crosshair" : "";
    else host.style.cursor = fall.edgeTest(e.clientX, e.clientY) ? "ns-resize" : "";
  };
  // «＋ Nota»: pressed on a key's lane at the time it should sound; dragged
  // up, it lasts until there (else one beat).
  const addPreview = () => {
    const a = adding;
    const n = { id: "nu-preview", midi: a.midi, start: a.start, end: a.end, draw_end: a.end, held: true, hand: null, velocity: 80 };
    fall.setPreview({ add: n });
    fall.setSelection(new Set(["nu-preview"]));
  };
  host.addEventListener("pointermove", edgeCursor);
  host.addEventListener("pointerdown", (e) => {
    if (e.pointerType === "touch") touches.set(e.pointerId, { x: e.clientX, y: e.clientY });
    if (touches.size === 2) {
      // The second finger: a pinch, nothing else (no scrub, drag or edit).
      if (scrub?.moved && scrub.wasPlaying) player.play();
      scrub = d = edge = adding = null;
      if (paint) {
        paint = null;
        fall.setPaint(null, state.painting);
      }
      fall.setPreview(null);
      host.style.cursor = "";
      pinch = { d0: Math.max(20, spread()), ahead0: clampAhead(state.view.fallAhead), at: performance.now(), moved: false, max: 2 };
      e.preventDefault();
      return;
    }
    if (pinch) {
      pinch.max = Math.max(pinch.max, touches.size); // three fingers: redo
      return;
    }
    if (e.button !== 0) return;
    const caught = stopGlide();
    if (caught && !state.painting && !state.adding) {
      // A press on a gliding song catches it: held, or dragged on from here.
      scrub = { id: null, add: false, x: e.clientX, y: e.clientY, t0: player.time, wasPlaying: caught.wasPlaying, moved: false, caught: true, trail: [] };
      host.setPointerCapture(e.pointerId);
      e.preventDefault();
      return;
    }
    // «Corregir manos»: what the stroke touches takes the brush's hand (even
    // while it plays: no scrubbing in this mode).
    if (state.painting) {
      paint = { ids: fall.hitsAlong(e.clientX, e.clientY, e.clientX, e.clientY), x: e.clientX, y: e.clientY };
      paintPreview();
      host.setPointerCapture(e.pointerId);
      e.preventDefault();
      return;
    }
    if (state.adding) {
      const p = fall.pointAt(e.clientX, e.clientY);
      if (!p) return;
      const start = snapToOnset(state.notes, p.sec);
      adding = { midi: p.midi, start, end: start + beatSec(), y: e.clientY };
      addPreview();
      host.setPointerCapture(e.pointerId);
      e.preventDefault();
      return;
    }
    // Playing, a press anywhere moves the song (a note there is not edited:
    // a finger sliding over the falling notes moved them). Paused, a press on
    // empty space does; on a note it selects and drags the note as before.
    const playing = player.playing;
    const at = playing ? null : fall.edgeTest(e.clientX, e.clientY);
    if (at) {
      const n = state.notes.find((x) => x.id === at);
      edge = { id: at, x: e.clientX, y: e.clientY, step: n?.step_sec || 0.125, steps: 0, target: null };
      select([at]);
      host.setPointerCapture(e.pointerId);
      e.preventDefault();
      return;
    }
    const id = fall.hitTest(e.clientX, e.clientY);
    const add = e.shiftKey || e.ctrlKey || e.metaKey;
    if (!id || playing) {
      scrub = { id, add, x: e.clientX, y: e.clientY, t0: player.time, wasPlaying: playing, moved: false, trail: [] };
      host.setPointerCapture(e.pointerId);
      e.preventDefault();
      return;
    }
    if (add || !state.selection.has(id)) select([id], { add });
    const n = state.notes.find((x) => x.id === id);
    d = { id, add, ids: selected(), x: e.clientX, y: e.clientY, step: n?.step_sec || 0.125, moved: false, semis: 0, steps: 0 };
    host.setPointerCapture(e.pointerId);
  });
  host.addEventListener("pointermove", (e) => {
    if (touches.has(e.pointerId)) touches.set(e.pointerId, { x: e.clientX, y: e.clientY });
    if (pinch) {
      if (touches.size !== 2) return;
      const d = Math.max(20, spread());
      // A tap with two fingers moves them a little: not a pinch yet.
      if (!pinch.moved && Math.abs(d - pinch.d0) < PINCH_START_PX) return;
      pinch.moved = true;
      setAhead(pinch.ahead0 * (pinch.d0 / d), { hint: true });
      return;
    }
    if (paint) {
      for (const id of fall.hitsAlong(paint.x, paint.y, e.clientX, e.clientY)) paint.ids.add(id);
      paint.x = e.clientX;
      paint.y = e.clientY;
      paintPreview();
      return;
    }
    if (scrub) {
      if (!scrub.moved && Math.abs(e.clientY - scrub.y) < 6) return;
      if (!scrub.moved) {
        scrub.moved = true;
        // Paused while the finger moves it, so it does not run off under it.
        if (scrub.wasPlaying) player.pause();
        host.style.cursor = "grabbing";
      }
      // The lane moves with the finger: the moment under it stays under it
      // (pull the notes down to go forward, push them up to go back).
      const dd = fall.dragDelta(scrub.x, scrub.y, scrub.x, e.clientY);
      const end = player.duration || Infinity;
      const t = Math.max(0, Math.min(end - 0.05, scrub.t0 - dd.sec));
      player.seek(t);
      trackFlick(scrub.trail, performance.now(), t);
      status(`⇅ ${formatTime(t)}${scrub.wasPlaying ? " — suelta para seguir" : ""}`);
      return;
    }
    if (adding) {
      if (adding.y - e.clientY < 6) return;
      const p = fall.pointAt(e.clientX, e.clientY);
      if (p) adding.end = Math.max(adding.start + 0.1, p.sec);
      addPreview();
      return;
    }
    if (edge) {
      const n = state.notes.find((x) => x.id === edge.id);
      if (!n) return;
      const dd = fall.dragDelta(edge.x, edge.y, e.clientX, e.clientY);
      edge.steps = Math.round(dd.sec / edge.step);
      const at = Math.max(0, (n.q_start ?? n.start) + edge.steps * edge.step);
      const prev = previousOnKey(state.notes, edge.id);
      // Dragged down (a click or a nudge up never joins) onto, or past, the
      // end of the note before: they will be one.
      const down = e.clientY - edge.y >= 6 && dd.sec < 0;
      edge.target = down && prev && at <= (prev.draw_end ?? prev.end) + edge.step / 2 ? prev.id : null;
      fall.setPreview({ start: { id: edge.id, at: edge.target ? (prev.draw_end ?? prev.end) : at } });
      fall.setSelection(new Set(edge.target ? [edge.id, edge.target] : [edge.id]));
      status(
        edge.target
          ? "Suelta para unir las dos notas en una sola"
          : `Inicio: ${edge.steps >= 0 ? "+" : ""}${edge.steps} paso(s) — baja hasta la nota anterior para unirlas`,
      );
      return;
    }
    if (!d) return;
    if (!d.moved && Math.abs(e.clientX - d.x) + Math.abs(e.clientY - d.y) < 6) return;
    d.moved = true;
    const dd = fall.dragDelta(d.x, d.y, e.clientX, e.clientY); // through the 3D perspective
    d.semis = Math.round(dd.semis);
    d.steps = Math.round(dd.sec / d.step);
    fall.setPreview({ ids: new Set(d.ids), semis: d.semis, sec: d.steps * d.step });
    status(`Mover: ${d.semis >= 0 ? "+" : ""}${d.semis} semitono(s) · ${d.steps >= 0 ? "+" : ""}${d.steps} paso(s) — suelta para aplicar`);
  });
  const end = (apply) => {
    if (!d) return;
    const x = d;
    d = null;
    fall.setPreview(null);
    if (!x.moved) {
      if (!x.add && state.selection.size > 1) select([x.id]);
      return;
    }
    if (apply && (x.steps || x.semis)) applyDrag(x.ids, x.steps, { semis: x.semis });
    else status();
  };
  const endEdge = (apply) => {
    const x = edge;
    edge = null;
    fall.setPreview(null);
    host.style.cursor = "";
    if (!apply) {
      select([x.id]);
      return status();
    }
    if (x.target) {
      edit(joinNotes(state.notes, x.target, x.id), "Notas unidas");
      select([x.target]);
    } else if (x.steps) {
      edit(moveStart(state.notes, x.id, x.steps), "Inicio movido");
      select([x.id]);
    } else {
      select([x.id]);
      status();
    }
  };
  const endAdd = (apply) => {
    const a = adding;
    adding = null;
    fall.setPreview(null);
    if (apply) placeNote({ midi: a.midi, start: a.start, end: a.end, hand: null });
    else fall.setSelection(new Set(state.selection));
  };
  // Two taps (or clicks) on empty space, close in time and place: play or
  // pause. Pointer events, so a finger and a mouse do the same.
  let lastEmptyTap = null; // { at (ms), x, y }
  const emptyTap = (s) => {
    const now = performance.now();
    const prev = lastEmptyTap;
    if (prev && now - prev.at < DOUBLE_TAP_MS && Math.hypot(s.x - prev.x, s.y - prev.y) < DOUBLE_TAP_PX) {
      lastEmptyTap = null;
      togglePlay();
      return true;
    }
    lastEmptyTap = { at: now, x: s.x, y: s.y };
    return false;
  };
  const endScrub = () => {
    const s = scrub;
    scrub = null;
    host.style.cursor = "";
    if (!s.moved) {
      if (!s.id && !s.add && !s.caught && emptyTap(s)) return;
      if (s.caught) {
        // A tap that stopped a glide: only that.
        status();
        if (s.wasPlaying) player.play();
        return;
      }
      // A tap: as before, it selects the note under it (or clears). Playing,
      // a note tapped is one to change: the song stops there, so the note
      // stays under the finger and the edit bar's buttons can reach it.
      if (s.id && s.wasPlaying) {
        player.pause();
        status("En pausa para editar la nota (▶ o Espacio para seguir)");
      }
      if (s.id) select([s.id], { add: s.add });
      else if (!s.add) select([]);
      return;
    }
    const v = flickSpeed(s.trail, performance.now());
    if (Math.abs(v) >= GLIDE_START) {
      glide = { v, at: performance.now(), wasPlaying: s.wasPlaying, raf: 0 };
      glide.raf = requestAnimationFrame(glideFrame);
      return;
    }
    status();
    if (s.wasPlaying) player.play();
  };
  const endPaint = (apply) => {
    const p = paint;
    paint = null;
    fall.setPaint(null, state.painting);
    if (apply && p.ids.size) setHands([...p.ids], state.paintHand || null);
  };
  // A pinch ends when both fingers are up; the one lifted first does nothing.
  const fingerUp = (e) => {
    touches.delete(e.pointerId);
    if (!pinch) return false;
    if (!touches.size) {
      // Two fingers tapped (down and up, not pinched): undo; three: redo.
      const p = pinch;
      pinch = null;
      if (!p.moved && performance.now() - p.at < MULTI_TAP_MS) (p.max >= 3 ? redo : undo)();
    }
    return true;
  };
  host.addEventListener("pointerup", (e) => fingerUp(e) || (paint ? endPaint(true) : scrub ? endScrub() : adding ? endAdd(true) : edge ? endEdge(true) : end(true)));
  host.addEventListener("pointercancel", (e) => fingerUp(e) || (paint ? endPaint(false) : scrub ? endScrub() : adding ? endAdd(false) : edge ? endEdge(false) : end(false)));
}

// ── hands: corrections, «🖌 Corregir manos», colours ────────────────────

/** A hand correction is being saved: remember each note's staff, to say
 *  afterwards how many notes around it the program moved with it. */
function noteHandEdit(ids) {
  state.handEdit = { ids: new Set(ids), staff: new Map(state.notes.map((n) => [n.id, n.staff])) };
}

/** Set the hand of `ids` ("R" / "L"; null = the program decides again). */
function setHands(ids, hand) {
  const set = new Set(ids);
  const changing = state.notes.filter((n) => set.has(n.id) && (n.hand ?? null) !== hand).length;
  if (!changing) return;
  noteHandEdit(ids);
  const one = changing === 1;
  const what = hand
    ? `Mano ${hand === "R" ? "derecha" : "izquierda"}: ${changing} nota${one ? "" : "s"}`
    : `${changing} nota${one ? "" : "s"} vuelve${one ? "" : "n"} a la mano que elija el programa`;
  edit(setNoteHands(state.notes, ids, hand), what);
  handsMsg(`${what} · guardando…`);
}

/** After the save: the notes around a correction that the program changed
 *  too (the model reads the hands set by the user as hints). */
function reportHandEdit(data) {
  const h = state.handEdit;
  if (!h) return;
  state.handEdit = null;
  let moved = 0;
  for (const n of data.notes) if (!h.ids.has(n.id) && h.staff.has(n.id) && h.staff.get(n.id) !== n.staff) moved++;
  const around = moved ? ` · el programa ajustó además ${moved} nota${moved === 1 ? "" : "s"} de alrededor` : "";
  handsMsg(`Mano corregida ✓${around}`);
  saveState("ok", `Guardado ✓ (versión ${data.version})${around}`);
  if (around) status(`Mano corregida ✓${around}`);
}

let handsMsgTimer = 0;
/** A line next to «🖌 Corregir manos» (the score's status line is hidden in
 *  the piano view); it goes away after a while unless the brush is on. */
function handsMsg(text) {
  $("sc-hands-msg").textContent = text || "";
  $("sc-hands-msg").title = text || ""; // cut to one line: the whole of it
  clearTimeout(handsMsgTimer);
  if (text && !state.painting) handsMsgTimer = setTimeout(() => handsMsg(""), 8000);
}

function setPainting(on) {
  if (on && state.adding) setAdding(false);
  state.painting = on;
  document.body.classList.toggle("sc-painting", on);
  $("sc-paint").setAttribute("aria-pressed", String(on));
  $("sc-paint-pick").hidden = !on;
  $("sc-fall").style.cursor = on ? "crosshair" : "";
  // Painting hands needs to see them.
  if (on && state.view.fallColors !== "hands") {
    state.view.fallColors = "hands";
    setFallView(true);
  }
  fall.setPaint(null, on);
  handsMsg(on ? "Toca o arrastra sobre las notas para cambiarles la mano · ● = mano que pusiste tú · Esc para terminar" : "");
}

function setPaintHand(hand) {
  state.paintHand = hand;
  for (const b of document.querySelectorAll("[data-paint]")) b.setAttribute("aria-pressed", String(b.dataset.paint === hand));
}

/** The hands' colours: the falling notes, the swatches, the pickers. */
function applyHandColors() {
  const c = state.view.handColors || null;
  fall.setHandColors(c);
  const root = document.documentElement.style;
  root.setProperty("--hand-r", c?.R || HAND_COLORS.R);
  root.setProperty("--hand-l", c?.L || HAND_COLORS.L);
  $("sc-color-r").value = c?.R || HAND_COLORS.R;
  $("sc-color-l").value = c?.L || HAND_COLORS.L;
  $("sc-color-reset").hidden = !c;
}

/** «✓ Canción revisada»: pressed when the whole song's hands are kept as
 *  confirmed (training data for the hand model, hand_labels.py). */
function showReviewed() {
  const on = !!state.data?.hand_labels?.reviewed;
  const b = $("sc-reviewed");
  b.setAttribute("aria-pressed", String(on));
  b.textContent = on ? "✓ Canción revisada" : "Marcar canción revisada";
}

async function toggleReviewed() {
  const on = !!state.data?.hand_labels?.reviewed;
  if (!on && !(await confirmDialog("¿Las manos de toda esta canción están bien? Se guardan como correctas para entrenar el modelo más adelante. Márcala solo después de revisarla entera (puedes quitar la marca cuando quieras)."))) return;
  try {
    const data = await api(`${API}/hands/reviewed`, { method: on ? "DELETE" : "POST" });
    await apply(data);
    handsMsg(on ? "Ya no está marcada como revisada" : "Canción marcada como revisada ✓ · sus manos quedan guardadas para entrenar");
  } catch (e) {
    handsMsg(`No se pudo guardar: ${e.message}`);
  }
}

function wireHands() {
  $("sc-reviewed").onclick = toggleReviewed;
  $("sc-paint").onclick = () => setPainting(!state.painting);
  for (const b of document.querySelectorAll("[data-paint]")) b.onclick = () => setPaintHand(b.dataset.paint);
  const pick = () => {
    state.view.handColors = { R: $("sc-color-r").value, L: $("sc-color-l").value };
    writeView();
    applyHandColors();
  };
  $("sc-color-r").oninput = pick;
  $("sc-color-l").oninput = pick;
  $("sc-color-reset").onclick = () => {
    state.view.handColors = null;
    writeView();
    applyHandColors();
  };
  applyHandColors();
}

// dialogs: resolved from the form's submit (which carries the button that
// was pressed) and from Escape, not from the dialog's "close" event, which
// some embedded browsers never fire.
function ask(dialog) {
  return new Promise((resolve) => {
    const form = dialog.querySelector("form");
    const done = (value) => {
      form.removeEventListener("submit", onSubmit);
      dialog.removeEventListener("cancel", onCancel);
      if (dialog.open) dialog.close();
      resolve(value);
    };
    const onSubmit = (e) => {
      e.preventDefault();
      done(e.submitter?.value || "cancel");
    };
    const onCancel = (e) => {
      e.preventDefault();
      done("cancel");
    };
    form.addEventListener("submit", onSubmit);
    dialog.addEventListener("cancel", onCancel);
    dialog.showModal();
  });
}

// chords
async function openChordDialog(timeMs, text) {
  $("sc-chord-input").value = text;
  const pending = ask($("sc-chord-dialog"));
  $("sc-chord-input").select();
  const action = await pending;
  if (action === "cancel") return;
  const body = { time_ms: timeMs, text: action === "save" ? $("sc-chord-input").value.trim() : action === "remove" ? "" : null };
  saveState("", "Guardando acorde…");
  try {
    await apply(await api(`${API}/chords`, { method: "PUT", body }));
    saveState("ok", "Acorde guardado ✓");
  } catch (e) {
    saveState("err", e.message);
  }
}

async function confirmDialog(text) {
  $("sc-confirm-text").textContent = text;
  return (await ask($("sc-confirm"))) === "ok";
}

// clean-up panel
function updateDoomed() {
  if (!state.ctx) return;
  const panelOpen = !$("sc-clean").hidden;
  const ids = panelOpen
    ? cleanupTargets(state.notes, {
        minVelocity: Number($("sc-clean-vel").value),
        minDurationMs: Number($("sc-clean-dur").value),
      })
    : [];
  state.doomed = markNotes(state.ctx, "sd-doomed", ids, state.doomed);
  $("sc-clean-count").textContent = ids.length;
  $("sc-clean-vel-v").textContent = $("sc-clean-vel").value;
  $("sc-clean-dur-v").textContent = $("sc-clean-dur").value;
}

// ── practice: loop, hands, metronome, count-in, MIDI keyboard ──────────

/** ▶ / ❚❚, with the count-in («Cuenta») before playing. */
function togglePlay() {
  if (player.playing) {
    mk.pausedByWait = false;
    return player.pause();
  }
  const t = player.time;
  const measures = state.data?.measures || [];
  const i = Math.max(0, measureAt(measures, t));
  const meter = measures[i]?.meter || 4;
  const clicks = state.view.countIn === "bar" ? meter : state.view.countIn === "2bar" ? 2 * meter : 0;
  return player.play({ countIn: clicks, beatSec: beatSecondsAt(measures, t) });
}

/** The loop over bars: shown on the bar, on the falling notes, remembered. */
function setLoop(loop) {
  state.loop = loop && loop.b > loop.a ? loop : null;
  const L = state.loop;
  $("sc-loop-toggle").setAttribute("aria-pressed", String(!!L?.on));
  $("sc-loop-label").textContent = L ? (L.from === L.to ? `compás ${L.from}` : `compases ${L.from}–${L.to}`) : "sin bucle";
  fall.setLoop(L);
  saveSong({ loop: L });
}

function loopFrom(i, j, on = true) {
  const L = loopOver(state.data?.measures || [], i, j);
  if (L) setLoop({ ...L, on });
}

const barIndexAt = (t) => Math.max(0, measureAt(state.data?.measures || [], t + 0.01));

function toggleLoop() {
  if (state.loop) return setLoop({ ...state.loop, on: !state.loop.on });
  const measures = state.data?.measures || [];
  const sel = state.notes.filter((n) => state.selection.has(n.id));
  const L = sel.length ? loopOverNotes(measures, sel) : null;
  if (L) setLoop({ ...L, on: true });
  else loopFrom(barIndexAt(player.time), barIndexAt(player.time));
}

/** One more time round the loop: back to A (after the count-in, if any),
 *  and the ramp's next speed. */
function loopAgain(a) {
  practice.loops += 1;
  practice.bestSpeed = Math.max(practice.bestSpeed, Math.round(player.rate * 100));
  const every = Number($("sc-loop-ramp").value) || 0;
  const next = rampSpeed(Math.round(player.rate * 100), every, practice.loops);
  player.seek(a);
  mk.doneAt = -Infinity;
  if (next !== Math.round(player.rate * 100)) {
    setSpeed(next);
    status(`Bucle: vuelta ${practice.loops} · velocidad ${next} %`);
  }
  if (state.view.countIn !== "0") {
    player.pause();
    togglePlay();
  }
}

/** «🔇 Silenciar»: the hand the player plays. It is silent in the MIDI and
 *  Pianoteq (the other one sounds alone) and drawn faint, outlined dashed,
 *  on the piano. "" = both sound. */
function setHand(hand) {
  state.hand = hand === "R" || hand === "L" ? hand : "";
  const staff = state.hand === "R" ? 1 : state.hand === "L" ? 2 : 0;
  for (const b of document.querySelectorAll("[data-mute]")) {
    const on = b.dataset.mute === state.hand;
    const name = b.dataset.mute === "R" ? "derecha" : "izquierda";
    b.setAttribute("aria-pressed", String(on));
    b.querySelector(".sc-mute-icon").textContent = on ? "🔇" : "🔈";
    b.title = on ? `Mano ${name} silenciada: la tocas tú. Pulsa para que vuelva a sonar` : `Silenciar la mano ${name} para tocarla tú`;
  }
  player.setSilentStaff(staff);
  fall.setOptions({ dimStaff: staff });
  fall.redraw();
  handHint();
  saveSong({ hand: state.hand });
}

/** A press on «🔇 Derecha» / «🔇 Izquierda»: silence that hand, or (pressed
 *  again) let both sound. The recording (stem, song) has both hands in it,
 *  so a hand is silenced on the MIDI or Pianoteq: switch to it. */
function toggleMute(hand) {
  const next = state.hand === hand ? "" : hand;
  setHand(next);
  const src = $("sc-source");
  if (next && src.value !== "midi" && src.value !== "pianoteq") {
    const opt = src.querySelector('[value="pianoteq"]');
    src.value = opt && !opt.hidden ? "pianoteq" : "midi";
    src.onchange?.();
  } else if (pt.want) {
    pianoteqRender();
  }
  const name = hand === "R" ? "derecha" : "izquierda";
  status(next ? `🔇 Mano ${name} silenciada: tócala tú (sus notas se ven tenues y punteadas)` : "Suenan ambas manos");
}

function handHint() {
  const src = $("sc-source").value;
  $("sc-hand-hint").hidden = !state.hand || src === "midi" || src === "pianoteq";
}

// Practice kept with the score (PUT .../practice): time played, loops, best
// speed of a loop played through, accuracy on a MIDI keyboard.
const practice = { secs: 0, loops: 0, bestSpeed: 0, lastWall: 0, sentAt: 0 };

function reportPractice(final = false) {
  if (!state.data || (!practice.secs && !practice.loops && !mk.asked)) return;
  const body = { seconds: Math.min(3600, Math.round(practice.secs)), loops: practice.loops };
  if (practice.bestSpeed) body.speed = Math.max(25, Math.min(125, practice.bestSpeed));
  if (mk.asked >= 10) body.accuracy = Math.max(0, Math.min(1, mk.hits / mk.asked));
  practice.secs = 0;
  practice.loops = 0;
  practice.bestSpeed = 0;
  practice.sentAt = performance.now();
  fetch(`${API}/practice`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
    keepalive: final,
  }).catch(() => {});
}

// The MIDI keyboard («🎹 Teclado MIDI»). Free play: the keys pressed show on
// the piano, green on a note of the song (struck on time), red otherwise.
// «Esperarme»: the song stops at each chord of the hands practised until
// every one of its keys is pressed.
const mk = {
  on: false,
  pressed: new Map(), // midi -> "ok" | "wrong" | ""
  struck: new Set(), // keys struck for the chord waited for
  chord: null, // {start, keys, ids}: the next chord to play («Esperarme»)
  doneAt: -Infinity, // start of the last chord played
  waiting: false,
  pausedByWait: false,
  wrongSince: false, // a wrong key since this chord became the one
  used: new Set(), // note ids already hit (free play)
  asked: 0,
  hits: 0,
  lastT: 0,
};

const midi = new MidiInput({
  onNote: (m, vel) => (vel ? keyDown(m, vel) : keyUp(m)),
  onChange: (devices) => midiStatus(devices),
});

function midiStatus(devices = midi.devices) {
  const el = $("sc-midi-status");
  el.className = "sc-muted";
  if (!mk.on) {
    el.textContent = "";
    return;
  }
  const acc = mk.asked ? ` · aciertos ${Math.round((100 * mk.hits) / mk.asked)} % (${mk.hits}/${mk.asked})` : "";
  if (mk.waiting) {
    el.className = "sc-muted wait";
    el.textContent = `esperando: ${[...(mk.chord?.keys || [])].map((k) => midiName(k, { names: state.view.fallNames === "solfege" ? "solfege" : "letters", flats: (state.data?.key?.fifths ?? 0) < 0 })).join(" ")}${acc}`;
    return;
  }
  el.className = devices.length ? "sc-muted ok" : "sc-muted";
  el.textContent = devices.length ? `${devices.join(", ")}${acc}` : "conecta el teclado por USB (se detecta solo)";
}

function showPressed() {
  fall.setPressed(new Map(mk.pressed), mk.waiting && mk.chord ? mk.chord.keys : null);
}

function keyDown(m, vel) {
  if ($("sc-midi-sound").checked) player.liveOn(m, vel);
  let kind = "";
  if ($("sc-midi-mode").value === "wait") {
    if (mk.chord?.keys.has(m)) {
      mk.struck.add(m);
      kind = "ok";
    } else {
      kind = "wrong";
      mk.wrongSince = true;
    }
  } else if (player.playing) {
    const id = hitNote(state.index.sorted, m, followT, state.hand || null, 0.18, mk.used);
    if (id) {
      mk.used.add(id);
      mk.hits += 1;
      kind = "ok";
    } else kind = "wrong";
  }
  mk.pressed.set(m, kind);
  showPressed();
  midiStatus();
}

function keyUp(m) {
  player.liveOff(m);
  mk.pressed.delete(m);
  showPressed();
}

/** Every frame with a MIDI keyboard: stop at the next chord until it is
 *  played («Esperarme»), count the notes the player let pass (free play). */
function midiFrame(t) {
  if (!mk.on) return;
  const sorted = state.index.sorted;
  const hand = state.hand || null;
  // A jump (a seek, the loop going back): what was played before it is not
  // the chord to wait for now.
  if (t < mk.lastT - 0.25 || t > mk.lastT + 2) {
    mk.doneAt = -Infinity;
    mk.used.clear();
    mk.struck.clear();
  }
  if ($("sc-midi-mode").value === "wait") {
    if (!mk.chord || mk.chord.start <= mk.doneAt || mk.chord.start < t - 0.5) {
      mk.chord = nextChord(sorted, t - 0.02, hand, mk.doneAt);
      mk.struck.clear();
      mk.wrongSince = false;
    }
    const c = mk.chord;
    if (c && chordDone(c, mk.struck, midi.down)) {
      mk.asked += 1;
      if (!mk.wrongSince) mk.hits += 1;
      mk.doneAt = c.start;
      mk.chord = null;
      if (mk.waiting) {
        mk.waiting = false;
        if (mk.pausedByWait) {
          mk.pausedByWait = false;
          player.play();
        }
      }
      showPressed();
      midiStatus();
    } else if (c && player.playing && !mk.waiting && t >= c.start - 0.01) {
      mk.waiting = true;
      mk.pausedByWait = true;
      player.pause();
      player.seek(c.start);
      showPressed();
      midiStatus();
    }
  } else if (player.playing) {
    // Free play: a note of the hands practised that went by unplayed.
    for (const n of sorted) {
      if (n.start > t - 0.2) break;
      if (n.start <= mk.lastT - 0.2 || !playsHand(n, hand)) continue;
      mk.asked += 1;
    }
  }
  mk.lastT = t;
}

async function toggleMidi() {
  if (mk.on) {
    midi.disconnect();
    mk.on = false;
    mk.waiting = false;
    mk.pressed.clear();
    showPressed();
  } else {
    try {
      await midi.connect();
      mk.on = true;
      mk.asked = 0;
      mk.hits = 0;
      mk.lastT = player.time;
    } catch (e) {
      $("sc-midi-status").textContent = e.message;
      return;
    }
  }
  $("sc-midi-connect").setAttribute("aria-pressed", String(mk.on));
  $("sc-midi-mode").hidden = !mk.on;
  $("sc-midi-sound-wrap").hidden = !mk.on;
  midiStatus();
}

// Inspection hooks for tests: a MIDI keyboard is played through keyDown/keyUp.
window.__practice = { mk, keyDown, keyUp, setLoop, practice, get loop() { return state.loop; } };

function wirePractice() {
  $("sc-loop-a").onclick = () => {
    const i = barIndexAt(player.time);
    const end = state.loop ? barIndexAt(state.loop.b - 0.02) : i;
    loopFrom(i, Math.max(i, end));
  };
  $("sc-loop-b").onclick = () => {
    const j = barIndexAt(player.time);
    const start = state.loop ? barIndexAt(state.loop.a) : j;
    loopFrom(Math.min(start, j), j);
  };
  $("sc-loop-toggle").onclick = toggleLoop;
  $("sc-loop-clear").onclick = () => setLoop(null);
  for (const b of document.querySelectorAll("[data-mute]")) b.onclick = () => toggleMute(b.dataset.mute);
  $("sc-metronome").checked = !!state.view.metronome;
  player.metronome = !!state.view.metronome;
  $("sc-metronome").onchange = () => {
    state.view.metronome = $("sc-metronome").checked;
    player.metronome = state.view.metronome;
    player.resetSynth();
    writeView();
  };
  $("sc-countin").value = state.view.countIn || "0";
  $("sc-countin").onchange = () => {
    state.view.countIn = $("sc-countin").value;
    writeView();
  };
  $("sc-pt-slow").onchange = () => {
    state.view.ptSlow = $("sc-pt-slow").checked;
    writeView();
    if (pt.want) pianoteqRender();
  };
  $("sc-midi-connect").hidden = !MidiInput.supported;
  $("sc-midi-connect").onclick = toggleMidi;
  $("sc-midi-mode").value = state.view.midiMode === "wait" ? "wait" : "free";
  $("sc-midi-mode").onchange = () => {
    state.view.midiMode = $("sc-midi-mode").value;
    writeView();
    mk.chord = null;
    mk.doneAt = player.time - 0.001;
    if (mk.waiting && state.view.midiMode !== "wait") {
      mk.waiting = false;
      showPressed();
    }
    midiStatus();
  };
  $("sc-midi-sound").checked = !!state.view.midiSound;
  $("sc-midi-sound").onchange = () => {
    state.view.midiSound = $("sc-midi-sound").checked;
    writeView();
  };
  // What the song remembers, and the practice time, kept when leaving.
  const leave = () => {
    if (state.data) saveSong({ t: Math.round(player.time * 10) / 10 });
    reportPractice(true);
  };
  window.addEventListener("pagehide", leave);
  document.addEventListener("visibilitychange", () => document.visibilityState === "hidden" && leave());
}

const QM_AWAKE_MS = 2500; // the ⚙ stays lit this long after the page is touched
const QM_CLOSE_MS = 6000; // the open menu closes after this long untouched

/** «⚙» quick menu (panels hidden or full screen): edit notes, add a note,
 *  undo, speed, mute a hand, fingers, how much is on screen, panels, full
 *  screen. Each item does what its control on the bars does. */
function wireQuickMenu() {
  const gear = $("sc-qm-gear");
  const menu = $("sc-qm-menu");
  let awake = 0;
  let closing = 0;
  const wake = () => {
    document.body.classList.add("sc-qm-awake");
    clearTimeout(awake);
    awake = setTimeout(() => document.body.classList.remove("sc-qm-awake"), QM_AWAKE_MS);
  };
  for (const ev of ["pointerdown", "pointermove", "keydown", "wheel", "touchstart"]) {
    document.addEventListener(ev, wake, { passive: true });
  }
  const close = () => {
    clearTimeout(closing);
    menu.hidden = true;
    gear.setAttribute("aria-expanded", "false");
  };
  const keepOpen = () => {
    clearTimeout(closing);
    closing = setTimeout(close, QM_CLOSE_MS);
  };
  const refresh = () => {
    const speed = Math.round(player.rate * 100);
    for (const b of menu.querySelectorAll("[data-qm-speed]")) {
      b.setAttribute("aria-pressed", String(Number(b.dataset.qmSpeed) === speed));
      const main = document.querySelector(`#sc-speed [data-speed="${b.dataset.qmSpeed}"]`);
      b.classList.toggle("sc-pt-ready", !!main?.classList.contains("sc-pt-ready"));
    }
    for (const b of menu.querySelectorAll("[data-qm-mute]")) b.setAttribute("aria-pressed", String(state.hand === b.dataset.qmMute));
    menu.querySelector('[data-qm="edit"]').setAttribute("aria-pressed", String(document.body.classList.contains("sc-qm-edit")));
    menu.querySelector('[data-qm="add"]').setAttribute("aria-pressed", String(!!state.adding));
    menu.querySelector('[data-qm="undo"]').disabled = !state.history.canUndo;
    const fing = menu.querySelector('[data-qm="fingers"]');
    const offer = !$("sc-fall-fingers-on").hidden;
    fing.hidden = !offer && !fingers.available;
    fing.textContent = offer ? "🖐 Activar dedos" : "🖐 Ver dedos";
    fing.setAttribute("aria-pressed", String(!offer && fingers.visible()));
    $("sc-qm-ahead").textContent = aheadLabel(state.view.fallAhead);
    menu.querySelector('[data-qm="panels"]').hidden = !state.view.bare;
    menu.querySelector('[data-qm="fs"]').textContent = state.fs ? "⛶ Salir de pantalla completa" : "⛶ Pantalla completa";
  };
  gear.onclick = () => {
    if (!menu.hidden) return close();
    refresh();
    menu.hidden = false;
    gear.setAttribute("aria-expanded", "true");
    keepOpen();
  };
  menu.addEventListener("pointerdown", keepOpen);
  menu.addEventListener("pointermove", keepOpen);
  // A tap elsewhere closes it (the piano, the notes).
  document.addEventListener("pointerdown", (e) => {
    if (!menu.hidden && !e.target.closest("#sc-qm")) close();
  });
  const actions = {
    edit: () => {
      const on = !document.body.classList.contains("sc-qm-edit");
      document.body.classList.toggle("sc-qm-edit", on);
      toast(on ? "✏️ Toca una nota para cambiarla" : "Edición cerrada");
      if (!on) select([]);
    },
    add: () => setAdding(!state.adding),
    undo: () => undo(),
    fingers: () => {
      if (!$("sc-fall-fingers-on").hidden) return $("sc-fall-fingers-on").click();
      const sel = $("sc-fall-fingers");
      sel.value = fingers.visible() ? state.view.fallNames || "letters" : "finger";
      sel.dispatchEvent(new Event("change"));
    },
    "ahead-": () => setAhead(clampAhead(state.view.fallAhead) / AHEAD_FACTOR, { hint: true }),
    "ahead+": () => setAhead(clampAhead(state.view.fallAhead) * AHEAD_FACTOR, { hint: true }),
    panels: () => {
      close();
      setBare(false);
    },
    fs: () => toggleFullscreen(),
  };
  menu.addEventListener("click", (e) => {
    const b = e.target.closest("button");
    if (!b) return;
    if (b.dataset.qmSpeed) setSpeed(Number(b.dataset.qmSpeed));
    else if (b.dataset.qmMute) toggleMute(b.dataset.qmMute);
    else actions[b.dataset.qm]?.();
    // A setting stays open to change it again; an action leaves the menu.
    if (["edit", "add", "fingers", "fs"].includes(b.dataset.qm)) close();
    else refresh();
  });
}

function wireControls() {
  wirePractice();
  wireHands();
  wireQuickMenu();
  $("sc-play").onclick = () => togglePlay();
  $("sc-mini-play").onclick = () => togglePlay();
  $("sc-bare").onclick = () => setBare(true);
  $("sc-mini-panels").onclick = () => {
    if (autoBare) {
      autoBareOff = true; // shown again for this play
      autoBareFrame();
      return;
    }
    setBare(false);
  };
  $("sc-fs").onclick = () => toggleFullscreen();
  $("sc-mini-fs").onclick = () => toggleFullscreen();
  for (const b of document.querySelectorAll("[data-jump]")) b.onclick = () => jump(Number(b.dataset.jump));
  $("sc-view-toggle").onclick = () => setFallView(!state.view.fall);
  $("sc-controls-toggle").onclick = () => setCompact(!state.view.compact);
  $("sc-settings-toggle").onclick = () => setSettings(!state.view.panelSettings);
  setSettings(!!state.view.panelSettings);
  // «⬇ Exportar»: the four downloads in one menu.
  const exportMenu = (open) => {
    $("sc-export-menu").hidden = !open;
    $("sc-export-toggle").setAttribute("aria-expanded", String(open));
  };
  $("sc-export-toggle").onclick = () => exportMenu($("sc-export-menu").hidden);
  for (const id of ["sc-dl-mid", "sc-dl-raw", "sc-dl-xml", "sc-print"]) $(id).addEventListener("click", () => exportMenu(false));
  document.addEventListener("pointerdown", (e) => {
    if (!$("sc-export-menu").hidden && !e.target.closest("#sc-export")) exportMenu(false);
  });
  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape" && !$("sc-export-menu").hidden) exportMenu(false);
  });
  setCompact(!!state.view.compact);
  $("sc-fall-ahead").oninput = () => setAhead(aheadFromSlider($("sc-fall-ahead").value));
  $("sc-fall-ahead").ondblclick = () => setAhead(4, { hint: true });
  for (const [id, key] of [["sc-fall-keys", "fallKeys"], ["sc-fall-colors", "fallColors"], ["sc-fall-names", "fallNames"], ["sc-fall-style", "fallStyle"]]) {
    $(id).onchange = () => {
      state.view[key] = $(id).value;
      setFallView(true);
    };
  }
  $("sc-seek").oninput = () => player.seek((Number($("sc-seek").value) / 1000) * player.duration);
  $("sc-source").onchange = () => {
    const v = $("sc-source").value;
    $("sc-pt-wrap").hidden = v !== "pianoteq";
    saveSong({ source: v });
    handHint();
    if (v === "pianoteq") {
      // Heard at once: the render there is (or the MIDI, until one is), not
      // the stem it was on while the selector already said «Pianoteq».
      player.setSource("pianoteq");
      pianoteqRender();
    } else {
      // pt.want stays: the render keeps up with edits in the background.
      player.setPianoteqStale(false);
      ptStatus("");
      player.setSource(v);
    }
  };
  $("sc-pt-preset").onchange = () => {
    // This song's piano (the server keeps it with the song). A song without
    // one starts with the default piano, not with this.
    pianoteqRender();
  };
  $("sc-sync").oninput = () => setSync(Number($("sc-sync").value));
  $("sc-sync").ondblclick = () => setSync(0);
  setSync(state.view.syncMs || 0);
  for (const b of document.querySelectorAll("[data-speed]")) b.onclick = () => setSpeed(Number(b.dataset.speed));
  // This song's own speed first (setSpeed keeps it with the song: with the
  // global one here, the song's was written over before the song loaded).
  setSpeed(state.song.speed || state.view.speed || 100);
  $("sc-follow").onchange = () => {
    state.view.follow = $("sc-follow").checked;
    writeView();
  };
  // «Zoom»: while the slider moves, what is drawn is scaled at once (a
  // preview: the lines break where they did); let go, the score is engraved
  // again at that size (~0.5 s of Verovio on a long song) and the page goes
  // back to where the song is.
  $("sc-zoom").oninput = () => {
    const f = Number($("sc-zoom").value) / state.view.zoom;
    const host = $("sc-score");
    host.classList.add("sd-zooming");
    for (const svg of host.querySelectorAll(":scope > svg")) svg.style.transform = `scale(${f})`;
  };
  $("sc-zoom").onchange = async () => {
    state.view.zoom = Number($("sc-zoom").value);
    writeView();
    await draw();
    $("sc-score").classList.remove("sd-zooming");
    state.lastSys = null;
    state.forceFollow = true;
    follow(clock.update(player.time, performance.now(), player.playing, player.rate));
    state.forceFollow = false;
  };
  $("sc-grid").onchange = () => putSettings({ grid: $("sc-grid").value });
  $("sc-split").onchange = () => putSettings({ split: Number($("sc-split").value) });
  $("sc-tempo").onchange = () => putSettings({ tempo: $("sc-tempo").value });
  $("sc-key-select").onchange = () => putSettings({ key: $("sc-key-select").value });
  $("sc-hands-select").onchange = () => putSettings({ hands: $("sc-hands-select").value });
  $("sc-pulse-select").onchange = () => putSettings({ pulse: $("sc-pulse-select").value, bar_shift: 0 });
  $("sc-meter-select").onchange = () => putSettings({ meter: $("sc-meter-select").value, bar_shift: 0 });
  const shift = (dir) => {
    const d = state.data;
    const meter = d.measures.find((m) => m.meter)?.meter || 4;
    putSettings({ bar_shift: nextBarShift(d.settings.bar_shift, dir, meter) });
  };
  $("sc-shift-left").onclick = () => shift(-1);
  $("sc-shift-right").onclick = () => shift(1);
  $("sc-pedal").oninput = () => {
    state.pedalDragging = true;
    setPedal(Number($("sc-pedal").value));
  };
  $("sc-pedal").onchange = async () => {
    state.pedalDragging = false;
    await putSettings({ pedal: Number($("sc-pedal").value) });
  };
  $("sc-chordrate").onchange = () => {
    const v = $("sc-chordrate").value;
    putSettings(v === "off" ? { chords: false } : { chords: true, chord_rate: v });
  };
  $("sc-names").onchange = () => {
    const v = $("sc-names").value;
    state.view.noteNames = v !== "none";
    writeView();
    // Names shown again in the spelling the score already has: only drawn.
    if (v === "none" || v === state.data.names) draw();
    else putSettings({ names: v });
  };
  $("sc-undo").onclick = undo;
  $("sc-redo").onclick = redo;
  $("sc-undo2").onclick = undo;
  $("sc-redo2").onclick = redo;
  $("sc-mini-undo").onclick = undo;
  $("sc-history-toggle").onclick = () => {
    $("sc-history").hidden = !$("sc-history").hidden;
    if (!$("sc-history").hidden) renderHistory();
  };
  $("sc-history-close").onclick = () => ($("sc-history").hidden = true);
  $("sc-history-reset").onclick = resetToOriginal;
  $("sc-add").onclick = () => setAdding(!state.adding);
  $("sc-fall-add").onclick = () => setAdding(!state.adding);
  $("sc-reset").onclick = resetToOriginal;
  $("sc-clean-toggle").onclick = () => {
    $("sc-clean").hidden = !$("sc-clean").hidden;
    updateDoomed();
  };
  $("sc-help-toggle").onclick = () => ($("sc-help").hidden = !$("sc-help").hidden);
  $("sc-clean-vel").oninput = updateDoomed;
  $("sc-clean-dur").oninput = updateDoomed;
  $("sc-clean-apply").onclick = () => {
    const ids = [...state.doomed];
    if (!ids.length) return;
    edit(deleteNotes(state.notes, ids), `Limpieza: ${ids.length} notas borradas`);
    state.selection = new Set();
  };
  $("sc-merge").onclick = () => {
    const next = mergeRepeats(state.notes);
    const n = state.notes.length - next.length;
    if (n) edit(next, `${n} notas repetidas unidas`);
    else status("No hay notas repetidas para unir.");
  };
  $("sc-print").onclick = () => window.print();
  $("sc-reextract-go").onclick = async () => {
    if (!(await confirmDialog("¿Volver a extraer el MIDI? Se descartan las ediciones de esta partitura."))) return;
    state.history = new History();
    try {
      await extract($("sc-reextract-source").value, true);
    } catch (e) {
      showState({ state: "error", error: e.message });
    }
  };
  document.addEventListener("keydown", onKey);
  let resizeTimer = null;
  window.addEventListener("resize", () => {
    clearTimeout(resizeTimer);
    resizeTimer = setTimeout(() => state.data && draw(), 300);
  });
  $("sc-audio").addEventListener("play", () => ($("sc-play").textContent = $("sc-mini-play").textContent = "❚❚"));
  $("sc-audio").addEventListener("pause", () => ($("sc-play").textContent = $("sc-mini-play").textContent = "▶"));
  $("sc-audio").addEventListener("loadedmetadata", () => ($("sc-total").textContent = formatTime(player.duration)));
}

// ── follow loop ─────────────────────────────────────────────────────────

/** One frame of following: what is sounding at time t, where the cursor is.
 *  Exported on window for tests (they drive time without real audio). */
let followT = 0; // the song time drawn last (the MIDI keyboard's free play reads it)
let miniText = "";
function follow(t) {
  followT = Math.max(0, t - (state.view.syncMs || 0) / 1000);
  $("sc-now").textContent = formatTime(t);
  if (state.view.bare) miniLine(t);
  if (player.duration && document.activeElement !== $("sc-seek")) {
    $("sc-seek").value = String(Math.round((t / player.duration) * 1000));
  }
  // What is drawn is what is heard: the audio clock minus this device's
  // unreported output latency (Bluetooth, tablets), set with «Sincronía».
  t = Math.max(0, t - (state.view.syncMs || 0) / 1000);
  if (state.view.fall) {
    fall.draw(t);
    return;
  }
  const ctx = state.ctx;
  if (!ctx) return;
  state.playing = markNotes(ctx, "sd-playing", activeAt(state.index, t), state.playing);
  const pos = cursorAt(ctx.timeline, t);
  // The bar sounding, lit (none before the first or after the last).
  const measures = state.data?.measures || [];
  const mi = measureAt(measures, t);
  placeBar(ctx, mi >= 0 && t < measures[measures.length - 1].end ? measures[mi].number : null);
  if (pos) {
    placeCursor(ctx, pos.x, pos.sys);
    if (state.view.follow && pos.sys !== state.lastSys && (player.playing || state.forceFollow)) {
      const b = pos.sys.getBoundingClientRect();
      const top = stickyBottom() + 10;
      if (b.top < top || b.bottom > innerHeight - 20) {
        window.scrollBy({ top: b.top - top - 10, behavior: "smooth" });
      }
    }
    state.lastSys = pos.sys;
  }
}

/** Score or falling notes, at the same point of the song: both follow the
 *  one player, so only the picture changes. */
/** The names inside the falling notes: none when the song shows finger
 *  numbers instead («En las notas: Número de dedo»). */
function fallNames() {
  return fingers.available && state.view.fallLabel === "finger" ? "none" : state.view.fallNames;
}

let aheadHintTimer = 0;
/** «Notas a la vista»: `sec` seconds of the song on the lane (1-20), kept on
 *  this device. `hint`: said over the lane for a moment (a gesture or a key:
 *  the slider may be hidden, full screen or «Ocultar paneles»). */
function setAhead(sec, { hint = false } = {}) {
  const s = Math.round(clampAhead(sec) * 10) / 10;
  state.view.fallAhead = s;
  writeView();
  $("sc-fall-ahead").value = String(sliderFromAhead(s));
  $("sc-fall-ahead-val").textContent = aheadLabel(s);
  fall.setOptions({ lookahead: s });
  if (state.view.fall) fall.draw(clock.update(player.time, performance.now(), player.playing, player.rate));
  if (!hint) return;
  const el = $("sc-fall-hint");
  el.textContent = `Notas a la vista: ${aheadLabel(s)}`;
  el.hidden = false;
  clearTimeout(aheadHintTimer);
  aheadHintTimer = setTimeout(() => (el.hidden = true), 1200);
}

function setFallView(on) {
  state.view.fall = on;
  writeView();
  document.body.classList.toggle("sc-fall-mode", on);
  $("sc-fall").hidden = !on;
  $("sc-fall-bar").hidden = !on;
  $("sc-view-toggle").textContent = on ? "𝄞 Partitura" : "🎹 Piano";
  $("sc-fall-keys").value = state.view.fallKeys;
  $("sc-fall-colors").value = state.view.fallColors;
  $("sc-fall-names").value = state.view.fallNames;
  $("sc-fall-style").value = state.view.fallStyle;
  const ahead = clampAhead(state.view.fallAhead);
  $("sc-fall-ahead").value = String(sliderFromAhead(ahead));
  $("sc-fall-ahead-val").textContent = aheadLabel(ahead);
  $("sc-fall-legend").hidden = state.view.fallColors !== "hands";
  fall.setOptions({ keys: state.view.fallKeys, colors: state.view.fallColors, names: fallNames(), style: fallStyle(), lookahead: ahead });
  const t = clock.update(player.time, performance.now(), player.playing, player.rate);
  if (on) {
    window.scrollTo({ top: 0 }); // the score may have been scrolled far down
    fitFall();
    fall.draw(t);
  } else {
    // Back on the score: scroll to where the song is now.
    state.lastSys = null;
    state.forceFollow = true;
    follow(t);
    state.forceFollow = false;
  }
}

/** The piano fills what is left of the screen below the toolbars, whatever
 *  their height (they wrap to two or three rows on a tablet). */
function fitFall() {
  const host = $("sc-fall");
  if (host.hidden) return;
  const top = host.getBoundingClientRect().top + window.scrollY;
  // Edge to edge with the panels hidden or in full screen (the one line of
  // «Ocultar paneles» floats over the top of the lane).
  const margin = state.view.bare || state.fs ? 0 : 12;
  host.style.height = `${Math.max(320, window.innerHeight - top - margin)}px`; // from the page top
  fall.resize();
}

// ── «Ocultar paneles» and «Pantalla completa» ──────────────────────────

/** The style the piano is drawn in: in full screen, the proportions of a
 *  falling-notes video («Video»); otherwise the one chosen in «Estilo». */
function fallStyle() {
  return state.fs ? "video" : state.view.fallStyle;
}

/** Every bar and panel hidden but one line: the song, where it is, a few
 *  details, play/pause and the way back. Remembered on this device. */
function setBare(on) {
  state.view.bare = on;
  writeView();
  document.body.classList.toggle("sc-bare", on);
  $("sc-mini").hidden = !on;
  $("sc-bare").setAttribute("aria-pressed", String(on));
  miniText = "";
  if (on) miniLine(player.time);
  measureBars();
  window.scrollTo({ top: state.view.fall ? 0 : window.scrollY });
  requestAnimationFrame(fitFall);
}

// On a narrow screen (a tablet) the bars took half of it over the piano:
// while the song plays in the piano view they step aside by themselves (the
// one line «Ocultar paneles» leaves stays, with ▶) and come back on pause.
// Not remembered; «▤ Paneles» on that line brings them back for this play.
const AUTO_BARE_MAX_W = 1100;
let autoBare = false;
let autoBareOff = false; // «▤ Paneles» pressed while playing: not again until a pause

function autoBareFrame() {
  const want = state.view.fall && player.playing && !state.view.bare && !autoBareOff && !state.fs && innerWidth <= AUTO_BARE_MAX_W;
  if (!player.playing) autoBareOff = false;
  if (want === autoBare) return;
  autoBare = want;
  document.body.classList.toggle("sc-bare", want || !!state.view.bare);
  document.body.classList.toggle("sc-auto-bare", want);
  $("sc-mini").hidden = !(want || state.view.bare);
  miniText = "";
  if (want) miniLine(player.time);
  measureBars();
  requestAnimationFrame(fitFall);
}
window.__autoBare = () => autoBare;

/** The one line: ▶, title · time / length · bar n of m · speed · what plays. */
function miniLine(t) {
  const d = state.data;
  if (!d) return;
  const measures = d.measures || [];
  const i = measureAt(measures, t);
  const src = $("sc-source").selectedOptions[0]?.textContent || "";
  const speed = Math.round(player.rate * 100);
  const parts = [
    `<b>${escapeHtml(d.job?.title || JOB)}</b>`,
    `${formatTime(t)} / ${formatTime(player.duration || state.songDuration)}`,
    measures.length ? `compás ${i >= 0 ? measures[i].number : 0} de ${measures.length}` : "",
    speed !== 100 ? `${speed} %` : "",
    state.loop?.on ? `🔁 ${state.loop.from}–${state.loop.to}` : "",
    src,
  ].filter(Boolean);
  const text = parts.join(" · ");
  if (text === miniText) return;
  miniText = text;
  $("sc-mini-text").innerHTML = text;
  $("sc-mini-play").textContent = player.playing ? "❚❚" : "▶";
}

const escapeHtml = (s) => String(s).replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" })[c]);

/** Full screen (the browser's own; where there is none, an iPhone, the same
 *  edge-to-edge page with the panels hidden). */
async function toggleFullscreen() {
  const el = document.documentElement;
  const native = el.requestFullscreen || el.webkitRequestFullscreen;
  const inNative = document.fullscreenElement || document.webkitFullscreenElement;
  if (native) {
    try {
      if (inNative) await (document.exitFullscreen || document.webkitExitFullscreen).call(document);
      else await native.call(el, { navigationUI: "hide" });
      return; // fullscreenchange does the rest
    } catch {
      /* refused (not from a click, an iframe): the page's own below */
    }
  }
  setFullscreen(!state.fs);
}

function setFullscreen(on) {
  state.fs = on;
  document.body.classList.toggle("sc-fs", on);
  for (const id of ["sc-fs", "sc-mini-fs"]) $(id).setAttribute("aria-pressed", String(on));
  $("sc-fs").textContent = on ? "⛶ Salir de pantalla completa" : "⛶ Pantalla completa";
  if (state.data) setFallView(!!state.view.fall); // the «Video» proportions in, or out
  requestAnimationFrame(fitFall);
}

for (const ev of ["fullscreenchange", "webkitfullscreenchange"]) {
  document.addEventListener(ev, () => setFullscreen(!!(document.fullscreenElement || document.webkitFullscreenElement)));
}
window.addEventListener("resize", () => fitFall());

/** The fixed bars at the top (title, transport, the score's settings) stay
 *  stacked whatever their height: each sticks below the ones above it. */
function measureBars() {
  const root = document.documentElement.style;
  root.setProperty("--sc-top-h", `${document.querySelector(".sc-top").offsetHeight}px`);
  root.setProperty("--sc-transport-h", `${document.querySelector(".sc-transport").offsetHeight}px`);
}
new ResizeObserver(measureBars).observe(document.querySelector(".sc-top"));
new ResizeObserver(measureBars).observe(document.querySelector(".sc-transport"));

/** Where the score starts being visible below the fixed bars (px from the top). */
function stickyBottom() {
  const bars = [".sc-top", ".sc-transport", ".sc-tools", "#sc-mini"].map((s) => document.querySelector(s)?.getBoundingClientRect());
  return Math.max(0, ...bars.filter((b) => b && b.height).map((b) => b.bottom));
}

/** Show only the playback line, or every control; remembered on this device. */
/** «🎼 Ajustes»: the transcription's settings shown or folded (remembered). */
function setSettings(on) {
  state.view.panelSettings = on;
  writeView();
  document.body.classList.toggle("sc-settings-open", on);
  const b = $("sc-settings-toggle");
  b.textContent = on ? "🎼 Ajustes ▴" : "🎼 Ajustes ▾";
  b.setAttribute("aria-expanded", String(on));
  measureBars();
}

function setCompact(on) {
  state.view.compact = on;
  writeView();
  document.body.classList.toggle("sc-compact", on);
  const b = $("sc-controls-toggle");
  b.textContent = on ? "Controles ▾" : "Controles ▴";
  b.setAttribute("aria-expanded", String(!on));
  measureBars();
  fitFall(); // the piano grows into the room the bars leave
}

/** Jump s seconds back or forward, in either view. */
function jump(s) {
  const end = player.duration || Infinity;
  player.seek(Math.max(0, Math.min(end - 0.05, player.time + s)));
}
window.__scoreFollow = follow;

let lastT = -1;
const clock = new SmoothClock();
let savedAt = 0;
function frame(nowMs) {
  const now = nowMs ?? performance.now();
  // While the audio stalls the clock holds instead of running ahead of it.
  let t = clock.update(player.time, now, player.playing && !player.stalled, player.rate);
  // The loop: past B, back to A.
  const back = player.playing && !player.stalled ? loopJump(state.loop, t) : null;
  if (back != null) {
    loopAgain(back);
    t = clock.update(player.time, now, false, player.rate);
  }
  autoBareFrame();
  if (t !== lastT || player.playing) {
    player.tick();
    follow(t);
    midiFrame(t);
    lastT = t;
  }
  // Practice time (wall clock while it plays), reported every 30 s; the
  // place in the song kept every few seconds.
  const dt = practice.lastWall ? Math.min(0.25, (now - practice.lastWall) / 1000) : 0;
  practice.lastWall = now;
  if (player.playing && !player.stalled && state.data) {
    practice.secs += dt;
    if (now - practice.sentAt > 30000 && practice.secs >= 5) reportPractice();
    if (now - savedAt > 3000) {
      savedAt = now;
      saveSong({ t: Math.round(t * 10) / 10 });
    }
  }
  requestAnimationFrame(frame);
}

// ── boot ────────────────────────────────────────────────────────────────

async function boot() {
  wireControls();
  wirePointer();
  if (!JOB || !/^[a-f0-9]{12}$/.test(JOB)) return landing();
  $("sc-back").href = `/`;
  try {
    const data = await api(API);
    if (data.status.state === "done") {
      await load(data);
    } else if (data.status.state === "queued" || data.status.state === "running") {
      showState(data.status);
      const done = await poll();
      if (done) await load(done);
    } else {
      showState(data.status);
    }
  } catch (e) {
    show("sc-state");
    $("sc-state-title").textContent = "No se pudo abrir";
    $("sc-state-text").textContent = e.message.startsWith("404")
      ? `No hay una canción terminada con stem «${stemName(STEM)}» con ese id, o ese stem no tiene motor de transcripción.`
      : e.message;
    $("sc-start").hidden = true;
  }
  requestAnimationFrame(frame);
}

boot();
