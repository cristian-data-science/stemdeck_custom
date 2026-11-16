"""Demucs weights: Meta first, mirror only when Meta fails (app/pipeline/demucs_weights.py)."""

from __future__ import annotations

import hashlib

import pytest
import torch.hub

from app.pipeline import demucs_weights as dw

META = "https://dl.fbaipublicfiles.com/demucs/hybrid_transformer/5c90dfd2-34c22ccb.th"
FILE = "5c90dfd2-34c22ccb.th"


@pytest.fixture
def hub(tmp_path, monkeypatch):
    monkeypatch.setattr(torch.hub, "get_dir", lambda: str(tmp_path))
    return tmp_path / "checkpoints"


def _fake_download(calls, fail_on=(), payload=b"weights"):
    def download(url, dst, prefix):
        calls.append(url)
        if any(s in url for s in fail_on):
            raise OSError(f"boom {url}")
        with open(dst, "wb") as f:
            f.write(payload)

    return download


def test_default_model_resolves_to_meta_url():
    assert dw._checkpoint_urls("htdemucs_6s") == [META]
    assert dw._hash_prefix(FILE) == "34c22ccb"


def test_meta_success_never_touches_mirror(hub, monkeypatch):
    calls = []
    monkeypatch.setattr(dw, "_download", _fake_download(calls))
    dw.ensure_checkpoints("htdemucs_6s")
    assert calls == [META]
    assert (hub / FILE).read_bytes() == b"weights"


def test_meta_failure_falls_back_to_mirror(hub, monkeypatch):
    calls = []
    monkeypatch.setattr(dw, "_download", _fake_download(calls, fail_on=["fbaipublicfiles"]))
    monkeypatch.setattr(dw, "_MIRROR_SHA256", {})
    dw.ensure_checkpoints("htdemucs_6s")
    assert calls == [META, dw.MIRROR_ROOT.rstrip("/") + "/" + FILE]
    assert (hub / FILE).read_bytes() == b"weights"
    assert not list(hub.glob("*.mirror"))


def test_cached_file_is_not_downloaded(hub, monkeypatch):
    hub.mkdir(parents=True)
    (hub / FILE).write_bytes(b"cached")
    calls = []
    monkeypatch.setattr(dw, "_download", _fake_download(calls))
    dw.ensure_checkpoints("htdemucs_6s")
    assert calls == []


def test_mirror_copy_must_match_pinned_sha256(hub, monkeypatch):
    monkeypatch.setattr(dw, "_download", _fake_download([], fail_on=["fbaipublicfiles"], payload=b"tampered"))
    monkeypatch.setattr(dw, "_MIRROR_SHA256", {FILE: hashlib.sha256(b"genuine").hexdigest()})
    with pytest.raises(RuntimeError, match="pinned SHA-256"):
        dw.ensure_checkpoints("htdemucs_6s")
    assert not (hub / FILE).exists()
    assert not list(hub.glob("*.mirror"))


def test_both_failing_reports_both_causes(hub, monkeypatch):
    monkeypatch.setattr(dw, "_download", _fake_download([], fail_on=["fbaipublicfiles", "github"]))
    with pytest.raises(RuntimeError, match=r"Meta: boom .*mirror: boom"):
        dw.ensure_checkpoints("htdemucs_6s")
    assert not (hub / FILE).exists()


def test_unknown_model_is_left_to_get_model(hub, monkeypatch):
    calls = []
    monkeypatch.setattr(dw, "_download", _fake_download(calls))
    dw.ensure_checkpoints("demucs_unittest")
    assert calls == []
