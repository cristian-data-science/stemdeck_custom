"""Score API: transcription lifecycle, persistent edits, settings, chords, exports.

The model is replaced by a stub that writes the calibration piece's exact
notes, so these tests check the plumbing, not the model (that is
test_score_transcribe_model.py).
"""

from __future__ import annotations

import io
import json
import time

import mido
import pytest
from fastapi.testclient import TestClient

from app.core.models import Job
from app.core.registry import _jobs
from app.score import calibration as cal

JOB = "abcdefabcd01"


@pytest.fixture(autouse=True)
def _isolate_registry():
    _jobs.clear()
    yield
    _jobs.clear()


@pytest.fixture
def jobs_dir(tmp_path, monkeypatch):
    monkeypatch.setattr("app.score.store.JOBS_DIR", tmp_path)
    monkeypatch.setattr("app.api.score.JOBS_DIR", tmp_path)
    monkeypatch.setattr("app.api.jobs.JOBS_DIR", tmp_path)
    return tmp_path


@pytest.fixture
def stub_engine(monkeypatch):
    calls = []

    def fake(stem, audio, out, report=None):
        calls.append(stem)
        if report:
            report("transcribe", 0.5)
        notes = [{k: n[k] for k in ("midi", "start", "end", "velocity")} for n in cal.notes()]
        # Two blips the automatic clean-up must drop.
        notes += [
            {"midi": 90, "start": 3.0, "end": 3.01, "velocity": 40},
            {"midi": 91, "start": 4.0, "end": 4.005, "velocity": 40},
        ]
        out.write_text(json.dumps({"engine": "stub", "notes": notes, "pedals": []}))

    monkeypatch.setattr("app.score.engines.transcribe", fake)
    # No beat model in these tests: the score keeps the song's grid.
    monkeypatch.setattr("app.score.pulse.track", lambda audio: None)
    monkeypatch.setattr("app.score.pulse.track_notes", lambda notes: None)
    return calls


@pytest.fixture
def client(jobs_dir):
    from app.main import app

    return TestClient(app)


@pytest.fixture
def done_job(jobs_dir):
    job = Job(id=JOB, status="done", title="Prueba", bpm=90, key="F", scale="Major")
    _jobs[job.id] = job
    stems = jobs_dir / JOB / "stems"
    stems.mkdir(parents=True)
    (stems / "piano.wav").write_bytes(b"RIFF0000WAVE")
    (stems / "beats.json").write_text(
        json.dumps(
            {
                "detector": "beat_this",  # a trusted grid, as from a drum track
                "source": "drums",
                "beats": cal.beats(),
                "bars": cal.bars(),
                "bpm": 90,
                "confidence": 97,
            }
        )
    )
    return job


def _transcribe(client) -> dict:
    r = client.post(f"/api/jobs/{JOB}/score/piano")
    assert r.status_code == 202
    for _ in range(100):
        data = client.get(f"/api/jobs/{JOB}/score/piano").json()
        if data["status"]["state"] == "done":
            return data
        assert data["status"]["state"] in ("queued", "running")
        time.sleep(0.05)
    raise AssertionError("transcription never finished")


def test_unknown_job_and_stem_404(client, done_job):
    assert client.get("/api/jobs/ffffffffffff/score/piano").status_code == 404
    assert client.get(f"/api/jobs/{JOB}/score/drums").status_code == 404
    assert client.get(f"/api/jobs/{JOB}/score/piano%2e%2e").status_code == 404


def test_status_none_before_transcription(client, done_job):
    data = client.get(f"/api/jobs/{JOB}/score/piano").json()
    assert data["status"]["state"] == "none"


def test_transcription_produces_the_score(client, done_job, stub_engine):
    data = _transcribe(client)
    assert stub_engine == ["piano"]
    assert data["bpm"] == 90
    assert data["meter"] == "4/4"
    assert data["key"]["name"] == "Fa mayor"
    assert data["stats"]["notes"] == cal.EXPECTED["notes"]
    assert data["stats"]["auto_removed"] == 2
    assert data["stats"]["raw_notes"] == cal.EXPECTED["notes"] + 2
    assert [c["text"] for c in data["chords"]] == cal.EXPECTED["chords"]
    assert len(data["measures"]) == 8
    assert all(f'xml:id="{n["id"]}"' in data["mei"] for n in data["notes"])
    # A second POST does not re-run the model.
    assert client.post(f"/api/jobs/{JOB}/score/piano").status_code == 200
    assert stub_engine == ["piano"]


def test_edits_persist_across_reads(client, done_job, stub_engine):
    data = _transcribe(client)
    notes = [
        {k: n[k] for k in ("id", "midi", "start", "end", "velocity", "hand")} for n in data["notes"]
    ]
    deleted = notes.pop(0)
    notes[0]["midi"] += 1
    notes[1]["hand"] = "L" if data["notes"][2]["staff"] == 1 else "R"
    r = client.put(f"/api/jobs/{JOB}/score/piano/notes", json={"notes": notes})
    assert r.status_code == 200
    saved = r.json()
    assert saved["edited"] is True
    assert saved["version"] == data["version"] + 1

    again = client.get(f"/api/jobs/{JOB}/score/piano").json()
    ids = {n["id"] for n in again["notes"]}
    assert deleted["id"] not in ids
    by_id = {n["id"]: n for n in again["notes"]}
    assert by_id[notes[0]["id"]]["midi"] == notes[0]["midi"]
    assert by_id[notes[1]["id"]]["hand"] == notes[1]["hand"]
    assert by_id[notes[1]["id"]]["staff"] == (2 if notes[1]["hand"] == "L" else 1)
    # On disk, atomically written.
    on_disk = json.loads((done_job_dir(client) / "notes.json").read_text())
    assert len(on_disk["notes"]) == len(notes)


def done_job_dir(client):
    from app.score import store

    return store.score_dir(JOB, "piano")


def test_reset_restores_the_transcription(client, done_job, stub_engine):
    data = _transcribe(client)
    client.put(f"/api/jobs/{JOB}/score/piano/notes", json={"notes": []})
    assert client.get(f"/api/jobs/{JOB}/score/piano").json()["stats"]["notes"] == 0
    r = client.delete(f"/api/jobs/{JOB}/score/piano/notes")
    assert r.json()["stats"]["notes"] == data["stats"]["notes"]
    assert r.json()["edited"] is False


@pytest.mark.parametrize(
    "bad",
    [
        {"id": "n1", "midi": 10, "start": 1, "end": 2},
        {"id": "n1", "midi": 60, "start": 2, "end": 1},
        {"id": "n1", "midi": 60, "start": 1, "end": 100},
        {"id": "x<script>", "midi": 60, "start": 1, "end": 2},
        {"id": "n1", "midi": 60, "start": 1, "end": 2, "hand": "X"},
    ],
)
def test_invalid_notes_are_refused(client, done_job, stub_engine, bad):
    _transcribe(client)
    r = client.put(f"/api/jobs/{JOB}/score/piano/notes", json={"notes": [bad]})
    assert r.status_code == 422


def test_duplicate_ids_are_refused(client, done_job, stub_engine):
    _transcribe(client)
    n = {"id": "n1", "midi": 60, "start": 1, "end": 2}
    assert (
        client.put(f"/api/jobs/{JOB}/score/piano/notes", json={"notes": [n, n]}).status_code == 422
    )


def test_edit_before_transcription_is_409(client, done_job):
    assert client.put(f"/api/jobs/{JOB}/score/piano/notes", json={"notes": []}).status_code == 409


def test_settings_persist_and_requantize(client, done_job, stub_engine):
    _transcribe(client)
    r = client.put(
        f"/api/jobs/{JOB}/score/piano/settings",
        json={"names": "letters", "split": 48, "hands": "split"},  # the fixed split point
    )
    data = r.json()
    assert data["names"] == "letters"
    assert data["settings"]["split"] == 48
    assert data["key"]["name"] == "F major"
    assert [c["text"] for c in data["chords"]][:3] == ["F", "C", "F"]
    # Split at C3: the left hand's C3/G3 now sit on the treble staff.
    by_midi = [n for n in data["notes"] if n["midi"] == 48]
    assert all(n["staff"] == 1 for n in by_midi)
    again = client.get(f"/api/jobs/{JOB}/score/piano").json()
    assert again["settings"]["split"] == 48


def test_chord_override_rename_remove_add(client, done_job, stub_engine):
    data = _transcribe(client)
    first = data["chords"][0]
    ms = int(first["id"][1:])
    r = client.put(f"/api/jobs/{JOB}/score/piano/chords", json={"time_ms": ms, "text": "Fa6"})
    assert r.json()["chords"][0]["text"] == "Fa6"
    assert r.json()["chords"][0]["override"] is True
    r = client.put(f"/api/jobs/{JOB}/score/piano/chords", json={"time_ms": ms, "text": ""})
    assert len(r.json()["chords"]) == len(data["chords"]) - 1
    r = client.put(f"/api/jobs/{JOB}/score/piano/chords", json={"time_ms": ms, "text": None})
    assert r.json()["chords"][0]["text"] == "Fa"
    # A chord where none was detected (beat 2 of bar 1).
    beat2 = round(cal.beats()[1] * 1000)
    r = client.put(f"/api/jobs/{JOB}/score/piano/chords", json={"time_ms": beat2, "text": "Sol7"})
    texts = [c["text"] for c in r.json()["chords"]]
    assert texts[:2] == ["Fa", "Sol7"]
    assert "Sol7" in r.json()["mei"]


def test_exports(client, done_job, stub_engine):
    _transcribe(client)
    r = client.get(f"/api/jobs/{JOB}/score/piano/export.mid")
    assert r.status_code == 200
    mid = mido.MidiFile(file=io.BytesIO(r.content))
    assert (
        sum(1 for t in mid.tracks for m in t if m.type == "note_on" and m.velocity)
        == cal.EXPECTED["notes"]
    )
    r = client.get(f"/api/jobs/{JOB}/score/piano/export.musicxml")
    assert r.status_code == 200 and b"<score-partwise" in r.content
    assert 'filename="Prueba_piano.musicxml"' in r.headers["content-disposition"]
    r = client.get(f"/api/jobs/{JOB}/score/piano/export.mei")
    assert r.status_code == 200 and b"<mei" in r.content
    assert client.get(f"/api/jobs/{JOB}/score/piano/export.exe").status_code == 404


def test_failed_transcription_reports_error(client, done_job, monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("model exploded")

    monkeypatch.setattr("app.score.engines.transcribe", boom)
    client.post(f"/api/jobs/{JOB}/score/piano")
    for _ in range(100):
        state = client.get(f"/api/jobs/{JOB}/score/piano").json()["status"]
        if state["state"] == "error":
            assert "model exploded" in state["error"]
            return
        time.sleep(0.05)
    raise AssertionError("error never reported")


def test_calibration_endpoint_registers_a_playable_job(client, jobs_dir):
    r = client.post("/api/score/calibration")
    assert r.status_code == 200
    body = r.json()
    assert body["expected"]["chords"] == cal.EXPECTED["chords"]
    job_id = body["job_id"]
    assert (jobs_dir / job_id / "stems" / "piano.wav").stat().st_size > 100_000
    beats = json.loads((jobs_dir / job_id / "stems" / "beats.json").read_text())
    assert beats["beats"][:2] == cal.beats()[:2]
    assert client.get(f"/api/jobs/{job_id}/score/piano").json()["status"]["state"] == "none"


def test_bass_stem_defaults_to_the_f_clef(client, done_job, stub_engine):
    (done_job_dir(client).parents[1] / "stems" / "bass.wav").write_bytes(b"RIFF0000WAVE")
    r = client.post(f"/api/jobs/{JOB}/score/bass")
    assert r.status_code == 202
    for _ in range(100):
        data = client.get(f"/api/jobs/{JOB}/score/bass").json()
        if data["status"]["state"] == "done":
            break
        time.sleep(0.05)
    assert data["settings"]["split"] == 84
    assert all(n["staff"] == 2 for n in data["notes"])
    assert stub_engine == ["bass"]


def test_gpu_failure_falls_back_to_the_cpu(monkeypatch, tmp_path):
    from app.score import engines
    from app.score.transcribe import TranscriptionError

    calls = []

    def fake_run(audio, out, device, report=None, **kw):
        calls.append(device)
        if device == "cuda":
            raise TranscriptionError("CUDA out of memory")
        out.write_text("{}")

    monkeypatch.setattr(engines, "run_transcription", fake_run)
    monkeypatch.setattr(engines, "device_for", lambda: "cuda")
    engines.transcribe("piano", tmp_path / "a.wav", tmp_path / "o.json")
    assert calls == ["cuda", "cpu"]
    # A cancel is not retried.
    calls.clear()

    def cancelled(audio, out, device, report=None, **kw):
        calls.append(device)
        raise TranscriptionError("cancelled")

    monkeypatch.setattr(engines, "run_transcription", cancelled)
    with pytest.raises(TranscriptionError):
        engines.transcribe("piano", tmp_path / "a.wav", tmp_path / "o.json")
    assert calls == ["cuda"]


def test_device_follows_the_app_setting(monkeypatch):
    from app.score import engines

    monkeypatch.setattr("app.core.settings.get_demucs_device", lambda: "cuda")
    assert engines.device_for() == "cuda"
    monkeypatch.setattr("app.core.settings.get_demucs_device", lambda: "mps")
    assert engines.device_for() == "cpu"
    monkeypatch.setattr("app.core.settings.get_demucs_device", lambda: "cpu")
    assert engines.device_for() == "cpu"


def test_key_from_notes_song_or_manual(client, done_job, stub_engine):
    _transcribe(client)
    data = client.get(f"/api/jobs/{JOB}/score/piano").json()
    assert data["key"]["source"] == "notes"
    assert data["key"]["notes"] == "Fa mayor" and data["key"]["song"] == "Fa mayor"
    r = client.put(f"/api/jobs/{JOB}/score/piano/settings", json={"key": "2:minor"})
    assert r.json()["key"]["name"] == "Re menor" and r.json()["key"]["source"] == "manual"
    assert client.get(f"/api/jobs/{JOB}/score/piano").json()["settings"]["key"] == "2:minor"
    r = client.put(f"/api/jobs/{JOB}/score/piano/settings", json={"key": "song"})
    assert r.json()["key"]["source"] == "song"
    assert (
        client.put(f"/api/jobs/{JOB}/score/piano/settings", json={"key": "13:major"}).status_code
        == 422
    )


def test_the_pipelines_key_label_is_read(client, done_job, stub_engine):
    done_job.key, done_job.scale = "B min", "Natural Minor"  # what analyze.py writes
    _transcribe(client)
    r = client.put(f"/api/jobs/{JOB}/score/piano/settings", json={"key": "song"})
    assert r.json()["key"]["name"] == "Si menor"
    assert r.json()["key"]["fifths"] == 2


def test_meter_and_bar_shift_settings(client, done_job, stub_engine):
    _transcribe(client)
    data = client.get(f"/api/jobs/{JOB}/score/piano").json()
    # 4/4, and the bass on beats 1 and 3 says so on its own.
    assert data["meter"] == "4/4" and data["stats"]["meter_source"] in ("auto", "notes")
    r = client.put(f"/api/jobs/{JOB}/score/piano/settings", json={"meter": "3"})
    assert r.json()["meter"] == "3/4" and r.json()["stats"]["meter_source"] == "manual"
    r = client.put(f"/api/jobs/{JOB}/score/piano/settings", json={"meter": "4", "bar_shift": 1})
    starts = [m["start"] for m in r.json()["measures"] if m["meter"] == 4]
    assert r.json()["settings"]["bar_shift"] == 1
    # Barlines moved one beat (0.667 s at 90 BPM) off the calibration's downbeats.
    assert all(abs(((s - 1.0) / (60 / 90)) % 4 - 1) < 0.01 for s in starts[1:])
    assert (
        client.put(f"/api/jobs/{JOB}/score/piano/settings", json={"meter": "5"}).status_code == 422
    )


def test_solo_piano_is_transcribed_from_the_original(client, done_job, monkeypatch, jobs_dir):
    heard = []

    def fake(stem, audio, out, report=None):
        heard.append(audio.name)
        notes = [{k: n[k] for k in ("midi", "start", "end", "velocity")} for n in cal.notes()]
        out.write_text(json.dumps({"engine": "stub", "notes": notes}))

    monkeypatch.setattr("app.score.engines.transcribe", fake)
    monkeypatch.setattr("app.score.pulse.track", lambda audio: None)
    (jobs_dir / JOB / "source.wav").write_bytes(b"RIFF0000WAVE")
    done_job.stem_presence = {
        "vocals": 0,
        "drums": 0,
        "bass": 2,
        "guitar": 18,
        "piano": 100,
        "other": 91,
    }
    data = _transcribe(client)
    assert heard == ["source.wav"]
    assert data["stats"]["audio_source"] == "original"
    # Asked for the stem, it gets the stem.
    client.post(f"/api/jobs/{JOB}/score/piano?force=true&source=stem")
    for _ in range(100):
        d = client.get(f"/api/jobs/{JOB}/score/piano").json()
        if d["status"]["state"] == "done" and d["stats"]["audio_source"] == "stem":
            break
        time.sleep(0.05)
    assert heard == ["source.wav", "piano.wav"]


def test_own_pulse_replaces_a_weak_song_grid(client, done_job, stub_engine, monkeypatch, jobs_dir):
    # The song's grid came from the librosa fallback on a silent drums stem.
    (jobs_dir / JOB / "stems" / "beats.json").write_text(
        json.dumps(
            {
                "detector": "librosa",
                "source": "drums",
                "beats": [i * 0.44 for i in range(80)],
                "bars": [],
            }
        )
    )
    done_job.stem_presence = {"drums": 0, "piano": 100}
    own = {"detector": "beat_this", "beats": cal.beats(), "bars": cal.bars()}
    monkeypatch.setattr("app.score.pulse.track", lambda audio: own)
    data = _transcribe(client)
    assert data["stats"]["pulse_source"] == "audio"
    assert data["bpm"] == 90 and data["meter"] == "4/4"
    r = client.put(f"/api/jobs/{JOB}/score/piano/settings", json={"pulse": "song"})
    assert r.json()["stats"]["pulse_source"] == "song"


# -- Pianoteq ---------------------------------------------------------------


@pytest.fixture
def fake_pianoteq(monkeypatch, tmp_path):
    """Pianoteq's command line replaced by a stub that writes the MIDI it was
    given as the "flac", so a test can read back what would have been played."""
    from app.score import pianoteq

    exe = tmp_path / "Pianoteq 9.exe"
    exe.write_bytes(b"")
    runs = []

    def run(args, timeout, wanted=None, low=False):
        if "--list-presets" in args:
            return type("R", (), {"stdout": "NY Steinway D Classical\nU4 Small\n", "stderr": ""})
        runs.append(args)
        midi = args[args.index("--midi") + 1]
        out = args[args.index("--flac") + 1]
        with open(midi, "rb") as src, open(out, "wb") as dst:
            dst.write(src.read())
        return type("R", (), {"stdout": "", "stderr": ""})

    monkeypatch.setenv("STEMDECK_PIANOTEQ", str(exe))
    monkeypatch.setattr(pianoteq, "_run", run)
    # Each test's score starts again at version 1 (the server keeps the
    # latest version it read per score).
    from app.api import score as api

    api._PT_NOTES.clear()
    api._PT_WANT.clear()
    pianoteq._presets.cache_clear()
    yield runs
    pianoteq._presets.cache_clear()


def _render(client, preset="NY Steinway D Classical") -> dict:
    r = client.post(f"/api/jobs/{JOB}/score/piano/pianoteq", json={"preset": preset})
    assert r.status_code in (200, 202), r.text
    st = r.json()
    for _ in range(100):
        if st["state"] != "rendering":
            return st
        time.sleep(0.02)
        st = client.get(f"/api/jobs/{JOB}/score/piano/pianoteq/status/{st['key']}").json()
    raise AssertionError("render never finished")


def test_pianoteq_renders_the_score_as_played_and_caches(
    client, done_job, stub_engine, fake_pianoteq
):
    info = client.get("/api/score/pianoteq").json()
    assert info["available"] and info["default"] == "NY Steinway D Classical"
    data = _transcribe(client)
    st = _render(client)
    assert st["state"] == "ready"
    audio = client.get(st["url"])
    assert audio.status_code == 200 and audio.headers["content-type"] == "audio/flac"
    # What Pianoteq was given: every note, on the song's own clock.
    mid = mido.MidiFile(file=io.BytesIO(audio.content))
    t, tempo, starts = 0.0, 500_000, []
    for msg in mido.merge_tracks(mid.tracks):
        t += mido.tick2second(msg.time, mid.ticks_per_beat, tempo)
        if msg.type == "set_tempo":
            tempo = msg.tempo
        if msg.type == "note_on" and msg.velocity:
            starts.append(t)
    assert len(starts) == len(data["notes"])
    want = sorted(n["start"] for n in data["notes"])
    assert max(abs(a - b) for a, b in zip(sorted(starts), want, strict=True)) < 0.01
    # Same notes and preset: from the cache, no second render.
    assert _render(client)["key"] == st["key"]
    assert len(fake_pianoteq) == 1
    # Another piano, or an edit, is a new render.
    assert _render(client, "U4 Small")["key"] != st["key"]
    notes = [{k: n[k] for k in ("id", "midi", "start", "end", "velocity")} for n in data["notes"]]
    notes[0]["midi"] += 1
    assert (
        client.put(f"/api/jobs/{JOB}/score/piano/notes", json={"notes": notes}).status_code == 200
    )
    assert _render(client)["key"] != st["key"]
    assert len(fake_pianoteq) == 3


def test_a_hand_change_does_not_render_pianoteq_again(client, done_job, stub_engine, fake_pianoteq):
    # The file splits the notes into a right- and a left-hand track, but
    # Pianoteq plays the same notes: a new hand model or a hand correction
    # made every song render again.
    data = _transcribe(client)
    st = _render(client)
    notes = [
        {k: n[k] for k in ("id", "midi", "start", "end", "velocity", "hand")} for n in data["notes"]
    ]
    notes[0]["hand"] = "L" if data["notes"][0]["staff"] == 1 else "R"
    r = client.put(f"/api/jobs/{JOB}/score/piano/notes", json={"notes": notes})
    assert r.status_code == 200
    assert _render(client)["key"] == st["key"]
    assert len(fake_pianoteq) == 1


def test_a_render_named_after_the_hands_is_kept(client, done_job, stub_engine, fake_pianoteq):
    # Renders made until 2026-11-12 were named after the two-track MIDI: one
    # still matching is renamed, not rendered again.
    from app.api.score import _pt_folder
    from app.score import pianoteq, service, store

    _transcribe(client)
    job = __import__("app.core.registry", fromlist=["get"]).get(JOB)
    doc, meta = store.read_notes(JOB, "piano"), store.read_meta(JOB, "piano")
    midi, sig = service.performance_signature(job, "piano", doc, meta)
    folder = _pt_folder(JOB, "piano")
    folder.mkdir(parents=True, exist_ok=True)
    old = pianoteq.audio_path(folder, pianoteq.render_key(midi, "U4 Small"))
    old.write_bytes(b"made before")
    st = _render(client, "U4 Small")
    assert st["key"] == pianoteq.render_key(sig, "U4 Small") and not fake_pianoteq
    assert pianoteq.audio_path(folder, st["key"]).read_bytes() == b"made before"


def test_hand_corrections_are_kept_for_retraining(client, done_job, stub_engine):
    from app.score import hand_labels

    data = _transcribe(client)
    assert data["hand_labels"] == {"corrected": 0, "reviewed": False, "reviewed_notes": 0}
    notes = [
        {k: n[k] for k in ("id", "midi", "start", "end", "velocity", "hand")} for n in data["notes"]
    ]
    first = data["notes"][0]
    shown = "R" if first["staff"] == 1 else "L"
    notes[0]["hand"] = "L" if shown == "R" else "R"
    notes[1]["midi"] += 1  # not a hand change: not logged
    url = f"/api/jobs/{JOB}/score/piano/notes"
    after = client.put(url, json={"notes": notes}).json()
    assert after["hand_labels"]["corrected"] == 1
    log = hand_labels.read_log(JOB, "piano")
    assert len(log) == 1
    e = log[0]
    assert (e["id"], e["hand"], e["was"], e["midi"]) == (
        first["id"],
        notes[0]["hand"],
        shown,
        first["midi"],
    )
    # Back to the program: logged too, and no longer a label.
    notes[0]["hand"] = None
    assert client.put(url, json={"notes": notes}).json()["hand_labels"]["corrected"] == 0
    # «Canción revisada»: every note's hand as shown; later corrections follow.
    rev = client.post(f"/api/jobs/{JOB}/score/piano/hands/reviewed").json()["hand_labels"]
    assert rev["reviewed"] and rev["reviewed_notes"] == len(notes)
    snap = hand_labels.reviewed(JOB, "piano")
    assert {n["hand"] for n in snap["notes"]} <= {"L", "R"}
    notes[2]["hand"] = "L"
    client.put(url, json={"notes": notes})
    snap = hand_labels.reviewed(JOB, "piano")
    assert next(n for n in snap["notes"] if n["id"] == notes[2]["id"])["hand"] == "L"
    gone = client.delete(f"/api/jobs/{JOB}/score/piano/hands/reviewed").json()["hand_labels"]
    assert not gone["reviewed"]
    # The log outlives «Restaurar original».
    client.delete(url)
    assert len(hand_labels.read_log(JOB, "piano")) == 3


def test_the_default_piano_is_the_users_bosendorfer_when_installed(monkeypatch, tmp_path):
    from app.score import pianoteq

    exe = tmp_path / "Pianoteq 9.exe"
    exe.write_bytes(b"")
    monkeypatch.setenv("STEMDECK_PIANOTEQ", str(exe))
    for listed, want in (
        ("NY Steinway D Classical\nBösendorfer VC Player\n", "Bösendorfer VC Player"),
        ("U4 Small\nNY Steinway D Classical\n", "NY Steinway D Classical"),
        ("U4 Small\n", "U4 Small"),
    ):
        monkeypatch.setattr(
            pianoteq,
            "_run",
            lambda args, timeout, out=listed: type("R", (), {"stdout": out, "stderr": ""}),
        )
        pianoteq._presets.cache_clear()
        assert pianoteq.info()["default"] == want
    pianoteq._presets.cache_clear()


def test_pianoteq_refuses_unknown_presets_and_absence(client, done_job, stub_engine, monkeypatch):
    from app.score import pianoteq

    _transcribe(client)
    monkeypatch.setenv("STEMDECK_PIANOTEQ", "Z:/nowhere/Pianoteq.exe")
    assert client.get("/api/score/pianoteq").json()["available"] is False
    r = client.post(f"/api/jobs/{JOB}/score/piano/pianoteq", json={"preset": "x"})
    assert r.status_code == 404
    assert client.get(f"/api/jobs/{JOB}/score/piano/pianoteq/status/..%2f..").status_code == 404
    assert not pianoteq.valid_key("../../etc")


def _held_seconds(midi_bytes: bytes) -> float:
    """Total seconds of sounding notes in a MIDI file."""
    mid = mido.MidiFile(file=io.BytesIO(midi_bytes))
    t, tempo, on, total = 0.0, 500_000, {}, 0.0
    for msg in mido.merge_tracks(mid.tracks):
        t += mido.tick2second(msg.time, mid.ticks_per_beat, tempo)
        if msg.type == "set_tempo":
            tempo = msg.tempo
        elif msg.type == "note_on" and msg.velocity:
            on.setdefault(msg.note, []).append(t)
        elif msg.type in ("note_off", "note_on") and on.get(msg.note):
            total += t - on[msg.note].pop(0)
    return total


def test_pedal_setting_lengthens_what_pianoteq_plays(client, done_job, stub_engine, fake_pianoteq):
    data = _transcribe(client)
    assert data["settings"]["pedal"] == 0
    assert data["stats"]["pedal_source"] == "chords"  # the stub hears no pedal
    assert any(n["pedal_end"] is not None for n in data["notes"])
    dry = client.get(_render(client)["url"]).content
    r = client.put(f"/api/jobs/{JOB}/score/piano/settings", json={"pedal": 100})
    assert r.status_code == 200 and r.json()["settings"]["pedal"] == 100
    assert client.get(f"/api/jobs/{JOB}/score/piano").json()["settings"]["pedal"] == 100
    wet = client.get(_render(client)["url"]).content
    client.put(f"/api/jobs/{JOB}/score/piano/settings", json={"pedal": 50})
    half = client.get(_render(client)["url"]).content
    assert _held_seconds(dry) < _held_seconds(half) < _held_seconds(wet)
    # Same note count and starts: the pedal only moves releases.
    assert len(mido.MidiFile(file=io.BytesIO(wet)).tracks) == len(
        mido.MidiFile(file=io.BytesIO(dry)).tracks
    )
    assert (
        client.put(f"/api/jobs/{JOB}/score/piano/settings", json={"pedal": 101}).status_code == 422
    )


def test_the_pulse_is_tracked_on_the_whole_song_even_from_a_stem(
    client, done_job, stub_engine, monkeypatch, jobs_dir
):
    # A sparse stem is a poor source of pulse (Saturday Night: the piano
    # plays in a few passages); the whole mix keeps the beat throughout.
    tracked = []
    monkeypatch.setattr("app.score.pulse.track", lambda audio: tracked.append(audio.name))
    (jobs_dir / JOB / "source.wav").write_bytes(b"RIFF0000WAVE")
    r = client.post(f"/api/jobs/{JOB}/score/piano?source=stem")
    assert r.status_code == 202
    for _ in range(100):
        if client.get(f"/api/jobs/{JOB}/score/piano").json()["status"]["state"] == "done":
            break
        time.sleep(0.05)
    assert stub_engine == ["piano"] and tracked == ["source.wav"]


def test_playback_follows_the_songs_tuning(client, done_job, stub_engine, fake_pianoteq, jobs_dir):
    # A song transcribed retuned (tuning.py) is played back at its own
    # tuning: Pianoteq gets a pitch bend, exports stay at A440.
    _transcribe(client)

    def bends(midi_bytes):
        mid = mido.MidiFile(file=io.BytesIO(midi_bytes))
        return [m.pitch for t in mid.tracks for m in t if m.type == "pitchwheel"]

    assert bends(client.get(_render(client)["url"]).content) == []
    raw_path = jobs_dir / JOB / "score" / "piano" / "raw.json"
    raw = json.loads(raw_path.read_text())
    raw["tuning"] = {"cents": 38.0, "consistency": 0.73, "corrected": True}
    raw_path.write_text(json.dumps(raw))
    tuned = bends(client.get(_render(client)["url"]).content)
    assert tuned == [round(38 / 200 * 8191)] * 2  # both hands, +-2 semitone range
    data = client.get(f"/api/jobs/{JOB}/score/piano").json()
    assert data["stats"]["tuning"]["corrected"] is True
    export = client.get(f"/api/jobs/{JOB}/score/piano/export.mid?quantized=false").content
    assert bends(export) == []


def test_deleted_notes_are_kept_to_restore_one_or_all(client, done_job, stub_engine):
    data = _transcribe(client)
    assert data["trash"] == []
    notes = [
        {k: n[k] for k in ("id", "midi", "start", "end", "velocity", "hand")} for n in data["notes"]
    ]
    put = lambda ns: client.put(f"/api/jobs/{JOB}/score/piano/notes", json={"notes": ns}).json()  # noqa: E731
    gone_a, gone_b = notes[3], notes[7]
    after = put([n for n in notes if n["id"] not in (gone_a["id"], gone_b["id"])])
    assert [t["id"] for t in after["trash"]] == [gone_a["id"], gone_b["id"]]
    assert after["trash"][0]["midi"] == gone_a["midi"] and after["trash"][0]["deleted_at"] > 0
    # A later deletion goes first; the history survives a reload.
    gone_c = notes[10]
    after = put([n for n in notes if n["id"] not in (gone_a["id"], gone_b["id"], gone_c["id"])])
    assert [t["id"] for t in after["trash"]][0] == gone_c["id"]
    assert len(client.get(f"/api/jobs/{JOB}/score/piano").json()["trash"]) == 3
    # Restoring one (it is back in the notes) takes it out of the history.
    after = put([n for n in notes if n["id"] not in (gone_b["id"], gone_c["id"])])
    assert {t["id"] for t in after["trash"]} == {gone_b["id"], gone_c["id"]}
    assert any(n["id"] == gone_a["id"] for n in after["notes"])
    # Restoring all empties it; so does going back to the transcription.
    assert put(notes)["trash"] == []
    put([n for n in notes if n["id"] != gone_a["id"]])
    reset = client.delete(f"/api/jobs/{JOB}/score/piano/notes").json()
    assert reset["trash"] == []


def test_joined_and_added_notes_are_held_and_not_listed_as_deleted(client, done_job, stub_engine):
    """Two notes on one key joined in the piano view: the second leaves, the
    first now covers it and is "held" -- its length is the user's, drawn and
    played whole though its hand plays on (the score is one voice per staff),
    and the one it took in is not a deleted note. An added note is held too."""
    data = _transcribe(client)
    notes = [
        {k: n[k] for k in ("id", "midi", "start", "end", "velocity", "hand")} for n in data["notes"]
    ]
    put = lambda ns: client.put(f"/api/jobs/{JOB}/score/piano/notes", json={"notes": ns}).json()  # noqa: E731
    a = notes[0]
    b = {
        "id": "nb",
        "midi": a["midi"],
        "start": a["end"] + 0.05,
        "end": a["end"] + 1.5,
        "velocity": 80,
        "hand": None,
    }
    put([*notes, b])
    joined = {**a, "end": b["end"], "held": True}
    after = put([joined if n["id"] == a["id"] else n for n in notes])
    assert after["trash"] == []  # joined, not deleted
    got = next(n for n in after["notes"] if n["id"] == a["id"])
    assert got["held"] is True and got["end"] == round(b["end"], 4)
    again = min(
        (n["start"] for n in notes if n["midi"] == a["midi"] and n["start"] > a["start"]),
        default=99,
    )
    assert got["sound_end"] == round(min(b["end"], again), 4)  # played whole, up to its next strike
    # Deleting it is a deletion; a plain note is not held.
    after = put(notes[1:])
    assert [t["id"] for t in after["trash"]] == [a["id"]]
    assert all("held" not in n for n in after["notes"])
    # An added note (an id of the page's own) is kept, held.
    added = {
        "id": "nu1abc",
        "midi": 72,
        "start": 1.0,
        "end": 1.5,
        "velocity": 80,
        "hand": "R",
        "held": True,
    }
    after = put([*notes[1:], added])
    assert any(n["id"] == "nu1abc" and n["held"] and n["hand"] == "R" for n in after["notes"])
    # Taken away again (🗑 or Undo), it is just gone: not in «Borradas».
    assert put(notes[1:])["trash"] == [t for t in after["trash"]]


def test_every_score_gets_its_pianoteq_audio_without_asking(
    client, done_job, stub_engine, fake_pianoteq, monkeypatch
):
    """Rendered as soon as the notes exist, beside the rest (the page opens
    meanwhile): both hands, then each hand alone. Choosing «Pianoteq» later
    finds it ready, and so does muting a hand (it used to render then, with
    the MIDI synth playing meanwhile)."""
    monkeypatch.setenv("STEMDECK_PIANOTEQ_AUTO", "1")
    _transcribe(client)
    from app.score import store

    folder = store.score_dir(JOB, "piano") / "pianoteq"
    for _ in range(500):
        if len(list(folder.glob("*.flac"))) == 12:
            break
        time.sleep(0.02)
    # Four speeds x (both hands, right, left).
    assert len(list(folder.glob("*.flac"))) == 12 and len(fake_pianoteq) == 12
    st = _render(client)
    assert st["state"] == "ready" and len(fake_pianoteq) == 12  # no other render
    for speed in (1.0, 0.7, 0.5, 0.25):
        for hand in (None, "R", "L"):
            r = client.post(
                f"/api/jobs/{JOB}/score/piano/pianoteq",
                json={"preset": "NY Steinway D Classical", "hand": hand, "speed": speed},
            )
            assert r.json()["state"] == "ready", (hand, speed)
    assert len(fake_pianoteq) == 12
    ready = client.get(f"/api/jobs/{JOB}/score/piano/pianoteq/ready").json()
    assert len(ready["variants"]) == 12 and "25:L" in ready["variants"]


def test_a_render_of_notes_edited_again_is_skipped(tmp_path, monkeypatch):
    """Renders run one at a time (~30 s a song): one no longer wanted when its
    turn comes is skipped, and one running is stopped. The render the page
    waited for came minutes late, behind renders of older notes."""
    from app.score import pianoteq

    exe = tmp_path / "Pianoteq 9.exe"
    exe.write_bytes(b"")
    monkeypatch.setenv("STEMDECK_PIANOTEQ", str(exe))
    ran = []
    monkeypatch.setattr(
        pianoteq, "_run", lambda args, timeout, wanted=None, low=False: ran.append(args)
    )
    with pytest.raises(pianoteq.Superseded):
        pianoteq.render_as(b"MThd", "U4 Small", tmp_path / "pt", "a" * 20, wanted=lambda: False)
    assert ran == [] and not list((tmp_path / "pt").glob("*.flac"))


def test_a_running_render_is_stopped_when_no_longer_wanted():
    import subprocess
    import sys

    from app.score import pianoteq

    asked = []

    def wanted():
        asked.append(1)
        return len(asked) < 2

    started = time.monotonic()
    with pytest.raises(pianoteq.Superseded):
        pianoteq._run_stoppable([sys.executable, "-c", "import time; time.sleep(30)"], 60, wanted)
    assert time.monotonic() - started < 10
    # And a run that finishes returns as before.
    done = pianoteq._run_stoppable([sys.executable, "-c", "print('ok')"], 60, lambda: True)
    assert isinstance(done, subprocess.CompletedProcess) and done.stdout.strip() == "ok"


def test_background_renders_wait_for_the_one_the_page_asked_for(monkeypatch):
    from app.api import score as api

    monkeypatch.setenv("STEMDECK_PIANOTEQ_AUTO", "1")
    ran = []
    monkeypatch.setattr(api, "_pt_background_one", lambda *task: ran.append(task) or "done")
    monkeypatch.setattr(api, "_PT_HIGH", 1)
    api._pt_background("abcdefabcd01", "piano", front=True)
    time.sleep(0.8)
    assert ran == []  # the page's render goes first
    monkeypatch.setattr(api, "_PT_HIGH", 0)
    for _ in range(100):
        if len(ran) == 12:
            break
        time.sleep(0.05)
    # By speed (100, 70, 50, 25 %), each: both hands, right, left.
    assert ran == [
        ("abcdefabcd01", "piano", h, s) for s in (1.0, 0.7, 0.5, 0.25) for h in (None, "R", "L")
    ]


def test_the_startup_sweep_queues_every_score(
    client, done_job, stub_engine, fake_pianoteq, monkeypatch
):
    """The whole library: every song at 100 % first (both hands, right, left;
    the most recently worked on first), then every song at 70 %, 50 %, 25 %
    -- not one song's slow renders before the next song has any."""
    from app.api import score as api
    from app.core.registry import _jobs
    from app.score import store

    _transcribe(client)
    other = "abcdefabcd02"
    _jobs[other] = _jobs[JOB].__class__(id=other, status="done")
    d = store.score_dir(other, "piano")
    d.mkdir(parents=True)
    (d / "raw.json").write_text("{}")
    queued = []
    monkeypatch.setattr(api, "_pt_queue", lambda tasks, front=False: queued.extend(tasks))
    monkeypatch.setenv("STEMDECK_PIANOTEQ_AUTO", "1")
    try:
        assert api.pianoteq_sweep() == 2
    finally:
        _jobs.pop(other, None)
    assert len(queued) == 24
    assert [t[3] for t in queued[:6]] == [1.0] * 6 and {t[0] for t in queued[:6]} == {JOB, other}
    assert [t[2] for t in queued[:3]] == [None, "R", "L"]
    assert [t[3] for t in queued[-6:]] == [0.25] * 6
    monkeypatch.setenv("STEMDECK_PIANOTEQ_AUTO", "0")
    assert api.pianoteq_sweep() == 0


def test_background_renders_run_below_normal_priority(monkeypatch):
    import sys

    from app.score import pianoteq

    seen = {}

    class P:
        returncode = 0

        def __init__(self, args, **kw):
            seen.clear()
            seen.update(kw)

        def communicate(self, timeout=None):
            return "", ""

    monkeypatch.setattr(pianoteq.subprocess, "Popen", P)
    pianoteq._run_stoppable(["x"], 10, lambda: True, low=True)
    if sys.platform == "win32":
        assert seen["creationflags"] & pianoteq.subprocess.BELOW_NORMAL_PRIORITY_CLASS
    else:
        assert seen["preexec_fn"] is pianoteq._nice
    pianoteq._run_stoppable(["x"], 10, lambda: True)
    if sys.platform == "win32":
        assert not seen["creationflags"] & pianoteq.subprocess.BELOW_NORMAL_PRIORITY_CLASS


# -- Pianoteq per song, practice renders, practice, library ------------------


def _note_starts(midi_bytes: bytes) -> list[float]:
    mid = mido.MidiFile(file=io.BytesIO(midi_bytes))
    t, tempo, starts = 0.0, 500_000, []
    for msg in mido.merge_tracks(mid.tracks):
        t += mido.tick2second(msg.time, mid.ticks_per_beat, tempo)
        if msg.type == "set_tempo":
            tempo = msg.tempo
        if msg.type == "note_on" and msg.velocity:
            starts.append(round(t, 3))
    return sorted(starts)


def test_a_setting_that_changes_no_note_keeps_the_render(
    client, done_job, stub_engine, fake_pianoteq
):
    """«Compás» redraws the score but plays the same notes: the same Pianoteq
    render (the song's tempo map used to be in the MIDI, so a new render)."""
    _transcribe(client)
    key = _render(client)["key"]
    r = client.put(f"/api/jobs/{JOB}/score/piano/settings", json={"meter": "3"})
    assert r.status_code == 200 and r.json()["meter"] == "3/4"
    assert _render(client)["key"] == key
    assert len(fake_pianoteq) == 1


def test_each_score_keeps_its_own_piano_and_lists_the_ready_ones(
    client, done_job, stub_engine, fake_pianoteq
):
    data = _transcribe(client)
    assert data["pianoteq"] == {"preset": None}
    ready = client.get(f"/api/jobs/{JOB}/score/piano/pianoteq/ready").json()
    assert ready["preset"] is None and ready["ready"] == [] and ready["variants"] == []
    _render(client, "U4 Small")
    assert client.get(f"/api/jobs/{JOB}/score/piano").json()["pianoteq"]["preset"] == "U4 Small"
    _render(client)
    ready = client.get(f"/api/jobs/{JOB}/score/piano/pianoteq/ready").json()
    assert ready["preset"] == "NY Steinway D Classical"
    assert sorted(ready["ready"]) == ["NY Steinway D Classical", "U4 Small"]
    # An edit: nothing is rendered for the new notes yet.
    notes = [{k: n[k] for k in ("id", "midi", "start", "end", "velocity")} for n in data["notes"]]
    client.put(f"/api/jobs/{JOB}/score/piano/notes", json={"notes": notes[1:]})
    assert client.get(f"/api/jobs/{JOB}/score/piano/pianoteq/ready").json()["ready"] == []


def test_practice_renders_one_hand_or_slower(client, done_job, stub_engine, fake_pianoteq):
    data = _transcribe(client)
    full = client.get(_render(client)["url"]).content
    r = client.post(
        f"/api/jobs/{JOB}/score/piano/pianoteq",
        json={"preset": "NY Steinway D Classical", "hand": "L"},
    )
    st = r.json()
    for _ in range(100):
        if st["state"] != "rendering":
            break
        time.sleep(0.02)
        st = client.get(f"/api/jobs/{JOB}/score/piano/pianoteq/status/{st['key']}").json()
    left = client.get(st["url"]).content
    want_left = [n for n in data["notes"] if n["staff"] == 2]
    assert 0 < len(_note_starts(left)) == len(want_left) < len(_note_starts(full))
    r = client.post(
        f"/api/jobs/{JOB}/score/piano/pianoteq",
        json={"preset": "NY Steinway D Classical", "speed": 0.5},
    )
    st = r.json()
    for _ in range(100):
        if st["state"] != "rendering":
            break
        time.sleep(0.02)
        st = client.get(f"/api/jobs/{JOB}/score/piano/pianoteq/status/{st['key']}").json()
    slow = _note_starts(client.get(st["url"]).content)
    assert max(abs(a - 2 * b) for a, b in zip(slow, _note_starts(full), strict=True)) < 0.01
    # The hand and the speed are the render's, not the song's piano.
    assert client.get(f"/api/jobs/{JOB}/score/piano").json()["pianoteq"]["preset"] == (
        "NY Steinway D Classical"
    )


def test_renders_under_the_old_name_are_kept_not_rendered_again(
    client, done_job, stub_engine, fake_pianoteq, jobs_dir
):
    from app.score import pianoteq, service, store

    _transcribe(client)
    job = done_job
    doc = store.read_notes(JOB, "piano")
    meta = store.read_meta(JOB, "piano")
    folder = store.score_dir(JOB, "piano") / "pianoteq"
    folder.mkdir(parents=True)
    old = pianoteq.legacy_key(service.legacy_performance_midi(job, "piano", doc, meta), "U4 Small")
    (folder / f"{old}.flac").write_bytes(b"old render")
    (folder / "0123456789abcdef0123.mp3").write_bytes(b"mp3 from before flac")
    ready = client.get(f"/api/jobs/{JOB}/score/piano/pianoteq/ready").json()
    assert ready["ready"] == ["U4 Small"]
    st = _render(client, "U4 Small")
    assert st["state"] == "ready" and fake_pianoteq == []  # adopted, not rendered
    assert client.get(st["url"]).content == b"old render"
    assert not list(folder.glob("*.mp3"))  # the MP3 leftovers are gone


def test_presets_saved_in_pianoteq_show_up_without_a_restart(monkeypatch, tmp_path):
    from app.score import pianoteq

    answers = iter([("A",), (), ("A", "Mine")])
    calls = []

    def listing(exe):
        calls.append(exe)
        return next(answers)

    cache = pianoteq._TimedCache(listing)
    assert cache("x") == ("A",)
    assert cache("x") == ("A",) and len(calls) == 1  # cached
    monkeypatch.setattr(pianoteq, "PRESETS_TTL", 0.0)
    assert cache("x") == ()  # an empty answer (Pianoteq busy) is not kept
    assert cache("x") == ("A", "Mine")
    # A user preset saved again is another render.
    presets = tmp_path / "Presets"
    presets.mkdir()
    monkeypatch.setattr(pianoteq, "_user_preset_dirs", lambda: [presets])
    assert pianoteq.preset_stamp("Mine") == ""
    (presets / "Mine.fxp").write_bytes(b"x")
    stamp = pianoteq.preset_stamp("Mine")
    assert stamp and pianoteq.render_key(b"m", "Mine") != pianoteq.render_key(b"m", "Mine", "")


def test_practice_is_kept_and_the_library_shows_each_score(
    client, done_job, stub_engine, fake_pianoteq
):
    lib = client.get("/api/score/library").json()
    assert JOB not in lib
    _transcribe(client)
    _render(client)
    put = lambda body: client.put(f"/api/jobs/{JOB}/score/piano/practice", json=body)  # noqa: E731
    assert put({"seconds": 30, "loops": 2, "speed": 70}).status_code == 200
    p = put({"seconds": 15.5, "speed": 60, "accuracy": 0.8}).json()
    assert p["seconds"] == 45.5 and p["loops"] == 2 and p["best_speed"] == 70
    assert p["accuracy"] == 0.8 and p["best_accuracy"] == 0.8
    assert put({"seconds": 99999}).status_code == 422
    entry = client.get("/api/score/library").json()[JOB]["piano"]
    assert entry["state"] == "done" and entry["pianoteq"] is True and entry["edited"] is False
    assert entry["practice"]["best_speed"] == 70
    assert client.get(f"/api/jobs/{JOB}/score/piano").json()["practice"]["loops"] == 2


def test_a_song_with_a_piano_gets_its_score_after_the_separation(
    client, done_job, stub_engine, monkeypatch
):
    import asyncio

    from app.api import score as api

    started = []

    async def fake_run(job, stem, source="auto"):
        started.append((job.id, stem, source))

    monkeypatch.setattr(api, "_run_async", fake_run)

    async def separated(job):
        api.prepare_after_separation(job)
        await asyncio.sleep(0)

    asyncio.run(separated(done_job))
    assert started == []  # off in the tests (conftest), as on any machine that sets it
    monkeypatch.setenv("STEMDECK_SCORE_AUTO", "1")
    done_job.stem_presence = {"piano": 5}
    asyncio.run(separated(done_job))
    assert started == []  # hardly any piano: not worth it
    done_job.stem_presence = {"piano": 80}
    asyncio.run(separated(done_job))
    assert started == [(JOB, "piano", "auto")]
    assert client.get(f"/api/jobs/{JOB}/score/piano").json()["status"]["state"] == "queued"
    api._RUNS.clear()


# -- the edit history («🕘 Historial»): kept on the server ---------------------


def _plain(notes):
    return [{k: n[k] for k in ("id", "midi", "start", "end", "velocity", "hand")} for n in notes]


def _put(client, notes, what=None):
    r = client.put(f"/api/jobs/{JOB}/score/piano/notes", json={"notes": notes, "what": what})
    assert r.status_code == 200, r.text
    return r.json()


def test_each_edit_is_kept_in_the_history_named_and_can_be_gone_back_on(
    client, done_job, stub_engine
):
    """A move made by mistake did not show in «Borradas» (only deleted notes
    do), and the page's own undo is lost on a reload. The server keeps every
    saved edit, with the notes it changed as they were and as they are."""
    data = _transcribe(client)
    original = _plain(data["notes"])
    moved = [dict(n) for n in original]
    moved[0]["start"] += 0.5
    moved[0]["end"] += 0.5
    v_move = _put(client, moved, "Movida")["version"]
    gone = moved[1:]
    v_del = _put(client, gone, "1 nota(s) borrada(s)")["version"]
    h = client.get(f"/api/jobs/{JOB}/score/piano/history").json()
    assert [e["what"] for e in h["entries"]] == ["1 nota(s) borrada(s)", "Movida"]
    assert h["entries"][0]["v"] == v_del and h["entries"][0]["before"] == 1
    move = h["entries"][1]
    assert move["v"] == v_move and move["before"] == 1 and move["after"] == 1
    assert move["notes"][0]["from"]["start"] + 0.5 == pytest.approx(move["notes"][0]["to"]["start"])
    # Back to before the move: the move and the later delete undone, saved as
    # one more edit (itself in the history: it can be gone back on in turn).
    r = client.post(f"/api/jobs/{JOB}/score/piano/history/{v_move}/undo")
    assert r.status_code == 200
    back = {n["id"]: n for n in r.json()["notes"]}
    assert len(back) == len(original)
    assert all(back[n["id"]]["start"] == pytest.approx(n["start"]) for n in original)
    h = client.get(f"/api/jobs/{JOB}/score/piano/history").json()
    assert h["entries"][0]["what"] == "Volver a antes de «Movida»"
    r = client.post(f"/api/jobs/{JOB}/score/piano/history/{h['entries'][0]['v']}/undo")
    assert len(r.json()["notes"]) == len(gone)
    # An unknown version: said, nothing changes.
    assert client.post(f"/api/jobs/{JOB}/score/piano/history/9999/undo").status_code == 404


def test_back_to_the_original_is_in_the_history_too(client, done_job, stub_engine):
    data = _transcribe(client)
    edited = _plain(data["notes"])[2:]
    _put(client, edited, "2 nota(s) borrada(s)")
    r = client.delete(f"/api/jobs/{JOB}/score/piano/notes")
    assert len(r.json()["notes"]) == len(data["notes"])
    h = client.get(f"/api/jobs/{JOB}/score/piano/history").json()
    assert h["entries"][0]["what"] == "Restaurar original (sin ediciones)"
    # Undoable: the edits are back.
    r = client.post(f"/api/jobs/{JOB}/score/piano/history/{h['entries'][0]['v']}/undo")
    assert {n["id"] for n in r.json()["notes"]} == {n["id"] for n in edited}


def test_a_save_that_changes_nothing_adds_no_entry_and_a_new_transcription_clears_it(
    client, done_job, stub_engine
):
    data = _transcribe(client)
    notes = _plain(data["notes"])
    _put(client, notes, "Nada")
    assert client.get(f"/api/jobs/{JOB}/score/piano/history").json()["entries"] == []
    _put(client, notes[1:], "Borrada")
    assert len(client.get(f"/api/jobs/{JOB}/score/piano/history").json()["entries"]) == 1
    client.post(f"/api/jobs/{JOB}/score/piano?force=true")
    for _ in range(100):
        if client.get(f"/api/jobs/{JOB}/score/piano").json()["status"]["state"] == "done":
            break
        time.sleep(0.05)
    assert client.get(f"/api/jobs/{JOB}/score/piano/history").json()["entries"] == []


def test_the_history_keeps_its_last_entries(client, done_job, stub_engine, monkeypatch):
    from app.score import store

    monkeypatch.setattr(store, "HISTORY_KEEP", 3)
    data = _transcribe(client)
    notes = _plain(data["notes"])
    for i in range(5):
        notes[0]["velocity"] = 60 + i
        _put(client, notes, f"Edición {i}")
    whats = [
        e["what"] for e in client.get(f"/api/jobs/{JOB}/score/piano/history").json()["entries"]
    ]
    assert whats == ["Edición 4", "Edición 3", "Edición 2"]


# -- Settings › Storage: sizes by kind, cleaning, what is made in the background


def _wait_flacs(folder, n):
    for _ in range(500):
        if len(list(folder.glob("*.flac"))) == n:
            return
        time.sleep(0.02)
    raise AssertionError(f"{len(list(folder.glob('*.flac')))} renders, not {n}")


def _row(client):
    data = client.get("/api/storage").json()
    return data, next(r for r in data["jobs"] if r["id"] == JOB)


def test_storage_tells_the_renders_apart_and_cleans_them_by_kind(
    client, done_job, stub_engine, fake_pianoteq, monkeypatch
):
    from app.score import store

    monkeypatch.setenv("STEMDECK_PIANOTEQ_AUTO", "1")
    _transcribe(client)
    folder = store.score_dir(JOB, "piano") / "pianoteq"
    _wait_flacs(folder, 12)
    monkeypatch.setenv("STEMDECK_PIANOTEQ_AUTO", "0")  # nothing made again behind
    data, row = _row(client)
    size = {p.name: p.stat().st_size for p in folder.glob("*.flac")}
    parts = row["parts"]
    assert parts["pt_main"] > 0 and parts["pt_hands"] > 0 and parts["pt_slow"] > 0
    assert parts["pt_old"] == 0
    assert parts["pt_main"] + parts["pt_hands"] + parts["pt_slow"] == sum(size.values())
    assert parts["stems"] > 0 and row["total"] == sum(parts.values())
    assert data["path"] and data["disk"]["free"] > 0 and data["background"] == "all"
    # Without the index (renders made before it), the same answer.
    (folder / "index.json").unlink()
    assert _row(client)[1]["parts"] == parts

    r = client.post("/api/storage/clean", json={"what": "slow", "jobs": [JOB]}).json()
    assert r["files"] == 9 and len(list(folder.glob("*.flac"))) == 3
    r = client.post("/api/storage/clean", json={"what": "hands"}).json()
    assert r["files"] == 2
    main = _row(client)[1]["parts"]
    assert main["pt_slow"] == main["pt_hands"] == 0 and main["pt_main"] > 0
    # An edit: the render left is of notes that are gone, "old".
    notes = _plain(client.get(f"/api/jobs/{JOB}/score/piano").json()["notes"])
    _put(client, notes[1:], "Borrada")
    old = _row(client)[1]["parts"]
    assert old["pt_main"] == 0 and old["pt_old"] == main["pt_main"]
    r = client.post("/api/storage/clean", json={"what": "old"}).json()
    assert r["files"] == 1 and r["bytes"] == main["pt_main"]
    assert not list(folder.glob("*.flac"))
    # The stems and the score are never touched.
    assert _row(client)[1]["parts"]["stems"] == parts["stems"]
    assert client.get(f"/api/jobs/{JOB}/score/piano").json()["status"]["state"] == "done"
    assert client.post("/api/storage/clean", json={"what": "everything"}).status_code == 422


def test_what_is_made_in_the_background_follows_the_setting(client, monkeypatch):
    from app.api import score as api

    monkeypatch.setattr(api, "pianoteq_sweep", lambda: 0)
    assert len(api._pt_variants("j", "piano")) == 12
    for value, n in (("hands", 3), ("main", 1), ("off", 0), ("all", 12)):
        r = client.put("/api/storage/background", json={"value": value})
        assert r.status_code == 200 and r.json() == {"background": value}
        assert len(api._pt_variants("j", "piano")) == n, value
    assert api._pt_variants("j", "piano")[:3] == [
        ("j", "piano", None, 1.0),
        ("j", "piano", "R", 1.0),
        ("j", "piano", "L", 1.0),
    ]
    assert client.put("/api/storage/background", json={"value": "x"}).status_code == 422


def test_storage_cleans_the_score_pages_copies_and_they_come_back(
    client, done_job, stub_engine, jobs_dir
):
    _transcribe(client)
    score = jobs_dir / JOB / "score"
    (score / "full_mix.wav").write_bytes(b"x" * 1000)
    (score / "audio").mkdir(exist_ok=True)
    (score / "audio" / "piano.flac").write_bytes(b"y" * 500)
    _, row = _row(client)
    assert row["parts"]["cache"] == 1500
    r = client.post("/api/storage/clean", json={"what": "cache", "jobs": [JOB]}).json()
    assert r == {"files": 2, "bytes": 1500}
    assert not (score / "full_mix.wav").exists() and not (score / "audio").exists()
    assert (score / "piano" / "raw.json").is_file()  # the score itself stays
