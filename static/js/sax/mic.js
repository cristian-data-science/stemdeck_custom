// «🎤 Practicar» in «🎷 Saxo»: the player's saxophone through the microphone,
// its pitch read (YIN) and set against the note the line asks for.

/** YIN (de Cheveigné & Kawahara 2002) on one frame: {hz, clarity} or null
 *  for a frame with no clear pitch (silence, breath, noise). */
export function yin(buf, sampleRate, { threshold = 0.15, fmin = 60, fmax = 1600 } = {}) {
  const n = buf.length;
  const maxLag = Math.min(Math.floor(n / 2), Math.ceil(sampleRate / fmin));
  const minLag = Math.max(2, Math.floor(sampleRate / fmax));
  let energy = 0;
  for (let i = 0; i < n; i++) energy += buf[i] * buf[i];
  if (energy / n < 1e-6) return null; // silence
  const d = new Float32Array(maxLag + 1);
  for (let lag = 1; lag <= maxLag; lag++) {
    let sum = 0;
    for (let i = 0; i < n - maxLag; i++) {
      const x = buf[i] - buf[i + lag];
      sum += x * x;
    }
    d[lag] = sum;
  }
  // Cumulative mean normalised difference.
  const cm = new Float32Array(maxLag + 1);
  cm[0] = 1;
  let running = 0;
  for (let lag = 1; lag <= maxLag; lag++) {
    running += d[lag];
    cm[lag] = running ? (d[lag] * lag) / running : 1;
  }
  let lag = -1;
  for (let k = minLag; k <= maxLag; k++) {
    if (cm[k] < threshold) {
      while (k + 1 <= maxLag && cm[k + 1] < cm[k]) k++;
      lag = k;
      break;
    }
  }
  if (lag < 0) return null;
  // Parabolic interpolation around the dip.
  const a = cm[lag - 1] ?? cm[lag];
  const b = cm[lag];
  const c = cm[lag + 1] ?? cm[lag];
  const shift = (a - c) / (2 * (a - 2 * b + c) || 1);
  const period = lag + (Number.isFinite(shift) ? Math.max(-1, Math.min(1, shift)) : 0);
  return { hz: sampleRate / period, clarity: 1 - b };
}

export const hzToMidi = (hz) => 69 + 12 * Math.log2(hz / 440);

/** How far `midi` is from `target`, in cents, and whether it is the right
 *  note an octave off (a saxophonist overblowing, or the line moved). */
export function judge(midi, target) {
  const cents = Math.round((midi - target) * 100);
  const octaves = Math.round((midi - target) / 12);
  const inOctave = Math.round((midi - target - 12 * octaves) * 100);
  return { cents, octave: octaves !== 0 && Math.abs(inOctave) < 50 ? octaves : 0, ok: Math.abs(cents) < 50 };
}

/** The microphone, read on demand: {midi, clarity} of the latest frame. */
export class MicPitch {
  constructor(ctx) {
    this.ctx = ctx;
    this.stream = null;
    this.analyser = null;
    this.buf = new Float32Array(2048);
  }

  async start() {
    this.stream = await navigator.mediaDevices.getUserMedia({
      // A saxophone, not a call: no processing that bends or gates the tone.
      audio: { echoCancellation: false, noiseSuppression: false, autoGainControl: false },
    });
    const src = this.ctx.createMediaStreamSource(this.stream);
    this.analyser = this.ctx.createAnalyser();
    this.analyser.fftSize = this.buf.length;
    src.connect(this.analyser); // not to the speakers
  }

  stop() {
    for (const t of this.stream?.getTracks() || []) t.stop();
    this.stream = null;
    this.analyser = null;
  }

  get on() {
    return !!this.analyser;
  }

  read() {
    if (!this.analyser) return null;
    this.analyser.getFloatTimeDomainData(this.buf);
    const r = yin(this.buf, this.ctx.sampleRate);
    return r && r.clarity > 0.8 ? { midi: hzToMidi(r.hz), clarity: r.clarity } : null;
  }
}
