"""Which hand plays each note (app/score/hands.py): the model, its decoding,
the user's corrections as hints, and a held-out piece with known hands."""

from __future__ import annotations

import json
import random
from pathlib import Path

import numpy as np
import pytest

from app.score import calibration as cal
from app.score import hands

FIXTURE = Path(__file__).parent / "fixtures" / "hands_kuhlau_op55_3.json"


def _piece() -> list[dict]:
    doc = json.loads(FIXTURE.read_text(encoding="utf-8"))
    return doc["notes"]


def _plain(notes, fixed=None):
    fixed = fixed or {}
    return [
        {**{k: v for k, v in n.items() if k != "gt"}, "hand": fixed.get(n["id"])} for n in notes
    ]


def _acc(out, notes):
    return sum(out[n["id"]] == n["gt"] for n in notes) / len(notes)


def test_the_model_ships():
    assert hands.available(), f"missing {hands.MODEL_PATH}"


def test_kuhlau_sonatina_hands_as_played():
    # Kuhlau, Sonatina Op. 55 No. 3, first movement: held out of training,
    # played with each hand on its own keyboard. A split at middle C gets
    # 79 %.
    notes = _piece()
    split = {n["id"]: "R" if n["midi"] >= 60 else "L" for n in notes}
    assert _acc(split, notes) < 0.80
    assert _acc(hands.assign_hands(_plain(notes)), notes) >= 0.96


def test_left_hand_below_right_hand_in_every_chord():
    notes = _plain(_piece())
    out = hands.assign_hands(notes)
    idx = hands._order(notes)
    _, _, gid = hands.features(notes, idx)
    chords: dict[int, list[dict]] = {}
    for k, i in enumerate(idx):
        chords.setdefault(int(gid[k]), []).append(notes[i])
    for chord in chords.values():
        left = [n["midi"] for n in chord if out[n["id"]] == "L"]
        right = [n["midi"] for n in chord if out[n["id"]] == "R"]
        if left and right:
            assert max(left) <= min(right)


def test_same_notes_same_hands():
    notes = _plain(_piece())
    shuffled = notes[:]
    random.Random(3).shuffle(shuffled)
    hands._CACHE.clear()
    a = hands.assign_hands(notes)
    hands._CACHE.clear()
    assert hands.assign_hands(shuffled) == a


def test_a_hand_the_user_set_is_kept_even_against_the_model():
    notes = _plain(_piece())
    out = hands.assign_hands(notes)
    # The highest note of the piece to the left hand, the lowest to the right.
    top = max(notes, key=lambda n: n["midi"])
    low = min(notes, key=lambda n: n["midi"])
    assert out[top["id"]] == "R" and out[low["id"]] == "L"
    fixed = _plain(_piece(), {top["id"]: "L", low["id"]: "R"})
    again = hands.assign_hands(fixed)
    assert again[top["id"]] == "L" and again[low["id"]] == "R"


def test_windows_read_like_the_whole_sequence():
    # Long songs run in overlapping windows (one batch); the reading must not
    # depend on where the cuts fall.
    notes = _plain(_piece())
    idx = hands._order(notes)
    keys, X, _ = hands.features(notes, idx)
    w = hands._weights()
    windowed = hands._forward(w, keys, X)
    core = hands.CORE
    try:
        hands.CORE = len(notes)
        whole = hands._forward(w, keys, X)
    finally:
        hands.CORE = core
    assert np.mean((windowed > 0.5) == (whole > 0.5)) >= 0.995
    assert len(notes) > hands.CORE + 2 * hands.CONTEXT  # the fixture is cut


def test_calibration_piece_even_with_human_timing():
    rng = random.Random(7)
    for jitter in (0.0, 0.03):
        notes = [{**n, "start": n["start"] + rng.uniform(-jitter, jitter)} for n in cal.notes()]
        out = hands.assign_hands(notes, 60)
        assert all(out[n["id"]] == n["hand_truth"] for n in notes)


def test_without_weights_it_falls_back_to_the_split(monkeypatch, tmp_path):
    monkeypatch.setattr(hands, "MODEL_PATH", tmp_path / "none.npz")
    hands._weights.cache_clear()
    try:
        notes = [
            {"id": "a", "midi": 59, "start": 0, "end": 1},
            {"id": "b", "midi": 60, "start": 0, "end": 1},
            {"id": "c", "midi": 72, "start": 1, "end": 2, "hand": "L"},
        ]
        assert hands.assign_hands(notes, 60) == {"a": "L", "b": "R", "c": "L"}
    finally:
        hands._weights.cache_clear()


@pytest.mark.parametrize("n", [0, 1, 2])
def test_tiny_inputs(n):
    notes = [
        {"id": f"x{i}", "midi": 60 + 7 * i, "start": 0.5 * i, "end": 0.5 * i + 0.4}
        for i in range(n)
    ]
    out = hands.assign_hands(notes)
    assert set(out) == {m["id"] for m in notes} and set(out.values()) <= {"L", "R"}
