"""Ara Automation: group-scheduler.

Owns the agent loop, GCal free/busy + create_event, Gmail confirmations,
and outbound SMS to non-initiator participants via the Twilio gateway.

See docs/app.md for the full implementation brief.
"""

import ara_sdk as ara
from ara_sdk import connectors, tool, secret

GATEWAY_URL = secret("GATEWAY_URL")
GATEWAY_KEY = secret("GATEWAY_KEY")


SYSTEM_PROMPT = """\
You are a group scheduler. The initiator texts you a request like
"30 min next week with Alex and Jordan for coffee." Your job:

1. Parse participants, duration, and window.
2. For each participant: if their calendar is connected, read free/busy
   silently. Otherwise call send_to_participant to ask via SMS.
3. Poll read_inbound for replies. Merge declared availability.
4. Call propose_time to find an intersection.
5. Confirm with the initiator via linq. On "yes", create the GCal event
   and send a confirmation email with a short agenda.

Never ask the initiator what you can infer. Never book without explicit
confirmation. Keep SMS copy short and human.
"""


@tool
def send_to_participant(number: str, body: str) -> dict:
    """POST to Twilio gateway /send. Returns {"ok": bool, "sid": str}."""
    raise NotImplementedError


@tool
def read_inbound(since_ts: str | None = None) -> list[dict]:
    """GET gateway /inbound. Returns [{from, body, ts}, ...]."""
    raise NotImplementedError


@tool
def set_participant_status(number: str, status: str, data: dict | None = None) -> dict:
    """Update participant state in the sandbox session."""
    raise NotImplementedError


@tool
def get_session_state() -> dict:
    """Return the merged session state (initiator, participants, inbound, ...)."""
    raise NotImplementedError


@tool
def propose_time(window_iso: dict, duration_min: int) -> dict:
    """Intersect free/busy + declared availability. Returns {start, end} or {error}."""
    raise NotImplementedError


automation = ara.Automation(
    "group-scheduler",
    system_instructions=SYSTEM_PROMPT,
    tools=[
        send_to_participant,
        read_inbound,
        set_participant_status,
        get_session_state,
        propose_time,
    ],
    skills=[
        connectors.google_calendar.list_events,
        connectors.google_calendar.create_event,
        connectors.gmail.send_email,
    ],
    allow_connector_tools=False,
)


if __name__ == "__main__":
    automation.run()
