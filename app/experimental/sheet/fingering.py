"""A finger (1 = thumb ... 5 = little finger) for every note, keeping the ones
printed on the score or set by hand.

Each hand separately, as a path through its onsets (a chord is one onset):
dynamic programming picks, for every onset, which fingers play its notes, so
that the stretches between consecutive fingers stay comfortable. Comfort per
pair of fingers comes from Parncutt et al. (1997, "An ergonomic model of
keyboard fingering for melodic fragments"): for each pair, the distance in
semitones that is relaxed, comfortable, or merely practicable. Leaps after a
long note cost less (the hand has time to move). Fixed fingers are
constraints; an impossible one (two fixed fingers that contradict) is
dropped rather than failing.

On top of the spans, the rest of Parncutt's rules (and Jacobs 2001's
refinements of them): the weak fingers (4, 5), 3 followed by 4, 4 on a black
key beside 3 on a white one, the thumb or little finger on a black key between
white ones, the thumb passing under at the same level.

Then the same figure gets the same fingers (consensus): a pass over the
result counts, for every onset, which fingers it took in each melodic
context it appears in (the keys before and after it, and whether it is
fast), and a second pass prefers the fingers a context took most often. In
"BAILE INOLVIDABLE" the run D4-C4-B3-A3 went 4-3-2-1 twelve times and 3-2-1
three, depending on a note further on; a pianist keeps one fingering for a
repeated figure. Measured on 17 songs (fast single notes whose context
repeats): 88.8 % took their context's usual finger before, 92.0 % now; against the
161 fingers printed on the Chopin nocturne, 57.8 % -> 84.5 % (the rules, the crossings); the same
finger on two different keys in a row in a fast run, 0.8 % -> 0.3 % (SAME_FINGER).

A suggestion, not an edition: it reads pitch and time only, not phrasing,
pedalling or the pianist's hand.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from itertools import combinations

# (min practicable, min comfortable, min relaxed, max relaxed, max comfortable,
#  max practicable) semitones from the lower-numbered finger to the higher one,
#  right hand (the left hand mirrors it).
SPAN = {
    (1, 2): (-5, -3, 1, 5, 8, 10),
    (1, 3): (-4, -2, 3, 7, 10, 12),
    (1, 4): (-3, -1, 5, 9, 12, 14),
    (1, 5): (-1, 1, 7, 10, 13, 15),
    (2, 3): (1, 1, 1, 2, 3, 5),
    (2, 4): (1, 1, 3, 4, 5, 7),
    (2, 5): (2, 2, 5, 6, 8, 10),
    (3, 4): (1, 1, 1, 2, 2, 4),
    (3, 5): (1, 1, 3, 4, 5, 7),
    (4, 5): (1, 1, 1, 2, 3, 5),
}
BLACK = {1, 3, 6, 8, 10}
# Notes this close together are one chord: a transcribed chord is struck over
# a few tens of milliseconds, and at 0.03 s its notes went to separate onsets
# that could take the same finger.
CHORD_SEC = 0.06
# Between onsets a stretch past what is practicable is not impossible: the
# hand moves (an arpeggio going back to its bass). Without this cap the thumb
# was used twice in a row (5-2-1-1) to avoid the "stretch" back down.
JUMP_COST = 5.0
CROSS_COST = 2.0
CROSS_TWO = 3.0  # extra for the 2 crossing the thumb (see _move_cost)
REPOSITION_SEC = 0.5  # this long between two onsets, the hand can move instead of cross
# Keys down at the same time (their bars overlap in the falling-notes view;
# the page gives each note its drawn end) must be playable together, with no
# exception: never the same finger on two keys, never the fingers in the wrong
# order (a 2 to the right of the 1 in the left hand), never wider apart than
# the pair can stretch. Each breach costs IMPOSSIBLE, so only a passage with no
# playable answer at all (more keys down than fingers) keeps one.
IMPOSSIBLE = 1000.0
# Parncutt's single-finger and succession rules (points, his scale: one per
# semitone of stretch, like pair_cost). Off with RULES = False (benchmarks).
RULES = True
WEAK = {4: 1.0, 5: 0.5}  # weak-finger rule (5 is used at the hand's edge, so less)
THREE_TO_FOUR = 1.0
FOUR_ON_BLACK = 1.0  # 3 and 4 in succession, 3 on a white key and 4 on a black one
BLACK_BETWEEN_WHITE = 2.0  # thumb / little finger on a black key next to a white one
# Consensus: passes that prefer, for each onset, the fingers its melodic
# context takes most often; PREFER is the cost of each finger that differs.
SAME_FINGER = 12.0
CONSENSUS_PASSES = 2
PREFER = 2.5  # the figure repeats with the same two onsets either side
PREFER_NEAR = 1.5  # only the onsets right beside it repeat: a weaker hint
FAST_SEC = 0.35  # a context is "fast" (no time to reposition) under this
HOLD_OVERLAP = 0.03  # bars overlapping less than this are one after the other
BUSY_SEC = 4.0  # a drawn note longer than this is the pedal: its key is free


def _black(midi: int) -> bool:
    return midi % 12 in BLACK


def pair_cost(f1: int, p1: int, f2: int, p2: int, hand: str) -> float:
    """How awkward it is to have finger f1 on p1 and f2 on p2 together or in
    succession."""
    if f1 == f2:
        # One finger on two different keys in a row: the hand lifts and lands
        # again, never done in a run. At 6 the consensus (PREFER) outweighed it
        # and a run D4-C4-B3-A3 before a drop got 4-3-2-2.
        return 0.0 if p1 == p2 else SAME_FINGER + abs(p1 - p2) * 0.3
    if f1 > f2:
        f1, p1, f2, p2 = f2, p2, f1, p1
    d = p2 - p1 if hand == "R" else p1 - p2
    min_p, min_c, min_r, max_r, max_c, max_p = SPAN[(f1, f2)]
    cost = 0.0
    if d < min_r:
        cost += min(min_r - d, min_r - min_c)
        if d < min_c:
            cost += 2 * min(min_c - d, min_c - min_p)
        if d < min_p:
            cost += 10 * (min_p - d)
    elif d > max_r:
        cost += min(d - max_r, max_c - max_r)
        if d > max_c:
            cost += 2 * min(d - max_c, max_p - max_c)
        if d > max_p:
            cost += 10 * (d - max_p)
    return cost


def _key_cost(f: int, p: int) -> float:
    """The thumb (and little finger) on a black key is awkward; the weak
    fingers cost a little wherever they go."""
    cost = WEAK.get(f, 0.0) if RULES else 0.0
    if not _black(p):
        return cost
    # the thumb is short: on a black key it twists the hand
    return cost + (1.6 if f == 1 else 0.5 if f == 5 else 0.0)


def _succession_cost(f1: int, p1: int, f2: int, p2: int) -> float:
    """Parncutt's rules on two fingers in a row (one hand, single notes)."""
    if not RULES or f1 == f2:
        return 0.0
    cost = 0.0
    if f1 == 3 and f2 == 4:
        cost += THREE_TO_FOUR
    if {f1, f2} == {3, 4}:
        three, four = (p1, p2) if f1 == 3 else (p2, p1)
        if not _black(three) and _black(four):
            cost += FOUR_ON_BLACK
    # The thumb or the little finger on a black key, with a white key before
    # or after it: the hand has to move in and out for it.
    if f2 in (1, 5) and _black(p2) and not _black(p1):
        cost += BLACK_BETWEEN_WHITE
    if f1 in (1, 5) and _black(p1) and not _black(p2):
        cost += BLACK_BETWEEN_WHITE
    return cost


def _onsets(notes: list[dict]) -> list[list[dict]]:
    ordered = sorted(notes, key=lambda n: (n["start"], n["midi"]))
    groups: list[list[dict]] = []
    for n in ordered:
        if groups and n["start"] - groups[-1][0]["start"] <= CHORD_SEC:
            groups[-1].append(n)
        else:
            groups.append([n])
    # Low to high inside each chord: the fingers of a candidate are matched to
    # its notes in that order (by start time, a chord struck top first got its
    # fingers upside down: 2 on B4 and 1 on D5).
    return [sorted(g, key=lambda n: n["midi"]) for g in groups]


def _candidates(group: list[dict], hand: str, fixed: dict[str, int]) -> list[tuple[int, ...]]:
    """Ways to finger an onset: its notes low to high get rising fingers in
    the right hand, falling ones in the left; at most five notes."""
    k = min(len(group), 5)
    out = []
    for combo in combinations(range(1, 6), k):
        fingers = combo if hand == "R" else tuple(reversed(combo))
        ok = all(fixed.get(n["id"]) in (None, f) for n, f in zip(group, fingers, strict=False))
        if ok:
            out.append(fingers)
    if not out:  # contradictory fixed fingers: ignore them for this onset
        out = [c if hand == "R" else tuple(reversed(c)) for c in combinations(range(1, 6), k)]
    return out


def _inner_cost(group: list[dict], fingers: tuple[int, ...], hand: str) -> float:
    cost = sum(_key_cost(f, n["midi"]) for n, f in zip(group, fingers, strict=False))
    for i in range(len(fingers) - 1):
        cost += pair_cost(fingers[i], group[i]["midi"], fingers[i + 1], group[i + 1]["midi"], hand)
    # A chord wider than its fingers can stretch (1 to 5 on two keys a tenth apart).
    for (n1, f1), (n2, f2) in combinations(zip(group, fingers, strict=False), 2):
        if impossible(f1, n1["midi"], f2, n2["midi"], hand):
            cost += IMPOSSIBLE
    return cost


def _move_cost(a: list[dict], fa: tuple, b: list[dict], fb: tuple, hand: str) -> float:
    """From one onset to the next: the outer notes of each (the top one
    carries the line in the right hand, the bottom one in the left)."""
    dt = max(0.01, b[0]["start"] - a[0]["start"])
    weight = min(1.0, max(0.15, 0.35 / dt))
    na, nb = len(fa), len(fb)

    def step(f1: int, p1: int, f2: int, p2: int) -> float:
        c = pair_cost(f1, p1, f2, p2, hand) + _succession_cost(f1, p1, f2, p2)
        if f1 == f2 or p1 == p2:
            return c
        up = (p2 - p1) * (f2 - f1) > 0
        if (hand == "R") != up:
            # With time between the two (a rest, a long note) the hand lifts
            # and lands where it wants: no crossing then, a move (the cap). A
            # figure after a short rest started on the thumb (1-3-2-1) to
            # avoid "crossing" from the note before it.
            if dt >= REPOSITION_SEC:
                return min(c + CROSS_COST, JUMP_COST)
            # Crossing (the next finger on the wrong side): fine for the thumb
            # passing under or a finger over it, now and then; never 3 over 4.
            # Without this a scale went 2-1-2-1-2.
            # The 2 over the thumb (2-1-2-1 down a run) is the awkward one of
            # those: the hand turns for a single step; 3 or 4 over it reach.
            if {f1, f2} == {1, 2}:
                return c + CROSS_COST + CROSS_TWO
            return c + (CROSS_COST if 1 in (f1, f2) else CROSS_COST + 6.0)
        # The fingers in order but too far apart: the hand moves there, which
        # costs the same however far (the cap; a crossing is not a move).
        return min(c, JUMP_COST)

    cost = step(fa[na - 1], a[na - 1]["midi"], fb[nb - 1], b[nb - 1]["midi"])
    if na > 1 or nb > 1:
        cost += step(fa[0], a[0]["midi"], fb[0], b[0]["midi"])
    return weight * cost


def impossible(f1: int, p1: int, f2: int, p2: int, hand: str) -> bool:
    """Two keys down at once that no hand can play with these fingers."""
    if p1 == p2:
        return f1 != f2  # one key, one finger
    if f1 == f2:
        return True
    lo_f, hi_f = (f1, f2) if p1 < p2 else (f2, f1)  # fingers on the lower / higher key
    if (hand == "R") != (lo_f < hi_f):
        return True  # crossed: right hand fingers rise with the keys, left hand fall
    a, b = sorted((f1, f2))
    return abs(p2 - p1) > SPAN[(a, b)][5]


def _held_cost(held: list[tuple], group: list[dict], fingers: tuple, hand: str) -> float:
    """Keys still down (end, midi, finger) when this onset is struck: the new
    keys must be playable with them (impossible() costs IMPOSSIBLE), and the
    hand spans them all at once."""
    t = group[0]["start"]
    cost = 0.0
    for end, midi, f in held:
        if end <= t + HOLD_OVERLAP:
            continue
        for n, fn in zip(group, fingers, strict=False):
            if impossible(f, midi, fn, n["midi"], hand):
                cost += IMPOSSIBLE
            elif fn != f:
                cost += 0.5 * pair_cost(f, midi, fn, n["midi"], hand)
    return cost


def _contexts(groups: list[list[dict]]) -> list[tuple]:
    """Each onset's melodic context: its keys, the keys of the two onsets
    before and after it, and which gaps are fast. Two onsets with the same
    context are the same figure."""
    keys = [tuple(n["midi"] for n in g) for g in groups]
    starts = [g[0]["start"] for g in groups]
    out = []
    for i in range(len(groups)):
        around = tuple(keys[j] if 0 <= j < len(keys) else None for j in range(i - 2, i + 3))
        fast = tuple(
            0 <= j < len(keys) - 1 and starts[j + 1] - starts[j] < FAST_SEC for j in (i - 1, i)
        )
        out.append((around, fast))
    return out


def _consensus(groups: list[list[dict]], chosen: list[tuple]) -> list[tuple | None]:
    """For each onset, (fingers, weight): the fingers most often taken by its
    context -- the two-onset one (PREFER), else the one-onset one when the
    wider one is unique (PREFER_NEAR: the figure may lead somewhere else) --
    or None when its context never repeats or has no clear favourite."""
    ctx = _contexts(groups)
    wide: dict[tuple, Counter] = defaultdict(Counter)
    near: dict[tuple, Counter] = defaultdict(Counter)
    near_of = [((c[0][1:4]), c[1]) for c in ctx]
    for c, n, f in zip(ctx, near_of, chosen, strict=True):
        wide[c][f] += 1
        near[n][f] += 1
    out: list[tuple | None] = []
    for c, n in zip(ctx, near_of, strict=True):
        is_wide = sum(wide[c].values()) >= 2
        votes = wide[c] if is_wide else near[n]
        total = sum(votes.values())
        if total < 2:
            out.append(None)
            continue
        best, count = votes.most_common(1)[0]
        out.append((best, PREFER if is_wide else PREFER_NEAR) if count * 2 > total else None)
    return out


def _hand_fingers(notes: list[dict], hand: str, fixed: dict[str, int]) -> dict[str, int]:
    groups = _onsets(notes)
    if not groups:
        return {}
    chosen = _viterbi(groups, hand, fixed, None)
    for _ in range(CONSENSUS_PASSES):
        prefer = _consensus(groups, chosen)
        again = _viterbi(groups, hand, fixed, prefer)
        if again == chosen:
            break
        chosen = again
    out: dict[str, int] = {}
    for g, fingers in zip(groups, chosen, strict=True):
        for n, f in zip(g, fingers, strict=False):
            out[n["id"]] = f
    return out


def _viterbi(
    groups: list[list[dict]], hand: str, fixed: dict[str, int], prefer: list | None
) -> list[tuple]:
    """The fingers of every onset on the cheapest path; `prefer`: fingers per
    onset that cost nothing, the others PREFER for each finger that differs."""
    # Viterbi over onsets. Each state also carries the keys still held on its
    # best path, so a finger that is busy is not used again (the previous
    # onset alone did not say: a held bass two onsets back did).
    prev = []  # (cost, back index, fingers, held) per candidate of the previous onset
    trail: list[list[tuple[float, int, tuple]]] = []
    for gi, group in enumerate(groups):
        cur = []
        t = group[0]["start"]
        for fingers in _candidates(group, hand, fixed):
            inner = _inner_cost(group, fingers, hand)
            want = prefer[gi] if prefer else None
            if want is not None and want[0] != fingers:
                inner += want[1] * sum(a != b for a, b in zip(want[0], fingers, strict=False))
            if gi == 0:
                back, best, held = -1, 0.0, []
            else:
                best, back = min(
                    (
                        pc
                        + _move_cost(groups[gi - 1], pf, group, fingers, hand)
                        + _held_cost(ph, group, fingers, hand),
                        j,
                    )
                    for j, (pc, _, pf, ph) in enumerate(prev)
                )
                held = [h for h in prev[back][3] if h[0] > t + HOLD_OVERLAP]
            held = held + [
                (min(n.get("end", n["start"]), n["start"] + BUSY_SEC), n["midi"], f)
                for n, f in zip(group, fingers, strict=False)
            ]
            cur.append((best + inner, back, fingers, held))
        trail.append([c[:3] for c in cur])
        prev = cur
    # Back to the start.
    path: list[tuple] = [()] * len(groups)
    j = min(range(len(prev)), key=lambda i: prev[i][0])
    for gi in range(len(groups) - 1, -1, -1):
        _, back, fingers = trail[gi][j]
        path[gi] = fingers
        j = back
    return path


def suggest(notes: list[dict], fixed: dict[str, int] | None = None) -> dict[str, int]:
    """note id -> finger for every note. `notes`: id, midi, start, hand ("L"
    or "R"; anything else counts as right). `fixed`: fingers to keep."""
    fixed = {k: v for k, v in (fixed or {}).items() if v in (1, 2, 3, 4, 5)}
    out: dict[str, int] = {}
    for hand in ("R", "L"):
        mine = [n for n in notes if (n.get("hand") == "L") == (hand == "L")]
        out.update(_hand_fingers(mine, hand, fixed))
    return out
