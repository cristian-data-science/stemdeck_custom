"""Notes with a known hand, for training and measuring app/score/hands.py.

* hannds (github.com/cemfi/hannds, MIT): 122 pieces played by conservatory
  students with the right hand on one keyboard and the left on another, so
  every note's hand is the hand that played it. Track 0 "rechts" is the right
  hand, track 1 "links" the left. Clone it and pass its data-hannds folder.
* Local jobs whose hands are known: falling-notes videos (each hand lit in its
  own colour, app/score/video_notes.py) and the Chopin nocturne built from its
  printed staves. Their notes.json carry "hand" on every note.
"""

from __future__ import annotations

import json
from pathlib import Path

import mido

ROOT = Path(__file__).resolve().parents[2]

# Job id -> name. "Nature of Daylight B" is listed but left out of the totals:
# from 200 s to 320 s its video paints 62 notes every 20 s over three octaves
# (F2-F5) as the left hand and 5 as the right -- the colour reading merged two
# of the video's colours; it is not ground truth there.
KNOWN_JOBS = {
    "187e80d4472f": "TURiSTA (video)",
    "1f69a44075e8": "Y dime intro (video)",
    "25300f4498ba": "Nature of Daylight A (video)",
    "ab7e8209ab33": "BAILE INoLVIDABLE (video)",
    "abc24534faa0": "Nature of Daylight B (video)",
    "e0640828479e": "Nocturno Chopin (partitura)",
}
UNRELIABLE = {"Nature of Daylight B (video)"}


def _tick_to_sec(mid: mido.MidiFile):
    changes = sorted(
        (t, m.tempo) for tr in mid.tracks for t, m in _abs(tr) if m.type == "set_tempo"
    )
    if not changes or changes[0][0] != 0:
        changes.insert(0, (0, 500000))
    segs, sec = [], 0.0
    for i, (t, tempo) in enumerate(changes):
        segs.append((t, sec, tempo))
        if i + 1 < len(changes):
            sec += (changes[i + 1][0] - t) * tempo / 1e6 / mid.ticks_per_beat

    def f(tick: int) -> float:
        for t, s, tempo in reversed(segs):
            if tick >= t:
                return s + (tick - t) * tempo / 1e6 / mid.ticks_per_beat
        return 0.0

    return f


def _abs(track):
    t = 0
    for m in track:
        t += m.time
        yield t, m


def _track_notes(track) -> list[tuple[int, int, int, int]]:
    out, on = [], {}
    for tick, m in _abs(track):
        if m.type == "note_on" and m.velocity > 0:
            on.setdefault(m.note, []).append((tick, m.velocity))
        elif m.type in ("note_off", "note_on") and on.get(m.note):
            t0, v = on[m.note].pop(0)
            out.append((t0, tick, m.note, v))
    return out


def hannds(folder: str | Path) -> list[tuple[str, list[dict]]]:
    songs = []
    # By name as a plain string: Path sorting ignores case on Windows only,
    # which changed the held-out draw from one platform to another.
    for path in sorted(Path(folder).glob("*.mid"), key=lambda p: p.name):
        mid = mido.MidiFile(path)
        sec = _tick_to_sec(mid)
        notes = []
        for hand, track in (("R", mid.tracks[0]), ("L", mid.tracks[1])):
            for t0, t1, m, v in _track_notes(track):
                notes.append(
                    {"midi": m, "start": sec(t0), "end": sec(t1), "velocity": v, "gt": hand}
                )
        notes.sort(key=lambda n: (n["start"], n["midi"]))
        for i, n in enumerate(notes):
            n["id"] = f"h{i:05d}"
        songs.append((path.stem, notes))
    return songs


def known_jobs(jobs_dir: str | Path = ROOT / "jobs") -> list[tuple[str, list[dict]]]:
    songs = []
    for job, name in KNOWN_JOBS.items():
        path = Path(jobs_dir) / job / "score" / "piano" / "notes.json"
        if not path.exists():
            continue
        doc = json.loads(path.read_text(encoding="utf-8"))
        notes = [
            {
                "id": n["id"],
                "midi": n["midi"],
                "start": n["start"],
                "end": n["end"],
                "velocity": n.get("velocity", 80),
                "gt": n["hand"],
            }
            for n in doc["notes"]
            if n.get("hand") in ("L", "R")
        ]
        songs.append((name, notes))
    return songs


def user_held_out(job_id: str) -> bool:
    """One user song in five is kept out of training to measure on, fixed by
    its id (so it stays out however many songs are added later)."""
    import hashlib

    return int(hashlib.sha1(job_id.encode()).hexdigest(), 16) % 5 == 0


def user_labels(jobs_dir: str | Path = ROOT / "jobs") -> list[dict]:
    """Hands the user confirmed in the app (app/score/hand_labels.py).

    Per score: {"job", "stem", "name", "held_out", "reviewed", "notes"} where
    notes carry "gt" ("R" / "L") when the user set or confirmed that note's
    hand, else None (unknown: no loss on it). A song marked reviewed is all
    labelled, from its snapshot. Otherwise the labels are the notes whose last
    logged correction set a hand and that still exist on the same key and
    are not set to the other hand now (a reset to the transcription keeps
    them: same ids). The known-hand jobs are left out: they are the benchmark.
    """
    out = []
    for score in sorted(Path(jobs_dir).glob("*/score/*")):
        job, stem = score.parent.parent.name, score.name
        if job in KNOWN_JOBS:
            continue
        reviewed = score / "hands_reviewed.json"
        log = score / "hand_labels.jsonl"
        if reviewed.is_file():
            snap = json.loads(reviewed.read_text(encoding="utf-8"))
            notes = [
                {**n, "gt": n["hand"] if n.get("hand") in ("L", "R") else None}
                for n in snap["notes"]
            ]
        elif log.is_file() and (score / "notes.json").is_file():
            last: dict[str, dict] = {}
            for line in log.read_text(encoding="utf-8").splitlines():
                try:
                    e = json.loads(line)
                except ValueError:
                    continue
                last[e["id"]] = e
            doc = json.loads((score / "notes.json").read_text(encoding="utf-8"))
            notes = []
            for n in doc["notes"]:
                e = last.get(n["id"])
                gt = None
                if (
                    e
                    and e.get("hand") in ("L", "R")
                    and e.get("midi") == n["midi"]
                    and n.get("hand") in (None, e["hand"])
                ):
                    gt = e["hand"]
                notes.append(
                    {
                        "id": n["id"],
                        "midi": n["midi"],
                        "start": n["start"],
                        "end": n["end"],
                        "velocity": n.get("velocity", 80),
                        "gt": gt,
                    }
                )
        else:
            continue
        labelled = sum(1 for n in notes if n["gt"])
        if not labelled:
            continue
        notes.sort(key=lambda n: (n["start"], n["midi"]))
        out.append(
            {
                "job": job,
                "stem": stem,
                "name": f"{job}/{stem}",
                "held_out": user_held_out(job),
                "reviewed": reviewed.is_file(),
                "labelled": labelled,
                "notes": notes,
            }
        )
    return out


def held_out(songs: list[tuple[str, list[dict]]], k: int = 12, seed: int = 1) -> set[str]:
    """The hannds pieces kept out of training to measure on (fixed)."""
    import random

    return set(random.Random(seed).sample(sorted(name for name, _ in songs), k))
