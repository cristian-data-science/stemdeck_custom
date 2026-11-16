"""Which hand plays each note: a small bidirectional GRU, run in numpy.

The rules used before (the left hand's reach from its bass, the right hand's
melodic line) were barely better than a fixed split at middle C: 88.7 %
against 87.0 % on the songs whose hands are known (falling-notes videos, the
Chopin nocturne's printed staves; scripts/score/hands_data.py), and 83.0 %
against 79.5 % on hannds. Pitch and time alone leave real ambiguity -- an
inner D#4 between a G#3 bass and an F4 melody can be either hand -- so the
published answer is a model that reads the whole passage both ways:

  Hadjakos, Waloschek & Leemhuis, "Detecting Hands in Piano MIDI Data"
  (MuC 2019): a bidirectional GRU, 94.5 % on 122 pieces recorded with each
  hand on its own keyboard (the hannds dataset, MIT licence,
  github.com/cemfi/hannds), against 92.2 % for a bidirectional Kalman filter.

This one is trained on hannds (scripts/score/train_hands.py) with
transcription-like noise (dropped notes, octave ghosts, timing jitter,
transposition, tempo) and per note it reads: pitch, the gaps to the previous
and next onset, its length, velocity, and where it sits in its chord.
Additions for the editor:

* Hints: a hand the user set is an input, not only an override (the model
  was trained with some notes' hands revealed, among them its own mistakes).
* Propagation: a correction pulls the same key nearby along (propagate()).
* Chord consistency: within one onset the left hand always takes the lower
  notes (the best split of each chord by the model's probabilities), and a
  hand the user set is always kept.

Measured (scripts/score/hands_benchmark.py): 96.0 % on the known songs
(TURiSTA 92.6, Y dime 99.4, Nature of Daylight 93.1, BAILE INoLVIDABLE 97.6,
nocturne 96.9), and 97.0 % on the 12 hannds pieces held out of training (the
split: 78.1 %). Deterministic: same notes, same hands.
Without the weights file it falls back to the split point.
"""

from __future__ import annotations

import hashlib
import json
from functools import lru_cache
from pathlib import Path

import numpy as np

MODEL_PATH = Path(__file__).parent / "models" / "hands_gru.npz"
GROUP_SEC = 0.035  # onsets this close are one chord
N_FEAT = 10
# The sequence is cut into windows run as one batch: a Python loop over 3000
# notes one by one took 0.4 s; context on both sides keeps every note's
# reading the same as on the whole sequence (benchmarked).
CORE = 256
CONTEXT = 96
FORCED = 50.0  # log-probability cost of contradicting a hand the user set
# Log-odds for the hand on the split point's side. 0.5 only decides what the
# model leaves even (known songs 95.94 -> 95.97 %, held-out hannds 97.11 ->
# 97.03; 0.25 was +0.05 on both but left C4-D4-E4-F4 alone to the left hand).
SPLIT_PRIOR = 0.5
PROPAGATE = 10.0  # log-odds a correction adds to the same key next to it...
PROPAGATE_SEC = 4.0  # ...fading to nothing this far away (benchmarked: 3-4 s)
# One hand cannot hold keys further apart than a ninth: a note the model
# leaves undecided (a G3 topping a left-hand arpeggio while the right hand
# holds C5+C6) goes to the hand that can reach it. A note's "held" time is
# capped, as the pedal makes notes ring after the key is up. Measured: known
# songs 95.5 -> 95.9 %, held-out hannds 96.9 -> 97.1 % (on another training,
# reach 12-14 all gave the same; 16 less).
REACH = 14
REACH_COST = 4.0
HELD_MAX_SEC = 1.0


@lru_cache(maxsize=1)
def _weights() -> dict[str, np.ndarray] | None:
    if not MODEL_PATH.exists():
        return None
    with np.load(MODEL_PATH) as z:
        return {k: z[k].astype(np.float32) for k in z.files}


def available() -> bool:
    return _weights() is not None


@lru_cache(maxsize=1)
def model_version() -> str | None:
    """The weights file's sha1 (12 hex), logged with each user correction."""
    if not MODEL_PATH.exists():
        return None
    return hashlib.sha1(MODEL_PATH.read_bytes()).hexdigest()[:12]


def _order(notes: list[dict]) -> list[int]:
    return sorted(range(len(notes)), key=lambda i: (notes[i]["start"], notes[i]["midi"]))


def features(notes: list[dict], idx: list[int]) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Notes in `idx` order -> (key index 0..87, features [N, N_FEAT], chord id).

    Must match the training script's features exactly."""
    n = len(idx)
    midi = np.array([notes[i]["midi"] for i in idx], dtype=np.float32)
    st = np.array([notes[i]["start"] for i in idx], dtype=np.float64)
    en = np.array([notes[i]["end"] for i in idx], dtype=np.float64)
    vel = np.array([notes[i].get("velocity") or 80 for i in idx], dtype=np.float32)
    hint = np.array(
        [{"R": 1.0, "L": -1.0}.get(notes[i].get("hand"), 0.0) for i in idx], dtype=np.float32
    )
    gid = np.zeros(n, dtype=np.int64)
    g, g0 = 0, st[0]
    for k in range(1, n):
        if st[k] - g0 > GROUP_SEC:
            g += 1
            g0 = st[k]
        gid[k] = g
    ng = g + 1
    gmin = np.full(ng, 200.0, dtype=np.float32)
    gmax = np.full(ng, -1.0, dtype=np.float32)
    gsize = np.zeros(ng, dtype=np.float32)
    np.minimum.at(gmin, gid, midi)
    np.maximum.at(gmax, gid, midi)
    np.add.at(gsize, gid, 1)
    first = np.r_[0, np.flatnonzero(np.diff(gid)) + 1]
    gst = st[first]
    dprev = np.r_[2.0, np.diff(gst)]
    dnext = np.r_[np.diff(gst), 2.0]
    X = np.zeros((n, N_FEAT), dtype=np.float32)
    X[:, 0] = (midi - 64) / 20
    X[:, 1] = np.log1p(np.clip(dprev[gid], 0, 8) / 0.05) / 4
    X[:, 2] = np.log1p(np.clip(dnext[gid], 0, 8) / 0.05) / 4
    X[:, 3] = np.log1p(np.clip(en - st, 0, 8) / 0.1) / 4
    X[:, 4] = vel / 127
    X[:, 5] = (midi - gmin[gid]) / 12
    X[:, 6] = (gmax[gid] - midi) / 12
    X[:, 7] = np.minimum(gsize[gid], 8) / 4
    X[:, 8] = (np.r_[1, np.diff(gid)] > 0).astype(np.float32)
    X[:, 9] = hint
    keys = np.clip(midi.astype(np.int64) - 21, 0, 87)
    return keys, X, gid


def _sigmoid(x: np.ndarray) -> np.ndarray:
    return 1 / (1 + np.exp(-x))


def _gru(x: np.ndarray, w: dict, name: str, reverse: bool) -> np.ndarray:
    """One GRU direction over a batch [B, T, in] (PyTorch gate order r, z, n)."""
    wih, whh = w[f"rnn.weight_ih_{name}"], w[f"rnn.weight_hh_{name}"]
    bih, bhh = w[f"rnn.bias_ih_{name}"], w[f"rnn.bias_hh_{name}"]
    b, t_len, _ = x.shape
    h_size = whh.shape[1]
    gi = x @ wih.T + bih
    whh_t = np.ascontiguousarray(whh.T)
    h = np.zeros((b, h_size), dtype=np.float32)
    out = np.empty((b, t_len, h_size), dtype=np.float32)
    steps = range(t_len - 1, -1, -1) if reverse else range(t_len)
    for t in steps:
        gh = h @ whh_t + bhh
        g = gi[:, t]
        r = _sigmoid(g[:, :h_size] + gh[:, :h_size])
        z = _sigmoid(g[:, h_size : 2 * h_size] + gh[:, h_size : 2 * h_size])
        c = np.tanh(g[:, 2 * h_size :] + r * gh[:, 2 * h_size :])
        h = (1 - z) * c + z * h
        out[:, t] = h
    return out


def _forward(w: dict, keys: np.ndarray, X: np.ndarray) -> np.ndarray:
    """P(right hand) per note, the sequence cut into overlapping windows."""
    n = len(keys)
    starts = list(range(0, n, CORE))
    span = min(n, CORE + 2 * CONTEXT)
    xb = np.zeros((len(starts), span, X.shape[1] + w["emb.weight"].shape[1]), dtype=np.float32)
    lo_of = []
    for j, s in enumerate(starts):
        lo = max(0, min(s - CONTEXT, n - span))
        lo_of.append(lo)
        xb[j] = np.concatenate([w["emb.weight"][keys[lo : lo + span]], X[lo : lo + span]], 1)
    # Windows that run past the sequence's end are padded at the end; the
    # windows are placed so none needs padding (lo <= n - span).
    x = xb
    for layer in range(2):
        f = _gru(x, w, f"l{layer}", False)
        b = _gru(x, w, f"l{layer}_reverse", True)
        x = np.concatenate([f, b], 2)
    z = (x @ w["out.weight"].T + w["out.bias"])[:, :, 0]
    p = np.empty(n, dtype=np.float32)
    for j, s in enumerate(starts):
        e = min(n, s + CORE)
        lo = lo_of[j]
        p[s:e] = _sigmoid(z[j, s - lo : e - lo])
    return p


def _split(notes: list[dict], split: int) -> dict[str, str]:
    return {
        n["id"]: n["hand"] if n.get("hand") in ("L", "R") else ("R" if n["midi"] >= split else "L")
        for n in notes
    }


def _digest(notes: list[dict]) -> str:
    rows = sorted(
        (
            n["id"],
            n["midi"],
            round(n["start"], 4),
            round(n["end"], 4),
            n.get("velocity"),
            n.get("hand"),
        )
        for n in notes
    )
    return hashlib.sha1(json.dumps(rows).encode()).hexdigest()


_CACHE: dict[str, dict[str, str]] = {}


def probabilities(notes: list[dict]) -> dict[str, float]:
    """note id -> P(right hand) from the model (hands set by the user are hints)."""
    w = _weights()
    if w is None or not notes:
        return {}
    idx = _order(notes)
    keys, X, _ = features(notes, idx)
    p = _forward(w, keys, X)
    return {notes[i]["id"]: float(p[k]) for k, i in enumerate(idx)}


def assign_hands(notes: list[dict], split: int = 60) -> dict[str, str]:
    """note id -> "L" | "R". A note's own "hand" (set by the user) is kept."""
    w = _weights()
    if w is None or not notes:
        return _split(notes, split)
    key = _digest(notes)
    if key in _CACHE:
        return _CACHE[key]
    if all(n.get("hand") in ("L", "R") for n in notes):  # a falling-notes video
        out = {n["id"]: n["hand"] for n in notes}
    else:
        idx = _order(notes)
        keys, X, gid = features(notes, idx)
        p = _forward(w, keys, X)
        # The split point breaks ties: a melody alone around middle C, which
        # the model leaves near 0.5, reads as the right hand's.
        logit = np.log(np.clip(p, 1e-6, 1) / np.clip(1 - p, 1e-6, 1))
        logit += SPLIT_PRIOR * np.where(keys + 21 >= split, 1.0, -1.0)
        p = propagate(notes, idx, 1 / (1 + np.exp(-logit)))
        out = decode(notes, idx, gid, p)
    if len(_CACHE) > 32:
        _CACHE.clear()
    _CACHE[key] = out
    return out


def propagate(notes: list[dict], idx: list[int], p_right: np.ndarray) -> np.ndarray:
    """A key the user put in one hand pulls the same key nearby (PROPAGATE_SEC
    either side, fading with the distance) towards that hand.

    The model reads the user's hands too, but a correction moves few of its
    neighbours by itself; a note repeated on one key (a 55 struck again and
    again, an inner voice) was what kept going wrong after its first fix.
    Measured by playing a user who corrects the earliest wrong note until none
    is left, on the songs with known hands: 269 errors took 247 corrections
    with the model's hints alone, 196 with this (267 -> 201 with the split
    point's tie-break) (other trainings of the same
    model: 279 -> 251, 265 -> 213). Neighbouring keys as well made it worse: a
    semitone away is often the other hand's line. It can also pull a note the
    model had right (Für Elise, held out: 55 errors, 80 corrections)."""
    fixed = [(k, notes[i]["hand"]) for k, i in enumerate(idx) if notes[i].get("hand") in ("L", "R")]
    if not fixed:
        return p_right
    p = np.clip(p_right.astype(np.float64), 1e-6, 1 - 1e-6)
    logit = np.log(p / (1 - p))
    starts = np.array([notes[i]["start"] for i in idx])
    midi = np.array([notes[i]["midi"] for i in idx])
    by_key: dict[int, np.ndarray] = {}
    for k, hand in fixed:
        m = int(midi[k])
        if m not in by_key:
            by_key[m] = np.flatnonzero(midi == m)
        same = by_key[m]
        near = np.clip(1 - np.abs(starts[same] - starts[k]) / PROPAGATE_SEC, 0, None)
        logit[same] += (PROPAGATE if hand == "R" else -PROPAGATE) * near
    return 1 / (1 + np.exp(-logit))


def decode(
    notes: list[dict], idx: list[int], gid: np.ndarray, p_right: np.ndarray
) -> dict[str, str]:
    """Hands from P(right) per note (in `idx` order), one chord at a time."""
    p = np.clip(p_right.astype(np.float64), 1e-6, 1 - 1e-6)
    log_r, log_l = np.log(p), np.log(1 - p)
    out: dict[str, str] = {}
    held: dict[str, list[tuple[float, int]]] = {"L": [], "R": []}  # (until, midi)
    k0 = 0
    n = len(idx)
    while k0 < n:
        k1 = k0
        while k1 < n and gid[k1] == gid[k0]:
            k1 += 1
        chord = sorted(range(k0, k1), key=lambda k: notes[idx[k]]["midi"])
        fixed = [notes[idx[k]].get("hand") for k in chord]
        pitch = [notes[idx[k]]["midi"] for k in chord]
        t = notes[idx[chord[0]]]["start"]
        for h in held:
            held[h] = [x for x in held[h] if x[0] > t + 0.02]
        # The lowest `cut` notes go to the left hand: the cut the model
        # likes best, never against a hand the user set, and with each hand
        # within reach of the keys it still holds down.
        best, cut = -np.inf, 0
        for c in range(len(chord) + 1):
            s = float(log_l[chord[:c]].sum() + log_r[chord[c:]].sum())
            s -= FORCED * sum(
                1 for q, h in enumerate(fixed) if (h == "L" and q >= c) or (h == "R" and q < c)
            )
            for h, mine in (("L", pitch[:c]), ("R", pitch[c:])):
                keys = mine + [m for _, m in held[h]]
                if mine and max(keys) - min(keys) > REACH:
                    s -= REACH_COST
            if s > best:
                best, cut = s, c
        for q, k in enumerate(chord):
            note = notes[idx[k]]
            hand = fixed[q] if fixed[q] in ("L", "R") else ("L" if q < cut else "R")
            out[note["id"]] = hand
            held[hand].append((min(note["end"], note["start"] + HELD_MAX_SEC), note["midi"]))
        k0 = k1
    return out
