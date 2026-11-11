"""Tuning: songs off A440 ("slowed" uploads) are transcribed brought to it."""

from __future__ import annotations

import numpy as np
import pytest
import soundfile as sf

from app.score import tuning

SR = 22050


def _tones(cents: float, seconds: float = 6.0) -> np.ndarray:
    """A few piano-like notes (harmonics, decay) detuned by `cents`."""
    t = np.arange(int(SR * seconds)) / SR
    y = np.zeros_like(t)
    for k, midi in enumerate((60, 64, 67, 72, 65, 69)):
        f0 = 440 * 2 ** ((midi - 69 + cents / 100) / 12)
        start = k * 0.9
        env = np.where(t >= start, np.exp(-(t - start) * 2.5), 0.0)
        for h, amp in ((1, 1.0), (2, 0.5), (3, 0.25)):
            y += amp * env * np.sin(2 * np.pi * f0 * h * (t - start))
    return (0.2 * y / np.abs(y).max()).astype(np.float32)


@pytest.mark.parametrize("cents", [-40, -20, 0, 7, 25, 38, 45])
def test_offset_is_measured_in_cents(cents):
    offset, consistency = tuning.estimate_offset(_tones(cents), SR)
    assert offset * 100 == pytest.approx(cents, abs=4)
    assert consistency > 0.8


def test_a_detuned_song_is_retuned_and_its_times_restored(tmp_path):
    src = tmp_path / "song.wav"
    sf.write(src, _tones(38), SR)
    r = tuning.prepare(src, tmp_path)
    assert r.corrected and r.path != src and r.cents == pytest.approx(38, abs=4)
    y, sr = sf.read(r.path)
    assert sr == SR and len(y) == pytest.approx(len(_tones(38)) * r.ratio, rel=1e-3)
    offset, _ = tuning.estimate_offset(y.astype(np.float32), SR)
    assert abs(offset * 100) < 4  # now on A440
    # A note found at 2 s in the slower copy is at 2 / ratio s in the song.
    raw = tuning.restore({"notes": [{"start": 2.0, "end": 3.0}], "pedals": []}, r)
    assert raw["notes"][0]["start"] == pytest.approx(2.0 / r.ratio, abs=1e-4)
    assert raw["tuning"]["corrected"] is True


def test_a_tuned_song_is_left_alone(tmp_path):
    src = tmp_path / "song.wav"
    sf.write(src, _tones(6), SR)
    r = tuning.prepare(src, tmp_path)
    assert not r.corrected and r.path == src and r.ratio == 1.0
    raw = tuning.restore({"notes": [{"start": 2.0, "end": 3.0}]}, r)
    assert raw["notes"][0]["start"] == 2.0 and raw["tuning"]["corrected"] is False


def test_unreadable_audio_is_transcribed_as_before(tmp_path):
    src = tmp_path / "bad.wav"
    src.write_bytes(b"RIFF0000WAVE")
    r = tuning.prepare(src, tmp_path)
    assert r.path == src and not r.corrected and r.cents is None
