"""Google Calendar API v3 for Yaad (official API only, host pinned, no redirects).

OAuth scope https://www.googleapis.com/auth/calendar.events (create / change / delete events; no reading of other
calendars), with the same Google Cloud OAuth client as the Business Profile (token exchange / refresh =
adapters.google_business). Events go to the person's PRIMARY calendar:
  POST   https://www.googleapis.com/calendar/v3/calendars/primary/events            -> {id, ...}
  PATCH  .../calendars/primary/events/{eventId}                                      -> {id, ...}
  DELETE .../calendars/primary/events/{eventId}                                      -> 204 (404 / 410 = already gone)
All-day = start/end {"date"} with end the NEXT day (Google's end is exclusive); timed = {"dateTime", "timeZone"}.
"""

from datetime import date, datetime, timedelta

from app.adapters.google_business import GoogleBusiness
from app.adapters.instagram.publishing import PublishError

SCOPE = "https://www.googleapis.com/auth/calendar.events"
EVENTS = "https://www.googleapis.com/calendar/v3/calendars/primary/events"
DEFAULT_MINUTES = 60
FOOTER = "Added from Yaad"


def event_body(
    *, title: str, day: date, start_time: str | None, place: str, notes: str, people: list[dict], tz: str
) -> dict:
    """The Google event for a Yaad event. People go into the description by name (no invites are sent)."""
    lines = [notes.strip()] if notes.strip() else []
    names = [p["name"] + (f" ({p['role']})" if p.get("role") else "") for p in people if p.get("name")]
    if names:
        lines.append("People: " + ", ".join(names))
    lines.append(FOOTER)
    body = {"summary": title, "location": place or None, "description": "\n\n".join(lines)}
    if start_time:
        start = datetime.combine(day, datetime.strptime(start_time, "%H:%M").time())
        end = start + timedelta(minutes=DEFAULT_MINUTES)
        body["start"] = {"dateTime": start.isoformat(), "timeZone": tz}
        body["end"] = {"dateTime": end.isoformat(), "timeZone": tz}
    else:
        body["start"] = {"date": day.isoformat()}
        body["end"] = {"date": (day + timedelta(days=1)).isoformat()}
    return body


class GoogleCalendar(GoogleBusiness):
    """Same request/error handling as the Business Profile client, Calendar host only."""

    HOSTS = frozenset({"www.googleapis.com"})

    def insert(self, body: dict) -> str:
        return self._req("POST", EVENTS, json=body)["id"]

    def update(self, event_id: str, body: dict) -> None:
        self._req("PATCH", f"{EVENTS}/{event_id}", json=body)

    def delete(self, event_id: str) -> None:
        try:
            self._req("DELETE", f"{EVENTS}/{event_id}")
        except PublishError as exc:
            if getattr(exc, "status", None) not in (404, 410):  # already gone from Google = done
                raise
