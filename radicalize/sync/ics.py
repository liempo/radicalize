from __future__ import annotations

import urllib.request

from radicalize.models import IcsUpstream


def fetch_ics_bytes(src: IcsUpstream) -> bytes:
    req = urllib.request.Request(
        src.external_ics_url,
        headers={"User-Agent": "radicalize/0.2"},
    )
    with urllib.request.urlopen(req, timeout=120) as resp:
        return resp.read()
