"""Ghost notes: what the model writes where the audio has no attack.

The piano model re-strikes held notes when another key is struck (a bass
or an inner voice "repeated" on every eighth of the right hand), and on a
separated stem it turns bleed from the voice or the guitar into soft notes.
Neither has an attack in the audio: right after the note's start, the energy
at its partials (fundamental, octave, twelfth) does not rise.

Measured (2026-11-01, constant-Q, 10 ms): repeated notes with no rise
(< GAIN_DB) were 19 % in "Cry" (a solo piano cover, transcribed from the
original) against 4 % in Comptine (a clean recording); in Barbarossa (from the
piano stem of a song with voice) 41-48 % of the notes under velocity 45 had
none, against 3 % above 60.

Marks, does not delete: raw.json keeps every note with "ghost": "merge" (a
re-strike: its time goes back to the note it repeats) or "drop" (a soft note
with no attack). notes.json starts without them and lists them as deleted
notes, so «Notas borradas» brings any back.
"""

from __future__ import annotations

import logging
from pathlib import Path

logger = logging.getLogger(__name__)

GAIN_DB = 1.0  # less than this rise at the note's partials: no attack...
RISE_DB = 4.0  # ...and less than this from the dip just before (a damper lifting and the
# hammer striking again make a dip then a rise: a real re-strike of a ringing
# B3 in "Cry" rose 4.7-12 dB from its dip with little net gain)
SOFT_VELOCITY = 45  # a note on its own is only dropped when this soft
JOIN_SEC = 0.05  # a re-strike: the same key ended at most this long before
# Bleed (a song transcribed from its piano stem): the note is this much louder
# in another stem than in the piano's own, at its pitch. In "Barbarossa -
# Stones" the notes on the sung pitch sat a median 18.6 dB under the voice
# stem (64 % under -15 dB); the rest +20 dB (8 % under -15 dB).
BLEED_DB = -15.0
BLEED_VELOCITY = 60  # only notes softer than this
# A weak attack: the model itself barely heard an onset (its onset output
# under WEAK_ONSET) and the audio shows little rise at the note's partials
# (under WEAK_GAIN_DB). In "Cry" from 1:02 the right hand filled with soft
# re-strikes of G5, D5, F#5 between the real ones; measured over whole songs
# this marks 19 % of Cry's notes, 1.7 % of Comptine's and 0.3 % of the Valse
# d'Amélie's (clean recordings).
WEAK_ONSET = 0.6
WEAK_GAIN_DB = 4.0
SR = 44100
HOP = 441  # 10 ms
LOW_MIDI = 21


def attack_gains(notes: list[dict], audio: Path) -> list[tuple[float, float]]:
    """For each note, how much the energy at its partials rises at its start:
    (after minus before, after minus the dip around the start), in dB."""
    import librosa
    import numpy as np

    y, sr = librosa.load(str(audio), sr=SR, mono=True)
    bins = 88 + 19  # up to the twelfth of the top note
    c = np.abs(
        librosa.cqt(
            y,
            sr=sr,
            hop_length=HOP,
            fmin=librosa.midi_to_hz(LOW_MIDI),
            n_bins=bins,
            bins_per_octave=12,
        )
    )
    from scipy.ndimage import uniform_filter1d

    # 30 ms smoothing: the beating of two strings is not an attack.
    db = uniform_filter1d(librosa.amplitude_to_db(c, ref=np.max), 3, axis=1)
    frames = db.shape[1]
    out = []
    for n in notes:
        b = int(n["midi"]) - LOW_MIDI
        f = int(n["start"] * sr / HOP)
        rows = [r for r in (b, b + 12, b + 19) if 0 <= r < bins]
        if not rows or f < 6 or f + 2 >= frames:
            out.append((99.0, 99.0))
            continue
        before = db[rows, f - 6 : f - 1].max(axis=1).mean()
        after = db[rows, f + 1 : min(frames, f + 8)].max(axis=1).mean()
        dip = db[rows, f - 4 : f + 2].min(axis=1).mean()
        out.append((float(after - before), float(after - dip)))
    return out


def mark(notes: list[dict], gains: list[tuple[float, float]]) -> dict[str, int]:
    """Set "ghost" on the notes with no attack (in place). Counts."""
    order = sorted(range(len(notes)), key=lambda i: notes[i]["start"])
    last_end: dict[int, float] = {}
    merged = dropped = 0
    for i in order:
        n, (gain, rise) = notes[i], gains[i]
        n.pop("ghost", None)
        n.pop("ghost_why", None)
        prev = last_end.get(n["midi"])
        repeat = prev is not None and n["start"] - prev < JOIN_SEC
        silent = gain < GAIN_DB and rise < RISE_DB
        weak = n.get("onset") is not None and n["onset"] < WEAK_ONSET and gain < WEAK_GAIN_DB
        if weak and not silent:
            n["ghost_why"] = "weak"
            silent = True
            if not repeat:
                n["ghost"] = "drop"
                dropped += 1
                last_end[n["midi"]] = max(last_end.get(n["midi"], 0.0), n["end"])
                continue
        if silent and repeat:
            n["ghost"] = "merge"
            merged += 1
        elif silent and n.get("velocity", 80) < SOFT_VELOCITY:
            n["ghost"] = "drop"
            dropped += 1
        last_end[n["midi"]] = max(last_end.get(n["midi"], 0.0), n["end"])
    return {"merged": merged, "dropped": dropped}


def bleed_sources(stems_dir: Path, transcribed: Path) -> list[Path]:
    """The stems a stem transcription is checked against: the voice only (the
    measured case). Not the guitar or "other": Demucs often puts part of a
    keyboard there, and those notes are real."""
    voice = stems_dir / "vocals.wav"
    if transcribed.parent != stems_dir or not voice.is_file():
        return []
    return [voice]


def bleed_margins(notes: list[dict], stem: Path, others: list[Path]) -> list[float]:
    """For each note, its level in the stem it was transcribed from minus the
    loudest of the other stems at its pitch, over its first 150 ms (dB)."""
    import librosa
    import numpy as np

    def cq(path: Path):
        y, sr = librosa.load(str(path), sr=22050, mono=True)
        c = np.abs(
            librosa.cqt(y, sr=sr, hop_length=220, fmin=librosa.midi_to_hz(LOW_MIDI), n_bins=88)
        )
        return librosa.amplitude_to_db(c, ref=1.0)

    own = cq(stem)
    rest = [cq(p) for p in others]
    out = []
    for n in notes:
        b = int(n["midi"]) - LOW_MIDI
        f = int(n["start"] * 22050 / 220)
        if not 0 <= b < 88 or f >= own.shape[1]:
            out.append(99.0)
            continue
        mine = own[b, f : f + 15].max()
        loudest = max((r[b, f : f + 15].max() for r in rest if f < r.shape[1]), default=-200.0)
        out.append(float(mine - loudest))
    return out


def mark_bleed(notes: list[dict], margins: list[float]) -> int:
    """Soft notes much louder in another stem: "drop", why "bleed". Count."""
    count = 0
    for n, m in zip(notes, margins, strict=True):
        if n.get("ghost") or m >= BLEED_DB or n.get("velocity", 80) >= BLEED_VELOCITY:
            continue
        n["ghost"] = "drop"
        n["ghost_why"] = "bleed"
        count += 1
    return count


def annotate(raw: dict, audio: Path, others: list[Path] | None = None) -> dict:
    """raw.json with its ghost notes marked, and the counts in raw["ghosts"].
    `others`: the song's other stems, when `audio` is a stem (bleed check).
    Never fatal: a song without the check is still a song."""
    notes = raw.get("notes") or []
    if not notes:
        return raw
    try:
        counts = mark(notes, attack_gains(notes, audio))
        if others:
            counts["bleed"] = mark_bleed(notes, bleed_margins(notes, audio, others))
        raw["ghosts"] = {**counts, "gain_db": GAIN_DB, "soft_velocity": SOFT_VELOCITY}
    except Exception as e:  # noqa: BLE001
        logger.warning("score: ghost-note check skipped: %s", e, exc_info=True)
    return raw
