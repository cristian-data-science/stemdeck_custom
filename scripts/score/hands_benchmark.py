"""How well app/score/hands.py tells the hands apart, on notes whose hand is known.

    .venv/Scripts/python.exe scripts/score/hands_benchmark.py [--hannds <dir>/data-hannds] [--fixes]

Prints, per song, the share of notes in the right hand for the model and for
a fixed split at middle C. --fixes also plays a user who corrects the
earliest wrong note until none is left (the model reads each correction as a
hint), and counts the corrections: with no hints that would be one per error.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from hands_data import UNRELIABLE, hannds, held_out, known_jobs  # noqa: E402

from app.score import hands  # noqa: E402


def strip(notes, fixed=None):
    fixed = fixed or {}
    return [
        {**{k: v for k, v in n.items() if k != "gt"}, "hand": fixed.get(n["id"])} for n in notes
    ]


def split(notes):
    return {n["id"]: "R" if n["midi"] >= 60 else "L" for n in notes}


def fixes_needed(notes, cap=300):
    fixed: dict[str, str] = {}
    errors0 = None
    for it in range(cap):
        out = hands.assign_hands(strip(notes, fixed))
        wrong = [n for n in sorted(notes, key=lambda n: n["start"]) if out[n["id"]] != n["gt"]]
        if errors0 is None:
            errors0 = len(wrong)
        if not wrong:
            return errors0, it
        fixed[wrong[0]["id"]] = wrong[0]["gt"]
    return errors0, cap


def report(title, songs, fixes=False):
    print(f"\n{title}")
    tot = ok_m = ok_s = 0
    E = F = 0
    for name, notes in songs:
        m = hands.assign_hands(strip(notes))
        s = split(notes)
        am = sum(m[n["id"]] == n["gt"] for n in notes)
        as_ = sum(s[n["id"]] == n["gt"] for n in notes)
        flag = "  (no cuenta: verdad dudosa)" if name in UNRELIABLE else ""
        line = f"  {name[:34]:34s} {len(notes):5d} notas  modelo {100 * am / len(notes):5.1f} %  corte C4 {100 * as_ / len(notes):5.1f} %"
        if fixes and name not in UNRELIABLE:
            e, f = fixes_needed(notes)
            E += e
            F += f
            line += f"  errores {e:3d} -> correcciones {f}"
        print(line + flag)
        if name not in UNRELIABLE:
            tot += len(notes)
            ok_m += am
            ok_s += as_
    print(
        f"  {'TOTAL':34s} {tot:5d} notas  modelo {100 * ok_m / tot:5.1f} %  corte C4 {100 * ok_s / tot:5.1f} %"
        + (f"  errores {E} -> correcciones {F}" if fixes else "")
    )


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--hannds", help="data-hannds folder: measure on its 12 held-out pieces too")
    ap.add_argument("--fixes", action="store_true")
    args = ap.parse_args()
    if not hands.available():
        sys.exit(f"no model at {hands.MODEL_PATH}")
    report("Canciones con manos conocidas (videos y partitura)", known_jobs(), args.fixes)
    if args.hannds:
        songs = hannds(args.hannds)
        keep = held_out(songs)
        report(
            "hannds: piezas no usadas al entrenar", [s for s in songs if s[0] in keep], args.fixes
        )


if __name__ == "__main__":
    main()
