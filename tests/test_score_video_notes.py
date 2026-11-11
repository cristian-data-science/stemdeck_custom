"""Notes read from a falling-notes video (app/score/video_notes.py).

A small video is drawn here: three octaves of keyboard from C, keys lit in
two colours (green left hand, blue right hand) at known times, plus a fade to
grey (not a note) and a dark-blue glow on a black key (not a note either).
"""

from __future__ import annotations

import shutil
import subprocess

import numpy as np
import pytest

from app.score import video_notes as vn

W, H, FPS = 420, 240, 30
WHITE = 20  # px
KB_TOP, BLACK_BOTTOM, KB_BOTTOM = 160, 200, 236
WHITE_PC = (0, 2, 4, 5, 7, 9, 11)
BLACK_AFTER = {0: 1, 2: 3, 5: 6, 7: 8, 9: 10}  # white pc -> black pc to its right

GREEN, BLUE, PINK = (40, 160, 40), (80, 130, 250), (250, 170, 245)
# (relative key, start s, end s, colour): a left-hand C-E-G chord, a right-hand line.
PRESSES = [
    (0, 0.5, 1.2, GREEN), (4, 0.5, 1.2, GREEN), (7, 0.5, 1.2, GREEN),
    (24, 0.6, 0.9, BLUE), (26, 0.9, 1.2, BLUE), (28, 1.2, 1.5, BLUE), (25, 1.6, 1.9, BLUE),
]  # fmt: skip


def _key_rects():
    rects = {}
    for i in range(21):
        octave, k = divmod(i, 7)
        pc = WHITE_PC[k]
        rects[octave * 12 + pc] = ("w", i * WHITE, i * WHITE + WHITE - 1)
        if pc in BLACK_AFTER:
            cx = (i + 1) * WHITE
            rects[octave * 12 + BLACK_AFTER[pc]] = ("b", cx - 6, cx + 6)
    return rects


def _frame(t: float) -> np.ndarray:
    img = np.zeros((H, W, 3), dtype=np.uint8)
    img[:] = (20, 20, 35)
    lit = {k: c for k, a, b, c in PRESSES if a <= t < b}
    rects = _key_rects()
    for key, (kind, x0, x1) in rects.items():
        if kind == "w":
            img[KB_TOP:KB_BOTTOM, x0:x1] = lit.get(key, (235, 235, 235))
    for key, (kind, x0, x1) in rects.items():
        if kind == "b":
            img[KB_TOP:BLACK_BOTTOM, x0:x1] = lit.get(key, (15, 15, 15))
    if 2.2 <= t < 2.4:  # a fade to grey: not a note
        img[KB_TOP:KB_BOTTOM] = (img[KB_TOP:KB_BOTTOM] * 0.3).astype(np.uint8)
    if 2.6 <= t < 2.9:  # a glow on a black key: dark blue, not a note
        kind, x0, x1 = rects[13]
        img[KB_TOP:BLACK_BOTTOM, x0:x1] = (45, 65, 105)
    return img


@pytest.fixture(scope="module")
def video(tmp_path_factory):
    if not shutil.which("ffmpeg") or not shutil.which("ffprobe"):
        pytest.skip("ffmpeg not installed")
    out = tmp_path_factory.mktemp("v") / "video.mp4"
    frames = np.stack([_frame(i / FPS) for i in range(int(3.5 * FPS))])
    subprocess.run(
        ["ffmpeg", "-nostdin", "-loglevel", "error", "-y", "-f", "rawvideo", "-pix_fmt", "rgb24",
         "-s", f"{W}x{H}", "-r", str(FPS), "-i", "-", "-g", "15", "-pix_fmt", "yuv420p", str(out)],
        input=frames.tobytes(), check=True,
    )  # fmt: skip
    return out


def test_the_keyboard_is_found_and_its_keys_named(video):
    kb = vn.detect(video)
    assert kb is not None
    keys = {p for p, _, _ in kb.keys}
    assert {1, 3, 6, 8, 10, 13} <= keys and {0, 2, 4, 5, 7, 12} <= keys  # blacks and whites


def test_lit_keys_become_notes_with_their_octave_and_hands(video):
    kb = vn.detect(video)
    pressed = vn.read(video, kb)
    assert sorted({v.key for v in pressed}) == [0, 4, 7, 24, 25, 26, 28]  # no fade, no glow
    # The audio says the chord is C3-E3-G3 (and misses one note): octave from it.
    audio = [{"midi": m, "start": a, "velocity": 70} for m, a in ((48, 0.5), (52, 0.51), (55, 0.5))]
    audio += [{"midi": m, "start": a, "velocity": 90} for m, a in ((72, 0.6), (74, 0.9), (76, 1.2))]
    notes, info = vn.to_notes(pressed, audio)
    assert info["octave_shift"] == 48
    got = sorted((n["midi"], n["hand"]) for n in notes)
    assert got == [(48, "L"), (52, "L"), (55, "L"), (72, "R"), (73, "R"), (74, "R"), (76, "R")]
    chord = [n for n in notes if n["hand"] == "L"]
    assert all(abs(n["start"] - 0.5) < 0.05 and abs(n["end"] - 1.2) < 0.07 for n in chord)


def test_a_video_the_audio_does_not_confirm_is_not_used(video):
    kb = vn.detect(video)
    audio = [{"midi": 30, "start": 0.5}, {"midi": 31, "start": 1.0}]
    assert vn.to_notes(vn.read(video, kb), audio) is None


def test_hands_by_register_when_the_video_has_one_colour():
    notes = [{"midi": m, "start": t, "color": (250, 170, 245)} for m, t in (
        (57, 0.0), (60, 0.0), (65, 0.0), (77, 0.1), (79, 0.3), (81, 0.5), (57, 1.0), (60, 1.0),
        (65, 1.0), (72, 1.2), (59, 2.0), (62, 2.0), (67, 2.0), (79, 2.1),
    )]  # fmt: skip
    vn._hands(notes)
    assert {n["midi"] for n in notes if n["hand"] == "L"} == {57, 59, 60, 62, 65, 67}
    assert {n["midi"] for n in notes if n["hand"] == "R"} == {72, 77, 79, 81}
