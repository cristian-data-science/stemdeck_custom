"""Notes read from a falling-notes video (Synthesia and the like).

When a song's video shows a piano keyboard whose keys light up as they sound,
the keys are a better source than the audio: the exact key, octave and time.
Measured on "Y dime - Agrupación Marilyn | Intro con notas y acordes"
(2026-10-31): of the 75 melody notes the video shows, the audio transcription
had 24 at the right pitch (70 an octave off, inside the chords' register) and
66 notes too many; the video gives each key as played.

How:
1. detect(): frames sampled across the video; their median is the keyboard
   at rest. The black keys are the dark runs of one row (in groups of two and
   three); their spacing gives the white keys' width and their grouping the
   note names (C# D# | F# G# A#). A row of bright keys must lie under them.
2. read(): every frame of the keyboard band; a key is lit while its colour is
   far from its colour at rest. Lit colours in two clusters are the two hands
   (Synthesia paints them apart); with one colour, hands are told apart by
   register (chords low, melody high).
3. The octave is not in the picture: the shift that best matches the audio
   transcription (same key, same time) is taken; so is each note's attack time
   when the audio has it (the video has 30 frames a second) and its velocity.

Never fatal: no keyboard, or notes that do not match the audio, and the score
keeps the audio transcription.
"""

from __future__ import annotations

import logging
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

import numpy as np

logger = logging.getLogger(__name__)

SAMPLE_FPS = 1.0  # frames a second sampled to find the keyboard
MAX_WIDTH = 640  # frames are read scaled to at most this width
LIT_DISTANCE = 40.0  # RGB distance from the key at rest that counts as lit (a pale pink: ~80)
MIN_SATURATION = 35  # a lit key is coloured: max - min channel
MIN_VIVID = 140  # ...and bright: its strongest channel at least this
MIN_FRAMES = 2  # a lit key shorter than this is a flicker
MIN_BLACK_KEYS = 10  # at least two octaves' worth to call it a keyboard
MATCH_SEC = 0.09  # a video note and an audio note are the same within this
MIN_AGREEMENT = 0.45  # share of video notes the audio must confirm to trust them

# Black keys within an octave by their gap pattern: a group of 2 is C# D#, of 3 F# G# A#.
_GROUP2 = (1, 3)
_GROUP3 = (6, 8, 10)
_WHITE_PC = (0, 2, 4, 5, 7, 9, 11)


@dataclass
class Keyboard:
    width: int  # frame width the positions are in
    height: int
    keys: list[tuple[int, float, int]]  # (pitch class offset from C of octave 0, x, y)
    top: int  # band to read: from the black keys' top...
    bottom: int  # ...to the white keys' bottom


def _ffmpeg() -> str:
    try:
        from app.core.config import ffmpeg_executable

        return ffmpeg_executable()
    except Exception:  # noqa: BLE001
        return "ffmpeg"


def _probe(video: Path) -> tuple[int, int, float]:
    """(width, height, fps) as read here (scaled to MAX_WIDTH)."""
    import json

    out = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries",
         "stream=width,height,r_frame_rate", "-of", "json", str(video)],
        capture_output=True, text=True, check=True, creationflags=_flags(),
        stdin=subprocess.DEVNULL,
    )  # fmt: skip
    s = json.loads(out.stdout)["streams"][0]
    w, h = int(s["width"]), int(s["height"])
    num, den = (int(x) for x in s["r_frame_rate"].split("/"))
    scale = min(1.0, MAX_WIDTH / w)
    w2, h2 = int(round(w * scale / 2)) * 2, int(round(h * scale / 2)) * 2
    return w2, h2, num / max(1, den)


def _flags() -> int:
    return subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0


def _frames(
    video: Path, w: int, h: int, *, fps: float | None = None, crop=None, keyframes: bool = False
) -> np.ndarray:
    vf = [f"scale={w}:{h}"]
    if fps:
        vf.insert(0, f"fps={fps}")
    if crop:
        top, bottom = crop
        vf.append(f"crop={w}:{bottom - top}:0:{top}")
    out = subprocess.run(
        [_ffmpeg(), "-nostdin", "-hide_banner", "-loglevel", "error",
         *(["-skip_frame", "nokey"] if keyframes else []), "-i", str(video), "-vf", ",".join(vf),
         # Only the frames decoded (not repeated to a constant rate).
         *(["-fps_mode", "passthrough"] if keyframes else []),
         "-f", "rawvideo", "-pix_fmt", "rgb24", "-"],
        capture_output=True, check=True, creationflags=_flags(), stdin=subprocess.DEVNULL,
    )  # fmt: skip
    rows = (crop[1] - crop[0]) if crop else h
    return np.frombuffer(out.stdout, dtype=np.uint8).reshape(-1, rows, w, 3)


def _dark_runs(row: np.ndarray, dark: float) -> list[tuple[int, int]]:
    d = row < dark
    runs, start = [], None
    for x, v in enumerate(d):
        if v and start is None:
            start = x
        elif not v and start is not None:
            runs.append((start, x))
            start = None
    if start is not None:
        runs.append((start, len(d)))
    return runs


def _black_keys(gray: np.ndarray):
    """(row, centres) in the middle of the tallest band of rows that look
    like black keys: the same dark runs row after row (a line of key labels
    has as many dark runs, but a few pixels tall)."""
    h, w = gray.shape
    per_row: list[list[float] | None] = []
    for y in range(h):
        row = gray[y]
        runs = [r for r in _dark_runs(row, 80) if 2 <= r[1] - r[0] <= w / 12]
        ok = 0.3 < (row > 150).mean() < 0.8 and len(runs) >= MIN_BLACK_KEYS
        if ok:
            widths = np.array([b - a for a, b in runs])
            ok = widths.std() <= 0.35 * widths.mean()
        per_row.append([(a + b) / 2 for a, b in runs] if ok else None)
    best, y = None, 0
    while y < h:
        if per_row[y] is None:
            y += 1
            continue
        z = y
        while (
            z + 1 < h
            and per_row[z + 1] is not None
            and len(per_row[z + 1]) == len(per_row[y])
            and np.max(np.abs(np.array(per_row[z + 1]) - np.array(per_row[y]))) <= 2.5
        ):
            z += 1
        tall = z - y + 1
        if best is None or tall > best[0]:
            best = (tall, (y + z) // 2)
        y = z + 1
    if best is None or best[0] < 6:
        return None, None
    return best[1], per_row[best[1]]


def _name_black(centres: list[float]) -> tuple[float, list[int]] | None:
    """White key width and each black key's pitch class, from the gaps."""
    gaps = np.diff(centres)
    unit = float(np.median(gaps[gaps < np.median(gaps) * 1.3]))
    groups, cur = [], [0]
    for i, g in enumerate(gaps):
        # Within a group the black keys are about a white key apart; between
        # groups (D# to F#, A# to C#) about two, drawn a little closer.
        if g < unit * 1.25:
            cur.append(i + 1)
        else:
            groups.append(cur)
            cur = [i + 1]
    groups.append(cur)
    pcs: list[int | None] = [None] * len(centres)
    last = len(groups) - 1
    for k, grp in enumerate(groups):
        n = len(grp)
        if k not in (0, last) or last == 0:
            if n == 2:
                names = _GROUP2
            elif n == 3:
                names = _GROUP3
            else:
                return None  # not a piano's pattern
        else:
            # A group at the edge may be cut: it is the other kind from its neighbour.
            neighbour = len(groups[1] if k == 0 else groups[-2])
            names = _GROUP3 if neighbour == 2 else _GROUP2
            if n > len(names):
                return None
            names = names[-n:] if k == 0 else names[:n]
        for j, i in enumerate(grp):
            pcs[i] = names[j]
    return unit, pcs  # type: ignore[return-value]


def detect(video: Path) -> Keyboard | None:
    """The keyboard in a falling-notes video, or None."""
    try:
        w, h, _ = _probe(video)
        # Key frames only first (fast on a long music video that is not one);
        # a short video may have too few, then one frame a second.
        frames = _frames(video, w, h, keyframes=True)
        if len(frames) < 8:
            frames = _frames(video, w, h, fps=SAMPLE_FPS)
    except (OSError, subprocess.SubprocessError, ValueError, KeyError) as e:
        logger.info("video notes: cannot read %s: %s", video, e)
        return None
    if len(frames) < 3:
        return None
    frames = frames[:: max(1, len(frames) // 60)]  # 60 are plenty for the median
    rest = np.median(frames, axis=0)  # the keyboard as it is most of the time: unlit
    gray = rest.mean(axis=2)
    yb, centres = _black_keys(gray)
    if yb is None:
        return None
    named = _name_black(centres)
    if named is None:
        return None
    unit, pcs = named

    # The black keys' band, and the white keys under it.
    def keys_in(y: int) -> int:  # dark runs as wide as a black key (not 1-px key edges)
        return sum(1 for a, b in _dark_runs(gray[y], 80) if b - a >= max(2, unit * 0.25))

    top = yb
    while top > 0 and keys_in(top - 1) >= MIN_BLACK_KEYS:
        top -= 1
    bot = yb
    while bot + 1 < h and keys_in(bot + 1) >= MIN_BLACK_KEYS // 2:
        bot += 1
    white_rows = [
        y
        for y in range(bot + 1, min(h, bot + int(unit * 4)))
        if (gray[y] > 130).mean() > 0.8  # white or light grey keys
    ]
    if not white_rows:
        return None
    # The cleanest rows (no key labels, no edges) are the brightest; the
    # middle one of those (the lowest touched the keys' bottom edge).
    level = {y: float((gray[y] > 130).mean()) for y in white_rows}
    clean = [y for y in white_rows if level[y] >= max(level.values()) - 0.02]
    yw = clean[len(clean) // 2]
    # Octave numbering: relative (the first C at or left of the first black is octave 0).
    keys: list[tuple[int, float, int]] = []
    octave = 0
    last_pc = None
    for x, pc in zip(centres, pcs, strict=True):
        if last_pc is not None and pc <= last_pc:
            octave += 1
        keys.append((octave * 12 + pc, x, yb))
        last_pc = pc
    # White keys: fit the black keys to a keyboard of white keys W wide
    # starting at x0 (a black key sits near the boundary after its white:
    # C# at 1, D# at 2, F# at 4, G# at 5, A# at 6 whites from C).
    slot = {1: 1, 3: 2, 6: 4, 8: 5, 10: 6}
    pos = np.array([(p // 12) * 7 + slot[p % 12] for p, _, _ in keys], dtype=float)
    xs = np.array([x for _, x, _ in keys])
    wk, x0 = np.polyfit(pos, xs, 1)
    whites = []
    for octave_i in range(int(min(pos) // 7) - 1, int(max(pos) // 7) + 2):
        for i, pc in enumerate(_WHITE_PC):
            x = x0 + (octave_i * 7 + i + 0.5) * wk
            if wk * 0.3 <= x < w - wk * 0.3:
                whites.append((octave_i * 12 + pc, float(x), yw))
    keys += whites
    return Keyboard(
        width=w, height=h, keys=sorted(keys), top=max(0, top - 2), bottom=min(h, yw + 3)
    )


@dataclass
class VideoNote:
    key: int  # relative pitch (octave unknown)
    start: float
    end: float
    color: tuple[int, int, int]


def read(video: Path, kb: Keyboard) -> list[VideoNote]:
    """Every key press in the video."""
    _, _, fps = _probe(video)
    band = _frames(video, kb.width, kb.height, crop=(kb.top, kb.bottom)).astype(np.int16)
    rest = np.median(band[:: max(1, len(band) // 60)], axis=0)
    notes: list[VideoNote] = []
    for p, x, y in kb.keys:
        xi, yi = int(round(x)), int(y) - kb.top
        if not (1 <= xi < kb.width - 1 and 1 <= yi < band.shape[1] - 1):
            continue
        patch = band[:, yi - 1 : yi + 2, xi - 1 : xi + 2].reshape(len(band), -1, 3).mean(axis=1)
        ref = rest[yi - 1 : yi + 2, xi - 1 : xi + 2].reshape(-1, 3).mean(axis=0)
        # Lit: far from the key at rest, and coloured (a fade to black or a
        # dimmed keyboard is far from rest too, but grey).
        sat = patch.max(axis=1) - patch.min(axis=1)
        vivid = patch.max(axis=1) >= MIN_VIVID  # a glow on a black key is dark blue, not lit
        lit = (np.linalg.norm(patch - ref, axis=1) > LIT_DISTANCE) & (sat >= MIN_SATURATION) & vivid
        f = 0
        while f < len(lit):
            if not lit[f]:
                f += 1
                continue
            g = f
            while g < len(lit) and lit[g]:
                g += 1
            if g - f >= MIN_FRAMES:
                col = tuple(int(c) for c in np.median(patch[f:g], axis=0))
                notes.append(VideoNote(p, f / fps, g / fps, col))
            f = g
    notes.sort(key=lambda n: (n.start, n.key))
    return notes


def _hands(notes: list[dict]) -> None:
    """R/L for each note (in place). Two lit colours: the hands as painted
    (the higher-pitched colour is the right hand). One colour: by register,
    in a window of a few seconds: the largest pitch gap splits chords from
    melody."""
    if not notes:
        return
    cols = np.array([n["color"] for n in notes], dtype=float)
    from scipy.cluster.vq import kmeans2

    two = False
    if len(notes) >= 8 and np.ptp(cols, axis=0).max() >= 40:  # more than one colour
        centres, label = kmeans2(cols, 2, seed=1, minit="++")
        if (
            np.linalg.norm(centres[0] - centres[1]) > 60
            and min(np.bincount(label, minlength=2)) >= 3
        ):
            two = True
            mean0 = np.mean([n["midi"] for n, lab in zip(notes, label, strict=True) if lab == 0])
            mean1 = np.mean([n["midi"] for n, lab in zip(notes, label, strict=True) if lab == 1])
            right = 0 if mean0 > mean1 else 1
            for n, lab in zip(notes, label, strict=True):
                n["hand"] = "R" if lab == right else "L"
    if two:
        return
    starts = np.array([n["start"] for n in notes])
    midis = np.array([n["midi"] for n in notes])
    for n in notes:
        near = np.sort(midis[np.abs(starts - n["start"]) <= 4.0])
        if len(near) < 4 or near[-1] - near[0] < 7:
            n["hand"] = "R" if n["midi"] >= 60 else "L"
            continue
        gaps = np.diff(near)
        i = int(np.argmax(gaps))
        split = (near[i] + near[i + 1]) / 2 if gaps[i] >= 3 else 59.5
        n["hand"] = "R" if n["midi"] > split else "L"


def to_notes(vnotes: list[VideoNote], audio_notes: list[dict]) -> tuple[list[dict], dict] | None:
    """The video's notes in MIDI, octave and attacks from the audio
    transcription; None when they do not agree with the audio."""
    if not vnotes or not audio_notes:
        return None
    a_start = np.array([n["start"] for n in audio_notes])
    a_midi = np.array([n["midi"] for n in audio_notes])

    def matches(shift: int) -> int:
        hit = 0
        for v in vnotes:
            near = np.abs(a_start - v.start) <= MATCH_SEC
            hit += bool(np.any(a_midi[near] == v.key + shift))
        return hit

    # Octave: relative key 0 is the C of the first octave on screen; try them all.
    shift = max(range(0, 97, 12), key=matches)
    agree = matches(shift) / len(vnotes)
    if agree < MIN_AGREEMENT:
        logger.info("video notes: only %.0f %% confirmed by the audio; kept the audio", 100 * agree)
        return None
    out = []
    for v in vnotes:
        midi = v.key + shift
        near = np.where((np.abs(a_start - v.start) <= MATCH_SEC) & (a_midi == midi))[0]
        start, vel = v.start, 80
        if len(near):
            j = near[np.argmin(np.abs(a_start[near] - v.start))]
            start, vel = float(a_start[j]), int(audio_notes[j].get("velocity", 80))
        out.append(
            {
                "midi": int(midi),
                "start": round(start, 4),
                "end": round(max(v.end, start + 0.05), 4),
                "velocity": vel,
                "color": v.color,
            }
        )
    _hands(out)
    for n in out:
        n.pop("color")
    return out, {"agreement": round(agree, 3), "octave_shift": shift, "notes": len(out)}


def notes_from_video(video: Path, audio_notes: list[dict]) -> tuple[list[dict], dict] | None:
    """The notes of a falling-notes video, checked against the audio; None if
    it is not one (or they disagree)."""
    kb = detect(video)
    if kb is None:
        return None
    try:
        vnotes = read(video, kb)
    except (OSError, subprocess.SubprocessError, ValueError) as e:
        logger.warning("video notes: reading %s failed: %s", video, e)
        return None
    got = to_notes(vnotes, audio_notes)
    if got is None:
        return None
    notes, info = got
    info["keys"] = len(kb.keys)
    return notes, info
