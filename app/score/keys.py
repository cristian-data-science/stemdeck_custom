"""Key signature and pitch spelling.

The job's key arrives as a pitch label that is always spelled with sharps
("A#") plus a scale name ("Major", "Natural Minor", "Harmonic Minor"), from
app/pipeline/analyze.py. A score needs the conventional key instead: A# major
is written as B-flat major with two flats, and in that key a black key between
A and B is B-flat, never A-sharp.
"""

from __future__ import annotations

from dataclasses import dataclass

LETTERS = "CDEFGAB"
# Pitch class of each natural letter.
LETTER_PC = {"C": 0, "D": 2, "E": 4, "F": 5, "G": 7, "A": 9, "B": 11}
SOLFEGE = {"C": "do", "D": "re", "E": "mi", "F": "fa", "G": "sol", "A": "la", "B": "si"}
_SHARP_LABELS = ("C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B")

# Conventional tonic spelling and fifths (negative = flats) per pitch class.
_MAJOR = {
    0: ("C", 0, 0),
    1: ("D", -1, -5),
    2: ("D", 0, 2),
    3: ("E", -1, -3),
    4: ("E", 0, 4),
    5: ("F", 0, -1),
    6: ("F", 1, 6),
    7: ("G", 0, 1),
    8: ("A", -1, -4),
    9: ("A", 0, 3),
    10: ("B", -1, -2),
    11: ("B", 0, 5),
}
_MINOR = {
    0: ("C", 0, -3),
    1: ("C", 1, 4),
    2: ("D", 0, -1),
    3: ("E", -1, -6),
    4: ("E", 0, 1),
    5: ("F", 0, -4),
    6: ("F", 1, 3),
    7: ("G", 0, -2),
    8: ("G", 1, 5),
    9: ("A", 0, 0),
    10: ("B", -1, -5),
    11: ("B", 0, 2),
}
# Order in which sharps / flats enter a key signature.
_SHARP_ORDER = "FCGDAEB"
_FLAT_ORDER = "BEADGCF"
_MAJOR_STEPS = (0, 2, 4, 5, 7, 9, 11)
_MINOR_STEPS = (0, 2, 3, 5, 7, 8, 10)
# Chromatic interval above the tonic -> scale degree (0-based) whose letter
# spells it.
_MAJOR_CHROMATIC = {1: 0, 3: 2, 6: 3, 8: 4, 10: 6}
_MINOR_CHROMATIC = {1: 1, 4: 2, 6: 3}


@dataclass(frozen=True)
class Key:
    tonic_pc: int
    minor: bool
    tonic_letter: str
    tonic_alter: int
    fifths: int

    @property
    def signature(self) -> dict[str, int]:
        """Letter -> alteration the key signature applies."""
        sig = dict.fromkeys(LETTERS, 0)
        if self.fifths > 0:
            for letter in _SHARP_ORDER[: self.fifths]:
                sig[letter] = 1
        elif self.fifths < 0:
            for letter in _FLAT_ORDER[: -self.fifths]:
                sig[letter] = -1
        return sig

    @property
    def mei_sig(self) -> str:
        if self.fifths == 0:
            return "0"
        return f"{abs(self.fifths)}{'s' if self.fifths > 0 else 'f'}"

    def name(self, solfege: bool = True) -> str:
        root = spell_name(self.tonic_letter, self.tonic_alter, solfege=solfege, capital=True)
        if solfege:
            return f"{root} {'menor' if self.minor else 'mayor'}"
        return f"{root} {'minor' if self.minor else 'major'}"


_LETTER_LABEL = {"C": 0, "D": 2, "E": 4, "F": 5, "G": 7, "A": 9, "B": 11}


def _label_pc(label: str) -> int | None:
    """ "A#", "Bb", "B min" -> pitch class. The job's label is "<pitch> <mode>"
    (analyze.py writes f"{_PITCHES[root]} {mode}", e.g. "B min"); the mode
    word is read by parse_key, only the pitch here."""
    head = label.strip().split()[0] if label and label.strip() else ""
    if not head or head[0].upper() not in _LETTER_LABEL:
        return None
    pc = _LETTER_LABEL[head[0].upper()]
    for ch in head[1:]:
        if ch in "#♯":
            pc += 1
        elif ch in "b♭":
            pc -= 1
        else:
            return None
    return pc % 12


def parse_key(label: str | None, scale: str | None) -> Key:
    """The job's key as a Key; C major when the job has none.

    Accepts what the pipeline writes ("B min", "A# maj") as well as a bare
    pitch ("A#", "Bb") with the mode in `scale` ("Natural Minor", "Major").
    Reading only bare sharps labels once turned "B min" into C minor.
    """
    pc = _label_pc(label or "")
    scale_l = (scale or "").lower()
    if "minor" in scale_l:
        minor = True
    elif "major" in scale_l:
        minor = False
    else:
        minor = any(w.startswith("min") or w == "m" for w in (label or "").lower().split()[1:])
    if pc is None:
        pc, minor = 0, False
    letter, alter, fifths = (_MINOR if minor else _MAJOR)[pc]
    return Key(pc, minor, letter, alter, fifths)


def key_from_id(key_id: str) -> Key | None:
    """ "B:minor" / "F:major" (the score's manual key setting) -> Key."""
    try:
        pc_s, mode = key_id.split(":")
        pc = int(pc_s)
    except (ValueError, AttributeError):
        return None
    if not 0 <= pc < 12 or mode not in ("major", "minor"):
        return None
    minor = mode == "minor"
    letter, alter, fifths = (_MINOR if minor else _MAJOR)[pc]
    return Key(pc, minor, letter, alter, fifths)


def key_id(key: Key) -> str:
    return f"{key.tonic_pc}:{'minor' if key.minor else 'major'}"


# Krumhansl-Kessler key profiles (probe-tone ratings), index 0 = tonic.
_KK_MAJOR = (6.35, 2.23, 3.48, 2.33, 4.38, 4.09, 2.52, 5.19, 2.39, 3.66, 2.29, 2.88)
_KK_MINOR = (6.33, 2.68, 3.52, 5.38, 2.60, 3.53, 2.54, 4.75, 3.98, 2.69, 3.34, 3.17)
MIN_KEY_NOTES = 24


def _pearson(a: list[float], b: tuple[float, ...]) -> float:
    ma, mb = sum(a) / 12, sum(b) / 12
    num = sum((x - ma) * (y - mb) for x, y in zip(a, b, strict=True))
    den = (sum((x - ma) ** 2 for x in a) * sum((y - mb) ** 2 for y in b)) ** 0.5
    return num / den if den else 0.0


# Triads that belong to a key, as (interval above the tonic, class). Minor
# keys take the harmonic minor's V and vii° as well as the natural minor's v.
_MAJOR_TRIADS = {(0, "M"), (2, "m"), (4, "m"), (5, "M"), (7, "M"), (9, "m"), (11, "d")}
_MINOR_TRIADS = {
    (0, "m"),
    (2, "d"),
    (3, "M"),
    (5, "m"),
    (7, "m"),
    (7, "M"),
    (8, "M"),
    (10, "M"),
    (11, "d"),
}
_CLASS = {
    "maj": "M",
    "7": "M",
    "maj7": "M",
    "aug": "M",
    "min": "m",
    "m7": "m",
    "dim": "d",
    "m7b5": "d",
}
CHORD_WEIGHT = 1.0
# Scale membership: the share of the notes' weight inside the key's scale
# (major, or natural minor plus its leading tone) decides the key signature,
# which is what the score is written in. On a solo piano piece the profile and
# the chords alone hovered between B minor, D major and F-sharp minor; 7 % of
# the notes fell outside B minor/D major and 11 % outside F-sharp minor (its
# leading tone E-sharp never sounded, G natural did, 10 %).
SCALE_WEIGHT = 2.0
_MAJOR_SCALE = (0, 2, 4, 5, 7, 9, 11)
_MINOR_SCALE = (0, 2, 3, 5, 7, 8, 10, 11)


def chord_fit(chords: list[tuple[int, str, float]], pc: int, minor: bool) -> float:
    """0..1: how much of the chords' time belongs to this key, half of it
    for being diatonic and half for being the tonic chord. Suspended chords
    (no third) count as diatonic when either triad on their root is."""
    total = sum(d for _, _, d in chords)
    if total <= 0:
        return 0.0
    triads = _MINOR_TRIADS if minor else _MAJOR_TRIADS
    tonic = (0, "m" if minor else "M")
    fit = 0.0
    for root, quality, dur in chords:
        iv = (root - pc) % 12
        cls = _CLASS.get(quality)
        classes = (cls,) if cls else ("M", "m")
        if any((iv, c) in triads for c in classes):
            fit += dur
        if any((iv, c) == tonic for c in classes):
            fit += dur
    return fit / (2 * total)


def estimate_key(
    notes: list[dict], chords: list[tuple[int, str, float]] | None = None
) -> tuple[Key, float, float] | None:
    """Key of the transcribed notes: pitch profile, scale fit and harmony.

    Profile: pitch classes weighted by duration (capped at 2 s, so one held
    pedal note cannot decide it) and a little by velocity, correlated with the
    24 rotated Krumhansl-Kessler profiles. Harmony, when `chords` is given as
    (root pc, quality, seconds): chord_fit, weighted as much as the profile. The profile
    alone confuses a minor key with its dominant -- on a solo piano piece it
    read F-sharp minor (0.84) for music whose longest chords were B minor,
    G, A, F-sharp minor and D, all of B minor; with the harmony it reads
    B minor, as the separation's own analysis did. Returns (key, score, margin
    over the runner-up), or None with too few notes.
    """
    if len(notes) < MIN_KEY_NOTES:
        return None
    hist = [0.0] * 12
    for n in notes:
        hist[n["midi"] % 12] += min(n["end"] - n["start"], 2.0) * (
            0.5 + n.get("velocity", 80) / 127
        )
    if not any(hist):
        return None
    total = sum(hist)
    scored = []
    for minor, profile in ((False, _KK_MAJOR), (True, _KK_MINOR)):
        for pc in range(12):
            rotated = tuple(profile[(i - pc) % 12] for i in range(12))
            score = _pearson(hist, rotated)
            inside = sum(hist[(pc + i) % 12] for i in (_MINOR_SCALE if minor else _MAJOR_SCALE))
            score += SCALE_WEIGHT * (inside / total - 1)
            if chords:
                score += CHORD_WEIGHT * chord_fit(chords, pc, minor)
            scored.append((score, pc, minor))
    scored.sort(reverse=True)
    best, pc, minor = scored[0]
    letter, alter, fifths = (_MINOR if minor else _MAJOR)[pc]
    return Key(pc, minor, letter, alter, fifths), round(best, 3), round(best - scored[1][0], 3)


def _diatonic_spellings(key: Key) -> dict[int, tuple[str, int]]:
    start = LETTERS.index(key.tonic_letter)
    steps = _MINOR_STEPS if key.minor else _MAJOR_STEPS
    out: dict[int, tuple[str, int]] = {}
    for degree, step in enumerate(steps):
        letter = LETTERS[(start + degree) % 7]
        pc = (key.tonic_pc + step) % 12
        alter = (pc - LETTER_PC[letter] + 6) % 12 - 6
        out[pc] = (letter, alter)
    return out


def spelling_table(key: Key) -> dict[int, tuple[str, int]]:
    """Pitch class -> (letter, alter) for every pitch class in this key.

    Diatonic notes take the scale's letters. In a minor key the raised 6th and
    7th (melodic/harmonic minor) are spelled on their scale letter, which is
    why D minor writes C-sharp and not D-flat. The other chromatic notes
    follow common-practice usage relative to the tonic: in major the flat 3rd
    and flat 7th, and the sharp 1st, 4th and 5th (so C major writes G-sharp
    for E7 and B-flat for the flat-seven chord); in minor the flat 2nd and the
    sharp 3rd and 4th.
    """
    table = _diatonic_spellings(key)
    start = LETTERS.index(key.tonic_letter)
    if key.minor:
        for degree in (5, 6):
            letter = LETTERS[(start + degree) % 7]
            raised = (key.tonic_pc + _MINOR_STEPS[degree] + 1) % 12
            if raised not in table:
                alter = (raised - LETTER_PC[letter] + 6) % 12 - 6
                if abs(alter) <= 1:
                    table[raised] = (letter, alter)
    chromatic = _MINOR_CHROMATIC if key.minor else _MAJOR_CHROMATIC
    for interval, degree in chromatic.items():
        pc = (key.tonic_pc + interval) % 12
        if pc in table:
            continue
        letter = LETTERS[(start + degree) % 7]
        alter = (pc - LETTER_PC[letter] + 6) % 12 - 6
        if abs(alter) <= 2:
            table[pc] = (letter, alter)
    for pc in range(12):
        if pc in table:
            continue
        natural = next((ltr for ltr, p in LETTER_PC.items() if p == pc), None)
        if natural:
            table[pc] = (natural, 0)
        elif key.fifths >= 0:
            table[pc] = (next(ltr for ltr, p in LETTER_PC.items() if p == (pc - 1) % 12), 1)
        else:
            table[pc] = (next(ltr for ltr, p in LETTER_PC.items() if p == (pc + 1) % 12), -1)
    return table


def spell_midi(midi: int, table: dict[int, tuple[str, int]]) -> tuple[str, int, int]:
    """(letter, alter, octave) for a MIDI note, octave in scientific pitch
    (middle C = C4). The octave follows the letter: B-sharp 3 sounds as C4."""
    letter, alter = table[midi % 12]
    octave = (midi - alter) // 12 - 1
    return letter, alter, octave


def spell_name(letter: str, alter: int, *, solfege: bool, capital: bool = False) -> str:
    """A pitch name for display: "Si♭", "Do♯", "Bb", "F#"."""
    base = SOLFEGE[letter] if solfege else letter
    if capital:
        base = base[0].upper() + base[1:]
    if solfege:
        return base + {-2: "𝄫", -1: "♭", 0: "", 1: "♯", 2: "𝄪"}[alter]
    return base + {-2: "bb", -1: "b", 0: "", 1: "#", 2: "##"}[alter]
