"""The real piano model on the synthesized calibration piece.

Slow (~30-60 s on a CPU) and needs the 170 MB checkpoint, so it runs only when
the checkpoint is already on disk or STEMDECK_TEST_SCORE_MODEL=1 asks for the
download. The bar is note-level F1 (onsets within 50 ms, pitch exact):
>= 0.90. On this piece the model scores ~0.97.
"""

from __future__ import annotations

import json
import os

import numpy as np
import pytest

from app.score import calibration as cal
from app.score.transcribe import checkpoint_path, run_transcription

_HAVE = checkpoint_path().is_file() or os.environ.get("STEMDECK_TEST_SCORE_MODEL") == "1"


def _cuda() -> bool:
    try:
        import torch

        return torch.cuda.is_available()
    except Exception:  # noqa: BLE001
        return False


@pytest.mark.skipif(not _HAVE, reason="piano checkpoint not downloaded")
@pytest.mark.parametrize(
    "device",
    ["cpu", pytest.param("cuda", marks=pytest.mark.skipif(not _cuda(), reason="no CUDA torch"))],
)
def test_model_transcribes_the_calibration_piece(tmp_path, device):
    mir_eval = pytest.importorskip("mir_eval")
    sf = pytest.importorskip("soundfile")
    ref = cal.notes()
    audio = cal.synthesize(ref)
    wav = tmp_path / "piano.wav"
    sf.write(wav, np.stack([audio, audio], axis=1), 44100)
    out = tmp_path / "raw.json"
    run_transcription(wav, out, device)
    est = json.loads(out.read_text())["notes"]

    def arrays(notes):
        return (
            np.array([[n["start"], n["end"]] for n in notes]),
            np.array([440.0 * 2 ** ((n["midi"] - 69) / 12) for n in notes]),
        )

    ri, rp = arrays(ref)
    ei, ep = arrays(est)
    p, r, f1, _ = mir_eval.transcription.precision_recall_f1_overlap(
        ri, rp, ei, ep, offset_ratio=None
    )
    assert f1 >= 0.90, f"F1 {f1:.3f} (P {p:.3f} R {r:.3f})"
