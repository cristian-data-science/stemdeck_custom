"""Transcription worker: one stem in, raw notes JSON out.

Run as a separate process (app/score/transcribe.py launches it) so the model's
memory -- and GPU memory, on CUDA -- is released when it exits, the same reason
lyrics transcription runs in app/pipeline/transcribe_worker.py.

Progress: "Segment i / N" on stdout, flushed per batch; the parent reads
those lines. The parent also runs this with PYTHONUNBUFFERED: the piano
engine's own prints are unflushed, and on a pipe they sat in an 8 KB buffer
until the end, so the page showed 0% for the whole run and the parent's stall
watchdog saw nothing for minutes.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path


def _batched_forward(batch: int):
    """The engine's pytorch_utils.forward, in batches and with flushed
    progress. Upstream runs one 10 s segment at a time (batch_size=1 is hard
    coded in PianoTranscription.transcribe). On an RTX 5070 its cuDNN GRU costs
    ~200 ms of CPU-side launch per call whatever the batch, so batching is
    most of the GPU speed-up (~30x over the CPU on a 90 s excerpt, measured)."""
    import numpy as np
    import torch
    from piano_transcription_inference.pytorch_utils import move_data_to_device

    def forward(model, x, **_upstream):  # upstream passes batch_size=1: ignored
        device = next(model.parameters()).device
        out: dict[str, list] = {}
        total = len(x)
        model.eval()
        for i in range(0, total, batch):
            chunk = move_data_to_device(x[i : i + batch], device)
            with torch.no_grad():
                result = model(chunk)
            for key, value in result.items():
                out.setdefault(key, []).append(value.data.cpu().numpy())
            print(f"Segment {min(i + batch, total)} / {total}", flush=True)
        return {key: np.concatenate(value, axis=0) for key, value in out.items()}

    return forward


def run(audio_path: Path, out_path: Path, checkpoint: Path, device: str) -> int:
    import librosa
    import piano_transcription_inference.inference as engine
    import torch
    from piano_transcription_inference import PianoTranscription, sample_rate

    print("PHASE load", flush=True)
    audio, _ = librosa.load(str(audio_path), sr=sample_rate, mono=True)
    duration = len(audio) / sample_rate
    model = PianoTranscription(device=torch.device(device), checkpoint_path=str(checkpoint))
    cuda = device == "cuda"
    # Batching alone is the speed-up. cudnn.benchmark only added autotuning
    # time; batch 16 on the GPU gave exactly the CPU's notes (F1 1.000 on a
    # 90 s excerpt), measured 2026-10-27.
    batch = max(1, int(os.environ.get("STEMDECK_SCORE_BATCH", 16 if cuda else 1)))
    # No fp16: under autocast this model returned zero notes on a 9-minute song.
    engine.forward = _batched_forward(batch)
    print(f"PHASE transcribe device={device} batch={batch}", flush=True)
    result = model.transcribe(audio, None)

    # How sure the model was of each attack: its onset output at the note's
    # first frames (0-1). A re-strike it half-hears in the reverb of a dense
    # pedalled passage sits low (ghosts.py uses it).
    onsets = (result.get("output_dict") or {}).get("reg_onset_output")
    notes = []
    for ev in result["est_note_events"]:
        start, end = float(ev["onset_time"]), float(ev["offset_time"])
        if end <= start:
            end = start + 0.05
        note = {
            "midi": int(ev["midi_note"]),
            "start": round(start, 4),
            "end": round(end, 4),
            "velocity": max(1, min(127, int(ev["velocity"]))),
        }
        if onsets is not None:
            p, f = int(ev["midi_note"]) - 21, int(round(start * 100))
            if 0 <= p < onsets.shape[1] and f < onsets.shape[0]:
                note["onset"] = round(float(onsets[max(0, f - 2) : f + 3, p].max()), 3)
        notes.append(note)
    pedals = [
        {"start": round(float(p["onset_time"]), 4), "end": round(float(p["offset_time"]), 4)}
        for p in result.get("est_pedal_events", [])
    ]
    notes.sort(key=lambda n: (n["start"], n["midi"]))
    out = {
        "engine": "piano_transcription_inference",
        "device": device,
        "duration": duration,
        "notes": notes,
        "pedals": pedals,
    }
    tmp = out_path.with_suffix(".tmp")
    tmp.write_text(json.dumps(out), encoding="utf-8")
    tmp.replace(out_path)
    print(f"DONE {len(notes)}", flush=True)
    return 0


def run_basic_pitch(
    audio_path: Path, out_path: Path, min_midi: int | None, max_midi: int | None
) -> int:
    import librosa

    from app.score import basic_pitch_onnx as bp

    print("PHASE load", flush=True)
    audio, _ = librosa.load(str(audio_path), sr=bp.AUDIO_SAMPLE_RATE, mono=True)
    print("PHASE transcribe", flush=True)

    def progress(i: int, n: int) -> None:
        print(f"Segment {i} / {n}", flush=True)

    output = bp.run_model(audio.astype("float32"), progress)
    notes = bp.notes_from_output(output, min_midi=min_midi, max_midi=max_midi)
    out = {
        "engine": "basic_pitch",
        "device": "cpu",
        "duration": len(audio) / bp.AUDIO_SAMPLE_RATE,
        "notes": notes,
        "pedals": [],
    }
    tmp = out_path.with_suffix(".tmp")
    tmp.write_text(json.dumps(out), encoding="utf-8")
    tmp.replace(out_path)
    print(f"DONE {len(notes)}", flush=True)
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--engine", default="piano", choices=("piano", "basic_pitch"))
    ap.add_argument("--audio", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--checkpoint", default="")
    ap.add_argument("--device", default="cpu")
    ap.add_argument("--min-midi", type=int, default=None)
    ap.add_argument("--max-midi", type=int, default=None)
    args = ap.parse_args(argv)
    if args.engine == "basic_pitch":
        return run_basic_pitch(Path(args.audio), Path(args.out), args.min_midi, args.max_midi)
    return run(Path(args.audio), Path(args.out), Path(args.checkpoint), args.device)


if __name__ == "__main__":
    sys.exit(main())
