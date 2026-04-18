# Brief: Twilio Gateway (`gateway/`)

You are implementing the Twilio gateway half of the group-scheduler hackathon project. Read `CLAUDE.md` at the repo root first. Do not weaken the three "why this wins" properties.

## Your scope

- `gateway/main.py` and `gateway/store.py` only. Do **not** touch `app.py`.
- The Ara automation is being built in parallel. Treat your HTTP surface as a contract — if you change it, update `docs/app.md` and flag it.

## What exists

Skeleton `gateway/main.py` with three FastAPI routes stubbed, and `gateway/store.py` with a `Store` class signature. Twilio + Upstash env vars are already referenced.

## What to build

### 1. `Store` (`gateway/store.py`)

Back it with Upstash Redis REST (simplest; no connection pool). Use `httpx` against `{STORE_URL}/...` with `Authorization: Bearer {STORE_TOKEN}`.

Keys:
- `session:{session_id}` → JSON blob (schema in CLAUDE.md)
- `participant:{e164_number}` → `session_id` (index so `/sms` can route)

Methods to implement:
- `get_session(session_id)` — GET, JSON-decode.
- `put_session(session_id, session)` — SET, JSON-encode.
- `append_inbound(session_id, msg)` — read-modify-write is fine for hackathon scale. One session, one initiator, low concurrency.
- `session_id_for_number(number)` — GET `participant:{number}`.
- `bind_number(number, session_id)` — SET `participant:{number}`.

### 2. Routes (`gateway/main.py`)

#### `POST /sms` — Twilio inbound webhook

- Form fields: `From`, `Body` (and ignore the rest).
- `session_id = store.session_id_for_number(From)`. If none, drop silently (return empty TwiML) — a human texted our number unprompted.
- Append `{from: From, body: Body, ts: utcnow iso}` to that session's `inbound`.
- Return `Response(content="<Response/>", media_type="application/xml")`.

#### `POST /send` — authenticated outbound

- Header `X-Gateway-Key` must match env `GATEWAY_KEY`; 401 otherwise.
- Body: `{to, body, session_id}`.
- **Bind the number to the session first** (`store.bind_number(to, session_id)`) so the reply can be routed.
- `twilio.messages.create(to=to, from_=TWILIO_FROM, body=body)`. Return `{"sid": msg.sid}`.

#### `GET /inbound` — poll endpoint for Ara

- Query: `session_id`, optional `since` (ISO ts).
- Read `session.inbound`, filter `ts > since`, return as JSON list.

### 3. `POST /bind` (optional, nice-to-have)

If the Ara agent wants to pre-bind a participant before sending (e.g. to track a "pending" status before the first outbound), expose `POST /bind` with `{number, session_id}` behind the same `X-Gateway-Key`. Otherwise the bind in `/send` is sufficient.

### 4. Deployment

- Target: Fly.io free tier. `fly launch`, set env vars, `fly deploy`.
- Have ngrok as a local-rehearsal fallback — the Twilio webhook URL must be publicly reachable.
- Put the deployed URL in the Ara secret `GATEWAY_URL` so `app.py` can reach you.

## Don'ts

- Don't put business logic in the gateway. It's dumb: receive, persist, forward. The agent reasons.
- Don't add a queue, retry layer, or rate limiter. Twilio + FastAPI + Upstash is the whole stack.
- Don't share the Twilio creds with Ara — they live in the gateway's env only.
- Don't sign or verify Twilio webhooks for the demo (nice in prod, wastes time today).
- Don't write tests. Curl the endpoints once end-to-end and move on.

## Definition of done

1. `curl -X POST $GATEWAY_URL/send -H "X-Gateway-Key: $K" -d '{"to":"+1...","body":"hi","session_id":"sess_test"}'` actually delivers an SMS.
2. Replying to that SMS from a phone appends to the session's `inbound` array.
3. `curl "$GATEWAY_URL/inbound?session_id=sess_test"` returns the reply.

When those three work, stop and go help rehearse.
