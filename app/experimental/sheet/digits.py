"""Printed fingering digits that Audiveris misses, found on the page itself.

Audiveris read 10 of the 59 fingers printed on the Chopin nocturne page. This
looks for them directly in the page image Audiveris binarised (inside its
.omr book), where its own layout is known: staves, measure stacks with the
x of every time slot, note heads with their staff.

1. Candidates: connected blobs about a digit's size, not part of anything
   Audiveris already recognised (heads, stems, beams, accidentals, tuplet
   numbers, rests...).
2. Shape: each blob is compared with 0-9 rendered in several bold serif
   fonts (fingering is set in a bold upright face) and with italic ones (the
   tuplet "3"s are italic: they must not count as fingers).
3. Place: a digit belongs to the notes right below it (above the staff) or
   right above it (below the staff), at the same x; digits stacked over a
   chord go to its notes from the top down; a pair side by side ("2 3",
   change fingers on a held or trilled note) keeps the first.

Each found finger is returned as (measure, staff, onset in quarter notes,
rank in its chord from the top, finger), which musicxml.parse can match.
"""

from __future__ import annotations

import io
import xml.etree.ElementTree as ET
import zipfile
from dataclasses import dataclass
from fractions import Fraction
from functools import lru_cache
from pathlib import Path

import numpy as np

UPRIGHT = [
    "SCHLBKB.TTF",
    "timesbd.ttf",
    "BOOKOSB.TTF",
    "georgiab.ttf",
    "cambriab.ttf",
    "palab.ttf",
    "CENSCBK.TTF",
]
ITALIC = ["SCHLBKBI.TTF", "timesbi.ttf", "timesi.ttf", "SCHLBKI.TTF", "palabi.ttf", "BOOKOSBI.TTF"]
GRID = (20, 28)  # (w, h) every blob and template is compared at
BLUR = 1.2  # px of softening on that grid
ACCEPT = 0.68  # correlation a blob needs with an upright digit 1-5
MARGIN = 0.03  # ... and its lead over any other class (6-9, 0, italic digits)
EXCLUDE = {
    "head", "alter", "key-alter", "clef", "rest", "flag", "augmentation-dot",
    "tuplet", "articulation", "time-whole", "time-pair", "repeat-dot", "fermata", "ornament",
    "small-head", "arpeggiato", "pedal",
}  # fmt: skip
BAND = 4.2  # a finger lies within this many interlines of its staff (not the title)
SURE = 0.70  # first-pass digits this sure teach the page's own font to the second pass


@dataclass
class Found:
    measure: int  # stack index on the page, 1-based (= printed bar number)
    staff: int  # 1 treble, 2 bass
    onset_q: float  # quarter notes from the bar start
    rank: int  # 0 = highest note of its chord at that onset
    finger: int
    score: float
    box: tuple[int, int, int, int]  # x, y, w, h in the .omr image


# -- the page as Audiveris saw it --------------------------------------------


def _bounds(el) -> tuple[int, int, int, int] | None:
    b = el.find("bounds")
    if b is None:
        return None
    return int(b.get("x")), int(b.get("y")), int(b.get("w")), int(b.get("h"))


def read_book(omr: Path):
    """(binary image as bool array, interline, staves, stacks, heads, boxes)."""
    from PIL import Image

    with zipfile.ZipFile(omr) as z:
        name = next(n for n in z.namelist() if n.endswith(".xml") and n.startswith("sheet#"))
        root = ET.fromstring(z.read(name))
        png = next(n for n in z.namelist() if n.endswith("BINARY.png"))
        img = np.array(Image.open(io.BytesIO(z.read(png))).convert("L")) < 128
    interline = float(root.find("scale/interline").get("main"))
    staves, stacks, heads, boxes = {}, [], [], []
    for system in root.iter("system"):
        sys_staves = []
        for staff in system.iter("staff"):
            ys = [float(p.get("y")) for line in staff.iter("line") for p in line.iter("point")]
            if not ys:
                continue
            sid = int(staff.get("id"))
            # A line's y varies a little along the page (skew): keep per line its mean.
            lines = [
                np.mean([float(p.get("y")) for p in line.iter("point")])
                for line in staff.iter("line")
            ]
            staves[sid] = {"top": min(lines), "bottom": max(lines), "system": system.get("id")}
            sys_staves.append(sid)
        for st in system.findall("stack"):
            left = float(st.get("left"))
            slots = [
                (left + float(s.get("x-offset")), float(Fraction(s.get("time-offset"))) * 4)
                for s in st.findall("slot")
            ]
            stacks.append(
                {
                    "id": int(st.get("id")),
                    "left": left,
                    "right": float(st.get("right")),
                    "slots": slots,
                    "staves": sys_staves,
                }
            )
    for el in root.iter():
        tag = el.tag
        if tag not in EXCLUDE and tag != "fingering":
            continue
        b = _bounds(el)
        if b is None:
            continue
        if tag == "head":
            heads.append({"box": b, "staff": int(el.get("staff", 0))})
        if tag in EXCLUDE:
            boxes.append(b)
    return img, interline, staves, stacks, heads, boxes


# -- shapes -------------------------------------------------------------------


def _norm(mask: np.ndarray) -> np.ndarray:
    """A blob cropped to its ink and resized to GRID, zero-mean unit-norm."""
    from PIL import Image

    ys, xs = np.nonzero(mask)
    if len(xs) == 0:
        return np.zeros(GRID[::-1])
    crop = mask[ys.min() : ys.max() + 1, xs.min() : xs.max() + 1].astype(np.uint8) * 255
    a = np.asarray(Image.fromarray(crop).resize(GRID, Image.BILINEAR), dtype=float) / 255
    # Softened: a scan's heavier strokes still line up with a font's.
    from scipy.ndimage import gaussian_filter

    a = gaussian_filter(a, BLUR)
    a -= a.mean()
    n = np.linalg.norm(a)
    return a / n if n else a


@lru_cache(maxsize=1)
def _templates() -> list[tuple[str, bool, float, np.ndarray]]:
    """(digit, upright?, width/height, normalised image) for every font found."""
    from PIL import Image, ImageDraw, ImageFont

    out = []
    for fonts, upright in ((UPRIGHT, True), (ITALIC, False)):
        for name in fonts:
            try:
                font = ImageFont.truetype(name, 72)
            except OSError:
                continue
            for d in "0123456789":
                im = Image.new("L", (90, 110), 0)
                ImageDraw.Draw(im).text((10, 5), d, fill=255, font=font)
                m = np.asarray(im) > 128
                ys, xs = np.nonzero(m)
                aspect = (xs.max() - xs.min() + 1) / (ys.max() - ys.min() + 1)
                out.append((d, upright, aspect, _norm(m)))
    return out


def classify(mask: np.ndarray, extra: list | None = None) -> tuple[int | None, float]:
    """The finger a blob reads as (1-5), or None, with its score. `extra`:
    more templates (digits read surely on this very page)."""
    ys, xs = np.nonzero(mask)
    aspect = (xs.max() - xs.min() + 1) / (ys.max() - ys.min() + 1)
    if aspect < 0.3:  # a stem or ledger stub, not even a "1" (with its serifs)
        return None, 0.0
    v = _norm(mask)
    best: dict[tuple[str, bool], float] = {}
    for d, upright, ta, t in _templates() + (extra or []):
        s = float((v * t).sum()) - 0.25 * abs(aspect - ta)
        best[(d, upright)] = max(s, best.get((d, upright), -9.0))
    (d, upright), s = max(best.items(), key=lambda kv: kv[1])
    if not upright or d not in "12345" or s < ACCEPT:
        return None, s
    # Clearly this digit, upright: not another digit, not its italic twin.
    rival = max((sc for k, sc in best.items() if k != (d, True)), default=-9.0)
    if s - rival < MARGIN:
        return None, s
    return int(d), s


# -- candidates and placement ----------------------------------------------


def _overlap(a, b) -> float:
    ax, ay, aw, ah = a
    bx, by, bw, bh = b
    w = min(ax + aw, bx + bw) - max(ax, bx)
    h = min(ay + ah, by + bh) - max(ay, by)
    return (w * h) / (aw * ah) if w > 0 and h > 0 else 0.0


def _candidates(img: np.ndarray, il: float, staves: dict, boxes: list):
    """(mask, box) for every blob about a digit's size near a staff; a blob
    two digits tall (a "5" sitting on a "2") is cut where its ink is thinnest."""
    from scipy import ndimage

    labels, _ = ndimage.label(img)
    bands = [(st["top"] - BAND * il, st["bottom"] + BAND * il) for st in staves.values()]
    for i, sl in enumerate(ndimage.find_objects(labels), start=1):
        if sl is None:
            continue
        h = sl[0].stop - sl[0].start
        w = sl[1].stop - sl[1].start
        if not (0.25 * il <= w <= 1.25 * il and 0.75 * il <= h <= 3.3 * il):
            continue
        cy = sl[0].start + h / 2
        if not any(lo <= cy <= hi for lo, hi in bands):
            continue
        box = (sl[1].start, sl[0].start, w, h)
        if any(_overlap(box, b) > 0.5 for b in boxes):
            continue
        mask = labels[sl] == i
        if h <= 1.6 * il:
            yield mask, box
            continue
        # Two stacked digits touching: cut at the thinnest row of the middle.
        rows = mask.sum(axis=1)
        lo, hi = int(h * 0.3), int(h * 0.7)
        cut = lo + int(np.argmin(rows[lo:hi]))
        for part, y0 in ((mask[:cut], 0), (mask[cut:], cut)):
            ys, xs = np.nonzero(part)
            if len(ys) < 10:
                continue
            sub = part[ys.min() : ys.max() + 1, xs.min() : xs.max() + 1]
            if 0.75 * il <= sub.shape[0] <= 1.6 * il:
                yield (
                    sub,
                    (
                        box[0] + int(xs.min()),
                        box[1] + y0 + int(ys.min()),
                        sub.shape[1],
                        sub.shape[0],
                    ),
                )


def find_digits(omr: Path) -> tuple[list[tuple[int, float, tuple]], dict]:
    """[(finger, score, box)] for every digit-like blob, and the page layout.
    Two passes: the surest digits of the first teach the page's own font."""
    img, il, staves, stacks, heads, boxes = read_book(omr)
    cands = list(_candidates(img, il, staves, boxes))
    first = [(classify(mask), mask) for mask, _ in cands]
    extra = []
    for (finger, score), mask in first:
        if finger and score >= SURE:
            ys, xs = np.nonzero(mask)
            aspect = (xs.max() - xs.min() + 1) / (ys.max() - ys.min() + 1)
            extra.append((str(finger), True, aspect, _norm(mask)))
    found = []
    for mask, box in cands:
        finger, score = classify(mask, extra)
        if finger:
            found.append((finger, score, box))
    layout = {"interline": il, "staves": staves, "stacks": stacks, "heads": heads}
    return found, layout


def place(found: list[tuple[int, float, tuple]], layout: dict) -> list[Found]:
    """Each digit on its note: (bar, staff, onset, rank in the chord)."""
    il = layout["interline"]
    heads = layout["heads"]
    stacks = layout["stacks"]
    staves = layout["staves"]
    # Side-by-side pairs ("2 3"): keep the left one.
    found = sorted(found, key=lambda f: (f[2][0], f[2][1]))
    keep = []
    for f in found:
        x, y, w, h = f[2]
        if any(
            abs(y - k[2][1]) < 0.4 * il and 0 < x - (k[2][0] + k[2][2]) < 0.6 * il for k in keep
        ):
            continue
        keep.append(f)
    out: list[Found] = []
    groups: dict[tuple, list] = {}
    for finger, score, box in keep:
        x, y, w, h = box
        cx, cy = x + w / 2, y + h / 2
        # Heads right below or above, at this x.
        near = [
            hd
            for hd in heads
            if abs(hd["box"][0] + hd["box"][2] / 2 - cx) < 1.1 * il and hd["staff"] in staves
        ]
        if not near:
            continue
        above = [hd for hd in near if hd["box"][1] > cy]  # digit above the heads
        below = [hd for hd in near if hd["box"][1] + hd["box"][3] < cy]  # digit below them
        if above and (
            not below
            or min(hd["box"][1] for hd in above) - cy
            <= cy - max(hd["box"][1] + hd["box"][3] for hd in below)
        ):
            side, cand = "above", above
        elif below:
            side, cand = "below", below
        else:
            continue
        # The chord: heads at the same x as the nearest one.
        ref = min(cand, key=lambda hd: abs(hd["box"][1] - cy))
        rx = ref["box"][0] + ref["box"][2] / 2
        chord = [
            hd
            for hd in cand
            if abs(hd["box"][0] + hd["box"][2] / 2 - rx) < 0.8 * il and hd["staff"] == ref["staff"]
        ]
        key = (id(ref), side, round(rx))
        groups.setdefault(
            key, {"chord": chord, "side": side, "digits": [], "staff": ref["staff"], "x": rx}
        )["digits"].append((cy, finger, score, box))
    for g in groups.values():
        chord = sorted(g["chord"], key=lambda hd: hd["box"][1])  # top first
        digits = sorted(g["digits"])  # top first
        if g["side"] == "below":  # stacked under: the lowest digit is the lowest note
            chord, digits = chord[::-1], digits[::-1]
        stack = next(
            (
                s
                for s in stacks
                if s["left"] - 2 <= g["x"] <= s["right"] + 2 and g["staff"] in s["staves"]
            ),
            None,
        )
        if stack is None:
            continue
        onset = (
            min(stack["slots"], key=lambda sl: abs(sl[0] - g["x"]))[1] if stack["slots"] else 0.0
        )
        staff = 1 if g["staff"] % 2 == 1 else 2
        for i, (_cy, finger, score, box) in enumerate(digits[: len(chord)]):
            hd = chord[i]
            # Rank from the top among the heads of that staff at that slot.
            col = sorted(
                (
                    h2
                    for h2 in heads
                    if h2["staff"] == g["staff"]
                    and abs(h2["box"][0] + h2["box"][2] / 2 - g["x"]) < 0.8 * il
                ),
                key=lambda h2: h2["box"][1],
            )
            rank = next((j for j, h2 in enumerate(col) if h2 is hd), i)
            out.append(Found(stack["id"], staff, onset, rank, finger, score, box))
    return out


def attach(notes: list[dict], found: list[Found], tol: float = 0.13) -> int:
    """Put each found finger on its note (same bar, staff and onset; its rank
    from the top among the notes there) unless the note already has one
    (Audiveris' own reading wins). Returns how many were added."""
    added = 0
    for f in found:
        here = [
            n
            for n in notes
            if n.get("measure") == f.measure
            and (1 if n["staff"] == 1 else 2) == f.staff
            and not n.get("grace")
            and abs(n.get("onset_q", -99) - f.onset_q) <= tol
        ]
        if not here:
            continue
        here.sort(key=lambda n: -n["midi"])
        n = here[min(f.rank, len(here) - 1)]
        if not n.get("finger"):
            n["finger"] = f.finger
            n["finger_from"] = "page"
            added += 1
    return added
