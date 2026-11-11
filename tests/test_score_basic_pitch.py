"""Basic Pitch over ONNX (app/score/basic_pitch_onnx.py), the engine for every
stem but the piano. The model ships in the repo (230 KB), so this runs
everywhere in a few seconds -- no download, no skip.
"""

from __future__ import annotations

import json

import numpy as np
import pytest

from app.score import calibration as cal
from app.score import engines

sf = pytest.importorskip("soundfile")
mir_eval = pytest.importorskip("mir_eval")


def _f1(ref, est):
    def arrays(notes):
        return (
            np.array([[n["start"], n["end"]] for n in notes]),
            np.array([440.0 * 2 ** ((n["midi"] - 69) / 12) for n in notes]),
        )

    ri, rp = arrays(ref)
    ei, ep = arrays(est)
    return mir_eval.transcription.precision_recall_f1_overlap(ri, rp, ei, ep, offset_ratio=None)


def _run(tmp_path, stem, ref):
    audio = cal.synthesize(ref)
    wav = tmp_path / f"{stem}.wav"
    sf.write(wav, np.stack([audio, audio], axis=1), 44100)
    out = tmp_path / f"{stem}.json"
    engines.transcribe(stem, wav, out)
    data = json.loads(out.read_text())
    assert data["engine"] == "basic_pitch"
    return data["notes"]


def test_bass_line(tmp_path):
    ref = [n for n in cal.notes() if n["hand_truth"] == "L"]
    est = _run(tmp_path, "bass", ref)
    p, r, f1, _ = _f1(ref, est)
    assert f1 >= 0.90, f"F1 {f1:.3f} (P {p:.3f} R {r:.3f})"
    # The bass range keeps every note within B0..G4.
    assert all(23 <= n["midi"] <= 67 for n in est)


def test_melody(tmp_path):
    ref = [n for n in cal.notes() if n["hand_truth"] == "R" and n["start"] < 9]  # bars 1-2: a scale
    est = _run(tmp_path, "vocals", ref)
    p, r, f1, _ = _f1(ref, est)
    assert f1 >= 0.90, f"F1 {f1:.3f} (P {p:.3f} R {r:.3f})"


def test_engines_table():
    assert engines.name("piano") == "piano_transcription_inference"
    assert engines.name("bass") == "basic_pitch"
    assert not engines.supports("drums")
    assert engines.default_split("bass") > 72  # a bass line sits on the F clef
    assert engines.default_split("vocals") < 48  # a melody sits on the G clef
