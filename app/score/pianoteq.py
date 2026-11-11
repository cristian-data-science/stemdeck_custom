"""Play the score with Pianoteq, when it is installed on this machine.

Pianoteq's own command line renders a MIDI file to audio without opening its
window (`--headless --midi x.mid --flac y.flac`). The MIDI is the score as the
page plays it -- each note from its heard start to its drawn end, on the
song's real tempo map -- so the rendered file starts at the song's second 0
and the cursor follows it like the stem.

Renders are cached by the MIDI bytes and the preset: the same notes in the
same piano are rendered once. One render at a time (Pianoteq is a whole
synthesizer; two at once only make both slower).

Nothing here is required: without Pianoteq the page simply does not offer it.
STEMDECK_PIANOTEQ points at a specific executable.
"""

from __future__ import annotations

import hashlib
import os
import re
import shutil
import subprocess
import sys
import threading
import time
from pathlib import Path

DEFAULT_PRESET = "NY Steinway D Classical"
RENDER_TIMEOUT = 30 * 60  # a 9-minute song takes about a minute
KEEP = 8  # renders kept per score (older ones are deleted): pianos x hands x speeds
PRESETS_TTL = 60.0  # s: a preset saved in Pianoteq's own window shows up within a minute

_KEY_RE = re.compile(r"^[0-9a-f]{20}$")
_render_lock = threading.Lock()


def _candidates() -> list[Path]:
    env = os.environ.get("STEMDECK_PIANOTEQ")
    if env:
        return [Path(env)]
    found: list[Path] = []
    if sys.platform == "win32":
        roots = [os.environ.get("PROGRAMFILES", r"C:\Program Files"), r"C:\Program Files"]
        for root in dict.fromkeys(roots):
            base = Path(root) / "Modartt"
            if base.is_dir():
                found += sorted(base.glob("Pianoteq*/Pianoteq*.exe"), reverse=True)
    elif sys.platform == "darwin":
        found += sorted(
            Path("/Applications").glob("Pianoteq*/Pianoteq*.app/Contents/MacOS/Pianoteq*"),
            reverse=True,
        )
    else:
        for name in ("pianoteq", "Pianoteq 9", "Pianoteq 8"):
            hit = shutil.which(name)
            if hit:
                found.append(Path(hit))
    # Skip the uninstaller and other helpers that match the glob.
    return [p for p in found if "unins" not in p.name.lower()]


def executable() -> Path | None:
    for p in _candidates():
        if p.is_file():
            return p
    return None


def _run(args: list[str], timeout: float) -> subprocess.CompletedProcess:
    flags = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
    return subprocess.run(
        args,
        capture_output=True,
        # Pianoteq prints UTF-8 whatever the console's code page: read with
        # the locale's (cp1252), "Bösendorfer" came out as "BÃ¶sendorfer".
        encoding="utf-8",
        errors="replace",
        timeout=timeout,
        creationflags=flags,
        check=False,
    )


class _TimedCache:
    """The preset list, asked of Pianoteq again after PRESETS_TTL seconds: a
    preset the user saves in Pianoteq's window was missing until the server
    restarted (lru_cache kept the first list for the life of the process).
    An empty answer is not kept (Pianoteq busy or slow to start)."""

    def __init__(self, fn):
        self.fn = fn
        self.cache: dict[str, tuple[float, tuple[str, ...]]] = {}

    def __call__(self, exe: str) -> tuple[str, ...]:
        hit = self.cache.get(exe)
        if hit and time.monotonic() - hit[0] < PRESETS_TTL:
            return hit[1]
        names = self.fn(exe)
        if names:
            self.cache[exe] = (time.monotonic(), names)
        return names

    def cache_clear(self) -> None:
        self.cache.clear()


@_TimedCache
def _presets(exe: str) -> tuple[str, ...]:
    out = _run([exe, "--headless", "--list-presets"], timeout=120)
    names = [line.strip() for line in out.stdout.splitlines()]
    return tuple(n for n in names if n)


def _user_preset_dirs() -> list[Path]:
    dirs = []
    if sys.platform == "win32":
        for env in ("APPDATA", "USERPROFILE"):
            base = os.environ.get(env)
            if base:
                dirs += [
                    Path(base) / "Modartt" / "Pianoteq" / "Presets",
                    Path(base) / "Documents" / "Modartt" / "Pianoteq" / "Presets",
                ]
    elif sys.platform == "darwin":
        dirs.append(
            Path.home() / "Library" / "Application Support" / "Modartt" / "Pianoteq" / "Presets"
        )
    else:
        dirs.append(Path.home() / ".local" / "share" / "Modartt" / "Pianoteq" / "Presets")
    return [d for d in dirs if d.is_dir()]


def preset_stamp(preset: str) -> str:
    """A user preset's file date: one saved again under the same name in
    Pianoteq's window is another sound, so another render (the factory
    presets have no file here and stamp "")."""
    for d in _user_preset_dirs():
        try:
            for f in d.rglob("*.fxp"):
                if f.stem == preset:
                    return str(int(f.stat().st_mtime))
        except OSError:
            continue
    return ""


def info() -> dict:
    """What the page needs: is it there, and which pianos it offers."""
    exe = executable()
    if exe is None:
        return {"available": False, "presets": [], "default": None}
    try:
        presets = list(_presets(str(exe)))
    except (OSError, subprocess.SubprocessError):
        presets = []
    default = DEFAULT_PRESET if DEFAULT_PRESET in presets else (presets[0] if presets else None)
    return {
        "available": bool(presets),
        "name": exe.stem,
        "presets": presets,
        "default": default,
    }


def render_key(midi: bytes, preset: str, stamp: str | None = None) -> str:
    """The render's name: the MIDI (only the notes as heard: see
    midi.performance_midi), the piano, and a user preset's file date."""
    stamp = preset_stamp(preset) if stamp is None else stamp
    tail = f"\0{stamp}".encode() if stamp else b""
    return hashlib.sha1(midi + b"\0" + preset.encode("utf-8") + tail).hexdigest()[:20]


def legacy_key(midi: bytes, preset: str) -> str:
    """The name renders had before (the score's MIDI with its tempo map)."""
    return hashlib.sha1(midi + b"\0" + preset.encode("utf-8")).hexdigest()[:20]


def valid_key(key: str) -> bool:
    return bool(_KEY_RE.match(key))


def audio_path(folder: Path, key: str) -> Path:
    # FLAC, not MP3: the page switches between Pianoteq, the stem and the mix
    # at the same moment of the song, and a VBR MP3 lands a seek up to 170 ms
    # off (measured in Chrome) while reporting the time asked for; FLAC lands
    # on the sample.
    return folder / f"{key}.flac"


def render(midi: bytes, preset: str, folder: Path) -> Path:
    """Render to folder/<key>.flac (atomically) and return the path."""
    return render_as(midi, preset, folder, render_key(midi, preset))


def render_as(midi: bytes, preset: str, folder: Path, key: str) -> Path:
    exe = executable()
    if exe is None:
        raise RuntimeError("Pianoteq no está instalado")
    out = audio_path(folder, key)
    if out.is_file():
        return out
    folder.mkdir(parents=True, exist_ok=True)
    mid = folder / f"{key}.mid"
    tmp = folder / f"{key}.part.flac"
    mid.write_bytes(midi)
    try:
        with _render_lock:
            if out.is_file():  # rendered meanwhile by another request
                return out
            tmp.unlink(missing_ok=True)
            res = _run(
                [
                    str(exe),
                    "--headless",
                    "--quiet",
                    "--preset",
                    preset,
                    "--midi",
                    str(mid),
                    "--flac",
                    str(tmp),
                ],
                timeout=RENDER_TIMEOUT,
            )
        if not tmp.is_file() or tmp.stat().st_size == 0:
            detail = (res.stderr or res.stdout or "").strip().splitlines()[-1:] or ["sin salida"]
            raise RuntimeError(f"Pianoteq no generó audio ({detail[0][:200]})")
        tmp.replace(out)
    finally:
        mid.unlink(missing_ok=True)
        tmp.unlink(missing_ok=True)
    _prune(folder, keep=out)
    return out


def adopt(folder: Path, old_key: str, new_key: str) -> bool:
    """A render made under its old name, renamed to the new one (the same
    audio: no new render for a change of naming)."""
    old = audio_path(folder, old_key)
    new = audio_path(folder, new_key)
    if new.is_file():
        return True
    if not old.is_file():
        return False
    try:
        old.replace(new)
    except OSError:
        return False
    return True


def drop_legacy(folder: Path) -> None:
    """MP3 renders from before FLAC: never served any more (130 MB of them
    were left behind, _prune only looked at *.flac)."""
    if folder.is_dir():
        for old in folder.glob("*.mp3"):
            if valid_key(old.stem):
                old.unlink(missing_ok=True)


def _prune(folder: Path, keep: Path) -> None:
    drop_legacy(folder)
    renders = sorted(
        (p for p in folder.glob("*.flac") if valid_key(p.stem)),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    for old in renders[KEEP:]:
        if old != keep:
            old.unlink(missing_ok=True)
