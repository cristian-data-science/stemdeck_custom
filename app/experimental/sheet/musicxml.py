"""MusicXML (as Audiveris exports it) -> notes in seconds, beats and bars, and
the fingers printed on the score.

Played as written, at one tempo: no repeats unfolded, no rubato. Grace notes
are slipped in just before their main note; before a trill they are the
start of the trill (ornaments.py plays trills out as notes). A measure the reader lost (the
exporter skips a measure it could not build: bar 13 of the Chopin nocturne)
is put back as a silent bar, so bar numbers keep matching the page, and is
reported.
"""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET
import zipfile
from dataclasses import dataclass, field
from pathlib import Path

from app.experimental.sheet.ornaments import upper_neighbour

STEP_PC = {"C": 0, "D": 2, "E": 4, "F": 5, "G": 7, "A": 9, "B": 11}
DYNAMICS = {"ppp": 30, "pp": 40, "p": 55, "mp": 65, "mf": 75, "f": 90, "ff": 105, "fff": 118}
GRACE_SEC = 0.08  # each grace note, taken from before its main note
DEFAULT_BPM = 60.0
ACCIDENTAL_MARK = {"sharp": 1, "natural": 0, "flat": -1, "double-sharp": 2, "flat-flat": -2}


@dataclass
class Score:
    notes: list[dict]
    beats: list[float]
    bars: list[dict]
    bpm: float
    fifths: int
    mode: str | None
    measures: int
    missing_measures: list[int] = field(default_factory=list)
    title: str = ""

    @property
    def fingers_read(self) -> int:
        return sum(1 for n in self.notes if n.get("finger"))


def read_xml(path: Path) -> ET.Element:
    """The score element of a .mxl (zip) or a plain .xml/.musicxml file."""
    if zipfile.is_zipfile(path):
        with zipfile.ZipFile(path) as z:
            name = None
            if "META-INF/container.xml" in z.namelist():
                container = ET.fromstring(z.read("META-INF/container.xml"))
                root = container.find(".//{*}rootfile")
                name = root.get("full-path") if root is not None else None
            if not name:
                name = next(
                    n for n in z.namelist() if n.endswith(".xml") and not n.startswith("META-INF")
                )
            return ET.fromstring(z.read(name))
    return ET.parse(path).getroot()


def _midi(pitch: ET.Element) -> int:
    step = pitch.findtext("step")
    octave = int(pitch.findtext("octave"))
    alter = round(float(pitch.findtext("alter") or 0))
    return 12 * (octave + 1) + STEP_PC[step] + alter


def _finger(note: ET.Element) -> int | None:
    """The first finger digit printed for the note (1-5), if any. "23" over
    a trill (play with 2 then 3) gives 2."""
    for f in note.findall("notations/technical/fingering"):
        m = re.search(r"[1-5]", f.text or "")
        if m:
            return int(m.group())
    return None


def parse(path: Path, bpm: float | None = None) -> Score:
    root = read_xml(path)
    title = (root.findtext("work/work-title") or root.findtext("movement-title") or "").strip()
    parts = root.findall("part")
    if not parts:
        raise ValueError("el MusicXML no tiene partes")

    # The tempo printed in the score, unless one is given.
    if bpm is None:
        for snd in root.iter("sound"):
            if snd.get("tempo"):
                bpm = float(snd.get("tempo"))
                break
    bpm = float(bpm or DEFAULT_BPM)
    q_sec = 60.0 / bpm  # one quarter note

    notes: list[dict] = []
    fifths, mode = 0, None
    layout: list[tuple[float, float, int, int]] = []  # (start_q, length_q, beats, beat_type)
    missing: list[int] = []
    staff_offset = 0

    for pi, part in enumerate(parts):
        divisions = 1.0
        beats_n, beat_type = 4, 4
        measure_start = 0.0
        last_number = None
        velocity = {1: 70, 2: 70}
        open_ties: dict[tuple[int, int], dict] = {}
        max_staff = 1
        for m_idx, measure in enumerate(part.findall("measure")):
            if pi > 0:
                # Other parts follow the first part's bars.
                measure_start = layout[min(m_idx, len(layout) - 1)][0] if layout else 0.0
            number = measure.get("number", "")
            num = int(number) if number.isdigit() else None
            # Put back measures the exporter skipped, as silent bars.
            if pi == 0 and num is not None and last_number is not None and num > last_number + 1:
                for lost in range(last_number + 1, num):
                    length = beats_n * 4 / beat_type
                    layout.append((measure_start, length, beats_n, beat_type))
                    missing.append(lost)
                    measure_start += length
            if num is not None:
                last_number = num

            attrs = measure.find("attributes")
            if attrs is not None:
                if attrs.findtext("divisions"):
                    divisions = float(attrs.findtext("divisions"))
                if attrs.find("key/fifths") is not None:
                    fifths = int(attrs.findtext("key/fifths"))
                    mode = attrs.findtext("key/mode") or mode
                if attrs.find("time/beats") is not None:
                    beats_n = int(re.match(r"\d+", attrs.findtext("time/beats")).group())
                    beat_type = int(attrs.findtext("time/beat-type"))
                if attrs.findtext("staves"):
                    max_staff = max(max_staff, int(attrs.findtext("staves")))

            cursor = 0.0  # quarter notes from the measure start
            reach = 0.0
            last_onset = 0.0
            graces: list[dict] = []
            for el in measure:
                if el.tag == "backup":
                    cursor -= float(el.findtext("duration")) / divisions
                elif el.tag == "forward":
                    cursor += float(el.findtext("duration")) / divisions
                    reach = max(reach, cursor)
                elif el.tag == "direction":
                    for dyn in el.findall("direction-type/dynamics/*"):
                        if dyn.tag in DYNAMICS:
                            staff = int(el.findtext("staff") or 1)
                            velocity[staff] = DYNAMICS[dyn.tag]
                elif el.tag == "note":
                    staff = int(el.findtext("staff") or 1) + staff_offset
                    is_chord = el.find("chord") is not None
                    grace = el.find("grace") is not None
                    dur = float(el.findtext("duration") or 0) / divisions
                    onset = last_onset if is_chord else cursor
                    if not is_chord and not grace:
                        last_onset = cursor
                        cursor += dur
                        reach = max(reach, cursor)
                    pitch = el.find("pitch")
                    if pitch is None or el.find("rest") is not None:
                        continue
                    midi = _midi(pitch)
                    finger = _finger(el)
                    if grace:
                        graces.append({"midi": midi, "staff": staff, "finger": finger})
                        continue
                    start_q = measure_start + onset
                    ties = {t.get("type") for t in el.findall("tie")}
                    key = (staff, midi)
                    if "stop" in ties and key in open_ties:
                        held = open_ties[key]
                        held["end_q"] = start_q + dur
                        if "start" not in ties:
                            del open_ties[key]
                        continue
                    n = {
                        "midi": midi,
                        "start_q": start_q,
                        "end_q": start_q + dur,
                        "onset_q": round(onset, 4),  # within its bar, for digits.attach
                        "staff": staff,
                        "velocity": velocity.get(staff - staff_offset, 70),
                        "measure": num,
                    }
                    if finger:
                        n["finger"] = finger
                    orn = el.find("notations/ornaments")
                    if orn is not None and orn.find("trill-mark") is not None:
                        mark = orn.findtext("accidental-mark")
                        alter = ACCIDENTAL_MARK.get(mark) if mark else None
                        up = upper_neighbour(
                            pitch.findtext("step"), int(pitch.findtext("octave")), fifths, alter
                        )
                        n["trill"] = {"upper": up, "pre": [g["midi"] for g in graces]}
                        graces = []  # played on the beat, as the trill's start
                    if el.find("notations/fermata") is not None:
                        n["fermata"] = True
                    notes.append(n)
                    if "start" in ties:
                        open_ties[key] = n
                    # Grace notes waiting for this note: just before it.
                    if graces:
                        g_q = GRACE_SEC / q_sec
                        for i, g in enumerate(graces):
                            gs = start_q - (len(graces) - i) * g_q
                            gn = {
                                "midi": g["midi"],
                                "start_q": gs,
                                "end_q": gs + g_q,
                                "staff": g["staff"],
                                "velocity": max(30, n["velocity"] - 10),
                                "measure": num,
                                "grace": True,
                            }
                            if g["finger"]:
                                gn["finger"] = g["finger"]
                            notes.append(gn)
                        graces = []
            if pi == 0:
                nominal = beats_n * 4 / beat_type
                implicit = measure.get("implicit") == "yes"
                # The printed bar length: a misread duration (bar 16 of the nocturne
                # overflowed to 5 beats) must not stretch the bar.
                length = reach if (implicit and reach > 0) else nominal
                layout.append((measure_start, length, beats_n, beat_type))
                measure_start += length
        staff_offset += max_staff

    # Beats (one per beat of each bar, in its own beat unit) and bars.
    beats: list[float] = []
    bars: list[dict] = []
    for start_q, length_q, _beats_n, beat_type in layout:
        unit = 4 / beat_type
        count = max(1, round(length_q / unit))
        if not bars or bars[-1]["beats_per_bar"] != count:
            bars.append({"beat": len(beats), "beats_per_bar": count})
        beats.extend(round((start_q + i * unit) * q_sec, 6) for i in range(count))
    end_q = sum(m[1] for m in layout[-1:]) + (layout[-1][0] if layout else 0)
    unit = 4 / (layout[-1][3] if layout else 4)
    beats.extend(round((end_q + i * unit) * q_sec, 6) for i in range(4))

    out = []
    for n in sorted(notes, key=lambda n: (n["start_q"], n["midi"])):
        o = {
            "midi": n["midi"],
            "start": round(max(0.0, n["start_q"]) * q_sec, 4),
            "end": round(n["end_q"] * q_sec, 4),
            "velocity": n["velocity"],
            "staff": n["staff"],
            "measure": n["measure"],
        }
        if n.get("finger"):
            o["finger"] = n["finger"]
        if "onset_q" in n:
            o["onset_q"] = n["onset_q"]
        if n.get("grace"):
            o["grace"] = True
        for k in ("trill", "fermata"):
            if n.get(k):
                o[k] = n[k]
        out.append(o)
    return Score(
        notes=out,
        beats=beats,
        bars=bars,
        bpm=bpm,
        fifths=fifths,
        mode=mode,
        measures=len(layout),
        missing_measures=missing,
        title=title,
    )
