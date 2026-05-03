from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv


@dataclass(frozen=True)
class RadicaleSettings:
    username: str
    password: str
    base_url: str
    sync_interval_seconds: int


def load_dotenv_for_data_dir(data_dir: Path) -> None:
    load_dotenv(data_dir / ".env", override=False)


def _require_env(*names: str) -> str:
    """Return the first non-empty value among the given env var names."""
    for name in names:
        v = os.environ.get(name, "")
        if v.strip():
            return v.strip()
    raise RuntimeError(f"Missing required environment variable: {names[0]}")


def load_radicale_settings(data_dir: Path) -> RadicaleSettings:
    load_dotenv_for_data_dir(data_dir)
    base = os.environ.get("RADICALE_BASE_URL", "http://127.0.0.1:5232").strip().rstrip("/")
    interval_raw = os.environ.get("SYNC_INTERVAL_SECONDS", "1800").strip()
    try:
        interval = int(interval_raw)
    except ValueError as e:
        raise RuntimeError("SYNC_INTERVAL_SECONDS must be an integer") from e
    return RadicaleSettings(
        username=_require_env("RADICALE_USERNAME", "RADICALE_USER"),
        password=_require_env("RADICALE_PASSWORD"),
        base_url=base,
        sync_interval_seconds=max(1, interval),
    )


def oauth_port() -> int:
    raw = os.environ.get("OAUTH_PORT", "8090").strip()
    try:
        return int(raw)
    except ValueError:
        return 8090
