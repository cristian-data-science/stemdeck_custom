"""Songs that are not tuned to A440, brought to it before transcription.

"Slowed" and "sped up" uploads play a recording at another speed, which moves
every pitch by a fraction of a semitone. Graham Coxon's "Saturday Night
(slowed)" sits 38 cents sharp: each note lies 0.4 semitone above a piano key,
and the piano model, trained on A440, read G5 as G#5 or as F5 + G#5 and
found 60 % of the stem's strong pitches. Played 2.2 % slower first (so 38
cents lower), the same model found 98 % of them, and the chords under them.

The offset is measured from the strong spectral peaks: the circular mean of
each peak's distance to the nearest equal-tempered note (a peak at +0.45 and
one at -0.55 agree). librosa.estimate_tuning said -8 cents on that song and is
not used. Tuned recordings measure within a few cents (the Tiersen pieces
+3..+6, a band song -2), well under the threshold.

The correction is a resampling, not a pitch shifter: the audio is played
slower or faster as a whole, so nothing is smeared, and the transcribed times
are scaled back to the song's own clock.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

import numpy as np

logger = logging.getLogger(__name__)

THRESHOLD_CENTS = 15.0  # below this, the model reads the notes right anyway
MIN_CONSISTENCY = 0.4  # how much the peaks agree (1 = all at the same offset)
ANALYSIS_SR = 22050


@dataclass
class Retune:
    path: Path  # the audio to transcribe
    ratio: float  # transcribed times / song times (1 = untouched)
    cents: float | None  # measured offset from A440
    consistency: float | None
    corrected: bool


def estimate_offset(y: np.ndarray, sr: int) -> tuple[float, float]:
    """(offset in semitones within -0.5..0.5, consistency 0..1)."""
    import librosa

    n, hop = 8192, 4096
    if len(y) < n:
        return 0.0, 0.0
    spec = np.abs(librosa.stft(y, n_fft=n, hop_length=hop))
    freqs = np.fft.rfftfreq(n, 1 / sr)
    band = (freqs > 80) & (freqs < 2500)
    loudest = spec[band].max() if band.any() else 0.0
    if loudest <= 0:
        return 0.0, 0.0
    angles: list[float] = []
    weights: list[float] = []
    inner = band[1:-1]
    for col in spec.T:
        top = col[band].max()
        if top < 1e-3 * loudest:
            continue  # silence
        mid = col[1:-1]
        peaks = np.where(inner & (mid > col[:-2]) & (mid >= col[2:]) & (mid > 0.1 * top))[0] + 1
        for i in peaks:
            a, b, c = np.log(col[i - 1] + 1e-12), np.log(col[i] + 1e-12), np.log(col[i + 1] + 1e-12)
            den = a - 2 * b + c
            frac = 0.5 * (a - c) / den if den else 0.0  # parabolic interpolation
            midi = float(librosa.hz_to_midi((i + frac) * sr / n))
            angles.append(2 * np.pi * (midi - round(midi)))
            weights.append(float(col[i]))
    if not angles:
        return 0.0, 0.0
    w = np.asarray(weights)
    z = np.sum(w * np.exp(1j * np.asarray(angles))) / w.sum()
    return float(np.angle(z) / (2 * np.pi)), float(abs(z))


def prepare(audio: Path, workdir: Path) -> Retune:
    """The audio to transcribe: `audio` itself, or a copy brought to A440."""
    untouched = Retune(audio, 1.0, None, None, False)
    try:
        import librosa
        import soundfile as sf

        y, sr = librosa.load(str(audio), sr=None, mono=True)
        small = librosa.resample(y, orig_sr=sr, target_sr=ANALYSIS_SR) if sr != ANALYSIS_SR else y
        offset, consistency = estimate_offset(small, ANALYSIS_SR)
    except Exception as e:  # noqa: BLE001 -- unreadable here: let the model try as before
        logger.warning("score: tuning not measured for %s: %s", audio, e)
        return untouched
    cents = round(offset * 100, 1)
    if abs(cents) < THRESHOLD_CENTS or consistency < MIN_CONSISTENCY:
        return Retune(audio, 1.0, cents, round(consistency, 2), False)
    # Played at sr after resampling to sr * ratio: longer by `ratio`, lower
    # by `offset` semitones.
    ratio = float(2 ** (offset / 12))
    shifted = librosa.resample(y, orig_sr=sr, target_sr=int(round(sr * ratio)))
    out = workdir / "tuned_input.wav"
    sf.write(str(out), shifted, sr)
    logger.info("score: %s is %+.1f cents from A440; transcribing it retuned", audio.name, cents)
    return Retune(out, ratio, cents, round(consistency, 2), True)


def restore(raw: dict, retune: Retune) -> dict:
    """Transcribed times back on the song's clock, and what was done."""
    if retune.corrected and retune.ratio != 1.0:
        k = 1 / retune.ratio
        for key in ("notes", "pedals"):
            for item in raw.get(key) or []:
                item["start"] = round(item["start"] * k, 4)
                item["end"] = round(item["end"] * k, 4)
    raw["tuning"] = {
        "cents": retune.cents,
        "consistency": retune.consistency,
        "corrected": retune.corrected,
    }
    return raw
