"""Seconds <-> score position, against the song's real beats.

Quantizing to a constant BPM drifts as soon as a human player speeds up or
slows down, which is what makes most audio-to-score conversions unreadable.
StemDeck already tracked every beat and downbeat (stems/beats.json, see
app/pipeline/beatgrid.py), so a note's position is taken *between the two
beats around it*: tempo changes are absorbed beat by beat.

A beat is a quarter note and is divided into TPB ticks. 12 is the least common
multiple of 4 (sixteenths) and 3 (eighth-note triplets).
"""

from __future__ import annotations

import bisect
from dataclasses import dataclass

TPB = 12
MAX_BEATS = 20000


@dataclass(frozen=True)
class Measure:
    start_beat: int  # index into TimeGrid.beats
    n_beats: int  # beats actually in this measure (less than meter for a pickup)
    meter: int  # beats per bar of the time signature in force


METERS = ("auto", "detected", "2", "3", "4", "6")


def _downbeat_times(beats: list[float], bars: list[dict] | None) -> list[float]:
    """Downbeat times the tracker reported (beats.json "bars": runs of
    {"beat": index, "beats_per_bar": n}). Two runs at one beat (the tracker
    can emit both) keep the later one."""
    runs: dict[int, int] = {}
    for bar in bars or []:
        try:
            idx, n = int(bar["beat"]), int(bar["beats_per_bar"])
        except (KeyError, TypeError, ValueError):
            continue
        if 0 <= idx < len(beats) and 1 <= n <= 16:
            runs[idx] = n
    starts = sorted(runs)
    out = []
    for i, idx in enumerate(starts):
        stop = starts[i + 1] if i + 1 < len(starts) else len(beats)
        out += [beats[j] for j in range(idx, stop, runs[idx])]
    return out


def regularize(beats: list[float]) -> tuple[list[float], int]:
    """Split intervals that span whole multiples of the typical beat.

    The tracker extrapolates through drum-free passages, and there it can
    land on every other beat: on a 9-minute song 212 of 879 intervals were
    1.0 s in a 0.5 s (119 BPM) grid, which quantized those passages against
    half notes. An interval within 20 % of k typical beats (k >= 2) becomes k
    beats. Returns (beats, beats inserted).
    """
    if len(beats) < 3:
        return list(beats), 0
    intervals = sorted(b - a for a, b in zip(beats, beats[1:], strict=False))
    typical = intervals[len(intervals) // 2]
    if typical <= 0:
        return list(beats), 0
    out = [beats[0]]
    added = 0
    for a, b in zip(beats, beats[1:], strict=False):
        k = round((b - a) / typical)
        if k >= 2 and abs((b - a) / k - typical) < 0.2 * typical:
            out += [a + (b - a) * j / k for j in range(1, k)]
            added += k - 1
        out.append(b)
    return out, added


def bass_salience(beats: list[float], notes: list[dict]) -> dict[int, tuple[float, int]]:
    """For bars of 2, 3 and 4 beats: (how much lower, in semitones, the
    lowest note on the bar's first beat is than on its other beats, best
    phase). In a waltz the "oom" of oom-pah-pah is the low one; counting all
    low notes is not enough, the "pah"s are low too. Measured: a waltz +2.9 for
    3 against +0.7 for 4; pieces in 4/4 +3.4 to +19.6 for 2 or 4 and at most
    +7.3 for 3 (that one a 4/4 whose bass moves in halves).
    """
    if len(beats) < 8:
        return {}
    lows: dict[int, int] = {}
    for n in notes:
        i = bisect.bisect_left(beats, n["start"])
        for j in (i - 1, i):
            if (
                0 <= j < len(beats) - 1
                and abs(n["start"] - beats[j]) < (beats[j + 1] - beats[j]) / 6
            ):
                lows[j] = min(lows.get(j, 128), n["midi"])
    out: dict[int, tuple[float, int]] = {}
    for m in (2, 3, 4):
        best = (float("-inf"), 0)
        for p in range(m):
            down = [v for j, v in lows.items() if (j - p) % m == 0]
            other = [v for j, v in lows.items() if (j - p) % m != 0]
            if len(down) >= 4 and len(other) >= 4:
                lift = sum(other) / len(other) - sum(down) / len(down)
                best = max(best, (lift, p))
        if best[0] != float("-inf"):
            out[m] = (round(best[0], 2), best[1])
    return out


def _meter_from_bass(salience: dict[int, tuple[float, int]]) -> int | None:
    """3 or 4 when the lowest notes say so clearly (1.5 semitones apart),
    else None and the tracker's bars decide."""
    if 3 not in salience or not (2 in salience or 4 in salience):
        return None
    triple = salience[3][0]
    duple = max(salience.get(2, (float("-inf"), 0))[0], salience.get(4, (float("-inf"), 0))[0])
    if triple >= duple + 1.5 and triple >= 1.5:
        return 3
    if duple >= triple + 1.5 and duple >= 1.5:
        return 4
    return None


class TimeGrid:
    def __init__(
        self,
        beats: list[float] | None,
        bars: list[dict] | None,
        *,
        t_min: float = 0.0,
        t_max: float = 0.0,
        bpm: float | None = None,
        tempo: str = "normal",
        meter: str = "auto",
        bar_shift: int = 0,
        notes: list[dict] | None = None,
        downbeat_times: list[float] | None = None,
    ) -> None:
        clean = sorted(float(b) for b in (beats or []) if isinstance(b, (int, float)) and b >= 0)
        downbeats = _downbeat_times(clean, bars) + list(downbeat_times or [])
        clean, self.regularized = regularize(clean)

        if tempo == "half" and len(clean) >= 4:
            clean = clean[::2]
        elif tempo == "double" and len(clean) >= 2:
            doubled = []
            for a, b in zip(clean, clean[1:], strict=False):
                doubled += [a, (a + b) / 2]
            doubled.append(clean[-1])
            clean = doubled

        if len(clean) < 2:
            step = 60.0 / (bpm if bpm and 20 <= bpm <= 300 else 120.0)
            clean = [0.0, step]

        # Extend the grid so every note has a beat on each side.
        k = 0
        first = clean[1] - clean[0]
        while clean[0] > t_min and len(clean) < MAX_BEATS:
            clean.insert(0, clean[0] - first)
            k += 1
        last = clean[-1] - clean[-2]
        while clean[-1] <= t_max + last and len(clean) < MAX_BEATS:
            clean.append(clean[-1] + last)

        self.beats = clean
        self.offset = k  # beats prepended before the tracker's first beat
        marks = sorted({self.nearest_beat(t) for t in downbeats})
        self.salience = bass_salience(clean, notes) if notes else {}
        segs, self.meter_source = self._meter(marks, meter, bar_shift, k, self.salience)
        self.measures = self._measures(segs, len(clean) - 1)
        self._measure_starts = [m.start_beat for m in self.measures]

    def nearest_beat(self, t: float) -> int:
        b = self.beats
        i = bisect.bisect_left(b, t)
        if i <= 0:
            return 0
        if i >= len(b):
            return len(b) - 1
        return i if b[i] - t < t - b[i - 1] else i - 1

    @staticmethod
    def _meter(
        marks: list[int],
        meter: str,
        bar_shift: int,
        offset: int,
        salience: dict[int, tuple[float, int]] | None = None,
    ) -> tuple[list[tuple[int, int]], str]:
        """Bar runs [(start beat, beats per bar)] and where they came from.

        "detected": the tracker's downbeats as they are, bar lengths and all.
        "auto": one meter for the whole song -- the tracker's most common bar
        length, with 2 and 8 read as 4 and 6 as 3 (the same pulse grouped
        differently; flipping 4/4 to 2/4 mid-song made the score unreadable)
        -- placed where most of its downbeats agree. "2"/"3"/"4"/"6": that
        meter, placed the same way. bar_shift moves the barlines by beats.
        """
        if meter == "detected" and len(marks) >= 2:
            segs: list[tuple[int, int]] = []
            for a, b in zip(marks, marks[1:], strict=False):
                n = max(1, min(16, b - a))
                if not segs or segs[-1][1] != n:
                    segs.append((a, n))
            return segs, "detected"
        notes_meter = _meter_from_bass(salience or {})
        if meter in ("2", "3", "4", "6"):
            m, source = int(meter), "manual"
        elif meter == "auto" and notes_meter:
            m, source = notes_meter, "notes"
        else:
            weights: dict[int, int] = {}
            for a, b in zip(marks, marks[1:], strict=False):
                n = {2: 4, 8: 4, 6: 3}.get(b - a, b - a)
                if n in (3, 4):
                    weights[n] = weights.get(n, 0) + (b - a)
            m = max(weights, key=weights.get) if weights else 4
            source = "auto" if weights else "default"
        votes = [0] * m
        for idx in marks:
            votes[idx % m] += 1
        if marks and max(votes) > 0:
            phase = max(range(m), key=lambda p: (votes[p], -p))
        elif salience and m in salience:
            phase = salience[m][1]  # no tracker downbeats: where the lowest notes fall
        else:
            phase = offset % m
        phase = (phase + bar_shift) % m
        return [(phase, m)], source

    @staticmethod
    def _measures(segs: list[tuple[int, int]], n_intervals: int) -> list[Measure]:
        first_start, first_meter = segs[0]
        pre: list[Measure] = []
        pos = first_start
        while pos > 0:
            start = max(0, pos - first_meter)
            pre.append(Measure(start, pos - start, first_meter))
            pos = start
        measures = list(reversed(pre))
        for i, (start, meter) in enumerate(segs):
            end = segs[i + 1][0] if i + 1 < len(segs) else n_intervals
            pos = start
            while pos < end:
                length = min(meter, end - pos)
                measures.append(Measure(pos, length, meter))
                pos += length
        return measures

    # -- conversions -----------------------------------------------------

    def locate(self, t: float) -> tuple[int, float]:
        """(beat index, fraction 0..1 of the way to the next beat)."""
        b = self.beats
        idx = min(max(bisect.bisect_right(b, t) - 1, 0), len(b) - 2)
        span = b[idx + 1] - b[idx]
        return idx, (t - b[idx]) / span if span > 0 else 0.0

    def sec_at(self, tick: int | float) -> float:
        b = self.beats
        j = int(tick // TPB)
        frac = (tick - j * TPB) / TPB
        if j >= len(b) - 1:
            span = b[-1] - b[-2]
            return b[-1] + (tick / TPB - (len(b) - 1)) * span
        if j < 0:
            return b[0] + (tick / TPB) * (b[1] - b[0])
        return b[j] + frac * (b[j + 1] - b[j])

    def beat_sec(self, beat: int) -> float:
        return self.sec_at(beat * TPB)

    def measure_index_at_beat(self, beat: int) -> int:
        return max(0, bisect.bisect_right(self._measure_starts, beat) - 1)

    def bpm_at(self, beat: int) -> float:
        b = self.beats
        j = min(max(beat, 0), len(b) - 2)
        span = b[j + 1] - b[j]
        return 60.0 / span if span > 0 else 0.0
