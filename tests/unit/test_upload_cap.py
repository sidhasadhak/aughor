"""Regression: file uploads must be bounded by AUGHOR_MAX_UPLOAD_MB so a
multi-GB upload can't fill the disk (AUDIT_2026-06-27.md #9). _stage_upload
streams in chunks and aborts past the cap, removing the partial temp dir."""
from __future__ import annotations

import io
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from aughor.routers.connections import _stage_upload, _max_upload_bytes


def _fake_upload(data: bytes, name: str = "big.csv"):
    return SimpleNamespace(filename=name, file=io.BytesIO(data))


def test_oversized_upload_is_rejected_and_cleaned_up(monkeypatch):
    monkeypatch.setenv("AUGHOR_MAX_UPLOAD_MB", "1")  # 1 MB cap
    payload = b"x" * (2 * 1024 * 1024)  # 2 MB
    captured = {}
    real_mkdtemp = __import__("tempfile").mkdtemp

    def _spy_mkdtemp(*a, **k):
        d = real_mkdtemp(*a, **k)
        captured["dir"] = d
        return d

    monkeypatch.setattr("tempfile.mkdtemp", _spy_mkdtemp)

    with pytest.raises(HTTPException) as ei:
        _stage_upload(_fake_upload(payload))
    assert ei.value.status_code == 413
    # partial temp dir was removed
    assert not Path(captured["dir"]).exists()


def test_within_limit_upload_succeeds(monkeypatch):
    monkeypatch.setenv("AUGHOR_MAX_UPLOAD_MB", "1")
    tmp_dir, tmp_path = _stage_upload(_fake_upload(b"a,b\n1,2\n"))
    try:
        assert tmp_path.exists() and tmp_path.read_bytes() == b"a,b\n1,2\n"
    finally:
        __import__("shutil").rmtree(tmp_dir, ignore_errors=True)


def test_default_cap_is_512mb(monkeypatch):
    monkeypatch.delenv("AUGHOR_MAX_UPLOAD_MB", raising=False)
    assert _max_upload_bytes() == 512 * 1024 * 1024


def test_bad_env_falls_back_to_default(monkeypatch):
    monkeypatch.setenv("AUGHOR_MAX_UPLOAD_MB", "not-a-number")
    assert _max_upload_bytes() == 512 * 1024 * 1024
