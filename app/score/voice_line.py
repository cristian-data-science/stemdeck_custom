"""A sung line as notes, for «🎷 Saxo»: pitch tracking (pYIN), not a
transcription model.

Basic Pitch, the score module's engine for the vocals stem, is built for
instruments: on a voice it misses the slides and the vibrato. Measured on
«Esta noche» (Francisca Valenzuela), 90 s of the vocals stem, against pYIN's
contour: only 71 % of the sung time had a note, and 15 % of what it had was
off by a semitone. The saxophone played wrong notes and long silences.

Here: pYIN's f0 (one pitch at a time, a voice's whole range), the singer's
tuning measured from it (a voice is rarely at A440 exactly: the notes are
read against the song's own pitch), each frame on the nearest semitone with
hysteresis (vibrato and a scoop into the note do not make notes of their
own), then runs of one semitone as notes. Measured: see tests/test_sax.py
(a synthetic voice with vibrato and slides) and docs/partitura.md.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path

import numpy as np

logger = logging.getLogger(__name__)

SR = 16000
HOP = 160  # 10 ms
FRAME = 1024
RESOLUTION = 0.2  # semitones per pitch bin: the notes are whole semitones anyway
CHUNKS = 8  # the song is tracked in this many pieces at once (one process each)
CHUNK_PAD = 0.1  # s of overlap on each side of a piece
FMIN, FMAX = 70.0, 1100.0  # a low male voice to a soprano's top
HOLD = 0.62  # semitones: how far the pitch must leave a note to change it...
HOLD_SEC = 0.06  # ...and for how long (vibrato swings back sooner)
MIN_NOTE = 0.09  # s
JOIN_GAP = 0.05  # s of unvoiced between two frames of one note (a consonant)
SPLIT_GAP = 0.04  # longer than JOIN_GAP never; shorter, the same note goes on


def tuning_cents(midi_f0: np.ndarray) -> float:
    """The voice's tuning against A440, in cents: the circular mean of every
    voiced frame's distance to the nearest semitone (-50..50)."""
    v = midi_f0[~np.isnan(midi_f0)]
    if v.size < 50:
        return 0.0
    ang = 2 * np.pi * (v - np.round(v))
    return float(np.angle(np.mean(np.exp(1j * ang))) / (2 * np.pi) * 100)


def quantise(midi_f0: np.ndarray, cents: float = 0.0, hold_sec: float | None = None) -> np.ndarray:
    """Each voiced frame on a semitone, with hysteresis: the note held stays
    until the pitch is more than HOLD away for HOLD_SEC (`hold_sec`)."""
    hold_frames = max(1, int(round((HOLD_SEC if hold_sec is None else hold_sec) * SR / HOP)))
    f = midi_f0 - cents / 100.0
    out = np.full(f.shape, np.nan)
    cur = None
    away = 0
    for i, x in enumerate(f):
        if np.isnan(x):
            continue
        near = int(round(x))
        if cur is None:
            cur = near
        elif near != cur and abs(x - cur) > HOLD:
            away += 1
            if away >= hold_frames:
                cur = near
                away = 0
                # The frames it took to be sure belong to the new note.
                for j in range(i - hold_frames + 1, i):
                    if j >= 0 and not np.isnan(out[j]):
                        out[j] = cur
        else:
            away = 0
        out[i] = cur
    return out


def notes_from(q: np.ndarray, energy: np.ndarray | None = None) -> list[dict]:
    """Runs of one semitone as notes; a short unvoiced gap inside one pitch
    (a consonant) does not split it."""
    sec = HOP / SR
    notes: list[dict] = []
    i = 0
    n = len(q)
    while i < n:
        if np.isnan(q[i]):
            i += 1
            continue
        p = q[i]
        j = i
        last = i
        while j < n:
            if np.isnan(q[j]):
                k = j
                while k < n and np.isnan(q[k]):
                    k += 1
                if k < n and q[k] == p and (k - j) * sec <= JOIN_GAP:
                    j = k
                    continue
                break
            if q[j] != p:
                break
            last = j
            j += 1
        start, end = i * sec, (last + 1) * sec
        if end - start >= MIN_NOTE:
            vel = 80
            if energy is not None:
                e = float(np.max(energy[i : last + 1]))
                vel = int(np.clip(40 + 87 * e, 30, 127))
            notes.append(
                {"start": round(start, 3), "end": round(end, 3), "midi": int(p), "velocity": vel}
            )
        i = j
    return notes


def _pyin(y: np.ndarray) -> np.ndarray:
    import librosa

    f0, voiced, _ = librosa.pyin(
        y,
        fmin=FMIN,
        fmax=FMAX,
        sr=SR,
        hop_length=HOP,
        frame_length=FRAME,
        resolution=RESOLUTION,
        center=True,
    )
    return np.where(voiced, librosa.hz_to_midi(f0), np.nan)


def pitch(y: np.ndarray) -> np.ndarray:
    """The sung pitch per HOP: RMVPE when its weights are here (robust to
    the band left in the stem; ~1 s a song on a GPU), else pYIN."""
    from app.score import rmvpe

    n = 1 + len(y) // HOP
    if rmvpe.available():
        try:
            f0, _conf = rmvpe.track(y)
            return f0[:n] if len(f0) >= n else np.pad(f0, (0, n - len(f0)), constant_values=np.nan)
        except Exception:  # noqa: BLE001 -- pYIN does it, slower
            logger.warning("rmvpe failed; pYIN instead", exc_info=True)
    return track(y)


def tracker() -> str:
    from app.score import rmvpe

    return "rmvpe" if rmvpe.available() else "pyin"


def track(y: np.ndarray, parallel: bool = True) -> np.ndarray:
    """pYIN's f0 in MIDI per HOP (NaN where unvoiced).

    pYIN runs on one core and took 47-56 s on a 3:16 vocals stem. The song is
    cut in CHUNKS pieces (a little overlap each side) tracked in as many
    processes: 6 s. Threads did not help (the GIL). Without processes (a
    frozen build, a sandbox) it runs in this one, the same result.
    """
    n_frames = 1 + len(y) // HOP
    if not parallel or len(y) < SR * 20:
        out = _pyin(y)
        return (
            out[:n_frames]
            if len(out) >= n_frames
            else np.pad(out, (0, n_frames - len(out)), constant_values=np.nan)
        )
    pad = int(CHUNK_PAD * SR) // HOP * HOP
    step = (len(y) // CHUNKS) // HOP * HOP
    bounds = [(i * step, len(y) if i == CHUNKS - 1 else (i + 1) * step) for i in range(CHUNKS)]
    pieces = [y[max(0, a - pad) : min(len(y), b + pad)] for a, b in bounds]
    try:
        from concurrent.futures import ProcessPoolExecutor

        with ProcessPoolExecutor(max_workers=min(CHUNKS, os.cpu_count() or 1)) as ex:
            tracked = list(ex.map(_pyin, pieces))
    except Exception:  # noqa: BLE001 -- no processes here: one after the other
        logger.warning("voice line: tracking in one process", exc_info=True)
        tracked = [_pyin(piece) for piece in pieces]
    out = np.full(n_frames, np.nan)
    for (a, b), f in zip(bounds, tracked, strict=True):
        skip = (a - max(0, a - pad)) // HOP  # the overlap before this piece's own part
        want = (b - a) // HOP + (1 if b == len(y) else 0)
        part = f[skip : skip + want]
        i = a // HOP
        out[i : i + len(part)] = part[: max(0, min(len(part), n_frames - i))]
    return out


SMOOTH_SEC = 0.17  # about one vibrato period (5-7 Hz): the wobble averages out
GATE = 0.3  # frames quieter than this share of the voice's loud level: a tail, not singing
FILL_SEC = 0.05  # unvoiced holes this short inside singing: the tracker blinking


def _fill(midi_f0: np.ndarray) -> np.ndarray:
    """Unvoiced holes up to FILL_SEC inside a run: the tracker blinking."""
    f = midi_f0.copy()
    n = len(f)
    fill = int(round(FILL_SEC * SR / HOP))
    i = 0
    while i < n:
        if np.isnan(f[i]):
            j = i
            while j < n and np.isnan(f[j]):
                j += 1
            if i > 0 and j < n and j - i <= fill:
                f[i:j] = np.linspace(f[i - 1], f[j], j - i + 2)[1:-1]
            i = j
        else:
            i += 1
    return f


def _runs(f: np.ndarray):
    """(start, end) of each voiced run."""
    n = len(f)
    i = 0
    while i < n:
        if np.isnan(f[i]):
            i += 1
            continue
        j = i
        while j < n and not np.isnan(f[j]):
            j += 1
        yield i, j
        i = j


def smooth(midi_f0: np.ndarray) -> np.ndarray:
    """Short holes filled, then a moving average over one vibrato period,
    within each voiced run (never across a rest)."""
    f = _fill(midi_f0)
    n = len(f)
    w = max(1, int(round(SMOOTH_SEC * SR / HOP)))
    out = np.full(n, np.nan)
    i = 0
    while i < n:
        if np.isnan(f[i]):
            i += 1
            continue
        j = i
        while j < n and not np.isnan(f[j]):
            j += 1
        run = f[i:j]
        if len(run) >= w:
            k = np.ones(w) / w
            pad = np.pad(run, (w // 2, w - 1 - w // 2), mode="edge")
            out[i:j] = np.convolve(pad, k, mode="valid")
        else:
            out[i:j] = np.median(run)
        i = j
    return out


INSTRUMENT_MEDIAN = 0.07  # s: an instrument's line, steadied without blurring its note changes
INSTRUMENT_HOLD = 0.04  # s: HOLD_SEC for an instrument (its notes change at once)


def smooth_instrument(midi_f0: np.ndarray) -> np.ndarray:
    """An instrument's pitch (a saxophone, a trumpet, a violin): a running
    median, not the voice's moving average. An instrument changes note at
    once; averaged over a vibrato period, a fast passage blurred into the
    notes between (on a known saxophone line over pads: 64-73 % of its notes
    right, 67-81 % with the median)."""
    from scipy.ndimage import median_filter

    f = _fill(midi_f0)
    out = np.full(len(f), np.nan)
    w = max(1, int(round(INSTRUMENT_MEDIAN * SR / HOP))) | 1
    for i, j in _runs(f):
        k = min(w, (j - i) if (j - i) % 2 else (j - i - 1)) or 1
        out[i:j] = median_filter(f[i:j], size=k, mode="nearest")
    return out


OCTAVE_WIN = 0.6  # s around a frame: what octave the voice is singing in


def fix_octaves(midi_f0: np.ndarray) -> np.ndarray:
    """Octave slips of the tracker (it locks for a moment on the octave
    below, often a bass left in the stem): a frame more than 9 semitones
    from the median around it moves by octaves toward it."""
    f = midi_f0.copy()
    w = max(3, int(round(OCTAVE_WIN * SR / HOP)))
    idx = np.where(~np.isnan(f))[0]
    if idx.size < 3:
        return f
    vals = f[idx]
    for i in idx:
        lo = np.searchsorted(idx, i - w // 2)
        hi = np.searchsorted(idx, i + w // 2, side="right")
        med = float(np.median(vals[lo:hi]))
        d = f[i] - med
        if abs(d) > 9:
            f[i] -= 12 * round(d / 12)
    return f


def voice_notes(wav: Path) -> dict:
    """{"notes": [...], "cents": the voice's tuning} for a vocals stem."""
    import librosa

    y, _ = librosa.load(str(wav), sr=SR, mono=True)
    f0 = pitch(y)
    rms = librosa.feature.rms(y=y, frame_length=FRAME, hop_length=HOP, center=True)[0]
    rms = rms[: len(f0)] if len(rms) >= len(f0) else np.pad(rms, (0, len(f0) - len(rms)))
    voiced = ~np.isnan(f0)
    peak = float(np.percentile(rms[voiced], 95)) if voiced.any() else 1.0
    energy = np.clip(rms / max(peak, 1e-6), 0, 1)
    f0 = np.where(energy >= GATE, f0, np.nan)  # reverb tails and bleed in the rests
    f0 = fix_octaves(f0)
    cents = tuning_cents(f0)
    q = quantise(smooth(f0), cents)
    notes = notes_from(q, energy)
    logger.info("voice line of %s: %d notes, %+.1f cents", wav.name, len(notes), cents)
    return {"notes": notes, "cents": round(cents, 1), "engine": "pyin"}


FILL_MIN = 0.15  # s: a pYIN note where the transcription has nothing, kept from this long


TRUST = 5  # semitones: pYIN's pitch replaces the transcription's up to this far (not by octaves)


def merge(
    line: list[dict], q: np.ndarray, own: list[dict], energy: np.ndarray | None = None
) -> list[dict]:
    """The transcription's notes (their starts and ends: it tells notes apart
    well) with pYIN's pitch where they disagree by a semitone or two (pYIN
    reads a sung pitch finer), its octave kept (pYIN slips octaves on the
    band left in the stem); pYIN's own notes where the transcription has
    nothing (a slide or a soft phrase it missed)."""
    sec = HOP / SR
    out = []
    for n in line:
        a = int(n["start"] / sec)
        b = max(a + 1, int(n["end"] / sec))
        if energy is not None and float(np.mean(energy[a:b])) < GATE * 0.8:
            continue  # the band left in the stem, in a rest of the voice
        seg = q[a:b]
        seg = seg[~np.isnan(seg)]
        midi = n["midi"]
        if seg.size >= 0.4 * (b - a):
            vals, counts = np.unique(seg, return_counts=True)
            cand = int(vals[np.argmax(counts)])
            d = cand - midi
            if d and abs(d) <= TRUST and abs(d) != 12:
                midi = cand
        out.append({**n, "midi": int(midi)})
    for m in own:
        if m["end"] - m["start"] < FILL_MIN:
            continue
        cover = sum(max(0.0, min(m["end"], n["end"]) - max(m["start"], n["start"])) for n in out)
        if cover <= 0.3 * (m["end"] - m["start"]):
            out.append(m)
    out.sort(key=lambda n: n["start"])
    for i in range(len(out) - 1):
        out[i]["end"] = min(out[i]["end"], out[i + 1]["start"])
    return [n for n in out if n["end"] - n["start"] >= 0.06]


_LAST: dict = {}  # the last analysis' pitch contour (for contour())


def analyse(wav: Path, kind: str = "voice") -> tuple[np.ndarray, np.ndarray, float, list[dict]]:
    """The tracker's quantised line (q), the energy, the tuning and its own
    notes. The pitch itself (before quantising) is kept for contour().
    `kind`: "voice", or "instrument" (a lead instrument in "other": its
    notes change at once, see smooth_instrument)."""
    import librosa

    y, _ = librosa.load(str(wav), sr=SR, mono=True)
    f0 = pitch(y)
    rms = librosa.feature.rms(y=y, frame_length=FRAME, hop_length=HOP, center=True)[0]
    rms = rms[: len(f0)] if len(rms) >= len(f0) else np.pad(rms, (0, len(f0) - len(rms)))
    voiced = ~np.isnan(f0)
    peak = float(np.percentile(rms[voiced], 95)) if voiced.any() else 1.0
    energy = np.clip(rms / max(peak, 1e-6), 0, 1)
    f0 = np.where(energy >= GATE, f0, np.nan)
    f0 = fix_octaves(f0)
    cents = tuning_cents(f0)
    if kind == "instrument":
        q = quantise(smooth_instrument(f0), cents, INSTRUMENT_HOLD)
    else:
        q = quantise(smooth(f0), cents)
    _LAST.update(wav=str(wav), f0=f0, energy=energy)
    return q, energy, cents, notes_from(q, energy)


CONTOUR_HOP = 2  # frames per contour point: 20 ms


def contour(wav: Path) -> dict | None:
    """The sung pitch and loudness every 20 ms (the analysis just done), for
    the saxophone to play the line as sung: its slides, vibrato and swells
    («Expresivo»). {"hop": s, "midi": [..|None], "level": [0..1]}."""
    if _LAST.get("wav") != str(wav):
        return None
    f0 = _LAST["f0"][::CONTOUR_HOP]
    level = _LAST["energy"][::CONTOUR_HOP]
    return {
        "hop": round(HOP * CONTOUR_HOP / SR, 4),
        "midi": [None if np.isnan(x) else round(float(x), 2) for x in f0],
        "level": [round(float(x), 2) for x in level],
    }


CHORD_SEC = 0.03
MIN_SEC = 0.06


def skyline(notes: list[dict]) -> list[dict]:
    """One line from a transcription: at each onset the highest note, each
    one cut where the next begins (static/js/sax/melody.js skyline, the same
    rule)."""
    s = sorted(
        (n for n in notes if n.get("end", 0) > n.get("start", 0)),
        key=lambda n: (n["start"], -n["midi"]),
    )
    line: list[dict] = []
    for n in s:
        if line and n["start"] - line[-1]["start"] < CHORD_SEC:
            if n["midi"] > line[-1]["midi"]:
                line[-1]["midi"] = n["midi"]
            continue
        end = n.get("sound_end") or n.get("draw_end") or n["end"]
        line.append(
            {"start": n["start"], "end": end, "midi": n["midi"], "velocity": n.get("velocity", 80)}
        )
    for i in range(len(line) - 1):
        line[i]["end"] = min(line[i]["end"], line[i + 1]["start"])
    return [n for n in line if n["end"] - n["start"] >= MIN_SEC]


def sung_line(wav: Path, transcribed: list[dict], analysed=None) -> dict:
    """The line «🎷 Saxo» plays for a voice: the transcription's notes,
    their pitch checked against pYIN, pYIN's notes in what it missed, and
    the voice's tuning (the saxophone plays at it). `analysed`: analyse(wav)
    already done (beside the transcription)."""
    q, energy, cents, own = analysed if analysed is not None else analyse(wav)
    notes = merge(skyline(transcribed), q, own, energy)
    logger.info("sung line of %s: %d notes, %+.1f cents", wav.name, len(notes), cents)
    return {"notes": notes, "cents": round(cents, 1), "engine": f"hybrid-{tracker()}"}


def tracked_line(wav: Path, analysed=None, kind: str = "voice") -> dict:
    """With RMVPE, the line is the tracker's own notes: on voices whose notes
    are known (vibrato, slides, a room, the band left in) 94 / 97 / 90 % of
    them right, against 85 / 88 / 78 % merged with Basic Pitch's (and far
    fewer notes where nobody sings). No transcription to wait for either."""
    q, energy, cents, own = analysed if analysed is not None else analyse(wav, kind)
    logger.info("tracked line of %s: %d notes, %+.1f cents", wav.name, len(own), cents)
    engine = tracker() + ("-instrument" if kind == "instrument" else "")
    return {"notes": own, "cents": round(cents, 1), "engine": engine}
