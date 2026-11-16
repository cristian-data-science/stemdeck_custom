"""Notes in seconds -> an engraved piano score (measures, staves, items).

Pure and deterministic: the same notes, beat grid, key and settings always
give the same score, which is what makes it testable without a model or a
browser (tests/test_score_engrave.py).

Pipeline:
  1. choose each beat's subdivision (2, 4, or 3 for triplets)
  2. snap every onset/offset to its beat's grid -> ticks (timegrid.TPB per beat)
  3. assign a staff: treble (1) or bass (2), by the split point or the note's
     own hand override from an edit
  4. per staff, notes with the same onset become one chord; v1 has one voice
     per staff, so a chord lasts until the next onset on that staff
  5. cut events at barlines and beats into notatable values, tied
  6. beam per beat, spell, and write accidentals with measure persistence
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field

from app.score.hands import assign_hands
from app.score.keys import LETTER_PC, LETTERS, Key, key_from_id, spell_midi, spelling_table
from app.score.timegrid import METERS, TPB, TimeGrid

GRIDS = ("8", "16", "16t")
STAFF_TREBLE = 1
STAFF_BASS = 2


@dataclass
class Settings:
    grid: str = "16t"
    split: int = 60  # MIDI note from which a note goes to the treble staff
    tempo: str = "normal"  # "normal" | "half" | "double" (beat-grid override)
    chord_rate: str = "half"  # "beat" | "half" | "bar"
    chords: bool = True
    meter: str = "auto"  # timegrid.METERS
    bar_shift: int = 0  # move barlines by this many beats
    key: str = "auto"  # "auto" (from the notes) | "song" (separation's analysis) | "pc:mode"
    hands: str = "auto"  # "auto" (follow each hand, hands.py) | "split" (fixed split point)
    pulse: str = (
        "auto"  # "auto" | "song" (the song's beat grid) | "audio" (tracked on this score's audio)
    )
    pedal: int = 0  # % of the sustain pedal heard in playback (pedal.py); not drawn

    @classmethod
    def from_dict(cls, data: dict | None) -> Settings:
        data = data or {}
        s = cls()
        if data.get("grid") in GRIDS:
            s.grid = data["grid"]
        if isinstance(data.get("split"), int) and 36 <= data["split"] <= 84:
            s.split = data["split"]
        if data.get("tempo") in ("normal", "half", "double"):
            s.tempo = data["tempo"]
        if data.get("chord_rate") in ("beat", "half", "bar"):
            s.chord_rate = data["chord_rate"]
        if isinstance(data.get("chords"), bool):
            s.chords = data["chords"]
        if data.get("hands") in ("auto", "split"):
            s.hands = data["hands"]
        if data.get("pulse") in ("auto", "song", "audio", "notes"):
            s.pulse = data["pulse"]
        if data.get("meter") in METERS:
            s.meter = data["meter"]
        if isinstance(data.get("bar_shift"), int) and 0 <= data["bar_shift"] < 16:
            s.bar_shift = data["bar_shift"]
        if isinstance(data.get("pedal"), int) and 0 <= data["pedal"] <= 100:
            s.pedal = data["pedal"]
        if isinstance(data.get("key"), str) and (
            data["key"] in ("auto", "song") or key_from_id(data["key"])
        ):
            s.key = data["key"]
        return s

    def to_dict(self) -> dict:
        return {
            "grid": self.grid,
            "split": self.split,
            "tempo": self.tempo,
            "chord_rate": self.chord_rate,
            "chords": self.chords,
            "meter": self.meter,
            "bar_shift": self.bar_shift,
            "key": self.key,
            "pulse": self.pulse,
            "hands": self.hands,
            "pedal": self.pedal,
        }


@dataclass
class Head:
    """One notehead as drawn. A note cut by a barline is several heads."""

    xml_id: str
    note_id: str
    midi: int
    letter: str
    alter: int
    octave: int
    tie: str | None = None  # "i" | "m" | "t"
    accid: int | None = None  # written accidental (0 = natural), None = none
    accid_ges: int = 0


@dataclass
class Item:
    kind: str  # "chord" | "rest" | "mrest"
    tick: int
    ticks: int
    dur: int  # 1 2 4 8 16 (MEI/MusicXML note value)
    dots: int = 0
    tuplet: int | None = None  # beat index of the triplet this item belongs to
    heads: list[Head] = field(default_factory=list)
    beam: int | None = None  # beam group number within the measure
    xml_id: str = ""


@dataclass
class EMeasure:
    number: int
    start_tick: int
    end_tick: int
    meter: int
    n_beats: int
    start_sec: float
    end_sec: float
    staves: dict[int, list[Item]] = field(default_factory=dict)
    meter_change: bool = False


@dataclass
class Engraved:
    measures: list[EMeasure]
    notes: dict[str, dict]  # note id -> placement info for the page
    subdiv: list[int]
    grid: TimeGrid
    key: Key
    key_info: dict = field(default_factory=dict)
    pulse_info: dict = field(default_factory=dict)


# -- quantization -------------------------------------------------------------


def _subdivisions(grid: TimeGrid, notes: list[dict], mode: str) -> list[int]:
    n = len(grid.beats)
    base = {"8": 2, "16": 4, "16t": 4}[mode]
    subdiv = [base] * n
    if mode != "16t":
        return subdiv
    fracs: dict[int, list[float]] = defaultdict(list)
    for note in notes:
        idx, frac = grid.locate(note["start"])
        if frac > 0.92:  # rounds onto the next beat: says nothing about this one
            continue
        fracs[idx].append(frac)
    for idx, fs in fracs.items():
        e4 = sum(abs(f * 4 - round(f * 4)) / 4 for f in fs)
        e3 = sum(abs(f * 3 - round(f * 3)) / 3 for f in fs)
        uses_third = any(round(f * 3) in (1, 2) for f in fs)
        if uses_third and e3 < 0.6 * e4:
            subdiv[idx] = 3
    return subdiv


def _snap(grid: TimeGrid, subdiv: list[int], t: float) -> int:
    idx, frac = grid.locate(t)
    d = subdiv[idx]
    pos = round(max(0.0, min(1.0, frac)) * d)
    return idx * TPB + pos * (TPB // d)


def quantize(notes: list[dict], grid: TimeGrid, settings: Settings) -> tuple[list[dict], list[int]]:
    """Each note gains on/off ticks and its staff. Returns (notes, subdiv)."""
    subdiv = _subdivisions(grid, notes, settings.grid)
    hands = assign_hands(notes, settings.split) if settings.hands == "auto" else {}
    out = []
    for note in notes:
        on = _snap(grid, subdiv, note["start"])
        step = TPB // subdiv[min(on // TPB, len(subdiv) - 1)]
        off = _snap(grid, subdiv, note["end"])
        if off <= on:
            off = on + step
        hand = note.get("hand")
        if hand == "R":
            staff = STAFF_TREBLE
        elif hand == "L":
            staff = STAFF_BASS
        elif note["id"] in hands:
            staff = STAFF_TREBLE if hands[note["id"]] == "R" else STAFF_BASS
        else:
            staff = STAFF_TREBLE if note["midi"] >= settings.split else STAFF_BASS
        out.append({**note, "on": on, "off": off, "staff": staff, "step": step})
    return out, subdiv


# -- note values -------------------------------------------------------------

_BINARY = {3: (16, 0), 6: (8, 0), 9: (8, 1), 12: (4, 0)}
_TERNARY = {4: (8, 0), 8: (4, 0)}
_WHOLE_BEATS = ((4, 1, 0), (3, 2, 1), (2, 2, 0), (1, 4, 0))


def decompose(a: int, b: int, subdiv: list[int]) -> list[tuple[int, int, int, int, int | None]]:
    """Cut [a, b) ticks into notatable values: (tick, ticks, dur, dots, tuplet).

    Whole beats from a beat boundary take the largest value that fits (whole,
    dotted half, half, quarter, and a dotted quarter when the half beat after
    it is binary). Anything inside a beat is one value of that beat's grid; in
    a triplet beat it belongs to that beat's tuplet.
    """
    out = []
    pos = a
    while pos < b:
        beat, off = divmod(pos, TPB)
        if off == 0 and b - pos >= TPB:
            whole = (b - pos) // TPB
            nxt = subdiv[beat + 1] if beat + 1 < len(subdiv) else 4
            if whole == 1 and b - pos == TPB + TPB // 2 and nxt in (2, 4):
                out.append((pos, TPB + TPB // 2, 4, 1, None))
                pos += TPB + TPB // 2
                continue
            for beats, dur, dots in _WHOLE_BEATS:
                if whole >= beats:
                    out.append((pos, beats * TPB, dur, dots, None))
                    pos += beats * TPB
                    break
            continue
        end = min(b, (beat + 1) * TPB)
        length = end - pos
        d = subdiv[beat] if beat < len(subdiv) else 4
        table, unit = (_TERNARY, 4) if d == 3 else (_BINARY, 3)
        if length in table:
            dur, dots = table[length]
            out.append((pos, length, dur, dots, beat if d == 3 else None))
            pos = end
        else:  # off-grid remainder: fall back to the beat's smallest unit
            step = min(unit, length)
            dur, dots = table.get(step, (16, 0))
            out.append((pos, step, dur, dots, beat if d == 3 else None))
            pos += step
    return out


# -- engraving ---------------------------------------------------------------


def _events(
    staff_notes: list[dict], duplicates: dict[str, str]
) -> list[tuple[int, int, list[dict]]]:
    """Chords per onset. The same pitch twice at one onset is one notehead:
    the others are recorded in `duplicates` (id -> the id drawn), since two
    heads on one line cannot be read and break tie matching."""
    by_on: dict[int, list[dict]] = defaultdict(list)
    for n in staff_notes:
        by_on[n["on"]].append(n)
    onsets = sorted(by_on)
    events = []
    for i, on in enumerate(onsets):
        group = []
        drawn: dict[int, dict] = {}
        for n in sorted(by_on[on], key=lambda n: (n["midi"], -(n["off"] - n["on"]), n["id"])):
            if n["midi"] in drawn:
                duplicates[n["id"]] = drawn[n["midi"]]["id"]
                continue
            drawn[n["midi"]] = n
            group.append(n)
        end = max(n["off"] for n in group)
        if i + 1 < len(onsets):
            end = min(end, onsets[i + 1])
        events.append((on, end, group))
    return events


def _respell_cluster(
    spelled: list[tuple[str, int, int]], midis: list[int]
) -> list[tuple[str, int, int]]:
    """Two notes of one chord on the same letter (E-flat with E-natural) would
    share a line. Move one to the neighbouring letter (D-sharp), the lower one
    down when it can, else the upper one up."""
    out = list(spelled)
    for i in range(len(out) - 1):
        (l1, _, o1), (l2, _, o2) = out[i], out[i + 1]
        if (l1, o1) != (l2, o2):
            continue
        for j, step in ((i, -1), (i + 1, 1)):
            letter, _, octave = out[j]
            k = LETTERS.index(letter) + step
            new_oct = octave + (k // 7)
            new_letter = LETTERS[k % 7]
            alter = midis[j] - (12 * (new_oct + 1) + LETTER_PC[new_letter])
            if abs(alter) <= 1 and (new_letter, new_oct) not in {(x[0], x[2]) for x in out}:
                out[j] = (new_letter, alter, new_oct)
                break
    return out


def engrave(
    notes: list[dict],
    beats: list[float] | None,
    bars: list[dict] | None,
    key: Key,
    settings: Settings,
    *,
    bpm: float | None = None,
    downbeat_times: list[float] | None = None,
) -> Engraved:
    t_min = min((n["start"] for n in notes), default=0.0)
    t_max = max((n["end"] for n in notes), default=0.0)
    grid = TimeGrid(
        beats,
        bars,
        t_min=t_min,
        t_max=t_max,
        bpm=bpm,
        tempo=settings.tempo,
        meter=settings.meter,
        bar_shift=settings.bar_shift,
        notes=notes,
        downbeat_times=downbeat_times,
    )
    qnotes, subdiv = quantize(notes, grid, settings)
    table = spelling_table(key)

    # Measures that hold music; leading and trailing silence is dropped.
    all_measures = grid.measures
    if qnotes:
        first_tick = min(n["on"] for n in qnotes)
        last_tick = max(n["off"] for n in qnotes)
        first_m = grid.measure_index_at_beat(first_tick // TPB)
        last_m = grid.measure_index_at_beat((last_tick - 1) // TPB)
        chosen = all_measures[first_m : last_m + 1]
    else:
        chosen = all_measures[grid.measure_index_at_beat(grid.offset) :][:1]

    measures: list[EMeasure] = []
    prev_meter = None
    for i, m in enumerate(chosen):
        start = m.start_beat * TPB
        end = (m.start_beat + m.n_beats) * TPB
        em = EMeasure(
            number=i + 1,
            start_tick=start,
            end_tick=end,
            meter=m.meter,
            n_beats=m.n_beats,
            start_sec=round(grid.sec_at(start), 4),
            end_sec=round(grid.sec_at(end), 4),
            meter_change=prev_meter is not None and m.meter != prev_meter,
        )
        prev_meter = m.meter
        measures.append(em)

    info: dict[str, dict] = {}
    duplicates: dict[str, str] = {}
    for staff in (STAFF_TREBLE, STAFF_BASS):
        staff_notes = [n for n in qnotes if n["staff"] == staff]
        events = _events(staff_notes, duplicates)
        _fill_staff(measures, staff, events, subdiv, table, key, info)

    for n in qnotes:
        placed = info.get(n["id"], {})
        letter, alter, octave = placed.get("spelled") or spell_midi(n["midi"], table)
        twin = info.get(duplicates.get(n["id"], ""), {})
        drawn_off = placed.get("drawn_off") or twin.get("drawn_off") or n["off"]
        info[n["id"]] = {
            "staff": n["staff"],
            "on": n["on"],
            "off": n["off"],
            "q_start": round(grid.sec_at(n["on"]), 4),
            "q_end": round(grid.sec_at(n["off"]), 4),
            # What sounds, lights up and is exported: the note as drawn. One
            # voice per staff cuts a held note at the next onset; the piano
            # model also caps a note whose release it never heard at 6 s, and
            # 222 such tails on a 9-minute song sounded on for bars under
            # notes drawn as half notes.
            "draw_off": drawn_off,
            "draw_end": round(grid.sec_at(drawn_off), 4),
            "step_sec": round(grid.sec_at(n["on"] + n["step"]) - grid.sec_at(n["on"]), 4),
            "letter": letter,
            "alter": alter,
            "octave": octave,
            "measure": placed.get("measure"),
            "heads": placed.get("heads", []),
            "duplicate_of": duplicates.get(n["id"]),
        }
    return Engraved(measures, info, subdiv, grid, key)


def _fill_staff(measures, staff, events, subdiv, table, key, info) -> None:
    sig = key.signature
    ev_i = 0
    for m in measures:
        items: list[Item] = []
        pos = m.start_tick
        # Skip events that ended before this measure.
        while ev_i < len(events) and events[ev_i][1] <= m.start_tick:
            ev_i += 1
        j = ev_i
        while pos < m.end_tick:
            if j < len(events) and events[j][0] < m.end_tick and events[j][1] > pos:
                on, off, group = events[j]
                if on > pos:
                    items += _rests(pos, on, subdiv)
                    pos = on
                    continue
                seg_end = min(off, m.end_tick)
                pieces = decompose(pos, seg_end, subdiv)
                spelled = _respell_cluster(
                    [spell_midi(n["midi"], table) for n in group], [n["midi"] for n in group]
                )
                for p_i, (tick, ticks, dur, dots, tup) in enumerate(pieces):
                    first_piece = pos == on and p_i == 0
                    last_piece = seg_end == off and p_i == len(pieces) - 1
                    heads = []
                    for n, (letter, alter, octave) in zip(group, spelled, strict=True):
                        if first_piece and last_piece:
                            tie = None
                        elif first_piece:
                            tie = "i"
                        elif last_piece:
                            tie = "t"
                        else:
                            tie = "m"
                        record = info.setdefault(
                            n["id"],
                            {
                                "measure": m.number,
                                "heads": [],
                                "spelled": (letter, alter, octave),
                                # Where the note's bar ends (falling notes,
                                # lit key, export): its own end, cut at the
                                # next onset on this staff. Not the chord's
                                # end: a staccato note struck with a long bass
                                # (moved to the left hand) took the bass's
                                # length. The score still draws the chord with
                                # one duration (one voice per staff).
                                "drawn_off": min(off, n["off"]),
                            },
                        )
                        xml_id = (
                            n["id"] if not record["heads"] else f"{n['id']}-{len(record['heads'])}"
                        )
                        record["heads"].append(xml_id)
                        heads.append(
                            Head(xml_id, n["id"], n["midi"], letter, alter, octave, tie=tie)
                        )
                    items.append(
                        Item("chord", tick, ticks, dur, dots, tup, heads, xml_id=f"c{staff}t{tick}")
                    )
                pos = seg_end
                if seg_end >= off:
                    j += 1
            else:
                nxt = m.end_tick
                if j < len(events):
                    nxt = min(nxt, max(events[j][0], pos))
                if nxt <= pos:
                    nxt = m.end_tick
                items += _rests(pos, nxt, subdiv)
                pos = nxt
        if all(it.kind == "rest" for it in items):
            items = [Item("mrest", m.start_tick, m.end_tick - m.start_tick, 1)]
        for k, it in enumerate(items):
            if it.kind != "chord":
                it.xml_id = f"r{staff}t{it.tick}k{k}"
        _beam(items)
        _accidentals(items, sig)
        m.staves[staff] = items


def _rests(a: int, b: int, subdiv: list[int]) -> list[Item]:
    return [
        Item("rest", tick, ticks, dur, dots, tup)
        for tick, ticks, dur, dots, tup in decompose(a, b, subdiv)
    ]


def _beam(items: list[Item]) -> None:
    group = 0
    run: list[Item] = []

    def close() -> None:
        nonlocal group
        if len(run) >= 2:
            group += 1
            for it in run:
                it.beam = group
        run.clear()

    current_beat = None
    for it in items:
        beat = it.tick // TPB
        beamable = it.kind == "chord" and it.dur >= 8
        if not beamable or beat != current_beat:
            close()
        current_beat = beat
        if beamable:
            run.append(it)
    close()


def _accidentals(items: list[Item], sig: dict[str, int]) -> None:
    state: dict[tuple[str, int], int] = {}
    for it in items:
        for h in it.heads:
            slot = (h.letter, h.octave)
            current = state.get(slot, sig[h.letter])
            h.accid_ges = h.alter
            if h.tie in ("m", "t"):
                state[slot] = h.alter
                continue
            if h.alter != current:
                h.accid = h.alter
                state[slot] = h.alter
