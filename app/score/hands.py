"""Which hand plays each note, followed through time.

A fixed split point (every note from middle C up goes to the treble staff)
breaks on accompaniment that climbs: in Yann Tiersen's Comptine the left hand
arpeggiates D3-F#3-B3-D4-E4 under a right-hand melody starting around G4, and
a split at C4 sent the arpeggio's top notes up to the treble staff, where a
pianist would never read them.

What defines the left hand is its reach from its own bass. Its floor is the
lowest note it played in the last FLOOR_SEC; a group's lowest note is the left
hand's when it lies within reach of that floor (SPAN semitones, a ninth plus),
and then the hand sits on it and takes everything it reaches above it. The
right hand takes the rest, and the top note of a group when it carries on the
right hand's line (melodic continuity). Within a group the left hand always
has the lower notes. Hands that are idle stay out of the way: with no left
hand for a while, a high group belongs to the right hand, and the other way
round. Measuring reach from a floor, not from the previous note, keeps a lone
melody from climbing into the left hand one step at a time.

(A first version followed each hand's average register; it split the left
hand's arpeggio in two -- bass in one hand, its upper notes in the other.)

Deterministic: same notes, same hands. A note the user moved with H keeps its
hand.
"""

from __future__ import annotations

GROUP_SEC = 0.035
SPAN = 14  # semitones the left hand reaches above its bass
SHIFT = 2  # how far above its floor's reach the hand may have moved meanwhile
FLOOR_SEC = 2.0  # how far back the left hand's floor looks
MELODY_SEC = 0.7  # quarters at ~90 BPM; longer windows stole accompaniment notes
MELODY_STEP = 4  # semitones: a step that continues the right hand's line
MELODY_MIN_ABOVE_BASS = 7
IDLE_SEC = 2.0
# A broken chord spread to a tenth (B2-F#3-B3-D#4 in Porz Goret) is still the
# left hand's when its top lies well below everything the right hand is
# playing; the plain reach would send the D#4 up to the treble staff.
REACH_EXTRA = 3  # semitones beyond SPAN
BELOW_RIGHT = 7  # semitones (a fifth) under the right hand's lowest recent note
RIGHT_SEC = 1.5  # how far back "recent" looks for the right hand
REPEAT_SEC = 2.0  # ...and only for a pitch the left hand itself played this recently


def _groups(notes: list[dict]) -> list[list[dict]]:
    ordered = sorted(notes, key=lambda n: (n["start"], n["midi"]))
    groups: list[list[dict]] = []
    for n in ordered:
        if groups and n["start"] - groups[-1][0]["start"] <= GROUP_SEC:
            groups[-1].append(n)
        else:
            groups.append([n])
    return groups


def _reaches(
    midi: int, ref: int, span: int, right_low: int | None, repeated: set[int], split: int
) -> bool:
    """Within span of ref, or a little further (a tenth) for a pitch of the
    left hand's own figure while the right hand is busy well above it (a new
    melody note there is not a repeat). Up to middle C and well under the right
    hand, a note is the left hand's whatever the reach: it has moved up from a
    deep bass octave."""
    if midi - ref <= span:
        return True
    if right_low is None or midi > right_low - BELOW_RIGHT:
        return False
    return midi <= split or (midi in repeated and midi - ref <= span + REACH_EXTRA)


def assign_hands(notes: list[dict], split: int = 60) -> dict[str, str]:
    """note id -> "L" | "R"."""
    out: dict[str, str] = {}
    left: list[dict] = []  # left-hand notes, for the bass reference
    last = {"L": float("-inf"), "R": float("-inf")}
    right_last: tuple[float, int] | None = None
    right: list[tuple[float, int]] = []  # (start, midi) of right-hand notes
    right_floor: int | None = None
    left_played: list[tuple[float, int]] = []  # (start, midi), REPEAT_SEC back
    last_floor: int | None = None

    for group in _groups(notes):
        t = group[0]["start"]
        pitches = sorted(group, key=lambda n: n["midi"])
        fixed = {n["id"]: n["hand"] for n in group if n.get("hand") in ("L", "R")}

        left = [n for n in left if t - n["start"] <= FLOOR_SEC]
        lowest = pitches[0]["midi"]
        right = [r for r in right if t - r[0] <= RIGHT_SEC]
        left_played = [p for p in left_played if t - p[0] <= REPEAT_SEC]
        repeated = {m for _, m in left_played}
        # Like the floor: a right hand that has not played lately is still
        # where its last group was.
        right_marks = [m for _, m in right] + ([right_floor] if right_floor is not None else [])
        right_low = min(right_marks) if right_marks else None

        ctx = (right_low, repeated, split)
        # A hand that has not played lately is still where it last was: a held
        # whole note in the bass must not leave the left hand without a floor
        # 2 s later (it let the melody in, on human timing).
        # Also the lowest note of its last group: a time window can cut a chord
        # in half (on human timing only the top of D3-F3-A3 was still inside it,
        # which raised the floor to A3 and let a melody A4 in).
        recent = [n["midi"] for n in left] + ([last_floor] if last_floor is not None else [])
        floor = min(recent) if recent else None
        # Known limit: an arpeggio climbing far above a deep bass (G2 then
        # G3-B3-D4) can lose its top notes to the right hand. Following the
        # left hand's own line fixes that but steals a melody that starts a
        # third above the arpeggio's top; pitch and time alone cannot tell
        # them apart, so H (move to the other hand) is the remedy.
        lowest_is_left = floor is None or _reaches(lowest, floor, SPAN, *ctx)
        bass = lowest if lowest_is_left else floor

        left_idle = t - last["L"] > IDLE_SEC
        right_idle = t - last["R"] > IDLE_SEC
        if left_idle and not left and lowest >= split:
            k = 0  # nothing low going on: a passage for the right hand alone
        elif right_idle and pitches[-1]["midi"] < split:
            k = len(pitches)  # all low, right hand resting
        elif not lowest_is_left:
            k = 0  # beyond the left hand's reach from where it has been
        else:
            k = 0
            for n in pitches:
                # Within reach of where the hand sits now, and not far above
                # where it has been: the first melody note sounding with an
                # arpeggio's top must not ride along into the left hand.
                if _reaches(n["midi"], bass, SPAN, *ctx) and (
                    floor is None or _reaches(n["midi"], floor, SPAN + SHIFT, *ctx)
                ):
                    k += 1
                else:
                    break
            # The top note carries on the right hand's line: give it back.
            top = pitches[-1]["midi"]
            if (
                k == len(pitches)
                and len(pitches) >= 1
                and right_last is not None
                and t - right_last[0] <= MELODY_SEC
                and abs(top - right_last[1]) <= MELODY_STEP
                and top - bass >= MELODY_MIN_ABOVE_BASS
                and top >= split
            ):
                k = len(pitches) - 1

        # The user's own moves win; keep the left hand below the right.
        for i, n in enumerate(pitches):
            if fixed.get(n["id"]) == "R":
                k = min(k, i)
        for i, n in enumerate(pitches):
            if fixed.get(n["id"]) == "L":
                k = max(k, i + 1)

        for i, n in enumerate(pitches):
            hand = fixed.get(n["id"]) or ("L" if i < k else "R")
            out[n["id"]] = hand
            last[hand] = t
            if hand == "L":
                left.append(n)
                left_played.append((t, n["midi"]))
            else:
                right.append((t, n["midi"]))
        if k < len(pitches):
            right_last = (t, pitches[-1]["midi"])
        left_now = [n["midi"] for n in pitches if out[n["id"]] == "L"]
        if left_now:
            last_floor = min(left_now)
        right_now = [n["midi"] for n in pitches if out[n["id"]] == "R"]
        if right_now:
            right_floor = min(right_now)
    return out

