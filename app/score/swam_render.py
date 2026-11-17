"""«🎷 Saxo» played by SWAM Saxophones (Audio Modeling, physical modelling):
a line rendered offline, as Pianoteq renders a score.

Run apart from the app, in its own environment with DawDreamer (it hosts
the plugin; a plugin that crashes takes this process down, not the server):

    .run/tools/swam-venv/Scripts/python.exe -I app/score/swam_render.py in.json out.flac

in.json: {"plugin": path to the SWAM .dll/.vst3, "duration": s, "cents": the
song's tuning, "notes": [{"start", "end", "midi" (concert), "velocity",
"legato", "curve": {"step", "midi": [...], "level": [...]} | absent}],
"octave": semitones added to every note (12 for SWAM's tenor and baritone),
"params": {a SWAM parameter's name: its value 0..1} set before rendering}.
Prints progress lines ("progress 0.42") and writes a 44.1 kHz FLAC.

How a line becomes a performance:
- a slurred note (`legato`) starts before the previous one ends: SWAM plays
  the transition (no new attack) as a saxophonist slurs;
- Expression (CC11) is the breath, kept even: one level a note (the line's
  loudness there, `curve.level` or the velocity, pulled most of the way to
  the line's middle) and one shape every note (a short swell in, unless
  slurred, then settling a little). The level read from a separated stem
  moves with whatever else is in it (pads, reverb): followed frame by frame
  it made the breath wobble inside a note and the same note louder or
  airier each time (Careless Whisper: CC11 jumping 12-32 steps in 20 ms,
  one note between 67 and 127);
- the pitch bend (±2 semitones) carries the song's tuning and, with a curve,
  the slides and vibrato of the line as played, cleaned of the tracker's
  noise (a frame more than a semitone off past the attack is dropped, a
  3-frame median and a light smoothing, ±half a semitone past the attack);
  SWAM's own vibrato is then off.
Measured on SWAM Saxophones 3 (Windows VST2): alto and soprano sound at
concert pitch (69 = A4), tenor and baritone an octave below the note sent
(57 sounded at 110 Hz, its harmonics 219/548/657 Hz: sent 12 higher);
"Pitch Bend Up/Down" 1/24 = ±2 semitones; ~20x realtime (4:18 in 15 s).
"""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

SR = 44100
BLOCK = 256
BEND_RANGE = 2.0  # semitones each way ("Pitch Bend Up/Down" = 1/24)
TICKS = 960  # per second (480 per beat at 120 bpm)
CC_STEP = 0.02  # s between controller points
EVEN = 0.2  # how much of a note's own loudness is kept against the line's middle
ATTACK = 0.1  # s at a note's start where a scoop may go up to ±2 semitones
BODY_BEND = 0.5  # semitones the pitch may move past the attack (vibrato, bends)


def _level_cc(level: float) -> int:
    return max(1, min(127, round(28 + 99 * min(1.0, level * 1.2))))


def _median(xs: list[float]) -> float:
    xs = sorted(xs)
    k = len(xs) // 2
    return xs[k] if len(xs) % 2 else (xs[k - 1] + xs[k]) / 2


def _note_level(n: dict) -> float:
    """A note's breath (CC11) before evening: its loudness as played."""
    curve = n.get("curve")
    if curve and curve.get("level"):
        return float(_level_cc(_median([float(x) for x in curve["level"]])))
    return 50 + 0.6 * max(30, min(127, int(n.get("velocity") or 80)))


def _clean_bend(curve: dict, centre: float) -> list[float]:
    """The curve (absolute MIDI, as tracked) as semitones off the note as
    tuned (`centre`: the note plus the song's tuning), the tracker's noise
    taken out."""
    step = float(curve["step"])
    raw: list[float] = []
    last = 0.0
    for k, m in enumerate(curve["midi"]):
        x = float(m) - centre if m is not None else last
        if k * step >= ATTACK and abs(x) > 1.0:
            x = last  # a jump to a neighbour or an octave: the tracker, not the player
        raw.append(x)
        last = x
    med = [_median(raw[max(0, k - 1) : k + 2]) for k in range(len(raw))]
    out = []
    for k in range(len(med)):
        a, b, c = med[max(0, k - 1)], med[k], med[min(len(med) - 1, k + 1)]
        x = 0.25 * a + 0.5 * b + 0.25 * c
        lim = BEND_RANGE if k * step < ATTACK else BODY_BEND
        out.append(max(-lim, min(lim, x)))
    return out


def events(data: dict) -> list[tuple[float, list[int]]]:
    """(time s, MIDI bytes) for the whole line, sorted."""
    cents = float(data.get("cents") or 0.0) / 100.0
    octave = int(data.get("octave") or 0)
    notes = sorted(data["notes"], key=lambda n: n["start"])
    out: list[tuple[float, list[int]]] = []

    def cc(t: float, num: int, val: int) -> None:
        out.append((t, [0xB0, num, max(0, min(127, int(val)))]))

    def bend(t: float, semis: float) -> None:
        v = max(-8192, min(8191, round(semis / BEND_RANGE * 8192)))
        v += 8192
        out.append((t, [0xE0, v & 0x7F, (v >> 7) & 0x7F]))

    bend(0.0, cents)
    cc(0.0, 11, 0)
    # The breath: one level a note, near the line's middle.
    levels = [_note_level(n) for n in notes]
    middle = max(90.0, min(112.0, _median(levels))) if levels else 100.0
    breath = [max(70.0, min(122.0, middle + EVEN * (lv - middle))) for lv in levels]
    for i, n in enumerate(notes):
        start, end, midi = float(n["start"]), float(n["end"]), int(n["midi"])
        sent = midi + octave  # the key SWAM is asked for (the bend stays against `midi`)
        if end <= start:
            continue
        # The attack, evened like the breath.
        vel = round(max(60.0, min(110.0, 90 + EVEN * (int(n.get("velocity") or 90) - 90))))
        nxt = notes[i + 1] if i + 1 < len(notes) else None
        slur_next = bool(nxt and nxt.get("legato") and nxt["start"] - end < 0.05)
        curve = n.get("curve")
        # The breath: the same shape every note, a swell in (none when
        # slurred: the air goes on), then settling a little.
        level = breath[i]
        slurred = bool(n.get("legato")) and i > 0 and start - float(notes[i - 1]["end"]) < 0.05
        dur = end - start
        k = 0
        while start + k * CC_STEP < end:
            t = k * CC_STEP
            swell = 1.0 if slurred else 0.72 + 0.28 * min(1.0, t / 0.06)
            settle = 1 - 0.06 * min(1.0, t / max(dur, 0.3))
            cc(start + t, 11, round(level * swell * settle))
            k += 1
        # The pitch: the song's tuning, and the curve as played (cleaned).
        if curve and curve.get("midi"):
            step = float(curve["step"])
            for k, x in enumerate(_clean_bend(curve, midi + cents)):
                t = start + k * step
                if t >= end:
                    break
                bend(t, max(-BEND_RANGE, min(BEND_RANGE, x + cents)))
        else:
            bend(start, cents)
        out.append((start, [0x90, sent, vel]))
        # Slurred into the next: this one ends just after that one starts
        # (SWAM hears the overlap as a legato transition).
        off = nxt["start"] + 0.02 if slur_next else end
        out.append((off, [0x80, sent, 64]))
        if not slur_next:
            # The breath stops, between this note and the next: never inside
            # the next (one starting right after had a hole of no air in it,
            # heard as a cut and a knock, e.g. after a note made longer).
            gap = (float(nxt["start"]) - end) if nxt else 1.0
            if gap > 0.06:
                cc(end + min(0.12, gap / 2), 11, 0)
    out.sort(key=lambda e: (e[0], e[1][0] == 0x90))  # note-offs before note-ons at one time
    return out


def write_midi(evts: list[tuple[float, list[int]]], path: Path) -> None:
    import mido

    mid = mido.MidiFile(ticks_per_beat=480)
    tr = mido.MidiTrack()
    mid.tracks.append(tr)
    tr.append(mido.MetaMessage("set_tempo", tempo=500000))
    last = 0
    for t, b in evts:
        tick = max(last, int(round(t * TICKS)))
        msg = mido.Message.from_bytes(b)
        msg.time = tick - last
        last = tick
        tr.append(msg)
    mid.save(str(path))


def render(data: dict, out: Path) -> None:
    import dawdreamer as daw
    import numpy as np
    import soundfile as sf

    eng = daw.RenderEngine(SR, BLOCK)
    sax = eng.make_plugin_processor("sax", data["plugin"])
    idx = {p["name"]: p["index"] for p in sax.get_parameters_description()}

    def setp(name: str, v: float) -> None:
        if name in idx:
            sax.set_parameter(idx[name], v)

    setp("Pitch Bend Up", 1 / 24)
    setp("Pitch Bend Down", 1 / 24)
    expressive = any(n.get("curve") for n in data["notes"])
    setp("Vibrato Depth", 0.0 if expressive else 0.25)  # the singer's own vibrato, or SWAM's
    # The plugin's settings for this render (app/score/swam.py plugin_params:
    # its name in SWAM -> its value, 0..1).
    for name, value in (data.get("params") or {}).items():
        setp(name, float(value))
    duration = float(data["duration"])
    with tempfile.TemporaryDirectory() as tmp:
        mid = Path(tmp) / "line.mid"
        write_midi(events(data), mid)
        sax.load_midi(str(mid), clear_previous=True, beats=False, all_events=True)
        eng.load_graph([(sax, [])])
        # One pass (the plugin's state carries through the whole line);
        # progress is only an estimate from the render speed.
        print("progress 0.05", flush=True)
        eng.render(duration)
        audio = eng.get_audio().T
    peak = float(np.abs(audio).max()) or 1.0
    audio = audio * (0.89 / peak)
    tmp_out = out.with_name(f".{out.name}.part.flac")
    sf.write(str(tmp_out), audio.astype("float32"), SR, format="FLAC")
    tmp_out.replace(out)
    print("progress 1.0", flush=True)


if __name__ == "__main__":
    data = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
    render(data, Path(sys.argv[2]))
