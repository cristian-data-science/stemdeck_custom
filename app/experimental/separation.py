"""Experimental: BS-RoFormer SW as a second separation model.

Chosen at import (the composer's «Modelo», Job.separator, used by
pipeline/separate.py) or afterwards, for a song already separated, as a copy
made with the other model (copy_job; the song itself never changes).

Demucs (htdemucs_6s, the app's separator) does not know a cumbia keyboard:
in "Y Dime" (Agrupación Marilyn) it split it between guitar, other and piano
as the song went on (piano presence 2/100). BS-RoFormer SW (jarredou; 6
stems: vocals, drums, bass, guitar, piano, other) put all of it in piano, and
the user heard it clean (2026-10-31).

Isolated like Audiveris: the inference package (bs-roformer-infer, MIT) is
unpacked in .run/tools/roformer/lib and its checkpoint (~700 MB, SHA-256
checked on download) in .run/tools/roformer/models; it runs as a separate
process on the app's own torch. The song asked for is not changed: a new
track is made beside it, as «re-split» already does, with the same sections,
beat grid, lyrics and tags (same recording).
"""

from __future__ import annotations

import logging
import os
import secrets
import shutil
import subprocess
import sys
import tempfile
from dataclasses import fields
from pathlib import Path

from app.core.config import JOBS_DIR, STEM_NAMES

logger = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parents[2]
TOOL_DIR = Path(os.environ.get("STEMDECK_ROFORMER", ROOT / ".run" / "tools" / "roformer"))
CHECKPOINT = "BS-Rofo-SW-Fixed.ckpt"
TIMEOUT_SEC = 30 * 60
MODELS = {"demucs": "Demucs", "roformer": "RoFormer"}
TITLE_SUFFIX = " — separador {}"


class SeparationError(RuntimeError):
    pass


def available() -> bool:
    """The package and its checkpoint are where the experiment expects them."""
    return (TOOL_DIR / "lib" / "bs_roformer").is_dir() and any(
        (TOOL_DIR / "models").glob(f"*/{CHECKPOINT}")
    )


def _device() -> str:
    try:
        from app.score.engines import device_for

        return device_for()
    except Exception:  # noqa: BLE001
        return "cpu"


def separate(audio: Path, out_dir: Path, device: str | None = None) -> dict[str, Path]:
    """The six stems of `audio` in out_dir, by BS-RoFormer SW. Blocking."""
    import soundfile as sf

    if not available():
        raise SeparationError("el separador RoFormer no está instalado")
    work = Path(tempfile.mkdtemp(prefix="stemdeck-rofo-"))
    try:
        src = work / "in"
        src.mkdir()
        # The tool reads every .wav of a folder: one file, as WAV (a YouTube
        # download or an upload may be m4a, opus, mp3...: ffmpeg, as the app).
        if audio.suffix.lower() == ".wav":
            shutil.copyfile(audio, src / "song.wav")
        else:
            subprocess.run(
                ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-i", str(audio),
                 "-ar", "44100", "-ac", "2", str(src / "song.wav")],
                check=True, capture_output=True,
                creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0,
            )  # fmt: skip
        env = os.environ.copy()
        env.update(
            PYTHONPATH=str(TOOL_DIR / "lib"),
            BS_ROFORMER_MODELS_PATH=str(TOOL_DIR / "models"),
            PYTHONIOENCODING="utf-8",
        )
        flags = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
        cmd = [
            sys.executable,
            "-m",
            "bs_roformer.inference",
            "--input_folder",
            str(src),
            "--store_dir",
            str(work / "out"),
            "--device",
            device or _device(),
        ]
        done = subprocess.run(
            cmd,
            env=env,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=TIMEOUT_SEC,
            creationflags=flags,
            check=False,
        )
        out_dir.mkdir(parents=True, exist_ok=True)
        stems = {}
        for name in STEM_NAMES:
            f = work / "out" / f"song_{name}.wav"
            if not f.is_file():
                tail = (done.stderr or done.stdout or "")[-600:]
                raise SeparationError(f"el separador no produjo {name}: {tail}")
            # As the app's own stems: 16-bit PCM.
            data, sr = sf.read(f)
            dest = out_dir / f"{name}.wav"
            sf.write(dest, data.clip(-1, 1), sr, subtype="PCM_16")
            stems[name] = dest
        return stems
    finally:
        shutil.rmtree(work, ignore_errors=True)


def separate_demucs(audio: Path, out_dir: Path, device: str | None = None) -> None:
    """The six stems by Demucs (htdemucs_6s), as the app's pipeline makes them:
    its own worker, one job. Blocking."""
    import json

    from app.core.config import DEMUCS_MODEL

    work = Path(tempfile.mkdtemp(prefix="stemdeck-demucs-"))
    try:
        req = json.dumps({"source": str(audio), "job_dir": str(work), "shifts": 1})
        flags = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
        done = subprocess.run(
            [sys.executable, "-m", "app.pipeline.demucs_worker", device or _device()],
            input=req + "\n", capture_output=True, text=True, encoding="utf-8", errors="replace",
            timeout=TIMEOUT_SEC, creationflags=flags, check=False, cwd=str(ROOT),
        )  # fmt: skip
        got = work / DEMUCS_MODEL / audio.stem
        out_dir.mkdir(parents=True, exist_ok=True)
        for name in STEM_NAMES:
            f = got / f"{name}.wav"
            if not f.is_file():
                raise SeparationError(f"Demucs no produjo {name}: {(done.stderr or '')[-600:]}")
            shutil.move(str(f), out_dir / f"{name}.wav")
    finally:
        shutil.rmtree(work, ignore_errors=True)


def other_model(job) -> str:
    """The model that did not separate this song."""
    return "demucs" if getattr(job, "separator", "demucs") == "roformer" else "roformer"


def copy_job(job_id: str, report=None, model: str | None = None) -> dict:
    """A new library track: `job_id`'s audio separated by `model` (by default
    the one that did not make it). The original is not touched. Returns
    {"job_id", "title", "stem_presence", "model"}."""
    from app.core.models import Job
    from app.core.registry import get as registry_get
    from app.core.registry import persist as registry_persist
    from app.core.registry import register as registry_register
    from app.pipeline.collect import compute_stem_peaks
    from app.pipeline.runner import _presence_from_rms
    from app.score import store

    job = registry_get(job_id)
    if job is None or job.status != "done":
        raise SeparationError("la canción no está lista")
    audio = store.source_audio(job_id)
    if audio is None:
        raise SeparationError("no hay audio de la canción para separar")

    model = model or other_model(job)
    if model not in MODELS:
        raise SeparationError(f"modelo desconocido: {model}")
    say = report or (lambda phase: None)
    new_id = secrets.token_hex(6)
    src_dir, dst_dir = JOBS_DIR / job_id, JOBS_DIR / new_id
    try:
        say("separating")
        if model == "roformer":
            separate(audio, dst_dir / "stems")
        else:
            separate_demucs(audio, dst_dir / "stems")
        say("finishing")
        stems_dir = dst_dir / "stems"
        # The full mix (as the mixer's "mix" track) and what depends only on
        # the recording: beat grid, lyrics, metadata.
        mix = src_dir / "stems" / "mix.wav"
        if mix.is_file():
            shutil.copyfile(mix, stems_dir / "mix.wav")
        for name in ("beats.json",):
            if (src_dir / "stems" / name).is_file():
                shutil.copyfile(src_dir / "stems" / name, stems_dir / name)
        for name in ("metadata.json", "lyrics.json", "lyrics_transcript.json"):
            if (src_dir / name).is_file():
                shutil.copyfile(src_dir / name, dst_dir / name)
        rms = compute_stem_peaks(stems_dir, list(STEM_NAMES))
        presence = _presence_from_rms(rms)

        keep = {f.name for f in fields(Job)}
        same = {
            k: getattr(job, k)
            for k in keep
            if k
            not in {
                "id", "status", "progress", "stage_message", "stems", "selected_stems", "mix_url",
                "stem_presence", "source_url", "created_at", "trashed_at", "favorite",
                "queue_position", "resume_attempts", "cancel_requested", "stop_requested",
                "version", "vocal_split", "error", "error_detail", "stage_timings",
                "compute_device", "gpu_fallback", "has_video", "video_status", "separator", "title",
            }
        }  # fmt: skip
        new = Job(
            **same,
            id=new_id,
            status="done",
            progress=1.0,
            stage_message="Done",
            stems=[{"name": s, "url": f"/api/jobs/{new_id}/stems/{s}.wav"} for s in STEM_NAMES],
            selected_stems=list(STEM_NAMES),
            stem_presence=presence,
            separator=model,
            # Distinct, so the library shows it beside the original (as re-split does).
            source_url=f"{job.source_url or 'local:track'} ({model} {new_id[:6]})",
            title=_base_title(job.title) + TITLE_SUFFIX.format(MODELS[model]),
        )
        registry_register(new)
        registry_persist(JOBS_DIR)
        return {"job_id": new_id, "title": new.title, "stem_presence": presence, "model": model}
    except Exception:
        shutil.rmtree(dst_dir, ignore_errors=True)
        raise


def _base_title(title: str | None) -> str:
    """The song's title without a copy's " — separador X" (a copy of a copy
    does not pile them up)."""
    t = title or "Canción"
    for name in MODELS.values():
        t = t.removesuffix(TITLE_SUFFIX.format(name))
    return t
