# Brief: Ara Automation (`app.py`)

You are implementing the Ara Automation half of the group-scheduler hackathon project. Read `CLAUDE.md` at the repo root first — it pins the architecture, tool surface, and non-goals. Do not weaken the three "why this wins" properties.

## Your scope

- `app.py` only. Do **not** touch `gateway/`.
- The gateway is being built in parallel by another agent. Treat its HTTP contract (below) as fixed.

## What exists

A skeleton `app.py` with:
- `SYSTEM_PROMPT` (tune if you want, keep it tight)
- 5 `@ara.tool` stubs that `raise NotImplementedError`
- `ara.Automation(...)` wired with Google Calendar + Gmail connector skills and `allow_connector_tools=False`

## What to build

### 1. Implement the 5 tools

| Tool | Behavior |
|---|---|
| `send_to_participant(number, body)` | `httpx.post(f"{GATEWAY_URL}/send", json={to, body, session_id}, headers={"X-Gateway-Key": GATEWAY_KEY})`. Return `{"ok": True, "sid": ...}` or `{"ok": False, "error": ...}`. |
| `read_inbound(since_ts)` | `httpx.get(f"{GATEWAY_URL}/inbound", params={"session_id": ..., "since": since_ts})`. Return list of `{from, body, ts}`. |
| `set_participant_status(number, status, data)` | Read session from sandbox filesystem (`session.json`), mutate the matching participant, write back. Status is one of `pending | replied | connected | declined`. |
| `get_session_state()` | Read `session.json` from sandbox. Create a default if missing, using the initiator's number/email from the run context. |
| `propose_time(window_iso, duration_min)` | Intersect each participant's `freebusy` (from GCal) with each non-connected participant's `declared` string (parse leniently: "tues after 3", "weds am"). Return `{start, end}` in ISO, or `{error: "no_overlap"}`. |

Sandbox filesystem: Ara gives each run a scratch dir. Put the session JSON there. The shape is in CLAUDE.md.

### 2. `session_id`

Generate once per run (e.g. `sess_` + 8 hex chars) and persist in the sandbox `session.json`. Pass it on every gateway call. **Before calling `send_to_participant` for a new number, POST to `{GATEWAY_URL}/bind` with `{number, session_id}`** so the gateway can route that participant's replies back to the right session. (Confirm with the gateway agent that `/bind` exists; if not, include `session_id` in `/send` and let the gateway bind on first outbound.)

### 3. Agent loop expectations

The system prompt already tells the model the loop. Your job is to make sure the tools are sufficient for the model to:

1. Get initiator context via `get_session_state`.
2. For each participant: list GCal free/busy via the connector skill if connected; otherwise `send_to_participant`.
3. Poll `read_inbound` until all replied/connected.
4. Call `propose_time`.
5. Confirm with initiator via Ara's `linq` messaging (built-in — no tool needed).
6. On "yes": `connectors.google_calendar.create_event` + `connectors.gmail.send_email` with a short agenda.

### 4. Parse free-text availability (lenient, not clever)

"tues after 3", "weds am", "Thursday anytime". Accept misspellings. Assume the initiator's timezone (from their GCal primary). Bias toward matching *any* slot — a wrong guess is better than asking twice.

## Don'ts

- Don't wrap GCal or Gmail — use the connector skills directly.
- Don't add retries, backoff, or queues. Ara's runtime handles it.
- Don't put Twilio credentials or SDK calls in `app.py`. Everything SMS goes through the gateway.
- Don't create `src/`, `models/`, `config/`. Keep it flat.
- Don't write tests. Rehearse the demo.

## Definition of done

The demo script in CLAUDE.md runs end-to-end in under 90 seconds in Ara's UI: initiator texts, one participant silent-resolves, one replies via SMS, initiator gets a proposal, says "yes", everyone gets a GCal invite + email.

Ping the gateway agent (via `docs/gateway.md` or the shared contract) if you need to change the HTTP surface.
