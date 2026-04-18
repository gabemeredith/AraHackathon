# CLAUDE.md — Group Scheduler

## What we're building

iMessage-native group meeting scheduler. One phone number. User texts:
"schedule 30 min with Alex and Jordan next week for coffee." The agent reads
calendars where it can, iMessages the humans where it can't, picks a time,
confirms, and books a real GCal event. Mixed mode is the whole point.

Hackathon: Ara x Cornell, April 18, 2026. One day. Optimizing for **Most Viral**.
Target demo: three students on stage, 90 seconds, end-to-end.

## Why this wins (do not weaken these)

1. **No link, no form.** GCal-connected participants resolve silently.
2. **It books.** Real invite, real agenda, real confirmation email.
3. **Mixed mode.** Non-users just reply to an iMessage like a human would.
4. **Blue bubbles on stage.** It reads as a person texting, not a bot. That's the viral clip.

If a change weakens 1–4, it's the wrong change.

## Messaging rail: Sendblue (confirmed working)

We use [Sendblue](https://sendblue.co) as the iMessage API. They run the Mac infrastructure; we get an HTTP API and webhooks. **Inbound has been tested end-to-end** (see `inbound.py` → payload below).

- Sendblue number (demo): `+17862139363`
- `service: "iMessage"` on inbound = real blue bubble confirmed
- Outbound: `POST https://api.sendblue.co/api/send-message`
- Inbound: Sendblue POSTs to our gateway's `/sendblue/inbound` endpoint

No Mac, no BlueBubbles, no Android. Sendblue is the rail.

## Architecture

Two processes. Keep them separate.

```
┌─────────────────────┐          ┌──────────────────────────┐
│ Ara Automation      │  HTTP    │ Sendblue Gateway         │
│ (app.py)            │ ───────▶ │ (gateway/main.py)        │
│ - agent loop        │          │ - POST /sendblue/inbound │
│ - GCal connector    │          │ - POST /send → Sendblue  │
│ - linq to initiator │          │ - GET /inbound (for Ara) │
└─────────────────────┘          └──────────────────────────┘
         │                                  │
         │                                  ▼
         │                      ┌──────────────────────┐
         │                      │ Sendblue API         │
         │                      │ (iMessage out + in)  │
         │                      └──────────────────────┘
         │                                  │
         └──────── shared store ────────────┘
              (Upstash Redis — one JSON blob per session_id)
```

- **Ara** owns: agent loop, GCal free/busy + `create_event`, messaging the initiator via `linq_send_message`, sandbox filesystem for per-run scratch.
- **Sendblue gateway** owns: calling Sendblue's HTTP API to send iMessages, receiving Sendblue webhooks on inbound, persisting inbound messages to the shared store, exposing a read endpoint Ara tools poll.
- **Our code** is the Automation + ~6 tools + a ~120-line FastAPI service.

Why a second process: Ara doesn't expose public HTTP endpoints, so Sendblue's inbound webhook must land somewhere else.

## Repo layout

```
group-scheduler/
  app.py                  # ara.Automation + @ara.tool defs
  inbound.py              # scratch receiver used to confirm Sendblue works (keep, delete later)
  gateway/
    main.py               # FastAPI: /sendblue/inbound, /send, /inbound
    store.py              # Upstash Redis client + session CRUD
    sendblue.py           # thin Sendblue HTTP client (send, lookup)
  requirements.txt        # ara-sdk, fastapi, uvicorn, httpx, redis, python-dotenv
  .env                    # local secrets (gitignored)
  .env.example            # commit this
  README.md               # demo script + setup
```

Flat. No `src/`, no `models/`, no `config/`. One-day hackathon.

## Sendblue payload shape (confirmed from live inbound)

This is the exact payload Sendblue POSTs to `/sendblue/inbound`:

```json
{
  "accountEmail": "cohort",
  "content": "Hi",
  "is_outbound": false,
  "status": "RECEIVED",
  "error_code": null,
  "error_message": null,
  "error_reason": null,
  "message_handle": "FA9E7710-9E14-421D-B0F9-9394F061CDDA",
  "date_sent": "2026-04-18T18:56:03.717Z",
  "date_updated": "2026-04-18T18:56:03.724Z",
  "from_number": "+19144063907",
  "number": "+19144063907",
  "to_number": "+17862139363",
  "was_downgraded": null,
  "plan": "free_api",
  "media_url": "",
  "message_type": "message",
  "group_id": "",
  "participants": [],
  "send_style": "",
  "opted_out": false,
  "error_detail": null,
  "sendblue_number": "+17862139363",
  "service": "iMessage",
  "group_display_name": null
}
```

### Fields we care about

| Field | Use |
|---|---|
| `from_number` | participant's handle (E.164) |
| `content` | message body |
| `message_handle` | unique ID — **dedup on this** (Sendblue retries on slow responses) |
| `date_sent` | ISO timestamp for ordering |
| `service` | must be `"iMessage"` for demo; `"SMS"` means downgraded, warn the user |
| `was_downgraded` | explicit downgrade flag — show a warning in logs |
| `opted_out` | respect STOP; skip sending |
| `group_id`, `participants` | empty in 1:1 (our case); non-empty = group chat, ignore for now |
| `media_url` | MMS attachment; ignore for v1 |

### Outbound payload (to Sendblue)

`POST https://api.sendblue.co/api/send-message` with headers:

```
sb-api-key-id: $SENDBLUE_API_KEY_ID
sb-api-secret-key: $SENDBLUE_API_SECRET
content-type: application/json
```

Body:

```json
{ "number": "+1...", "content": "hi", "send_style": "" }
```

Returns `{ "message_handle": "...", "status": "QUEUED", ... }`. Store the `message_handle` on outbound for later correlation.

## Webhook verification

Sendblue sends the `sb-signing-secret` header on every inbound. We verify it matches `SB_SECRET` from `.env` (already working in `inbound.py`). Gateway enforces the same check.

## Ara SDK contract

`pip install ara-sdk`. Import surface:

```python
import ara_sdk as ara
from ara_sdk import connectors, tool, secret, env

@ara.tool
def send_to_participant(handle: str, body: str) -> dict:
    """POST to Sendblue gateway. `handle` is an E.164 phone number. Returns {"ok": bool, "message_handle": str}."""
    ...

ara.Automation(
    "group-scheduler",
    system_instructions=SYSTEM_PROMPT,
    tools=[send_to_participant, read_inbound, set_participant_status,
           get_session_state, propose_time, create_session],
    skills=[
        connectors.google_calendar.list_events,
        connectors.google_calendar.create_event,
        connectors.gmail.send_email,  # confirmation + agenda link
    ],
    allow_connector_tools=False,
)
```

`allow_connector_tools=False` is mandatory. Judges see determinism.

## Tool surface (keep it tight)

| Tool | Purpose |
|---|---|
| `create_session(initiator_handle, participants, duration_min, window)` | open a new scheduling session in the store, return `session_id` |
| `send_to_participant(session_id, handle, body)` | outbound iMessage via gateway |
| `read_inbound(session_id, since_ts)` | poll gateway for replies belonging to this session |
| `set_participant_status(session_id, handle, status, data)` | update merged state |
| `get_session_state(session_id)` | read full merged state |
| `propose_time(session_id)` | intersect free/busy + declared prefs, return best slot |

GCal reads/writes and Gmail sends go through the connector skills — do not wrap them.

## Shared store schema

One JSON blob per session, keyed `session:{session_id}` in Redis.

```json
{
  "session_id": "sess_abc",
  "initiator": { "handle": "+1...", "email": "..." },
  "participants": [
    {
      "handle": "+1...",
      "name": "Alex",
      "status": "connected|pending|replied",
      "freebusy": [],
      "declared": "Tues after 3"
    }
  ],
  "duration_min": 30,
  "window": { "start_iso": "...", "end_iso": "..." },
  "inbound": [
    { "message_handle": "...", "from": "+1...", "body": "...", "ts": "..." }
  ],
  "proposed_time": null,
  "confirmed": false,
  "seen_handles": ["FA9E7710-..."]
}
```

- Write path on inbound webhook: find the session where `from_number` matches a participant handle; append to `inbound` if `message_handle` not in `seen_handles`; add to `seen_handles`. Dedup lives here.
- Status transitions: `pending → replied` (free-text) or `pending → connected` (GCal linked, out-of-band).
- Session lookup: maintain a secondary key `handle:{phone} → session_id` when a session opens. Clear on confirmation.

## Sendblue gateway contract

- `POST /sendblue/inbound` — Sendblue webhook. Verify `sb-signing-secret`. Parse payload. Look up session by `from_number`. Dedup on `message_handle`. Append to `session.inbound`. Return `{ "ok": true }`.
- `POST /send` — body `{ session_id, to, body }`. Auth header `X-Gateway-Key`. Calls Sendblue's `/api/send-message`. Returns `{ message_handle }`.
- `GET /inbound?session_id=&since=` — returns inbound messages for that session after timestamp. Used by Ara's `read_inbound` tool.

## Environment (`.env`)

```
# Sendblue
SB_SECRET=                       # Global Secret pasted into Sendblue dashboard
SENDBLUE_API_KEY_ID=
SENDBLUE_API_SECRET=
SENDBLUE_FROM_NUMBER=+17862139363

# Gateway
GATEWAY_KEY=                     # shared secret: Ara tool ↔ gateway /send
GATEWAY_URL=                     # public URL of the gateway (ngrok for dev, Fly.io for demo)

# Shared store
REDIS_URL=                       # Upstash Redis REST URL
REDIS_TOKEN=
```

Mirror this in `.env.example` with empty values. `.env` is gitignored.

## Tunneling (local dev)

```bash
uvicorn gateway.main:app --port 8000
ngrok http 8000
```

Paste `https://<ngrok>/sendblue/inbound` into Sendblue's Inbound Messages webhook. Re-paste if the ngrok URL rotates between runs (free tier rotates on restart — use `ngrok http --domain=<reserved>` if you reserved one).

## Demo script (rehearse this, not the code)

1. Presenter iMessages `+17862139363`: "30 min next week with Alex and Jordan for coffee." (Blue bubble.)
2. Agent replies to presenter: "On it — reaching out to Alex and Jordan."
3. Alex (GCal connected in Ara): silent auto-resolve — no message.
4. Jordan (not connected): receives iMessage from `+17862139363`. Replies "tues after 3 or weds am."
5. Agent iMessages presenter: "Tuesday 3:30pm works. Book it?" Presenter replies "yes."
6. Everyone gets GCal invite + short agenda doc link in the email body.

Target: under 90 seconds. Practice the "yes" path only. No edge cases on stage. All three phones on stage should be iPhones so every bubble is blue — that's the clip.

## Build order (H1–H8)

- **H1** — `gateway/main.py`: promote `inbound.py` into the real gateway. Add `/send` (calls Sendblue) and `/inbound` (reads from store). Wire `store.py` against Upstash. Round-trip test: POST `/send` → iPhone rings → reply → see it in `/inbound`.
- **H2** — `app.py`: stub `@ara.tool`s against the gateway. Hard-code one fake session. `ara deploy` + `ara run`, send yourself a message, watch the loop.
- **H3** — GCal free/busy via `connectors.google_calendar.list_events`. Real availability for the presenter.
- **H4** — `propose_time` logic: intersect connected participants' free/busy with declared prefs from replies. Keep it dumb — first 30-min slot that works.
- **H5** — End-to-end with one non-connected participant. This is the critical rehearsal.
- **H6** — `create_event` + Gmail confirmation with agenda link.
- **H7** — Polish copy, deploy gateway to Fly.io with a stable URL, update Sendblue webhook to the stable URL.
- **H8** — Rehearse 3x. Stop coding.

If behind at H5, cut H6's agenda link. **Never cut mixed mode.**

## Secrets (via `ara.secret(...)`)

- `GATEWAY_URL` — public URL of the Sendblue gateway
- `GATEWAY_KEY` — shared secret for outbound auth
- (Sendblue credentials live in the gateway's env, not Ara's. Ara only talks to the gateway.)

## Non-goals (for today)

- Timezone disambiguation beyond the initiator's GCal default.
- Rescheduling, cancellation, recurring events.
- More than one pending session per initiator at a time.
- Group iMessage threads (`group_id != ""`). Only 1:1 for v1.
- MMS / media (`media_url`).
- A web UI. The medium is the message.
- Tests. You have one day.

## Don'ts

- Don't fork the ara-python-sdk repo — it's a mirror, edits get overwritten.
- Don't build a framework. The SDK is the framework.
- Don't add retry logic, queueing, or observability — Ara runtime + Sendblue both handle their own.
- Don't put Sendblue calls inside an `@ara.tool` directly. Route through the gateway so inbound and outbound share one surface and one store.
- Don't expand scope mid-demo-day.
- Don't trust a single inbound webhook — Sendblue retries. **Dedup on `message_handle`.**
- Don't let `service` be `"SMS"` on stage. If a downgrade happens in rehearsal, investigate why (usually Wi-Fi Calling off, or recipient isn't on iMessage).
