"""Experimental: a song from a printed score, and fingering.

The OMR step (Audiveris) is not run here: the MusicXML it would export is
written by hand, so these check the reading, the fingering and the API.
"""

from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from app.core.models import Job
from app.core.registry import _jobs
from app.experimental.sheet.fingering import suggest
from app.experimental.sheet.musicxml import parse

# Two bars of 4/4, two staves. Bar 1: right hand C4 (finger 1) D4 E4 F4
# (finger 1) in quarters, left hand C3 whole; a tie G4-G4 across the barline.
# Bar 3 is missing (as Audiveris drops a bar it cannot build).
MUSICXML = """<?xml version="1.0" encoding="UTF-8"?>
<score-partwise version="3.1">
  <work><work-title>Prueba</work-title></work>
  <part-list><score-part id="P1"><part-name>Piano</part-name></score-part></part-list>
  <part id="P1">
    <measure number="1">
      <attributes><divisions>2</divisions><key><fifths>0</fifths></key>
        <time><beats>4</beats><beat-type>4</beat-type></time><staves>2</staves></attributes>
      <direction><direction-type><dynamics><pp/></dynamics></direction-type><staff>1</staff></direction>
      <note><pitch><step>C</step><octave>4</octave></pitch><duration>2</duration><staff>1</staff>
        <notations><technical><fingering>1</fingering></technical></notations></note>
      <note><pitch><step>D</step><octave>4</octave></pitch><duration>2</duration><staff>1</staff></note>
      <note><grace/><pitch><step>F</step><alter>1</alter><octave>4</octave></pitch><staff>1</staff></note>
      <note><pitch><step>E</step><octave>4</octave></pitch><duration>2</duration><staff>1</staff></note>
      <note><pitch><step>F</step><octave>4</octave></pitch><duration>2</duration><staff>1</staff>
        <notations><technical><fingering>23</fingering></technical></notations></note>
      <note><chord/><pitch><step>A</step><octave>4</octave></pitch><duration>2</duration><staff>1</staff></note>
      <backup><duration>8</duration></backup>
      <note><pitch><step>C</step><octave>3</octave></pitch><duration>8</duration><staff>2</staff></note>
    </measure>
    <measure number="2">
      <note><pitch><step>G</step><octave>4</octave></pitch><duration>4</duration><tie type="start"/><staff>1</staff></note>
      <note><pitch><step>G</step><octave>4</octave></pitch><duration>4</duration><tie type="stop"/><staff>1</staff></note>
      <backup><duration>8</duration></backup>
      <note><rest/><duration>8</duration><staff>2</staff></note>
    </measure>
    <measure number="4">
      <note><pitch><step>C</step><octave>5</octave></pitch><duration>8</duration><staff>1</staff></note>
    </measure>
  </part>
</score-partwise>
"""


@pytest.fixture
def score_file(tmp_path):
    p = tmp_path / "s.musicxml"
    p.write_text(MUSICXML, encoding="utf-8")
    return p


def test_musicxml_notes_beats_and_printed_fingers(score_file):
    s = parse(score_file, bpm=60)
    assert s.title == "Prueba" and s.bpm == 60 and s.fifths == 0
    # Bar 3 lost by the reader comes back as a silent bar: bar 4 starts at 12 s.
    assert s.measures == 4 and s.missing_measures == [3]
    assert s.bars == [{"beat": 0, "beats_per_bar": 4}] and s.beats[:5] == [0, 1, 2, 3, 4]
    by = {(n["midi"], round(n["start"], 2)): n for n in s.notes}
    assert by[(60, 0)]["finger"] == 1 and by[(60, 0)]["staff"] == 1
    assert by[(60, 0)]["velocity"] == 40  # pp
    assert by[(65, 3)]["finger"] == 2  # "23" over a trill: starts with 2
    assert by[(69, 3)]["start"] == 3  # chord note
    assert by[(48, 0)]["end"] == 4 and by[(48, 0)]["staff"] == 2
    # The tie G4 is one note of 4 beats; the grace F#4 sits just before E4.
    assert by[(67, 4)]["end"] == 8 and sum(1 for n in s.notes if n["midi"] == 67) == 1
    grace = next(n for n in s.notes if n.get("grace"))
    assert grace["midi"] == 66 and grace["end"] == pytest.approx(2.0, abs=0.001)
    assert by[(72, 12)]["measure"] == 4


def _seq(midis, hand="R", dt=0.25):
    return [{"id": f"n{i}", "midi": m, "start": i * dt, "hand": hand} for i, m in enumerate(midis)]


def _fingers(notes, fixed=None):
    f = suggest(notes, fixed)
    return [f[n["id"]] for n in notes]


def test_suggested_fingering_plays_scales_and_chords_as_pianists_do():
    assert _fingers(_seq([60, 62, 64, 65, 67, 69, 71, 72])) == [1, 2, 3, 1, 2, 3, 4, 5]
    assert _fingers(_seq([72, 71, 69, 67, 65, 64, 62, 60])) == [5, 4, 3, 2, 1, 3, 2, 1]
    assert _fingers(_seq([48, 50, 52, 53, 55, 57, 59, 60], "L")) == [5, 4, 3, 2, 1, 3, 2, 1]
    chord = [
        {"id": i, "midi": m, "start": 0, "hand": "R"} for i, m in (("a", 64), ("b", 68), ("c", 73))
    ]
    assert _fingers(chord) == [1, 2, 5]  # as printed in the Chopin nocturne


def test_suggestion_keeps_fixed_fingers_and_never_repeats_the_thumb_in_an_arpeggio():
    up = _seq([60, 62, 64, 65, 67, 69, 71, 72])
    assert _fingers(up, {"n3": 4})[3] == 4
    arp = _seq([49, 56, 64, 61, 49, 57, 63, 61], "L", 0.54)
    f = _fingers(arp)
    assert all(a != b for a, b in zip(f, f[1:], strict=False))  # no finger twice in a row


# -- API ------------------------------------------------------------------------

JOB = "f1f1f1f1f1f1"


@pytest.fixture(autouse=True)
def _registry():
    _jobs.clear()
    yield
    _jobs.clear()


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr("app.score.store.JOBS_DIR", tmp_path)
    monkeypatch.setattr("app.api.score.JOBS_DIR", tmp_path)
    from app.main import app

    stems = tmp_path / JOB / "stems"
    stems.mkdir(parents=True)
    (stems / "piano.wav").write_bytes(b"RIFF0000WAVE")
    _jobs[JOB] = Job(id=JOB, status="done", title="Hoja", bpm=60)
    d = tmp_path / JOB / "score" / "piano"
    d.mkdir(parents=True)
    notes = [
        {"midi": m, "start": i * 0.5, "end": i * 0.5 + 0.45, "velocity": 70}
        for i, m in enumerate([60, 62, 64, 65])
    ]
    (d / "raw.json").write_text(json.dumps({"engine": "partitura", "notes": notes}))
    return TestClient(app), d


def test_fingering_only_for_songs_that_have_it_then_by_hand(client):
    c, d = client
    url = f"/api/jobs/{JOB}/score/piano/fingering"
    assert c.get(url).json() == {"available": False}  # an ordinary song: nothing changes
    assert c.put(url, json={"set": {"n00001": 2}}).status_code == 404
    (d / "meta.json").write_text(
        json.dumps(
            {"fingering": {"source": "sheet", "fixed": {"n00001": {"f": 3, "src": "score"}}}}
        )
    )
    data = c.get(url).json()
    assert data["fingers"]["n00001"] == {"f": 3, "src": "score"}
    assert data["counts"] == {"score": 1, "user": 0, "auto": 3}
    data = c.put(url, json={"set": {"n00002": 4}}).json()
    assert data["fingers"]["n00002"] == {"f": 4, "src": "user"}
    data = c.put(url, json={"set": {"n00002": None}}).json()
    assert data["fingers"]["n00002"]["src"] == "auto"
    assert c.put(url, json={"set": {"n00002": 7}}).status_code == 422


def test_sheet_import_says_when_audiveris_is_missing(client, monkeypatch):
    c, _ = client
    monkeypatch.setattr("app.experimental.sheet.omr.executable", lambda: None)
    assert c.get("/api/experimental/sheet").json()["available"] is False
    r = c.post("/api/experimental/sheet", files={"file": ("p.pdf", b"%PDF-1.4", "application/pdf")})
    assert r.status_code == 503
    r = c.post(
        "/api/experimental/sheet", files={"file": ("p.exe", b"x", "application/octet-stream")}
    )
    assert r.status_code == 415


# -- printed finger digits read from the page (digits.py) ---------------------


def _render(text: str, font_name: str, size: int = 26):
    import numpy as np
    from PIL import Image, ImageDraw, ImageFont

    try:
        font = ImageFont.truetype(font_name, size)
    except OSError:
        pytest.skip(f"font {font_name} not installed")
    im = Image.new("L", (size * 2, size * 2), 0)
    ImageDraw.Draw(im).text((4, 2), text, fill=255, font=font)
    m = np.asarray(im) > 128
    ys, xs = np.nonzero(m)
    return m[ys.min() : ys.max() + 1, xs.min() : xs.max() + 1]


@pytest.mark.parametrize("digit", ["1", "2", "3", "4", "5"])
def test_a_bold_upright_digit_reads_as_that_finger(digit):
    from app.experimental.sheet.digits import classify

    assert classify(_render(digit, "SCHLBKB.TTF"))[0] == int(digit)


def test_not_fingers_italic_tuplet_three_other_digits_and_stem_stubs():
    import numpy as np

    from app.experimental.sheet.digits import classify

    assert classify(_render("3", "timesbi.ttf"))[0] is None  # a tuplet "3" is italic
    assert classify(_render("8", "SCHLBKB.TTF"))[0] is None
    assert classify(np.ones((26, 3), dtype=bool))[0] is None  # a stem stub is no "1"


def test_found_digits_go_to_their_note_in_the_chord():
    from app.experimental.sheet.digits import Found, attach

    notes = [
        {"midi": 64, "staff": 1, "measure": 1, "onset_q": 0.0},
        {"midi": 73, "staff": 1, "measure": 1, "onset_q": 0.0},
        {"midi": 68, "staff": 1, "measure": 1, "onset_q": 0.0},
        {"midi": 49, "staff": 2, "measure": 1, "onset_q": 1.0, "finger": 5},
    ]
    found = [
        Found(1, 1, 0.0, 0, 5, 0.9, (0, 0, 1, 1)),  # top of the chord
        Found(1, 1, 0.02, 2, 1, 0.9, (0, 0, 1, 1)),  # bottom
        Found(1, 2, 1.0, 0, 3, 0.9, (0, 0, 1, 1)),  # already read by Audiveris: kept
        Found(2, 1, 0.0, 0, 2, 0.9, (0, 0, 1, 1)),  # no note there: ignored
    ]
    assert attach(notes, found) == 2
    assert [n.get("finger") for n in notes] == [1, 5, None, 5]


# -- trills played out (ornaments.py) -------------------------------------------


def test_upper_neighbour_follows_the_key_signature():
    from app.experimental.sheet.ornaments import upper_neighbour

    assert upper_neighbour("F", 5, 4) == 80  # F#5 in C# minor trills with G#5
    assert upper_neighbour("B", 4, 4) == 73  # B#4 -> C#5
    assert upper_neighbour("E", 5, 0) == 77  # E5 in C major -> F5
    assert upper_neighbour("E", 5, 4, alter=1) == 78  # a sharp printed with the "tr"


def test_a_trill_is_played_out_on_the_principal_note_with_its_termination():
    from app.experimental.sheet.ornaments import realize

    trill = {
        "midi": 78, "start": 2.0, "end": 4.0, "velocity": 60, "staff": 1, "finger": 2,
        "trill": {"upper": 80, "post": [76, 78], "fingers": {"p": 2, "u": 3, "post": [1, 3]}},
    }  # fmt: skip
    out = realize([{"midi": 80, "start": 0, "end": 2, "velocity": 60, "staff": 1}, trill])
    notes = out[1:]
    keys = [n["midi"] for n in notes]
    assert keys[0] == 78 and keys[-3] == 78  # starts and ends on the principal note
    assert keys[-2:] == [76, 78]  # then the termination
    assert all(a != b for a, b in zip(keys[:-2], keys[1:-2], strict=False))  # alternates
    assert notes[0]["start"] == 2.0 and notes[-1]["end"] == pytest.approx(4.0, abs=0.001)
    assert {n["midi"]: n["finger"] for n in notes[:-2]} == {78: 2, 80: 3}
    assert [n["finger"] for n in notes[-2:]] == [1, 3]
    assert 14 <= len(notes) <= 20  # ~8 notes a second


def test_grace_notes_before_a_trill_start_it_on_the_beat(tmp_path):
    xml = MUSICXML.replace(
        """<note><pitch><step>G</step><octave>4</octave></pitch><duration>4</duration><tie type="start"/><staff>1</staff></note>""",
        """<note><grace/><pitch><step>F</step><alter>1</alter><octave>4</octave></pitch><staff>1</staff></note>
      <note><pitch><step>G</step><octave>4</octave></pitch><duration>4</duration><tie type="start"/><staff>1</staff>
        <notations><ornaments><trill-mark/></ornaments></notations></note>""",
    )
    p = tmp_path / "t.musicxml"
    p.write_text(xml, encoding="utf-8")
    s = parse(p, bpm=60)
    g = next(n for n in s.notes if n["midi"] == 67)
    assert g["trill"] == {"upper": 69, "pre": [66]} and g["end"] == 8
    assert not any(n.get("grace") and n["measure"] == 2 for n in s.notes)  # not slipped before


def test_fingers_for_any_song_on_request_and_away_again(client):
    c, d = client
    url = f"/api/jobs/{JOB}/score/piano/fingering"
    assert c.get(url).json() == {"available": False}
    data = c.post(url + "/enable").json()
    assert data["available"] and data["source"] == "manual"
    assert data["counts"] == {"score": 0, "user": 0, "auto": 4}  # all suggested
    assert [data["fingers"][f"n{i:05d}"]["f"] for i in range(4)] == [1, 2, 3, 4]  # C D E F
    c.put(url, json={"set": {"n00002": 4}})
    again = c.post(url + "/enable").json()  # enabling twice keeps what was set
    assert again["fingers"]["n00002"] == {"f": 4, "src": "user"}
    assert c.delete(url).json() == {"available": False}
    assert c.get(url).json() == {"available": False}


def test_a_song_from_a_score_keeps_its_printed_fingers(client):
    c, d = client
    (d / "meta.json").write_text(json.dumps({"fingering": {"source": "sheet", "fixed": {}}}))
    assert c.delete(f"/api/jobs/{JOB}/score/piano/fingering").status_code == 409


def test_a_chord_struck_unevenly_still_gets_rising_fingers():
    # A transcribed chord: the top note struck 20 ms before the bottom one.
    chord = [
        {"id": "a", "midi": 74, "start": 0.000, "end": 0.5, "hand": "R"},
        {"id": "b", "midi": 71, "start": 0.020, "end": 0.5, "hand": "R"},
        {"id": "c", "midi": 67, "start": 0.045, "end": 0.5, "hand": "R"},
    ]
    f = suggest(chord)
    assert f["c"] < f["b"] < f["a"]


def test_a_finger_holding_a_key_is_not_used_for_another():
    # A held G4 under a moving line: whatever plays the line, not the G4's finger.
    notes = [{"id": "held", "midi": 67, "start": 0.0, "end": 1.0, "hand": "R"}] + [
        {"id": f"m{i}", "midi": m, "start": 0.2 + i * 0.2, "end": 0.4 + i * 0.2, "hand": "R"}
        for i, m in enumerate([71, 72, 74, 72])
    ]
    f = suggest(notes)
    assert all(f[f"m{i}"] != f["held"] for i in range(4))


def test_a_scale_passes_the_thumb_under_instead_of_alternating_fingers():
    up = _seq([64, 66, 68, 69, 71, 73, 74])  # E major-ish run, as in bar 21 of the nocturne
    f = _fingers(up)
    assert sum(1 for a, b in zip(f, f[1:], strict=False) if b < a) <= 1  # one thumb passing


# -- a song separated again by BS-RoFormer (experimental/separation.py) ---------


def test_roformer_copy_keeps_the_song_and_adds_a_track(client, monkeypatch, tmp_path):
    import numpy as np
    import soundfile as sf

    from app.core.config import STEM_NAMES
    from app.experimental import separation

    c, _ = client
    monkeypatch.setattr("app.experimental.separation.JOBS_DIR", tmp_path)
    monkeypatch.setattr("app.score.store.JOBS_DIR", tmp_path)
    stems = tmp_path / JOB / "stems"
    for i, name in enumerate(STEM_NAMES):  # an original to separate from
        sf.write(stems / f"{name}.wav", np.full((4410, 2), 0.01 * (i + 1)), 44100)
    monkeypatch.setattr("app.experimental.separation.available", lambda: False)
    assert c.get("/api/experimental/separation").json() == {"available": False}
    assert c.post(f"/api/experimental/jobs/{JOB}/separation").status_code == 503

    def fake(audio, out_dir, device=None):
        out_dir.mkdir(parents=True, exist_ok=True)
        level = {"piano": 0.2, "guitar": 0.0}
        for name in STEM_NAMES:
            sf.write(out_dir / f"{name}.wav", np.full((4410, 2), level.get(name, 0.1)), 44100)

    monkeypatch.setattr(separation, "separate", fake)
    out = separation.copy_job(JOB)
    assert out["job_id"] != JOB and out["title"].endswith(" — separador RoFormer")
    assert out["stem_presence"]["piano"] == 100 and out["stem_presence"]["guitar"] == 0
    assert _jobs[out["job_id"]].status == "done" and JOB in _jobs  # the song is still there
    assert (tmp_path / out["job_id"] / "stems" / "piano.wav").is_file()


def test_import_asks_for_roformer_only_when_installed(client, monkeypatch):
    c, _ = client
    monkeypatch.setattr("app.experimental.separation.available", lambda: False)
    url = "https://www.youtube.com/watch?v=dQw4w9WgXcQ"
    r = c.post("/api/jobs", json={"url": url, "separator": "roformer"})
    assert r.status_code == 422 and "RoFormer" in r.json()["detail"]


def test_the_pipeline_separates_with_roformer_when_chosen(tmp_path, monkeypatch):
    import numpy as np
    import soundfile as sf

    from app.core.config import DEMUCS_MODEL, STEM_NAMES
    from app.pipeline import separate as sep

    called = {}

    def fake(audio, out_dir, device=None):
        called["device"] = device
        out_dir.mkdir(parents=True, exist_ok=True)
        for name in STEM_NAMES:
            sf.write(out_dir / f"{name}.wav", np.zeros((441, 2)), 44100)

    monkeypatch.setattr("app.experimental.separation.separate", fake)
    monkeypatch.setattr(sep, "get_demucs_device", lambda: "cpu")
    job = Job(id="a1b2c3d4e5f6", separator="roformer")
    src = tmp_path / "source.wav"
    sf.write(src, np.zeros((441, 2)), 44100)
    out = sep.separate(job, src, tmp_path)
    assert out == tmp_path / DEMUCS_MODEL / "source"  # where collect() looks
    assert called == {"device": "cpu"} and (out / "piano.wav").is_file()
    assert job.to_state()["separator"] == "roformer"


# -- the same figure, the same fingers (consensus; fingering.py) ---------------


def _figure_song(tails, figure=(62, 60, 59, 57), gap=0.2, jitter=0.0):
    """The figure, again and again, each time followed by `tails[i]`."""
    notes, figs, t = [], [], 0.0
    for rep, tail in enumerate(tails):
        ids = []
        for k, m in enumerate(figure):
            nid = f"n{len(notes):04d}"
            # A transcription's timing is never exact: some repetitions drift.
            at = t + (jitter if rep % 2 and k == 2 else 0.0)
            notes.append({"id": nid, "midi": m, "start": at, "end": at + gap * 0.9, "hand": "R"})
            ids.append(nid)
            t += gap
        figs.append(ids)
        for m in tail:
            notes.append(
                {
                    "id": f"n{len(notes):04d}",
                    "midi": m,
                    "start": t,
                    "end": t + gap * 0.9,
                    "hand": "R",
                }
            )
            t += gap
        t += 2 * gap
    return notes, figs


def test_a_figure_that_repeats_keeps_its_fingers():
    # D4-C4-B3-A3 (a run of "BAILE INOLVIDABLE"), each time going on a little
    # differently and played a little unevenly: one fingering for it.
    notes, figs = _figure_song([[64, 65], [64, 62], [65, 64], [64, 65], [62, 64]], jitter=0.025)
    f = suggest(notes)
    got = {tuple(f[i] for i in ids) for ids in figs}
    assert len(got) == 1, got


def test_a_fast_run_never_puts_one_finger_on_two_keys_in_a_row():
    # Before a drop the figure may change fingers (to prepare it), but never by
    # sliding one finger from key to key (4-3-2-2 came out of the consensus).
    notes, _ = _figure_song([[64, 65], [57, 55], [67, 69], [62, 64], [52, 53], [60, 62]])
    f = suggest(notes)
    run = sorted(notes, key=lambda n: n["start"])
    for a, b in zip(run, run[1:], strict=False):
        if b["start"] - a["start"] < 0.35 and a["midi"] != b["midi"]:
            assert f[a["id"]] != f[b["id"]], (a, b)


def _timed(pairs, hand="R"):
    """(midi or [midis], start) -> notes; a list is a chord."""
    out = []
    for midis, t in pairs:
        for m in midis if isinstance(midis, list) else [midis]:
            out.append({"id": f"n{len(out)}", "midi": m, "start": t, "end": t + 0.3, "hand": hand})
    return out


def test_a_repeated_key_keeps_its_finger():
    # From "Cry": C5 struck again and again, then a chord with the thumb a key
    # lower. The last C5 went to the 2 to free the thumb (a change on one key
    # cost almost nothing): hard to follow on the falling notes.
    notes = _timed(
        [([72, 84], 0.0), (72, 0.45), (72, 0.64), (72, 1.1), ([71, 74, 83], 1.56), ([71, 74], 1.99)]
    )
    f = suggest(notes)
    assert f["n0"] == f["n2"] == f["n3"] == f["n4"], f
    # A run down onto a repeated A4, a dip to E4 and the A4 again (BAILE
    # INOLVIDABLE): the A4 is one finger all three times.
    notes = _timed(
        [
            (74, 0.0),
            (72, 0.34),
            (71, 0.68),
            (69, 1.02),
            (69, 1.35),
            (64, 1.85),
            (69, 2.02),
            (72, 2.36),
        ]
    )
    f = suggest(notes)
    assert f["n3"] == f["n4"] == f["n6"], f


def test_a_melody_in_octaves_is_always_thumb_and_little_finger():
    # From "Cry": a single G5 on the 4, then octaves moving up and down, over
    # black keys too. 1-4 came out on the octave after the 4 (and on 40 % of
    # octaves overall): the hand keeps its shape, so 1-5 every time.
    right = _timed(
        [
            (79, 0.0),
            (78, 0.41),
            ([67, 79], 0.80),
            ([69, 81], 1.20),
            ([70, 82], 1.60),
            ([66, 78], 2.0),
            ([67, 79], 2.4),
        ]
    )
    f = suggest(right)
    octaves = [right[i : i + 2] for i in range(2, len(right), 2)]
    assert all((f[a["id"]], f[b["id"]]) == (1, 5) for a, b in octaves), f
    # The left hand: little finger on the bottom key, thumb on the top one.
    left = _timed(
        [(47, 0.0), ([35, 47], 0.42), ([40, 52], 0.83), ([35, 47], 1.24), ([43, 55], 1.65)],
        hand="L",
    )
    f = suggest(left)
    octaves = [left[i : i + 2] for i in range(1, len(left), 2)]
    assert all((f[a["id"]], f[b["id"]]) == (5, 1) for a, b in octaves), f


def test_a_key_coming_back_with_the_hand_in_place_keeps_its_finger():
    # A turn around E4 (Valse d'Amélie): the hand never moves, so each key
    # keeps one finger all the way.
    midis = [64, 65, 67, 65, 64, 62, 64, 65, 64, 62, 64, 65, 67]
    notes = _seq(midis, dt=0.16)
    f = suggest(notes)
    by_key: dict[int, set[int]] = {}
    for n in notes:
        by_key.setdefault(n["midi"], set()).add(f[n["id"]])
    assert all(len(v) == 1 for v in by_key.values()), by_key


def test_the_weak_fingers_are_not_taken_without_a_reason():
    # Three neighbouring keys up: 1-2-3 (Parncutt's weak-finger rule), not 2-3-4 / 3-4-5.
    assert _fingers(_seq([60, 62, 64])) == [1, 2, 3]
