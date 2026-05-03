from __future__ import annotations

from collections import OrderedDict
from pathlib import Path

import pytest
from icalendar import Calendar as ICalCalendar
from icalendar import Event as ICalEvent

from radicalize import pair_merge, runner
from radicalize.envconfig import RadicaleSettings
from radicalize.models import (
    Downstream,
    GoogleUpstream,
    IcsUpstream,
    Pair,
)


def _settings() -> RadicaleSettings:
    return RadicaleSettings(
        username="alice",
        password="pw",
        base_url="http://radicale:5232",
        sync_interval_seconds=1800,
    )


def _ics_with(*uids: str) -> bytes:
    cal = pair_merge.empty_calendar("u")
    for uid in uids:
        ev = ICalEvent()
        ev.add("uid", uid)
        cal.add_component(ev)
    return cal.to_ical()


def test_group_pairs_preserves_order() -> None:
    pairs = [
        Pair(upstream_id="a", downstream_id="x"),
        Pair(upstream_id="b", downstream_id="y"),
        Pair(upstream_id="c", downstream_id="x"),
    ]
    grouped = runner._group_pairs_by_downstream(pairs)
    assert isinstance(grouped, OrderedDict)
    assert list(grouped.keys()) == ["x", "y"]
    assert [p.upstream_id for p in grouped["x"]] == ["a", "c"]


def test_sync_downstream_chains_replace_then_update(monkeypatch, tmp_path: Path) -> None:
    holidays = IcsUpstream(id="holidays", external_ics_url="https://x/holidays.ics")
    work = IcsUpstream(id="work", external_ics_url="https://x/work.ics")
    downstream = Downstream(id="merged")

    fetched = []

    def fake_fetch(_data_dir: Path, upstream):
        fetched.append(upstream.id)
        if upstream.id == "holidays":
            return _ics_with("h1@x", "h2@x")
        if upstream.id == "work":
            return _ics_with("w1@x", "w2@x")
        raise AssertionError(f"unexpected upstream {upstream.id}")

    def fake_get_collection(_url: str, _settings):
        return None  # empty radicale

    put_args: dict[str, bytes] = {}

    def fake_put_collection(url: str, _settings, body: bytes) -> None:
        put_args["url"] = url
        put_args["body"] = body

    monkeypatch.setattr(runner, "fetch_upstream_bytes", fake_fetch)
    monkeypatch.setattr(runner, "get_collection", fake_get_collection)
    monkeypatch.setattr(runner, "put_collection", fake_put_collection)

    pairs = [
        Pair(upstream_id="holidays", downstream_id="merged", method="replace"),
        Pair(upstream_id="work", downstream_id="merged", method="update"),
    ]

    runner.sync_downstream(
        tmp_path,
        _settings(),
        downstream,
        pairs,
        {"holidays": holidays, "work": work},
    )

    assert fetched == ["holidays", "work"]
    assert put_args["url"] == "http://radicale:5232/alice/merged"
    body = pair_merge.parse_calendar(put_args["body"])
    uids = sorted(str(c.get("uid")) for c in getattr(body, "subcomponents", []) if c.name == "VEVENT")
    assert uids == ["h1@x", "h2@x", "w1@x", "w2@x"]


def test_sync_downstream_continues_after_fetch_failure(monkeypatch, tmp_path: Path) -> None:
    holidays = IcsUpstream(id="holidays", external_ics_url="https://x/holidays.ics")
    work = IcsUpstream(id="work", external_ics_url="https://x/work.ics")

    def fake_fetch(_data_dir: Path, upstream):
        if upstream.id == "holidays":
            raise RuntimeError("network down")
        return _ics_with("w1@x")

    monkeypatch.setattr(runner, "fetch_upstream_bytes", fake_fetch)
    monkeypatch.setattr(runner, "get_collection", lambda _u, _s: None)

    captured: dict = {}
    monkeypatch.setattr(
        runner,
        "put_collection",
        lambda url, _s, body: captured.update(url=url, body=body),
    )

    pairs = [
        Pair(upstream_id="holidays", downstream_id="merged", method="replace"),
        Pair(upstream_id="work", downstream_id="merged", method="update"),
    ]
    runner.sync_downstream(
        tmp_path,
        _settings(),
        Downstream(id="merged"),
        pairs,
        {"holidays": holidays, "work": work},
    )
    body = pair_merge.parse_calendar(captured["body"])
    uids = [str(c.get("uid")) for c in getattr(body, "subcomponents", []) if c.name == "VEVENT"]
    assert uids == ["w1@x"]


def test_sync_downstream_skips_when_no_pairs(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(runner, "get_collection", lambda *_: pytest.fail("should not GET"))
    monkeypatch.setattr(runner, "put_collection", lambda *_: pytest.fail("should not PUT"))
    runner.sync_downstream(tmp_path, _settings(), Downstream(id="merged"), [], {})
