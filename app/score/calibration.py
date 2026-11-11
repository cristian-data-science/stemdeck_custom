"""The calibration piece: a short piano score whose every note is known.

Used three ways:
  * tests transcribe its synthesized audio and score the result (mir_eval);
  * tests engrave its exact notes and compare against EXPECTED;
  * scripts/make_score_demo.py registers it as a library track, so a person
    can open the score view and check it against the list in EXPECTED_TEXT
    instead of judging "by eye".

F major, 4/4, 90 BPM, 8 bars:
  1  RH scale F G A B-flat (quarters)        LH F2+C3 halves      -> Fa
  2  RH scale C D E F (quarters)             LH C3+G3 halves      -> Do
  3  RH F-A-C whole chord                    LH F2 whole          -> Fa
  4  RH B-flat-D-F half, C-E-G half          LH B-flat2, C3       -> Si♭  Do
  5  RH eighths A B-flat C D C B-flat A G    LH D3+F3+A3 whole    -> Rem
  6  RH A-C#-E half chord, then two triplets LH E3 whole          -> La/Mi
  7  RH G dotted quarter, E eighth, B-flat half  LH C3+E3 whole   -> Do7
  8  RH F-A-C whole chord                    LH F2+F3 whole       -> Fa
"""

from __future__ import annotations

import math

BPM = 90.0
LEAD_IN_SEC = 1.0
BEATS_PER_BAR = 4
N_BARS = 8
KEY = ("F", "Major")

# (bar 1-based, beat offset in the bar, length in beats, midi notes)
_RH = [
    (1, 0, 1, [65]),
    (1, 1, 1, [67]),
    (1, 2, 1, [69]),
    (1, 3, 1, [70]),
    (2, 0, 1, [72]),
    (2, 1, 1, [74]),
    (2, 2, 1, [76]),
    (2, 3, 1, [77]),
    (3, 0, 4, [65, 69, 72]),
    (4, 0, 2, [70, 74, 77]),
    (4, 2, 2, [72, 76, 79]),
    *[(5, i * 0.5, 0.5, [m]) for i, m in enumerate([69, 70, 72, 74, 72, 70, 69, 67])],
    (6, 0, 2, [69, 73, 76]),
    *[(6, 2 + i / 3, 1 / 3, [m]) for i, m in enumerate([76, 73, 69, 76, 73, 69])],
    (7, 0, 1.5, [67]),
    (7, 1.5, 0.5, [64]),
    (7, 2, 2, [70]),
    (8, 0, 4, [65, 69, 72]),
]
_LH = [
    (1, 0, 2, [41, 48]),
    (1, 2, 2, [41, 48]),
    (2, 0, 2, [48, 55]),
    (2, 2, 2, [48, 55]),
    (3, 0, 4, [41]),
    (4, 0, 2, [46]),
    (4, 2, 2, [48]),
    (5, 0, 4, [50, 53, 57]),
    (6, 0, 4, [52]),
    (7, 0, 4, [48, 52]),
    (8, 0, 4, [41, 53]),
]

EXPECTED = {
    "bpm": 90,
    "meter": "4/4",
    "key": "Fa mayor",
    "measures": 8,
    "notes": 59,
    "chords": ["Fa", "Do", "Fa", "Si♭", "Do", "Rem", "La/Mi", "Do7", "Fa"],
}

EXPECTED_TEXT = """Lo que debes ver en la partitura de calibración:
1. Cabecera: 90 BPM, compás 4/4, tonalidad Fa mayor (un bemol en la armadura).
2. Dos pentagramas por sistema: clave de sol arriba, clave de fa abajo, unidos con llave.
3. 8 compases y 59 notas, cada una con su nombre adentro (fa, sol, la, si…).
4. Acordes arriba: Fa | Do | Fa | Si♭ Do | Rem | La/Mi | Do7 | Fa.
5. Compás 5: ocho corcheas unidas por barras. Compás 6: dos tresillos y un do con sostenido (♯).
6. Al reproducir, la nota que suena se ilumina y el cursor avanza al ritmo del audio."""


def _beat_sec(beat: float) -> float:
    return LEAD_IN_SEC + beat * 60.0 / BPM


def beats() -> list[float]:
    total = N_BARS * BEATS_PER_BAR + 4
    return [round(_beat_sec(i), 6) for i in range(total)]


def bars() -> list[dict]:
    return [{"beat": 0, "beats_per_bar": BEATS_PER_BAR}]


def notes(gap: float = 0.03) -> list[dict]:
    """The piece in seconds, with a small release gap so repeated notes are
    heard as two notes."""
    out = []
    for hand, rows in (("R", _RH), ("L", _LH)):
        for bar, off, length, midis in rows:
            start_beat = (bar - 1) * BEATS_PER_BAR + off
            start = _beat_sec(start_beat)
            end = _beat_sec(start_beat + length) - gap
            for m in midis:
                out.append(
                    {
                        "midi": m,
                        "start": round(start, 4),
                        "end": round(end, 4),
                        "velocity": 80,
                        "hand_truth": hand,
                    }
                )
    out.sort(key=lambda n: (n["start"], n["midi"]))
    for i, n in enumerate(out):
        n["id"] = f"n{i:05d}"
    return out


def duration_sec() -> float:
    return _beat_sec(N_BARS * BEATS_PER_BAR) + 2.0


def synthesize(note_list: list[dict], sr: int = 44100):
    """A piano-like render: inharmonic partials with frequency-dependent decay
    and a soft hammer transient. Good enough for a piano model to hear notes,
    deliberately not a sampled piano."""
    import numpy as np

    total = int((max(n["end"] for n in note_list) + 2.0) * sr)
    out = np.zeros(total, dtype=np.float64)
    for n in note_list:
        f0 = 440.0 * 2 ** ((n["midi"] - 69) / 12)
        start = int(n["start"] * sr)
        hold = max(n["end"] - n["start"], 0.05)
        length = int((hold + 0.25) * sr)
        t = np.arange(length) / sr
        tone = np.zeros(length)
        b = 0.0004
        for k in range(1, 9):
            fk = k * f0 * math.sqrt(1 + b * k * k)
            if fk > sr / 2.2:
                break
            decay = (0.5 + 0.6 * k) * (f0 / 261.6) ** 0.35
            tone += (1.0 / k**2) * np.exp(-t * decay) * np.sin(2 * math.pi * fk * t)
        # Continuous release (a damper, not a cut): a step in the envelope is
        # heard by a transcription model as a second attack.
        env = np.minimum(1.0, t / 0.004)
        env *= np.where(t > hold, np.exp(-(t - hold) / 0.05), 1.0)
        rng = np.random.default_rng(n["midi"])
        hammer = rng.standard_normal(length) * np.exp(-t * 300) * 0.15
        amp = (n.get("velocity", 80) / 127) ** 1.5
        seg = (tone * env + hammer) * amp
        end = min(total, start + length)
        out[start:end] += seg[: end - start]
    peak = float(np.max(np.abs(out))) or 1.0
    return (out / peak * 0.8).astype(np.float32)
