"""A jobs directory with one finished track whose piano is already
transcribed, for the score view's browser tests (tests/score-e2e).

The transcription is the calibration piece's exact notes (app/score/
calibration.py), written where the worker would write it, so the browser
tests exercise the real server, the real engraving and the real Verovio,
with only the model skipped.

Usage:  python tests/score-e2e/seed.py <jobs-dir>
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import numpy as np
import soundfile as sf

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from app.score import calibration as cal  # noqa: E402

JOB_ID = "5c0de0000001"
TITLE = "Score E2E (calibración)"


def seed(jobs_dir: Path) -> str:
    stems = jobs_dir / JOB_ID / "stems"
    stems.mkdir(parents=True, exist_ok=True)
    notes = cal.notes()
    audio = cal.synthesize(notes)
    sf.write(stems / "piano.wav", np.stack([audio, audio], axis=1), 44100, subtype="PCM_16")
    beats = cal.beats()
    (stems / "beats.json").write_text(
        json.dumps(
            {
                "version": 1,
                "bars": cal.bars(),
                "bpm": cal.BPM,
                "confidence": 100,
                "beats": beats,
                "onsets": beats,
            }
        ),
        encoding="utf-8",
    )
    score = jobs_dir / JOB_ID / "score" / "piano"
    score.mkdir(parents=True, exist_ok=True)
    raw = [{k: n[k] for k in ("midi", "start", "end", "velocity")} for n in notes]
    (score / "raw.json").write_text(
        json.dumps({"engine": "fixture", "notes": raw, "pedals": []}), encoding="utf-8"
    )
    record = {
        "id": JOB_ID,
        "status": "done",
        "progress": 1.0,
        "stage_message": "Done",
        "title": TITLE,
        "duration_sec": len(audio) / 44100,
        "source_url": "local:score-e2e",
        "created_at": time.time(),
        "bpm": 90,
        "key": "F",
        "scale": "Major",
        "stem_presence": {"piano": 100},
        "stems": [{"name": "piano", "url": f"/api/jobs/{JOB_ID}/stems/piano.wav"}],
    }
    (jobs_dir / "registry.json").write_text(
        json.dumps({"version": 1, "jobs": [record]}, indent=2), encoding="utf-8"
    )
    return JOB_ID


if __name__ == "__main__":
    target = Path(sys.argv[1]).expanduser().resolve()
    target.mkdir(parents=True, exist_ok=True)
    print(seed(target))
