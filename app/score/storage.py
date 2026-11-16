"""What the songs take on disk, and cleaning up what can be made again.

Per job: the stems, the score (notes, edits, history), the Pianoteq renders
split by kind -- the main one (both hands at 100 %), each hand alone at 100 %,
the slow ones (70, 50, 25 %) and old ones (notes edited since, another piano)
-- the video, the kept upload, the rest.

The Pianoteq renders are named by a hash (pianoteq.render_key), which says
nothing of what they are. Each render made since this module exists is noted
in pianoteq/index.json ({key: {hand, speed, preset, v}}). A render without an
entry (made before) is recognised by working out the keys of the score as it
stands now; what matches nothing is "old".

Cleaning deletes what is made again by itself: Pianoteq renders (from the
notes, on demand, or in the background if pianoteq_background asks for them)
and the score page's copies ("cache": the song rebuilt from its stems, FLAC
copies for playback). The stems, the score and its edits are never touched
here; a whole song goes to the Trash as before.
"""

from __future__ import annotations

import json
import logging
import os
import shutil
import threading
from pathlib import Path

from app.core.config import JOB_ID_RE
from app.score import store

logger = logging.getLogger(__name__)

INDEX = "index.json"
_LOCK = threading.Lock()

# Kinds of Pianoteq render, and what cleaning each one means.
PT_KINDS = ("pt_main", "pt_hands", "pt_slow", "pt_old")
CLEAN = {
    "cache": ("cache",),  # copies the score page makes again (_CACHE)
    "slow": ("pt_slow",),  # the slow speeds (70, 50, 25 %)
    "hands": ("pt_hands",),  # each hand alone at 100 %
    "old": ("pt_old",),  # notes edited since, another piano
    "pianoteq": PT_KINDS,  # every render
}


def _size(path: Path) -> int:
    if path.is_file():
        try:
            return path.stat().st_size
        except OSError:
            return 0
    total = 0
    for root, _dirs, files in os.walk(path):
        for f in files:
            try:
                total += os.stat(os.path.join(root, f)).st_size
            except OSError:
                pass
    return total


def read_index(folder: Path) -> dict:
    try:
        data = json.loads((folder / INDEX).read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def note_render(
    folder: Path, key: str, *, preset, hand, speed: float, version, old: bool = False
) -> None:
    """Say what a render is (called once it is made; `old`: of notes or a
    piano the score no longer has)."""
    with _LOCK:
        index = read_index(folder)
        index[key] = {"preset": preset, "hand": hand, "speed": speed, "v": version}
        if old:
            index[key]["old"] = True
        live = {p.stem for p in folder.glob("*.flac")}
        index = {k: v for k, v in index.items() if k in live}
        tmp = folder / (INDEX + ".tmp")
        try:
            tmp.write_text(json.dumps(index), encoding="utf-8")
            os.replace(tmp, folder / INDEX)
        except OSError:
            logger.warning("pianoteq index not written in %s", folder, exc_info=True)


def _kind(hand, speed: float) -> str:
    if speed != 1.0:
        return "pt_slow"
    return "pt_main" if hand is None else "pt_hands"


def classify(job, stem: str, current) -> dict[str, str]:
    """{flac name: kind} for one score's renders. `current(job, stem,
    keys=...)` gives the score as it stands now: ({key: (hand, speed)} of its
    renders with its piano -- worked out only when keys=True, for renders the
    index does not know --, its notes version, its piano) (app/api/score.py)."""
    folder = store.JOBS_DIR / job.id / "score" / stem / "pianoteq"
    flacs = [p for p in folder.glob("*.flac") if not p.name.endswith(".part.flac")]
    if not flacs:
        return {}
    index = read_index(folder)

    def now(keys: bool):
        try:
            return current(job, stem, keys=keys)
        except Exception:  # noqa: BLE001 -- unknown: old
            return {}, None, None

    _, version, preset = now(False)
    keys = None
    out = {}
    for p in flacs:
        entry = index.get(p.stem)
        if entry is not None and entry.get("old"):
            out[p.name] = "pt_old"
            continue
        if entry is not None:
            fresh = entry.get("v") == version and entry.get("preset") == preset
            out[p.name] = _kind(entry.get("hand"), entry.get("speed", 1.0)) if fresh else "pt_old"
            continue
        if keys is None:
            keys = now(True)[0]
        if p.stem in keys:
            hand, speed = keys[p.stem]
            out[p.name] = _kind(hand, speed)
            # Known from now on, without working the keys out again.
            note_render(folder, p.stem, preset=preset, hand=hand, speed=speed, version=version)
        else:
            out[p.name] = "pt_old"
            note_render(
                folder, p.stem, preset=None, hand=None, speed=1.0, version=version, old=True
            )
    return out


# Copies the score page makes and makes again when missing: the song rebuilt
# from its stems (score/full_mix.wav) and FLAC copies for playback
# (score/audio/). Cleaned with "cache".
_CACHE = ("full_mix.wav", "audio")


def job_usage(job, current) -> dict:
    root = store.JOBS_DIR / job.id
    parts = dict.fromkeys(("stems", "score", "cache", *PT_KINDS, "video", "source", "other"), 0)
    if not root.is_dir():
        return {"id": job.id, "title": job.title, "path": str(root), "parts": parts, "total": 0}
    for entry in root.iterdir():
        name = entry.name
        if name == "stems":
            parts["stems"] += _size(entry)
        elif name == "score" and entry.is_dir():
            for d in entry.iterdir():
                if d.name in _CACHE:
                    parts["cache"] += _size(d)
                    continue
                if not d.is_dir():
                    parts["score"] += _size(d)
                    continue
                kinds = classify(job, d.name, current)
                for sub in d.iterdir():
                    if sub.name == "pianoteq" and sub.is_dir():
                        for f in sub.iterdir():
                            k = kinds.get(f.name)
                            parts[k or "score"] += _size(f)
                    else:
                        parts["score"] += _size(sub)
        elif name == "video.mp4":
            parts["video"] += _size(entry)
        elif name.startswith("source."):
            parts["source"] += _size(entry)
        else:
            parts["other"] += _size(entry)
    return {
        "id": job.id,
        "title": job.title,
        "path": str(root),
        "parts": parts,
        "total": sum(parts.values()),
    }


def usage(jobs, current) -> dict:
    """Every job's usage (largest first), the totals and the disk."""
    rows = [job_usage(j, current) for j in jobs]
    rows.sort(key=lambda r: -r["total"])
    totals = {k: sum(r["parts"][k] for r in rows) for k in (rows[0]["parts"] if rows else {})}
    try:
        disk = shutil.disk_usage(store.JOBS_DIR)
        disk_info = {"total": disk.total, "free": disk.free, "used": disk.used}
    except OSError:
        disk_info = None
    return {
        "path": str(store.JOBS_DIR),
        "jobs": rows,
        "totals": totals,
        "total": sum(totals.values()),
        "disk": disk_info,
    }


def clean(jobs, what: str, current) -> dict:
    """Delete the Pianoteq renders of `what` ("slow", "hands", "old",
    "pianoteq") in these jobs. Returns {"files", "bytes"}."""
    kinds = CLEAN[what]
    files = freed = 0
    for job in jobs:
        if not JOB_ID_RE.match(job.id):
            continue
        root = store.JOBS_DIR / job.id / "score"
        if "cache" in kinds:
            for name in _CACHE:
                path = root / name
                size = _size(path)
                try:
                    if path.is_dir():
                        n = sum(1 for _ in path.iterdir())
                        shutil.rmtree(path)
                    elif path.is_file():
                        n = 1
                        path.unlink()
                    else:
                        continue
                except OSError:  # in use right now (Windows): left for next time
                    continue
                files += n
                freed += size
            continue
        for d in root.iterdir() if root.is_dir() else []:
            if not d.is_dir():
                continue
            folder = d / "pianoteq"
            for name, kind in classify(job, d.name, current).items():
                if kind not in kinds:
                    continue
                path = folder / name
                size = _size(path)
                try:
                    path.unlink()
                except OSError:  # playing right now (Windows): left for next time
                    continue
                files += 1
                freed += size
            if folder.is_dir():
                live = {p.stem for p in folder.glob("*.flac")}
                with _LOCK:
                    index = {k: v for k, v in read_index(folder).items() if k in live}
                    try:
                        (folder / INDEX).write_text(json.dumps(index), encoding="utf-8")
                    except OSError:
                        pass
    return {"files": files, "bytes": freed}
