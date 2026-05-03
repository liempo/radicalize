from __future__ import annotations

import os
from pathlib import Path


MARKER_FILE = ".radicalize"
PAIR_FILENAME = "pair.json"


def default_data_dir() -> Path:
    raw = os.environ.get("RADICALIZE_DATA", "").strip()
    if raw:
        return Path(raw).expanduser().resolve()
    return (Path.home() / ".calendar" / "radicalize").expanduser().resolve()


def upstream_dir(root: Path) -> Path:
    return root / "upstream"


def downstream_dir(root: Path) -> Path:
    return root / "downstream"


def tokens_dir(root: Path) -> Path:
    return root / "tokens"


def credentials_dir(root: Path) -> Path:
    return root / "credentials"


def pair_file(root: Path) -> Path:
    return root / PAIR_FILENAME


def marker_file(root: Path) -> Path:
    return root / MARKER_FILE


def is_initialized(root: Path) -> bool:
    return marker_file(root).is_file() and pair_file(root).is_file()


def ensure_layout(root: Path) -> None:
    upstream_dir(root).mkdir(parents=True, exist_ok=True)
    downstream_dir(root).mkdir(parents=True, exist_ok=True)
    tokens_dir(root).mkdir(parents=True, exist_ok=True)
    credentials_dir(root).mkdir(parents=True, exist_ok=True)
    pf = pair_file(root)
    if not pf.is_file():
        pf.write_text('{"pairs": []}\n', encoding="utf-8")
    mk = marker_file(root)
    if not mk.is_file():
        mk.write_text("radicalize v2\n", encoding="utf-8")


def upstream_path(root: Path, upstream_id: str) -> Path:
    return upstream_dir(root) / f"{upstream_id}.json"


def downstream_path(root: Path, downstream_id: str) -> Path:
    return downstream_dir(root) / f"{downstream_id}.json"


def google_token_path(root: Path, upstream_id: str) -> Path:
    return tokens_dir(root) / f"{upstream_id}.json"


def data_dotenv_path(root: Path) -> Path:
    """Root `DATA_DIR/.env` (Radicale credentials, etc.).

    Reset and the Docker entrypoint intentionally do not delete or chown this path
    so it can stay a read-only host bind-mount.
    """
    return root / ".env"


def google_oauth_json_bind_path(root: Path) -> Path:
    """Google Desktop OAuth *client* JSON (``google/oauth.json`` under ``DATA_DIR``).

    This is the only supported path for `InstalledAppFlow` client secrets. Often a
    read-only host bind-mount. Reset and the Docker entrypoint do not chown or delete it.
    """
    return root / "google" / "oauth.json"
