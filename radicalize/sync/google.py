from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Optional

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from icalendar import Calendar as ICalCalendar
from icalendar import Event as ICalEvent

from radicalize import paths
from radicalize.envconfig import oauth_port
from radicalize.models import GoogleUpstream, display_name


SCOPES = ["https://www.googleapis.com/auth/calendar.readonly"]


def _save_token(creds: Credentials, token_path: Path) -> None:
    token_path.parent.mkdir(parents=True, exist_ok=True)
    token_path.write_text(creds.to_json(), encoding="utf-8")


def run_google_oauth(data_dir: Path, src: GoogleUpstream) -> Path:
    """Interactive Google OAuth; saves token to tokens/<id>.json. Returns token path."""
    client_path = paths.google_oauth_json_bind_path(data_dir)
    token_path = paths.google_token_path(data_dir, src.id)
    if not client_path.is_file():
        raise RuntimeError(
            "Google OAuth client file missing: "
            f"{client_path}\n"
            "Download a Desktop OAuth client JSON from Google Cloud Console and place "
            "it at that path (often a read-only bind-mount in Docker)."
        )
    port = oauth_port()
    flow = InstalledAppFlow.from_client_secrets_file(str(client_path), SCOPES)
    creds = flow.run_local_server(
        port=port,
        open_browser=False,
        host="127.0.0.1",
        bind_addr="0.0.0.0",
    )
    _save_token(creds, token_path)
    return token_path


def _load_credentials(token_path: Path) -> Credentials:
    if not token_path.is_file():
        raise RuntimeError(
            f"No Google token at {token_path}. "
            "Run: radicalize upstream edit <id> (and re-run OAuth) "
            "or radicalize upstream add <id>."
        )
    creds = Credentials.from_authorized_user_file(str(token_path), SCOPES)
    if creds and creds.valid:
        return creds
    if creds and creds.expired and creds.refresh_token:
        creds.refresh(Request())
        _save_token(creds, token_path)
        return creds
    raise RuntimeError(
        "Google token invalid or expired without refresh. Delete the token file and re-run "
        "`radicalize upstream edit <id>`."
    )


def _parse_dt(s: str) -> datetime:
    if s.endswith("Z"):
        return datetime.fromisoformat(s.replace("Z", "+00:00"))
    return datetime.fromisoformat(s)


def _events_to_ical(events: list[dict[str, Any]], calendar_name: str) -> bytes:
    cal = ICalCalendar()
    cal.add("prodid", "-//radicalize//EN")
    cal.add("version", "2.0")
    cal.add("calscale", "GREGORIAN")
    cal.add("x-wr-calname", calendar_name)

    for ev in events:
        if ev.get("status") == "cancelled":
            continue
        if not ev.get("start"):
            continue
        ve = ICalEvent()

        uid = ev.get("id", "")
        if uid:
            ve.add("uid", f"{uid}@google.com")

        if ev.get("summary"):
            ve.add("summary", ev["summary"])
        if ev.get("description"):
            ve.add("description", ev["description"])
        if ev.get("location"):
            ve.add("location", ev["location"])

        start = ev.get("start") or {}
        end = ev.get("end") or {}
        if "dateTime" in start:
            ve.add("dtstart", _parse_dt(start["dateTime"]))
        elif "date" in start:
            ve.add("dtstart", date.fromisoformat(start["date"]))
        if "dateTime" in end:
            ve.add("dtend", _parse_dt(end["dateTime"]))
        elif "date" in end:
            ve.add("dtend", date.fromisoformat(end["date"]))

        updated = ev.get("updated")
        if updated:
            ve.add("dtstamp", _parse_dt(updated))

        cal.add_component(ve)

    return cal.to_ical()


def _fetch_events(service: Any, calendar_id: str) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    page_token: Optional[str] = None
    time_min = (datetime.now(timezone.utc) - timedelta(days=90)).isoformat()
    time_max = (datetime.now(timezone.utc) + timedelta(days=365 * 2)).isoformat()
    while True:
        req = (
            service.events()
            .list(
                calendarId=calendar_id,
                singleEvents=True,
                orderBy="startTime",
                timeMin=time_min,
                timeMax=time_max,
                pageToken=page_token,
                maxResults=2500,
            )
            .execute()
        )
        out.extend(req.get("items", []))
        page_token = req.get("nextPageToken")
        if not page_token:
            break
    return out


def fetch_google_bytes(data_dir: Path, src: GoogleUpstream) -> bytes:
    token_path = paths.google_token_path(data_dir, src.id)
    creds = _load_credentials(token_path)
    service = build("calendar", "v3", credentials=creds, cache_discovery=False)
    events = _fetch_events(service, src.google_calendar_id)
    return _events_to_ical(events, display_name(src))
