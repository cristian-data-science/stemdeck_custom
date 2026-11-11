"""Which transcription engine serves which stem.

piano   -> piano_transcription_inference (Kong et al., MIT): piano-specific,
           note offsets and velocities, ~0.97 note F1 on the calibration piece.
others  -> Basic Pitch (Spotify, Apache-2.0) over ONNX (basic_pitch_onnx.py):
           instrument-agnostic, limited to the stem's playable range so the
           octave above a bass note or a vocal's breath is not read as a note.

Each stem also suggests where the treble/bass split starts, so a bass line
lands on the F clef and a melody on the G clef before anyone touches it.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from pathlib import Path

from app.score.transcribe import TranscriptionError, run_transcription

# stem -> (engine, min midi, max midi, default split)
logger = logging.getLogger(__name__)

_STEMS: dict[str, tuple[str, int | None, int | None, int]] = {
    "piano": ("piano_transcription_inference", None, None, 60),
    "bass": ("basic_pitch", 23, 67, 84),  # B0..G4, all on the F clef
    "guitar": ("basic_pitch", 38, 90, 55),  # D2..F#6
    "vocals": ("basic_pitch", 40, 84, 36),  # E2..C6, all on the G clef
    "lead_vocals": ("basic_pitch", 40, 84, 36),
    "backing_vocals": ("basic_pitch", 40, 84, 36),
    "other": ("basic_pitch", None, None, 60),
}


def supports(stem: str) -> bool:
    return stem in _STEMS


def name(stem: str) -> str | None:
    entry = _STEMS.get(stem)
    return entry[0] if entry else None


def default_split(stem: str) -> int:
    entry = _STEMS.get(stem)
    return entry[3] if entry else 60


AUDIO_SOURCES = ("auto", "stem", "original")
# Presence (0-100, the job's per-stem RMS) under which a part counts as absent.
_ABSENT = 10


def choose_audio(
    stem: str, presence: dict | None, requested: str, has_original: bool
) -> tuple[str, str]:
    """("stem" | "original", why) for a transcription.

    A solo piano recording is better transcribed from the original audio than
    from Demucs' piano stem: Demucs splits a solo piano between "piano" and
    "other" (presence 100 / 91 on one), and the piano stem agreed with the
    original's transcription at only F1 0.70 there. The piano model was trained
    on solo piano, so the original is its best input when nothing else plays.
    "auto" picks the original for the piano stem when vocals, drums and bass
    are all absent; only the piano engine reads a full mix.
    """
    if stem != "piano" or not has_original:
        return "stem", "este stem se transcribe desde su propio audio"
    if requested in ("stem", "original"):
        return requested, "elegido"
    p = presence or {}
    if (
        all(p.get(k, 0) <= _ABSENT for k in ("vocals", "drums", "bass"))
        and p.get("piano", 0) > _ABSENT
    ):
        return "original", "piano solo: sin voz, batería ni bajo"
    return "stem", "hay otros instrumentos"


def device_for() -> str:
    """The GPU when the app's device setting allows one, else the CPU.

    The same setting separation uses (Settings, "auto" probes the hardware),
    not the device the job happened to be separated on: a song separated
    before a CUDA torch was installed should still transcribe on the GPU.
    MPS maps to the CPU; this model is untested there.
    """
    try:
        from app.core.settings import get_demucs_device

        return "cuda" if get_demucs_device() == "cuda" else "cpu"
    except Exception:  # noqa: BLE001 -- no device probe may stop a transcription
        logger.warning("score: device probe failed, using the CPU", exc_info=True)
        return "cpu"


def transcribe(
    stem: str,
    audio: Path,
    out: Path,
    report: Callable[[str, float], None] | None = None,
) -> None:
    if stem not in _STEMS:
        raise ValueError(f"no engine for {stem}")
    engine, lo, hi, _ = _STEMS[stem]
    kind = "piano" if engine == "piano_transcription_inference" else "basic_pitch"
    device = device_for() if kind == "piano" else "cpu"  # Basic Pitch runs ONNX on the CPU
    kwargs = {"engine": kind, "min_midi": lo, "max_midi": hi}
    try:
        run_transcription(audio, out, device, report, **kwargs)
    except TranscriptionError as e:
        if device != "cuda" or str(e) == "cancelled":
            raise
        # A GPU that cannot run it (out of memory, a driver/torch mismatch)
        # should cost speed, not the transcription.
        logger.warning("score: GPU transcription failed (%s); retrying on the CPU", e)
        if report:
            report("cpu-fallback", 0.0)
        run_transcription(audio, out, "cpu", report, **kwargs)
