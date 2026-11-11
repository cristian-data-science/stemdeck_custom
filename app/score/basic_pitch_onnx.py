"""Basic Pitch (Spotify) note transcription, ONNX only.

Ported from basic-pitch 0.4.0 (inference.py: windowing and unwrapping;
note_creation.py: output_to_notes_polyphonic, get_infered_onsets,
model_frames_to_time), Copyright 2022 Spotify AB, Apache License 2.0 -- see
app/score/models/BASIC_PITCH_LICENSE.txt and BASIC_PITCH_NOTICE.txt. The model
file app/score/models/basic_pitch_nmp.onnx is the package's own
saved_models/icassp_2022/nmp.onnx, unmodified.

Why a port and not the package: basic-pitch declares TensorFlow on Python
>= 3.11, which has no wheels for this project's Python, and depending on it
would also pull tensorflow-macos/coremltools into the macOS desktop builds. It
needs none of that to run its ONNX model, which is all this module does, with
the onnxruntime the vocal split already installs. Pitch bends and MIDI writing
are left out: the score has no use for them.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import numpy as np

MODEL_PATH = Path(__file__).resolve().parent / "models" / "basic_pitch_nmp.onnx"

FFT_HOP = 256
AUDIO_SAMPLE_RATE = 22050
AUDIO_WINDOW_LENGTH = 2
ANNOTATIONS_FPS = AUDIO_SAMPLE_RATE // FFT_HOP
ANNOT_N_FRAMES = ANNOTATIONS_FPS * AUDIO_WINDOW_LENGTH
AUDIO_N_SAMPLES = AUDIO_SAMPLE_RATE * AUDIO_WINDOW_LENGTH - FFT_HOP
N_OVERLAPPING_FRAMES = 30
MIDI_OFFSET = 21
MAX_FREQ_IDX = 87


def _windows(audio: np.ndarray):
    overlap_len = N_OVERLAPPING_FRAMES * FFT_HOP
    hop = AUDIO_N_SAMPLES - overlap_len
    padded = np.concatenate([np.zeros(overlap_len // 2, dtype=np.float32), audio])
    for i in range(0, padded.shape[0], hop):
        w = padded[i : i + AUDIO_N_SAMPLES]
        if len(w) < AUDIO_N_SAMPLES:
            w = np.pad(w, (0, AUDIO_N_SAMPLES - len(w)))
        yield w.astype(np.float32)


def _unwrap(output: np.ndarray, original_length: int) -> np.ndarray:
    n_olap = N_OVERLAPPING_FRAMES // 2
    if n_olap > 0:
        output = output[:, n_olap:-n_olap, :]
    n_frames = int(np.floor(original_length * (ANNOTATIONS_FPS / AUDIO_SAMPLE_RATE)))
    return output.reshape(output.shape[0] * output.shape[1], output.shape[2])[:n_frames, :]


def run_model(
    audio: np.ndarray, progress: Callable[[int, int], None] | None = None
) -> dict[str, np.ndarray]:
    """audio: mono float32 at AUDIO_SAMPLE_RATE -> {"note", "onset", "contour"}."""
    import onnxruntime as ort

    session = ort.InferenceSession(str(MODEL_PATH), providers=["CPUExecutionProvider"])
    windows = list(_windows(audio))
    out: dict[str, list] = {"note": [], "onset": [], "contour": []}
    for i, w in enumerate(windows):
        note, onset, contour = session.run(
            ["StatefulPartitionedCall:1", "StatefulPartitionedCall:2", "StatefulPartitionedCall:0"],
            {"serving_default_input_2:0": w[None, :, None]},
        )
        out["note"].append(note)
        out["onset"].append(onset)
        out["contour"].append(contour)
        if progress:
            progress(i + 1, len(windows))
    return {k: _unwrap(np.concatenate(v), len(audio)) for k, v in out.items()}


def _frames_to_time(n_frames: int) -> np.ndarray:
    original = np.arange(n_frames) * FFT_HOP / AUDIO_SAMPLE_RATE
    window_numbers = np.floor(np.arange(n_frames) / ANNOT_N_FRAMES)
    window_offset = (FFT_HOP / AUDIO_SAMPLE_RATE) * (
        ANNOT_N_FRAMES - (AUDIO_N_SAMPLES / FFT_HOP)
    ) + 0.0018
    return original - (window_offset * window_numbers)


def _inferred_onsets(onsets: np.ndarray, frames: np.ndarray, n_diff: int = 2) -> np.ndarray:
    diffs = []
    for n in range(1, n_diff + 1):
        appended = np.concatenate([np.zeros((n, frames.shape[1])), frames])
        diffs.append(appended[n:, :] - appended[:-n, :])
    frame_diff = np.min(diffs, axis=0)
    frame_diff[frame_diff < 0] = 0
    frame_diff[:n_diff, :] = 0
    peak = np.max(frame_diff)
    if peak > 0:
        frame_diff = np.max(onsets) * frame_diff / peak
    return np.max([onsets, frame_diff], axis=0)


def _midi_to_idx(midi: float) -> int:
    return int(np.round(midi - MIDI_OFFSET))


def notes_from_output(
    output: dict[str, np.ndarray],
    *,
    onset_thresh: float = 0.5,
    frame_thresh: float = 0.3,
    min_note_ms: float = 127.7,
    min_midi: int | None = None,
    max_midi: int | None = None,
    melodia_trick: bool = True,
    energy_tol: int = 11,
) -> list[dict]:
    """Polyphonic note events: [{"midi", "start", "end", "velocity"}]."""
    from scipy.signal import argrelmax

    frames = output["note"].copy()
    onsets = output["onset"].copy()
    n_frames = frames.shape[0]
    min_len = int(np.round(min_note_ms / 1000 * (AUDIO_SAMPLE_RATE / FFT_HOP)))
    if max_midi is not None:
        onsets[:, _midi_to_idx(max_midi) + 1 :] = 0
        frames[:, _midi_to_idx(max_midi) + 1 :] = 0
    if min_midi is not None:
        onsets[:, : _midi_to_idx(min_midi)] = 0
        frames[:, : _midi_to_idx(min_midi)] = 0
    onsets = _inferred_onsets(onsets, frames)

    peak_mat = np.zeros(onsets.shape)
    peaks = argrelmax(onsets, axis=0)
    peak_mat[peaks] = onsets[peaks]
    onset_idx = np.where(peak_mat >= onset_thresh)
    remaining = frames.copy()
    events: list[tuple[int, int, int, float]] = []

    def clear(i0: int, i1: int, f: int) -> None:
        remaining[i0:i1, f] = 0
        if f < MAX_FREQ_IDX:
            remaining[i0:i1, f + 1] = 0
        if f > 0:
            remaining[i0:i1, f - 1] = 0

    for start, f in zip(onset_idx[0][::-1], onset_idx[1][::-1], strict=True):
        if start >= n_frames - 1:
            continue
        i, k = start + 1, 0
        while i < n_frames - 1 and k < energy_tol:
            k = k + 1 if remaining[i, f] < frame_thresh else 0
            i += 1
        i -= k
        if i - start <= min_len:
            continue
        clear(start, i, f)
        events.append(
            (int(start), int(i), int(f) + MIDI_OFFSET, float(np.mean(frames[start:i, f])))
        )

    if melodia_trick:
        while np.max(remaining) > frame_thresh:
            i_mid, f = np.unravel_index(np.argmax(remaining), remaining.shape)
            remaining[i_mid, f] = 0
            i, k = i_mid + 1, 0
            while i < n_frames - 1 and k < energy_tol:
                k = k + 1 if remaining[i, f] < frame_thresh else 0
                clear(i, i + 1, f)
                i += 1
            i_end = i - 1 - k
            i, k = i_mid - 1, 0
            while i > 0 and k < energy_tol:
                k = k + 1 if remaining[i, f] < frame_thresh else 0
                clear(i, i + 1, f)
                i -= 1
            i_start = i + 1 + k
            if i_end - i_start <= min_len:
                continue
            events.append(
                (
                    int(i_start),
                    int(i_end),
                    int(f) + MIDI_OFFSET,
                    float(np.mean(frames[i_start:i_end, f])),
                )
            )

    times = _frames_to_time(n_frames + 1)
    notes = []
    for s, e, midi, amp in events:
        start, end = float(times[s]), float(times[min(e, n_frames)])
        if end <= start or start < 0:
            continue
        notes.append(
            {
                "midi": midi,
                "start": round(start, 4),
                "end": round(end, 4),
                "velocity": max(1, min(127, int(round(127 * min(1.0, amp * 1.6))))),
            }
        )
    notes.sort(key=lambda n: (n["start"], n["midi"]))
    return notes
