"""Score endpoints: transcribe a stem to MIDI, read/edit the notes, export.

POST   /jobs/{id}/score/{stem}              start the transcription (202)
GET    /jobs/{id}/score/{stem}              status, or the full score payload
PUT    /jobs/{id}/score/{stem}/notes        save edited notes (persisted)
DELETE /jobs/{id}/score/{stem}/notes        back to the transcription
PUT    /jobs/{id}/score/{stem}/settings     grid, hand split, tempo, names...
PUT    /jobs/{id}/score/{stem}/chords       rename / remove / add a chord
GET    /jobs/{id}/score/{stem}/export.{mid|musicxml|mei}
GET    /jobs/{id}/score/{stem}/history      the edit history (newest first)
POST   /jobs/{id}/score/{stem}/history/{v}/undo   back to before edit v (one more edit)
GET    /score/pianoteq                      is Pianoteq installed, its presets
GET    /score/pianoteq/queue                the background renders: running, waiting
POST   /jobs/{id}/score/{stem}/pianoteq     render the score with a preset
GET    /jobs/{id}/score/{stem}/pianoteq/status/{key}
GET    /jobs/{id}/score/{stem}/pianoteq/audio/{key}.flac
GET    /jobs/{id}/score/{stem}/pianoteq/ready   this score's piano, and the pianos already rendered
PUT    /jobs/{id}/score/{stem}/practice     add practice time / best speed (the library shows it)
GET    /score/library                       every song's score state, for the library
"""

from __future__ import annotations

import asyncio
import logging
import os
import re
import threading
import time
from collections import deque
from typing import Literal

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import FileResponse, JSONResponse, Response
from pydantic import BaseModel, Field, field_validator, model_validator

from app.core.config import JOB_ID_RE, JOBS_DIR
from app.core.registry import get as registry_get
from app.score import engines, ghosts, hand_labels, pianoteq, pulse, service, storage, store, tuning

logger = logging.getLogger(__name__)
router = APIRouter()

_NOTE_ID_RE = re.compile(r"^n[A-Za-z0-9_]{1,24}$")
MAX_NOTES = 20000

# (job_id, stem) -> {"state": queued|running|error, "phase", "progress", "error"}
_RUNS: dict[tuple[str, str], dict] = {}
_RUNS_LOCK = threading.Lock()


def _job_or_404(job_id: str, stem: str):
    if not JOB_ID_RE.match(job_id):
        raise HTTPException(status_code=404, detail="job not found")
    job = registry_get(job_id)
    if job is None or job.status != "done":
        raise HTTPException(status_code=404, detail="job not found")
    if not engines.supports(stem):
        raise HTTPException(status_code=404, detail="no transcription for this stem")
    if not store.stem_wav(job_id, stem).is_file() or not store.stem_wav(
        job_id, stem
    ).is_relative_to(JOBS_DIR.resolve()):
        raise HTTPException(status_code=404, detail="stem not found")
    return job


def _status(job_id: str, stem: str) -> dict:
    with _RUNS_LOCK:
        run = _RUNS.get((job_id, stem))
        if run is not None and run["state"] in ("queued", "running"):
            return dict(run)
    if store.read_raw(job_id, stem) is not None:
        return {"state": "done"}
    err = store.read_json(store.score_dir(job_id, stem) / "error.json")
    if err:
        return {"state": "error", "error": err.get("error", "failed")}
    return {"state": "none"}


async def _full(job, stem: str) -> dict:
    notes_doc = await asyncio.to_thread(store.read_notes, job.id, stem)
    if notes_doc is None:
        return {"status": _status(job.id, stem)}
    meta = store.read_meta(job.id, stem)
    data = await asyncio.to_thread(service.payload, job, stem, notes_doc, meta)
    data["status"] = {"state": "done"}
    # This score's own piano (the page used to pick the one last chosen on any
    # song, and re-rendered every song it opened with it), and its practice.
    data["pianoteq"] = {"preset": (meta.get("pianoteq") or {}).get("preset")}
    data["practice"] = meta.get("practice") or {}
    data["hand_labels"] = hand_labels.summary(job.id, stem)
    return data


@router.get("/jobs/{job_id}/score/{stem}")
async def get_score(job_id: str, stem: str) -> JSONResponse:
    job = _job_or_404(job_id, stem)
    status = _status(job_id, stem)
    if status["state"] != "done":
        return JSONResponse({"status": status, "stem": stem, "engine": engines.name(stem)})
    # A score transcribed before this rendered nothing yet: start it now too.
    pianoteq_soon(job, stem)
    return JSONResponse(await _full(job, stem))


def _video_notes(job, stem: str, source: str, raw: dict, used: str, why: str) -> tuple[str, str]:
    """Replace raw's notes by the ones a falling-notes video shows, when the
    job has such a video (asked for, or "auto"). Returns (source, reason)."""
    from app.score import video_notes

    video = store.JOBS_DIR / job.id / "video.mp4"
    if stem != "piano" or source not in ("auto", "video") or not video.is_file():
        return used, why
    heard = [n for n in raw.get("notes") or [] if not n.get("ghost")]
    got = video_notes.notes_from_video(video, heard)
    if got is None:
        if source == "video":
            return used, f"{why}; el video no muestra un teclado legible (se usó el audio)"
        return used, why
    notes, info = got
    raw["notes"] = notes
    raw["video"] = {**info, "audio_notes": len(heard)}
    raw.pop("ghosts", None)  # the audio's ghost marks are about notes no longer here
    pct = round(100 * info["agreement"])
    return "video", f"notas leídas del video de notas cayendo ({pct} % confirmadas por el audio)"


def _run(job, stem: str, source: str = "auto") -> None:
    key = (job.id, stem)
    d = store.score_dir(job.id, stem)
    d.mkdir(parents=True, exist_ok=True)

    def report(phase: str, frac: float) -> None:
        with _RUNS_LOCK:
            _RUNS[key].update(state="running", phase=phase, progress=round(frac, 3))

    try:
        out = d / "raw.next.json"
        original = store.source_audio(job.id)
        audio_pick = "auto" if source == "video" else source
        used, why = engines.choose_audio(stem, job.stem_presence, audio_pick, original is not None)
        audio = original if used == "original" else store.stem_wav(job.id, stem)
        # A song off A440 (a "slowed" upload) is transcribed brought to it.
        retune = tuning.prepare(audio, d)
        try:
            engines.transcribe(stem, retune.path, out, report)
        finally:
            if retune.path != audio:
                retune.path.unlink(missing_ok=True)
        raw = tuning.restore(store.read_json(out) or {}, retune)
        # Notes with no attack in the audio they came from (re-strikes of a
        # held key, stem bleed) are marked, and start out deleted (ghosts.py).
        ghosts.annotate(
            raw, audio, ghosts.bleed_sources(store.stem_wav(job.id, stem).parent, audio)
        )
        # A falling-notes video: its lit keys are the notes (video_notes.py),
        # checked against what the audio says; the audio's stay otherwise.
        used, why = _video_notes(job, stem, source, raw, used, why)
        raw.update(audio_source=used, audio_source_reason=why, audio_source_requested=source)
        store.write_json(out, raw)
        if report:
            report("pulse", 1.0)
        # The pulse is the song's, not the stem's: a sparse stem (a piano
        # that plays in a few passages) gave 64 beats at 103 BPM, CV 0.15, and
        # its notes a wrong 71 BPM; the whole mix 195 steady beats (CV 0.07).
        own = pulse.track(original if original is not None else audio)
        if own:
            store.write_json(d / "beats.json", own)
        else:
            (d / "beats.json").unlink(missing_ok=True)
        from_notes = pulse.track_notes((store.read_json(out) or {}).get("notes", []))
        if from_notes:
            store.write_json(d / "beats_notes.json", from_notes)
        else:
            (d / "beats_notes.json").unlink(missing_ok=True)
        out.replace(d / "raw.json")
        (d / "notes.json").unlink(missing_ok=True)
        store.clear_history(job.id, stem)  # about notes that are gone
        (d / "error.json").unlink(missing_ok=True)
        store.read_notes(job.id, stem)
        with _RUNS_LOCK:
            _RUNS.pop(key, None)
        # The Pianoteq audio starts at once, beside whatever the page does
        # next: by the time the score is read, it is (nearly) ready.
        pianoteq_soon(job, stem)
    except Exception as e:  # noqa: BLE001 -- any failure is reported to the page
        logger.warning("[%s] score transcription of %s failed: %s", job.id, stem, e, exc_info=True)
        tail = getattr(e, "tail", None) or []
        store.write_json(d / "error.json", {"error": str(e), "tail": tail[-10:], "at": time.time()})
        with _RUNS_LOCK:
            _RUNS[key] = {"state": "error", "error": str(e)}


async def _run_async(job, stem: str, source: str = "auto") -> None:
    from app.pipeline.runner import _pipeline_lock

    # Behind the pipeline lock like the vocal split: never two models on the
    # GPU at once. Waiting shows as "queued".
    async with _pipeline_lock:
        with _RUNS_LOCK:
            _RUNS[(job.id, stem)].update(state="running", phase="load")
        await asyncio.to_thread(_run, job, stem, source)


@router.post("/jobs/{job_id}/score/{stem}")
async def start_score(
    job_id: str,
    stem: str,
    force: bool = Query(default=False),
    source: Literal["auto", "stem", "original", "video"] = Query(default="auto"),
) -> JSONResponse:
    job = _job_or_404(job_id, stem)
    status = _status(job_id, stem)
    if status["state"] in ("queued", "running"):
        return JSONResponse({"status": status}, status_code=202)
    if status["state"] == "done" and not force:
        return JSONResponse(await _full(job, stem))
    with _RUNS_LOCK:
        _RUNS[(job_id, stem)] = {"state": "queued", "phase": "queued", "progress": 0.0}
    asyncio.get_running_loop().create_task(_run_async(job, stem, source))
    return JSONResponse({"status": _status(job_id, stem)}, status_code=202)


class NoteIn(BaseModel):
    id: str
    midi: int = Field(ge=21, le=108)
    start: float = Field(ge=0, lt=86400)
    end: float = Field(gt=0, le=86400)
    velocity: int = Field(default=80, ge=1, le=127)
    hand: Literal["R", "L"] | None = None
    # A length the user set (joined notes, lengthened, added): kept whole even
    # where the score, one voice per staff, cuts it (pedal.sound_ends).
    held: bool | None = None

    @field_validator("id")
    @classmethod
    def _check_id(cls, v: str) -> str:
        if not _NOTE_ID_RE.match(v):
            raise ValueError("invalid note id")
        return v

    @model_validator(mode="after")
    def _check_span(self):
        if not (self.start < self.end <= self.start + 60):
            raise ValueError("a note must end after it starts, within 60 s")
        return self


class NotesBody(BaseModel):
    notes: list[NoteIn] = Field(max_length=MAX_NOTES)
    # What the edit was («Movida», «1 nota(s) borrada(s)»...), for the history.
    what: str | None = Field(default=None, max_length=160)

    @model_validator(mode="after")
    def _unique(self):
        ids = [n.id for n in self.notes]
        if len(ids) != len(set(ids)):
            raise ValueError("duplicate note id")
        return self


def _require_done(job_id: str, stem: str) -> None:
    if _status(job_id, stem)["state"] != "done":
        raise HTTPException(status_code=409, detail="no transcription yet")


@router.put("/jobs/{job_id}/score/{stem}/notes")
async def put_notes(job_id: str, stem: str, body: NotesBody) -> JSONResponse:
    job = _job_or_404(job_id, stem)
    _require_done(job_id, stem)
    notes = [
        {
            "id": n.id,
            "midi": n.midi,
            "start": round(n.start, 4),
            "end": round(n.end, 4),
            "velocity": n.velocity,
            "hand": n.hand,
            **({"held": True} if n.held else {}),
        }
        for n in sorted(body.notes, key=lambda n: (n.start, n.midi))
    ]
    await asyncio.to_thread(_save_and_label, job_id, stem, notes, body.what)
    return JSONResponse(await _full(job, stem))


@router.get("/jobs/{job_id}/score/{stem}/history")
async def get_history(job_id: str, stem: str) -> JSONResponse:
    """The edit history, newest first: each save, what it was, when, and how
    many notes it changed (the notes themselves stay on the server)."""
    _job_or_404(job_id, stem)
    _require_done(job_id, stem)
    history = await asyncio.to_thread(store.read_history, job_id, stem)
    current = (store.read_notes(job_id, stem) or {}).get("version")
    return JSONResponse(
        {
            "version": current,
            "entries": [
                {
                    "v": e["v"],
                    "at": e.get("at"),
                    "what": e.get("what"),
                    "before": len(e.get("before") or []),
                    "after": len(e.get("after") or []),
                    "notes": _history_notes(e),
                }
                for e in reversed(history)
            ],
        }
    )


def _history_notes(entry: dict) -> list[dict]:
    """A few of the notes an entry changed, to name them (pitch, time; before
    -> after when the same note): enough for "Do4 -> Re4 en 0:12"."""
    before = {n["id"]: n for n in entry.get("before") or []}
    after = {n["id"]: n for n in entry.get("after") or []}
    out = []
    for i in list(dict.fromkeys([*before, *after]))[:3]:
        b, a = before.get(i), after.get(i)
        out.append(
            {
                "from": {"midi": b["midi"], "start": b["start"]} if b else None,
                "to": {"midi": a["midi"], "start": a["start"]} if a else None,
            }
        )
    return out


@router.post("/jobs/{job_id}/score/{stem}/history/{version}/undo")
async def undo_to(job_id: str, stem: str, version: int) -> JSONResponse:
    """The notes as they were before the edit that made `version` (that edit
    and every later one undone), saved as one more edit: itself undoable."""
    job = _job_or_404(job_id, stem)
    _require_done(job_id, stem)
    got = await asyncio.to_thread(store.notes_before, job_id, stem, version)
    if got is None:
        raise HTTPException(status_code=404, detail="esa edición ya no está en el historial")
    notes, entry = got
    what = f"Volver a antes de «{entry.get('what') or 'Edición'}»"
    await asyncio.to_thread(_save_and_label, job_id, stem, notes, what)
    return JSONResponse(await _full(job, stem))


def _save_and_label(job_id: str, stem: str, notes: list[dict], what: str | None = None) -> None:
    """Save, and keep the hands the user changed for retraining
    (hand_labels.py); a reviewed song's snapshot follows them."""
    before = (store.read_notes(job_id, stem) or {}).get("notes") or []
    store.save_notes(job_id, stem, notes, what)
    if not hand_labels.changed_hands(before, notes):
        return
    try:
        meta = store.read_meta(job_id, stem)
        hand_labels.record(job_id, stem, before, notes, service.shown_hands(before, meta, stem))
        if hand_labels.reviewed(job_id, stem):
            hand_labels.mark_reviewed(job_id, stem, notes, service.shown_hands(notes, meta, stem))
    except Exception:  # never lose the edit for the training log
        logger.exception("hand labels for %s/%s", job_id, stem)


@router.post("/jobs/{job_id}/score/{stem}/hands/reviewed")
async def mark_hands_reviewed(job_id: str, stem: str) -> JSONResponse:
    """«✓ Canción revisada»: every note's hand, as the score shows it, kept as
    confirmed by the user (training data for the hand model)."""
    job = _job_or_404(job_id, stem)
    _require_done(job_id, stem)

    def mark():
        notes = (store.read_notes(job_id, stem) or {}).get("notes") or []
        meta = store.read_meta(job_id, stem)
        hand_labels.mark_reviewed(job_id, stem, notes, service.shown_hands(notes, meta, stem))

    await asyncio.to_thread(mark)
    return JSONResponse(await _full(job, stem))


@router.delete("/jobs/{job_id}/score/{stem}/hands/reviewed")
async def unmark_hands_reviewed(job_id: str, stem: str) -> JSONResponse:
    job = _job_or_404(job_id, stem)
    _require_done(job_id, stem)
    await asyncio.to_thread(hand_labels.unmark_reviewed, job_id, stem)
    return JSONResponse(await _full(job, stem))


@router.delete("/jobs/{job_id}/score/{stem}/notes")
async def reset_notes(job_id: str, stem: str) -> JSONResponse:
    job = _job_or_404(job_id, stem)
    _require_done(job_id, stem)
    await asyncio.to_thread(store.reset_notes, job_id, stem)
    store.update_meta(job_id, stem, lambda meta: meta.pop("chord_overrides", None))
    return JSONResponse(await _full(job, stem))


class SettingsBody(BaseModel):
    grid: Literal["8", "16", "16t"] | None = None
    split: int | None = Field(default=None, ge=36, le=84)
    tempo: Literal["normal", "half", "double"] | None = None
    chord_rate: Literal["beat", "half", "bar"] | None = None
    chords: bool | None = None
    meter: Literal["auto", "detected", "2", "3", "4", "6"] | None = None
    pulse: Literal["auto", "song", "audio", "notes"] | None = None
    hands: Literal["auto", "split"] | None = None
    bar_shift: int | None = Field(default=None, ge=0, le=15)
    key: str | None = Field(default=None, pattern=r"^(auto|song|([0-9]|1[01]):(major|minor))$")
    names: Literal["solfege", "letters"] | None = None
    pedal: int | None = Field(default=None, ge=0, le=100)


@router.put("/jobs/{job_id}/score/{stem}/settings")
async def put_settings(job_id: str, stem: str, body: SettingsBody) -> JSONResponse:
    job = _job_or_404(job_id, stem)
    _require_done(job_id, stem)

    def change(meta: dict) -> None:
        settings = dict(meta.get("settings") or {})
        for field in _SETTING_FIELDS:
            value = getattr(body, field)
            if value is not None:
                settings[field] = value
        meta["settings"] = settings
        if body.names is not None:
            meta["names"] = body.names

    store.update_meta(job_id, stem, change)
    return JSONResponse(await _full(job, stem))


_SETTING_FIELDS = (
    "grid",
    "split",
    "tempo",
    "chord_rate",
    "chords",
    "meter",
    "bar_shift",
    "key",
    "pulse",
    "hands",
    "pedal",
)


class ChordBody(BaseModel):
    time_ms: int = Field(ge=0, lt=86_400_000)
    # "" removes the chord shown there; null drops the override (detected again).
    text: str | None = Field(default=None, max_length=24)


@router.put("/jobs/{job_id}/score/{stem}/chords")
async def put_chord(job_id: str, stem: str, body: ChordBody) -> JSONResponse:
    job = _job_or_404(job_id, stem)
    _require_done(job_id, stem)

    def change(meta: dict) -> None:
        overrides = dict(meta.get("chord_overrides") or {})
        key = str(body.time_ms)
        if body.text is None:
            overrides.pop(key, None)
        else:
            overrides[key] = body.text.strip()
        if len(overrides) > 5000:
            raise HTTPException(status_code=413, detail="too many chord edits")
        meta["chord_overrides"] = overrides

    store.update_meta(job_id, stem, change)
    return JSONResponse(await _full(job, stem))


_EXPORT_TYPES = {
    "mid": "audio/midi",
    "musicxml": "application/vnd.recordare.musicxml+xml",
    "mei": "application/mei+xml",
}


@router.get("/jobs/{job_id}/score/{stem}/export.{fmt}")
async def export_score(
    job_id: str, stem: str, fmt: str, quantized: bool = Query(default=True)
) -> Response:
    job = _job_or_404(job_id, stem)
    if fmt not in _EXPORT_TYPES:
        raise HTTPException(status_code=404, detail="unknown format")
    _require_done(job_id, stem)
    notes_doc = await asyncio.to_thread(store.read_notes, job_id, stem)
    meta = store.read_meta(job_id, stem)
    if fmt == "mid":
        body: bytes | str = await asyncio.to_thread(
            service.midi, job, stem, notes_doc, meta, quantized
        )
    elif fmt == "musicxml":
        body = await asyncio.to_thread(service.musicxml, job, stem, notes_doc, meta)
    else:
        body = (await asyncio.to_thread(service.payload, job, stem, notes_doc, meta))["mei"]
    slug = re.sub(r"[^A-Za-z0-9]+", "_", job.title or "score").strip("_")[:60] or "score"
    return Response(
        body,
        media_type=_EXPORT_TYPES[fmt],
        headers={"Content-Disposition": f'attachment; filename="{slug}_{stem}.{fmt}"'},
    )


# -- Pianoteq ----------------------------------------------------------------

# render key -> {"state": "rendering" | "error", "error"}
_PT_RUNS: dict[tuple[str, str, str], dict] = {}  # (job, stem, key): one score's renders
_PT_LOCK = threading.RLock()  # _pt_start holds it around _pt_status
# What each score wants rendered now. Renders run one at a time (~30 s a
# song), and every edit, hand pre-render and automatic render used to queue
# one more: after a few edits the render the page waited for came minutes
# later, behind renders of notes already edited again. A render is wanted
# while its notes are the score's latest (notes.json "version") and it is the
# latest asked for its kind (hand, speed); otherwise skipped, or stopped.
_PT_NOTES: dict[tuple[str, str], int] = {}  # (job, stem) -> latest notes version
_PT_WANT: dict[tuple[str, str, str | None, float], str] = {}  # (job, stem, hand, speed) -> key
# Renders the page asked for, waiting or running: the background ones
# (_pt_background) give way to them, stopping mid-render if need be.
_PT_HIGH = 0
# Background renders, nobody waiting for them: every score's Pianoteq audio
# at every practice speed (PT_SPEEDS, the page's «Velocidad» buttons) and for
# both hands, the right hand alone and the left hand alone -- so choosing a
# speed or muting a hand («Silenciar») plays Pianoteq at once instead of the
# MIDI synth while a render runs. (job, stem, hand, speed); the piano and the
# notes are read when the render's turn comes, so it is always of the score
# as it stands then.
_PT_BG: deque[tuple[str, str, str | None, float]] = deque()
_PT_BG_RUNNING = False
_PT_BG_NOW: dict = {}  # the background render running: {job, stem, hand, speed, since}
PT_HANDS: tuple[str | None, ...] = (None, "R", "L")
PT_SPEEDS: tuple[float, ...] = (1.0, 0.7, 0.5, 0.25)


@router.get("/score/pianoteq")
async def pianoteq_info() -> JSONResponse:
    return JSONResponse(await asyncio.to_thread(pianoteq.info))


class PianoteqBody(BaseModel):
    preset: str = Field(min_length=1, max_length=200)
    # Practice renders: one hand only (to play the other one yourself), and a
    # slower tempo rendered by Pianoteq instead of stretched by the browser.
    hand: Literal["R", "L"] | None = None
    speed: float = Field(default=1.0, ge=0.25, le=1.25)

    @field_validator("speed")
    @classmethod
    def _snap_speed(cls, v: float) -> float:
        return round(round(v * 20) / 20, 2)  # 5 % steps: a few renders, not one per pixel


def _pt_folder(job_id: str, stem: str):
    return store.score_dir(job_id, stem) / "pianoteq"


def _pt_status(job_id: str, stem: str, key: str) -> dict:
    if pianoteq.audio_path(_pt_folder(job_id, stem), key).is_file():
        return {
            "state": "ready",
            "key": key,
            "url": f"/api/jobs/{job_id}/score/{stem}/pianoteq/audio/{key}.flac",
        }
    with _PT_LOCK:
        run = _PT_RUNS.get((job_id, stem, key))
    if run is None:
        return {"state": "none", "key": key}
    return {**run, "key": key}


def _pt_wanted(job_id: str, stem: str, key: str, version: int, hand, speed) -> bool:
    with _PT_LOCK:
        return (
            _PT_NOTES.get((job_id, stem), version) == version
            and _PT_WANT.get((job_id, stem, hand, speed), key) == key
        )


def _pt_render(
    job_id: str,
    stem: str,
    key: str,
    midi: bytes,
    preset: str,
    version: int = 0,
    hand: str | None = None,
    speed: float = 1.0,
) -> None:
    """A render the page asked for (counted in _PT_HIGH while it waits)."""
    global _PT_HIGH
    try:
        _pt_render_now(job_id, stem, key, midi, preset, version, hand, speed)
    finally:
        with _PT_LOCK:
            _PT_HIGH -= 1
    # Rendered with this piano (the notes as they stand): every other speed
    # and hand follows, behind (the ones already made are skipped at once).
    if pianoteq.audio_path(_pt_folder(job_id, stem), key).is_file():
        _pt_background(job_id, stem, front=True)


def _pt_render_now(
    job_id: str,
    stem: str,
    key: str,
    midi: bytes,
    preset: str,
    version: int,
    hand: str | None,
    speed: float,
) -> None:
    try:
        pianoteq.render_as(
            midi,
            preset,
            _pt_folder(job_id, stem),
            key,
            wanted=lambda: _pt_wanted(job_id, stem, key, version, hand, speed),
        )
        storage.note_render(
            _pt_folder(job_id, stem), key, preset=preset, hand=hand, speed=speed, version=version
        )
        with _PT_LOCK:
            _PT_RUNS.pop((job_id, stem, key), None)
    except pianoteq.Superseded:
        # Asked again (POST) if the page still wants it: "none" from now on.
        logger.info("pianoteq render %s of %s/%s skipped: superseded", key, job_id, stem)
        with _PT_LOCK:
            _PT_RUNS.pop((job_id, stem, key), None)
    except Exception as exc:  # noqa: BLE001 - reported to the page
        logger.warning("pianoteq render failed for %s/%s: %s", job_id, stem, exc)
        with _PT_LOCK:
            _PT_RUNS[(job_id, stem, key)] = {"state": "error", "error": str(exc)[:300]}


def _adopt_legacy(
    job, stem: str, notes_doc: dict, meta: dict, presets: list[str], keys: dict, midi: bytes
) -> None:
    """Renders saved under an older naming renamed to the current one: the
    same sound, so not rendered again. Named after the two-track MIDI itself
    (the hands in the name, until 2026-11-12), or before that after the MIDI
    with the song's tempo map."""
    folder = _pt_folder(job.id, stem)
    if not folder.is_dir():
        return
    pianoteq.drop_legacy(folder)
    missing = [p for p in presets if not pianoteq.audio_path(folder, keys[p]).is_file()]
    for p in missing:
        pianoteq.adopt(folder, pianoteq.render_key(midi, p), keys[p])
    missing = [p for p in missing if not pianoteq.audio_path(folder, keys[p]).is_file()]
    if not missing:
        return
    try:
        old = service.legacy_performance_midi(job, stem, notes_doc, meta)
    except Exception:  # noqa: BLE001 -- nothing to adopt then
        return
    for p in missing:
        pianoteq.adopt(folder, pianoteq.legacy_key(old, p), keys[p])


def _pt_start(job, stem: str, preset: str, hand: str | None = None, speed: float = 1.0) -> dict:
    """The render of the score as it stands now with `preset`: its status,
    starting it (in a thread) unless it is ready or already running."""
    global _PT_HIGH
    notes_doc = store.read_notes(job.id, stem)
    meta = store.read_meta(job.id, stem)
    midi, sig = service.performance_signature(job, stem, notes_doc, meta, hand=hand, speed=speed)
    key = pianoteq.render_key(sig, preset)
    if hand is None and speed == 1.0:
        _adopt_legacy(job, stem, notes_doc, meta, [preset], {preset: key}, midi)
    version = int((notes_doc or {}).get("version", 0))
    with _PT_LOCK:  # the page and the automatic render may ask at once: one render
        # The latest notes and the latest of this kind: older renders waiting
        # for their turn (or running) give way to this one.
        # Read now, so the score as it stands: the latest (a new transcription
        # starts again at version 1, hence no "newer than" comparison).
        _PT_NOTES[(job.id, stem)] = version
        _PT_WANT[(job.id, stem, hand, speed)] = key
        status = _pt_status(job.id, stem, key)
        if status["state"] in ("ready", "rendering"):
            return status
        _PT_RUNS[(job.id, stem, key)] = {"state": "rendering"}
        _PT_HIGH += 1
    threading.Thread(
        target=_pt_render,
        args=(job.id, stem, key, midi, preset, version, hand, speed),
        daemon=True,
    ).start()
    return {"state": "rendering", "key": key}


def _pt_preset(job_id: str, stem: str, presets: list[str], default: str | None) -> str | None:
    """The piano last chosen for this score (the page's «Pianoteq» select),
    else Pianoteq's default."""
    last = (store.read_meta(job_id, stem).get("pianoteq") or {}).get("preset")
    return last if last in presets else default


def _pt_combos() -> list[tuple[str | None, float]]:
    """(hand, speed) of the background renders, as Settings › Storage asks
    («pianoteq_background»): "all" every speed and hand, "hands" both hands
    and each hand at 100 %, "main" only both hands at 100 %, "off" none."""
    from app.core.settings import get_pianoteq_background

    mode = get_pianoteq_background()
    if mode == "off":
        return []
    speeds = PT_SPEEDS if mode == "all" else (1.0,)
    hands = PT_HANDS if mode in ("all", "hands") else (None,)
    return [(h, s) for s in speeds for h in hands]


def _pt_variants(job_id: str, stem: str) -> list[tuple[str, str, str | None, float]]:
    """Every background render of one score, in the order they are made:
    by speed (100 %, 70 %, 50 %, 25 %), and at each speed both hands, the
    right hand alone, the left hand alone (as far as _pt_combos allows)."""
    return [(job_id, stem, h, s) for h, s in _pt_combos()]


def pt_current(job, stem: str, keys: bool = True) -> tuple[dict, int, str | None]:
    """The renders this score would have now with its piano: {key: (hand,
    speed)} for every speed and hand, its notes version and the piano
    (storage.py tells the renders on disk apart with it)."""
    info = pianoteq.info()
    if not info["available"]:
        return {}, None, None
    preset = _pt_preset(job.id, stem, info["presets"], info["default"])
    notes_doc = store.read_notes(job.id, stem)
    version = int((notes_doc or {}).get("version", 0))
    if not keys:
        return {}, version, preset
    meta = store.read_meta(job.id, stem)
    out = {}
    for speed in PT_SPEEDS:
        for hand in PT_HANDS:
            _, sig = service.performance_signature(
                job, stem, notes_doc, meta, hand=hand, speed=speed
            )
            out[pianoteq.render_key(sig, preset)] = (hand, speed)
    return out, version, preset


def _pt_queue(tasks, front: bool = False) -> None:
    """Queue background renders (see _PT_BG): `front` for the song just made
    or opened (before everything else), else at the end (the startup sweep)."""
    global _PT_BG_RUNNING
    if os.environ.get("STEMDECK_PIANOTEQ_AUTO", "1") == "0":
        return  # off (the tests: a real Pianoteq must not render behind them)
    tasks = list(tasks)
    with _PT_LOCK:
        for t in tasks:
            if t in _PT_BG:
                _PT_BG.remove(t)
        if front:
            _PT_BG.extendleft(reversed(tasks))
        else:
            _PT_BG.extend(tasks)
        if _PT_BG_RUNNING:
            return
        _PT_BG_RUNNING = True
    threading.Thread(target=_pt_background_loop, daemon=True, name="pianoteq-bg").start()


def _pt_background(job_id: str, stem: str, front: bool = False) -> None:
    """Every variant of this score (_pt_variants), in the background."""
    _pt_queue(_pt_variants(job_id, stem), front=front)


def _pt_background_loop() -> None:
    global _PT_BG_RUNNING
    while True:
        task = None
        with _PT_LOCK:
            busy = _PT_HIGH > 0
            if not busy:
                if not _PT_BG:
                    _PT_BG_RUNNING = False
                    return
                task = _PT_BG.popleft()
        if task is None:  # the page is waiting for a render: it goes first
            time.sleep(0.5)
            continue
        try:
            if _pt_background_one(*task) == "yielded":
                with _PT_LOCK:
                    if task not in _PT_BG:
                        _PT_BG.appendleft(task)
        except Exception as exc:  # noqa: BLE001 -- a head start only
            logger.warning("pianoteq background render of %s skipped: %s", task, exc)


def _pt_background_one(job_id: str, stem: str, hand: str | None, speed: float = 1.0) -> str:
    """One background render: "done", "skipped" (nothing to do), or
    "yielded" (stopped for a render the page asked for: queued again)."""
    job = registry_get(job_id)
    if job is None or job.status != "done" or getattr(job, "trashed_at", None):
        return "skipped"
    if not (store.score_dir(job_id, stem) / "raw.json").is_file():
        return "skipped"
    available = pianoteq.info()
    if not available["available"]:
        return "skipped"
    preset = _pt_preset(job_id, stem, available["presets"], available["default"])
    if not preset:
        return "skipped"
    notes_doc = store.read_notes(job_id, stem)
    meta = store.read_meta(job_id, stem)
    midi, sig = service.performance_signature(job, stem, notes_doc, meta, hand=hand, speed=speed)
    key = pianoteq.render_key(sig, preset)
    if hand is None and speed == 1.0:
        _adopt_legacy(job, stem, notes_doc, meta, [preset], {preset: key}, midi)
    version = int((notes_doc or {}).get("version", 0))
    with _PT_LOCK:
        _PT_NOTES[(job_id, stem)] = version  # read now: the score as it stands
        if _pt_status(job_id, stem, key)["state"] in ("ready", "rendering"):
            return "skipped"
        _PT_RUNS[(job_id, stem, key)] = {"state": "rendering"}
        _PT_BG_NOW.update(job=job_id, stem=stem, hand=hand, speed=speed, since=time.time())

    def wanted() -> bool:
        with _PT_LOCK:
            return _PT_HIGH == 0 and _PT_NOTES.get((job_id, stem), version) == version

    try:
        # Below normal priority: the page, the audio and a separation stay
        # smooth while it renders.
        pianoteq.render_as(midi, preset, _pt_folder(job_id, stem), key, wanted=wanted, low=True)
        storage.note_render(
            _pt_folder(job_id, stem), key, preset=preset, hand=hand, speed=speed, version=version
        )
        logger.info(
            "[%s] pianoteq %s at %d %% (%s) rendered in the background",
            job_id,
            hand or "both hands",
            round(speed * 100),
            preset,
        )
        return "done"
    except pianoteq.Superseded:
        with _PT_LOCK:
            edited = _PT_NOTES.get((job_id, stem), version) != version
        return "skipped" if edited else "yielded"
    finally:
        with _PT_LOCK:
            _PT_BG_NOW.clear()
            if (_PT_RUNS.get((job_id, stem, key)) or {}).get("state") == "rendering":
                _PT_RUNS.pop((job_id, stem, key), None)


def pianoteq_soon(job, stem: str) -> None:
    """Render the score with Pianoteq in the background, without anyone
    asking: every score gets its Pianoteq audio at every practice speed and
    for each hand (_pt_variants), and nothing waits for it (the transcription
    is done, the page opens; the renders run beside, giving way to any the
    page asks for)."""
    _pt_background(job.id, stem, front=True)


def pianoteq_sweep() -> int:
    """Every finished score's Pianoteq audio, made in the background when the
    server starts: what is missing is rendered (songs made before the speeds
    and the hands were rendered too), the rest is skipped at once. By speed
    first: every song at 100 % (both hands, right, left), the most recently
    worked on first; then every song at 70 %, 50 %, 25 %. Returns how many
    scores were queued."""
    from app.core.registry import all_jobs

    if os.environ.get("STEMDECK_PIANOTEQ_AUTO", "1") == "0":
        return 0
    try:
        if not pianoteq.info()["available"]:
            return 0
    except Exception:  # noqa: BLE001
        return 0
    found = []
    for job_id, job in all_jobs().items():
        if job.status != "done" or getattr(job, "trashed_at", None) or not JOB_ID_RE.match(job_id):
            continue
        root = JOBS_DIR / job_id / "score"
        for d in root.iterdir() if root.is_dir() else []:
            raw = d / "raw.json"
            if d.is_dir() and raw.is_file():
                notes = d / "notes.json"
                found.append(((notes if notes.is_file() else raw).stat().st_mtime, job_id, d.name))
    scores = [(job_id, stem) for _, job_id, stem in sorted(found, reverse=True)]
    combos = _pt_combos()
    _pt_queue([(j, s, h, v) for v in PT_SPEEDS for j, s in scores for h, cv in combos if cv == v])
    return len(scores)


def pianoteq_queue_state() -> dict:
    """What the background is doing: the render running, and how many wait."""
    with _PT_LOCK:
        return {"running": dict(_PT_BG_NOW) or None, "waiting": len(_PT_BG)}


@router.get("/score/pianoteq/queue")
async def pianoteq_queue() -> JSONResponse:
    return JSONResponse(pianoteq_queue_state())


@router.post("/jobs/{job_id}/score/{stem}/pianoteq")
async def pianoteq_render(job_id: str, stem: str, body: PianoteqBody) -> JSONResponse:
    """Render the score as it stands now; returns at once ("rendering") and
    the page polls the status. The same notes and preset render only once.
    The piano is kept as this score's own (not the hand or the speed)."""
    job = _job_or_404(job_id, stem)
    _require_done(job_id, stem)
    available = await asyncio.to_thread(pianoteq.info)
    if not available["available"]:
        raise HTTPException(status_code=404, detail="Pianoteq no está instalado")
    if body.preset not in available["presets"]:
        raise HTTPException(status_code=422, detail="preset desconocido")
    if (store.read_meta(job_id, stem).get("pianoteq") or {}).get("preset") != body.preset:
        # Remembered, so the next automatic render uses the same piano.
        store.update_meta(job_id, stem, lambda meta: meta.update(pianoteq={"preset": body.preset}))
    status = await asyncio.to_thread(_pt_start, job, stem, body.preset, body.hand, body.speed)
    return JSONResponse(status, status_code=200 if status["state"] == "ready" else 202)


def _pt_ready(job, stem: str) -> dict:
    info = pianoteq.info()
    meta = store.read_meta(job.id, stem)
    preset = (meta.get("pianoteq") or {}).get("preset")
    if not info["available"]:
        return {"preset": preset, "ready": []}
    notes_doc = store.read_notes(job.id, stem)
    midi, sig = service.performance_signature(job, stem, notes_doc, meta)
    keys = {p: pianoteq.render_key(sig, p) for p in info["presets"]}
    _adopt_legacy(job, stem, notes_doc, meta, info["presets"], keys, midi)
    folder = _pt_folder(job.id, stem)
    ready = [p for p in info["presets"] if pianoteq.audio_path(folder, keys[p]).is_file()]
    # This score's piano at each practice speed and hand: which are made
    # ("100:both", "70:R"...), for the page to mark the speeds ready.
    own = (
        preset
        if preset in info["presets"]
        else _pt_preset(job.id, stem, info["presets"], info["default"])
    )
    variants = []
    for speed in PT_SPEEDS:
        for hand in PT_HANDS:
            if hand is None and speed == 1.0:
                ok = own in ready
            else:
                _, vsig = service.performance_signature(
                    job, stem, notes_doc, meta, hand=hand, speed=speed
                )
                ok = pianoteq.audio_path(folder, pianoteq.render_key(vsig, own)).is_file()
            if ok:
                variants.append(f"{round(speed * 100)}:{hand or 'both'}")
    return {
        "preset": preset if preset in info["presets"] else None,
        "ready": ready,
        "piano": own,
        "variants": variants,
    }


@router.get("/jobs/{job_id}/score/{stem}/pianoteq/ready")
async def pianoteq_ready(job_id: str, stem: str) -> JSONResponse:
    """This score's own piano, and every piano already rendered for its
    notes as they stand: those play at once, no new render."""
    job = _job_or_404(job_id, stem)
    _require_done(job_id, stem)
    return JSONResponse(await asyncio.to_thread(_pt_ready, job, stem))


@router.get("/jobs/{job_id}/score/{stem}/pianoteq/status/{key}")
async def pianoteq_status(job_id: str, stem: str, key: str) -> JSONResponse:
    _job_or_404(job_id, stem)
    if not pianoteq.valid_key(key):
        raise HTTPException(status_code=404, detail="unknown render")
    return JSONResponse(_pt_status(job_id, stem, key))


@router.get("/jobs/{job_id}/score/{stem}/pianoteq/audio/{key}.flac")
async def pianoteq_audio(job_id: str, stem: str, key: str) -> FileResponse:
    _job_or_404(job_id, stem)
    if not pianoteq.valid_key(key):
        raise HTTPException(status_code=404, detail="unknown render")
    path = pianoteq.audio_path(_pt_folder(job_id, stem), key)
    if not path.is_file():
        raise HTTPException(status_code=404, detail="not rendered")
    # The key is a hash of the content: the file never changes under its name.
    return FileResponse(
        path, media_type="audio/flac", headers={"Cache-Control": "private, max-age=31536000"}
    )


# -- practice and the library ------------------------------------------------


class PracticeBody(BaseModel):
    seconds: float = Field(default=0, ge=0, le=3600)  # practised since the last report
    speed: int | None = Field(default=None, ge=25, le=125)  # % reached (a loop played through)
    loops: int = Field(default=0, ge=0, le=1000)
    accuracy: float | None = Field(default=None, ge=0, le=1)  # MIDI keyboard: hit / asked


@router.put("/jobs/{job_id}/score/{stem}/practice")
async def put_practice(job_id: str, stem: str, body: PracticeBody) -> JSONResponse:
    """Practice kept with the score: total time, best speed, loops, the
    last accuracy on a MIDI keyboard. The library shows it per song."""
    _job_or_404(job_id, stem)
    _require_done(job_id, stem)

    def change(meta: dict) -> None:
        p = dict(meta.get("practice") or {})
        p["seconds"] = round(float(p.get("seconds", 0)) + body.seconds, 1)
        p["loops"] = int(p.get("loops", 0)) + body.loops
        if body.speed is not None:
            p["best_speed"] = max(int(p.get("best_speed", 0)), body.speed)
        if body.accuracy is not None:
            p["accuracy"] = round(body.accuracy, 3)
            p["best_accuracy"] = max(float(p.get("best_accuracy", 0)), round(body.accuracy, 3))
        p["last_at"] = round(time.time(), 1)
        meta["practice"] = p

    meta = await asyncio.to_thread(store.update_meta, job_id, stem, change)
    return JSONResponse(meta["practice"])


def _library() -> dict:
    from app.core.registry import all_jobs

    out: dict[str, dict] = {}
    for job_id, job in all_jobs().items():
        if job.status != "done" or not JOB_ID_RE.match(job_id):
            continue
        stems: dict[str, dict] = {}
        root = JOBS_DIR / job_id / "score"
        for d in sorted(root.iterdir()) if root.is_dir() else []:
            if not d.is_dir() or not engines.supports(d.name):
                continue
            if not (d / "raw.json").is_file():
                if (d / "error.json").is_file():
                    stems[d.name] = {"state": "error"}
                continue
            notes = store.read_json(d / "notes.json") or {}
            meta = store.read_json(d / "meta.json") or {}
            pt = d / "pianoteq"
            stems[d.name] = {
                "state": "done",
                "edited": bool(notes.get("edited")),
                "notes": len(notes.get("notes") or []),
                "pianoteq": pt.is_dir() and any(pt.glob("*.flac")),
                "preset": (meta.get("pianoteq") or {}).get("preset"),
                "practice": meta.get("practice") or {},
            }
        with _RUNS_LOCK:
            for (jid, stem), run in _RUNS.items():
                if jid == job_id and run["state"] in ("queued", "running"):
                    stems[stem] = {"state": run["state"], "progress": run.get("progress", 0)}
        if stems:
            out[job_id] = stems
    return out


@router.get("/score/library")
async def score_library() -> JSONResponse:
    """Per song: which stems have a score, edited or not, with Pianoteq
    ready, and their practice (the /score/ list and the phone show it)."""
    return JSONResponse(await asyncio.to_thread(_library))


# -- prepared after the separation -------------------------------------------

# Presence (0-100, the job's per-stem RMS) from which a piano is prepared by itself.
AUTO_PIANO_PRESENCE = 25


def prepare_after_separation(job) -> None:
    """A song with a piano in it gets its score (and then its Pianoteq audio)
    as soon as its separation is done, queued like any transcription: opening
    the score later finds it ready. Off with STEMDECK_SCORE_AUTO=0."""
    if os.environ.get("STEMDECK_SCORE_AUTO", "1") == "0":
        return
    try:
        if not store.stem_wav(job.id, "piano").is_file():
            return
        presence = (job.stem_presence or {}).get("piano")
        if presence is not None and presence < AUTO_PIANO_PRESENCE:
            return
        if _status(job.id, "piano")["state"] != "none":
            return
        with _RUNS_LOCK:
            _RUNS[(job.id, "piano")] = {"state": "queued", "phase": "queued", "progress": 0.0}
        asyncio.get_running_loop().create_task(_run_async(job, "piano", "auto"))
        logger.info("[%s] piano score queued after the separation", job.id)
    except Exception as exc:  # noqa: BLE001 -- the page can still start it
        logger.warning("[%s] automatic score skipped: %s", job.id, exc)


CALIBRATION_JOB_ID = "ca11b0000001"
CALIBRATION_TITLE = "Calibración de partitura (Fa mayor, 90 BPM)"


def _make_calibration_job():
    import json as _json

    import numpy as np
    import soundfile as sf

    from app.core.models import Job
    from app.core.registry import persist as registry_persist
    from app.core.registry import register as registry_register
    from app.pipeline.collect import compute_stem_peaks
    from app.score import calibration as cal

    stems_dir = JOBS_DIR / CALIBRATION_JOB_ID / "stems"
    stems_dir.mkdir(parents=True, exist_ok=True)
    audio = cal.synthesize(cal.notes())
    stereo = np.stack([audio, audio], axis=1)
    sf.write(stems_dir / "piano.wav", stereo, 44100, subtype="PCM_16")
    beats = cal.beats()
    (stems_dir / "beats.json").write_text(
        _json.dumps(
            {
                "version": 1,
                "source": "calibration",
                "detector": "calibration",
                "bars": cal.bars(),
                "bpm": cal.BPM,
                "duration": len(audio) / 44100,
                "confidence": 100,
                "onsets": beats,
                "beats": beats,
            }
        ),
        encoding="utf-8",
    )
    rms = compute_stem_peaks(stems_dir, ["piano"])
    job = Job(
        id=CALIBRATION_JOB_ID,
        status="done",
        progress=1.0,
        stage_message="Done",
        title=CALIBRATION_TITLE,
        duration_sec=len(audio) / 44100,
        bpm=int(cal.BPM),
        key=cal.KEY[0],
        scale=cal.KEY[1],
        key_confidence=100,
        source_url="local:calibracion-partitura",
        source_format="wav",
        stem_presence={"piano": 100} if rms else None,
        stems=[{"name": "piano", "url": f"/api/jobs/{CALIBRATION_JOB_ID}/stems/piano.wav"}],
        selected_stems=["piano"],
    )
    registry_register(job)
    registry_persist(JOBS_DIR)
    return job


@router.post("/score/calibration")
async def make_calibration() -> JSONResponse:
    """Register the calibration piece as a library track (idempotent). Its
    expected score is published with it, so what the page shows can be
    checked against a list rather than judged by eye."""
    from app.score import calibration as cal

    job = registry_get(CALIBRATION_JOB_ID)
    if job is None or not store.stem_wav(CALIBRATION_JOB_ID, "piano").is_file():
        job = await asyncio.to_thread(_make_calibration_job)
    return JSONResponse(
        {
            "job_id": job.id,
            "title": job.title,
            "expected": cal.EXPECTED,
            "expected_text": cal.EXPECTED_TEXT,
        }
    )


@router.get("/score/calibration/expected")
async def calibration_expected() -> JSONResponse:
    from app.score import calibration as cal

    return JSONResponse(
        {"job_id": CALIBRATION_JOB_ID, "expected": cal.EXPECTED, "expected_text": cal.EXPECTED_TEXT}
    )


# -- playback audio for the score page: FLAC, so every switch lands on the sample --
#
# The page plays one <audio> element as the clock and switches it between the
# stem, the whole song and Pianoteq at the same moment of the song. A VBR MP3
# (the app's stems and mixdowns) lands a seek 40-170 ms off in Chrome while
# reporting the exact time asked for, so after each switch the score, the MIDI
# and the sound drifted apart. FLAC lands within 3 ms (measured, Comptine) at
# about a third of a WAV's size. Kept on disk next to the score.

_AUDIO_LOCK = threading.Lock()


def _flac_of(src, dest) -> None:
    import subprocess
    import sys

    from app.core.config import ffmpeg_executable

    if dest.is_file() and dest.stat().st_mtime >= src.stat().st_mtime:
        return
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_name(f".{dest.name}.part.flac")
    subprocess.run(
        [ffmpeg_executable(), "-nostdin", "-loglevel", "error", "-y", "-i", str(src),
         "-ar", "44100", "-c:a", "flac", str(tmp)],
        check=True, capture_output=True, stdin=subprocess.DEVNULL,
        creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0,
    )  # fmt: skip
    tmp.replace(dest)


@router.get("/jobs/{job_id}/score/audio/{name}.flac")
async def score_audio(job_id: str, name: str) -> FileResponse:
    """A stem (`name`), or the whole song (`mix`), as FLAC for the score page."""
    job = registry_get(job_id)
    if job is None or not re.fullmatch(r"[a-z_]{2,20}", name):
        raise HTTPException(status_code=404, detail="not found")
    src = store.source_audio(job_id) if name == "mix" else store.stem_wav(job_id, name)
    if src is None or not src.is_file():
        raise HTTPException(status_code=404, detail="no audio")
    dest = store.JOBS_DIR / job_id / "score" / "audio" / f"{name}.flac"

    def make() -> None:
        with _AUDIO_LOCK:
            _flac_of(src, dest)

    await asyncio.to_thread(make)
    return FileResponse(dest, media_type="audio/flac", headers={"Cache-Control": "no-cache"})
