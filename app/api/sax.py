"""«🎷 Saxo»: the rest of the song, to play the saxified line over.

GET /jobs/{id}/sax/backing.flac?without=vocals,piano
    The song's stems mixed, but for the ones the saxophone plays instead.
    Cached beside the score page's copies (score/audio/, cleaned as "cache"
    in Settings › Storage); made again when a stem is newer.
GET /jobs/{id}/sax/line/{stem}
    A voice's line (vocals, lead_vocals, backing_vocals) from a pitch tracker
    (app/score/voice_line.py), and the voice's tuning; with RMVPE, also the
    line of "other", where a lead instrument ends up (a saxophone, a trumpet,
    a violin: the separator has no stem of its own for them), read as an
    instrument. Cached in score/<stem>/sax_line.json.

The piano's, guitar's and bass's lines are worked out in the page
(static/js/sax/melody.js) from the notes the score module transcribed.
"""

from __future__ import annotations

import asyncio
import re
import subprocess
import sys
import threading
from pathlib import Path

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel, Field

from app.core.config import JOB_ID_RE, STEM_NAMES
from app.core.registry import get as registry_get
from app.score import store

router = APIRouter()
_LOCK = threading.Lock()
SPLIT = ("lead_vocals", "backing_vocals")  # the vocals, split on demand (vocal_split.py)


def backing_parts(stems_dir: Path, without: set[str]) -> list[Path]:
    """The stem files that stay. A split voice counts as its two halves: the
    saxophone playing the lead voice leaves the backing voices in."""
    names = list(STEM_NAMES)
    split = all((stems_dir / f"{s}.wav").is_file() for s in SPLIT)
    if split and without & set(SPLIT):
        names.remove("vocals")
        names += [s for s in SPLIT]
    keep = [n for n in names if n not in without and not (n == "vocals" and "vocals" in without)]
    return [stems_dir / f"{n}.wav" for n in keep if (stems_dir / f"{n}.wav").is_file()]


def _mix(parts: list[Path], dest: Path) -> None:
    from app.core.config import ffmpeg_executable

    if dest.is_file() and all(dest.stat().st_mtime >= p.stat().st_mtime for p in parts):
        return
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_name(f".{dest.name}.part.flac")
    cmd = [ffmpeg_executable(), "-nostdin", "-loglevel", "error", "-y"]
    for p in parts:
        cmd += ["-i", str(p)]
    if len(parts) > 1:
        inputs = "".join(f"[{i}:a]" for i in range(len(parts)))
        cmd += ["-filter_complex", f"{inputs}amix=inputs={len(parts)}:normalize=0"]
    cmd += ["-ar", "44100", "-c:a", "flac", str(tmp)]
    subprocess.run(
        cmd,
        check=True,
        capture_output=True,
        stdin=subprocess.DEVNULL,
        creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0,
    )
    tmp.replace(dest)


@router.get("/jobs/{job_id}/sax/backing.flac")
async def sax_backing(
    job_id: str, without: str = Query(default="", max_length=200)
) -> FileResponse:
    if not JOB_ID_RE.match(job_id) or registry_get(job_id) is None:
        raise HTTPException(status_code=404, detail="job not found")
    names = {n for n in without.split(",") if n}
    if any(not re.fullmatch(r"[a-z_]{2,20}", n) for n in names):
        raise HTTPException(status_code=422, detail="bad stem name")
    stems_dir = store.JOBS_DIR / job_id / "stems"
    parts = backing_parts(stems_dir, names)
    if not parts:
        raise HTTPException(status_code=404, detail="nothing else in this song")
    key = "-".join(sorted(names)) or "all"
    dest = store.JOBS_DIR / job_id / "score" / "audio" / f"backing-{key}.flac"

    def make() -> None:
        with _LOCK:
            _mix(parts, dest)

    await asyncio.to_thread(make)
    return FileResponse(dest, media_type="audio/flac", headers={"Cache-Control": "no-cache"})


VOICES = ("vocals", "lead_vocals", "backing_vocals")
# Stems whose lead instrument is tracked like a voice (one pitch at a time,
# robust to what plays under it). On a known saxophone line over pads and a
# bass, Basic Pitch's top notes had 40-45 % of the notes right (pads' top
# notes, octave slips), RMVPE 67-81 %. Only with RMVPE (pYIN is not robust
# to the band); without it, the page uses the score's transcription.
LEADS = ("other",)
_LINE_LOCK = threading.Lock()  # one pitch tracking at a time (a CPU's worth)
LINE_VERSION = 4  # bump when voice_line changes: cached lines are made again


def _transcribed(job_id: str, stem: str, wav: Path) -> list[dict]:
    """The stem's notes: its score's (edited, if it was), else a transcription
    made here (Basic Pitch, ~8 s; kept as score/<stem>/sax_bp.json) without
    the rest of the score's work (the pulse, ghost notes, engraving: ~35 s
    more the saxophone does not need)."""
    from app.score import engines

    doc = store.read_notes(job_id, stem)
    if doc is not None:
        return doc.get("notes") or []
    d = store.score_dir(job_id, stem)
    own = d / "sax_bp.json"
    if not own.is_file() or own.stat().st_mtime < wav.stat().st_mtime:
        d.mkdir(parents=True, exist_ok=True)
        engines.transcribe(stem, wav, own)
    return (store.read_json(own) or {}).get("notes") or []


def _line(job_id: str, stem: str) -> dict:
    from concurrent.futures import ThreadPoolExecutor

    from app.score import voice_line

    wav = store.stem_wav(job_id, stem)
    if not wav.is_file():
        raise HTTPException(status_code=404, detail="no such stem in this song")
    d = store.score_dir(job_id, stem)
    cache = d / "sax_line.json"
    src = [wav, d / "raw.json", d / "notes.json"]
    newest = max(p.stat().st_mtime for p in src if p.is_file())
    with _LINE_LOCK:
        old = store.read_json(cache)
        if old and old.get("v") == LINE_VERSION and cache.stat().st_mtime >= newest:
            return old
        if stem in LEADS:
            data = voice_line.tracked_line(
                wav, voice_line.analyse(wav, "instrument"), kind="instrument"
            )
        elif voice_line.tracker() == "rmvpe":
            # RMVPE's own notes beat the merge with a transcription (see
            # voice_line.tracked_line): ~2 s a song, no transcription.
            data = voice_line.tracked_line(wav, voice_line.analyse(wav))
        else:
            # The transcription and the pitch tracking at once (each ~6-8 s).
            with ThreadPoolExecutor(2) as ex:
                notes = ex.submit(_transcribed, job_id, stem, wav)
                analysed = ex.submit(voice_line.analyse, wav)
                data = voice_line.sung_line(wav, notes.result(), analysed.result())
        data["contour"] = voice_line.contour(wav)
        data["v"] = LINE_VERSION
        d.mkdir(parents=True, exist_ok=True)
        store.write_json(cache, data)
        return data


# The voices' lines, made in the background (after a separation, and every
# song's at startup): opening «🎷 Saxo» then finds them ready.
_SOON: list[tuple[str, str]] = []
_SOON_LOCK = threading.Lock()
_SOON_RUNNING = False
MIN_PRESENCE = 20  # a voice quieter than this in the song (presence %) is not worth it


def _rmvpe() -> bool:
    from app.score import rmvpe

    return rmvpe.available()


def sax_soon(job_ids: list[str], front: bool = False) -> None:
    """Queue the voices' lines of these songs (those with a voice)."""
    import os

    global _SOON_RUNNING
    if os.environ.get("STEMDECK_SAX_AUTO", "1") == "0":
        return
    tasks = []
    for job_id in job_ids:
        job = registry_get(job_id)
        if job is None or job.status != "done" or getattr(job, "trashed_at", None):
            continue
        presence = job.stem_presence or {}
        for stem in VOICES + (LEADS if _rmvpe() else ()):
            if (
                presence.get(stem, 100 if stem != "vocals" else 0) >= MIN_PRESENCE
            ) and store.stem_wav(job_id, stem).is_file():
                tasks.append((job_id, stem))
    with _SOON_LOCK:
        for t in tasks:
            if t in _SOON:
                _SOON.remove(t)
        _SOON[:0] = tasks if front else []
        if not front:
            _SOON.extend(tasks)
        if _SOON_RUNNING or not _SOON:
            return
        _SOON_RUNNING = True
    threading.Thread(target=_soon_loop, daemon=True, name="sax-lines").start()


def _soon_loop() -> None:
    global _SOON_RUNNING
    import logging

    log = logging.getLogger(__name__)
    while True:
        with _SOON_LOCK:
            if not _SOON:
                _SOON_RUNNING = False
                return
            job_id, stem = _SOON.pop(0)
        try:
            _line(job_id, stem)
        except Exception as exc:  # noqa: BLE001 -- a head start only
            log.warning("sax line of %s/%s skipped: %s", job_id, stem, exc)


def sax_sweep() -> int:
    """Every song's voice line, in the background (startup)."""
    from app.core.registry import all_jobs

    ids = [j for j, job in all_jobs().items() if job.status == "done"]
    sax_soon(ids)
    return len(ids)


@router.get("/jobs/{job_id}/sax/line/{stem}")
async def sax_line(job_id: str, stem: str) -> JSONResponse:
    if not JOB_ID_RE.match(job_id) or registry_get(job_id) is None:
        raise HTTPException(status_code=404, detail="job not found")
    if stem not in VOICES + LEADS:
        raise HTTPException(status_code=404, detail="no tracked line for this stem")
    if stem in LEADS and not await asyncio.to_thread(_rmvpe):
        raise HTTPException(status_code=404, detail="a lead instrument needs RMVPE")
    return JSONResponse(await asyncio.to_thread(_line, job_id, stem))


# «✏️ Editar» in «🎷 Saxo»: the player's corrections of a line (notes taken
# out, moved in pitch or in time, made longer or shorter), per line (the stems it plays and its
# phrasing: "other|clean"). Each note is named by its stem, its start and
# its concert pitch before any edit ("other|12.34|65"), so a correction
# outlives a change of saxophone. Kept in score/sax_edits.json (not cache).

EDIT_SET_RE = re.compile(r"[a-z_,]{2,120}\|[a-z]{2,10}")
EDIT_KEY_RE = re.compile(r"[a-z_]{2,20}\|-?\d{1,5}\.\d{2}\|\d{1,3}")
MAX_EDITS = 5000


class EditsBody(BaseModel):
    set: str = Field(max_length=140)
    edits: dict[str, dict[str, float | int | bool]] = Field(default_factory=dict)


def _edits_file(job_id: str) -> Path:
    return store.JOBS_DIR / job_id / "score" / "sax_edits.json"


@router.get("/jobs/{job_id}/sax/edits")
async def get_sax_edits(job_id: str) -> JSONResponse:
    if not JOB_ID_RE.match(job_id) or registry_get(job_id) is None:
        raise HTTPException(status_code=404, detail="job not found")
    data = store.read_json(_edits_file(job_id)) or {}
    return JSONResponse({"sets": data.get("sets") or {}})


@router.put("/jobs/{job_id}/sax/edits")
async def put_sax_edits(job_id: str, body: EditsBody) -> JSONResponse:
    if not JOB_ID_RE.match(job_id) or registry_get(job_id) is None:
        raise HTTPException(status_code=404, detail="job not found")
    if not EDIT_SET_RE.fullmatch(body.set):
        raise HTTPException(status_code=422, detail="bad line name")
    if len(body.edits) > MAX_EDITS:
        raise HTTPException(status_code=422, detail="too many edits")
    clean: dict[str, dict] = {}
    for key, e in body.edits.items():
        if not EDIT_KEY_RE.fullmatch(key):
            raise HTTPException(status_code=422, detail="bad note name")
        out: dict = {}
        if e.get("del"):
            out["del"] = True
        # A note the player put in («＋ Nota»): named "add|start|pitch", its
        # length here; moved and stretched like any other.
        if e.get("add") and key.startswith("add|"):
            length = round(float(e.get("len") or 0.4), 3)
            if not 0.05 <= length <= 30:
                raise HTTPException(status_code=422, detail="edit out of range")
            out["add"] = True
            out["len"] = length
        dm = int(e.get("dm") or 0)
        dt = round(float(e.get("dt") or 0), 3)
        dd = round(float(e.get("dd") or 0), 3)  # longer (+) or shorter (-), s
        if not (-36 <= dm <= 36 and -30 <= dt <= 30 and -30 <= dd <= 30):
            raise HTTPException(status_code=422, detail="edit out of range")
        if dm:
            out["dm"] = dm
        if dt:
            out["dt"] = dt
        if dd:
            out["dd"] = dd
        if out:
            clean[key] = out

    def save() -> None:
        with _LOCK:
            path = _edits_file(job_id)
            data = store.read_json(path) or {}
            sets = data.get("sets") or {}
            if clean:
                sets[body.set] = clean
            else:
                sets.pop(body.set, None)
            store.write_json(path, {"sets": sets})

    await asyncio.to_thread(save)
    return JSONResponse({"ok": True, "count": len(clean)})


# «🎷 Saxo» played by SWAM Saxophones (app/score/swam.py): the page sends the
# line as it plays it (phrased, in the saxophone's range, with its edits and
# its curves) and plays the render under the song when it is back.


class SwamCurve(BaseModel):
    step: float = Field(gt=0.004, lt=0.25)
    midi: list[float] = Field(max_length=4000)
    level: list[float] = Field(max_length=4000)


class SwamNote(BaseModel):
    start: float = Field(ge=0, le=3600)
    end: float = Field(ge=0, le=3600)
    midi: int = Field(ge=20, le=110)
    velocity: int = Field(default=80, ge=1, le=127)
    legato: bool = False
    curve: SwamCurve | None = None


class SwamBody(BaseModel):
    sax: str = Field(pattern=r"^(alto|tenor|soprano|baritone)$")
    duration: float = Field(gt=0, le=3600)
    cents: float = Field(default=0, ge=-60, le=60)
    notes: list[SwamNote] = Field(max_length=8000)
    room: str = Field(default="medium", pattern=r"^(dry|medium|large)$")  # «Sala»
    tone: str = Field(default="clean", pattern=r"^(clean|soft|growl)$")  # «Tono»
    # The stem the line is of: the render is made as loud as it is in the song.
    stem: str | None = Field(default=None, pattern=r"^[a-z_]{2,20}$")


def _swam_folder(job_id: str) -> Path:
    return store.JOBS_DIR / job_id / "score" / "audio"


def _swam_url(job_id: str, key: str) -> str:
    return f"/api/jobs/{job_id}/sax/swam/{key}/audio.flac"


@router.get("/sax/swam")
async def swam_info() -> JSONResponse:
    from app.score import swam

    return JSONResponse(await asyncio.to_thread(swam.available))


@router.post("/jobs/{job_id}/sax/swam")
async def swam_render(job_id: str, body: SwamBody) -> JSONResponse:
    from app.score import swam

    if not JOB_ID_RE.match(job_id) or registry_get(job_id) is None:
        raise HTTPException(status_code=404, detail="job not found")
    info = await asyncio.to_thread(swam.available)
    if body.sax not in info["saxes"]:
        raise HTTPException(status_code=404, detail="SWAM Saxophones not found")
    payload = body.model_dump()
    stem = payload.pop("stem", None)
    if stem:
        level = await asyncio.to_thread(
            swam.stem_level_db, store.stem_wav(job_id, stem), payload["notes"]
        )
        if level is not None:
            payload["level_db"] = level
    key = swam.render_key(payload)
    st = swam.request(key, _swam_folder(job_id), payload, job_id)
    return JSONResponse({"key": key, **st, "url": _swam_url(job_id, key)})


@router.get("/jobs/{job_id}/sax/swam/{key}")
async def swam_status(job_id: str, key: str) -> JSONResponse:
    from app.score import swam

    if not JOB_ID_RE.match(job_id) or not swam.KEY_RE.fullmatch(key):
        raise HTTPException(status_code=404, detail="not found")
    return JSONResponse(
        {"key": key, **swam.status(key, _swam_folder(job_id)), "url": _swam_url(job_id, key)}
    )


@router.get("/jobs/{job_id}/sax/swam/{key}/audio.flac")
async def swam_audio(job_id: str, key: str) -> FileResponse:
    from app.score import swam

    if not JOB_ID_RE.match(job_id) or not swam.KEY_RE.fullmatch(key):
        raise HTTPException(status_code=404, detail="not found")
    path = swam.audio_path(_swam_folder(job_id), key)
    if not path.is_file():
        raise HTTPException(status_code=404, detail="not rendered")
    return FileResponse(
        path, media_type="audio/flac", headers={"Cache-Control": "max-age=31536000, immutable"}
    )
