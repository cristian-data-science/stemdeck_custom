"""Demucs checkpoints: Meta first, a mirror only when Meta fails.

Demucs fetches its weights from dl.fbaipublicfiles.com on first use and caches
them in <torch hub>/checkpoints. When that host is unreachable or misbehaving
(2026-11-12: its TLS certificate expired at 2026-11-11 23:59:59 GMT and every
Demucs job failed with CERTIFICATE_VERIFY_FAILED) no song can be separated
until the weights are cached. ensure_checkpoints() fills the cache before
get_model() runs: it always tries Meta's URL, and only if that raises does it
fetch the same file from the mirror. A cached file is never re-downloaded.

The mirror is the python-audio-separator release (the audio-separator package
StemDeck already depends on), served by GitHub. Every download is checked
against the hash Demucs bakes into the filename (<sig>-<sha256 prefix>.th),
and mirror downloads of files listed in _MIRROR_SHA256 against the full
SHA-256 as well, so a mirror file can only stand in for the exact bytes Meta
publishes.
"""

from __future__ import annotations

import hashlib
import logging
import os
from pathlib import Path

import yaml

log = logging.getLogger("stemdeck.pipeline")

MIRROR_ROOT = os.environ.get(
    "STEMDECK_DEMUCS_MIRROR",
    "https://github.com/nomadkaraoke/python-audio-separator/releases/download/model-configs/",
).strip()

# Full SHA-256 of mirror files we have checked. The prefix in the filename is
# only 8 hex digits; this pins the rest for the models StemDeck ships with.
_MIRROR_SHA256 = {
    # htdemucs_6s, the default DEMUCS_MODEL. Prefix matches Meta's "34c22ccb".
    "5c90dfd2-34c22ccb.th": "34c22ccb381c6f9fdbf324f04e1e2fe21aaaf293f5ded163a162697ff9a02ddd",
}


def _checkpoint_urls(name: str) -> list[str]:
    """Meta URLs of every checkpoint the model (a bag or a single signature) needs."""
    from demucs.pretrained import REMOTE_ROOT, _parse_remote_files

    urls = _parse_remote_files(REMOTE_ROOT / "files.txt")
    if name in urls:
        return [urls[name]]
    bag = REMOTE_ROOT / f"{name}.yaml"
    if not bag.is_file():
        return []  # not a remote model (local repo, unittest): let get_model decide
    with open(bag, encoding="utf-8") as f:
        sigs = yaml.safe_load(f)["models"]
    return [urls[s] for s in sigs if s in urls]


def _hash_prefix(filename: str) -> str | None:
    stem = filename.rsplit(".", 1)[0]
    return stem.split("-", 1)[1] if "-" in stem else None


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _download(url: str, dst: Path, prefix: str | None) -> None:
    from torch.hub import download_url_to_file

    # Writes to a temp file and moves it into place only after the hash check.
    download_url_to_file(url, str(dst), hash_prefix=prefix, progress=False)


def _from_mirror(filename: str, dst: Path, prefix: str | None) -> None:
    tmp = dst.with_name(dst.name + ".mirror")
    try:
        _download(MIRROR_ROOT.rstrip("/") + "/" + filename, tmp, prefix)
        want = _MIRROR_SHA256.get(filename)
        if want is not None and _sha256(tmp) != want:
            raise RuntimeError(f"mirror copy of {filename} does not match its pinned SHA-256")
        os.replace(tmp, dst)
    finally:
        tmp.unlink(missing_ok=True)


def ensure_checkpoints(name: str) -> None:
    """Make sure every checkpoint of `name` is in the torch hub cache.

    Meta first; the mirror only when Meta raises. Raises if both fail, with
    both causes in the message.
    """
    from torch.hub import get_dir

    ckpt_dir = Path(get_dir()) / "checkpoints"
    for url in _checkpoint_urls(name):
        filename = url.rsplit("/", 1)[1]
        dst = ckpt_dir / filename
        if dst.is_file():
            continue
        ckpt_dir.mkdir(parents=True, exist_ok=True)
        prefix = _hash_prefix(filename)
        try:
            _download(url, dst, prefix)
            continue
        except Exception as meta_err:  # noqa: BLE001 -- any failure means: try the mirror
            log.warning("demucs weights: Meta download of %s failed (%s); trying mirror", filename, meta_err)
            try:
                _from_mirror(filename, dst, prefix)
            except Exception as mirror_err:  # noqa: BLE001
                raise RuntimeError(
                    f"could not download Demucs weights {filename}: "
                    f"Meta: {meta_err}; mirror: {mirror_err}"
                ) from mirror_err
            log.info("demucs weights: %s downloaded from mirror", filename)
