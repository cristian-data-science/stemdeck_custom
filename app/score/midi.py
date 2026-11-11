"""Notes -> Standard MIDI File with the song's real tempo map.

Every beat of the grid is one MIDI quarter note, with a tempo event per beat,
so the file plays back in the song's own time (it lines up with the audio
from second 0) *and* its beats line up with the score in any DAW. The time
before the first beat is one lead-in quarter whose tempo makes it last
exactly that long.
"""

from __future__ import annotations

import io
import math

import mido

from app.score.engrave import STAFF_TREBLE, Engraved
from app.score.timegrid import TPB

PPQ = 480
MAX_QUARTER_SEC = 16.0  # under MIDI's largest tempo (0xFFFFFF us per quarter)


class _Clock:
    def __init__(self, beats: list[float]) -> None:
        self.beats = beats
        self.j0 = next((j for j, b in enumerate(beats) if b >= 0), len(beats) - 2)
        self.lead_sec = beats[self.j0]
        # One lead-in quarter, or more when the first beat comes late: a MIDI
        # tempo is at most 16.7 s per quarter, and a song whose pulse starts
        # after that ("1st": 17 s of free intro) could not be exported at all.
        self.lead_quarters = max(1, math.ceil(self.lead_sec / MAX_QUARTER_SEC))
        self.lead = PPQ * self.lead_quarters if self.lead_sec > 0.001 else 0

    def tick(self, pos_beats: float, t_sec: float) -> int:
        """MIDI tick of a grid position (in beats) that falls at t_sec."""
        if t_sec < self.lead_sec and self.lead:
            return max(0, round(t_sec / self.lead_sec * self.lead))
        return max(0, round((pos_beats - self.j0) * PPQ) + self.lead)


BEND_RANGE_CENTS = 200  # the General MIDI default (+-2 semitones); Pianoteq follows it


def to_midi(
    eng: Engraved, notes: list[dict], *, quantized: bool = False, cents: float = 0.0
) -> bytes:
    """`cents`: tune the playback that far from A440 with a pitch bend at the
    start of each track (to play along with a song that is not at A440)."""
    grid = eng.grid
    clock = _Clock(grid.beats)
    mid = mido.MidiFile(type=1, ticks_per_beat=PPQ)

    meta = mido.MidiTrack()
    mid.tracks.append(meta)
    events: list[tuple[int, int, mido.MetaMessage]] = []
    if clock.lead:
        per_quarter = clock.lead_sec / clock.lead_quarters
        events.append((0, 0, mido.MetaMessage("set_tempo", tempo=int(per_quarter * 1_000_000))))
    for j in range(clock.j0, len(grid.beats) - 1):
        span = grid.beats[j + 1] - grid.beats[j]
        tick = (j - clock.j0) * PPQ + clock.lead
        tempo = min(0xFFFFFF, max(1, int(span * 1_000_000)))
        events.append((tick, 0, mido.MetaMessage("set_tempo", tempo=tempo)))
    for m in grid.measures:
        if m.start_beat >= clock.j0 and m.n_beats == m.meter:
            tick = (m.start_beat - clock.j0) * PPQ + clock.lead
            events.append(
                (tick, 1, mido.MetaMessage("time_signature", numerator=m.meter, denominator=4))
            )
    events.sort(key=lambda e: (e[0], e[1]))
    last = 0
    for tick, _, msg in events:
        msg.time = tick - last
        meta.append(msg)
        last = tick

    def tick_of_sec(t: float) -> int:
        idx, frac = grid.locate(t)
        return clock.tick(idx + frac, t)

    info = eng.notes
    for name, want_treble in (("Mano derecha", True), ("Mano izquierda", False)):
        track = mido.MidiTrack()
        mid.tracks.append(track)
        track.append(mido.MetaMessage("track_name", name=name, time=0))
        if cents:
            bend = round(max(-1.0, min(1.0, cents / BEND_RANGE_CENTS)) * 8191)
            track.append(mido.Message("pitchwheel", pitch=bend, time=0))
        msgs = []
        for n in notes:
            placed = info.get(n["id"])
            if placed is None or (placed["staff"] == STAFF_TREBLE) != want_treble:
                continue
            if quantized:
                on = clock.tick(placed["on"] / TPB, grid.sec_at(placed["on"]))
                off = clock.tick(placed["draw_off"] / TPB, grid.sec_at(placed["draw_off"]))
            else:
                on = tick_of_sec(n["start"])
                off = tick_of_sec(n["end"])
            off = max(off, on + 1)
            vel = int(n.get("velocity", 80))
            msgs.append((on, 1, mido.Message("note_on", note=n["midi"], velocity=vel)))
            msgs.append((off, 0, mido.Message("note_off", note=n["midi"], velocity=0)))
        msgs.sort(key=lambda e: (e[0], e[1]))
        last = 0
        for tick, _, msg in msgs:
            msg.time = tick - last
            track.append(msg)
            last = tick
    buf = io.BytesIO()
    mid.save(file=buf)
    return buf.getvalue()


PERF_PPQ = 960
PERF_TEMPO = 500_000  # 120 BPM: a tick is 1/1920 s, the notes keep their seconds


def performance_midi(
    notes: list[dict], treble: dict[str, bool], *, cents: float = 0.0, speed: float = 1.0
) -> bytes:
    """The notes as heard, for Pianoteq to render: one fixed tempo and the
    notes at their own seconds (divided by `speed`: a render for practising
    slower, played back at its own rate instead of stretched by the browser).

    Only what is heard is in the file -- no tempo map, no time signatures --
    so a setting that redraws the score without changing a note (the meter,
    the bars) gives the same bytes, and the same render: with the song's
    tempo map in it, changing «Compás» re-rendered a whole song for an
    identical sound. `treble`: note id -> right hand (its staff)."""
    scale = 1.0 / max(0.1, speed)
    mid = mido.MidiFile(type=1, ticks_per_beat=PERF_PPQ)
    meta = mido.MidiTrack()
    meta.append(mido.MetaMessage("set_tempo", tempo=PERF_TEMPO, time=0))
    mid.tracks.append(meta)
    per_sec = PERF_PPQ * 1_000_000 / PERF_TEMPO
    for name, want_treble in (("Mano derecha", True), ("Mano izquierda", False)):
        track = mido.MidiTrack()
        mid.tracks.append(track)
        track.append(mido.MetaMessage("track_name", name=name, time=0))
        if cents:
            bend = round(max(-1.0, min(1.0, cents / BEND_RANGE_CENTS)) * 8191)
            track.append(mido.Message("pitchwheel", pitch=bend, time=0))
        msgs = []
        for n in notes:
            if treble.get(n["id"], True) != want_treble:
                continue
            on = max(0, round(n["start"] * scale * per_sec))
            off = max(on + 1, round(n["end"] * scale * per_sec))
            vel = max(1, min(127, int(n.get("velocity", 80))))
            msgs.append((on, 1, n["midi"], mido.Message("note_on", note=n["midi"], velocity=vel)))
            msgs.append((off, 0, n["midi"], mido.Message("note_off", note=n["midi"], velocity=0)))
        msgs.sort(key=lambda e: (e[0], e[1], e[2]))
        last = 0
        for tick, _, _, msg in msgs:
            msg.time = tick - last
            track.append(msg)
            last = tick
    buf = io.BytesIO()
    mid.save(file=buf)
    return buf.getvalue()
