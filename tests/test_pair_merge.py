from __future__ import annotations

from icalendar import Calendar as ICalCalendar
from icalendar import Event as ICalEvent

from radicalize import pair_merge
from radicalize.pair_merge import UPSTREAM_TAG_PROP


def _vevent(uid: str, summary: str = "", *, tag: str | None = None) -> ICalEvent:
    ev = ICalEvent()
    ev.add("uid", uid)
    if summary:
        ev.add("summary", summary)
    if tag:
        ev.add(UPSTREAM_TAG_PROP.lower(), tag)
    return ev


def _calendar(*events: ICalEvent) -> ICalCalendar:
    cal = pair_merge.empty_calendar("test")
    for ev in events:
        cal.add_component(ev)
    return cal


def _uids_with_tag(cal: ICalCalendar) -> list[tuple[str, str | None]]:
    out: list[tuple[str, str | None]] = []
    for c in getattr(cal, "subcomponents", []):
        if c.name != "VEVENT":
            continue
        tag = c.get(UPSTREAM_TAG_PROP.lower())
        out.append((str(c.get("uid")), str(tag) if tag is not None else None))
    return sorted(out)


def test_replace_drops_only_matching_tag() -> None:
    working = _calendar(
        _vevent("a@x", "old-a", tag="src1"),
        _vevent("b@x", "kept-b", tag="src2"),
        _vevent("c@x", "kept-local"),
    )
    upstream = _calendar(_vevent("a@x", "new-a"), _vevent("d@x", "new-d"))

    removed, added = pair_merge.apply_replace(working, upstream, "src1")

    assert removed == 1
    assert added == 2
    assert _uids_with_tag(working) == sorted([
        ("a@x", "src1"),
        ("b@x", "src2"),
        ("c@x", None),
        ("d@x", "src1"),
    ])


def test_update_replaces_by_uid_and_appends_new() -> None:
    working = _calendar(
        _vevent("a@x", "old-a", tag="src1"),
        _vevent("b@x", "kept-b", tag="src2"),
        _vevent("c@x", "kept-local"),
    )
    upstream = _calendar(_vevent("a@x", "new-a"), _vevent("d@x", "new-d"))

    updated, added = pair_merge.apply_update(working, upstream, "src1")

    assert updated == 1
    assert added == 1
    assert _uids_with_tag(working) == sorted([
        ("a@x", "src1"),
        ("b@x", "src2"),
        ("c@x", None),
        ("d@x", "src1"),
    ])


def test_chain_replace_then_update_preserves_other_upstream() -> None:
    working = pair_merge.empty_calendar("merged")

    holidays = _calendar(_vevent("h1@x", "Holiday 1"), _vevent("h2@x", "Holiday 2"))
    work = _calendar(_vevent("w1@x", "Work 1"), _vevent("w2@x", "Work 2"))

    pair_merge.apply_replace(working, holidays, "holidays")
    pair_merge.apply_update(working, work, "work")

    by_uid = dict(_uids_with_tag(working))
    assert by_uid == {
        "h1@x": "holidays",
        "h2@x": "holidays",
        "w1@x": "work",
        "w2@x": "work",
    }


def test_replace_second_pass_does_not_strip_other_upstreams() -> None:
    working = pair_merge.empty_calendar("merged")
    pair_merge.apply_replace(working, _calendar(_vevent("a@x"), _vevent("b@x")), "src1")
    pair_merge.apply_replace(working, _calendar(_vevent("c@x"), _vevent("d@x")), "src2")

    pair_merge.apply_replace(working, _calendar(_vevent("a@x"), _vevent("e@x")), "src1")

    by_uid = dict(_uids_with_tag(working))
    assert by_uid == {
        "a@x": "src1",
        "e@x": "src1",
        "c@x": "src2",
        "d@x": "src2",
    }


def test_parse_calendar_returns_empty_on_garbage() -> None:
    cal = pair_merge.parse_calendar(b"not a calendar", "fallback")
    assert isinstance(cal, ICalCalendar)
    assert "x-wr-calname" in cal


def test_serialize_sets_calendar_name() -> None:
    cal = pair_merge.empty_calendar()
    body = pair_merge.serialize(cal, "Renamed")
    text = body.decode("utf-8")
    assert "X-WR-CALNAME:Renamed" in text
