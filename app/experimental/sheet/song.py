"""A library track made from a printed score.

Like the calibration track: no recording, so the audio is rendered from the
notes (Pianoteq when installed, the calibration synth otherwise). The beat
grid is the score's own (exact bars, the read tempo), each note keeps the hand
of its staff, and the fingers read from the page go to meta.json as fixed
fingers; the rest are suggested on request (fingering.py). Nothing is
transcribed: raw.json is written directly, so the score page opens it like
any other track.
"""

from __future__ import annotations

import io
import json
import secrets
import shutil
import subprocess
import sys
import time
from pathlib import Path

from app.core.config import JOBS_DIR
from app.experimental.sheet import omr
from app.experimental.sheet.musicxml import Score, parse

PRESET = "NY Steinway D Classical"
SR = 44100
SHEET_DIR = "sheet"  # jobs/<id>/sheet: the page, the MusicXML, the report


def _midi_bytes(notes: list[dict], bpm: float) -> bytes:
    import mido

    mid = mido.MidiFile(ticks_per_beat=480)
    tr = mido.MidiTrack()
    mid.tracks.append(tr)
    tempo = int(60_000_000 / bpm)
    tr.append(mido.MetaMessage("set_tempo", tempo=tempo, time=0))
    tick = lambda sec: round(sec * 480 * bpm / 60)  # noqa: E731
    ev = []
    for n in notes:
        on, off = tick(n["start"]), max(tick(n["end"]), tick(n["start"]) + 1)
        ev.append((on, 1, mido.Message("note_on", note=n["midi"], velocity=n["velocity"])))
        ev.append((off, 0, mido.Message("note_off", note=n["midi"], velocity=0)))
    ev.sort(key=lambda e: (e[0], e[1]))
    last = 0
    for t, _, msg in ev:
        msg.time = t - last
        tr.append(msg)
        last = t
    buf = io.BytesIO()
    mid.save(file=buf)
    return buf.getvalue()


def render_audio(notes: list[dict], bpm: float, wav: Path) -> str:
    """The track's audio: Pianoteq, else the calibration synth. Which one."""
    from app.score import pianoteq

    exe = pianoteq.executable()
    if exe is not None:
        mid = wav.with_suffix(".mid")
        mid.write_bytes(_midi_bytes(notes, bpm))
        flags = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
        subprocess.run(
            [
                str(exe),
                "--headless",
                "--quiet",
                "--preset",
                PRESET,
                "--midi",
                str(mid),
                "--wav",
                str(wav),
            ],
            capture_output=True,
            timeout=30 * 60,
            creationflags=flags,
            check=False,
        )
        mid.unlink(missing_ok=True)
        if wav.is_file() and wav.stat().st_size > 1000:
            return f"Pianoteq ({PRESET})"
    import numpy as np
    import soundfile as sf

    from app.score import calibration as cal

    audio = cal.synthesize(notes, sr=SR)
    sf.write(wav, np.stack([audio, audio], axis=1), SR, subtype="PCM_16")
    return "sintetizador"


def read_more_fingers(score: Score, omr_dir: Path) -> int:
    """The printed fingers Audiveris missed, read from its own page image
    (digits.py). Never fatal: an import without them is still an import."""
    import logging

    from app.experimental.sheet import digits

    book = next(iter(sorted(omr_dir.glob("*.omr"))), None)
    if book is None:
        return 0
    try:
        found, layout = digits.find_digits(book)
        return digits.attach(score.notes, digits.place(found, layout))
    except Exception as e:  # noqa: BLE001
        logging.getLogger(__name__).warning("finger digits not read: %s", e, exc_info=True)
        return 0


def create(image: Path, title: str, bpm: float | None = None, report=None) -> dict:
    """PDF/image -> a done library track. Returns the import report."""
    from app.experimental.sheet import ornaments

    job_id = secrets.token_hex(6)
    job_dir = JOBS_DIR / job_id
    sheet_dir = job_dir / SHEET_DIR
    sheet_dir.mkdir(parents=True, exist_ok=True)
    page = sheet_dir / f"page{image.suffix.lower()}"
    shutil.copyfile(image, page)

    say = report or (lambda phase: None)
    say("omr")
    t0 = time.time()
    mxl = omr.recognize(page, sheet_dir / "omr")
    score: Score = parse(mxl, bpm=bpm)
    if not score.notes:
        raise omr.OmrError("Audiveris no encontró notas en la partitura.")
    fingers_omr = score.fingers_read
    fingers_page = read_more_fingers(score, sheet_dir / "omr")
    omr_sec = round(time.time() - t0, 1)

    say("audio")
    result = write_track(
        job_id,
        title,
        ornaments.realize(score.notes),
        beats=score.beats,
        bars=score.bars,
        bpm=score.bpm,
        engine="partitura (Audiveris)",
        source_url=f"local:partitura:{image.name}",
        source_format=image.suffix.lower().lstrip("."),
        report={
            "measures": score.measures,
            "missing_measures": score.missing_measures,
            "fingers_audiveris": fingers_omr,
            "fingers_detector": fingers_page,
            "omr_seconds": omr_sec,
        },
    )
    return result


def write_track(
    job_id: str,
    title: str,
    notes: list[dict],
    *,
    beats: list[float],
    bars: list[dict],
    bpm: float,
    engine: str,
    source_url: str,
    source_format: str,
    report: dict | None = None,
) -> dict:
    """A done library track from notes in seconds (each with its staff, 1 =
    right hand, and maybe a printed finger): the rendered audio, the score's
    own beat grid, raw.json/notes.json and the fingers as fixed ones."""
    from app.core.models import Job
    from app.core.registry import persist as registry_persist
    from app.core.registry import register as registry_register
    from app.pipeline.collect import compute_stem_peaks
    from app.score import store

    job_dir = JOBS_DIR / job_id
    sheet_dir = job_dir / SHEET_DIR
    sheet_dir.mkdir(parents=True, exist_ok=True)
    notes = sorted(notes, key=lambda n: (n["start"], n["midi"]))
    stems = job_dir / "stems"
    stems.mkdir(parents=True, exist_ok=True)
    audio = render_audio(notes, bpm, stems / "piano.wav")
    import soundfile as sf

    duration = sf.info(stems / "piano.wav").duration
    store.write_json(
        stems / "beats.json",
        {
            "version": 1,
            "source": "sheet",
            "detector": "sheet",
            "bars": bars,
            "bpm": bpm,
            "duration": duration,
            "confidence": 100,
            "onsets": beats,
            "beats": beats,
        },
    )

    # The notes as read: raw.json, notes.json with each note's hand, and the
    # printed fingers (ids are the raw index, as store.initial_notes gives them).
    d = store.score_dir(job_id, "piano")
    d.mkdir(parents=True, exist_ok=True)
    raw_notes = [{k: n[k] for k in ("midi", "start", "end", "velocity")} for n in notes]
    store.write_json(
        d / "raw.json",
        {
            "engine": engine,
            "device": "cpu",
            "notes": raw_notes,
            "pedals": [],
            "audio_source": "sheet",
        },
    )
    doc = store.initial_notes({"notes": raw_notes})
    by_id = {x["id"]: x for x in doc["notes"]}
    for i, n in enumerate(notes):
        x = by_id.get(f"n{i:05d}")
        if x is not None:
            x["hand"] = "R" if n["staff"] == 1 else "L"
    store.write_json(d / "notes.json", doc)
    fixed = {
        f"n{i:05d}": {"f": n["finger"], "src": "score"}
        for i, n in enumerate(notes)
        if n.get("finger") and f"n{i:05d}" in by_id
    }
    store.write_meta(
        job_id,
        "piano",
        {"settings": {"pulse": "song"}, "fingering": {"source": "sheet", "fixed": fixed}},
    )

    result = {
        "job_id": job_id,
        "title": title,
        "notes": len(doc["notes"]),
        "fingers_read": len(fixed),
        "bpm": bpm,
        "audio": audio,
        **(report or {}),
    }
    (sheet_dir / "report.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=1), encoding="utf-8"
    )

    rms = compute_stem_peaks(stems, ["piano"])
    job = Job(
        id=job_id,
        status="done",
        progress=1.0,
        stage_message="Done",
        title=title,
        duration_sec=duration,
        bpm=round(bpm),
        source_url=source_url,
        source_format=source_format,
        stem_presence={"piano": 100} if rms else None,
        stems=[{"name": "piano", "url": f"/api/jobs/{job_id}/stems/piano.wav"}],
        selected_stems=["piano"],
    )
    registry_register(job)
    registry_persist(JOBS_DIR)
    return result
