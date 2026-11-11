"""Engraved score -> MEI 5, what the score page renders with Verovio.

MEI rather than MusicXML because Verovio keeps each element's xml:id in the
SVG it draws. Every notehead therefore carries the id of the note it came
from, which is how the page puts a name inside it, lights it while it sounds,
and knows which note a click selected.
"""

from __future__ import annotations

from xml.sax.saxutils import escape

from app.score.engrave import STAFF_BASS, STAFF_TREBLE, EMeasure, Engraved, Item
from app.score.timegrid import TPB

_ACCID = {-2: "ff", -1: "f", 0: "n", 1: "s", 2: "x"}


def _attr(**kw) -> str:
    return "".join(
        f' {k.replace("_", ".")}="{escape(str(v))}"' for k, v in kw.items() if v is not None
    )


def _note(h, dur=None, dots=None) -> str:
    accid = _ACCID[h.accid] if h.accid is not None else None
    ges = _ACCID[h.accid_ges] if h.accid_ges and h.accid is None else None
    attrs = {
        "xml:id": h.xml_id,
        "pname": h.letter.lower(),
        "oct": h.octave,
        "dur": dur,
        "dots": dots or None,
        "accid": accid,
        "accid_ges": ges,
        "tie": h.tie,
    }
    body = "".join(
        f' {k if k == "xml:id" else k.replace("_", ".")}="{escape(str(v))}"'
        for k, v in attrs.items()
        if v is not None
    )
    return f"<note{body}/>"


def _item(it: Item) -> str:
    if it.kind == "mrest":
        return f'<mRest xml:id="{it.xml_id}"/>'
    dots = it.dots or None
    if it.kind == "rest":
        return f'<rest xml:id="{it.xml_id}"{_attr(dur=it.dur, dots=dots)}/>'
    if len(it.heads) == 1:
        return _note(it.heads[0], it.dur, it.dots)
    inner = "".join(_note(h) for h in it.heads)
    return f'<chord xml:id="{it.xml_id}"{_attr(dur=it.dur, dots=dots)}>{inner}</chord>'


def _layer(items: list[Item]) -> str:
    out: list[str] = []
    i = 0
    while i < len(items):
        it = items[i]
        if it.tuplet is not None:
            j = i
            while j < len(items) and items[j].tuplet == it.tuplet:
                j += 1
            group = items[i:j]
            inner = _beamed(group)
            out.append(
                f'<tuplet num="3" numbase="2" num.visible="true" bracket.visible="false">{inner}</tuplet>'
            )
            i += len(group)
            continue
        if it.beam is not None:
            group = []
            while i < len(items) and items[i].beam == it.beam and items[i].tuplet is None:
                group.append(items[i])
                i += 1
            out.append("<beam>" + "".join(_item(x) for x in group) + "</beam>")
            continue
        out.append(_item(it))
        i += 1
    return "".join(out)


def _beamed(group: list[Item]) -> str:
    if len(group) >= 2 and all(x.kind == "chord" and x.dur >= 8 for x in group):
        return "<beam>" + "".join(_item(x) for x in group) + "</beam>"
    return "".join(_item(x) for x in group)


def _measure(m: EMeasure, harms: list[tuple[float, str, str]]) -> str:
    parts = []
    if m.meter_change:
        parts.append(f'<scoreDef meter.count="{m.meter}" meter.unit="4"/>')
    for staff in (STAFF_TREBLE, STAFF_BASS):
        parts.append(
            f'<staff n="{staff}"><layer n="1">{_layer(m.staves.get(staff, []))}</layer></staff>'
        )
    for tstamp, text, hid in harms:
        parts.append(
            f'<harm xml:id="{hid}" staff="1" place="above" tstamp="{tstamp:g}">{escape(text)}</harm>'
        )
    metcon = ' metcon="false"' if m.n_beats < m.meter else ""
    return f'<measure n="{m.number}" xml:id="m{m.number}"{metcon}>{"".join(parts)}</measure>'


def to_mei(eng: Engraved, chords: list[dict], *, bpm: int | None = None, title: str = "") -> str:
    """`chords`: [{"beat": grid beat index, "text": label, "id": stable id}]."""
    by_measure: dict[int, list[tuple[float, str, str]]] = {}
    for c in chords:
        tick = c["beat"] * TPB
        for m in eng.measures:
            if m.start_tick <= tick < m.end_tick:
                tstamp = (tick - m.start_tick) / TPB + 1
                by_measure.setdefault(m.number, []).append((tstamp, c["text"], c["id"]))
                break
    first = eng.measures[0] if eng.measures else None
    meter = first.meter if first else 4
    tempo = f' midi.bpm="{int(bpm)}"' if bpm else ""
    head = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<mei xmlns="http://www.music-encoding.org/ns/mei" meiversion="5.0">'
        f"<meiHead><fileDesc><titleStmt><title>{escape(title)}</title></titleStmt><pubStmt/></fileDesc></meiHead>"
        "<music><body><mdiv><score>"
        f'<scoreDef key.sig="{eng.key.mei_sig}" meter.count="{meter}" meter.unit="4"{tempo}>'
        '<staffGrp symbol="brace" bar.thru="true">'
        '<staffDef n="1" lines="5" clef.shape="G" clef.line="2"/>'
        '<staffDef n="2" lines="5" clef.shape="F" clef.line="4"/>'
        "</staffGrp></scoreDef><section>"
    )
    body = "".join(_measure(m, by_measure.get(m.number, [])) for m in eng.measures)
    if not eng.measures:
        body = (
            '<measure n="1"><staff n="1"><layer n="1"><mRest/></layer></staff>'
            '<staff n="2"><layer n="1"><mRest/></layer></staff></measure>'
        )
    return head + body + "</section></score></mdiv></body></music></mei>"
