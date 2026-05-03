from __future__ import annotations

import copy
import sys
from typing import Iterable, Optional

from icalendar import Calendar as ICalCalendar


UPSTREAM_TAG_PROP = "X-RADICALIZE-UPSTREAM-ID"
EVENT_COMPONENT_NAMES = {"VEVENT", "VTODO", "VJOURNAL"}


def empty_calendar(calendar_name: Optional[str] = None) -> ICalCalendar:
    cal = ICalCalendar()
    cal.add("prodid", "-//radicalize//EN")
    cal.add("version", "2.0")
    cal.add("calscale", "GREGORIAN")
    if calendar_name:
        cal.add("x-wr-calname", calendar_name)
    return cal


def parse_calendar(data: Optional[bytes], calendar_name: Optional[str] = None) -> ICalCalendar:
    """Parse iCalendar bytes; return empty shell on failure or empty input."""
    if not data or not data.strip():
        return empty_calendar(calendar_name)
    try:
        cal = ICalCalendar.from_ical(data)
        if isinstance(cal, ICalCalendar):
            return cal
    except Exception as e:
        print(f"radicalize: calendar parse failed, treating as empty: {e!r}", file=sys.stderr)
    return empty_calendar(calendar_name)


def _set_calendar_name(cal: ICalCalendar, name: Optional[str]) -> None:
    if not name:
        return
    if "x-wr-calname" in cal:
        del cal["x-wr-calname"]
    cal.add("x-wr-calname", name)


def _tag_value(component) -> Optional[str]:
    raw = component.get(UPSTREAM_TAG_PROP) or component.get(UPSTREAM_TAG_PROP.lower())
    if raw is None:
        return None
    return str(raw)


def _set_tag(component, upstream_id: str) -> None:
    if UPSTREAM_TAG_PROP in component:
        del component[UPSTREAM_TAG_PROP]
    if UPSTREAM_TAG_PROP.lower() in component:
        del component[UPSTREAM_TAG_PROP.lower()]
    component.add(UPSTREAM_TAG_PROP.lower(), upstream_id)


def _uid(component) -> str:
    u = component.get("uid")
    return str(u) if u is not None else ""


def _iter_event_components(cal: ICalCalendar) -> Iterable:
    for c in getattr(cal, "subcomponents", []):
        if c.name in EVENT_COMPONENT_NAMES:
            yield c


def _iter_vtimezones(cal: ICalCalendar) -> Iterable:
    for c in getattr(cal, "subcomponents", []):
        if c.name == "VTIMEZONE":
            yield c


def _prune_empty_vtimezones(cal: ICalCalendar) -> None:
    """Remove VTIMEZONE shells with no subcomponents (Radicale rejects them)."""
    _drop_components(
        cal,
        lambda c: c.name == "VTIMEZONE"
        and len(getattr(c, "subcomponents", []) or []) == 0,
    )


def _merge_vtimezones(target: ICalCalendar, *sources: ICalCalendar) -> None:
    # Drop invalid shells first so a good upstream definition is not skipped
    # because `seen` already contains the same TZID from a shallow-copied block.
    _prune_empty_vtimezones(target)
    seen: set[str] = {
        str(c.get("tzid"))
        for c in _iter_vtimezones(target)
        if c.get("tzid") is not None
    }
    for src in sources:
        for c in _iter_vtimezones(src):
            tid = c.get("tzid")
            tid_s = str(tid) if tid is not None else ""
            if not tid_s or tid_s in seen:
                continue
            if len(getattr(c, "subcomponents", []) or []) == 0:
                continue
            seen.add(tid_s)
            # icalendar Component.copy() omits nested subcomponents (STANDARD/DAYLIGHT).
            target.add_component(copy.deepcopy(c))


def _drop_components(cal: ICalCalendar, predicate) -> int:
    """Remove components from cal where predicate(c) is True. Returns count removed."""
    keep = []
    removed = 0
    for c in getattr(cal, "subcomponents", []):
        if predicate(c):
            removed += 1
            continue
        keep.append(c)
    cal.subcomponents = keep
    return removed


def apply_replace(
    working: ICalCalendar,
    upstream_cal: ICalCalendar,
    upstream_id: str,
) -> tuple[int, int]:
    """Drop everything tagged with upstream_id, then insert all upstream events tagged.

    Returns (removed, added).
    """
    removed = _drop_components(
        working,
        lambda c: c.name in EVENT_COMPONENT_NAMES and _tag_value(c) == upstream_id,
    )
    _merge_vtimezones(working, upstream_cal)
    added = 0
    new_events = sorted(
        (copy.deepcopy(c) for c in _iter_event_components(upstream_cal)),
        key=_uid,
    )
    for c in new_events:
        _set_tag(c, upstream_id)
        working.add_component(c)
        added += 1
    return removed, added


def apply_update(
    working: ICalCalendar,
    upstream_cal: ICalCalendar,
    upstream_id: str,
) -> tuple[int, int]:
    """Match upstream events to working by UID; replace matches, append new.

    Returns (updated, added).
    """
    upstream_events = list(_iter_event_components(upstream_cal))
    upstream_by_uid: dict[str, list] = {}
    for c in upstream_events:
        upstream_by_uid.setdefault(_uid(c), []).append(c)

    upstream_uids = {uid for uid in upstream_by_uid if uid}

    updated = _drop_components(
        working,
        lambda c: (
            c.name in EVENT_COMPONENT_NAMES
            and _uid(c) in upstream_uids
        ),
    )
    _merge_vtimezones(working, upstream_cal)

    added = 0
    sorted_events = sorted(
        (copy.deepcopy(c) for c in upstream_events),
        key=_uid,
    )
    for c in sorted_events:
        _set_tag(c, upstream_id)
        working.add_component(c)
        added += 1
    new_count = added - updated
    return updated, max(0, new_count)


def serialize(cal: ICalCalendar, calendar_name: Optional[str] = None) -> bytes:
    if calendar_name:
        _set_calendar_name(cal, calendar_name)
    _prune_empty_vtimezones(cal)
    return cal.to_ical()
