from __future__ import annotations

from radicalize.envconfig import RadicaleSettings
from radicalize.models import Downstream
from radicalize.radicale_client import collection_url


def _settings(base: str = "http://radicale:5232") -> RadicaleSettings:
    return RadicaleSettings(
        username="alice",
        password="pw",
        base_url=base,
        sync_interval_seconds=1800,
    )


def test_collection_url_uses_href() -> None:
    s = _settings()
    d = Downstream(id="merged", href="custom-href")
    assert collection_url(s, d) == "http://radicale:5232/alice/custom-href"


def test_collection_url_defaults_to_id() -> None:
    s = _settings()
    d = Downstream(id="merged")
    assert collection_url(s, d) == "http://radicale:5232/alice/merged"
