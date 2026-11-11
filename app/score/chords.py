"""Chord symbols from the transcribed notes.

The song is cut into windows on the beat grid (a beat, half a bar or a bar).
In each window every sounding note adds its overlap time, weighted a little by
velocity, to its pitch class. The 12-bin profile is matched against chord
templates; the lowest clearly-sounding note is the bass, and a bass that is
not the root gives a slash chord ("La/Mi"). Only changes are labelled.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.score.keys import Key, spell_name, spelling_table
from app.score.timegrid import TimeGrid

# quality -> (intervals, complexity penalty, solfege/letter suffix)
QUALITIES: dict[str, tuple[tuple[int, ...], float, str]] = {
    "maj": ((0, 4, 7), 0.0, ""),
    "min": ((0, 3, 7), 0.0, "m"),
    "7": ((0, 4, 7, 10), 0.05, "7"),
    "maj7": ((0, 4, 7, 11), 0.06, "maj7"),
    "m7": ((0, 3, 7, 10), 0.05, "m7"),
    "dim": ((0, 3, 6), 0.04, "dim"),
    "aug": ((0, 4, 8), 0.06, "aug"),
    "sus4": ((0, 5, 7), 0.05, "sus4"),
    "sus2": ((0, 2, 7), 0.06, "sus2"),
    "m7b5": ((0, 3, 6, 10), 0.07, "m7♭5"),
}
MIN_WEIGHT = 0.12  # seconds of weighted sound a window needs to get a chord


@dataclass
class Chord:
    time: float  # window start, seconds
    beat: int  # grid beat index of the window start
    root: int
    quality: str
    bass: int
    score: float

    def same(self, other: Chord | None) -> bool:
        return other is not None and (self.root, self.quality, self.bass) == (
            other.root,
            other.quality,
            other.bass,
        )


# Spellings that name another key than the one played: a chord on the key B
# in E-flat minor read "Dob" and was taken for C. Named by the key that sounds.
_PLAIN = {("C", -1): ("B", 0), ("F", -1): ("E", 0), ("E", 1): ("F", 0), ("B", 1): ("C", 0)}


def _plain(letter: str, alter: int) -> tuple[str, int]:
    return _PLAIN.get((letter, alter), (letter, alter))


def chord_name(root: int, quality: str, bass: int, key: Key, *, solfege: bool = True) -> str:
    table = spelling_table(key)
    name = spell_name(*_plain(*table[root]), solfege=solfege, capital=True) + QUALITIES[quality][2]
    if bass != root:
        name += "/" + spell_name(*_plain(*table[bass]), solfege=solfege, capital=True)
    return name


def _windows(grid: TimeGrid, rate: str) -> list[tuple[int, int, int]]:
    """(start beat, end beat, measure index) per window."""
    out = []
    for mi, m in enumerate(grid.measures):
        if rate == "beat":
            size = 1
        elif rate == "bar":
            size = m.n_beats
        else:
            size = m.meter // 2 if m.meter % 2 == 0 and m.meter >= 4 else m.meter
        size = max(1, size)
        b = m.start_beat
        end = m.start_beat + m.n_beats
        while b < end:
            out.append((b, min(end, b + size), mi))
            b += size
    return out


def classify(profile: list[float], bass_pc: int | None, prev: Chord | None = None):
    total = sum(profile)
    if total <= 0:
        return None
    v = [x / total for x in profile]
    best = None
    for root in range(12):
        if v[root] < 0.04:
            continue
        for quality, (intervals, penalty, _) in QUALITIES.items():
            pcs = {(root + i) % 12 for i in intervals}
            inside = sum(v[pc] for pc in pcs)
            outside = 1.0 - inside
            # Every chord tone should be heard a little; a missing fifth is
            # forgiven, a missing third is not.
            missing = sum(1 for i in intervals if v[(root + i) % 12] < 0.02 and i != 7)
            if len(intervals) == 4:
                # A seventh has to be part of the harmony, not a passing note
                # of the melody: weigh it against the weakest triad tone.
                heard = [v[(root + i) % 12] for i in intervals[:3] if v[(root + i) % 12] >= 0.02]
                if not heard or v[(root + intervals[3]) % 12] < 0.35 * min(heard):
                    continue
            score = inside - 0.6 * outside - penalty - 0.25 * missing
            if bass_pc == root:
                score += 0.08
            if prev is not None and (root, quality) == (prev.root, prev.quality):
                score += 0.04  # hysteresis: do not flicker between near-equal readings
            if best is None or score > best[0]:
                best = (score, root, quality)
    return best


# Within one bar, two readings with the same root where one only adds a
# seventh, or one is a suspension of the other, are one chord heard through a
# melody's passing notes: keep the richer reading.
_MERGE_INTO = {
    frozenset(("maj", "7")): "7",
    frozenset(("maj", "maj7")): "maj7",
    frozenset(("min", "m7")): "m7",
    frozenset(("maj", "sus2")): "maj",
    frozenset(("maj", "sus4")): "maj",
    frozenset(("min", "sus2")): "min",
    frozenset(("min", "sus4")): "min",
    frozenset(("7", "sus4")): "7",
}


def _merge_in_bars(readings: list[tuple[int, Chord | None]]) -> list[Chord | None]:
    out = [c for _, c in readings]
    for i in range(1, len(readings)):
        (m_prev, a), (m_cur, b) = readings[i - 1], readings[i]
        a = out[i - 1]
        if a is None or b is None or m_prev != m_cur or a.root != b.root or a.quality == b.quality:
            continue
        merged = _MERGE_INTO.get(frozenset((a.quality, b.quality)))
        if merged is None:
            continue
        intervals = QUALITIES[merged][0]
        bass = a.bass if (a.bass - a.root) % 12 in intervals else a.root
        unified = Chord(a.time, a.beat, a.root, merged, bass, max(a.score, b.score))
        out[i - 1] = unified
        out[i] = Chord(b.time, b.beat, a.root, merged, bass, unified.score)
        # Carry the unified reading back over earlier windows of the bar.
        k = i - 2
        while k >= 0 and readings[k][0] == m_cur and out[k] is not None and out[k].root == a.root:
            out[k] = Chord(out[k].time, out[k].beat, a.root, merged, bass, unified.score)
            k -= 1
    return out


def detect(notes: list[dict], grid: TimeGrid, rate: str = "half") -> list[Chord]:
    if not notes:
        return []
    ordered = sorted(notes, key=lambda n: n["start"])
    readings: list[tuple[int, Chord | None]] = []
    prev: Chord | None = None
    first = ordered[0]["start"]
    last = max(n["end"] for n in ordered)
    lo = 0
    for b0, b1, mi in _windows(grid, rate):
        t0, t1 = grid.beat_sec(b0), grid.beat_sec(b1)
        if t1 <= first or t0 >= last:
            continue
        # Sorted by start, so only notes that began over 30 s ago can be
        # skipped for good; none of the transcribed notes is held that long.
        while lo < len(ordered) and ordered[lo]["start"] < t0 - 30:
            lo += 1
        profile = [0.0] * 12
        overlaps = []
        for n in ordered[lo:]:
            if n["start"] >= t1:
                break
            ov = min(n["end"], t1) - max(n["start"], t0)
            if ov <= 0:
                continue
            w = ov * (0.4 + 0.6 * n.get("velocity", 80) / 127)
            profile[n["midi"] % 12] += w
            overlaps.append((n["midi"], ov))
        weight = sum(profile)
        if weight < MIN_WEIGHT:
            prev = None
            readings.append((mi, None))
            continue
        longest = max(ov for _, ov in overlaps)
        bass_midi = min(m for m, ov in overlaps if ov >= 0.3 * longest)
        bass_pc = bass_midi % 12
        best = classify(profile, bass_pc, prev)
        if best is None:
            prev = None
            readings.append((mi, None))
            continue
        score, root, quality = best
        intervals = QUALITIES[quality][0]
        bass = bass_pc if (bass_pc - root) % 12 in intervals else root
        prev = Chord(round(t0, 4), b0, root, quality, bass, round(score, 3))
        readings.append((mi, prev))
    chords: list[Chord] = []
    last_chord: Chord | None = None
    for chord in _merge_in_bars(readings):
        if chord is not None and not chord.same(last_chord):
            chords.append(chord)
        last_chord = chord
    return chords
