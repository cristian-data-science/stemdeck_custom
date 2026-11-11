// Score view: a MIDI keyboard plugged into this computer (Web MIDI: Chrome,
// Edge, the desktop app). Every key pressed and released reaches
// onNote(midi, velocity) / onNote(midi, 0); the keys held now are in `down`.
// Nothing is asked of the browser until the player presses «Teclado MIDI».

export class MidiInput {
  constructor({ onNote, onChange } = {}) {
    this.onNote = onNote || (() => {});
    this.onChange = onChange || (() => {});
    this.access = null;
    this.down = new Map(); // midi -> velocity
    this.sustain = false;
  }

  static get supported() {
    return typeof navigator !== "undefined" && typeof navigator.requestMIDIAccess === "function";
  }

  /** Names of the keyboards connected now. */
  get devices() {
    if (!this.access) return [];
    return [...this.access.inputs.values()].filter((i) => i.state !== "disconnected").map((i) => i.name || "Teclado MIDI");
  }

  async connect() {
    if (!MidiInput.supported) throw new Error("este navegador no permite teclados MIDI (usa Chrome o Edge)");
    if (!this.access) {
      this.access = await navigator.requestMIDIAccess({ sysex: false });
      this.access.onstatechange = () => {
        this._wire();
        this.onChange(this.devices);
      };
    }
    this._wire();
    this.onChange(this.devices);
    return this.devices;
  }

  disconnect() {
    if (!this.access) return;
    for (const input of this.access.inputs.values()) input.onmidimessage = null;
    for (const m of [...this.down.keys()]) this.onNote(m, 0);
    this.down.clear();
    this.access.onstatechange = null;
    this.access = null;
    this.onChange([]);
  }

  _wire() {
    for (const input of this.access.inputs.values()) input.onmidimessage = (e) => this._message(e.data);
  }

  _message(data) {
    const [status, a = 0, b = 0] = data;
    const kind = status & 0xf0;
    if (kind === 0x90 && b > 0) {
      this.down.set(a, b);
      this.onNote(a, b);
    } else if (kind === 0x80 || (kind === 0x90 && b === 0)) {
      if (!this.down.has(a)) return;
      this.down.delete(a);
      this.onNote(a, 0);
    } else if (kind === 0xb0 && a === 64) {
      this.sustain = b >= 64;
    }
  }
}
