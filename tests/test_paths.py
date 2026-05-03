from __future__ import annotations

import os
from pathlib import Path

from radicalize import paths


def test_default_data_dir_uses_env(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("RADICALIZE_DATA", str(tmp_path / "custom"))
    assert paths.default_data_dir() == (tmp_path / "custom").resolve()


def test_default_data_dir_falls_back_to_home(monkeypatch) -> None:
    monkeypatch.delenv("RADICALIZE_DATA", raising=False)
    expected = (Path.home() / ".calendar" / "radicalize").resolve()
    assert paths.default_data_dir() == expected


def test_ensure_layout_creates_everything(tmp_path: Path) -> None:
    paths.ensure_layout(tmp_path)
    for sub in ("upstream", "downstream", "tokens", "credentials"):
        assert (tmp_path / sub).is_dir()
    assert paths.pair_file(tmp_path).is_file()
    assert paths.marker_file(tmp_path).is_file()
    assert paths.is_initialized(tmp_path)


def test_ensure_layout_is_idempotent(tmp_path: Path) -> None:
    paths.ensure_layout(tmp_path)
    paths.pair_file(tmp_path).write_text('{"pairs": [{"upstream_id":"a","downstream_id":"b","method":"update"}]}', encoding="utf-8")
    paths.ensure_layout(tmp_path)
    assert "upstream_id" in paths.pair_file(tmp_path).read_text(encoding="utf-8")
