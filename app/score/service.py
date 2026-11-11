"""Everything the score page needs for one stem, in one payload.

notes.json + beats.json + the job's key -> engraving -> chords -> MEI, plus
placement per note (staff, quantized time, spelling, notehead ids) and a few
diagnostics that say whether a bad-looking score is the transcription's fault
or the beat grid's.
"""

from __future__ import annotations

import statistics

from app.score import engines, pedal, pulse, store
from app.score.chords import chord_name, detect
from app.score.engrave import Engraved, Settings, engrave
from app.score.keys import Key, estimate_key, key_from_id, key_id, parse_key
from app.score.mei import to_mei
from app.score.musicxml import to_musicxml
from app.score.timegrid import TPB

NAMES = ("solfege", "letters")


def view_settings(meta: dict, stem: str = "piano") -> tuple[Settings, str]:
    saved = dict(meta.get("settings") or {})
    saved.setdefault("split", engines.default_split(stem))
    # Two hands to follow only on a piano; a bass line or a voice keeps the
    # fixed split that puts it all on one clef.
    saved.setdefault("hands", "auto" if stem == "piano" else "split")
    settings = Settings.from_dict(saved)
    names = meta.get("names") if meta.get("names") in NAMES else "solfege"
    return settings, names


def _grid_inputs(job, stem: str, setting: str) -> tuple[list[float], list[dict], int | None, dict]:
    """Beats and bars the score is quantized against: the song's grid, or the
    one tracked on this score's own audio (pulse.py), and why."""
    song = store.read_json(store.beats_path(job.id))
    own = store.read_json(store.score_dir(job.id, stem) / "beats.json")
    notes_grid = store.read_json(store.score_dir(job.id, stem) / "beats_notes.json")
    grid, source, why = pulse.choose(song, own, job.stem_presence, setting, notes_grid)
    grid = grid or {}
    # The notes' grid has beats but no barlines: borrow the downbeats the audio
    # tracker heard, placed by time, as votes for where bars start.
    downbeats: list[float] = []
    if source == "notes" and own and own.get("bars"):
        from app.score.timegrid import _downbeat_times

        downbeats = _downbeat_times(sorted(own.get("beats") or []), own.get("bars"))
    beats = grid.get("beats") if isinstance(grid.get("beats"), list) else []
    bars = grid.get("bars") if isinstance(grid.get("bars"), list) else []
    conf = grid.get("confidence") if isinstance(grid.get("confidence"), int) else None
    info = {
        "source": source,
        "reason": why,
        "own_available": own is not None,
        "notes_available": notes_grid is not None,
        "downbeats": downbeats,
    }
    return beats, bars, conf, info


def build_chords(
    notes: list[dict], eng: Engraved, settings: Settings, names: str, overrides: dict
) -> list[dict]:
    if not settings.chords:
        return []
    solfege = names == "solfege"
    out = []
    for c in detect(notes, eng.grid, settings.chord_rate):
        out.append(
            {
                "id": f"h{round(c.time * 1000)}",
                "beat": c.beat,
                "time": c.time,
                "text": chord_name(c.root, c.quality, c.bass, eng.key, solfege=solfege),
                "root": c.root,
                "quality": c.quality,
                "bass": c.bass,
                "override": False,
            }
        )
    for ms_key, text in (overrides or {}).items():
        try:
            t = int(ms_key) / 1000
        except ValueError:
            continue
        match = next((c for c in out if abs(c["time"] - t) < 0.03), None)
        if match is not None:
            if text:
                match.update(text=text, override=True)
            else:
                out.remove(match)
            continue
        if not text:
            continue
        idx, frac = eng.grid.locate(t)
        beat = idx + (1 if frac > 0.5 else 0)
        out.append(
            {
                "id": f"h{ms_key}",
                "beat": beat,
                "time": round(eng.grid.beat_sec(beat), 4),
                "text": text,
                "root": None,
                "quality": None,
                "bass": None,
                "override": True,
            }
        )
    out.sort(key=lambda c: c["beat"])
    return out


def resolve_key(
    job, notes: list[dict], setting: str, chords: list[tuple[int, str, float]] | None = None
) -> tuple[Key, dict]:
    """The key the score is written in, and how it was chosen.

    "auto": from this stem's own notes and their chords when there are enough
    of them (keys.estimate_key), else the song's analysis from the separation.
    "song": the separation's analysis. "pc:mode": the user's choice.
    """
    song = parse_key(job.key, job.scale) if job.key else None
    estimate = estimate_key(notes, chords)
    info = {
        "song": song.name() if song else None,
        "notes": estimate[0].name() if estimate else None,
        "notes_confidence": estimate[1] if estimate else None,
        "notes_margin": estimate[2] if estimate else None,
    }
    manual = key_from_id(setting) if setting not in ("auto", "song") else None
    if manual:
        return manual, {**info, "source": "manual"}
    if setting == "auto" and estimate:
        return estimate[0], {**info, "source": "notes"}
    if song:
        return song, {**info, "source": "song"}
    return parse_key(None, None), {**info, "source": "default"}


def engrave_stem(job, stem: str, notes_doc: dict, meta: dict):
    settings, names = view_settings(meta, stem)
    beats, bars, conf, pulse_info = _grid_inputs(job, stem, settings.pulse)
    notes = notes_doc.get("notes", [])
    key, key_info = resolve_key(job, notes, settings.key)
    downbeats = pulse_info.pop("downbeats", [])
    eng = engrave(notes, beats, bars, key, settings, bpm=job.bpm, downbeat_times=downbeats)
    if settings.key == "auto" and notes:
        # Chord roots and qualities do not depend on the key (only their
        # spelling does), so read them off this engraving and let them vote.
        harmony = _chord_durations(detect(drawn(notes, eng), eng.grid, "half"))
        voted, key_info = resolve_key(job, notes, settings.key, harmony)
        if (voted.tonic_pc, voted.minor) != (key.tonic_pc, key.minor):
            key = voted
            eng = engrave(notes, beats, bars, key, settings, bpm=job.bpm, downbeat_times=downbeats)
    eng.key_info = key_info
    eng.pulse_info = pulse_info
    chords = build_chords(
        drawn(notes, eng), eng, settings, names, meta.get("chord_overrides") or {}
    )
    return eng, chords, settings, names, conf


def _chord_durations(chords) -> list[tuple[int, str, float]]:
    """(root, quality, seconds held) for each detected chord."""
    out = []
    for a, b in zip(chords, [*chords[1:], None], strict=True):
        out.append((a.root, a.quality, (b.time if b else a.time + 2.0) - a.time))
    return out


def sounding(notes: list[dict], eng: Engraved) -> list[dict]:
    """Notes as playback sounds them without pedal (pedal.sound_ends)."""
    ends = pedal.sound_ends(
        notes, {n["id"]: eng.notes[n["id"]]["draw_end"] for n in notes if n["id"] in eng.notes}
    )
    return [{**n, "end": ends[n["id"]]} for n in notes]


def pedal_holds(job, stem: str, notes: list[dict], eng: Engraved, settings: Settings):
    """note id -> end with the pedal fully down (pedal.py), and its source.
    Pedal changes follow the drawn harmony; holds start where notes sound."""
    raw = store.read_raw(job.id, stem) or {}
    chord_times = [c.time for c in detect(drawn(notes, eng), eng.grid, settings.chord_rate)]
    segs, source = pedal.segments(raw.get("pedals"), chord_times)
    return pedal.full_hold(sounding(notes, eng), segs), source


def drawn(notes: list[dict], eng: Engraved) -> list[dict]:
    """Notes as the score draws them: each ends where its drawn note ends.
    Chords are read from these, so a tail the score does not show (and the
    page does not play) cannot colour the harmony of the bars after it."""
    out = []
    for n in notes:
        placed = eng.notes.get(n["id"])
        end = placed["draw_end"] if placed else n["end"]
        out.append({**n, "end": max(end, n["start"] + 0.01)})
    return out


def payload(job, stem: str, notes_doc: dict, meta: dict) -> dict:
    eng, chords, settings, names, conf = engrave_stem(job, stem, notes_doc, meta)
    notes = notes_doc.get("notes", [])
    solfege = names == "solfege"
    first = eng.measures[0] if eng.measures else None
    spans = []
    if eng.measures:
        g = eng.grid
        lo = eng.measures[0].start_tick // TPB
        hi = eng.measures[-1].end_tick // TPB
        spans = [g.beats[i + 1] - g.beats[i] for i in range(max(0, lo), min(hi, len(g.beats) - 1))]
    bpm = round(60 / statistics.median(spans)) if spans else job.bpm
    moved = sum(1 for n in notes if abs(eng.notes[n["id"]]["q_start"] - n["start"]) > 0.04)

    holds, pedal_source = pedal_holds(job, stem, notes, eng, settings)
    sound = {n["id"]: n["end"] for n in sounding(notes, eng)}
    out_notes = []
    for n in notes:
        p = eng.notes[n["id"]]
        out_notes.append({**n, **p, "sound_end": sound[n["id"]], "pedal_end": holds.get(n["id"])})
    raw = store.read_raw(job.id, stem) or {}
    return {
        "job": {
            "id": job.id,
            "title": job.title,
            "bpm": job.bpm,
            "key": job.key,
            "scale": job.scale,
        },
        "stem": stem,
        "settings": settings.to_dict(),
        "names": names,
        "bpm": bpm,
        "meter": f"{first.meter}/4" if first else "4/4",
        "key": {
            "name": eng.key.name(solfege),
            "id": key_id(eng.key),
            "fifths": eng.key.fifths,
            "minor": eng.key.minor,
            **eng.key_info,
        },
        "notes": out_notes,
        "chords": [
            {k: v for k, v in c.items() if k not in ("root", "quality", "bass")} for c in chords
        ],
        "measures": [
            {"number": m.number, "start": m.start_sec, "end": m.end_sec, "meter": m.meter}
            for m in eng.measures
        ],
        "mei": to_mei(eng, chords, bpm=bpm, title=job.title or ""),
        "version": notes_doc.get("version", 1),
        # Deleted notes, newest first, for «Borradas» (restore one or all).
        "trash": notes_doc.get("trash") or [],
        "edited": bool(notes_doc.get("edited")),
        "stats": {
            "notes": len(notes),
            "raw_notes": len(raw.get("notes", [])),
            "auto_removed": (notes_doc.get("auto_clean") or {}).get("removed", 0),
            "ghosts_removed": (notes_doc.get("auto_clean") or {}).get("ghosts", 0),
            "moved_over_40ms": moved,
            "duplicates": sum(1 for n in out_notes if n.get("duplicate_of")),
            "moved_pct": round(100 * moved / len(notes)) if notes else 0,
            "beat_confidence": conf,
            "detected_bpm": job.bpm,
            "measures": len(eng.measures),
            "chords": len(chords),
            "meter_source": eng.grid.meter_source,
            "pulse_source": eng.pulse_info["source"],
            "pulse_reason": eng.pulse_info["reason"],
            "pulse_own_available": eng.pulse_info["own_available"],
            "pulse_notes_available": eng.pulse_info["notes_available"],
            "salience": {str(k): v[0] for k, v in eng.grid.salience.items()},
            "beats_inserted": eng.grid.regularized,
            "engine": raw.get("engine"),
            "device": raw.get("device", "cpu"),
            "audio_source": raw.get("audio_source", "stem"),
            "audio_source_reason": raw.get("audio_source_reason"),
            "pedal_source": pedal_source,
            "tuning": raw.get("tuning"),
        },
    }


def musicxml(job, stem: str, notes_doc: dict, meta: dict) -> str:
    eng, chords, *_ = engrave_stem(job, stem, notes_doc, meta)
    return to_musicxml(eng, chords, bpm=job.bpm, title=job.title or "")


def midi(job, stem: str, notes_doc: dict, meta: dict, quantized: bool) -> bytes:
    from app.score.midi import to_midi

    eng, *_ = engrave_stem(job, stem, notes_doc, meta)
    return to_midi(eng, notes_doc.get("notes", []), quantized=quantized)


def _played(job, stem: str, notes_doc: dict, meta: dict):
    """The notes as the page plays them (heard starts and releases, held by
    the Pedal setting), and the engraving they were placed with."""
    eng, _, settings, *_ = engrave_stem(job, stem, notes_doc, meta)
    played = sounding(notes_doc.get("notes", []), eng)
    if settings.pedal:
        holds, _ = pedal_holds(job, stem, notes_doc.get("notes", []), eng, settings)
        played = [
            {**n, "end": pedal.held_end(n["end"], holds.get(n["id"]), settings.pedal)}
            for n in played
        ]
    return eng, played


def performance_midi(
    job,
    stem: str,
    notes_doc: dict,
    meta: dict,
    *,
    hand: str | None = None,
    speed: float = 1.0,
) -> bytes:
    """The score as the page plays it, for Pianoteq (midi.performance_midi):
    second 0 of the file is second 0 of the song (divided by `speed`).
    `hand` "R" / "L": only that hand's notes (its engraved staff), to
    practise the other one."""
    from app.score.engrave import STAFF_TREBLE
    from app.score.midi import performance_midi as build

    eng, played = _played(job, stem, notes_doc, meta)
    treble = {
        n["id"]: eng.notes[n["id"]]["staff"] == STAFF_TREBLE for n in played if n["id"] in eng.notes
    }
    if hand in ("R", "L"):
        played = [n for n in played if treble.get(n["id"], True) == (hand == "R")]
    return build(played, treble, cents=playback_cents(job, stem), speed=speed)


def legacy_performance_midi(job, stem: str, notes_doc: dict, meta: dict) -> bytes:
    """What Pianoteq was given before performance_midi (the song's tempo map
    in it): the name its existing renders were saved under, so they are kept
    rather than rendered again (api/score.py adopts them)."""
    from app.score.midi import to_midi

    eng, played = _played(job, stem, notes_doc, meta)
    return to_midi(eng, played, quantized=False, cents=playback_cents(job, stem))


def playback_cents(job, stem: str) -> float:
    """How far from A440 playback is tuned: the song's own offset when the
    transcription corrected it (tuning.py), so the MIDI plays in tune with
    the stem and the song; 0 otherwise."""
    t = (store.read_raw(job.id, stem) or {}).get("tuning") or {}
    return float(t["cents"]) if t.get("corrected") and t.get("cents") else 0.0
