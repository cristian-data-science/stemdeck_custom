"""RMVPE: a sung pitch, robust to the band left in a vocals stem.

Wei, Cao, Dan, Chen, "RMVPE: A Robust Model for Vocal Pitch Estimation in
Polyphonic Music" (Interspeech 2023; Dream-High/RMVPE, Apache-2.0). The
network below follows the RVC project's implementation (RVC-Project/
Retrieval-based-Voice-Conversion-WebUI, infer/rmvpe.py, MIT, Copyright (c)
2023 liujing04, 源文雨, Ftps), whose weights it loads: rmvpe.pt from
huggingface.co/lj1995/VoiceConversionWebUI (181 MB, sha256 6d62215f...ec193),
kept out of the repository in .run/tools/rmvpe/ (or STEMDECK_RMVPE). RVC asks
for its models to be used responsibly; here it only reads a pitch.

A log-mel (128 bands, 16 kHz, hop 160) through a U-Net and a BiGRU gives 360
pitch bins (20 cents apart) every 10 ms; the pitch is the salience-weighted
average around the peak, unvoiced where the peak is under a threshold.
Without the weights (or torch), voice_line uses pYIN.
"""

from __future__ import annotations

import hashlib
import logging
import os
import threading
from functools import lru_cache
from pathlib import Path

import numpy as np

logger = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parents[2]
SHA256 = "6d62215f4306e3ca278246188607209f09af3dc77ed4232efdd069798c4ec193"
SR = 16000
HOP = 160
THRESHOLD = 0.03  # peak salience under this: unvoiced (RVC's value)
CHUNK = 32 * 96  # mel frames per pass (~31 s): memory stays small on any GPU
OVERLAP = 64  # frames of context on each side of a pass
_LOCK = threading.Lock()


def weights_path() -> Path:
    env = os.environ.get("STEMDECK_RMVPE")
    return Path(env) if env else ROOT / ".run" / "tools" / "rmvpe" / "rmvpe.pt"


def available() -> bool:
    if os.environ.get("STEMDECK_RMVPE_OFF") == "1":
        return False
    try:
        import torch  # noqa: F401
    except Exception:  # noqa: BLE001
        return False
    return weights_path().is_file()


def _net():
    import torch
    from torch import nn

    class ConvBlockRes(nn.Module):
        def __init__(self, i, o, momentum=0.01):
            super().__init__()
            self.conv = nn.Sequential(
                nn.Conv2d(i, o, (3, 3), (1, 1), (1, 1), bias=False),
                nn.BatchNorm2d(o, momentum=momentum),
                nn.ReLU(),
                nn.Conv2d(o, o, (3, 3), (1, 1), (1, 1), bias=False),
                nn.BatchNorm2d(o, momentum=momentum),
                nn.ReLU(),
            )
            if i != o:
                self.shortcut = nn.Conv2d(i, o, (1, 1))

        def forward(self, x):
            return self.conv(x) + (self.shortcut(x) if hasattr(self, "shortcut") else x)

    class ResEncoderBlock(nn.Module):
        def __init__(self, i, o, kernel_size, n_blocks=1, momentum=0.01):
            super().__init__()
            self.conv = nn.ModuleList([ConvBlockRes(i, o, momentum)])
            for _ in range(n_blocks - 1):
                self.conv.append(ConvBlockRes(o, o, momentum))
            self.kernel_size = kernel_size
            if kernel_size is not None:
                self.pool = nn.AvgPool2d(kernel_size=kernel_size)

        def forward(self, x):
            for c in self.conv:
                x = c(x)
            return (x, self.pool(x)) if self.kernel_size is not None else x

    class Encoder(nn.Module):
        def __init__(self, i, in_size, n, kernel_size, n_blocks, o=16, momentum=0.01):
            super().__init__()
            self.bn = nn.BatchNorm2d(i, momentum=momentum)
            self.layers = nn.ModuleList()
            for _ in range(n):
                self.layers.append(ResEncoderBlock(i, o, kernel_size, n_blocks, momentum))
                i, o, in_size = o, o * 2, in_size // 2
            self.out_channel = o

        def forward(self, x):
            skips = []
            x = self.bn(x)
            for layer in self.layers:
                t, x = layer(x)
                skips.append(t)
            return x, skips

    class Intermediate(nn.Module):
        def __init__(self, i, o, n, n_blocks, momentum=0.01):
            super().__init__()
            self.layers = nn.ModuleList([ResEncoderBlock(i, o, None, n_blocks, momentum)])
            for _ in range(n - 1):
                self.layers.append(ResEncoderBlock(o, o, None, n_blocks, momentum))

        def forward(self, x):
            for layer in self.layers:
                x = layer(x)
            return x

    class ResDecoderBlock(nn.Module):
        def __init__(self, i, o, stride, n_blocks=1, momentum=0.01):
            super().__init__()
            pad = (0, 1) if stride == (1, 2) else (1, 1)
            self.conv1 = nn.Sequential(
                nn.ConvTranspose2d(i, o, (3, 3), stride, (1, 1), pad, bias=False),
                nn.BatchNorm2d(o, momentum=momentum),
                nn.ReLU(),
            )
            self.conv2 = nn.ModuleList([ConvBlockRes(o * 2, o, momentum)])
            for _ in range(n_blocks - 1):
                self.conv2.append(ConvBlockRes(o, o, momentum))

        def forward(self, x, skip):
            x = torch.cat((self.conv1(x), skip), dim=1)
            for c in self.conv2:
                x = c(x)
            return x

    class Decoder(nn.Module):
        def __init__(self, i, n, stride, n_blocks, momentum=0.01):
            super().__init__()
            self.layers = nn.ModuleList()
            for _ in range(n):
                self.layers.append(ResDecoderBlock(i, i // 2, stride, n_blocks, momentum))
                i //= 2

        def forward(self, x, skips):
            for k, layer in enumerate(self.layers):
                x = layer(x, skips[-1 - k])
            return x

    class DeepUnet(nn.Module):
        def __init__(self, kernel_size, n_blocks, layers=5, inter=4, i=1, o=16):
            super().__init__()
            self.encoder = Encoder(i, 128, layers, kernel_size, n_blocks, o)
            self.intermediate = Intermediate(
                self.encoder.out_channel // 2, self.encoder.out_channel, inter, n_blocks
            )
            self.decoder = Decoder(self.encoder.out_channel, layers, kernel_size, n_blocks)

        def forward(self, x):
            x, skips = self.encoder(x)
            return self.decoder(self.intermediate(x), skips)

    class BiGRU(nn.Module):
        def __init__(self, i, h, n):
            super().__init__()
            self.gru = nn.GRU(i, h, num_layers=n, batch_first=True, bidirectional=True)

        def forward(self, x):
            return self.gru(x)[0]

    class E2E(nn.Module):
        def __init__(self, n_blocks=4, n_gru=1, kernel_size=(2, 2)):
            super().__init__()
            self.unet = DeepUnet(kernel_size, n_blocks)
            self.cnn = nn.Conv2d(16, 3, (3, 3), padding=(1, 1))
            self.fc = nn.Sequential(
                BiGRU(3 * 128, 256, n_gru), nn.Linear(512, 360), nn.Dropout(0.25), nn.Sigmoid()
            )

        def forward(self, mel):
            mel = mel.transpose(-1, -2).unsqueeze(1)
            return self.fc(self.cnn(self.unet(mel)).transpose(1, 2).flatten(-2))

    return E2E


@lru_cache(maxsize=1)
def _model(device: str):
    import torch

    path = weights_path()
    with open(path, "rb") as f:
        digest = hashlib.sha256(f.read()).hexdigest()
    if digest != SHA256:
        raise RuntimeError(f"rmvpe weights do not match (sha256 {digest[:12]}…)")
    model = _net()()
    model.load_state_dict(torch.load(path, map_location="cpu", weights_only=True))
    model.eval().to(device)
    logger.info("rmvpe loaded on %s", device)
    return model


def _mel(y: np.ndarray, device: str):
    import librosa
    import torch

    basis = (
        torch.from_numpy(
            librosa.filters.mel(sr=SR, n_fft=1024, n_mels=128, fmin=30, fmax=8000, htk=True)
        )
        .float()
        .to(device)
    )
    audio = torch.from_numpy(y.astype(np.float32)).to(device).unsqueeze(0)
    spec = torch.stft(
        audio,
        n_fft=1024,
        hop_length=HOP,
        win_length=1024,
        window=torch.hann_window(1024, device=device),
        center=True,
        return_complex=True,
    ).abs()
    return torch.log(torch.clamp(torch.matmul(basis, spec), min=1e-5))  # (1, 128, frames)


_CENTS = np.pad(20 * np.arange(360) + 1997.3794084376191, (4, 4))


def _decode(salience: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """MIDI per frame (NaN unvoiced) and the peak salience (a confidence)."""
    peak = salience.max(axis=1)
    center = salience.argmax(axis=1) + 4
    padded = np.pad(salience, ((0, 0), (4, 4)))
    idx = center[:, None] + np.arange(-4, 5)[None, :]
    w = np.take_along_axis(padded, idx, axis=1)
    cents = (w * _CENTS[idx]).sum(1) / np.maximum(w.sum(1), 1e-9)
    hz = 10 * 2 ** (cents / 1200)
    midi = 69 + 12 * np.log2(np.maximum(hz, 1e-6) / 440)
    midi[peak <= THRESHOLD] = np.nan
    return midi, peak


def device() -> str:
    try:
        import torch

        return "cuda" if torch.cuda.is_available() else "cpu"
    except Exception:  # noqa: BLE001
        return "cpu"


def track(y: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """(MIDI per 10 ms, NaN unvoiced; confidence) of mono 16 kHz audio."""
    import torch
    import torch.nn.functional as F

    dev = device()
    with _LOCK, torch.no_grad():
        model = _model(dev)
        mel = _mel(y, dev)
        n = mel.shape[-1]
        out = np.zeros((n, 360), dtype=np.float32)
        for a in range(0, n, CHUNK):
            lo, hi = max(0, a - OVERLAP), min(n, a + CHUNK + OVERLAP)
            piece = mel[..., lo:hi]
            pad = (-piece.shape[-1]) % 32
            if pad:
                piece = F.pad(piece, (0, pad))
            sal = model(piece)[0, : hi - lo].float().cpu().numpy()
            take = min(CHUNK, n - a)
            out[a : a + take] = sal[a - lo : a - lo + take]
    return _decode(out)
