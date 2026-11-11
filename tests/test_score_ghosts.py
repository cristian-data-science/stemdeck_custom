"""Ghost notes (app/score/ghosts.py): notes the model writes where the audio
has no attack start out deleted, restorable from «Notas borradas»."""

from __future__ import annotations

import numpy as np
import pytest
import soundfile as sf

from app.score import ghosts, store


def _n(midi, start, end, velocity=70):
    return {"midi": midi, "start": start, "end": end, "velocity": velocity}


def test_a_held_key_struck_again_without_attack_is_merged_a_real_one_kept():
    notes = [_n(40, 0.0, 1.0), _n(40, 1.0, 2.0), _n(59, 1.0, 1.4), _n(59, 1.4, 1.8)]
    gains = [(12.0, 15.0), (-0.6, 0.4), (7.0, 10.0), (0.1, 8.9)]  # E1 ghost; B3 dip-and-rise: real
    counts = ghosts.mark(notes, gains)
    assert counts == {"merged": 1, "dropped": 0}
    assert notes[1]["ghost"] == "merge" and "ghost" not in notes[3]


def test_a_soft_loose_note_without_attack_is_dropped_a_loud_one_kept():
    notes = [_n(64, 0.0, 0.5, velocity=30), _n(67, 1.0, 1.5, velocity=80)]
    counts = ghosts.mark(notes, [(0.2, 1.0), (0.2, 1.0)])
    assert counts == {"merged": 0, "dropped": 1}
    assert notes[0]["ghost"] == "drop" and "ghost" not in notes[1]


def test_a_weak_attack_the_model_barely_heard_is_dropped_or_merged():
    """Cry from 1:02: soft re-strikes of G5/D5/F#5 between the real notes.
    The model's own onset confidence under 0.6 and little rise in the audio."""
    notes = [
        {**_n(79, 64.16, 64.32, 84), "onset": 0.70},  # the real G5 (confident, clear attack)
        {**_n(79, 64.56, 64.75, 65), "onset": 0.41},  # a re-strike of it a little later
        {**_n(74, 64.59, 64.65, 55), "onset": 0.49},  # a loose D5
        {**_n(74, 64.65, 64.90, 64), "onset": 0.84},  # confident: kept, whatever the gain
        {**_n(67, 66.09, 66.98, 70), "onset": 0.89},  # G4: clear
    ]
    gains = [(7.7, 12.4), (0.5, 5.1), (0.0, 4.4), (2.7, 5.4), (10.1, 11.4)]
    counts = ghosts.mark(notes, gains)
    assert [n.get("ghost") for n in notes] == [None, "drop", "drop", None, None]
    assert counts == {"merged": 0, "dropped": 2}
    # Without the model's confidence (an older transcription) nothing changes.
    plain = [{k: v for k, v in n.items() if k != "onset"} for n in notes]
    assert ghosts.mark(plain, gains) == {"merged": 0, "dropped": 0}


def test_bleed_only_for_soft_notes_much_louder_in_the_voice():
    notes = [_n(72, 0, 1, velocity=40), _n(72, 2, 3, velocity=80), _n(60, 4, 5, velocity=40)]
    assert ghosts.mark_bleed(notes, [-20.0, -20.0, -5.0]) == 1
    assert notes[0]["ghost"] == "drop" and notes[0]["ghost_why"] == "bleed"
    assert "ghost" not in notes[1] and "ghost" not in notes[2]


def test_bleed_is_checked_against_the_voice_stem_and_only_for_a_stem(tmp_path):
    stems = tmp_path / "stems"
    stems.mkdir()
    for name in ("piano", "vocals", "guitar"):
        (stems / f"{name}.wav").write_bytes(b"")
    assert ghosts.bleed_sources(stems, stems / "piano.wav") == [stems / "vocals.wav"]
    assert ghosts.bleed_sources(stems, tmp_path / "score" / "full_mix.wav") == []


def test_attack_gains_tell_a_new_strike_from_a_ringing_note(tmp_path):
    sr = 44100
    t = np.arange(int(sr * 3.0)) / sr
    a3 = 220.0
    y = np.zeros_like(t)
    for start in (0.5, 2.0):  # struck at 0.5 s and again at 2.0 s
        k = t >= start
        y[k] += 0.4 * np.exp(-(t[k] - start) * 1.5) * np.sin(2 * np.pi * a3 * (t[k] - start))
    wav = tmp_path / "a.wav"
    sf.write(wav, y, sr)
    notes = [_n(57, 0.5, 1.2), _n(57, 1.2, 2.0), _n(57, 2.0, 2.8)]  # 1.2: the model's re-strike
    g = ghosts.attack_gains(notes, wav)
    assert g[0][0] > 6 and g[2][0] > 1  # real strikes rise
    assert g[1][0] < ghosts.GAIN_DB and g[1][1] < ghosts.RISE_DB  # the ghost does not


def test_notes_start_without_ghosts_listed_as_deleted_and_reset_keeps_them(tmp_path, monkeypatch):
    raw = {
        "notes": [
            _n(40, 0.0, 1.0),
            _n(40, 1.0, 2.0) | {"ghost": "merge"},
            _n(72, 0.5, 0.9, velocity=30) | {"ghost": "drop", "ghost_why": "bleed"},
            _n(64, 0.2, 0.21),  # a blip: auto-clean as before
        ]
    }
    doc = store.initial_notes(raw)
    assert [n["id"] for n in doc["notes"]] == ["n00000"]
    assert doc["notes"][0]["end"] == 2.0  # the re-strike gave its time back
    assert {t["id"]: t["reason"] for t in doc["trash"]} == {"n00001": "ghost", "n00002": "bleed"}
    assert doc["auto_clean"]["ghosts"] == 2 and doc["auto_clean"]["removed"] == 1

    monkeypatch.setattr(store, "JOBS_DIR", tmp_path)
    d = store.score_dir("j1", "piano")
    d.mkdir(parents=True)
    store.write_json(d / "raw.json", raw)
    store.write_json(
        d / "notes.json", {**doc, "trash": doc["trash"] + [{"id": "n00009", "midi": 50}]}
    )
    again = store.reset_notes("j1", "piano")
    assert {t["id"] for t in again["trash"]} == {"n00001", "n00002", "n00009"}


@pytest.mark.parametrize("bad", [{}, {"notes": []}])
def test_annotate_never_fails(tmp_path, bad):
    out = ghosts.annotate(dict(bad), tmp_path / "missing.wav")
    assert "notes" not in bad or out["notes"] == []
