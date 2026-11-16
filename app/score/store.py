"""Files of one stem's score: jobs/<job_id>/score/<stem>/.

  raw.json    what the model heard. Written once by the worker, never edited:
              it is what "Restaurar" goes back to.
  notes.json  the notes the score is drawn from: the raw notes after the
              automatic clean-up, plus every edit. Saved on each edit, so
              edits survive a reload, a restart and a re-quantization.
  meta.json   view settings (grid, hand split, tempo override, chord rate,
              names) and chord-name overrides.
  error.json  the last failure, if the transcription failed.

Every write is atomic (temp file + os.replace), so a crash mid-save leaves the
previous version, never a truncated file.
"""

from __future__ import annotations

import json
import logging
import os
import threading
import time
import uuid
from pathlib import Path

from app.core.config import JOBS_DIR, STEM_NAMES

AUTO_MIN_DURATION = 0.03  # seconds; shorter detections are blips, not notes
_LOCK = threading.Lock()


def score_dir(job_id: str, stem: str) -> Path:
    d = (JOBS_DIR / job_id / "score" / stem).resolve()
    if not d.is_relative_to(JOBS_DIR.resolve()):
        raise ValueError("bad path")
    return d


def stem_wav(job_id: str, stem: str) -> Path:
    return (JOBS_DIR / job_id / "stems" / f"{stem}.wav").resolve()


def source_audio(job_id: str) -> Path | None:
    """The job's full audio, for transcribing a solo piano from all of it.

    An upload keeps its import as jobs/<id>/source.<ext>. A YouTube import
    does not (the download is deleted after separation), and stems/original.wav
    is not the original either: it is the sum of the stems the user did *not*
    select (collect.make_original_track). So, failing source.*, the full audio
    is rebuilt as the sum of the separated stems -- Demucs' sources add back
    up to (close to) the mixture -- and cached as score/full_mix.wav.
    """
    root = (JOBS_DIR / job_id).resolve()
    if not root.is_relative_to(JOBS_DIR.resolve()) or not root.is_dir():
        return None
    found = sorted(p for p in root.glob("source.*") if p.is_file() and p.suffix != ".part")
    if found:
        return found[0]
    cached = root / "score" / "full_mix.wav"
    if cached.is_file():
        return cached
    stems = [root / "stems" / f"{name}.wav" for name in STEM_NAMES]
    stems = [p for p in stems if p.is_file()]
    if len(stems) < 2:
        return None
    try:
        import numpy as np
        import soundfile as sf

        total, rate = None, None
        for path in stems:
            data, sr = sf.read(path, dtype="float32", always_2d=True)
            if total is None:
                total, rate = data.copy(), sr
            elif sr == rate:
                n = min(len(total), len(data))
                total = total[:n] + data[:n]
        peak = float(np.max(np.abs(total))) if total is not None and total.size else 0.0
        if peak > 1.0:
            total /= peak
        cached.parent.mkdir(parents=True, exist_ok=True)
        tmp = cached.with_suffix(".tmp.wav")
        sf.write(tmp, total, rate, subtype="PCM_16")
        os.replace(tmp, cached)
        return cached
    except Exception:  # noqa: BLE001 -- no full audio just means "use the stem"
        return None


def beats_path(job_id: str) -> Path:
    return (JOBS_DIR / job_id / "stems" / "beats.json").resolve()


def write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.parent / f".{path.name}.{uuid.uuid4().hex}.tmp"
    try:
        with tmp.open("w", encoding="utf-8", newline="\n") as fh:
            fh.write(json.dumps(data, ensure_ascii=False))
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, path)
    finally:
        tmp.unlink(missing_ok=True)


def read_json(path: Path) -> dict | None:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def read_raw(job_id: str, stem: str) -> dict | None:
    return read_json(score_dir(job_id, stem) / "raw.json")


def read_meta(job_id: str, stem: str) -> dict:
    return read_json(score_dir(job_id, stem) / "meta.json") or {}


def write_meta(job_id: str, stem: str, meta: dict) -> None:
    with _LOCK:
        write_json(score_dir(job_id, stem) / "meta.json", meta)


def update_meta(job_id: str, stem: str, change) -> dict:
    """Read, change and write meta.json as one step: `change(meta)` edits the
    dict in place. Read outside the lock, two edits at once (the piano chosen
    and a setting, a finger) could each write back the other's old copy."""
    with _LOCK:
        path = score_dir(job_id, stem) / "meta.json"
        meta = read_json(path) or {}
        change(meta)
        write_json(path, meta)
    return meta


def initial_notes(raw: dict) -> dict:
    """notes.json as first derived from raw.json: ids assigned, blips
    shorter than AUTO_MIN_DURATION removed (and counted, so the page can say
    so and "Restaurar" can bring them back).

    Ghost notes (ghosts.py: no attack in the audio) start out deleted: a
    re-strike ("merge") gives its time back to the note it repeats, a soft
    loose note ("drop") just goes; both are listed in «Notas borradas» (the
    trash), so any can come back with one click."""
    now = time.time()
    raw_notes = raw.get("notes", [])
    notes = []
    removed = 0
    ghosts = []
    by_id: dict[int, dict] = {}
    # In time order, so a re-strike finds the note it repeats; ids stay the
    # raw index.
    for i in sorted(range(len(raw_notes)), key=lambda i: raw_notes[i]["start"]):
        n = raw_notes[i]
        if n["end"] - n["start"] < AUTO_MIN_DURATION:
            removed += 1
            continue
        note = {
            "id": f"n{i:05d}",
            "midi": n["midi"],
            "start": n["start"],
            "end": n["end"],
            "velocity": n.get("velocity", 80),
            # A hand the source knows (the notes of a falling-notes video);
            # None lets the score place it (hands.py), as for a transcription.
            "hand": n.get("hand") if n.get("hand") in ("L", "R") else None,
        }
        ghost = n.get("ghost")
        if ghost in ("merge", "drop"):
            held = by_id.get(n["midi"])
            if ghost == "merge" and held is not None:
                held["end"] = max(held["end"], n["end"])
            why = "bleed" if n.get("ghost_why") == "bleed" else "ghost"
            ghosts.append({**note, "deleted_at": round(now, 3), "reason": why})
            continue
        by_id[n["midi"]] = note
        notes.append(note)
    notes.sort(key=lambda n: n["id"])
    return {
        "version": 1,
        "edited": False,
        "updated_at": now,
        "auto_clean": {
            "min_duration": AUTO_MIN_DURATION,
            "removed": removed,
            "ghosts": len(ghosts),
        },
        "notes": notes,
        "trash": ghosts,
    }


def read_notes(job_id: str, stem: str) -> dict | None:
    d = score_dir(job_id, stem)
    data = read_json(d / "notes.json")
    if data is not None:
        return data
    raw = read_raw(job_id, stem)
    if raw is None:
        return None
    data = initial_notes(raw)
    with _LOCK:
        write_json(d / "notes.json", data)
    return data


TRASH_MAX = 2000  # deleted notes kept for restoring, newest first


def _trash(current: dict, notes: list[dict], now: float) -> list[dict]:
    """The deleted-notes history after a save: notes gone since the last
    version join it (newest first); notes that are back (restored, undone)
    leave it."""
    present = {n["id"] for n in notes}
    gone = [
        {**n, "deleted_at": round(now, 3)}
        for n in current.get("notes") or []
        if n.get("id") not in present and not _joined(n, notes) and not _added(n)
    ]
    kept = [t for t in current.get("trash") or [] if t.get("id") not in present]
    seen = {t["id"] for t in gone}
    return (gone + [t for t in kept if t.get("id") not in seen])[:TRASH_MAX]


def _joined(gone: dict, notes: list[dict]) -> bool:
    """A note that left because it was joined into the one before it on its
    key (a "held" note now covering it): one longer note, not a deleted one,
    so it is not listed in «Borradas». Undo brings it back."""
    return any(
        n.get("held")
        and n["midi"] == gone["midi"]
        and n["start"] <= gone["start"] + 1e-3
        and n["end"] >= gone["end"] - 1e-3
        for n in notes
    )


def _added(note: dict) -> bool:
    """A note the user added on the page (id "nu..."): taken away again, it
    is just gone (Undo brings it back), not a transcribed note to restore."""
    return str(note.get("id", "")).startswith("nu")


# The edit history (score/<stem>/history.jsonl): one line per save, the notes
# it changed as they were before and after. Kept on the server, so an edit
# can be gone back on from any device, after a reload (the page's own undo
# lives in memory), and «Restaurar original» is one more entry, undoable too.
HISTORY = "history.jsonl"
HISTORY_KEEP = 300  # entries kept per score (the oldest drop off)
_NOTE_FIELDS = ("midi", "start", "end", "velocity", "hand", "held")


def _field(note: dict, key: str):
    v = note.get(key)
    if isinstance(v, bool) or v is None:
        return v or None  # held False and absent are the same
    if isinstance(v, (int, float)):
        return round(float(v), 4)
    return v


def _same(a: dict, b: dict) -> bool:
    return all(_field(a, k) == _field(b, k) for k in _NOTE_FIELDS)


def note_changes(old: list[dict], new: list[dict]) -> tuple[list[dict], list[dict]]:
    """(before, after): the notes a save changed -- removed or changed ones as
    they were, added or changed ones as they are now."""
    was = {n["id"]: n for n in old}
    now = {n["id"]: n for n in new}
    before = [n for i, n in was.items() if i not in now or not _same(n, now[i])]
    after = [n for i, n in now.items() if i not in was or not _same(was[i], n)]
    return before, after


def _log_history(d: Path, version: int, now: float, what: str | None, before, after) -> None:
    if not before and not after:
        return
    entry = {
        "v": version,
        "at": round(now, 3),
        "what": (what or "Edición")[:160],
        "before": before,
        "after": after,
    }
    path = d / HISTORY
    lines = path.read_text(encoding="utf-8").splitlines() if path.is_file() else []
    lines.append(json.dumps(entry, ensure_ascii=False, separators=(",", ":")))
    tmp = path.with_suffix(".tmp")
    tmp.write_text("\n".join(lines[-HISTORY_KEEP:]) + "\n", encoding="utf-8")
    os.replace(tmp, path)


def read_history(job_id: str, stem: str) -> list[dict]:
    """The edit history, oldest first."""
    path = score_dir(job_id, stem) / HISTORY
    out = []
    for line in path.read_text(encoding="utf-8").splitlines() if path.is_file() else []:
        try:
            out.append(json.loads(line))
        except ValueError:
            continue
    return out


def clear_history(job_id: str, stem: str) -> None:
    """A new transcription: the history is about notes that are gone."""
    (score_dir(job_id, stem) / HISTORY).unlink(missing_ok=True)


def notes_before(job_id: str, stem: str, version: int) -> tuple[list[dict], dict] | None:
    """The notes as they were just before the save that made `version`: the
    current ones with every later entry undone, newest first. None when the
    history does not reach that far back. Also returns that entry."""
    history = read_history(job_id, stem)
    target = next((e for e in history if e.get("v") == version), None)
    current = read_notes(job_id, stem)
    if target is None or current is None:
        return None
    notes = {n["id"]: n for n in current.get("notes") or []}
    for e in sorted((e for e in history if e.get("v", 0) >= version), key=lambda e: -e["v"]):
        for n in e.get("after") or []:
            notes.pop(n["id"], None)
        for n in e.get("before") or []:
            notes[n["id"]] = n
    return sorted(notes.values(), key=lambda n: (n["start"], n["midi"])), target


def save_notes(job_id: str, stem: str, notes: list[dict], what: str | None = None) -> dict:
    d = score_dir(job_id, stem)
    with _LOCK:
        current = read_json(d / "notes.json") or {}
        now = time.time()
        data = {
            "version": int(current.get("version", 0)) + 1,
            "edited": True,
            "updated_at": now,
            "auto_clean": current.get("auto_clean"),
            "notes": notes,
            "trash": _trash(current, notes, now),
        }
        write_json(d / "notes.json", data)
        try:
            before, after = note_changes(current.get("notes") or [], notes)
            _log_history(d, data["version"], now, what, before, after)
        except Exception:  # noqa: BLE001 -- the history never costs an edit
            logging.getLogger("stemdeck.score").warning("edit history not written", exc_info=True)
    return data


def reset_notes(job_id: str, stem: str) -> dict | None:
    raw = read_raw(job_id, stem)
    if raw is None:
        return None
    data = initial_notes(raw)
    with _LOCK:
        current = read_json(score_dir(job_id, stem) / "notes.json") or {}
        data["version"] = int(current.get("version", 0)) + 1
        # Back to the transcription: what it brings back leaves the history.
        # The ghost notes start in it again (ghosts.py).
        present = {n["id"] for n in data["notes"]}
        seen = {t["id"] for t in data["trash"]}
        data["trash"] = data["trash"] + [
            t
            for t in current.get("trash") or []
            if t.get("id") not in present and t.get("id") not in seen
        ]
        write_json(score_dir(job_id, stem) / "notes.json", data)
        try:
            before, after = note_changes(current.get("notes") or [], data["notes"])
            _log_history(
                score_dir(job_id, stem),
                data["version"],
                time.time(),
                "Restaurar original (sin ediciones)",
                before,
                after,
            )
        except Exception:  # noqa: BLE001
            logging.getLogger("stemdeck.score").warning("edit history not written", exc_info=True)
    return data
