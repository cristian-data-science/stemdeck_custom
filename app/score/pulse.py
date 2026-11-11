"""The score's own beat grid, when the song's is not to be trusted.

The separation pipeline tracks beats on the drums stem (app/pipeline/beatgrid.py
_SOURCE_PREFERENCE). On a solo piano recording that stem is silence: the
neural tracker found 0 beats there, the librosa fallback invented 136 BPM with
no downbeats, and 20 % of the notes sat over 40 ms off the grid. beat_this on
the audio the score was transcribed from found 125 BPM with downbeats, and the
same notes fell to 3.8 % off. So the score tracks its own beats, on that audio,
whenever the song's grid is weak, and keeps the song's grid otherwise (a drum
track is the better beat source when there is one).
"""

from __future__ import annotations

import logging
from pathlib import Path

logger = logging.getLogger(__name__)

PULSES = ("auto", "song", "audio", "notes")
_SILENT = 10  # stem presence under which a stem is not a beat source


def song_grid_is_weak(grid: dict | None, presence: dict | None) -> str | None:
    """Why the song's beat grid should not drive this score, or None."""
    if not grid or len(grid.get("beats") or []) < 8:
        return "la canción no tiene pulso detectado"
    if grid.get("detector") != "beat_this":
        return "el pulso de la canción salió del detector de respaldo"
    if not grid.get("bars"):
        return "el pulso de la canción no tiene barras de compás"
    source = grid.get("source")
    if source in (presence or {}) and (presence or {}).get(source, 0) <= _SILENT:
        return f"el pulso de la canción salió de un stem en silencio ({source})"
    return None


def track(audio: Path) -> dict | None:
    """beat_this on `audio` -> {"beats", "bars", "bpm", "detector", ...}, or None."""
    try:
        import librosa

        from app.pipeline.beat_detect import _get_model
        from app.pipeline.beatgrid import _downbeats_to_bars

        model = _get_model()
        if model is None:
            return None
        y, sr = librosa.load(str(audio), sr=22050, mono=True)
        beats, downbeats = model(y, sr)
        beats = sorted(float(b) for b in beats if b >= 0)
        downbeats = sorted(float(d) for d in downbeats if d >= 0)
        if len(beats) < 8:
            return None
        intervals = sorted(b - a for a, b in zip(beats, beats[1:], strict=False))
        typical = intervals[len(intervals) // 2]
        return {
            "version": 1,
            "detector": "beat_this",
            "source": "score-audio",
            "audio": audio.name,
            "beats": [round(b, 6) for b in beats],
            "bars": _downbeats_to_bars(beats, downbeats) if len(downbeats) >= 2 else [],
            "bpm": round(60 / typical, 3) if typical > 0 else None,
        }
    except Exception:  # noqa: BLE001 -- a missing grid falls back to the song's
        logger.warning("score: beat tracking on %s failed", audio, exc_info=True)
        return None


def track_notes(notes: list[dict]) -> dict | None:
    """Beats from the transcribed note onsets themselves.

    A piano transcription's onsets are sharper than any audio onset curve,
    and expressive solo piano is where audio beat trackers drift: on La Valse
    d'Amelie the audio grid wandered between 0.8x and 2.3x its own beat (13 %
    of notes off it) while onsets, low notes weighted up, gave a steady
    182 BPM waltz pulse with 1 % off. librosa's tracker on that envelope.
    """
    try:
        import librosa
        import numpy as np

        if len(notes) < 16:
            return None
        fps = 100
        env = np.zeros(int((max(n["end"] for n in notes) + 2) * fps))
        for n in notes:
            env[int(n["start"] * fps)] += (n.get("velocity", 80) / 127) * (
                1.0 + max(0, 60 - n["midi"]) / 24
            )
        env = np.convolve(env, np.hanning(7), mode="same")
        _tempo, beats = librosa.beat.beat_track(
            onset_envelope=env, sr=fps, hop_length=1, units="time", tightness=100
        )
        beats = sorted(float(b) for b in beats)
        if len(beats) < 8:
            return None
        intervals = sorted(b - a for a, b in zip(beats, beats[1:], strict=False))
        return {
            "version": 1,
            "detector": "notes",
            "source": "score-notes",
            "beats": [round(b, 6) for b in beats],
            "bars": [],
            "bpm": round(60 / intervals[len(intervals) // 2], 3),
        }
    except Exception:  # noqa: BLE001
        logger.warning("score: beat tracking on the notes failed", exc_info=True)
        return None


def regularity(grid: dict | None) -> float:
    """Spread of the beat intervals once half-tempo stretches are filled in
    (coefficient of variation): lower is steadier. inf when unusable."""
    from app.score.timegrid import regularize

    beats = sorted((grid or {}).get("beats") or [])
    if len(beats) < 8:
        return float("inf")
    reg, _ = regularize(beats)
    iv = [b - a for a, b in zip(reg, reg[1:], strict=False)]
    mean = sum(iv) / len(iv)
    return (sum((x - mean) ** 2 for x in iv) / len(iv)) ** 0.5 / mean if mean > 0 else float("inf")


def choose(
    song: dict | None,
    own: dict | None,
    presence: dict | None,
    setting: str,
    notes_grid: dict | None = None,
) -> tuple[dict | None, str, str | None]:
    """(grid, "song" | "audio" | "notes", why) for this score.

    When the song's grid is weak, the steadier of the two grids tracked for
    this score wins (on four solo piano pieces the notes' grid was steadier
    every time: CV 0.06-0.09 against 0.11-0.19)."""
    if setting == "audio" and own:
        return own, "audio", "elegido"
    if setting == "notes" and notes_grid:
        return notes_grid, "notes", "elegido"
    if setting == "song" and song:
        return song, "song", "elegido"
    weak = song_grid_is_weak(song, presence)
    if weak:
        candidates = [
            (regularity(g), name, g) for name, g in (("audio", own), ("notes", notes_grid)) if g
        ]
        if candidates:
            _, name, grid = min(candidates, key=lambda c: c[0])
            return grid, name, weak
    return song, "song", None if song else "sin pulso"
