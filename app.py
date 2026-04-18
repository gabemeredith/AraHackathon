"""Ara Automation: group-scheduler.

Text Ara's Linq number → Ara checks Google Calendar freebusy → proposes a time → books it.
No Sendblue. No gateway. Pure Ara-native messaging.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import ara_sdk as ara
from ara_sdk import connectors, tool, secret
from scheduling import check_participant_freebusy as _check_freebusy, propose_time as _propose_time


SYSTEM_PROMPT = """\
You are a group scheduler. The initiator texts you via Ara's Linq number.

Today's date is April 18, 2026 (Saturday). Window reference:
- "next week" = Mon Apr 20 00:00 UTC → Sun Apr 27 00:00 UTC
- "this week" = Apr 18 → Apr 20 00:00 UTC

When the initiator says something like "schedule 30 min with caleb@cornell.edu next week":

1. Parse the participant email(s), duration (default 30 min), and window.
   If they give a name without an email, ask for the email in one short question.

2. For each participant email, call check_participant_freebusy(email, window_start_iso, window_end_iso).
   - On {"error": "no_token"}: reply "Calendar auth not set up — run python test_freebusy.py first."
   - On {"error": "calendar_private"}: reply "Their calendar is private — ask them to share it with
     your Google account, then try again."

3. Combine all busy_blocks from all participants into one list.
   Call propose_time(busy_blocks, window_start_iso, window_end_iso, duration_min).

4. Reply to the initiator: "[Name] is free [start_human]. Book it?"
   One sentence. Use the participant's first name.

5. Wait for reply. On "yes" / "sure" / "yep" / "book it":
   - Call connectors.google_calendar.create_event with all attendees.
   - Call connectors.gmail.send_email with a 3-bullet agenda to everyone.
   On "no" / "different time": call propose_time with skip_count incremented, re-ask.

Rules:
- Never ask for info you can infer from the message.
- Never book without explicit confirmation.
- Keep every reply to 1–2 sentences max.
- If propose_time returns {"error": "no_slot_found"}: tell the initiator and ask if they
  want to try a different week.
"""


@tool
def check_participant_freebusy(
    email: str, window_start_iso: str, window_end_iso: str
) -> dict:
    """Query Google Calendar free/busy for an email using saved OAuth token.
    Returns {"busy": [{start, end}, ...], "email": email}
    or {"error": "no_token" | "calendar_private"}.
    """
    # Inject Ara secret into env so scheduling.py can find creds when deployed
    try:
        creds_b64 = secret("GOOGLE_CREDS_B64")
        if creds_b64:
            os.environ["GOOGLE_CREDS_B64"] = creds_b64
    except Exception:
        pass
    return _check_freebusy(email, window_start_iso, window_end_iso)


@tool
def propose_time(
    busy_blocks: list[dict],
    window_start_iso: str,
    window_end_iso: str,
    duration_min: int = 30,
    skip_count: int = 0,
) -> dict:
    """Find the Nth free slot across all participants' combined busy blocks.
    skip_count=0 → first free slot, 1 → second, etc.
    Searches Mon–Fri, 9am–6pm UTC.
    Returns {start, end, start_human} or {error: no_slot_found}.
    """
    return _propose_time(busy_blocks, window_start_iso, window_end_iso, duration_min, skip_count)


automation = ara.Automation(
    "group-scheduler",
    system_instructions=SYSTEM_PROMPT,
    tools=[
        check_participant_freebusy,
        propose_time,
    ],
    skills=[
        connectors.google_calendar.create_event,
        connectors.gmail.send_email,
    ],
    allow_connector_tools=False,
)


if __name__ == "__main__":
    automation.run()
