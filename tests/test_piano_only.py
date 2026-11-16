"""A link imported as a solo piano: not separated, straight to its score.

Asked at import («¿Solo piano o canción completa?», static/js/job.js). The job
is separator "none": its one stem "piano" is the audio itself, and the piano
score (then its Pianoteq audio) is queued when it is done, as for any song
with a piano (runner._run_async -> score.prepare_after_separation).
"""

from __future__ import annotations

from unittest.mock import patch

import numpy as np
import pytest
import soundfile as sf
from fastapi.testclient import TestClient

from app.core.config import DEMUCS_MODEL
from app.core.models import Job
from app.core.registry import _jobs

URL = "https://www.youtube.com/watch?v=dQw4w9WgXcQ"


@pytest.fixture(autouse=True)
def _isolate_registry():
    _jobs.clear()
    yield
    _jobs.clear()


@pytest.fixture
def client():
    with patch("app.api.jobs.jobqueue.enqueue", lambda job_id: None):
        from app.main import app

        with TestClient(app) as c:
            yield c


def test_a_piano_only_link_is_one_piano_stem_not_separated(client):
    r = client.post("/api/jobs", json={"url": URL, "piano_only": True, "separator": "roformer"})
    assert r.status_code == 200
    job = _jobs[r.json()["job_id"]]
    assert job.separator == "none" and job.selected_stems == ["piano"]
    assert job.to_state()["separator"] == "none"
    # Survives a restart (registry.json).
    assert Job.from_record(job.to_record()).separator == "none"


def test_a_full_song_is_separated_as_before(client):
    r = client.post("/api/jobs", json={"url": URL})
    job = _jobs[r.json()["job_id"]]
    assert job.separator == "demucs" and len(job.selected_stems) == 6


def test_the_piano_stem_is_the_audio_itself(tmp_path):
    from app.pipeline import separate as sep
    from app.pipeline.collect import collect, make_original_track, make_selected_mix

    rate = 22050  # a separation's stems are 44.1 kHz stereo: converted
    t = np.arange(rate) / rate
    tone = 0.3 * np.sin(2 * np.pi * 440 * t)
    sf.write(tmp_path / "source.wav", np.stack([tone, tone], axis=1), rate)
    job = Job(id="a1b2c3d4e5f6", separator="none", selected_stems=["piano"])

    with patch.object(sep, "_run_demucs", side_effect=AssertionError("no Demucs")):
        out = sep.separate(job, tmp_path / "source.wav", tmp_path)
    assert out == tmp_path / DEMUCS_MODEL / "source"  # where collect() looks
    data, sr = sf.read(out / "piano.wav", always_2d=True)
    assert sr == 44100 and data.shape[1] == 2 and abs(len(data) - 44100) < 100
    assert 0.25 < np.max(np.abs(data)) < 0.35

    found = collect(job, out, tmp_path)
    stems = tmp_path / "stems"
    assert found == ["piano"] and (stems / "piano.wav").is_file()
    # No other stems: no "original" backing track, and the mix is the piano.
    assert make_original_track(job, tmp_path, stems) is None
    assert make_selected_mix(job, stems, found) == stems / "piano.wav"


def test_a_solo_piano_has_no_lyrics_to_look_for(tmp_path, monkeypatch):
    from app.pipeline import runner

    ran = []
    monkeypatch.setattr(runner, "_run_common", lambda *a: ran.append("separation"))
    monkeypatch.setattr(runner.IdentifyLookup, "start", staticmethod(lambda *a, **k: None))

    def no(*a, **k):
        raise AssertionError("lyrics stage ran for a solo piano")

    monkeypatch.setattr(runner.LyricsLookup, "start", staticmethod(no))
    monkeypatch.setattr(runner, "transcribe_lyrics", no)
    monkeypatch.setattr(runner, "retime_after_separation", no)
    runner._run_with_band_lookup(Job(id="a1b2c3d4e5f6", separator="none"), tmp_path, tmp_path)
    assert ran == ["separation"]

    # A song still gets them.
    called = []
    monkeypatch.setattr(runner.LyricsLookup, "start", staticmethod(lambda *a, **k: None))
    monkeypatch.setattr(runner, "transcribe_lyrics", lambda *a: called.append("transcribe"))
    monkeypatch.setattr(runner, "retime_after_separation", lambda *a: called.append("retime"))
    runner._run_with_band_lookup(Job(id="a1b2c3d4e5f6"), tmp_path, tmp_path)
    assert called == ["transcribe", "retime"]


def test_its_score_is_queued_when_done(tmp_path, monkeypatch):
    """The piano score starts by itself, and reads the piano stem (the audio)."""
    from app.api import score as api
    from app.score import engines

    monkeypatch.setattr("app.score.store.JOBS_DIR", tmp_path)
    monkeypatch.setenv("STEMDECK_SCORE_AUTO", "1")
    stems = tmp_path / "a1b2c3d4e5f6" / "stems"
    stems.mkdir(parents=True)
    sf.write(stems / "piano.wav", np.zeros((441, 2)), 44100)
    job = Job(id="a1b2c3d4e5f6", separator="none", stem_presence={"piano": 100})

    started = []

    async def fake_run(job, stem, source):
        started.append((job.id, stem, source))

    monkeypatch.setattr(api, "_run_async", fake_run)

    import asyncio

    async def go():
        api.prepare_after_separation(job)
        await asyncio.sleep(0)

    asyncio.run(go())
    assert started == [("a1b2c3d4e5f6", "piano", "auto")]
    # One stem: no full mix to rebuild, the stem is the recording.
    from app.score import store

    assert store.source_audio(job.id) is None
    assert engines.choose_audio("piano", job.stem_presence, "auto", False)[0] == "stem"
    api._RUNS.pop(("a1b2c3d4e5f6", "piano"), None)
