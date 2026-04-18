# Phase 2 — Wire Ara to the gateway

Goal: Ara's agent loop drives a real scheduling conversation end-to-end. You iMessage Ara → Ara reads/writes calendars where it can → iMessages other participants where it can't → proposes a time → books it.

Depends on Phase 1 (see `docs/phase1.md`). Don't touch the gateway code in this phase.

## Architectural choice (settled)

**Keep the gateway. Ara pulls from it.** Alternative considered: `@ara.fastapi_endpoint` as the Sendblue webhook target, bypassing the gateway entirely. Rejected — Phase 1 round-trips today; swapping transports mid-hackathon is negative EV. The gateway's `/sendblue/inbound` webhook + in-memory index is the single source of truth for routing.

Concretely:
- Ara **sends** iMessages by calling `gateway POST /send`.
- Ara **reads replies** by polling `gateway GET /inbound?session_id=X&since=Y`.
- Ara **registers a session** via `gateway POST /sessions` so the gateway knows how to route inbound webhooks.
- Ara keeps its own copy of session state (participants, freebusy, proposed_time) in Ara's sandbox filesystem. The gateway's session store is just a routing index + inbound queue, not a shared brain.

This split means **gateway state can reset without losing Ara's context** — Ara just re-registers the session.

## Prereqs to check before coding

1. `ara --version` works. User logged in.
2. Gateway is running on laptop (`uvicorn gateway.main:app --reload --port 8000`).
3. ngrok is tunneling to :8000 and the Sendblue dashboard webhook URL points at it.
4. Ara has a Google Calendar connector authenticated in `app.ara.so` for the presenter's account.
5. Phone replies to the gateway roundtrip successfully (phase 1 test 4 passed).

## Ara secrets to set

Via Ara's secret store (not `.env` — these are read by the deployed automation):

| Secret | Value |
|---|---|
| `GATEWAY_URL` | current ngrok URL, e.g. `https://xxxx.ngrok-free.app` |
| `GATEWAY_KEY` | same value as the gateway's `.env` `GATEWAY_KEY` |

**When ngrok rotates (free tier rotates on restart), update `GATEWAY_URL`.** Or reserve a stable ngrok domain and set it once.

## Tool surface

Six `@ara.tool`s on `app.py`. Each either calls the gateway over HTTP or reads/writes Ara's sandbox filesystem. No direct Sendblue calls in Ara.

| Tool | Backs onto | Notes |
|---|---|---|
| `create_session(initiator_handle, participants, duration_min, window)` | `POST gateway/sessions` + write to sandbox | returns `session_id` |
| `send_to_participant(session_id, handle, body)` | `POST gateway/send` | returns `message_handle` |
| `read_inbound(session_id, since_ts)` | `GET gateway/inbound` | returns list; Ara calls repeatedly |
| `set_participant_status(session_id, handle, status, data)` | sandbox file write | update per-participant state |
| `get_session_state(session_id)` | sandbox file read | full merged state |
| `propose_time(session_id)` | in-tool logic | intersect freebusy + declared |

GCal reads/writes and Gmail sends go through Ara connector **skills**, not tools:
- `connectors.google_calendar.list_events` (for freebusy)
- `connectors.google_calendar.create_event`
- `connectors.gmail.send_email`

`allow_connector_tools=False` stays — judges want determinism.

## Session storage in Ara's sandbox

Single JSON file: `sandbox://sessions/{session_id}.json`. Schema matches Phase 1's (see `docs/phase1.md § In-memory session schema`).

Why two copies of the session (gateway + Ara)?
- Gateway needs just enough to route inbound webhooks (phone → session_id) and answer `/inbound` queries.
- Ara needs the full brain: participant statuses, declared prefs, freebusy arrays, proposed_time, confirmation state.
- They're separate processes with separate lifecycles. Syncing would be pointless ceremony.

Ara's copy is authoritative for scheduling decisions. The gateway's copy is ephemeral routing metadata.

## Tool implementations (skeleton)

All tools use `httpx` (sync is fine — Ara calls tools sync). Gateway URL + key come from `ara.secret(...)`.

```python
import httpx, json, os
import ara_sdk as ara
from ara_sdk import connectors, tool, secret

GATEWAY_URL = secret("GATEWAY_URL")
GATEWAY_KEY = secret("GATEWAY_KEY")
SANDBOX = "/sandbox"  # whatever Ara exposes; adjust to SDK

def _headers():
    return {"X-Gateway-Key": GATEWAY_KEY, "content-type": "application/json"}

def _session_path(session_id: str) -> str:
    return f"{SANDBOX}/sessions/{session_id}.json"

def _read_session(session_id: str) -> dict:
    with open(_session_path(session_id)) as f:
        return json.load(f)

def _write_session(session_id: str, s: dict) -> None:
    os.makedirs(f"{SANDBOX}/sessions", exist_ok=True)
    with open(_session_path(session_id), "w") as f:
        json.dump(s, f)


@tool
def create_session(initiator_handle: str, participants: list[dict],
                   duration_min: int, window: dict) -> dict:
    """Register a new scheduling session with the gateway AND Ara sandbox."""
    body = {
        "initiator": {"handle": initiator_handle},
        "participants": participants,
        "duration_min": duration_min,
        "window": window,
    }
    r = httpx.post(f"{GATEWAY_URL}/sessions", headers=_headers(), json=body, timeout=10)
    r.raise_for_status()
    session_id = r.json()["session_id"]
    _write_session(session_id, {
        "session_id": session_id,
        "initiator": {"handle": initiator_handle},
        "participants": [{**p, "status": "pending", "freebusy": [], "declared": None} for p in participants],
        "duration_min": duration_min,
        "window": window,
        "proposed_time": None,
        "confirmed": False,
    })
    return {"session_id": session_id}


@tool
def send_to_participant(session_id: str, handle: str, body: str) -> dict:
    r = httpx.post(f"{GATEWAY_URL}/send", headers=_headers(),
                   json={"session_id": session_id, "to": handle, "body": body}, timeout=35)
    r.raise_for_status()
    return r.json()


@tool
def read_inbound(session_id: str, since_ts: str | None = None) -> list[dict]:
    params = {"session_id": session_id}
    if since_ts:
        params["since"] = since_ts
    r = httpx.get(f"{GATEWAY_URL}/inbound", params=params, timeout=10)
    r.raise_for_status()
    return r.json()


@tool
def set_participant_status(session_id: str, handle: str, status: str,
                           data: dict | None = None) -> dict:
    s = _read_session(session_id)
    for p in s["participants"]:
        if p["handle"] == handle:
            p["status"] = status
            if data:
                p.update(data)
            break
    _write_session(session_id, s)
    return {"ok": True}


@tool
def get_session_state(session_id: str) -> dict:
    return _read_session(session_id)


@tool
def propose_time(session_id: str) -> dict:
    """Intersect each participant's freebusy + declared prefs. First 30-min slot wins."""
    s = _read_session(session_id)
    # Dumb algorithm for v1: walk the window in 30-min steps, return first slot
    # where every connected participant is free AND no declared pref excludes it.
    # If nobody is connected yet and we have no declared prefs, return {"error": "need more info"}.
    # Implementation detail — keep it short and readable.
    raise NotImplementedError  # TODO in this phase
```

## System prompt

```
You are a group scheduler. The initiator texts you a request like
"30 min next week with Alex and Jordan for coffee." Your job:

1. Parse participants (names + phone numbers), duration, and window.
2. Call create_session to open a session.
3. For each participant: if their calendar is connected in Ara, read free/busy
   silently via the google_calendar skill. Otherwise, call send_to_participant
   to ask them via iMessage. Message must be short and human — "Hey! quick 30
   min next week? what times work?"
4. Poll read_inbound every ~10s. When a participant replies, call
   set_participant_status with status="replied" and data={"declared": body}.
5. Once every participant is either "connected" or "replied", call propose_time
   to find a slot.
6. iMessage the initiator with the proposal and wait for "yes" / "confirm".
7. On confirmation: call google_calendar.create_event with all participants,
   then gmail.send_email with a short agenda to each.
8. If the initiator replies anything other than yes (no, change, etc.), ask
   what to change and redo step 5-6.

Rules:
- Never ask the initiator for info you can infer.
- Never book without explicit confirmation.
- Keep iMessage copy short and human — 1-2 sentences max.
- If Sendblue downgraded a message to SMS, don't retry; just note in logs.
- If read_inbound returns empty for >2 minutes, nudge the initiator.
```

## Implementation steps (order matters)

### Step 1 — Rewrite `app.py` tools
Replace every `NotImplementedError` with the skeletons above. `propose_time` can stay `NotImplementedError` for step 1; we fill it in step 3.

**Logical checks:**
- `create_session` writes to both gateway and sandbox.
- `read_inbound` passes `since` only when set (don't send empty string).
- `set_participant_status` is the *only* mutator of `s["participants"]`.
- No direct Sendblue calls in `app.py`.

### Step 2 — Deploy and smoke-test
```bash
ara deploy
ara run
```

iMessage `+17862139363`: "30 min next week with yourself for coffee."

Expected: Ara calls `create_session`, then (because there's only one participant and they're you), either resolves silently via GCal or asks via iMessage. Either way, you see tool calls in `ara run` output.

**Fail modes:**
- `Connection refused` to gateway → ngrok rotated. Update `GATEWAY_URL` secret, redeploy.
- `401 bad gateway key` → Ara's `GATEWAY_KEY` secret doesn't match `.env` value in gateway.
- Gateway 404 on session → session was created against a gateway process that got restarted. Restart Ara too (or implement auto-recreate on 404 — premature).

### Step 3 — Implement `propose_time`
Start dumb: walk the window at 30-min steps, return the first slot where every "connected" participant's freebusy has no overlap **and** no "replied" participant's declared string excludes it.

Excluded-time parsing is the hard part. For the demo, cheat: if declared says "tues after 3" or "weds am", hand-code a few regex rules. Don't build a NLP tool. The demo script has one presenter who will reply in a predictable format.

### Step 4 — End-to-end with one non-connected participant
This is the critical rehearsal path. Two phones in the room:
- Your phone (initiator, GCal connected).
- Someone else's phone (not connected).

Run the flow. Watch the second phone receive an iMessage; reply from it; watch Ara propose; reply "yes" from your phone; verify a GCal invite lands.

### Step 5 — Calendar event + email
`connectors.google_calendar.create_event` with attendees. `connectors.gmail.send_email` with a short agenda. Both are skill calls, not tools — Ara runs them directly from the prompt.

### Step 6 — Cleanup
- Delete `inbound.py`.
- Fix the Twilio comments in `app.py` docstring.
- Update `docs/app.md` and `docs/gateway.md` or delete them.
- Optionally update `CLAUDE.md` to replace Redis/Fly.io references with "in-memory + ngrok".

## How you verify Phase 2

1. **Tool stubs return real values.** In `ara run`, create a session, send yourself an iMessage, poll inbound — tool outputs should match what the gateway returns.
2. **Blue bubble** on the recipient's phone, not green.
3. **Reply routes back.** `read_inbound` returns the reply within a polling cycle.
4. **GCal invite lands.** After "yes", both calendars show the event.
5. **90-second end-to-end.** Time it. If >90s, cut scope (drop the agenda email first).

## Explicit non-goals (don't do these in Phase 2)

- Rescheduling / cancellation flows.
- Multiple concurrent sessions per initiator.
- Group iMessage threads (`group_id != ""`).
- MMS (`media_url`).
- Retry logic in Ara — the runtime handles it.
- Persisting Ara sessions to disk beyond sandbox default.
- A web UI.
- Tests.

## Fallback if we're running out of time (H-minus-2)

If `propose_time` with GCal intersection is misbehaving close to demo:
1. Hard-code the demo slot (`"Tuesday 3:30pm"`) in `propose_time`.
2. Demo the messaging flow end-to-end; skip the intersection logic.
3. Mixed mode still works (blue bubbles), initiator still gets asked to confirm, event still gets created.

**The demo is the messaging. The scheduling intelligence is the nice-to-have.**
