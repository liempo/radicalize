from __future__ import annotations

from pathlib import Path

import pytest

from radicalize.envconfig import load_radicale_settings


def test_load_radicale_settings_uses_username(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("RADICALE_USERNAME", "alice")
    monkeypatch.setenv("RADICALE_PASSWORD", "secret")
    monkeypatch.setenv("RADICALE_BASE_URL", "http://radicale:5232/")
    monkeypatch.setenv("SYNC_INTERVAL_SECONDS", "60")
    s = load_radicale_settings(tmp_path)
    assert s.username == "alice"
    assert s.password == "secret"
    assert s.base_url == "http://radicale:5232"
    assert s.sync_interval_seconds == 60


def test_load_radicale_settings_accepts_v1_user_alias(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.delenv("RADICALE_USERNAME", raising=False)
    monkeypatch.setenv("RADICALE_USER", "bob")
    monkeypatch.setenv("RADICALE_PASSWORD", "pw")
    s = load_radicale_settings(tmp_path)
    assert s.username == "bob"


def test_load_radicale_settings_missing_password(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("RADICALE_USERNAME", "alice")
    monkeypatch.delenv("RADICALE_PASSWORD", raising=False)
    with pytest.raises(RuntimeError):
        load_radicale_settings(tmp_path)


def test_load_radicale_settings_invalid_interval(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("RADICALE_USERNAME", "alice")
    monkeypatch.setenv("RADICALE_PASSWORD", "pw")
    monkeypatch.setenv("SYNC_INTERVAL_SECONDS", "notanumber")
    with pytest.raises(RuntimeError):
        load_radicale_settings(tmp_path)
