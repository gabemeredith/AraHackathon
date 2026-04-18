"""Pure-Python scheduling helpers — no ara_sdk dependency.

Importable standalone for testing: python test_freebusy.py
Also imported by app.py and wrapped with @tool.
"""

import os
import pickle
from datetime import datetime, timedelta, timezone

_EASTERN = timezone(timedelta(hours=-5))  # fixed EST (UTC-5)

TOKEN_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "token.pickle")


def _load_creds():
    """Load Google OAuth creds from env var (deployed) or token.pickle (local)."""
    import base64
    import pickle as _pickle

    creds_b64 = os.environ.get("GOOGLE_CREDS_B64")
    if creds_b64:
        return _pickle.loads(base64.b64decode(creds_b64))

    if os.path.exists(TOKEN_PATH):
        with open(TOKEN_PATH, "rb") as f:
            return _pickle.load(f)

    return None


def check_participant_freebusy(email: str, window_start_iso: str, window_end_iso: str) -> dict:
    """Query Google Calendar free/busy using saved OAuth token (token.pickle).

    Returns {"busy": [{start, end}, ...], "email": email}
    or {"error": "no_token" | "calendar_private", ...}.
    """
    try:
        from google.auth.transport.requests import Request
        from googleapiclient.discovery import build

        creds = _load_creds()
        if creds is None:
            return {"error": "no_token", "message": "Run python test_freebusy.py first to authenticate"}

        if creds.expired and creds.refresh_token:
            creds.refresh(Request())

        service = build("calendar", "v3", credentials=creds)
        body = {
            "timeMin": window_start_iso,
            "timeMax": window_end_iso,
            "items": [{"id": email}],
        }
        result = service.freebusy().query(body=body).execute()
        cal = result["calendars"].get(email, {})

        if cal.get("errors"):
            return {"error": "calendar_private", "errors": cal["errors"]}

        return {"busy": cal.get("busy", []), "email": email}

    except Exception as e:
        return {"error": str(e)}


def propose_time(
    busy_blocks: list[dict],
    window_start_iso: str,
    window_end_iso: str,
    duration_min: int = 30,
    skip_count: int = 0,
) -> dict:
    """Find the Nth free slot (skip_count=0 → first, 1 → second, etc.).
    Searches Mon–Fri, 9am–6pm UTC. Returns {start, end, start_human} or {error}.
    """
    start = datetime.fromisoformat(window_start_iso.replace("Z", "+00:00"))
    end = datetime.fromisoformat(window_end_iso.replace("Z", "+00:00"))
    duration = timedelta(minutes=duration_min)
    step = timedelta(minutes=30)

    parsed_busy = []
    for b in busy_blocks:
        bs = datetime.fromisoformat(b["start"].replace("Z", "+00:00"))
        be = datetime.fromisoformat(b["end"].replace("Z", "+00:00"))
        parsed_busy.append((bs, be))

    found = 0
    slot = start

    while slot + duration <= end:
        local = slot.astimezone(_EASTERN)

        # Skip weekends — jump to next Monday 9am Eastern
        if local.weekday() >= 5:
            days_ahead = 7 - local.weekday()
            next_day = (local + timedelta(days=days_ahead)).replace(
                hour=9, minute=0, second=0, microsecond=0
            )
            slot = next_day.astimezone(timezone.utc)
            continue

        # Before 9am Eastern — jump to 9am same day Eastern
        if local.hour < 9:
            slot = local.replace(hour=9, minute=0, second=0, microsecond=0).astimezone(timezone.utc)
            continue

        slot_end = slot + duration
        local_end = slot_end.astimezone(_EASTERN)

        # After 6pm Eastern — jump to next day 9am Eastern
        if local_end.hour > 18 or (local_end.hour == 18 and local_end.minute > 0):
            next_day = (local + timedelta(days=1)).replace(
                hour=9, minute=0, second=0, microsecond=0
            )
            slot = next_day.astimezone(timezone.utc)
            continue

        conflict = any(slot < be and slot_end > bs for bs, be in parsed_busy)

        if not conflict:
            if found == skip_count:
                return {
                    "start": slot.isoformat(),
                    "end": slot_end.isoformat(),
                    "start_human": slot.strftime("%A %-I:%M %p"),
                }
            found += 1

        slot += step

    return {"error": "no_slot_found", "message": "No free slot found in the window"}
