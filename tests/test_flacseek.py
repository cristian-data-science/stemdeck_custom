"""A seek table for FLAC files written without one (app/score/flacseek.py)."""

from __future__ import annotations

import shutil
import subprocess

import numpy as np
import pytest
import soundfile as sf

from app.score import flacseek

pytestmark = pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg not on PATH")


def _flac(tmp_path, seconds=12.0, name="a.flac"):
    """A FLAC as the app makes them (ffmpeg, which writes no seek table)."""
    sr = 44100
    t = np.arange(int(sr * seconds)) / sr
    noise = np.random.default_rng(1).normal(0, 0.05, t.size)
    audio = 0.3 * np.sin(2 * np.pi * 220 * t) + noise
    wav = tmp_path / "a.wav"
    sf.write(wav, np.stack([audio, audio * 0.5], axis=1), sr)
    out = tmp_path / name
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", str(wav), "-c:a", "flac", str(out)], check=True)
    return out


def test_a_flac_without_one_gets_a_seek_table_and_the_audio_is_unchanged(tmp_path):
    path = _flac(tmp_path)
    assert not flacseek.has_seektable(path)
    before, sr = sf.read(path, dtype="int32")
    assert flacseek.add_seektable(path)
    assert flacseek.has_seektable(path)
    after, _ = sf.read(path, dtype="int32")
    assert np.array_equal(before, after)
    # One point a second, each at a real frame header, the samples in order.
    data = path.read_bytes()
    blocks, first = flacseek._metadata(data)
    table = next(b for k, b in blocks if k == flacseek.SEEKTABLE)
    points = [(int.from_bytes(table[o : o + 8], "big"), int.from_bytes(table[o + 8 : o + 16], "big")) for o in range(0, len(table), 18)]
    assert len(points) == 12
    assert points[0] == (0, 0)
    assert all(data[first + off] == 0xFF and data[first + off + 1] in (0xF8, 0xF9) for _, off in points)
    assert all(b[0] > a[0] and b[1] > a[1] for a, b in zip(points, points[1:], strict=False))
    assert all(abs(s - k * sr) < 4608 for k, (s, _) in enumerate(points))
    # The decoder reads it without complaint, and a second time changes nothing.
    err = subprocess.run(["ffmpeg", "-v", "error", "-i", str(path), "-f", "null", "-"], capture_output=True, text=True).stderr
    assert err.strip() == ""
    assert not flacseek.add_seektable(path)


def test_not_a_flac_is_left_alone(tmp_path):
    p = tmp_path / "x.flac"
    p.write_bytes(b"not audio at all")
    assert not flacseek.add_seektable(p)
    assert p.read_bytes() == b"not audio at all"


def test_the_score_page_audio_is_served_with_a_seek_table(monkeypatch, tmp_path):
    """Made now or before: the song's FLAC the page plays has one."""
    from fastapi.testclient import TestClient

    from app.core.models import Job
    from app.core.registry import _jobs
    from app.main import app
    from app.score import store

    job = "abcdefabcd31"
    monkeypatch.setattr(store, "JOBS_DIR", tmp_path)
    _jobs[job] = Job(id=job, status="done", title="Seek")
    stems = tmp_path / job / "stems"
    stems.mkdir(parents=True)
    sf.write(stems / "piano.wav", np.zeros((44100 * 3, 2)) + 0.01, 44100)
    c = TestClient(app)
    try:
        assert c.get(f"/api/jobs/{job}/score/audio/piano.flac").status_code == 200
        dest = tmp_path / job / "score" / "audio" / "piano.flac"
        assert flacseek.has_seektable(dest)
        # One made before seek tables: given one when served.
        old = _flac(tmp_path, 3.0, "old.flac")
        shutil.copy(old, dest)
        assert not flacseek.has_seektable(dest)
        assert c.get(f"/api/jobs/{job}/score/audio/piano.flac").status_code == 200
        assert flacseek.has_seektable(dest)
    finally:
        _jobs.pop(job, None)
