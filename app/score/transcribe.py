"""Launch the transcription worker for one stem and follow its progress.

The checkpoint (~170 MB) is fetched on first use into MODELS_DIR. The engine's
own downloader shells out to `wget`, which Windows does not have, so the file
is fetched here and its path handed to the engine.
"""

from __future__ import annotations

import logging
import os
import re
import subprocess
import sys
import threading
import time
import urllib.request
from collections import deque
from collections.abc import Callable
from pathlib import Path

from app.core.config import MODELS_DIR

logger = logging.getLogger(__name__)

CHECKPOINT_URL = (
    "https://zenodo.org/record/4034264/files/CRNN_note_F1%3D0.9677_pedal_F1%3D0.9186.pth?download=1"
)
CHECKPOINT_NAME = "note_F1=0.9677_pedal_F1=0.9186.pth"
CHECKPOINT_MIN_BYTES = 160_000_000
TIMEOUT_SEC = int(os.environ.get("STEMDECK_TIMEOUT_SCORE", "3600"))
STALL_SEC = int(os.environ.get("STEMDECK_TIMEOUT_SCORE_STALL", "600"))

_SEGMENT_RE = re.compile(r"Segment (\d+) / (\d+)")

Progress = Callable[[str, float], None]


class TranscriptionError(RuntimeError):
    def __init__(self, message: str, tail: list[str] | None = None) -> None:
        super().__init__(message)
        self.tail = tail or []


def checkpoint_path() -> Path:
    override = os.environ.get("STEMDECK_PIANO_CHECKPOINT", "").strip()
    if override:
        return Path(override)
    return MODELS_DIR / "piano_transcription" / CHECKPOINT_NAME


def ensure_checkpoint(report: Progress | None = None) -> Path:
    path = checkpoint_path()
    if path.is_file() and path.stat().st_size >= CHECKPOINT_MIN_BYTES:
        return path
    path.parent.mkdir(parents=True, exist_ok=True)
    part = path.with_suffix(".part")
    logger.info("score: downloading piano transcription model to %s", path)
    with urllib.request.urlopen(CHECKPOINT_URL, timeout=60) as resp, part.open("wb") as fh:
        total = int(resp.headers.get("Content-Length") or 0)
        done = 0
        while chunk := resp.read(1 << 20):
            fh.write(chunk)
            done += len(chunk)
            if report and total:
                report("download", done / total)
    if part.stat().st_size < CHECKPOINT_MIN_BYTES:
        part.unlink(missing_ok=True)
        raise TranscriptionError("model download was incomplete")
    part.replace(path)
    return path


def _worker_cmd(
    audio: Path,
    out: Path,
    ckpt: Path | None,
    device: str,
    engine: str = "piano",
    min_midi: int | None = None,
    max_midi: int | None = None,
) -> list[str]:
    cmd = [
        sys.executable,
        "-m",
        "app.score.worker",
        "--engine",
        engine,
        "--audio",
        str(audio),
        "--out",
        str(out),
        "--device",
        device,
    ]
    if ckpt is not None:
        cmd += ["--checkpoint", str(ckpt)]
    if min_midi is not None:
        cmd += ["--min-midi", str(min_midi)]
    if max_midi is not None:
        cmd += ["--max-midi", str(max_midi)]
    return cmd


def run_transcription(
    audio: Path,
    out: Path,
    device: str = "cpu",
    report: Progress | None = None,
    cancelled: Callable[[], bool] | None = None,
    *,
    engine: str = "piano",
    min_midi: int | None = None,
    max_midi: int | None = None,
) -> None:
    """Blocking. Writes `out` (raw notes JSON) or raises TranscriptionError."""
    ckpt = ensure_checkpoint(report) if engine == "piano" else None
    env = os.environ.copy()
    env["PYTHONIOENCODING"] = "utf-8:replace"
    # The piano engine prints its progress unflushed; on a pipe that sat in the
    # buffer until the end (0% on the page, and the stall watchdog fired on
    # long songs). See worker.py.
    env["PYTHONUNBUFFERED"] = "1"
    proc = subprocess.Popen(
        _worker_cmd(audio, out, ckpt, device, engine, min_midi, max_midi),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
        bufsize=1,
        env=env,
    )
    tail: deque[str] = deque(maxlen=30)
    state = {"last": time.monotonic(), "phase": "load", "frac": 0.0}
    lock = threading.Lock()

    def reader() -> None:
        assert proc.stdout is not None
        for line in proc.stdout:
            line = line.rstrip()
            with lock:
                state["last"] = time.monotonic()
                tail.append(line)
                if line.startswith("PHASE "):
                    state["phase"] = (line[6:].split() or ["load"])[0]
                m = _SEGMENT_RE.search(line)
                if m and int(m.group(2)) > 0:
                    state["phase"] = "transcribe"
                    state["frac"] = min(1.0, int(m.group(1)) / int(m.group(2)))

    t = threading.Thread(target=reader, daemon=True)
    t.start()
    started = time.monotonic()
    failed = None
    try:
        while proc.poll() is None:
            if cancelled and cancelled():
                proc.kill()
                failed = "cancelled"
                break
            with lock:
                phase, frac, last = state["phase"], state["frac"], state["last"]
            if report:
                report(phase, frac)
            now = time.monotonic()
            if now - started > TIMEOUT_SEC:
                proc.kill()
                failed = f"timed out after {TIMEOUT_SEC}s"
                break
            if now - last > STALL_SEC:
                proc.kill()
                failed = f"stalled for {STALL_SEC}s"
                break
            time.sleep(0.25)
    finally:
        t.join(timeout=2)
    if failed:
        raise TranscriptionError(failed, list(tail))
    if proc.returncode != 0 or not out.is_file():
        raise TranscriptionError(f"worker exited with {proc.returncode}", list(tail))
