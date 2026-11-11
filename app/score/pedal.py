"""How long each note sounds in playback, with and without the sustain pedal.

Without the pedal a note sounds until the key came up, as the model heard it
(sound_ends). Not until its drawn end: a staff is drawn as one voice, so a
held note is drawn only up to the next onset of its hand, and playing that
cut 40-55 % of the notes of the Tiersen pieces to less than half of what the
pianist held (a Comptine arpeggio heard 0.6 s each sounded 0.09-0.26 s).
The drawn end is used only where the model never heard the release: it caps
those at 6 s, and such tails sounded on for bars under half notes.

The piano model hears the pianist's sustain pedal (raw.json "pedals", down/up
times) apart from the keys, so the notes end where the key came up. With the
pedal fully applied a note rings on until the pedal comes up after its
release; the slider takes a share of that: 0 % is the notes as the pianist held them, 100 %
the pianist's pedal, 40 % each note rings 40 % of the way to it.

Lengthening notes, not sending the pedal itself (MIDI CC64), on purpose:
Pianoteq's half pedal is not proportional (in a test nothing up to ~30 %,
partial at 50 %, all of it from ~75 %), and the page's synth has no pedal.
This way both play the same thing.

Without the pianist's pedal (the calibration, a stem from Basic Pitch) the
pedal is changed at every chord, as a pianist would.
"""

from __future__ import annotations

PEDAL_GAP = 0.03  # pedal changes this long before the next chord (and after it)
UNHEARD_SEC = 5.9  # the piano model caps a release it never heard at 6 s


def sound_ends(notes: list[dict], drawn_ends: dict[str, float]) -> dict[str, float]:
    """note id -> where it stops sounding without pedal: its heard release,
    or its drawn end when the release was never heard; never past the next
    strike of the same key."""
    by_pitch: dict[int, list[float]] = {}
    for n in notes:
        by_pitch.setdefault(n["midi"], []).append(n["start"])
    for v in by_pitch.values():
        v.sort()
    out: dict[str, float] = {}
    for n in notes:
        drawn = drawn_ends.get(n["id"], n["end"])
        # A length the user set ("held") is meant, however long.
        end = drawn if n["end"] - n["start"] >= UNHEARD_SEC and not n.get("held") else n["end"]
        again = next((s for s in by_pitch[n["midi"]] if s > n["start"] + 1e-6), None)
        if again is not None:
            end = min(end, again)
        out[n["id"]] = round(max(end, n["start"] + 0.01), 4)
    return out


def segments(raw_pedals: list[dict] | None, chord_times: list[float]) -> tuple[list, str]:
    """[(down, up)] in seconds, sorted, and where they came from."""
    found = sorted(
        (float(p["start"]), float(p["end"]))
        for p in raw_pedals or []
        if isinstance(p, dict) and float(p.get("end", 0)) > float(p.get("start", 0))
    )
    if found:
        return found, "transcription"
    times = sorted(chord_times)
    segs = [
        (a + PEDAL_GAP, b - PEDAL_GAP)
        for a, b in zip(times, times[1:], strict=False)
        if b - a > 2 * PEDAL_GAP
    ]
    if times:
        segs.append((times[-1] + PEDAL_GAP, times[-1] + 4.0))
    return segs, "chords" if segs else "none"


def full_hold(notes: list[dict], segs: list[tuple[float, float]]) -> dict[str, float | None]:
    """note id -> where it stops with the pedal fully down (None: the pedal
    does not hold it). `notes` end where they sound (sound_ends). A key
    struck again cuts its own ringing."""
    starts_by_pitch: dict[int, list[float]] = {}
    for n in notes:
        starts_by_pitch.setdefault(n["midi"], []).append(n["start"])
    for v in starts_by_pitch.values():
        v.sort()
    out: dict[str, float | None] = {}
    j = 0
    ordered = sorted(notes, key=lambda n: n["end"])
    for n in ordered:
        end = n["end"]
        while j < len(segs) and segs[j][1] <= end:
            j += 1
        held = None
        if j < len(segs) and segs[j][0] <= end < segs[j][1]:
            held = segs[j][1]
            again = next((s for s in starts_by_pitch[n["midi"]] if s > n["start"] + 1e-6), None)
            if again is not None:
                held = min(held, again)
            if held <= end:
                held = None
        out[n["id"]] = round(held, 4) if held is not None else None
    return out


def held_end(end: float, full: float | None, pct: int) -> float:
    """Where a note drawn to `end` stops with the slider at pct %."""
    if full is None or pct <= 0:
        return end
    return end + (full - end) * min(pct, 100) / 100
