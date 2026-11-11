// Score view: playback. An <audio> element is the clock (its currentTime is
// what the score follows); a small WebAudio synth can play the extracted
// notes alongside or instead of it, which is the quickest way for a person to
// hear whether the transcription is right (A/B against the stem).
//
// Practice on top of that: a metronome on the bars' beats and a count-in
// before playing, one hand left silent (to play it yourself), the keys of a
// MIDI keyboard sounded, and Pianoteq renders made at a slower tempo -- a
// file whose second s is song second s * speed, played at its own rate
// instead of stretched by the browser (which smears a piano).

import { buildTimeIndex, heldEnd, upperBound } from "./model.js";

const LOOKAHEAD = 0.25; // seconds of notes scheduled ahead of the playhead

export class Player {
  constructor(audio) {
    this.audio = audio;
    this.source = "stem";
    this.rate = 1;
    this.pedal = 0; // % of the sustain pedal (model.heldEnd)
    this.detune = 0; // cents from A440: the song's own tuning, to play along with it
    // Listening to Pianoteq after an edit, before its new render is back: the
    // file still has the old notes (a deleted one included), so the synth,
    // which has the edit, plays instead until the render lands.
    this.ptStale = false;
    this.urls = { stem: "", mix: "", pianoteq: "" };
    // The Pianoteq file's speed: 1, or the practice speed it was rendered at.
    this.ptSpeed = 1;
    this.scale = 1; // song seconds per second of the file loaded now
    // The staff the synth leaves out (1 right hand, 2 left; 0 none): the
    // hand the player plays themself.
    this.silentStaff = 0;
    this.metronome = false;
    this.beats = []; // [{t, down}] (practice.beatsOf)
    this.nextBeat = 0;
    this.countIn = null; // {timer, clicks} while counting in
    this.ctx = null;
    this.master = null;
    this.voices = new Set();
    this.live = new Map(); // midi -> voice: keys held on a MIDI keyboard
    this.index = buildTimeIndex([]);
    this.nextIdx = 0;
    this.scheduledUntil = 0;
    audio.preservesPitch = true;
    // "waiting": the audio stopped to load (after a jump, on Wi-Fi): notes
    // already scheduled would sound ahead of it.
    for (const ev of ["seeking", "pause", "ratechange", "waiting"]) {
      audio.addEventListener(ev, () => this.resetSynth());
    }
  }

  setNotes(notes) {
    this.index = buildTimeIndex(notes);
    this.resetSynth();
  }

  setUrls(urls, { ptSpeed } = {}) {
    this.urls = { ...this.urls, ...urls };
    if (ptSpeed != null) this.ptSpeed = ptSpeed;
    this._applySource(true);
  }

  setSource(source) {
    this.source = source;
    this._applySource();
  }

  setBeats(beats) {
    this.beats = beats;
    this.resetSynth();
  }

  /** Point the audio element at the current source, at the same moment of
   *  the song. While a new file loads its currentTime reads 0, so the moment
   *  is kept in `pending` until it lands: reading currentTime there sent the
   *  song back to 0:00 when a Pianoteq render arrived (a reload of the
   *  current file immediately followed by the switch), and on any second
   *  switch made before the first file had loaded. */
  _applySource() {
    // Pianoteq: the score rendered by Pianoteq, a file on the song's own
    // timeline (at ptSpeed), so it is the clock like the stem.
    const pt = this.source === "pianoteq" && this.urls.pianoteq;
    const wanted = this.source === "stem" || this.source === "midi" || this.source === "both"
      ? this.urls.stem
      : this.urls[this.source] || this.urls.stem;
    const scale = pt && wanted === this.urls.pianoteq ? this.ptSpeed || 1 : 1;
    if (wanted && (!this.audio.src.endsWith(wanted) || scale !== this.scale)) {
      const at = this.pending || { t: this.time, playing: !this.audio.paused };
      this.pending = at;
      const seq = (this.loadSeq = (this.loadSeq || 0) + 1);
      const reload = !this.audio.src.endsWith(wanted);
      this.scale = scale;
      const land = () => {
        if (seq !== this.loadSeq) return; // a newer switch owns the element now
        // Nothing asked for (0:00) but the element was moved meanwhile (set
        // straight on it while the file loaded): keep where it was moved to.
        const file = at.t === 0 && this.audio.currentTime > 0 ? this.audio.currentTime : at.t / this.scale;
        this.audio.currentTime = Math.min(file, this.audio.duration || file);
        this._setElementRate();
        this.pending = null;
        if (at.playing) this.audio.play();
      };
      if (reload) {
        this.audio.src = wanted;
        this.audio.addEventListener("loadedmetadata", land, { once: true });
      } else land();
    }
    // MIDI only: keep the audio running as the clock, silently.
    this.audio.muted = this.synthOnly;
    this.resetSynth();
  }

  _setElementRate() {
    // A file rendered slower plays faster to keep the song's rate: at the
    // practice speed it was made for, at its own rate (no stretching at all).
    const r = Math.max(0.0625, Math.min(16, this.rate / this.scale));
    this.audio.defaultPlaybackRate = r;
    this.audio.playbackRate = r;
  }

  setRate(rate) {
    this.rate = rate;
    // Loading a new src resets playbackRate to the default one: set both.
    this._setElementRate();
  }

  /** The synth is all that is heard (the audio only keeps time). */
  get synthOnly() {
    return this.source === "midi" || (this.source === "pianoteq" && (this.ptStale || !this.urls.pianoteq));
  }

  setPianoteqStale(stale) {
    if (this.ptStale === stale) return;
    this.ptStale = stale;
    this.audio.muted = this.synthOnly;
    this.resetSynth();
  }

  setSilentStaff(staff) {
    this.silentStaff = staff || 0;
    this.resetSynth();
  }

  get playing() {
    if (this.countIn) return true;
    return this.pending ? this.pending.playing : !this.audio.paused;
  }

  /** Playing but not moving: seeking, or waiting for data (a jump on Wi-Fi
   *  loads a new stretch of the file first). Nothing should run ahead then. */
  get stalled() {
    return !!this.countIn || (!this.audio.paused && (this.audio.seeking || this.audio.readyState < 3));
  }

  get time() {
    return this.pending ? this.pending.t : (this.audio.currentTime || 0) * this.scale;
  }

  get duration() {
    return Number.isFinite(this.audio.duration) ? this.audio.duration * this.scale : 0;
  }

  /** Play, after `countIn` clicks (seconds apart, song time) when asked. */
  async play({ countIn = 0, beatSec = 0.5 } = {}) {
    if (this.pending) {
      this.pending.playing = true;
      return;
    }
    this._ensureCtx();
    if (countIn > 0 && this.ctx) {
      const gap = beatSec / this.rate;
      const t0 = this.ctx.currentTime + 0.05;
      for (let k = 0; k < countIn; k++) this._click(t0 + k * gap, k === 0);
      const timer = setTimeout(() => {
        if (this.countIn?.timer !== timer) return;
        this.countIn = null;
        this.audio.play();
      }, (0.05 + countIn * gap) * 1000);
      this.countIn = { timer };
      return;
    }
    await this.audio.play();
  }

  pause() {
    if (this.countIn) {
      clearTimeout(this.countIn.timer);
      this.countIn = null;
    }
    if (this.pending) this.pending.playing = false;
    else this.audio.pause();
  }

  async toggle(opts = {}) {
    if (this.countIn) return this.pause();
    if (this.pending) {
      // Still loading the new source: play/pause takes effect when it lands.
      this.pending.playing = !this.pending.playing;
      return;
    }
    if (this.audio.paused) await this.play(opts);
    else this.pause();
  }

  seek(t) {
    if (this.pending) this.pending.t = Math.max(0, t); // lands with the file being loaded
    const file = Math.max(0, t) / this.scale;
    this.audio.currentTime = Math.min(file, Number.isFinite(this.audio.duration) ? this.audio.duration : file);
    this.resetSynth();
  }

  _ensureCtx() {
    if (this.ctx) {
      if (this.ctx.state === "suspended") this.ctx.resume();
      return;
    }
    const Ctx = window.AudioContext || window.webkitAudioContext;
    if (!Ctx) return;
    this.ctx = new Ctx();
    this.master = this.ctx.createGain();
    this.master.gain.value = 0.22;
    this.master.connect(this.ctx.destination);
  }

  resetSynth() {
    for (const v of this.voices) {
      try {
        v.gain.gain.cancelScheduledValues(0);
        v.gain.gain.setTargetAtTime(0, this.ctx.currentTime, 0.01);
        v.osc.forEach((o) => o.stop(this.ctx.currentTime + 0.05));
      } catch {
        /* already stopped */
      }
    }
    this.voices.clear();
    this.nextIdx = upperBound(this.index.starts, this.time - 1e-6);
    this.scheduledUntil = this.time;
    this.nextBeat = upperBound(this.beats.map((b) => b.t), this.time - 1e-6);
  }

  /** Called every animation frame while playing. */
  tick() {
    if (this.audio.paused || !this.ctx || this.stalled) return;
    const t = this.time;
    const horizon = t + LOOKAHEAD * this.rate;
    if (this.metronome) {
      while (this.nextBeat < this.beats.length && this.beats[this.nextBeat].t < horizon) {
        const b = this.beats[this.nextBeat++];
        if (b.t < t - 0.05) continue;
        this._click(this.ctx.currentTime + (b.t - t) / this.rate, b.down);
      }
    }
    if (!this.synthOnly && this.source !== "both") return;
    const { sorted } = this.index;
    while (this.nextIdx < sorted.length && sorted[this.nextIdx].start < horizon) {
      const n = sorted[this.nextIdx++];
      if (n.start < t - 0.05) continue;
      if (this.silentStaff && (n.staff === 2 ? 2 : 1) === this.silentStaff) continue;
      this._voice(n, this.ctx.currentTime + (n.start - t) / this.rate, (heldEnd(n, this.pedal) - n.start) / this.rate);
    }
  }

  /** A metronome click: higher and louder on the bar's first beat. */
  _click(when, down) {
    const ctx = this.ctx;
    if (!ctx) return;
    const o = ctx.createOscillator();
    const g = ctx.createGain();
    o.type = "square";
    o.frequency.value = down ? 1760 : 1175;
    g.gain.setValueAtTime(0, when);
    g.gain.linearRampToValueAtTime(down ? 0.5 : 0.3, when + 0.002);
    g.gain.exponentialRampToValueAtTime(0.0001, when + 0.06);
    o.connect(g).connect(this.master);
    o.start(when);
    o.stop(when + 0.08);
  }

  /** A key pressed on a MIDI keyboard, sounded by the synth until released. */
  liveOn(midi, velocity = 80) {
    this._ensureCtx();
    if (!this.ctx) return;
    this.liveOff(midi);
    const v = this._voice({ midi, velocity }, this.ctx.currentTime, 30, { live: true });
    this.live.set(midi, v);
  }

  liveOff(midi) {
    const v = this.live.get(midi);
    if (!v) return;
    this.live.delete(midi);
    const now = this.ctx.currentTime;
    try {
      v.gain.gain.cancelScheduledValues(now);
      v.gain.gain.setTargetAtTime(0.0001, now, 0.08);
      v.osc.forEach((o) => o.stop(now + 0.5));
    } catch {
      /* already stopped */
    }
  }

  _voice(n, when, dur, { live = false } = {}) {
    const ctx = this.ctx;
    const f = 440 * 2 ** ((n.midi - 69) / 12);
    const gain = ctx.createGain();
    const vel = Math.max(0.15, (n.velocity || 80) / 127);
    const peak = 0.6 * vel;
    const off = when + Math.max(0.06, dur);
    // Attack, a quick settle, then a fade like a string left ringing (the
    // pedal can hold a note for many seconds; low notes ring longer). Each
    // stage stops at the release, so a short note never swells back.
    const settle = Math.min(when + 0.35, off);
    gain.gain.setValueAtTime(0, when);
    gain.gain.linearRampToValueAtTime(peak, when + 0.006);
    gain.gain.exponentialRampToValueAtTime(peak * 0.45, settle);
    if (off > settle) gain.gain.setTargetAtTime(0.0001, settle, 0.8 + 2.2 * Math.max(0, (84 - n.midi) / 48));
    gain.gain.setTargetAtTime(0.0001, off, 0.05);
    gain.connect(this.master);
    const osc = [
      ["triangle", f, 1],
      ["sine", f * 2, 0.25],
    ].map(([type, freq, level]) => {
      const o = ctx.createOscillator();
      o.type = type;
      o.frequency.value = freq;
      o.detune.value = live ? 0 : this.detune;
      const g = ctx.createGain();
      g.gain.value = level;
      o.connect(g).connect(gain);
      o.start(when);
      o.stop(off + 0.4);
      return o;
    });
    const voice = { osc, gain };
    if (!live) {
      this.voices.add(voice);
      osc[0].onended = () => this.voices.delete(voice);
    }
    return voice;
  }
}
