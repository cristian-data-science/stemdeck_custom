"""The user's hand corrections, kept to retrain the hand model (hands.py).

notes.json keeps each note's "hand", but that alone cannot train a model: it
does not say whether the hand came from the user or from a falling-notes
video, nor what the model had said, and «Restaurar original» wipes it. So:

* hand_labels.jsonl (append-only, per score): one line per hand the user
  changed, whatever the tool (brush, edit bar, H) -- the note as it was, the
  hand set ("R" / "L", or null for «Auto»: back to the program), the hand the
  score showed before, the model's version and the time. It survives
  «Restaurar original» (the transcription keeps its note ids).
* hands_reviewed.json: «✓ Canción revisada» -- every note with the hand the
  score shows, all confirmed by the user. Labels for a whole passage are
  worth far more to training than scattered corrections; later corrections
  rewrite it, «Quitar revisada» deletes it.

scripts/score/hands_data.py user_labels() reads both;
scripts/score/train_hands.py --user trains on them.
"""

from __future__ import annotations

import json
import threading
import time

from app.score import hands, store

LOG = "hand_labels.jsonl"
REVIEWED = "hands_reviewed.json"
_LOCK = threading.Lock()


def _note(n: dict) -> dict:
    return {k: n.get(k) for k in ("id", "midi", "start", "end", "velocity")}


def changed_hands(before: list[dict], after: list[dict]) -> list[dict]:
    """Notes present before and after whose own hand changed (a note the user
    added takes its staff's hand: not a correction)."""
    old = {n["id"]: n for n in before}
    out = []
    for n in after:
        b = old.get(n["id"])
        if b is not None and (b.get("hand") or None) != (n.get("hand") or None):
            out.append(n)
    return out


def record(job_id: str, stem: str, before: list[dict], after: list[dict], shown: dict) -> int:
    """Append the hands the user changed from `before` to `after`. `shown`:
    note id -> the hand the score showed before (engraved staff). Returns how
    many; a reviewed song gets its snapshot rewritten with the new hands."""
    moved = changed_hands(before, after)
    if not moved:
        return 0
    now = round(time.time(), 3)
    model = hands.model_version()
    lines = [
        json.dumps(
            {
                **_note(n),
                "hand": n.get("hand") or None,
                "was": shown.get(n["id"]),
                "model": model,
                "t": now,
            }
        )
        for n in moved
    ]
    d = store.score_dir(job_id, stem)
    with _LOCK:
        d.mkdir(parents=True, exist_ok=True)
        with open(d / LOG, "a", encoding="utf-8") as f:
            f.write("\n".join(lines) + "\n")
    return len(lines)


def read_log(job_id: str, stem: str) -> list[dict]:
    path = store.score_dir(job_id, stem) / LOG
    if not path.is_file():
        return []
    out = []
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            out.append(json.loads(line))
        except ValueError:
            continue  # a line cut by a crash
    return out


def latest(log: list[dict]) -> dict[str, dict]:
    """Note id -> its last logged entry (a later «Auto» undoes a correction)."""
    out: dict[str, dict] = {}
    for e in log:
        out[e["id"]] = e
    return out


def mark_reviewed(job_id: str, stem: str, notes: list[dict], shown: dict) -> dict:
    snap = {
        "at": round(time.time(), 3),
        "model": hands.model_version(),
        "notes": [{**_note(n), "hand": shown.get(n["id"])} for n in notes],
    }
    with _LOCK:
        store.write_json(store.score_dir(job_id, stem) / REVIEWED, snap)
    return snap


def unmark_reviewed(job_id: str, stem: str) -> None:
    with _LOCK:
        (store.score_dir(job_id, stem) / REVIEWED).unlink(missing_ok=True)


def reviewed(job_id: str, stem: str) -> dict | None:
    return store.read_json(store.score_dir(job_id, stem) / REVIEWED)


def summary(job_id: str, stem: str) -> dict:
    """What this score adds to a retraining: notes the user put in a hand
    (still set), and whether the whole song is marked reviewed."""
    kept = [e for e in latest(read_log(job_id, stem)).values() if e.get("hand")]
    rev = reviewed(job_id, stem)
    return {
        "corrected": len(kept),
        "reviewed": bool(rev),
        "reviewed_notes": len(rev["notes"]) if rev else 0,
    }
