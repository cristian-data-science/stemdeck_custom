"""Chopin, Nocturne in C# minor (B. 49, op. posth.): the whole piece as a
library track, with the printed fingering of the Alfred page.

    .venv/Scripts/python.exe scripts/experimental/nocturno_chopin.py \
        --gouin <gouin.mxl> --alfred <folder with Audiveris' omr/ of the Alfred page> \n        --recording <rec.json> [--write]

Why a script and not the import button: the Alfred page the user has holds
bars 1-18 only, Audiveris lost its bar 13 and its grace notes, and no trill
was played. The notes come instead from Pierre Gouin's typeset edition (IMSLP,
Les Éditions Outremontaises 2006: the whole nocturne, 64 bars, the intro
written out twice), read by Audiveris and corrected by hand where it misread
(FIXES: every bar checked against the page at 300-500 dpi). The fingers come
from the Alfred page (Audiveris + digits.py), moved to Gouin's bar numbers.
The tempo, bar by bar, is the one of a real performance (Stefano Ligoratti,
IMSLP #72479), found by aligning the score to its transcription; the same
alignment says, bar by bar, how many of the pianist's notes the score has.

Alfred bar a = Gouin bar a (a <= 2, and the repeat of the intro: a + 2),
Gouin bar a + 2 for a >= 3.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from fractions import Fraction
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from app.experimental.sheet import ornaments  # noqa: E402
from app.experimental.sheet.musicxml import parse  # noqa: E402

TITLE = "Nocturno en do# menor, op. póstumo (Chopin) — completo"
FIFTHS = 4  # C# minor


# Time signatures as printed: 4/4, bar 32 in 5/4, 33-43 in 3/4, 4/4 again.
def bar_quarters(m: int) -> float:
    if m == 32:
        return 5.0
    if 33 <= m <= 43:
        return 3.0
    return 4.0


# Bars Audiveris misread, written out from the page. Per staff, events in
# order; "|" starts another voice at the bar start.
#   d:P / d:P+P   a note / chord lasting d quarters (1/3, 0.75...), P a pitch
#                 as sounding, accidental included (C#5, Fx4, D5 = D natural)
#   d:r           a rest
#   @tr @f        trill / fermata on the note before
#   ~             tied to the same pitch next
#   g:P,P+P       small notes before the next note (a trill's start, or an
#                 acciaccatura chord just before the beat)
#   a:P,P         small notes after the trill before (its termination)
#   runD:P,P,...  a free run spread evenly over D quarters
RUN_GOUIN_15 = (
    "1/3:C#7 1/3:D7 1/3:B6 1/3:A6 1/3:G#6 1/3:F#6 "  # 8va
    "0.2:E#6 0.2:D6 0.2:C#6 0.2:B5 0.2:A5 "
    "1/6:G#5 1/6:F#5 1/6:E#5 1/6:D5 1/6:C#5 1/6:B4"
)
FIXES: dict[int, dict[int, str]] = {
    # Gouin prints the two small notes E5-F#5 before the trills of 5, 13
    # and 46; the Alfred page does not ("the trill begins on the principal
    # note") and neither does the recording: left out.
    5: {1: "2:G#5 2:F#5@tr a:E5,F#5"},
    # Gouin ties the C#6; Alfred strikes it again (finger 3), as Ligoratti does.
    7: {1: "2:C#6 0.75:C#6 0.25:B5 1/3:C#6 1/3:B5 1/3:A5"},
    11: {
        1: "g:C#5,D#5 3:D#5@tr 0.5:D#5 0.5:C#5",
        2: "0.5:G#2 0.5:D#3 0.5:C#4 0.5:F#3 0.5:G#2 0.5:D#3 1:G#3 | 1:r 2:C#4 0.5:B#3 0.5:A#3",
    },
    13: {1: "2:G#5 2:F#5@tr a:E5,F#5,G#5,A5"},
    15: {1: RUN_GOUIN_15},
    24: {
        1: "g:E5+C#6 0.75:D5+B5 0.25:C#5+A5 0.75:D5+B5 0.25:E5+C#6 2:C#5+A5",
        2: "0.5:A2 0.5:E3 0.5:E4 0.5:G#3 0.5:A2 0.5:E3 0.5:E4 0.5:A3",
    },
    28: {
        1: "g:G#4+E5 0.75:F#4+D#5 0.25:E4+C#5 0.75:F#4+D#5 0.25:G#4+E5 2:E4+C#5",
        2: "0.5:G#2 0.5:D#3 0.5:B#3 0.5:G#3 0.5:C#3 0.5:E3 0.5:C#4 0.5:G#3",
    },
    32: {
        1: "0.75:D#4 0.25:C#5 0.5:E#4 0.5:Fx4 0.5:G#4 0.25:r 0.25:G#5 1.5:B#4@f 0.5:C#5",
        2: "0.5:D#3 0.5:A#3 0.5:C#4 0.5:D#4 1/3:G#2 1/3:D#3 1/3:G#3 1.5:B#3@f 0.5:G#3",
    },
    # 44-47: Audiveris missed the treble clef in the middle of bar 44.
    44: {
        1: "1/3:r 1/3:D#3 1/3:B#3 1/3:G#3 1/3:B#3 1/3:D#4 "
        "1/3:B#4 1/3:G#4 1/3:B#4 1/3:D#5 1/3:G#5 1/3:B#5"
    },
    45: {1: "2:G#6@f 1:r 1:G#4"},
    46: {1: "2:G#5 2:F#5@tr a:E5,F#5,G#5,A5"},
    47: {1: "2:G#5 1:C#5 1:C#6"},
    48: {1: RUN_GOUIN_15},
    51: {
        1: "2:E5@tr a:D#5,E5 1:F#5 1:C#5",
        2: "0.5:C#3 0.5:E3 0.5:C#4 0.5:G#3 0.5:A2 0.5:D#3 0.5:C#4 0.5:A3",
    },
    52: {
        1: "1/3:D#5 1/3:E5 1/3:D#5 1/3:Cx5 1/3:D#5 1/3:E5 "
        "0.2:F#5 0.2:G#5 0.2:A5 0.2:A#5 0.2:B5 "
        "1/6:B#5 1/6:C#6 1/6:Cx6 1/6:D#6 1/6:E6 1/6:F#6"
    },
    56: {1: "4:D#5@tr a:C#5"},
    57: {1: "2:C#5 run2:D#5,E5,F#5,G#5,A5,B5,C#6,D#6,C#6,B5,A5,G#5,F#5,E5,D#5,C#5,B4,A4"},
    58: {
        1: "2:G#4 run2:A4,B4,C#5,D#5,E5,F#5,G#5,A5,"
        "B5,C#6,D#6,E6,F#6,G#6,A6,B6,C#7,D#7,C#7,B6,A6,G#6,F#6,E6,D#6,C#6,B5,"  # 8va
        "A5,G#5,F#5,E5,D#5,C#5,B4,A4"
    },
    59: {1: "2:G#4 run2:A4,B4,C#5,D#5,E5,F#5,E5,D#5,C#5,B4,A4"},
    60: {1: "2:G#4 run2:A4,B4,C#5,D#5,E5,F#5,G#5,F#5,E5,D#5,C#5,B4,A4"},
    61: {1: "4:G#4~"},
    62: {1: "4:G#4~"},
    63: {1: "1.5:G#4 0.5:C#5 0.5:E#5 0.5:G#5 0.5:C#6 0.5:E#6"},
    64: {1: "4:C#7@f", 2: "4:C#2@f"},  # 8va
}

PITCH = re.compile(r"^([A-G])(bb|b|#|x)?(-?\d)$")
ALTER = {None: 0, "#": 1, "x": 2, "b": -1, "bb": -2}
STEP_PC = {"C": 0, "D": 2, "E": 4, "F": 5, "G": 7, "A": 9, "B": 11}


def pitch(p: str) -> tuple[int, str, int]:
    """(midi, step, octave) of "C#5"."""
    m = PITCH.match(p)
    if not m:
        raise ValueError(p)
    step, acc, octave = m.group(1), m.group(2), int(m.group(3))
    return 12 * (octave + 1) + STEP_PC[step] + ALTER[acc], step, octave


def parse_fix(text: str, staff: int, measure: int, start_q: float, velocity: int) -> list[dict]:
    """A FIXES entry -> notes in quarters (start/end) like parse(bpm=60) gives."""
    out = []
    for voice in text.split("|"):
        t = Fraction(0)
        pending: list[list[int]] = []
        last: list[dict] = []
        for tok in voice.split():
            kind, _, body = tok.partition(":")
            if kind == "g":
                pending = [[pitch(p)[0] for p in ev.split("+")] for ev in body.split(",")]
                continue
            if kind == "a":
                for n in last:
                    n.setdefault("trill", {})["post"] = [pitch(p)[0] for p in body.split(",")]
                continue
            if kind.startswith("run"):
                notes = body.split(",")
                span = Fraction(kind[3:])
                dt = span / len(notes)
                for i, p in enumerate(notes):
                    on = t + i * dt
                    n = _note(pitch(p)[0], start_q, on, dt, staff, measure, velocity)
                    out.append(dict(n, run=True))
                t += span
                last = []
                continue
            d = Fraction(kind)
            flags = set(re.findall(r"@(\w+)", body))
            body = re.sub(r"@\w+", "", body)
            if body == "r":
                t += d
                continue
            last = []
            for p in body.split("+"):
                tie = p.endswith("~")
                midi, step, octave = pitch(p.rstrip("~"))
                n = _note(midi, start_q, t, d, staff, measure, velocity)
                if tie:
                    n["tie"] = True
                if "f" in flags:
                    n["fermata"] = True
                if "tr" in flags:
                    n["trill"] = {
                        "upper": ornaments.upper_neighbour(step, octave, FIFTHS),
                        "pre": [g[0] for g in pending],
                    }
                last.append(n)
                out.append(n)
            if pending and "tr" not in flags:
                # An acciaccatura (chord): just before the beat, 0.08 quarters each.
                for k, chord in enumerate(pending):
                    g_on = float(t) - (len(pending) - k) * 0.08
                    for m in chord:
                        g = _note(m, start_q, Fraction(0), Fraction(0), staff, measure, velocity)
                        g.update(start=start_q + g_on, end=start_q + g_on + 0.08, grace=True)
                        g.pop("onset_q")
                        out.append(g)
            pending = []
            t += d
    return out


def _note(midi, start_q, on, d, staff, measure, velocity) -> dict:
    return {
        "midi": midi,
        "start": start_q + float(on),
        "end": start_q + float(on + d),
        "velocity": velocity,
        "staff": staff,
        "measure": measure,
        "onset_q": round(float(on), 4),
    }


def gouin_notes(mxl: Path) -> tuple[list[dict], list[float]]:
    """Every note in quarters (start/end), with FIXES applied; and bar starts."""
    score = parse(mxl, bpm=60)  # one second = one quarter
    assert score.measures == 64, score.measures
    starts = [0.0]
    for m in range(1, 65):
        starts.append(starts[-1] + bar_quarters(m))
    notes = []
    vel: dict[tuple[int, int], list[int]] = {}
    for n in score.notes:
        st = 1 if n["staff"] == 1 else 2
        vel.setdefault((n["measure"], st), []).append(n["velocity"])
        if n["measure"] in FIXES and st in FIXES[n["measure"]]:
            continue
        n = dict(n, staff=st)
        if n.get("grace"):
            raise ValueError(f"grace note left in bar {n['measure']}: write it in FIXES")
        notes.append(n)
    for m, staves in FIXES.items():
        for st, text in staves.items():
            v = vel.get((m, st)) or vel.get((m - 1, st)) or [60]
            notes += parse_fix(text, st, m, starts[m - 1], round(sum(v) / len(v)))
    # Ties written in FIXES (61-62-63): one note.
    notes.sort(key=lambda n: (n["start"], n["midi"]))
    for n in [n for n in notes if n.get("tie")]:
        nxt = next(
            (x for x in notes if x["midi"] == n["midi"] and abs(x["start"] - n["end"]) < 1e-6),
            None,
        )
        if nxt is not None:
            n["end"] = nxt["end"]
            notes.remove(nxt)
            nxt["merged"] = True
        n.pop("tie")
    # The same key struck twice at once (the C#4 of bar 11 in both voices): once.
    seen: dict[tuple[int, float], dict] = {}
    for n in list(notes):
        k = (n["midi"], round(n["start"], 4))
        if k in seen:
            seen[k]["end"] = max(seen[k]["end"], n["end"])
            notes.remove(n)
        else:
            seen[k] = n
    # Every bar adds up, in every voice: nothing may start past its bar.
    for n in notes:
        m = n["measure"]
        assert starts[m - 1] - 0.5 <= n["start"] < starts[m] + 1e-6, (m, n)
    return notes, starts


# -- fingers from the Alfred page --------------------------------------------------


def alfred_fingers(alfred: Path) -> tuple[list[dict], list]:
    """The Alfred page's fingered notes (Audiveris + digits.py), and the digits
    found in its bar 13, which Audiveris could not export."""
    from app.experimental.sheet import digits
    from app.experimental.sheet.song import read_more_fingers

    omr = alfred / "omr"
    score = parse(next(omr.glob("*.mxl")), bpm=60)
    read_more_fingers(score, omr)
    found, layout = digits.find_digits(next(omr.glob("*.omr")))
    lost_bar = [f for f in digits.place(found, layout) if f.measure in score.missing_measures]
    return [n for n in score.notes if n.get("finger") and not n.get("grace")], lost_bar


def gouin_bars(a: int) -> list[int]:
    return [a, a + 2] if a <= 2 else [a + 2]


# The fingering printed on the Alfred page (the user's PDF), read from the page
# at 300 dpi, on Gouin's bars: (bar, staff, beat, key) -> finger. The detector
# (digits.py) reads most of these on its own; check_alfred() compares.
ALFRED = {
    # Alfred 1 = Gouin 1 and 3
    **{
        (g, st, on, k): f
        for g in (1, 3)
        for (st, on, k), f in {
            (1, 0, "C#5"): 5, (1, 0, "G#4"): 2, (1, 0, "E4"): 1,
            (1, 1.5, "B4"): 5, (1, 1.5, "G#4"): 3, (1, 1.5, "C#4"): 1,
            (1, 2, "A4"): 4, (1, 2, "F#4"): 2,
            (1, 3.5, "G#4"): 4, (1, 3.5, "E4"): 2,
            (2, 0, "C#2"): 5, (2, 1.5, "C#3"): 2,
        }.items()
    },
    # Alfred 2 = Gouin 2 and 4 (the C#4 and E4 are held from bar 1)
    **{
        (g, 1, on, k): f
        for g in (2, 4)
        for (on, k), f in {(0, "Fx4"): 3, (1, "D#4"): 2, (1, "B#3"): 1}.items()
    },
    (5, 1, 0, "G#5"): 3,
    (5, 2, 0, "C#3"): 5, (5, 2, 0.5, "G#3"): 3, (5, 2, 1, "E4"): 1, (5, 2, 1.5, "C#4"): 2,
    (5, 2, 2, "C#3"): 5, (5, 2, 2.5, "A3"): 1, (5, 2, 3, "D#4"): 2, (5, 2, 3.5, "C#4"): 3,
    (6, 1, 0, "G#5"): 4, (6, 2, 0, "C#3"): 5, (6, 2, 0.5, "G#3"): 3,
    (7, 1, 0, "C#6"): 4, (7, 1, 2, "C#6"): 3, (7, 1, 3.667, "A5"): 1,
    (8, 1, 0, "A5"): 2,
    (8, 2, 0, "F#3"): 5, (8, 2, 0.5, "A3"): 4, (8, 2, 1, "F#4"): 1, (8, 2, 1.5, "C#4"): 2,
    (9, 1, 0, "G#5"): 5,
    (12, 1, 3, "G#4"): 1,
    (13, 1, 0, "G#5"): 5,  # then 3 on the held key ("5 3")
    # Alfred 13 = Gouin 15, the 8va run: same 17 notes, beamed otherwise.
    (15, 1, 0, "C#7"): 3, (15, 1, 0.667, "B6"): 2, (15, 1, 1, "A6"): 1, (15, 1, 1.333, "G#6"): 4,
    (15, 1, 2.2, "D6"): 1, (15, 1, 2.4, "C#6"): 3, (15, 1, 3, "G#5"): 4, (15, 1, 3.5, "D5"): 1,
    (16, 1, 0, "A4"): 3, (16, 2, 3, "A3"): 1,
    (17, 1, 3.5, "C#5"): 3,
    (19, 1, 1, "A4"): 5,
}  # fmt: skip
# Trills: the fingers printed over them (principal, upper) and on their small
# notes before / after.
TRILL_FINGERS = {
    5: {"p": 2, "u": 3, "post": [1, 3]},  # "2 3", termination "1 3"
    11: {"p": 2, "u": 3, "pre": [1, 2]},  # small notes "1 2", trill "3 2"
    13: {"p": 2, "u": 3},  # "2 3"
    18: {"p": 2, "u": 3},  # "3 2" over B#4: 2 on B#4, 3 on C#5
}
# Bars Gouin prints again note for note (the return of 13-15 as 46-48).
REPEATS = {13: 46, 14: 47, 15: 48}


def apply_alfred(notes: list[dict]) -> dict:
    """The printed fingers on their notes. Counts, and what found no note."""
    placed, missed = 0, []
    for (bar, st, on, key), f in ALFRED.items():
        midi = pitch(key)[0]
        n = next(
            (
                n
                for n in notes
                if n["measure"] == bar
                and n["staff"] == st
                and n["midi"] == midi
                and abs(n.get("onset_q", -9) - on) < 0.01
            ),
            None,
        )
        if n is None:
            missed.append((bar, st, on, key, f))
            continue
        n["finger"] = f
        placed += 1
    for bar, fing in TRILL_FINGERS.items():
        for n in notes:
            if n["measure"] == bar and n.get("trill"):
                n["trill"]["fingers"] = fing
                n["finger"] = fing["p"]
    again = 0
    for src, dst in REPEATS.items():
        a = sorted((n for n in notes if n["measure"] == src), key=lambda n: (n["start"], n["midi"]))
        b = sorted((n for n in notes if n["measure"] == dst), key=lambda n: (n["start"], n["midi"]))
        if [(n["staff"], n.get("onset_q"), n["midi"]) for n in a] != [
            (n["staff"], n.get("onset_q"), n["midi"]) for n in b
        ]:
            raise ValueError(f"bar {dst} is no longer bar {src} again")
        for x, y in zip(a, b, strict=True):
            if x.get("finger"):
                y["finger"] = x["finger"]
                again += 1
            if x.get("trill", {}).get("fingers"):
                y["trill"]["fingers"] = x["trill"]["fingers"]
    return {"placed": placed, "again": again, "missed": missed}


def check_alfred(alfred: Path) -> dict:
    """How many of the table's fingers the automatic reading (Audiveris +
    digits.py on the Alfred page) also gives, at the same place."""
    fingered, lost_bar = alfred_fingers(alfred)
    table = {(b, s, round(o, 2), pitch(k)[0]): f for (b, s, o, k), f in ALFRED.items()}
    same = differ = 0
    for a in fingered:
        st = 1 if a["staff"] == 1 else 2
        for g in gouin_bars(a["measure"]):
            f = table.get((g, st, round(a["onset_q"], 2), a["midi"]))
            if f is None:
                continue
            same += f == a["finger"]
            differ += f != a["finger"]
    read = [f.finger for f in sorted(lost_bar, key=lambda f: f.box[0])]
    run = [f for (b, s, o, k), f in sorted(ALFRED.items()) if b == 15] + [ALFRED[(16, 1, 0, "A4")]]
    return {
        "same": same,
        "differ": differ,
        "run_read": read,
        "run_table": sorted(run) == sorted(read),
    }


# -- the performance: tempo bar by bar, and how many of its notes the score has --


def _features(notes, t_of, frames, hop):
    import numpy as np

    on = np.zeros((frames, 12))
    hold = np.zeros((frames, 12))
    for n in notes:
        a, b = t_of(n["start"]), t_of(n["end"])
        i, j = int(a / hop), max(int(a / hop) + 1, int(b / hop))
        if i >= frames:
            continue
        on[i, n["midi"] % 12] += 1
        hold[i : min(j, frames), n["midi"] % 12] += 0.25
    from scipy.ndimage import gaussian_filter1d

    on = gaussian_filter1d(on, 1.0, axis=0)
    f = np.hstack([on, hold]) + 1e-3
    return f / np.linalg.norm(f, axis=1, keepdims=True)


def align(notes, starts, rec_notes) -> tuple[list[float], callable]:
    """Bar start times in the recording (65 values) and a quarter->second map
    following the alignment note by note."""
    import librosa
    import numpy as np

    sq = 0.125  # score frame: an eighth of a quarter
    sr_hop = 0.05
    total_q = starts[-1]
    rec_end = max(n["end"] for n in rec_notes)
    fs = _features(notes, lambda q: q, int(total_q / sq) + 1, sq)
    fr = _features(rec_notes, lambda s: s, int(rec_end / sr_hop) + 1, sr_hop)
    _, path = librosa.sequence.dtw(X=fs.T, Y=fr.T, metric="cosine")
    path = path[::-1]
    qs = path[:, 0] * sq
    ts = path[:, 1] * sr_hop
    # Each score frame: the mean recording time it was matched to; monotonic.
    uq = np.unique(qs)
    ut = np.array([ts[qs == q].mean() for q in uq])
    ut = np.maximum.accumulate(ut)
    first = min(n["start"] for n in rec_notes)

    def q2s(q: float) -> float:
        return float(np.interp(q, uq, ut))

    # Refine onset by onset (a score follower): every onset of the score (a
    # chord is one) gets a time where the pianist struck its keys, near the
    # coarse path, by dynamic programming: as many keys found as possible,
    # with a steady local tempo between onsets.
    plain = [n for n in notes if not (n.get("trill") or n.get("grace"))]
    events: dict[float, set[int]] = {}
    for n in plain:
        events.setdefault(round(n["start"], 3), set()).add(n["midi"])
    eq = sorted(events)
    rec_s = sorted(rec_notes, key=lambda r: r["start"])
    rt = np.array([r["start"] for r in rec_s])
    rm = np.array([r["midi"] for r in rec_s])
    for _round in range(4):
        # Seconds per quarter around q: the map's slope over three beats each side.
        def spq(q: float, f=q2s) -> float:
            return max(0.15, (f(q + 3) - f(q - 3)) / 6)

        cands = []  # per onset: [(time, keys found)], last one = "not found"
        for q in eq:
            t0 = q2s(q)
            lo, hi = np.searchsorted(rt, t0 - 5.0), np.searchsorted(rt, t0 + 5.0)
            opts = []
            for j in range(lo, hi):
                if rm[j] in events[q]:
                    near = (np.abs(rt[lo:hi] - rt[j]) <= 0.09) & np.isin(rm[lo:hi], list(events[q]))
                    opts.append((float(rt[j]), int(len(set(rm[lo:hi][near])))))
            opts = sorted(set(opts))
            opts.append((t0, 0))
            cands.append(opts)
        # Viterbi: gain = keys found; cost = change of local tempo (log ratio).
        best = [[(-float(k), -1) for _, k in cands[0]]]
        for i in range(1, len(eq)):
            dq = eq[i] - eq[i - 1]
            ref = max(0.02, dq * spq(eq[i]))  # seconds for dq at the local tempo
            row = []
            for t, k in cands[i]:
                bc, bj = float("inf"), 0
                for j, (tp, _) in enumerate(cands[i - 1]):
                    dt = t - tp
                    if dt <= 0.02 * dq:
                        continue
                    c = best[i - 1][j][0] + 0.45 * abs(np.log(dt / ref))
                    if c < bc:
                        bc, bj = c, j
                if bc == float("inf"):  # nothing before fits: follow the coarse path
                    bj = len(cands[i - 1]) - 1
                    bc = best[i - 1][bj][0] + 5.0
                row.append((bc - k, bj))
            best.append(row)
        j = int(np.argmin([c for c, _ in best[-1]]))
        times = [0.0] * len(eq)
        found = [0] * len(eq)
        for i in range(len(eq) - 1, -1, -1):
            times[i], found[i] = cands[i][j][0], cands[i][j][1]
            j = best[i][j][1]
        keep = [i for i in range(len(eq)) if found[i] > 0]
        uq = np.array([eq[i] for i in keep])
        ut = np.array([times[i] for i in keep])
        ok = np.concatenate([[True], np.diff(ut) > 0])
        uq, ut = uq[ok], ut[ok]

        def q2s(q: float, uq=uq, ut=ut) -> float:  # noqa: F811
            return float(np.interp(q, uq, ut))

    bars = [q2s(q) for q in starts]
    bars[0] = first
    bars[-1] = max(bars[-1], rec_end)
    return bars, q2s


def compare(notes, rec_notes, q2s, starts, tol=0.15) -> list[dict]:
    """Per bar: the score's notes the pianist played (pitch and time), and
    the pianist's notes the score does not have. Trills and free runs are
    counted apart (a trill's number of notes is the pianist's own)."""
    import bisect

    rec = sorted(rec_notes, key=lambda n: n["start"])
    rec_t = [n["start"] for n in rec]
    used = set()
    bar_q = [q2s(q) for q in starts]

    def linear(q: float) -> float:
        import numpy as np

        return float(np.interp(q, starts, bar_q))

    bars = [
        {"bar": m, "notes": 0, "found": 0, "extra": 0, "missing": [], "extra_pitches": []}
        for m in range(1, 65)
    ]
    orn_windows = []
    for n in notes:
        if n.get("ornament") or n.get("grace") or n.get("run"):
            orn_windows.append((q2s(n["start"]) - 0.1, q2s(n["end"]) + 0.1))
            continue
        b = bars[n["measure"] - 1]
        b["notes"] += 1
        best = None
        # Where the follower puts it, else steady inside its bar (the follower
        # can slip inside a bar where a chord repeats; the bar ends are sure).
        for t in (q2s(n["start"]), linear(n["start"])):
            i = bisect.bisect_left(rec_t, t - tol)
            while i < len(rec) and rec_t[i] <= t + tol:
                closer = best is None or abs(rec_t[i] - t) < abs(rec_t[best] - t)
                if i not in used and rec[i]["midi"] == n["midi"] and closer:
                    best = i
                i += 1
            if best is not None:
                break
        if best is not None:
            used.add(best)
            b["found"] += 1
        else:
            b["missing"].append(n["midi"])
    bar_t = [q2s(q) for q in starts]
    for i, r in enumerate(rec):
        if i in used or r["velocity"] < 25:
            continue
        if any(a <= r["start"] <= b for a, b in orn_windows):
            continue
        m = max(1, min(64, bisect.bisect_right(bar_t, r["start"])))
        bars[m - 1]["extra"] += 1
        bars[m - 1]["extra_pitches"].append(r["midi"])
    return bars


NAMES = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]


def name(m: int) -> str:
    return f"{NAMES[m % 12]}{m // 12 - 1}"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--gouin", type=Path, required=True)
    ap.add_argument(
        "--alfred",
        type=Path,
        default=Path("jobs/e0640828479e/sheet/alfred"),
        help="the Alfred page as imported: page.pdf and omr/ (kept with the track)",
    )
    ap.add_argument(
        "--recording", type=Path, required=True, help="the performance transcribed (raw notes JSON)"
    )
    ap.add_argument("--write", action="store_true", help="create the library track")
    ap.add_argument("--report", type=Path)
    args = ap.parse_args()

    from app.core.config import JOBS_DIR

    notes, starts = gouin_notes(args.gouin)
    fing = apply_alfred(notes)
    check = check_alfred(args.alfred)

    rec_notes = json.loads(args.recording.read_text(encoding="utf-8"))["notes"]
    bar_t, q2s = align(notes, starts, rec_notes)

    # Seconds: each bar as long as the pianist played it (linear inside the bar).
    import numpy as np

    def to_sec(q: float) -> float:
        return float(np.interp(q, starts, bar_t)) - bar_t[0]

    timed = []
    for n in notes:
        x = dict(n, start=round(to_sec(n["start"]), 4), end=round(to_sec(n["end"]), 4))
        timed.append(x)
    played = ornaments.realize(timed)
    beats, bars_meta = [], []
    for m in range(1, 65):
        q0, qn = starts[m - 1], bar_quarters(m)
        count = int(qn)
        if not bars_meta or bars_meta[-1]["beats_per_bar"] != count:
            bars_meta.append({"beat": len(beats), "beats_per_bar": count})
        beats += [round(to_sec(q0 + i), 4) for i in range(count)]
    total = to_sec(starts[-1])
    bpm = round(60 * starts[-1] / total, 1)

    # The comparison, on the realized notes (trills counted apart).
    played_q = [dict(n) for n in played]
    s_axis = [to_sec(q) for q in starts]
    for n in played_q:  # back to quarters for compare()
        n["start"] = float(np.interp(n["start"], s_axis, starts))
        n["end"] = float(np.interp(n["end"], s_axis, starts))
    cmp = compare(played_q, rec_notes, q2s, starts)
    tot_n = sum(b["notes"] for b in cmp)
    tot_f = sum(b["found"] for b in cmp)
    tot_x = sum(b["extra"] for b in cmp)
    lines = [
        f"compases: 64 · notas: {len(played)} (sin trinos: {tot_n}) · duración {total:.1f} s · ~{bpm} negras/min",
        f"dedos impresos (Alfred): {fing['placed']} + trinos {len(TRILL_FINGERS)} + {fing['again']} repetidos "
        f"en la reexposición · sin nota: {len(fing['missed'])} · lectura automática: {check['same']} iguales, "
        f"{check['differ']} distintos; escala del c. 13 {check['run_read']} (coincide: {check['run_table']})",
        f"contra la grabación (Ligoratti): {tot_f}/{tot_n} notas de la partitura tocadas "
        f"({100 * tot_f / max(1, tot_n):.0f} %), {tot_x} notas de la grabación fuera de la partitura",
        "",
        "compás  tiempo  partitura  tocadas  extra   faltan / sobran",
    ]
    for b, t0 in zip(cmp, bar_t, strict=False):
        miss = " ".join(name(m) for m in b["missing"][:6])
        extra = " ".join(name(m) for m in sorted(b["extra_pitches"])[:8])
        lines.append(
            f"{b['bar']:>5}  {t0 - bar_t[0]:6.1f}  {b['notes']:>9}  {b['found']:>7}  {b['extra']:>5}   {miss}{' / ' + extra if extra else ''}"
        )
    if fing["missed"]:
        lines.append("")
        lines.append("dedos de Alfred sin nota (compás Gouin, pentagrama, tiempo, nota, dedo):")
        lines += [f"  {b} {s} {o} {k} {f}" for b, s, o, k, f in fing["missed"]]
    text = "\n".join(lines)
    print(text)
    if args.report:
        args.report.write_text(text, encoding="utf-8")

    if args.write:
        import secrets

        from app.experimental.sheet.song import write_track

        for n in played:
            n.pop("onset_q", None)
        job_id = secrets.token_hex(6)
        result = write_track(
            job_id,
            TITLE,
            played,
            beats=beats,
            bars=bars_meta,
            bpm=bpm,
            engine="partitura (Gouin + correcciones; dedos Alfred)",
            source_url="local:partitura:chopin-nocturno-op-posth (Gouin, IMSLP)",
            source_format="pdf",
            report={
                "measures": 64,
                "missing_measures": [],
                "fingers_alfred": fing["placed"] + fing["again"],
                "tempo_from": "Stefano Ligoratti (IMSLP #72479)",
                "comparison": {"score_notes": tot_n, "played": tot_f, "extra": tot_x},
            },
        )
        (JOBS_DIR / job_id / "sheet" / "comparison.txt").write_text(text, encoding="utf-8")
        print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
