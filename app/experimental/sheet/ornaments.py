"""Trills played out as notes, so the falling-notes view shows (and the audio
plays) what a pianist plays, not one long note under a "tr".

A trill note carries {"upper": midi, "pre": [midi...], "post": [midi...]}:
the upper neighbour it alternates with, and the small notes printed before
it (played on the beat: the Chopin turn E-F#-trill) and after it (the
termination before the next note). Without notes before it, the trill starts
on the principal note (the Alfred edition's footnote for this nocturne, and
Chopin's usual practice); it always ends on the principal note, then the
termination.

Speed: about TRILL_SEC per note, evenly over the written length: a slow
whole-note trill gets more notes, not slower ones.

Fingers: the trill note's own finger goes on every principal note; a
"fingers" entry ({"p", "u", "pre", "post"}: what an edition prints over the
trill, "2 3", and on its small notes) fingers the rest.
"""

from __future__ import annotations

TRILL_SEC = 0.12  # ~8 notes per second

# Sharps / flats added by the key signature, in order.
SHARPS = "FCGDAEB"
FLATS = "BEADGCF"
STEPS = "CDEFGAB"
STEP_PC = {"C": 0, "D": 2, "E": 4, "F": 5, "G": 7, "A": 9, "B": 11}


def key_alter(step: str, fifths: int) -> int:
    if fifths > 0 and step in SHARPS[:fifths]:
        return 1
    if fifths < 0 and step in FLATS[:-fifths]:
        return -1
    return 0


def upper_neighbour(step: str, octave: int, fifths: int, alter: int | None = None) -> int:
    """The next note up the scale from a written step: B#4 in C# minor -> C#5.
    `alter`: an accidental printed with the trill (overrides the key)."""
    i = STEPS.index(step)
    up, octave = (STEPS[i + 1], octave) if i < 6 else ("C", octave + 1)
    if alter is None:
        alter = key_alter(up, fifths)
    return 12 * (octave + 1) + STEP_PC[up] + alter


def realize(notes: list[dict], note_sec: float = TRILL_SEC) -> list[dict]:
    """The notes, with every trill note replaced by its notes. Times in seconds.
    The principal notes keep the trill note's printed finger."""
    out = []
    for n in notes:
        t = n.get("trill")
        if not t:
            out.append(n)
            continue
        p, u = n["midi"], t["upper"]
        pre, post = list(t.get("pre") or []), list(t.get("post") or [])
        span = n["end"] - n["start"]
        k = max(len(pre) + len(post) + 3, round(span / note_sec))
        mid = k - len(pre) - len(post)
        start_upper = bool(pre) and pre[-1] == p
        seq = [u if (i % 2 == 0) == start_upper else p for i in range(mid)]
        if seq[-1] != p:  # end on the principal note
            seq.pop()
        # Fingers printed for the trill: {"p", "u", "pre": [...], "post": [...]}.
        fing = t.get("fingers") or {}
        pf = fing.get("p") or n.get("finger")
        fingers = (
            list(fing.get("pre") or [None] * len(pre))
            + [pf if m == p else fing.get("u") for m in seq]
            + list(fing.get("post") or [None] * len(post))
        )
        seq = pre + seq + post
        dt = span / len(seq)
        for i, m in enumerate(seq):
            x = {k2: v for k2, v in n.items() if k2 not in ("trill", "finger")}
            x.update(
                midi=m,
                start=round(n["start"] + i * dt, 4),
                end=round(n["start"] + (i + 1) * dt, 4),
                velocity=n["velocity"] if i == 0 else max(30, n["velocity"] - 8),
                ornament="trill",
            )
            if fingers[i]:
                x["finger"] = fingers[i]
            out.append(x)
    return out
