"""«🎷 Saxo»: a voice's line (app/score/voice_line.py) and its endpoint.

The voice's notes were read by the transcription model alone, which on a
real vocals stem had a note for 71 % of the sung time and the wrong semitone
in 15 % of it. Now its notes are checked against a pitch tracker (pYIN), and
the voice's own tuning is measured.
"""

from __future__ import annotations

import numpy as np
import pytest
import soundfile as sf

from app.score import voice_line as V


def _contour(notes, cents=0.0, vibrato=0.0, sec=V.HOP / V.SR):
    """A pitch contour in MIDI per frame, from [(start, end, midi)]."""
    n = int(max(e for _, e, _ in notes) / sec) + 10
    f = np.full(n, np.nan)
    for a, b, m in notes:
        i, j = int(a / sec), int(b / sec)
        t = np.arange(j - i) * sec
        f[i:j] = m + cents / 100 + vibrato * np.sin(2 * np.pi * 5.5 * t)
    return f


def test_the_voices_tuning_is_measured():
    f = _contour([(0, 2, 60), (2, 4, 64), (4, 6, 67)], cents=23, vibrato=0.3)
    assert abs(V.tuning_cents(f) - 23) < 3
    f = _contour([(0, 2, 60), (2, 4, 62)], cents=-31)
    assert abs(V.tuning_cents(f) + 31) < 3


def test_vibrato_does_not_make_notes_a_real_step_does():
    f = _contour([(0, 1.5, 64), (1.5, 3, 65)], vibrato=0.45)
    notes = V.notes_from(V.quantise(V.smooth(f)))
    assert [n["midi"] for n in notes] == [64, 65]
    assert abs(notes[1]["start"] - 1.5) < 0.15


def test_an_octave_slip_of_the_tracker_is_put_back():
    f = _contour([(0, 3, 67)])
    i = int(1.2 / (V.HOP / V.SR))
    f[i : i + 6] -= 12  # the tracker locked on the octave below for 70 ms
    assert np.nanmax(np.abs(V.fix_octaves(f) - 67)) < 0.01


def test_the_transcription_corrected_by_the_tracker():
    sec = V.HOP / V.SR
    q = V.quantise(_contour([(0, 1, 62), (1, 2, 64), (3, 4, 67)]))
    energy = np.ones(len(q))
    energy[int(2.1 / sec) : int(2.9 / sec)] = 0  # silence: the band left in the stem
    line = [
        {"start": 0.0, "end": 1.0, "midi": 61},  # a semitone off: corrected
        {"start": 1.0, "end": 2.0, "midi": 76},  # an octave above the tracker: kept
        {"start": 2.2, "end": 2.8, "midi": 50},  # in the voice's silence: dropped
    ]
    own = V.notes_from(q)
    out = V.merge(line, q, own, energy)
    assert [n["midi"] for n in out] == [62, 76, 67]  # 67: the tracker's, where nothing was
    assert out[-1]["start"] == pytest.approx(3.0, abs=0.05)


def test_a_sung_line_from_audio(tmp_path):
    """A synthetic voice (harmonics, vibrato, a scoop, 18 cents sharp): its
    notes, on the right semitone, and its tuning."""
    sr = V.SR
    truth = [(0.2, 0.9, 60), (0.9, 1.6, 62), (1.6, 2.6, 64), (3.0, 3.6, 67), (3.6, 4.8, 65)]
    y = np.zeros(int(5.2 * sr))
    for a, b, m in truth:
        i, j = int(a * sr), int(b * sr)
        t = np.arange(j - i) / sr
        midi = m + 0.18 + 0.3 * np.sin(2 * np.pi * 5.5 * t) * (t > 0.2)
        hz = 440 * 2 ** ((midi - 69) / 12)
        ph = 2 * np.pi * np.cumsum(hz) / sr
        tone = sum(np.sin(k * ph) / k for k in range(1, 9))
        env = np.minimum(1, np.minimum(t / 0.03, (b - a - t) / 0.05))
        y[i:j] += 0.25 * tone * env
    wav = tmp_path / "v.wav"
    sf.write(wav, y, sr)
    line = V.sung_line(wav, [{"start": a, "end": b, "midi": m} for a, b, m in truth])
    assert abs(line["cents"] - 18) < 6
    got = [n["midi"] for n in line["notes"]]
    assert got == [m for _, _, m in truth]


def test_the_endpoint_transcribes_on_its_own_then_caches(monkeypatch, tmp_path):
    """No score needed: the line's own transcription (Basic Pitch) beside the
    pitch tracking, then cached. (The full score made the user wait ~100 s
    on «Escuchando Voz… 100 %».)"""
    import json

    from fastapi.testclient import TestClient

    from app.core.models import Job
    from app.core.registry import _jobs
    from app.main import app
    from app.score import engines, store

    job = "abcdefabcd09"
    monkeypatch.setattr(store, "JOBS_DIR", tmp_path)
    _jobs[job] = Job(id=job, status="done", title="Voz")
    stems = tmp_path / job / "stems"
    stems.mkdir(parents=True)
    sf.write(stems / "vocals.wav", np.zeros((22050, 1)), 22050)
    c = TestClient(app)
    transcribed, tracked = [], []

    def fake_transcribe(stem, wav, out, report=None):
        transcribed.append(stem)
        out.write_text(json.dumps({"notes": [{"midi": 60, "start": 0, "end": 1, "velocity": 80}]}))

    def fake_line(wav, notes, analysed=None):
        tracked.append(len(notes))
        return {"notes": notes, "cents": -7.0}

    monkeypatch.setattr(engines, "transcribe", fake_transcribe)
    monkeypatch.setattr(V, "tracker", lambda: "pyin")  # the merge with a transcription
    monkeypatch.setattr(V, "analyse", lambda wav: None)
    monkeypatch.setattr(V, "sung_line", fake_line)
    try:
        assert c.get(f"/api/jobs/{job}/sax/line/piano").status_code == 404  # only voices
        r = c.get(f"/api/jobs/{job}/sax/line/vocals").json()
        assert r["cents"] == -7.0 and r["notes"][0]["midi"] == 60
        c.get(f"/api/jobs/{job}/sax/line/vocals")
        assert transcribed == ["vocals"] and tracked == [1]  # the second time from the cache
        # A score made since (edited notes) is what the line follows.
        d = store.score_dir(job, "vocals")
        (d / "raw.json").write_text(
            '{"notes": [{"midi": 62, "start": 0, "end": 1, "velocity": 80}]}'
        )
        r = c.get(f"/api/jobs/{job}/sax/line/vocals").json()
        assert r["notes"][0]["midi"] == 62
    finally:
        _jobs.pop(job, None)


def test_every_recorded_note_speaks_at_once():
    """The MIS notes often swell in (up to a second): cut where anything was
    heard, a short note in a song ended before it sounded. Every one now
    reaches half its sustained level within 0.12 s."""
    from pathlib import Path

    import librosa

    root = Path(__file__).resolve().parents[1] / "static" / "audio" / "sax"
    files = sorted(root.glob("*/*/*.mp3"))
    # alto and soprano, 32 notes: with vibrato pp mf ff (192), without mf ff (128)
    assert len(files) == 320
    for f in files[::7]:  # a sample of them (decoding all takes a while)
        y, sr = librosa.load(f, sr=22050, mono=True)
        rms = librosa.feature.rms(y=y, frame_length=512, hop_length=128)[0]
        sustain = np.median(rms[len(rms) // 4 : 3 * len(rms) // 4])
        assert np.argmax(rms >= 0.5 * sustain) * 128 / sr < 0.12, f.name


def test_with_rmvpe_the_line_is_the_trackers_own_without_a_transcription(monkeypatch, tmp_path):
    from fastapi.testclient import TestClient

    from app.core.models import Job
    from app.core.registry import _jobs
    from app.main import app
    from app.score import engines, store

    job = "abcdefabcd08"
    monkeypatch.setattr(store, "JOBS_DIR", tmp_path)
    _jobs[job] = Job(id=job, status="done", title="Voz")
    (tmp_path / job / "stems").mkdir(parents=True)
    sf.write(tmp_path / job / "stems" / "vocals.wav", np.zeros((16000, 1)), 16000)
    monkeypatch.setattr(V, "tracker", lambda: "rmvpe")
    own = [{"start": 0.0, "end": 0.5, "midi": 64, "velocity": 90}]
    monkeypatch.setattr(V, "analyse", lambda wav: (None, None, 12.0, own))
    monkeypatch.setattr(
        engines, "transcribe", lambda *a, **k: pytest.fail("no transcription with RMVPE")
    )
    try:
        r = TestClient(app).get(f"/api/jobs/{job}/sax/line/vocals").json()
        assert r["notes"] == own and r["cents"] == 12.0 and r["engine"] == "rmvpe"
        assert "contour" in r
    finally:
        _jobs.pop(job, None)


def test_rmvpe_reads_a_known_pitch():
    """When its weights are here (.run/tools/rmvpe), a 440 Hz tone is A4."""
    from app.score import rmvpe

    if not rmvpe.available():
        pytest.skip("RMVPE weights not installed")
    t = np.arange(16000 * 2) / 16000
    tone = sum(np.sin(2 * np.pi * 440 * k * t) / k for k in range(1, 6)) * 0.2
    midi, conf = rmvpe.track(tone.astype(np.float32))
    assert abs(np.nanmedian(midi) - 69) < 0.1 and np.nanmax(conf) > 0.5


def test_an_instruments_note_changes_are_not_blurred():
    """A saxophone changes note at once: its median keeps a fast run's notes
    (the voice's moving average over a vibrato period blurred them)."""
    f0 = np.full(60, np.nan)
    f0[0:12], f0[12:24], f0[24:36], f0[36:48] = 60.0, 62.0, 64.0, 65.0  # 0.12 s each
    q = V.quantise(V.smooth_instrument(f0), 0.0, V.INSTRUMENT_HOLD)
    notes = V.notes_from(q)
    assert [n["midi"] for n in notes] == [60, 62, 64, 65]


def test_the_lead_instrument_in_other_is_tracked_with_rmvpe(monkeypatch, tmp_path):
    from fastapi.testclient import TestClient

    from app.api import sax
    from app.core.models import Job
    from app.core.registry import _jobs
    from app.main import app
    from app.score import store

    job = "abcdefabcd09"
    monkeypatch.setattr(store, "JOBS_DIR", tmp_path)
    _jobs[job] = Job(id=job, status="done", title="Careless")
    (tmp_path / job / "stems").mkdir(parents=True)
    sf.write(tmp_path / job / "stems" / "other.wav", np.zeros((16000, 1)), 16000)
    own = [{"start": 0.0, "end": 0.5, "midi": 70, "velocity": 90}]
    kinds = []

    def fake_analyse(wav, kind="voice"):
        kinds.append(kind)
        return (None, None, -5.0, own)

    monkeypatch.setattr(V, "analyse", fake_analyse)
    monkeypatch.setattr(V, "tracker", lambda: "rmvpe")
    try:
        monkeypatch.setattr(sax, "_rmvpe", lambda: False)
        assert TestClient(app).get(f"/api/jobs/{job}/sax/line/other").status_code == 404
        monkeypatch.setattr(sax, "_rmvpe", lambda: True)
        r = TestClient(app).get(f"/api/jobs/{job}/sax/line/other").json()
        assert r["notes"] == own and r["engine"] == "rmvpe-instrument" and kinds == ["instrument"]
        assert TestClient(app).get(f"/api/jobs/{job}/sax/line/drums").status_code == 404
    finally:
        _jobs.pop(job, None)


def test_the_corrections_of_a_line_are_kept(monkeypatch, tmp_path):
    from fastapi.testclient import TestClient

    from app.core.models import Job
    from app.core.registry import _jobs
    from app.main import app
    from app.score import store

    job = "abcdefabcd10"
    monkeypatch.setattr(store, "JOBS_DIR", tmp_path)
    _jobs[job] = Job(id=job, status="done", title="Editada")
    c = TestClient(app)
    url = f"/api/jobs/{job}/sax/edits"
    try:
        assert c.get(url).json() == {"sets": {}}
        edits = {
            "other|12.34|65": {"del": True},
            "other|20.00|70": {"dm": -12, "dt": 0.05},
            "other|21.00|72": {"dd": 0.4},
        }
        assert c.put(url, json={"set": "other|clean", "edits": edits}).json()["count"] == 3
        assert (
            c.put(
                url, json={"set": "vocals,piano|all", "edits": {"vocals|1.00|60": {"dm": 1}}}
            ).status_code
            == 200
        )
        sets = c.get(url).json()["sets"]
        assert sets["other|clean"] == edits and sets["vocals,piano|all"] == {
            "vocals|1.00|60": {"dm": 1}
        }
        # Back to the original: the line's corrections go.
        c.put(url, json={"set": "other|clean", "edits": {}})
        assert "other|clean" not in c.get(url).json()["sets"]
        # Nonsense is refused.
        assert c.put(url, json={"set": "../x", "edits": {}}).status_code == 422
        assert (
            c.put(url, json={"set": "other|clean", "edits": {"../x": {"del": True}}}).status_code
            == 422
        )
        assert (
            c.put(
                url, json={"set": "other|clean", "edits": {"other|1.00|60": {"dm": 99}}}
            ).status_code
            == 422
        )
    finally:
        _jobs.pop(job, None)


def test_a_line_becomes_a_swam_performance():
    """Slurred notes overlap (SWAM plays the transition), the loudness rides
    Expression (CC11), the tuning and the curve ride the pitch bend, the
    tenor is sent an octave up (SWAM's tenor sounds an octave below)."""
    from app.score import swam_render as R

    data = {
        "cents": 25,
        "octave": 12,
        "notes": [
            {"start": 0.5, "end": 1.0, "midi": 60, "velocity": 90},
            {"start": 1.0, "end": 1.5, "midi": 62, "velocity": 90, "legato": True},
            {
                "start": 2.0,
                "end": 2.4,
                "midi": 64,
                "curve": {
                    "step": 0.02,
                    "midi": [63.4, 63.5, 63.7, 64, 64, 64, 64.2, 64.3, 64.3, 64.2]
                    + [64, 64, 64, 64.2, 64.3, 64.3, 64.2, 64, 64, 64],
                    "level": [0.2, 0.9, 1, 1, 0.5] * 4,
                },
            },
        ],
    }
    ev = R.events(data)
    ons = [(t, b[1]) for t, b in ev if b[0] == 0x90]
    offs = {b[1]: t for t, b in ev if b[0] == 0x80}
    assert ons == [(0.5, 72), (1.0, 74), (2.0, 76)]
    assert offs[72] > 1.0  # slurred: the first ends after the second starts
    assert offs[74] == 1.5  # not slurred into the third
    bends = [(t, (b[1] | b[2] << 7) - 8192) for t, b in ev if b[0] == 0xE0]
    assert bends[0] == (0.0, round(0.25 / 2 * 8192))  # the song's tuning
    curve_bends = [v for t, v in bends if 2.0 <= t < 2.4]
    assert curve_bends[0] < 0 and max(curve_bends) > 0  # the scoop up, the vibrato
    # The curve is absolute: the tuning is not added twice (64.3 tracked is
    # 0.05 semitones above 64 tuned 25 cents up).
    assert max(curve_bends) <= round(0.35 / 2 * 8192)
    cc = [b[2] for t, b in ev if b[0] == 0xB0 and 2.0 <= t < 2.4]
    assert cc[0] < cc[3]  # it swells in


def test_swam_breath_and_pitch_are_even():
    """The same note played again sounds the same: the breath is one level a
    note pulled to the line's middle (not the stem's loudness frame by
    frame), the attack too, and the tracker's jumps are out of the pitch."""
    from app.score import swam_render as R

    def note(start, level, midi_jitter=()):
        lv = [level + (0.3 if k % 2 else -0.3) for k in range(25)]  # pads beating under it
        mids = [65.0] * 25
        for k in midi_jitter:
            mids[k] = 66.6  # the tracker jumping to a neighbour for a frame
        return {
            "start": start,
            "end": start + 0.5,
            "midi": 65,
            "velocity": 127 if level > 0.5 else 70,
            "curve": {"step": 0.02, "midi": mids, "level": lv},
        }

    ev = R.events({"notes": [note(1, 0.9), note(2, 0.35, (8, 15)), note(3, 0.6)]})

    def body(a, b):  # past the swell in
        return [x[1][2] for x in ev if x[1][0] == 0xB0 and a + 0.08 <= x[0] < b]

    loud, soft = body(1, 1.5), body(2, 2.5)
    assert max(loud) - min(loud) <= 8  # no wobble inside a note
    assert abs(sum(loud) / len(loud) - sum(soft) / len(soft)) <= 15  # was 28+99*... : 127 vs 69
    vels = [x[1][2] for x in ev if x[1][0] == 0x90]
    assert max(vels) - min(vels) <= 20
    bends = [(x[1][1] | x[1][2] << 7) - 8192 for x in ev if x[1][0] == 0xE0 and 2.1 <= x[0] < 2.5]
    assert max(abs(v) for v in bends) < 0.2 / 2 * 8192  # the neighbour's frames gone


def test_swam_renders_are_asked_for_and_served(monkeypatch, tmp_path):
    from fastapi.testclient import TestClient

    from app.core.models import Job
    from app.core.registry import _jobs
    from app.main import app
    from app.score import store, swam

    job = "abcdefabcd11"
    monkeypatch.setattr(store, "JOBS_DIR", tmp_path)
    _jobs[job] = Job(id=job, status="done", title="Swam")
    asked = []

    def fake_request(key, folder, payload, job_id):
        asked.append((key, payload["sax"], len(payload["notes"])))
        swam.audio_path(folder, key).parent.mkdir(parents=True, exist_ok=True)
        swam.audio_path(folder, key).write_bytes(b"fLaC")
        return {"state": "done"}

    monkeypatch.setattr(
        swam, "available", lambda: {"available": True, "saxes": ["alto"], "python": True}
    )
    monkeypatch.setattr(swam, "request", fake_request)
    c = TestClient(app)
    body = {
        "sax": "alto",
        "duration": 10,
        "cents": 3,
        "notes": [{"start": 1, "end": 2, "midi": 69}],
    }
    try:
        assert c.get("/api/sax/swam").json()["available"] is True
        r = c.post(f"/api/jobs/{job}/sax/swam", json=body).json()
        assert r["state"] == "done" and asked == [(r["key"], "alto", 1)]
        assert (
            c.post(f"/api/jobs/{job}/sax/swam", json=body).json()["key"] == r["key"]
        )  # same line, same render
        assert c.get(r["url"]).content == b"fLaC"
        assert c.get(f"/api/jobs/{job}/sax/swam/{r['key']}").json()["state"] == "done"
        assert (
            c.post(f"/api/jobs/{job}/sax/swam", json={**body, "sax": "tenor"}).status_code == 404
        )  # not installed
        assert c.post(f"/api/jobs/{job}/sax/swam", json={**body, "sax": "kazoo"}).status_code == 422
        assert c.get(f"/api/jobs/{job}/sax/swam/../x").status_code == 404
    finally:
        _jobs.pop(job, None)


def test_swam_plays_the_note_asked_for(monkeypatch, tmp_path):
    """When SWAM Saxophones and its environment are installed here: a real
    render, at the pitch sent (the tenor too, an octave fixed)."""
    import time

    from app.score import swam

    monkeypatch.delenv("STEMDECK_SWAM_OFF", raising=False)
    info = swam.available()
    if not info["available"] or "tenor" not in info["saxes"]:
        pytest.skip("SWAM Saxophones not installed")
    payload = {
        "sax": "tenor",
        "duration": 2.5,
        "cents": 0,
        "notes": [{"start": 0.3, "end": 2.0, "midi": 57, "velocity": 90}],
    }
    key = swam.render_key(payload)
    swam.request(key, tmp_path, payload, "testjob00001")
    for _ in range(120):
        if swam.status(key, tmp_path)["state"] in ("done", "error"):
            break
        time.sleep(0.5)
    assert swam.status(key, tmp_path)["state"] == "done", swam.status(key, tmp_path)
    y, _ = __import__("librosa").load(swam.audio_path(tmp_path, key), sr=16000, mono=True)
    f0, _, _ = __import__("librosa").pyin(y, fmin=60, fmax=800, sr=16000, hop_length=160)
    assert abs(np.nanmedian(__import__("librosa").hz_to_midi(f0[60:190])) - 57) < 0.3


def test_swam_breath_never_stops_inside_the_next_note():
    """A note right after another (a note made longer pushes the next to
    its end): the breath stop of the first must not fall inside the second
    (a hole of no air: a cut and a knock)."""
    from app.score import swam_render as R

    ev = R.events(
        {
            "notes": [
                {"start": 1.0, "end": 2.5, "midi": 65, "velocity": 90},
                {"start": 2.5, "end": 3.0, "midi": 67, "velocity": 90},
                {"start": 3.03, "end": 3.5, "midi": 69, "velocity": 90},
                {"start": 4.0, "end": 4.5, "midi": 69, "velocity": 90},
            ]
        }
    )
    inside = [b[2] for t, b in ev if b[0] == 0xB0 and (1.0 <= t < 3.5 or 4.0 <= t < 4.5)]
    assert min(inside) > 50
    stops = [t for t, b in ev if b[0] == 0xB0 and b[2] == 0 and t > 0]
    assert any(3.5 < t < 4.0 for t in stops)  # a real rest: the air stops there


def test_a_swam_render_is_named_by_what_it_plays():
    """Asked again for what plays the same, the render already made is used
    (closing and opening the app must not render a song again); what plays
    differently is another render."""
    from app.score import swam

    def body():
        return {
            "sax": "alto",
            "duration": 6.0,
            "cents": -5.5,
            "notes": [
                {"start": 1.0, "end": 2.0, "midi": 65, "velocity": 100, "legato": False,
                 "curve": {"step": 0.02, "midi": [65.0] * 50, "level": [0.8] * 50}},
                {"start": 2.5, "end": 3.0, "midi": 67, "velocity": 90, "legato": False, "curve": None},
            ],
        }

    base = swam.render_key(body())
    same = body()
    same["notes"][0]["curve"]["level"][10] = 0.81  # the note's breath is its median: unchanged
    assert swam.render_key(same) == base
    other = body()
    other["notes"][1]["midi"] = 68
    assert swam.render_key(other) != base
    tenor = body()
    tenor["sax"] = "tenor"
    assert swam.render_key(tenor) != base


def test_swam_is_set_steady_and_a_render_already_there_is_used(tmp_path):
    """SWAM's own random dynamics and dynamic pitch are off (the line has the
    player's), the settings are part of what names a render, and a render
    already made is the answer (and counts as used: the last one pruned)."""
    from app.score import swam

    payload = {"sax": "alto", "duration": 4.0, "cents": 0.0,
               "notes": [{"start": 1.0, "end": 2.0, "midi": 69, "velocity": 80, "legato": False, "curve": None}]}
    params = swam.plugin_params(payload)
    assert params["Random Dynamic"] == 0.0 and params["Dynamic Pitch"] == 0.0
    assert swam._performance(payload)["params"] == params
    key = swam.render_key(payload)
    swam.audio_path(tmp_path, key).write_bytes(b"fLaC")
    assert swam.request(key, tmp_path, payload, "abcdefabcd12") == {"state": "done"}
    assert swam.status(key, tmp_path) == {"state": "done"}
