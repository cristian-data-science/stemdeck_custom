"""SWAM Saxophones (Audio Modeling) for «🎷 Saxo»: where it is, and its
renders, as Pianoteq's are made for the score.

The plugin is hosted by DawDreamer in an environment of its own
(.run/tools/swam-venv, or STEMDECK_SWAM_PYTHON) and run as a separate
process (app/score/swam_render.py): a plugin that crashes takes that
process down, never the server, and the app's environment gets no new
packages. The plugin files are looked for where Audio Modeling's Software
Center installs them (VST2 .dll and VST3), or in STEMDECK_SWAM_DIR.

A render is named by a hash of what SWAM is made to play (the MIDI events
swam_render.events() makes of the line, the saxophone, the length, this
module's version), not of what the page sent: anything that does not change
the performance (a curve value that rounds the same, a field the renderer
does not read, a page script that sends the same line differently) finds
the render already made. The same line asked again is the same file:
score/audio/swam-<key>.flac (cleaned with "cache").
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import subprocess
import sys
import tempfile
import threading
from pathlib import Path

logger = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parents[2]
VERSION = 3  # bump when swam_render.py changes how it plays a line
KEY_RE = re.compile(r"[0-9a-f]{20}")
NAMES = {"alto": "Alto", "tenor": "Tenor", "soprano": "Soprano", "baritone": "Baritone"}
# SWAM's tenor and baritone sound an octave below the note sent (measured:
# swam_render.py's docstring): sent 12 higher to sound where the line is.
OCTAVE = {"tenor": 12, "baritone": 12}
KEEP = 12  # renders kept per song (the newest; ~18 MB each for 4 min)


def python_exe() -> Path | None:
    env = os.environ.get("STEMDECK_SWAM_PYTHON")
    p = Path(env) if env else ROOT / ".run" / "tools" / "swam-venv" / "Scripts" / "python.exe"
    if not env and sys.platform != "win32":
        p = ROOT / ".run" / "tools" / "swam-venv" / "bin" / "python"
    return p if p.is_file() else None


def _dirs() -> list[Path]:
    env = os.environ.get("STEMDECK_SWAM_DIR")
    if env:
        return [Path(env)]
    common = Path(os.environ.get("COMMONPROGRAMFILES", r"C:\Program Files\Common Files"))
    pf = Path(os.environ.get("PROGRAMFILES", r"C:\Program Files"))
    return [common / "VST2", pf / "VSTPlugins", pf / "Steinberg" / "VSTPlugins", common / "VST3"]


def plugins() -> dict[str, Path]:
    """sax -> its SWAM plugin (VST2 first: DawDreamer's most reliable on Windows)."""
    if os.environ.get("STEMDECK_SWAM_OFF") == "1":
        return {}
    found: dict[str, Path] = {}
    for d in _dirs():
        if not d.is_dir():
            continue
        for sax, name in NAMES.items():
            if sax in found:
                continue
            for pattern in (f"SWAM {name} Sax*.dll", f"SWAM {name} Sax*.vst3"):
                hits = sorted(d.rglob(pattern))
                if hits:
                    found[sax] = hits[-1]
                    break
    return found


def available() -> dict:
    exe = python_exe()
    found = plugins() if exe else {}
    return {"available": bool(exe and found), "saxes": sorted(found), "python": bool(exe)}


# SWAM humanises on its own: a random change of dynamics from note to note
# ("Random Dynamic", 9 by default; 3 is its least) and a pitch that moves
# with the dynamics ("Dynamic Pitch", 30). The line already has the player's
# own dynamics and pitch, and on top of them these made the same note sound
# different each time: off (measured: docs/partitura.md).
STEADY = {"Random Dynamic": 0.0, "Dynamic Pitch": 0.0}


# «Sala»: SWAM's own room, a model of a room (its size, what its walls are
# made of, how far the saxophone is). "Reverb Mix" and "Reverb Time" do
# nothing in SWAM 3 unless "Legacy Reverb" is on (measured: the render is
# the same sample for sample). "medium" is the plugin as it comes (MEDIUM 3,
# medium absorption, 3 m): nothing set. Measured, the tail 0.35-0.65 s after
# a note against the note: dry -41 dB, medium -28 dB, large -20 dB.
ROOMS = {
    "dry": {
        "Room Sizes": 0.0,
        "Absorption Materials": 0.0,
        "Source Distance": 0.0,
    },  # MEDIUM 1, HIGH, 1.2 m
    "medium": {},
    "large": {"Room Sizes": 0.8, "Absorption Materials": 1.0},  # LARGE 2, LOW
}


# «Tono»: how the saxophone is blown. "clean" is as it was. "soft": blown
# at 70 % (SWAM's tone gets darker and airier the softer it is blown: 8 dB
# less above 5 kHz, measured) with its breath noise at the most. "growl":
# SWAM's growl at 35 % (the loudness fluttering at 20-90 Hz: +3 dB, measured).
TONES = {
    "clean": {"blow": 1.0, "params": {}},
    "soft": {"blow": 0.7, "params": {"Breath Noise": 1.0}},
    "growl": {"blow": 1.0, "params": {"Growl": 0.35}},
}


def _tone(payload: dict) -> dict:
    return TONES.get(payload.get("tone") or "clean", TONES["clean"])


def plugin_params(payload: dict) -> dict[str, float]:
    """SWAM's settings for this render: its parameter's name -> 0..1."""
    params = dict(STEADY)
    params.update(ROOMS.get(payload.get("room") or "medium", {}))
    params.update(_tone(payload)["params"])
    return params


def _performance(payload: dict) -> dict:
    """What decides the sound: the events SWAM gets, which saxophone, for how
    long, and SWAM's own vibrato or not (swam_render.render)."""
    from app.score import swam_render

    sax = payload.get("sax", "alto")
    data = {
        "cents": payload.get("cents", 0),
        "octave": OCTAVE.get(sax, 0),
        "notes": payload["notes"],
        "blow": _tone(payload)["blow"],
    }
    return {
        "v": VERSION,
        "sax": sax,
        "duration": payload["duration"],
        "expressive": any(n.get("curve") for n in payload["notes"]),
        "params": plugin_params(payload),
        "events": swam_render.events(data),
    }


def render_key(payload: dict) -> str:
    blob = json.dumps(_performance(payload), sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(blob.encode()).hexdigest()[:20]


def audio_path(folder: Path, key: str) -> Path:
    if not KEY_RE.fullmatch(key):
        raise ValueError("bad key")
    return folder / f"swam-{key}.flac"


# ── renders, one at a time, the newest asked for first ──────────────────

_LOCK = threading.Lock()
_STATE: dict[str, dict] = {}  # key -> {"state": queued|rendering|done|error, "error"?}
_QUEUE: list[tuple[str, Path, dict]] = []  # (key, dest, payload)
_RUNNING = False
_PROC: dict[str, subprocess.Popen] = {}


def status(key: str, folder: Path) -> dict:
    if audio_path(folder, key).is_file():
        return {"state": "done"}
    with _LOCK:
        return dict(_STATE.get(key) or {"state": "none"})


def request(key: str, folder: Path, payload: dict, job: str) -> dict:
    """Queue this render (unless it is there already). A newer one for the
    same song goes first; one still waiting for it is dropped (the line has
    changed again since)."""
    global _RUNNING
    dest = audio_path(folder, key)
    if dest.is_file():
        dest.touch(exist_ok=True)  # used again: the newest, the last one pruned
        return {"state": "done"}
    with _LOCK:
        cur = _STATE.get(key)
        if cur and cur["state"] in ("queued", "rendering"):
            return dict(cur)
        for k, d, p in list(_QUEUE):
            if p.get("_job") == job:
                _QUEUE.remove((k, d, p))
                _STATE.pop(k, None)
        _QUEUE.insert(0, (key, dest, {**payload, "_job": job}))
        _STATE[key] = {"state": "queued"}
        if not _RUNNING:
            _RUNNING = True
            threading.Thread(target=_loop, daemon=True, name="swam-render").start()
    return {"state": "queued"}


def _loop() -> None:
    global _RUNNING
    while True:
        with _LOCK:
            if not _QUEUE:
                _RUNNING = False
                return
            key, dest, payload = _QUEUE.pop(0)
            _STATE[key] = {"state": "rendering"}
        try:
            _render(key, dest, payload)
            with _LOCK:
                _STATE[key] = {"state": "done"}
            _prune(dest.parent, dest)
        except Exception as exc:  # noqa: BLE001 -- said to the page
            logger.warning("swam render %s failed: %s", key, exc)
            with _LOCK:
                _STATE[key] = {"state": "error", "error": str(exc)[:300]}


def _render(key: str, dest: Path, payload: dict) -> None:
    from app.score.pianoteq import _low_priority_flags

    exe = python_exe()
    found = plugins()
    sax = payload.get("sax", "alto")
    if not exe or sax not in found:
        raise RuntimeError("SWAM Saxophones not found")
    data = {
        "plugin": str(found[sax]),
        "duration": payload["duration"],
        "cents": payload.get("cents", 0),
        "octave": OCTAVE.get(sax, 0),
        "notes": payload["notes"],
        "blow": _tone(payload)["blow"],
        "params": plugin_params(payload),
    }
    dest.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as tmp:
        src = Path(tmp) / "line.json"
        src.write_text(json.dumps(data), encoding="utf-8")
        script = Path(__file__).with_name("swam_render.py")
        proc = subprocess.Popen(
            [str(exe), "-I", str(script), str(src), str(dest)],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            stdin=subprocess.DEVNULL,
            creationflags=_low_priority_flags() | getattr(subprocess, "CREATE_NO_WINDOW", 0),
            text=True,
        )
        with _LOCK:
            _PROC[key] = proc
        try:
            out, err = proc.communicate(timeout=max(120, payload["duration"] * 2))
        except subprocess.TimeoutExpired:
            proc.kill()
            raise RuntimeError("SWAM took too long") from None
        finally:
            with _LOCK:
                _PROC.pop(key, None)
    if proc.returncode != 0 or not dest.is_file():
        raise RuntimeError((err or out or f"exit {proc.returncode}").strip().splitlines()[-1][:300])
    logger.info("swam: %s rendered (%s, %d notes)", dest.name, sax, len(payload["notes"]))


def _prune(folder: Path, keep: Path) -> None:
    renders = sorted(folder.glob("swam-*.flac"), key=lambda p: p.stat().st_mtime, reverse=True)
    for p in renders[KEEP:]:
        if p != keep:
            try:
                p.unlink()
            except OSError:
                pass
