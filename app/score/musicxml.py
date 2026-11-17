"""Engraved score -> MusicXML 4.0 (partwise), for MuseScore, Sibelius, Finale.

The same engraving as the page, so opening the file in another notation
program is an independent check of what StemDeck drew.
"""

from __future__ import annotations

from xml.sax.saxutils import escape

from app.score.engrave import STAFF_BASS, STAFF_TREBLE, Engraved, Item
from app.score.keys import spelling_table
from app.score.timegrid import TPB

_TYPE = {1: "whole", 2: "half", 4: "quarter", 8: "eighth", 16: "16th"}
_ACCID = {-2: "flat-flat", -1: "flat", 0: "natural", 1: "sharp", 2: "double-sharp"}
_KIND = {
    "maj": "major",
    "min": "minor",
    "7": "dominant",
    "maj7": "major-seventh",
    "m7": "minor-seventh",
    "dim": "diminished",
    "aug": "augmented",
    "sus4": "suspended-fourth",
    "sus2": "suspended-second",
    "m7b5": "half-diminished",
}


def _harmony(c: dict, offset: int) -> str:
    off = f"<offset>{offset}</offset>" if offset else ""
    if c.get("override") or c.get("root") is None:
        return (
            '<direction placement="above"><direction-type>'
            f"<words>{escape(c['text'])}</words></direction-type>{off}<staff>1</staff></direction>"
        )
    step, alter = c["root_spelled"]
    root = (
        f"<root><root-step>{step}</root-step>"
        + (f"<root-alter>{alter}</root-alter>" if alter else "")
        + "</root>"
    )
    bass = ""
    if c.get("bass_spelled") and c["bass"] != c["root"]:
        b_step, b_alter = c["bass_spelled"]
        bass = (
            f"<bass><bass-step>{b_step}</bass-step>"
            + (f"<bass-alter>{b_alter}</bass-alter>" if b_alter else "")
            + "</bass>"
        )
    return (
        f'<harmony placement="above">{root}<kind text="{escape(c["text"])}">{_KIND[c["quality"]]}</kind>'
        f"{bass}{off}<staff>1</staff></harmony>"
    )


def _transpose(part: dict) -> str:
    t = part.get("transpose")
    if not t:
        return ""
    diatonic, chromatic, octave = t
    oc = f"<octave-change>{octave}</octave-change>" if octave else ""
    return f"<transpose><diatonic>{diatonic}</diatonic><chromatic>{chromatic}</chromatic>{oc}</transpose>"


def _notes(it: Item, staff: int, beam_state: dict) -> str:
    voice = 1 if staff == STAFF_TREBLE else 5
    out = []
    if it.kind in ("rest", "mrest"):
        measure_attr = ' measure="yes"' if it.kind == "mrest" else ""
        typ = "" if it.kind == "mrest" else f"<type>{_TYPE[it.dur]}</type>" + "<dot/>" * it.dots
        tm = (
            "<time-modification><actual-notes>3</actual-notes><normal-notes>2</normal-notes></time-modification>"
            if it.tuplet is not None
            else ""
        )
        out.append(
            f"<note><rest{measure_attr}/><duration>{it.ticks}</duration><voice>{voice}</voice>"
            f"{typ}{tm}<staff>{staff}</staff></note>"
        )
        return "".join(out)
    beam = ""
    if it.beam is not None:
        key = (staff, it.beam)
        n = beam_state.get(key, 0)
        total = beam_state.get(("len",) + key, 0)
        kind = "begin" if n == 0 else ("end" if n == total - 1 else "continue")
        beam_state[key] = n + 1
        beam = f'<beam number="1">{kind}</beam>'
    for i, h in enumerate(it.heads):
        chord = "<chord/>" if i else ""
        alter = f"<alter>{h.alter}</alter>" if h.alter else ""
        ties = ""
        tied = ""
        if h.tie in ("t", "m"):
            ties += '<tie type="stop"/>'
            tied += '<tied type="stop"/>'
        if h.tie in ("i", "m"):
            ties += '<tie type="start"/>'
            tied += '<tied type="start"/>'
        accid = f"<accidental>{_ACCID[h.accid]}</accidental>" if h.accid is not None else ""
        tm = (
            "<time-modification><actual-notes>3</actual-notes><normal-notes>2</normal-notes></time-modification>"
            if it.tuplet is not None
            else ""
        )
        notations = tied
        if it.tuplet is not None and i == 0:
            pos = beam_state.get(("tup", staff, it.tuplet), 0)
            count = beam_state.get(("tuplen", staff, it.tuplet), 1)
            if pos == 0:
                notations += '<tuplet type="start" bracket="no"/>'
            if pos == count - 1:
                notations += '<tuplet type="stop"/>'
            beam_state[("tup", staff, it.tuplet)] = pos + 1
        notations = f"<notations>{notations}</notations>" if notations else ""
        out.append(
            f'<note id="{h.xml_id}">{chord}<pitch><step>{h.letter}</step>{alter}<octave>{h.octave}</octave></pitch>'
            f"<duration>{it.ticks}</duration>{ties}<voice>{voice}</voice><type>{_TYPE[it.dur]}</type>"
            + "<dot/>" * it.dots
            + f"{accid}{tm}<staff>{staff}</staff>{beam if i == 0 else ''}{notations}</note>"
        )
    return "".join(out)


def to_musicxml(
    eng: Engraved,
    chords: list[dict],
    *,
    bpm: int | None = None,
    title: str = "",
    part: dict | None = None,
) -> str:
    """`part`: one instrument on one treble staff instead of the piano's two:
    {"name": its name, "transpose": (diatonic, chromatic, octave change)
    from what is written to what sounds}."""
    staves = (STAFF_TREBLE,) if part else (STAFF_TREBLE, STAFF_BASS)
    table = spelling_table(eng.key)
    for c in chords:
        if c.get("root") is not None:
            c["root_spelled"] = table[c["root"]]
            c["bass_spelled"] = table[c["bass"]]
    parts = [
        '<?xml version="1.0" encoding="UTF-8" standalone="no"?>'
        '<!DOCTYPE score-partwise PUBLIC "-//Recordare//DTD MusicXML 4.0 Partwise//EN" '
        '"http://www.musicxml.org/dtds/partwise.dtd">'
        '<score-partwise version="4.0">'
        f"<work><work-title>{escape(title)}</work-title></work>"
        f'<part-list><score-part id="P1"><part-name>{escape(part["name"]) if part else "Piano"}</part-name></score-part></part-list>'
        '<part id="P1">'
    ]
    for m in eng.measures:
        attrs = ""
        if m.number == 1:
            attrs = (
                f"<attributes><divisions>{TPB}</divisions><key><fifths>{eng.key.fifths}</fifths>"
                f"<mode>{'minor' if eng.key.minor else 'major'}</mode></key>"
                f"<time><beats>{m.meter}</beats><beat-type>4</beat-type></time>"
                + (
                    '<clef number="1"><sign>G</sign><line>2</line></clef>' + _transpose(part)
                    if part
                    else "<staves>2</staves>"
                    '<clef number="1"><sign>G</sign><line>2</line></clef>'
                    '<clef number="2"><sign>F</sign><line>4</line></clef>'
                )
                + "</attributes>"
            )
            if bpm:
                attrs += (
                    '<direction placement="above"><direction-type><metronome><beat-unit>quarter</beat-unit>'
                    f"<per-minute>{int(bpm)}</per-minute></metronome></direction-type>"
                    f'<sound tempo="{int(bpm)}"/></direction>'
                )
        elif m.meter_change:
            attrs = f"<attributes><time><beats>{m.meter}</beats><beat-type>4</beat-type></time></attributes>"
        implicit = ' implicit="yes"' if m.n_beats < m.meter else ""
        body = [f'<measure number="{m.number}"{implicit}>', attrs]
        state: dict = {}
        for staff in staves:
            items = m.staves.get(staff, [])
            for it in items:
                if it.beam is not None:
                    state[("len", staff, it.beam)] = state.get(("len", staff, it.beam), 0) + 1
                if it.tuplet is not None:
                    state[("tuplen", staff, it.tuplet)] = (
                        state.get(("tuplen", staff, it.tuplet), 0) + 1
                    )
            harms = (
                [c for c in chords if m.start_tick <= c["beat"] * TPB < m.end_tick]
                if staff == STAFF_TREBLE
                else []
            )
            for it in items:
                for c in harms:
                    tick = c["beat"] * TPB
                    if it.tick <= tick < it.tick + it.ticks:
                        body.append(_harmony(c, tick - it.tick))
                body.append(_notes(it, staff, state))
            if staff == STAFF_TREBLE and len(staves) > 1:
                body.append(f"<backup><duration>{m.end_tick - m.start_tick}</duration></backup>")
        body.append("</measure>")
        parts.append("".join(body))
    parts.append("</part></score-partwise>")
    return "".join(parts)
