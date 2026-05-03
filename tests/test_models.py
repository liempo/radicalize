from __future__ import annotations

import pytest
from pydantic import TypeAdapter, ValidationError

from radicalize.models import (
    Downstream,
    GoogleUpstream,
    IcsUpstream,
    Pair,
    PairFile,
    Upstream,
    collection_href,
    display_name,
)


def test_google_upstream_defaults() -> None:
    u = GoogleUpstream(id="work")
    assert u.source == "google"
    assert u.google_calendar_id == "primary"


def test_ics_upstream_requires_url() -> None:
    with pytest.raises(ValidationError):
        IcsUpstream(id="holidays", external_ics_url="")


def test_upstream_discriminator_resolves_correctly() -> None:
    adapter = TypeAdapter(Upstream)
    google = adapter.validate_python({"source": "google", "id": "g1"})
    ics = adapter.validate_python({"source": "ics", "id": "i1", "external_ics_url": "https://x/y.ics"})
    assert isinstance(google, GoogleUpstream)
    assert isinstance(ics, IcsUpstream)


def test_pair_default_method_is_update() -> None:
    p = Pair(upstream_id="u", downstream_id="d")
    assert p.method == "update"


def test_pair_method_must_be_valid() -> None:
    with pytest.raises(ValidationError):
        Pair(upstream_id="u", downstream_id="d", method="merge")  # type: ignore[arg-type]


def test_pair_file_round_trip() -> None:
    pf = PairFile(pairs=[Pair(upstream_id="u1", downstream_id="d1", method="replace")])
    raw = pf.model_dump(mode="json")
    assert PairFile.model_validate(raw) == pf


def test_collection_href_falls_back_to_id() -> None:
    d = Downstream(id="merged")
    assert collection_href(d) == "merged"
    assert collection_href(Downstream(id="merged", href="custom")) == "custom"


def test_display_name_falls_back_to_id() -> None:
    assert display_name(GoogleUpstream(id="work")) == "work"
    assert display_name(GoogleUpstream(id="work", name="Work")) == "Work"
