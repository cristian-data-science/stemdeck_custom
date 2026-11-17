// A saxophone in the browser (Web Audio): a reed-like tone (saw + square)
// through the instrument's formants, a breath at each attack, vibrato that
// comes in on held notes, a soft growl. Not a sampled saxophone, but it
// sings the line in tune and in time, with nothing to download.

export class SaxSynth {
  constructor(ctx) {
    this.ctx = ctx;
    this.out = ctx.createGain();
    this.out.gain.value = 0.8;
    // A touch of saturation (the reed's edge), then a compressor.
    const shaper = ctx.createWaveShaper();
    const curve = new Float32Array(1024);
    for (let i = 0; i < curve.length; i++) {
      const x = (i / (curve.length - 1)) * 2 - 1;
      curve[i] = Math.tanh(1.8 * x);
    }
    shaper.curve = curve;
    const comp = ctx.createDynamicsCompressor();
    comp.threshold.value = -16;
    comp.ratio.value = 3;
    // The body: formants of an alto (and a little room).
    const f1 = ctx.createBiquadFilter();
    f1.type = "peaking";
    f1.frequency.value = 650;
    f1.Q.value = 1.4;
    f1.gain.value = 6;
    const f2 = ctx.createBiquadFilter();
    f2.type = "peaking";
    f2.frequency.value = 1750;
    f2.Q.value = 1.8;
    f2.gain.value = 4;
    this.bus = ctx.createGain();
    this.bus.connect(f1).connect(f2).connect(shaper).connect(comp).connect(this.out);
    this.out.connect(ctx.destination);
    this.noise = this._noise();
    this.voices = new Set();
    this.cents = 0; // the song's tuning: the saxophone plays in tune with the record
  }

  _noise() {
    const len = this.ctx.sampleRate;
    const buf = this.ctx.createBuffer(1, len, this.ctx.sampleRate);
    const d = buf.getChannelData(0);
    for (let i = 0; i < len; i++) d[i] = Math.random() * 2 - 1;
    return buf;
  }

  set volume(v) {
    this.out.gain.setTargetAtTime(Math.max(0, v), this.ctx.currentTime, 0.02);
  }

  /** One note: `midi` (concert), from `when` (context time) for `dur` s. */
  play(midi, when, dur, velocity = 80) {
    const ctx = this.ctx;
    const f = 440 * 2 ** ((midi + this.cents / 100 - 69) / 12);
    const peak = 0.12 + (velocity / 127) * 0.16;
    const end = when + Math.max(0.06, dur);
    const release = 0.08;

    const saw = ctx.createOscillator();
    saw.type = "sawtooth";
    saw.frequency.value = f;
    const sq = ctx.createOscillator();
    sq.type = "square";
    sq.frequency.value = f * 1.003;
    const sqGain = ctx.createGain();
    sqGain.gain.value = 0.3;

    // Vibrato: in after a held note's first moment.
    const lfo = ctx.createOscillator();
    lfo.frequency.value = 5.3;
    const depth = ctx.createGain();
    depth.gain.setValueAtTime(0, when);
    if (dur > 0.35) {
      depth.gain.setValueAtTime(0, when + 0.22);
      depth.gain.linearRampToValueAtTime(f * 0.007, when + 0.6);
    }
    lfo.connect(depth);
    depth.connect(saw.frequency);
    depth.connect(sq.frequency);
    // A small scoop into the note, as a player lips up to it.
    saw.frequency.setValueAtTime(f * 0.985, when);
    saw.frequency.exponentialRampToValueAtTime(f, when + 0.05);

    // Brightness: opens on the attack, settles.
    const tone = ctx.createBiquadFilter();
    tone.type = "lowpass";
    tone.Q.value = 0.9;
    const bright = Math.min(9000, f * (6 + velocity / 25));
    tone.frequency.setValueAtTime(f * 2, when);
    tone.frequency.exponentialRampToValueAtTime(bright, when + 0.05);
    tone.frequency.exponentialRampToValueAtTime(Math.min(7000, f * 4.5), when + 0.25);

    const amp = ctx.createGain();
    amp.gain.setValueAtTime(0, when);
    amp.gain.linearRampToValueAtTime(peak, when + 0.035);
    amp.gain.setTargetAtTime(peak * 0.82, when + 0.04, 0.12);
    amp.gain.setValueAtTime(peak * 0.82, end);
    amp.gain.linearRampToValueAtTime(0, end + release);

    // The breath: noise through the reed's band, strongest at the attack.
    const air = ctx.createBufferSource();
    air.buffer = this.noise;
    air.loop = true;
    const airBand = ctx.createBiquadFilter();
    airBand.type = "bandpass";
    airBand.frequency.value = Math.min(6000, f * 5);
    airBand.Q.value = 0.8;
    const airAmp = ctx.createGain();
    airAmp.gain.setValueAtTime(0, when);
    airAmp.gain.linearRampToValueAtTime(peak * 0.35, when + 0.02);
    airAmp.gain.setTargetAtTime(peak * 0.06, when + 0.03, 0.08);
    airAmp.gain.setValueAtTime(peak * 0.06, end);
    airAmp.gain.linearRampToValueAtTime(0, end + release);

    saw.connect(tone);
    sq.connect(sqGain).connect(tone);
    tone.connect(amp).connect(this.bus);
    air.connect(airBand).connect(airAmp).connect(this.bus);

    const nodes = [saw, sq, lfo, air];
    for (const s of nodes) {
      s.start(when);
      s.stop(end + release + 0.02);
    }
    const voice = { nodes, amp, airAmp };
    this.voices.add(voice);
    saw.onended = () => this.voices.delete(voice);
    return voice;
  }

  /** Everything sounding or scheduled stops now (a pause, a seek). */
  stopAll() {
    const now = this.ctx.currentTime;
    for (const v of this.voices) {
      for (const g of [v.amp.gain, v.airAmp.gain]) {
        g.cancelScheduledValues(now);
        g.setTargetAtTime(0, now, 0.015);
      }
      for (const s of v.nodes) {
        try {
          s.stop(now + 0.08);
        } catch {
          /* not started yet: stop() before start() throws in some browsers */
        }
      }
    }
    this.voices.clear();
  }
}

// ── a real saxophone ────────────────────────────────────────────────────
//
// Recorded notes (static/audio/sax/<alto|soprano>/<pp|mf|ff>/<midi>.mp3,
// built by scripts/sax/build_samples.py from the University of Iowa MIS
// recordings: every note of the instrument, with vibrato, three dynamics).
// The tenor and the baritone play the alto's notes moved to their pitch
// (the MIS has no tenor or baritone).

const SAMPLE_SET = { alto: "alto", soprano: "soprano", tenor: "alto", baritone: "alto" };

export class SaxSampler {
  constructor(ctx) {
    this.ctx = ctx;
    this.out = ctx.createGain();
    this.out.gain.value = 0.9;
    // A little room, so it does not sound like a dry recording booth.
    const dry = ctx.createGain();
    const wet = ctx.createGain();
    wet.gain.value = 0.18;
    const room = ctx.createConvolver();
    room.buffer = this._room(1.6);
    this.bus = ctx.createGain();
    this.bus.connect(dry).connect(this.out);
    this.bus.connect(room).connect(wet).connect(this.out);
    this.out.connect(ctx.destination);
    this.cents = 0;
    this.buffers = new Map(); // "pp:61" -> AudioBuffer
    this.tuning = new Map(); // "pp:61" -> cents the recording is off
    this.notes = [];
    this.set = null;
    this.voices = new Set();
  }

  _room(seconds) {
    const rate = this.ctx.sampleRate;
    const len = Math.round(seconds * rate);
    const buf = this.ctx.createBuffer(2, len, rate);
    for (let ch = 0; ch < 2; ch++) {
      const d = buf.getChannelData(ch);
      for (let i = 0; i < len; i++) d[i] = (Math.random() * 2 - 1) * Math.exp((-3.2 * i) / len) * (i < rate * 0.01 ? i / (rate * 0.01) : 1);
    }
    return buf;
  }

  set volume(v) {
    this.out.gain.setTargetAtTime(Math.max(0, v), this.ctx.currentTime, 0.02);
  }

  get ready() {
    return this.buffers.size > 0;
  }

  /** Load the recordings for a saxophone (every note, three dynamics). */
  /** `variant`: "" (with vibrato) or "-novib" (without: for «Expresivo»,
   *  where the vibrato is the singer's). */
  async load(sax, onProgress, variant = "") {
    const set = (SAMPLE_SET[sax] || "alto") + variant;
    if (this.set === set && this.ready) return;
    const base = `/audio/sax/${set}`;
    const manifest = await (await fetch(`${base}/manifest.json`)).json();
    const jobs = [];
    for (const [midi, layers] of Object.entries(manifest.notes)) {
      for (const [dyn, info] of Object.entries(layers)) jobs.push({ midi: Number(midi), dyn, cents: info.cents });
    }
    const buffers = new Map();
    const tuning = new Map();
    let done = 0;
    await Promise.all(
      jobs.map(async (j) => {
        const data = await (await fetch(`${base}/${j.dyn}/${j.midi}.mp3`)).arrayBuffer();
        buffers.set(`${j.dyn}:${j.midi}`, await this.ctx.decodeAudioData(data));
        tuning.set(`${j.dyn}:${j.midi}`, j.cents);
        onProgress?.(++done / jobs.length);
      }),
    );
    this.buffers = buffers;
    this.tuning = tuning;
    this.notes = [...new Set(jobs.map((j) => j.midi))].sort((a, b) => a - b);
    this.set = set;
  }

  _nearest(midi) {
    let best = this.notes[0];
    for (const n of this.notes) if (Math.abs(n - midi) < Math.abs(best - midi)) best = n;
    return best;
  }

  /** One note: `midi` (concert), from `when` (context time) for `dur` s.
   *  `legato`: slurred from the note before: the recording joined past its
   *  tongued attack, faded in under the note before's release, so the two
   *  sound as one breath (a new attack on every note sounded choppy). */
  play(midi, when, dur, velocity = 80, { legato = false } = {}) {
    if (!this.ready) return null;
    // pp only for really soft notes: under the band it was lost (a learner must hear the line).
    const dyn = velocity < 45 ? "pp" : velocity < 100 ? "mf" : "ff";
    const src = this._nearest(midi);
    const key = `${dyn}:${src}`;
    const buf = this.buffers.get(key) || this.buffers.get(`mf:${src}`);
    if (!buf) return null;
    const cents = (midi - src) * 100 - (this.tuning.get(key) || 0) + this.cents;
    const rate = 2 ** (cents / 1200);
    const ctx = this.ctx;
    const release = 0.12;
    const end = when + Math.max(0.08, dur);
    const amp = ctx.createGain();
    if (legato) {
      amp.gain.setValueAtTime(0, when);
      amp.gain.linearRampToValueAtTime(1, when + 0.04);
    } else {
      amp.gain.setValueAtTime(1, when);
    }
    amp.gain.setValueAtTime(1, end);
    amp.gain.linearRampToValueAtTime(0, end + release);
    amp.connect(this.bus);
    // The recording as long as it lasts; a longer note goes on with the
    // middle of it again, crossfaded (its sustain, vibrato and all).
    const sources = [];
    const usable = buf.duration / rate - 0.35;
    const xfade = 0.25;
    let t = when;
    let offset = legato ? 0.07 : 0; // past the attack of the recording
    while (t < end + release) {
      const s = ctx.createBufferSource();
      s.buffer = buf;
      s.playbackRate.value = rate;
      const g = ctx.createGain();
      s.connect(g).connect(amp);
      const span = (buf.duration - offset) / rate - 0.35;
      const segEnd = Math.min(end + release, t + span);
      if (offset > 0 && t > when) {
        g.gain.setValueAtTime(0, t);
        g.gain.linearRampToValueAtTime(1, t + xfade);
      }
      if (segEnd < end + release) {
        g.gain.setValueAtTime(1, segEnd - xfade);
        g.gain.linearRampToValueAtTime(0, segEnd);
      }
      s.start(t, offset);
      s.stop(segEnd + 0.02);
      sources.push(s);
      if (segEnd >= end + release || usable <= 0.6) break;
      t = segEnd - xfade;
      offset = 0.6;
    }
    const voice = { sources, amp };
    this.voices.add(voice);
    sources[sources.length - 1].onended = () => this.voices.delete(voice);
    return voice;
  }

  /** «Expresivo»: one note played as it was sung. `curve.midi` (concert,
   *  every `curve.step` s from `when`): the sung pitch, slides and vibrato
   *  included, applied to a recording without vibrato; `curve.level` (0-1):
   *  its loudness, the swells and fades. `legato`: from the note before
   *  without a new attack. */
  playCurve(target, when, dur, curve, { legato = false } = {}) {
    if (!this.ready || !curve?.midi?.length) return this.play(target, when, dur, 80, { legato });
    const meanLevel = curve.level.reduce((a, b) => a + b, 0) / curve.level.length;
    const dyn = meanLevel > 0.8 && this.buffers.has(`ff:${this._nearest(target)}`) ? "ff" : "mf";
    const src = this._nearest(target);
    const key = `${dyn}:${src}`;
    const buf = this.buffers.get(key) || this.buffers.get(`mf:${src}`);
    if (!buf) return null;
    const own = this.tuning.get(key) || 0;
    // The contour is in the song's own tuning already: only the recording's
    // own offset is taken out.
    const rates = Float32Array.from(curve.midi, (m) => 2 ** (((m - src) * 100 - own) / 1200));
    const gains = Float32Array.from(curve.level, (l) => 0.3 + 0.7 * Math.min(1, l * 1.25));
    const ctx = this.ctx;
    const release = 0.1;
    const end = when + Math.max(0.08, dur);
    const shape = ctx.createGain(); // the singer's loudness
    shape.gain.setValueCurveAtTime(gains.length > 1 ? gains : Float32Array.of(gains[0], gains[0]), when, Math.max(0.02, end - when));
    const amp = ctx.createGain(); // in (legato) and out
    amp.gain.setValueAtTime(legato ? 0 : 1, when);
    if (legato) amp.gain.linearRampToValueAtTime(1, when + 0.04);
    amp.gain.setValueAtTime(1, end);
    amp.gain.linearRampToValueAtTime(0, end + release);
    shape.connect(amp).connect(this.bus);
    const at = (t) => Math.min(rates.length - 1, Math.max(0, Math.round((t - when) / curve.step)));
    const sources = [];
    const xfade = 0.25;
    let t = when;
    let offset = legato ? 0.07 : 0;
    while (t < end + release) {
      const s = ctx.createBufferSource();
      s.buffer = buf;
      const meanRate = rates[at(t)] || 1;
      const span = (buf.duration - offset) / meanRate - 0.35;
      const segEnd = Math.min(end + release, t + Math.max(0.1, span));
      const a = at(t);
      const b = Math.max(a + 2, at(segEnd) + 1);
      const slice = rates.slice(a, Math.min(rates.length, b));
      if (slice.length >= 2) s.playbackRate.setValueCurveAtTime(slice, t, Math.max(0.02, Math.min(segEnd, end) - t));
      else s.playbackRate.setValueAtTime(slice[0] || 1, t);
      const g = ctx.createGain();
      s.connect(g).connect(shape);
      if (sources.length) {
        g.gain.setValueAtTime(0, t);
        g.gain.linearRampToValueAtTime(1, t + xfade);
      }
      if (segEnd < end + release) {
        g.gain.setValueAtTime(1, segEnd - xfade);
        g.gain.linearRampToValueAtTime(0, segEnd);
      }
      s.start(t, offset);
      s.stop(segEnd + 0.02);
      sources.push(s);
      if (segEnd >= end + release || span <= 0.6) break;
      t = segEnd - xfade;
      offset = 0.6;
    }
    const voice = { sources, amp };
    this.voices.add(voice);
    sources[sources.length - 1].onended = () => this.voices.delete(voice);
    return voice;
  }

  stopAll() {
    const now = this.ctx.currentTime;
    for (const v of this.voices) {
      v.amp.gain.cancelScheduledValues(now);
      v.amp.gain.setTargetAtTime(0, now, 0.02);
      for (const s of v.sources) {
        try {
          s.stop(now + 0.1);
        } catch {
          /* already stopped */
        }
      }
    }
    this.voices.clear();
  }
}
