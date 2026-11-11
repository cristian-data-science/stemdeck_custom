"""Experimental endpoints (app/experimental). Kept in their own router so the
stable API does not change when an experiment does.

GET  /experimental/sheet                         can this machine import scores (Audiveris)?
POST /experimental/sheet                         import a PDF/image score -> a library track
GET  /experimental/sheet/{import_id}             progress of an import
GET  /jobs/{id}/score/{stem}/fingering           a finger for every note ({"available": false}: none)
PUT  /jobs/{id}/score/{stem}/fingering           set or clear fingers by hand
POST /jobs/{id}/score/{stem}/fingering/enable    fingers for any song, on request
DELETE /jobs/{id}/score/{stem}/fingering         take them away again (only those)
POST /experimental/jobs/{id}/separation[?model=]  a copy separated by the other model
GET  /experimental/separation[/{run_id}]         installed? / progress of a copy
"""

from __future__ import annotations

import logging
import secrets
import tempfile
import threading
from pathlib import Path

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from app.api.score import _job_or_404, _require_done
from app.experimental.sheet import fingering, omr
from app.score import store

logger = logging.getLogger(__name__)
router = APIRouter()

SUFFIXES = {".pdf", ".png", ".jpg", ".jpeg", ".tif", ".tiff"}
MAX_BYTES = 60 * 1024 * 1024
_IMPORTS: dict[str, dict] = {}
_LOCK = threading.Lock()


@router.get("/experimental/sheet")
async def sheet_info() -> JSONResponse:
    exe = omr.executable()
    return JSONResponse({"available": exe is not None, "audiveris": str(exe) if exe else None})


def _run_import(import_id: str, path: Path, title: str, bpm: float | None) -> None:
    from app.experimental.sheet import song

    def report(phase: str) -> None:
        with _LOCK:
            _IMPORTS[import_id].update(state="running", phase=phase)

    try:
        result = song.create(path, title, bpm=bpm, report=report)
        with _LOCK:
            _IMPORTS[import_id] = {"state": "done", "result": result}
    except Exception as e:  # noqa: BLE001 -- reported to the page
        logger.warning("sheet import failed: %s", e, exc_info=True)
        with _LOCK:
            _IMPORTS[import_id] = {"state": "error", "error": str(e)[:400]}
    finally:
        path.unlink(missing_ok=True)


@router.post("/experimental/sheet")
async def sheet_import(
    file: UploadFile = File(...),
    title: str | None = Form(default=None),
    bpm: float | None = Form(default=None, ge=20, le=300),
) -> JSONResponse:
    suffix = Path(file.filename or "").suffix.lower()
    if suffix not in SUFFIXES:
        raise HTTPException(status_code=415, detail="sube un PDF o una imagen (PNG, JPG, TIFF)")
    if omr.executable() is None:
        raise HTTPException(status_code=503, detail="Audiveris no está instalado")
    data = await file.read(MAX_BYTES + 1)
    if len(data) > MAX_BYTES:
        raise HTTPException(status_code=413, detail="archivo demasiado grande")
    tmp = Path(tempfile.mkdtemp(prefix="stemdeck-sheet-")) / f"score{suffix}"
    tmp.write_bytes(data)
    import_id = secrets.token_hex(4)
    name = (title or Path(file.filename or "partitura").stem).strip()[:120] or "Partitura"
    with _LOCK:
        _IMPORTS[import_id] = {"state": "queued", "phase": "queued"}
    threading.Thread(target=_run_import, args=(import_id, tmp, name, bpm), daemon=True).start()
    return JSONResponse({"import_id": import_id, "state": "queued"}, status_code=202)


@router.get("/experimental/sheet/{import_id}")
async def sheet_status(import_id: str) -> JSONResponse:
    with _LOCK:
        st = _IMPORTS.get(import_id)
    if st is None:
        raise HTTPException(status_code=404, detail="unknown import")
    return JSONResponse(st)


# -- fingering ----------------------------------------------------------------


def _as_drawn(job_id: str, stem: str, doc: dict) -> list[dict]:
    """The notes as the falling-notes view shows them: each in the hand of the
    staff it is drawn on (a hand set by the user wins there too), ending where
    its bar ends. The fingers must fit what is on screen: two bars that overlap
    are two keys down at once."""
    from app.core.registry import get as registry_get
    from app.score import service
    from app.score.engrave import STAFF_TREBLE
    from app.score.hands import assign_hands

    notes = doc["notes"]
    job = registry_get(job_id)
    try:
        eng = service.engrave_stem(job, stem, doc, store.read_meta(job_id, stem))[0]
    except Exception:  # noqa: BLE001 -- no engraving (a test, an odd score): the hands alone
        logger.warning("fingering: no engraving for %s/%s", job_id, stem, exc_info=True)
        guess = assign_hands([n for n in notes if n.get("hand") not in ("L", "R")])
        return [
            {**n, "hand": n.get("hand") if n.get("hand") in ("L", "R") else guess.get(n["id"], "R")}
            for n in notes
        ]
    out = []
    for n in notes:
        placed = eng.notes.get(n["id"])
        if placed is None:
            out.append({**n, "hand": n.get("hand") if n.get("hand") in ("L", "R") else "R"})
            continue
        out.append(
            {
                **n,
                "hand": "R" if placed["staff"] == STAFF_TREBLE else "L",
                # The bar's end, unless the key came up earlier (a quantized bar
                # may reach a little past the next note of a run).
                "end": max(min(placed["draw_end"], n["end"]), n["start"] + 0.01),
            }
        )
    return out


def _fingering(job_id: str, stem: str) -> dict:
    meta = store.read_meta(job_id, stem)
    fg = meta.get("fingering")
    if not isinstance(fg, dict):
        raise HTTPException(status_code=404, detail="this score has no fingering")
    doc = store.read_notes(job_id, stem) or {"notes": []}
    notes = _as_drawn(job_id, stem, doc)
    ids = {n["id"] for n in notes}
    fixed = {k: v for k, v in (fg.get("fixed") or {}).items() if k in ids}
    auto = fingering.suggest(notes, {k: v["f"] for k, v in fixed.items()})
    out = {}
    for n in notes:
        if n["id"] in fixed:
            out[n["id"]] = {"f": fixed[n["id"]]["f"], "src": fixed[n["id"]].get("src", "user")}
        elif n["id"] in auto:
            out[n["id"]] = {"f": auto[n["id"]], "src": "auto"}
    return {
        "source": fg.get("source"),
        "fingers": out,
        "counts": {
            s: sum(1 for v in out.values() if v["src"] == s) for s in ("score", "user", "auto")
        },
    }


@router.get("/jobs/{job_id}/score/{stem}/fingering")
async def get_fingering(job_id: str, stem: str) -> JSONResponse:
    """Every song page asks; most songs have no fingering, which is an answer,
    not an error (a 404 showed up as a console error on every score page)."""
    _job_or_404(job_id, stem)
    _require_done(job_id, stem)
    if not isinstance(store.read_meta(job_id, stem).get("fingering"), dict):
        return JSONResponse({"available": False})
    return JSONResponse({"available": True, **_fingering(job_id, stem)})


class FingeringBody(BaseModel):
    # note id -> finger 1-5, or null to go back to the suggestion
    set: dict[str, int | None] = Field(max_length=5000)


@router.put("/jobs/{job_id}/score/{stem}/fingering")
async def put_fingering(job_id: str, stem: str, body: FingeringBody) -> JSONResponse:
    _job_or_404(job_id, stem)
    _require_done(job_id, stem)

    # One read-change-write (store.update_meta): fingers pressed quickly, or
    # beside a setting or the piano, no longer write over each other.
    def change(meta: dict) -> None:
        fg = meta.get("fingering")
        if not isinstance(fg, dict):
            raise HTTPException(status_code=404, detail="this score has no fingering")
        fixed = dict(fg.get("fixed") or {})
        for nid, f in body.set.items():
            if f is None:
                fixed.pop(nid, None)
            elif f in (1, 2, 3, 4, 5):
                fixed[nid] = {"f": f, "src": "user"}
            else:
                raise HTTPException(status_code=422, detail="finger must be 1-5")
        fg["fixed"] = fixed
        meta["fingering"] = fg

    store.update_meta(job_id, stem, change)
    return JSONResponse({"available": True, **_fingering(job_id, stem)})


@router.post("/jobs/{job_id}/score/{stem}/fingering/enable")
async def enable_fingering(job_id: str, stem: str) -> JSONResponse:
    """Fingers for a song that did not come from a score: all suggested at
    first, then corrected by hand (1-5). Only for the songs where the user
    asks («Activar dedos»): every other song stays as it was."""
    _job_or_404(job_id, stem)
    _require_done(job_id, stem)

    def change(meta: dict) -> None:
        if not isinstance(meta.get("fingering"), dict):
            meta["fingering"] = {"source": "manual", "fixed": {}}

    store.update_meta(job_id, stem, change)
    return JSONResponse({"available": True, **_fingering(job_id, stem)})


@router.delete("/jobs/{job_id}/score/{stem}/fingering")
async def disable_fingering(job_id: str, stem: str) -> JSONResponse:
    """Undo «Activar dedos» (the fingers set by hand go too). A song made from
    a score keeps its printed fingers: 409."""
    _job_or_404(job_id, stem)
    _require_done(job_id, stem)

    def change(meta: dict) -> None:
        fg = meta.get("fingering")
        if isinstance(fg, dict) and fg.get("source") != "manual":
            raise HTTPException(status_code=409, detail="los dedos vienen de la partitura")
        meta.pop("fingering", None)

    store.update_meta(job_id, stem, change)
    return JSONResponse({"available": False})


# -- a song separated again by BS-RoFormer SW (app/experimental/separation.py) --

_SPLITS: dict[str, dict] = {}


@router.get("/experimental/separation")
async def separation_info() -> JSONResponse:
    from app.experimental import separation

    return JSONResponse({"available": separation.available()})


def _run_split(run_id: str, job_id: str, model: str) -> None:
    from app.experimental import separation

    def report(phase: str) -> None:
        with _LOCK:
            _SPLITS[run_id].update(state="running", phase=phase)

    try:
        result = separation.copy_job(job_id, report=report, model=model)
        with _LOCK:
            _SPLITS[run_id] = {"state": "done", "result": result}
    except Exception as e:  # noqa: BLE001 -- reported to the page
        logger.warning("roformer separation of %s failed: %s", job_id, e, exc_info=True)
        with _LOCK:
            _SPLITS[run_id] = {"state": "error", "error": str(e)[:400]}


async def _split_async(run_id: str, job_id: str, model: str) -> None:
    import asyncio

    from app.pipeline.runner import _pipeline_lock

    # Never two models on the GPU at once: behind the separation queue.
    async with _pipeline_lock:
        await asyncio.to_thread(_run_split, run_id, job_id, model)


@router.post("/experimental/jobs/{job_id}/separation")
async def start_separation(job_id: str, model: str | None = None) -> JSONResponse:
    """A copy of the song separated by `model` ("demucs" or "roformer"; by
    default the one that did not separate it). The song itself is kept."""
    import asyncio

    from app.core.registry import get as registry_get
    from app.experimental import separation

    job = registry_get(job_id)
    if job is None or job.status != "done":
        raise HTTPException(status_code=404, detail="job not found")
    model = model or separation.other_model(job)
    if model not in separation.MODELS:
        raise HTTPException(status_code=422, detail="modelo desconocido")
    if model == "roformer" and not separation.available():
        raise HTTPException(status_code=503, detail="el separador RoFormer no está instalado")
    run_id = secrets.token_hex(4)
    with _LOCK:
        _SPLITS[run_id] = {"state": "queued", "phase": "queued"}
    asyncio.get_running_loop().create_task(_split_async(run_id, job_id, model))
    return JSONResponse({"run_id": run_id, "state": "queued", "model": model}, status_code=202)


@router.get("/experimental/separation/{run_id}")
async def separation_status(run_id: str) -> JSONResponse:
    with _LOCK:
        st = _SPLITS.get(run_id)
    if st is None:
        raise HTTPException(status_code=404, detail="unknown run")
    return JSONResponse(st)
