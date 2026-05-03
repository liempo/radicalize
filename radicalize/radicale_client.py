from __future__ import annotations

import base64
import urllib.error
import urllib.request
from typing import Optional

from radicalize.envconfig import RadicaleSettings
from radicalize.models import Downstream, collection_href


def collection_url(settings: RadicaleSettings, downstream: Downstream) -> str:
    return f"{settings.base_url}/{settings.username}/{collection_href(downstream)}"


def _auth_header(settings: RadicaleSettings) -> str:
    token = base64.b64encode(f"{settings.username}:{settings.password}".encode()).decode()
    return f"Basic {token}"


def put_collection(url: str, settings: RadicaleSettings, body: bytes) -> None:
    req = urllib.request.Request(
        url,
        data=body,
        method="PUT",
        headers={"Content-Type": "text/calendar; charset=utf-8"},
    )
    req.add_header("Authorization", _auth_header(settings))
    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            if resp.status not in (200, 201, 204):
                raise RuntimeError(f"Radicale PUT unexpected status {resp.status}")
    except urllib.error.HTTPError as e:
        msg = e.read().decode(errors="replace")
        raise RuntimeError(f"Radicale PUT failed {e.code} {e.reason}\n{msg}") from e


def get_collection(url: str, settings: RadicaleSettings) -> Optional[bytes]:
    req = urllib.request.Request(url, method="GET")
    req.add_header("Authorization", _auth_header(settings))
    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            if resp.status == 404:
                return None
            data = resp.read()
            if not data or not data.strip():
                return None
            return data
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return None
        raise
