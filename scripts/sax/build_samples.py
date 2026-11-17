"""Real saxophone notes for «🎷 Saxo», from the University of Iowa Musical
Instrument Samples (MIS): alto and soprano saxophone, with vibrato, pp / mf /
ff, every chromatic note of the instrument, recorded by Michael Giles (1997).
"Freely available ... may be downloaded and used for any projects, without
restrictions" (https://theremin.music.uiowa.edu/MIS.html).

The MIS files hold one chromatic run each (AltoSax.Vib.mf.C4B4.aiff: C4 to
B4). This cuts each run into its notes at the silences, checks every note's
pitch against the one it should be (pYIN), keeps how far off it is (cents,
corrected when played), evens the loudness inside each dynamic, and writes
each note as a small mono MP3, with a manifest the page reads.

Usage:
  1. Download and unzip into one folder:
       sound files/MIS/Woodwinds/altosaxophone/AltoSax.Vib.zip       -> <src>/alto/
       sound files/MIS/Woodwinds/sopranosaxophone/SopSax.Vib.zip     -> <src>/soprano/
       sound files/MIS/Woodwinds/altosaxophone/AltoSax.NoVib.zip     -> <src>/alto-novib/
       sound files/MIS/Woodwinds/sopranosaxophone/SopSax.NoVib.zip   -> <src>/soprano-novib/
     (https://theremin.music.uiowa.edu/MISaltosaxophone.html, ...soprano...)
  2. python scripts/sax/build_samples.py <src> static/audio/sax
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
import tempfile
from pathlib import Path

import librosa
import numpy as np
import soundfile as sf

NAMES = {"C": 0, "Db": 1, "D": 2, "Eb": 3, "E": 4, "F": 5, "Gb": 6, "G": 7, "Ab": 8, "A": 9, "Bb": 10, "B": 11}
RANGE_RE = re.compile(r"\.(pp|mf|ff)\.([A-G]b?)(\d)([A-G]b?)(\d)\.aiff?$", re.I)
SR = 44100
HOP = 512
RMS_TARGET = {"pp": 0.05, "mf": 0.11, "ff": 0.19}  # sustain loudness per dynamic, evened inside it
MAX_SEC = 5.0
FADE_OUT = 0.08


def midi_of(name: str, octave: str) -> int:
    return 12 * (int(octave) + 1) + NAMES[name]


def segments(y: np.ndarray, expected: int) -> list[tuple[int, int]]:
    """The notes of a run: stretches louder than a threshold, apart by
    silences; the threshold that gives the expected count."""
    rms = librosa.feature.rms(y=y, frame_length=2048, hop_length=HOP)[0]
    db = 20 * np.log10(np.maximum(rms, 1e-9) / max(rms.max(), 1e-9))
    for thr in (-40, -36, -44, -32, -48, -28, -52):
        on = db > thr
        segs = []
        i = 0
        while i < len(on):
            if not on[i]:
                i += 1
                continue
            j = i
            while j < len(on) and on[j]:
                j += 1
            segs.append([i, j])
            i = j
        merged = []  # a dip inside a note is not a silence
        for s in segs:
            if merged and (s[0] - merged[-1][1]) * HOP / SR < 0.25:
                merged[-1][1] = s[1]
            else:
                merged.append(s)
        merged = [s for s in merged if (s[1] - s[0]) * HOP / SR > 0.3]
        if len(merged) == expected:
            return [(a * HOP, b * HOP) for a, b in merged]
    raise ValueError(f"{expected} notes expected, the silences gave no such count")


SPEAK = 0.35  # of the note's sustained level: where it has started to sound
LEAD = 0.015  # s kept before it (the breath into the note)


def speaks_at(y: np.ndarray, a: int, b: int) -> int:
    """Where the note speaks: many MIS notes start soft and swell (up to a
    second to reach their level, two thirds of them over 0.15 s), so a note
    cut where anything is heard played silence first: a short note in a song
    ended before it sounded. The first frame at SPEAK of the note's
    sustained level (its middle half), less LEAD."""
    seg = y[a:b]
    hop = 128
    rms = librosa.feature.rms(y=seg, frame_length=512, hop_length=hop)[0]
    if rms.size < 8:
        return a
    sustain = float(np.median(rms[rms.size // 4 : 3 * rms.size // 4]))
    first = int(np.argmax(rms >= SPEAK * sustain))
    return max(0, a + first * hop - int(LEAD * SR))


def pitch_cents(y: np.ndarray, midi: int) -> float:
    """How far the note is from `midi`, in cents (its steady part)."""
    a, b = int(len(y) * 0.2), int(len(y) * 0.8)
    f0, voiced, _ = librosa.pyin(y[a:b], fmin=librosa.midi_to_hz(midi - 7), fmax=librosa.midi_to_hz(midi + 7), sr=SR)
    f = f0[voiced]
    if f.size < 5:
        raise ValueError(f"no pitch found for {midi}")
    return float(np.median(librosa.hz_to_midi(f)) - midi) * 100


def build(src: Path, out: Path) -> None:
    ffmpeg = "ffmpeg"
    try:
        sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
        from app.core.config import ffmpeg_executable

        ffmpeg = ffmpeg_executable()
    except Exception:  # noqa: BLE001 -- run outside the app: ffmpeg on PATH
        pass
    # With vibrato: the notes as written («Notas exactas»). Without
    # (-novib, mf and ff only): «Expresivo», where the vibrato, the slides and
    # the swells are the singer's own, played through the recording.
    for sax in ("alto", "soprano", "alto-novib", "soprano-novib"):
        files = sorted((src / sax).glob("*.aif*"))
        if sax.endswith("-novib"):
            files = [f for f in files if ".pp." not in f.name]
        if not files:
            print(f"{sax}: no files in {src / sax}, skipped")
            continue
        manifest: dict = {
            "sax": sax,
            "source": "University of Iowa Electronic Music Studios, Musical Instrument Samples (MIS), "
            "https://theremin.music.uiowa.edu/MIS.html",
            "player": "Michael Giles (1997)",
            "terms": "freely available ... may be downloaded and used for any projects, without restrictions",
            "layers": ["mf", "ff"] if sax.endswith("-novib") else ["pp", "mf", "ff"],
            "vibrato": not sax.endswith("-novib"),
            "notes": {},
        }
        for f in files:
            m = RANGE_RE.search(f.name)
            if not m:
                continue
            dyn = m.group(1).lower()
            lo, hi = midi_of(m.group(2), m.group(3)), midi_of(m.group(4), m.group(5))
            y, sr = sf.read(f, dtype="float32", always_2d=True)
            y = y.mean(axis=1)
            if sr != SR:
                y = librosa.resample(y, orig_sr=sr, target_sr=SR)
            segs = segments(y, hi - lo + 1)
            for k, (a, b) in enumerate(segs):
                midi = lo + k
                a = speaks_at(y, a, b)
                b = min(len(y), b + int(0.15 * SR), a + int(MAX_SEC * SR))
                note = y[a:b].copy()
                cents = pitch_cents(note, midi)
                if abs(cents) > 60:
                    raise ValueError(f"{f.name}: note {k} measures {cents:+.0f} cents from {midi}")
                body = note[int(0.15 * SR) : max(int(0.16 * SR), len(note) - int(0.3 * SR))]
                rms = float(np.sqrt(np.mean(body**2))) or 1e-6
                note *= RMS_TARGET[dyn] / rms
                peak = float(np.max(np.abs(note)))
                if peak > 0.98:
                    note *= 0.98 / peak
                n_in, n_out = int(0.006 * SR), int(FADE_OUT * SR)
                note[:n_in] *= np.linspace(0, 1, n_in)
                note[-n_out:] *= np.linspace(1, 0, n_out)
                dest = out / sax / dyn / f"{midi}.mp3"
                dest.parent.mkdir(parents=True, exist_ok=True)
                with tempfile.TemporaryDirectory() as tmp:
                    wav = Path(tmp) / "n.wav"
                    sf.write(wav, note, SR, subtype="PCM_16")
                    subprocess.run(
                        [ffmpeg, "-nostdin", "-loglevel", "error", "-y", "-i", str(wav), "-ac", "1",
                         "-c:a", "libmp3lame", "-b:a", "96k", str(dest)],
                        check=True, stdin=subprocess.DEVNULL,
                    )  # fmt: skip
                entry = manifest["notes"].setdefault(str(midi), {})
                entry[dyn] = {"cents": round(cents, 1), "sec": round(len(note) / SR, 2)}
            print(f"{sax} {dyn} {m.group(2)}{m.group(3)}-{m.group(4)}{m.group(5)}: {len(segs)} notes")
        (out / sax / "manifest.json").write_text(json.dumps(manifest, indent=1), encoding="utf-8")
        midis = sorted(int(k) for k in manifest["notes"])
        print(f"{sax}: {len(midis)} notes, MIDI {midis[0]}-{midis[-1]}")


if __name__ == "__main__":
    build(Path(sys.argv[1]), Path(sys.argv[2]))
