"""Score module, pure part: notes -> engraved score, spelling, chords, writers.

Golden tests: exact input -> exact output. No model, no browser. The
calibration piece (app/score/calibration.py) is the main fixture, because the
same piece is what a person checks by eye in the score view.
"""

from __future__ import annotations

import io
import random
import xml.etree.ElementTree as ET

import mido
import pytest

from app.score import calibration as cal
from app.score.chords import chord_name, detect
from app.score.engrave import Settings, decompose, engrave
from app.score.keys import parse_key, spell_midi, spelling_table
from app.score.mei import to_mei
from app.score.midi import to_midi
from app.score.musicxml import to_musicxml
from app.score.timegrid import TPB, TimeGrid


def _sig(eng) -> list[str]:
    """One line per measure and staff: kind, value, dots, triplet, beam, and
    each head as letter+accidental+octave, '!' for a written accidental and
    the tie flag. Compact enough to read as a score."""
    out = []
    for m in eng.measures:
        for staff, items in sorted(m.staves.items()):
            cells = []
            for it in items:
                heads = ",".join(
                    h.letter
                    + {1: "#", -1: "b", 0: ""}[h.alter]
                    + str(h.octave)
                    + ("!" if h.accid is not None else "")
                    + (h.tie or "")
                    for h in it.heads
                )
                cells.append(
                    f"{it.kind[0]}{it.dur}{'.' * it.dots}{'t' if it.tuplet is not None else ''}"
                    f"{'b' if it.beam else ''}[{heads}]"
                )
            out.append(f"{m.number}/{staff} " + " ".join(cells))
    return out


CALIBRATION_SIG = [
    "1/1 c4[F4] c4[G4] c4[A4] c4[Bb4]",
    "1/2 c2[F2,C3] c2[F2,C3]",
    "2/1 c4[C5] c4[D5] c4[E5] c4[F5]",
    "2/2 c2[C3,G3] c2[C3,G3]",
    "3/1 c1[F4,A4,C5]",
    "3/2 c1[F2]",
    "4/1 c2[Bb4,D5,F5] c2[C5,E5,G5]",
    "4/2 c2[Bb2] c2[C3]",
    "5/1 c8b[A4] c8b[Bb4] c8b[C5] c8b[D5] c8b[C5] c8b[Bb4] c8b[A4] c8b[G4]",
    "5/2 c1[D3,F3,A3]",
    "6/1 c2[A4,C#5!,E5] c8tb[E5] c8tb[C#5] c8tb[A4] c8tb[E5] c8tb[C#5] c8tb[A4]",
    "6/2 c1[E3]",
    "7/1 c4.[G4] c8[E4] c2[Bb4]",
    "7/2 c1[C3,E3]",
    "8/1 c1[F4,A4,C5]",
    "8/2 c1[F2,F3]",
]


def _engrave(notes, **settings):
    return engrave(
        notes, cal.beats(), cal.bars(), parse_key(*cal.KEY), Settings.from_dict(settings)
    )


def test_calibration_engraves_exactly():
    eng = _engrave(cal.notes())
    assert _sig(eng) == CALIBRATION_SIG
    assert len(eng.measures) == cal.EXPECTED["measures"]
    assert sum(len(i["heads"]) > 0 for i in eng.notes.values()) == cal.EXPECTED["notes"]


def test_human_timing_jitter_gives_the_same_score():
    rng = random.Random(7)
    jittered = []
    for n in cal.notes():
        d = rng.uniform(-0.03, 0.03)
        jittered.append({**n, "start": n["start"] + d, "end": n["end"] + rng.uniform(-0.03, 0.03)})
    assert _sig(_engrave(jittered)) == CALIBRATION_SIG


def test_tempo_drift_is_absorbed_by_the_beat_grid():
    # Beats that accelerate from 90 to ~110 BPM: eighths placed halfway
    # between beats must still be eighths.
    beats = [0.0]
    for i in range(12):
        beats.append(beats[-1] + 60 / (90 + 2 * i))
    notes = []
    for i in range(8):
        t0 = beats[i]
        mid = (beats[i] + beats[i + 1]) / 2
        notes.append(
            {"id": f"n{2 * i:04d}", "midi": 72, "start": t0, "end": mid - 0.02, "velocity": 80}
        )
        notes.append(
            {
                "id": f"n{2 * i + 1:04d}",
                "midi": 74,
                "start": mid,
                "end": beats[i + 1] - 0.02,
                "velocity": 80,
            }
        )
    eng = engrave(
        notes, beats, [{"beat": 0, "beats_per_bar": 4}], parse_key("C", "Major"), Settings()
    )
    values = [it.dur for m in eng.measures for it in m.staves[1]]
    assert values == [8] * 16


def test_grid_setting_changes_resolution():
    # A note on the second sixteenth of a beat lands on it with "16" and is
    # pulled to a beat boundary with "8".
    beats = [i * 0.5 for i in range(10)]
    notes = [{"id": "n0001", "midi": 72, "start": 0.125, "end": 0.45, "velocity": 80}]
    on16 = engrave(
        notes, beats, [], parse_key("C", "Major"), Settings.from_dict({"grid": "16"})
    ).notes["n0001"]["on"]
    on8 = engrave(
        notes, beats, [], parse_key("C", "Major"), Settings.from_dict({"grid": "8"})
    ).notes["n0001"]["on"]
    assert on16 % TPB == 3
    assert on8 % (TPB // 2) == 0


def test_hand_override_moves_a_note_to_the_other_staff():
    notes = cal.notes()
    target = next(n for n in notes if n["midi"] == 65 and n["start"] < 1.1)  # F4, treble
    target["hand"] = "L"
    eng = _engrave(notes)
    assert eng.notes[target["id"]]["staff"] == 2


@pytest.mark.parametrize(
    ("label", "scale", "fifths", "name"),
    [
        ("F", "Major", -1, "Fa mayor"),
        ("A#", "Major", -2, "Si♭ mayor"),
        ("D", "Natural Minor", -1, "Re menor"),
        ("D#", "Major", -3, "Mi♭ mayor"),
        ("F#", "Natural Minor", 3, "Fa♯ menor"),
        (None, None, 0, "Do mayor"),
    ],
)
def test_key_from_the_jobs_sharp_spelled_label(label, scale, fifths, name):
    key = parse_key(label, scale)
    assert key.fifths == fifths
    assert key.name() == name


def test_spelling_follows_the_key():
    def spelled(label, scale, midi):
        letter, alter, octave = spell_midi(midi, spelling_table(parse_key(label, scale)))
        return f"{letter}{ {1: '#', -1: 'b', 0: ''}[alter] }{octave}"

    assert spelled("F", "Major", 70) == "Bb4"  # never A#
    assert spelled("D", "Natural Minor", 73) == "C#5"  # raised 7th
    assert spelled("C", "Major", 68) == "G#4"  # E7's third
    assert spelled("C", "Major", 70) == "Bb4"  # flat seven
    assert spelled("G", "Major", 66) == "F#4"
    assert spelled("C", "Major", 60) == "C4"  # middle C


def test_accidental_persists_within_a_measure_and_naturals_cancel():
    beats = [i * 0.5 for i in range(10)]
    seq = [73, 73, 72, 73]  # C#5 C#5 C5 C#5
    notes = [
        {"id": f"n{i:04d}", "midi": m, "start": i * 0.5, "end": i * 0.5 + 0.45, "velocity": 80}
        for i, m in enumerate(seq)
    ]
    eng = engrave(
        notes, beats, [{"beat": 0, "beats_per_bar": 4}], parse_key("C", "Major"), Settings()
    )
    heads = [it.heads[0] for it in eng.measures[0].staves[1]]
    assert [h.accid for h in heads] == [1, None, 0, 1]


def test_notes_across_a_barline_are_tied():
    beats = [i * 0.5 for i in range(20)]
    notes = [
        {"id": "n0001", "midi": 72, "start": 1.5, "end": 2.98, "velocity": 80}
    ]  # beat 3 -> beat 6
    eng = engrave(
        notes, beats, [{"beat": 0, "beats_per_bar": 4}], parse_key("C", "Major"), Settings()
    )
    ties = [h.tie for m in eng.measures for it in m.staves[1] for h in it.heads]
    assert ties == ["i", "t"]
    assert eng.notes["n0001"]["heads"] == ["n0001", "n0001-1"]


def test_decompose_values():
    sub = [4] * 8
    assert [(d, dots) for _, _, d, dots, _ in decompose(0, 4 * TPB, sub)] == [(1, 0)]
    assert [(d, dots) for _, _, d, dots, _ in decompose(0, 18, sub)] == [(4, 1)]
    assert [(d, dots) for _, _, d, dots, _ in decompose(3, 12, sub)] == [(8, 1)]
    tri = [3] * 8
    assert [(d, t) for _, _, d, _, t in decompose(0, 4, tri)] == [(8, 0)]


def test_calibration_chords():
    notes = cal.notes()
    eng = _engrave(notes)
    key = parse_key(*cal.KEY)
    names = [chord_name(c.root, c.quality, c.bass, key) for c in detect(notes, eng.grid, "half")]
    assert names == cal.EXPECTED["chords"]
    letters = [
        chord_name(c.root, c.quality, c.bass, key, solfege=False)
        for c in detect(notes, eng.grid, "half")
    ]
    assert letters == ["F", "C", "F", "Bb", "C", "Dm", "A/E", "C7", "F"]


def test_chord_names_in_both_systems():
    key = parse_key("D", "Natural Minor")
    assert chord_name(2, "min", 2, key) == "Rem"
    assert chord_name(9, "maj", 4, key) == "La/Mi"
    assert chord_name(10, "maj", 10, key) == "Si♭"
    assert chord_name(9, "7", 9, key, solfege=False) == "A7"


def test_mei_carries_note_ids_and_chords():
    notes = cal.notes()
    eng = _engrave(notes)
    key = parse_key(*cal.KEY)
    chords = [
        {"beat": c.beat, "text": chord_name(c.root, c.quality, c.bass, key), "id": f"h{i}"}
        for i, c in enumerate(detect(notes, eng.grid, "half"))
    ]
    mei = to_mei(eng, chords, bpm=90)
    root = ET.fromstring(mei)
    ns = {"m": "http://www.music-encoding.org/ns/mei"}
    xml_id = "{http://www.w3.org/XML/1998/namespace}id"
    note_ids = {el.get(xml_id) for el in root.iter("{http://www.music-encoding.org/ns/mei}note")}
    assert {n["id"] for n in notes} <= note_ids
    harms = [h.text for h in root.iterfind(".//m:harm", ns)]
    assert harms == cal.EXPECTED["chords"]
    staff_defs = root.findall(".//m:staffDef", ns)
    assert [(s.get("clef.shape"), s.get("clef.line")) for s in staff_defs] == [
        ("G", "2"),
        ("F", "4"),
    ]
    assert root.find(".//m:scoreDef", ns).get("key.sig") == "1f"


def test_musicxml_is_well_formed_and_complete():
    notes = cal.notes()
    eng = _engrave(notes)
    xml = to_musicxml(eng, [], bpm=90, title="cal")
    root = ET.fromstring(xml.split("?>", 1)[1].split(">", 1)[1])  # drop decl + DOCTYPE
    pitched = [n for n in root.iter("note") if n.find("pitch") is not None]
    assert len(pitched) == cal.EXPECTED["notes"]
    assert len(root.findall(".//measure")) == 8
    assert root.find(".//key/fifths").text == "-1"
    # Every measure's two staves add up to the bar.
    for m in root.findall(".//measure"):
        per_staff = {"1": 0, "2": 0}
        for n in m.findall("note"):
            if n.find("chord") is None:
                per_staff[n.find("staff").text] += int(n.find("duration").text)
        assert per_staff == {"1": 4 * TPB, "2": 4 * TPB}


@pytest.mark.parametrize("quantized", [False, True])
def test_midi_plays_back_in_the_songs_time(quantized):
    notes = cal.notes()
    eng = _engrave(notes)
    mid = mido.MidiFile(file=io.BytesIO(to_midi(eng, notes, quantized=quantized)))
    ons = []
    for track in mid.tracks[1:]:
        t = 0
        for msg in track:
            t += msg.time
            if msg.type == "note_on" and msg.velocity > 0:
                ons.append(t)
    assert len(ons) == cal.EXPECTED["notes"]
    # Played through its tempo map, every note sounds when it sounds in the
    # audio (second 0 of the file is second 0 of the song).
    played = []
    elapsed = 0.0
    for msg in mid:  # iterating a MidiFile yields delta times in seconds
        elapsed += msg.time
        if msg.type == "note_on" and msg.velocity > 0:
            played.append((round(elapsed, 3), msg.note))
    expected = sorted((round(n["start"], 3), n["midi"]) for n in notes)
    assert len(played) == len(expected)
    for (t, m), (t_ref, m_ref) in zip(sorted(played), expected, strict=True):
        assert m == m_ref
        assert abs(t - t_ref) < (0.06 if quantized else 0.01)


def test_empty_notes_engrave_to_one_empty_measure():
    eng = engrave([], cal.beats(), cal.bars(), parse_key("C", "Major"), Settings())
    assert len(eng.measures) == 1
    assert "<mRest" in to_mei(eng, [])


def test_tempo_override_halves_the_grid():
    notes = cal.notes()
    normal = _engrave(notes)
    half = _engrave(notes, tempo="half")
    # 4/4 at 90 read as 45 BPM: each tracker bar is two beats now, which the
    # "auto" meter groups as 4/4 -- half as many bars.
    assert half.measures[0].meter == 4
    assert len(half.measures) == len(normal.measures) // 2
    detected = _engrave(notes, tempo="half", meter="detected")
    assert detected.measures[0].meter == 2


def test_same_pitch_twice_at_one_onset_is_one_head():
    # Transcription sometimes reports one key twice. Two heads on one line
    # cannot be read and break Verovio's tie matching (found by a 1200-note
    # stress run): one is drawn, the other points at it.
    beats = [i * 0.5 for i in range(20)]
    notes = [
        {"id": "n0001", "midi": 62, "start": 0.0, "end": 0.9, "velocity": 80},
        {"id": "n0002", "midi": 62, "start": 0.01, "end": 2.6, "velocity": 70},
        {"id": "n0003", "midi": 69, "start": 0.0, "end": 2.6, "velocity": 70},
    ]
    # Split at middle C: which hand a lone D4+A4 is (either can be) is not
    # what this test is about.
    eng = engrave(
        notes,
        beats,
        [{"beat": 0, "beats_per_bar": 4}],
        parse_key("C", "Major"),
        Settings.from_dict({"hands": "split"}),
    )
    drawn = [h.note_id for it in eng.measures[0].staves[1] for h in it.heads]  # D4: treble
    assert "n0002" in drawn and "n0001" not in drawn  # the longer one is kept
    assert eng.notes["n0001"]["duplicate_of"] == "n0002"
    assert eng.notes["n0001"]["heads"] == []
    mei = to_mei(eng, [])
    assert 'xml:id="n0001"' not in mei
    assert mei.count('pname="d" oct="4"') == sum(
        1 for m in eng.measures for it in m.staves[1] for h in it.heads if h.midi == 62
    )


def test_minor_second_on_one_letter_is_respelled():
    # E-flat and E-natural in one chord: E-flat becomes D-sharp so the two
    # heads sit on different lines.
    beats = [i * 0.5 for i in range(10)]
    notes = [
        {"id": "n0001", "midi": 75, "start": 0.0, "end": 0.45, "velocity": 80},  # Eb5 in F major
        {"id": "n0002", "midi": 76, "start": 0.0, "end": 0.45, "velocity": 80},  # E5
    ]
    eng = engrave(
        notes, beats, [{"beat": 0, "beats_per_bar": 4}], parse_key("F", "Major"), Settings()
    )
    heads = eng.measures[0].staves[1][0].heads
    assert [(h.letter, h.alter, h.octave) for h in heads] == [("D", 1, 5), ("E", 0, 5)]
    # The label inside the notehead follows the respelling.
    assert eng.notes["n0001"]["letter"] == "D"


# -- beat grid and meter, the cases a 9-minute song brought up --------------


def _song_like_grid():
    # 0.5 s beats (120 BPM), except an intro the tracker extrapolated at every
    # other beat (1.0 s), and bar runs that contradict each other: two runs at
    # one beat, and a stretch of 2-beat bars between 4-beat ones.
    head = [i * 1.0 for i in range(16)]  # 16 s at half tempo
    body = [16.0 + i * 0.5 for i in range(200)]  # index 16 is 16.0 s
    beats = head + body
    bars = [
        {"beat": 16, "beats_per_bar": 4},
        {"beat": 16, "beats_per_bar": 2},
        {"beat": 30, "beats_per_bar": 4},
        {"beat": 80, "beats_per_bar": 2},
        {"beat": 120, "beats_per_bar": 4},
    ]
    return beats, bars


def test_half_tempo_stretches_are_split():
    from app.score.timegrid import regularize

    beats, _ = _song_like_grid()
    reg, added = regularize(beats)
    assert added == 16  # sixteen 1.0 s intervals, one beat inserted in each
    gaps = [b - a for a, b in zip(reg, reg[1:], strict=False)]
    assert max(gaps) - min(gaps) < 1e-9 and abs(gaps[0] - 0.5) < 1e-9


def test_one_meter_where_the_tracker_contradicts_itself():
    beats, bars = _song_like_grid()
    grid = TimeGrid(beats, bars, t_max=beats[-1])
    assert {m.meter for m in grid.measures} == {4}
    assert grid.meter_source == "auto"
    # Barlines sit on the tracker's majority downbeats (16.0 s is one).
    starts = {round(grid.beats[m.start_beat], 3) for m in grid.measures}
    assert 16.0 in starts and 18.0 in starts
    detected = TimeGrid(beats, bars, t_max=beats[-1], meter="detected")
    assert {m.meter for m in detected.measures} >= {2, 4}


def test_bar_shift_and_forced_meter():
    beats, bars = _song_like_grid()
    base = TimeGrid(beats, bars, t_max=beats[-1])
    shifted = TimeGrid(beats, bars, t_max=beats[-1], bar_shift=1)
    a = {m.start_beat for m in base.measures if m.n_beats == 4}
    b = {m.start_beat for m in shifted.measures if m.n_beats == 4}
    assert {x + 1 for x in a} & b
    three = TimeGrid(beats, bars, t_max=beats[-1], meter="3")
    assert {m.meter for m in three.measures} == {3} and three.meter_source == "manual"


@pytest.mark.parametrize(
    ("label", "scale", "name"),
    [
        ("B min", "Natural Minor", "Si menor"),  # what the pipeline writes
        ("A# maj", "Major", "Si♭ mayor"),
        ("C maj", "Major", "Do mayor"),
        ("Bb", None, "Si♭ mayor"),
        ("F# min", None, "Fa♯ menor"),
    ],
)
def test_key_labels_as_the_pipeline_writes_them(label, scale, name):
    assert parse_key(label, scale).name() == name


def test_key_estimated_from_the_notes():
    from app.score.keys import estimate_key

    key, corr, margin = estimate_key(cal.notes())
    assert key.name() == "Fa mayor" and corr > 0.7 and margin > 0
    # The same piece a fourth lower and in minor-sounding material is not
    # needed: a plain B minor scale and triad, which is what the song read.
    b_minor = [71, 73, 74, 76, 78, 79, 81, 83, 71, 74, 78, 59, 66, 71]
    notes = [
        {"midi": m, "start": i * 0.5, "end": i * 0.5 + 0.45, "velocity": 80}
        for i, m in enumerate(b_minor * 2)
    ]
    assert estimate_key(notes)[0].name() == "Si menor"
    assert estimate_key(notes[:5]) is None


def test_a_held_note_sounds_as_long_as_it_is_drawn():
    # A bass note the model held 6 s (its cap when it never hears the release)
    # under moving notes on the same staff is drawn up to the next onset: a
    # half note. It must stop there in playback, lighting, chords and the
    # quantized MIDI too -- it used to sound on for bars (a 9-minute song had
    # 222 such notes).
    beats = [i * 0.5 for i in range(40)]
    notes = [
        {"id": "n0001", "midi": 43, "start": 0.0, "end": 6.0, "velocity": 80},  # G2, 12 beats heard
        {"id": "n0002", "midi": 45, "start": 1.0, "end": 1.9, "velocity": 80},  # A2 on beat 3
        {"id": "n0003", "midi": 47, "start": 2.0, "end": 2.9, "velocity": 80},
    ]
    eng = engrave(
        notes, beats, [{"beat": 0, "beats_per_bar": 4}], parse_key("G", "Major"), Settings()
    )
    held = eng.notes["n0001"]
    assert held["draw_end"] == 1.0  # a half note, as drawn
    assert held["q_end"] > 5.9  # what the model heard is kept, not lost
    mid = mido.MidiFile(file=io.BytesIO(to_midi(eng, notes, quantized=True)))
    t, on, off = 0.0, None, None
    for msg in mid:
        t += msg.time
        if msg.type == "note_on" and msg.note == 43 and msg.velocity:
            on = t
        elif msg.type in ("note_off", "note_on") and msg.note == 43 and not msg.velocity:
            off = t
    assert on is not None and abs((off - on) - 1.0) < 0.02


def test_chords_are_read_from_the_drawn_notes():
    from app.score.service import drawn

    beats = [i * 0.5 for i in range(40)]
    notes = [
        {"id": "n0001", "midi": 48, "start": 0.0, "end": 6.0, "velocity": 80},
        {"id": "n0002", "midi": 47, "start": 2.0, "end": 3.9, "velocity": 80},
    ]
    eng = engrave(
        notes, beats, [{"beat": 0, "beats_per_bar": 4}], parse_key("C", "Major"), Settings()
    )
    ends = {n["id"]: n["end"] for n in drawn(notes, eng)}
    assert ends["n0001"] == 2.0  # stops where B2 starts, not at 6 s


def test_audio_source_choice():
    from app.score.engines import choose_audio

    solo = {"vocals": 0, "drums": 0, "bass": 2, "guitar": 18, "piano": 100, "other": 91}
    band = {"vocals": 80, "drums": 100, "bass": 58, "guitar": 7, "piano": 45, "other": 64}
    assert choose_audio("piano", solo, "auto", True)[0] == "original"
    assert choose_audio("piano", band, "auto", True)[0] == "stem"
    assert choose_audio("piano", solo, "stem", True)[0] == "stem"
    assert choose_audio("piano", band, "original", True)[0] == "original"
    assert choose_audio("piano", solo, "auto", False)[0] == "stem"  # no original on disk
    assert (
        choose_audio("bass", solo, "original", True)[0] == "stem"
    )  # only the piano model reads a mix


def test_weak_song_grids():
    from app.score.pulse import choose, song_grid_is_weak

    good = {
        "detector": "beat_this",
        "source": "drums",
        "beats": list(range(20)),
        "bars": [{"beat": 0, "beats_per_bar": 4}],
    }
    assert song_grid_is_weak(good, {"drums": 100}) is None
    assert "respaldo" in song_grid_is_weak({**good, "detector": "librosa"}, {"drums": 100})
    assert "barras" in song_grid_is_weak({**good, "bars": []}, {"drums": 100})
    assert "silencio" in song_grid_is_weak(good, {"drums": 0})
    assert song_grid_is_weak(None, {}) is not None
    own = {"detector": "beat_this", "beats": list(range(20)), "bars": []}
    assert choose(good, own, {"drums": 100}, "auto")[1] == "song"
    assert choose(good, own, {"drums": 0}, "auto")[1] == "audio"
    assert choose(good, own, {"drums": 100}, "audio")[1] == "audio"
    assert choose(good, None, {"drums": 0}, "auto")[1] == "song"  # nothing better to offer


def test_harmony_breaks_a_minor_key_and_its_dominant():
    from app.score.keys import chord_fit, estimate_key

    # The profile of a melody that dwells on its fifth leans to the dominant's
    # minor (F-sharp minor for B minor); B minor's own chords settle it. Chord
    # durations as measured on the user's solo piano recording.
    chords = [
        (11, "min", 53),
        (7, "maj", 29),
        (9, "maj", 24),
        (6, "min", 22),
        (2, "maj", 22),
        (1, "dim", 17),
        (4, "min", 16),
        (6, "maj", 6),
    ]
    assert chord_fit(chords, 11, True) > 0.6 > 0.4 > chord_fit(chords, 6, True)
    weights = {6: 20, 9: 15, 11: 13, 1: 12, 2: 12, 4: 10, 7: 10, 8: 6}
    notes = []
    t = 0.0
    for pc, w in weights.items():
        for _ in range(w):
            notes.append({"midi": 60 + pc, "start": t, "end": t + 0.5, "velocity": 80})
            t += 0.5
    assert estimate_key(notes)[0].name() == "Fa♯ menor"  # the profile alone
    assert estimate_key(notes, chords)[0].name() == "Si menor"  # with the harmony


# -- hands, meter from the bass, pulse from the notes (Yann Tiersen pieces) --


def _arpeggio_under_melody():
    # Comptine-like: the left hand arpeggiates D3-F#3-B3-D4-E4 in eighths
    # while the right hand plays a melody from G4 up. A split at C4 sent the
    # arpeggio's D4/E4 to the treble staff.
    notes, i = [], 0
    lh = [50, 54, 59, 62, 50, 54, 59, 64] * 4
    for k, m in enumerate(lh):
        notes.append(
            {
                "id": f"n{i:04d}",
                "midi": m,
                "start": k * 0.3,
                "end": k * 0.3 + 0.28,
                "velocity": 70,
                "truth": "L",
            }
        )
        i += 1
    for k, m in enumerate([67, 66, 67, 71, 72, 71, 67, 66]):
        t = 2.4 + k * 0.6
        notes.append(
            {
                "id": f"n{i:04d}",
                "midi": m,
                "start": t,
                "end": t + 0.55,
                "velocity": 90,
                "truth": "R",
            }
        )
        i += 1
    return notes


def _with_first_of_each_key(notes, keys, hand):
    """The user puts the first note of each of `keys` in `hand`."""
    first = {m: next(n["id"] for n in notes if n["midi"] == m) for m in keys}
    return [{**n, "hand": hand if n["id"] in first.values() else None} for n in notes], first


def test_left_hand_arpeggio_follows_one_correction_per_key():
    # Pitch and time alone leave the arpeggio's top (D4/E4 under a melody
    # from G4) to either hand: the model, trained on pianists, gives some of
    # them to the right hand. The old rules kept them all left, but were
    # 85 % right against 95 % on songs with known hands (hands.py). One
    # correction per key brings that key's notes nearby along.
    from app.score.hands import PROPAGATE_SEC, assign_hands

    notes, first = _with_first_of_each_key(_arpeggio_under_melody(), (62, 64), "L")
    hands = assign_hands(notes, 60)
    for m, fid in first.items():
        t0 = next(n["start"] for n in notes if n["id"] == fid)
        nxt = min(
            (n for n in notes if n["midi"] == m and n["start"] > t0), key=lambda n: n["start"]
        )
        assert nxt["start"] - t0 < PROPAGATE_SEC and hands[nxt["id"]] == "L"
    assert all(hands[n["id"]] == "R" for n in notes if n["truth"] == "R")  # the melody
    assert all(hands[n["id"]] == "L" for n in notes if n["midi"] < 59)  # D3, F#3
    # Engraved as the hands say: the notes set left are on the bass staff.
    eng = engrave(
        notes, [i * 0.6 for i in range(40)], [], parse_key("E", "Natural Minor"), Settings()
    )
    assert all(eng.notes[n["id"]]["staff"] == (2 if hands[n["id"]] == "L" else 1) for n in notes)
    split = engrave(
        notes,
        [i * 0.6 for i in range(40)],
        [],
        parse_key("E", "Natural Minor"),
        Settings.from_dict({"hands": "split"}),
    )
    assert any(
        split.notes[n["id"]]["staff"] == 1 for n in notes if n["truth"] == "L"
    )  # the old way


def test_hands_on_the_calibration_piece_even_with_human_timing():
    from app.score.hands import assign_hands

    rng = random.Random(7)
    for jitter in (0.0, 0.03):
        notes = [{**n, "start": n["start"] + rng.uniform(-jitter, jitter)} for n in cal.notes()]
        hands = assign_hands(notes, 60)
        assert all(hands[n["id"]] == n["hand_truth"] for n in notes)


def _note(i, midi, t, truth, dur=0.3):
    return {
        "id": f"n{i:04d}",
        "midi": midi,
        "start": t,
        "end": t + dur,
        "velocity": 70,
        "truth": truth,
    }


def test_left_hand_figure_spread_to_a_tenth_follows_one_correction():
    # Porz Goret: the left hand rocks G#3-D#4 and then spreads B2-B3-G#3-D#4 (a
    # tenth above its bass) while the right hand plays around D#5-A#5. The
    # inner D#4 is either hand by pitch and time; one D#4 put in the left
    # hand takes the D#4s around it along.
    from app.score.hands import PROPAGATE_SEC, assign_hands

    notes, t = [], 0.0
    for _ in range(4):  # the ostinato the left hand sets up
        for m in (56, 63):
            notes.append(_note(len(notes), m, t, "L"))
            t += 0.2
    notes.append(_note(len(notes), 75, t, "R", 0.4))  # D#5
    for _ in range(3):
        for m, hand in ((47, "L"), (82, "R"), (63, "L"), (59, "L"), (75, "R"), (63, "L")):
            notes.append(_note(len(notes), m, t, hand))
            t += 0.2
    notes, first = _with_first_of_each_key(notes, (63,), "L")
    hands = assign_hands(notes, 60)
    t0 = next(n["start"] for n in notes if n["id"] == first[63])
    wrong = [(n["midi"], n["start"]) for n in notes if hands[n["id"]] != n["truth"]]
    assert all(m == 63 and s - t0 > PROPAGATE_SEC / 2 for m, s in wrong)


def test_a_correction_pulls_only_its_own_key_nearby():
    import numpy as np

    from app.score.hands import PROPAGATE_SEC, propagate

    notes = [
        {"id": "a", "midi": 60, "start": 0.0, "hand": "L"},
        {"id": "b", "midi": 60, "start": PROPAGATE_SEC / 4},
        {"id": "c", "midi": 60, "start": PROPAGATE_SEC * 2},
        {"id": "d", "midi": 61, "start": PROPAGATE_SEC / 4},
    ]
    p = propagate(notes, [0, 1, 2, 3], np.full(4, 0.9))
    assert p[1] < 0.01  # same key, near: pulled to the left hand
    assert p[2] == pytest.approx(0.9) and p[3] == pytest.approx(0.9)  # far / another key
    assert np.array_equal(propagate(notes[1:], [0, 1, 2], np.full(3, 0.9)), np.full(3, 0.9))


def test_arpeggio_from_a_deep_bass_stays_in_the_left_hand():
    # Valse d'Amelie: C2-G2-C3-D3-E3-G3 climbs far above its bass while the
    # right hand holds octaves around C5-C6; G3 and E3 went to the treble staff.
    from app.score.hands import assign_hands

    notes = [_note(0, 72, 0.0, "R", 1.0), _note(1, 84, 0.0, "R", 1.0)]
    for k, m in enumerate((36, 43, 48, 50, 52, 55, 52, 50, 48, 43)):
        notes.append(_note(len(notes), m, 0.15 * (k + 1), "L"))
    hands = assign_hands(notes, 60)
    assert [(n["midi"], n["start"]) for n in notes if hands[n["id"]] != n["truth"]] == []


def test_a_note_moved_by_hand_keeps_its_hand():
    from app.score.hands import assign_hands

    notes = _arpeggio_under_melody()
    notes[3] = {**notes[3], "hand": "R"}  # D4 of the arpeggio, moved up by the user
    assert assign_hands(notes, 60)[notes[3]["id"]] == "R"


def _oom_pah_pah(beats_per_bar: int):
    beats = [i * 0.35 for i in range(64)]
    notes = []
    for b in range(60):
        low = b % beats_per_bar == 0
        pitches = [36] if low else [55, 60]  # deep bass on 1, chord on the rest
        for m in pitches:
            notes.append(
                {
                    "id": f"n{len(notes):04d}",
                    "midi": m,
                    "start": beats[b],
                    "end": beats[b] + 0.3,
                    "velocity": 80,
                }
            )
    return beats, notes


def test_meter_from_the_bass_finds_a_waltz():
    beats, notes = _oom_pah_pah(3)
    grid = TimeGrid(beats, [], t_max=beats[-1], notes=notes)
    assert grid.meter_source == "notes" and {m.meter for m in grid.measures} == {3}
    assert grid.beats[grid.measures[1].start_beat] in [beats[i] for i in range(0, 60, 3)]
    beats, notes = _oom_pah_pah(4)
    grid = TimeGrid(beats, [], t_max=beats[-1], notes=notes)
    assert {m.meter for m in grid.measures} == {4}
    # Too little evidence: the tracker's bars decide, as before.
    assert TimeGrid(beats, cal.bars(), t_max=beats[-1], notes=notes[:6]).meter_source == "auto"


def test_pulse_from_the_notes_and_the_steadier_grid_wins():
    from app.score.pulse import choose, regularity, track_notes

    grid = track_notes(cal.notes())
    assert grid and abs(grid["bpm"] - 90) < 3
    shaky = {
        "detector": "beat_this",
        "beats": [i * 0.66 * (1.3 if i % 3 == 0 else 1.0) for i in range(60)],
        "bars": [],
    }
    weak_song = {"detector": "librosa", "beats": cal.beats(), "bars": []}
    assert regularity(grid) < regularity(shaky)
    assert choose(weak_song, shaky, {}, "auto", grid)[1] == "notes"
    assert choose(weak_song, shaky, {}, "audio", grid)[1] == "audio"


# -- sustain pedal (playback only) --


def test_pedal_holds_a_note_until_the_pedal_comes_up():
    from app.score import pedal

    segs, source = pedal.segments([{"start": 0.0, "end": 2.0}, {"start": 2.1, "end": 4.0}], [])
    assert source == "transcription"
    notes = [
        {"id": "a", "midi": 60, "start": 0.0, "end": 0.5},  # released with the pedal down
        {"id": "b", "midi": 64, "start": 0.0, "end": 2.05},  # released between pedals
        {"id": "c", "midi": 67, "start": 2.2, "end": 2.5},
        {"id": "d", "midi": 67, "start": 3.0, "end": 3.2},  # the same key again
    ]
    full = pedal.full_hold(notes, segs)
    assert full == {"a": 2.0, "b": None, "c": 3.0, "d": 4.0}
    assert pedal.held_end(0.5, full["a"], 0) == 0.5
    assert pedal.held_end(0.5, full["a"], 40) == pytest.approx(1.1)
    assert pedal.held_end(0.5, full["a"], 100) == 2.0
    assert pedal.held_end(2.05, full["b"], 100) == 2.05


def test_without_the_pianists_pedal_it_changes_at_every_chord():
    from app.score import pedal

    segs, source = pedal.segments([], [0.0, 2.0, 4.0])
    assert source == "chords"
    assert segs == [
        (pytest.approx(0.03), pytest.approx(1.97)),
        (pytest.approx(2.03), pytest.approx(3.97)),
        (pytest.approx(4.03), pytest.approx(8.0)),
    ]
    assert pedal.segments(None, []) == ([], "none")


def test_pedal_setting_is_kept_and_bounded():
    assert Settings.from_dict({"pedal": 40}).pedal == 40
    assert Settings.from_dict({"pedal": 140}).pedal == 0
    assert Settings.from_dict({}).to_dict()["pedal"] == 0


def test_playback_sounds_the_heard_release_not_the_one_voice_cut():
    from app.score import pedal

    notes = [
        # Left-hand arpeggio: each held ~0.6 s, drawn only up to the next onset.
        {"id": "a", "midi": 52, "start": 0.0, "end": 0.6},
        {"id": "b", "midi": 59, "start": 0.15, "end": 0.75},
        # A release the model never heard: capped at 6 s, drawn as a half note.
        {"id": "c", "midi": 43, "start": 1.0, "end": 7.0},
        # The same key struck again before the first one was released.
        {"id": "d", "midi": 60, "start": 2.0, "end": 3.0},
        {"id": "e", "midi": 60, "start": 2.5, "end": 3.2},
    ]
    drawn = {"a": 0.15, "b": 0.3, "c": 2.33, "d": 2.5, "e": 3.0}
    ends = pedal.sound_ends(notes, drawn)
    assert ends == {"a": 0.6, "b": 0.75, "c": 2.33, "d": 2.5, "e": 3.2}


def test_chords_on_the_key_b_in_e_flat_minor_are_named_si_not_do_flat():
    # Porz Goret, E-flat minor: a chord on B read "Dobmaj7" and was taken for C.
    from app.score.chords import chord_name

    k = parse_key("Eb", "Natural Minor")
    assert chord_name(11, "maj7", 3, k) == "Simaj7/Mi♭"
    assert chord_name(8, "min", 11, k) == "La♭m/Si"
    assert chord_name(10, "7", 2, k) == "Si♭7/Re"  # ordinary flats stay
    assert chord_name(11, "maj7", 3, k, solfege=False) == "Bmaj7/Eb"


def test_a_held_note_sounds_its_whole_length():
    """A length the user set (held) is meant even past the 6 s the model
    caps an unheard release at; still not past the next strike of its key."""
    from app.score import pedal

    notes = [
        {"id": "a", "midi": 60, "start": 0.0, "end": 8.0, "held": True},
        {"id": "b", "midi": 62, "start": 0.0, "end": 8.0},
        {"id": "c", "midi": 64, "start": 0.0, "end": 3.0, "held": True},
        {"id": "d", "midi": 64, "start": 2.0, "end": 2.5},
    ]
    ends = pedal.sound_ends(notes, {"a": 1.0, "b": 1.0, "c": 1.0, "d": 2.5})
    assert ends["a"] == 8.0 and ends["b"] == 1.0 and ends["c"] == 2.0


def test_a_short_note_struck_with_a_long_one_keeps_its_own_length():
    # A staccato C4 struck with a long bass G2, then moved to the left hand:
    # one chord on the bass staff. The score draws the chord with one duration
    # (the longer), but the note's bar (falling notes, lit key, export) keeps
    # its own length; it took the bass's whole note before.
    beats = [i * 0.5 for i in range(40)]
    notes = [
        {"id": "bass", "midi": 43, "start": 0.0, "end": 1.95, "velocity": 80},  # a whole note
        {"id": "short", "midi": 60, "start": 0.0, "end": 0.24, "velocity": 80, "hand": "L"},  # an eighth
    ]
    eng = engrave(
        notes, beats, [{"beat": 0, "beats_per_bar": 4}], parse_key("C", "Major"), Settings()
    )
    assert eng.notes["short"]["staff"] == eng.notes["bass"]["staff"] == 2
    assert eng.notes["bass"]["draw_end"] == 2.0
    assert eng.notes["short"]["draw_end"] == 0.25
    # Still cut at the next onset of its hand: a long note under moving notes.
    notes.append({"id": "next", "midi": 48, "start": 1.0, "end": 1.4, "velocity": 80, "hand": "L"})
    eng = engrave(
        notes, beats, [{"beat": 0, "beats_per_bar": 4}], parse_key("C", "Major"), Settings()
    )
    assert eng.notes["bass"]["draw_end"] == 1.0
    assert eng.notes["short"]["draw_end"] == 0.25
