# Phase 1 — Sendblue Gateway (done)

Essentials to carry into Phase 2. Assume everything in this file is **already built and working** — don't redesign it.

## What it does

HTTP gateway that sits between Sendblue (iMessage rail) and whatever agent is doing the scheduling. Owns outbound sends, inbound webhook, dedup, and phone→session routing.

```
Sendblue ──(webhook)──► Gateway ──(polled by)──► Ara
Ara ────(/send)───────► Gateway ──(POST)───────► Sendblue ──► iPhone
```

Gateway runs on laptop, exposed via ngrok. In-memory store (lost on restart). No Redis, no Fly.io.

## Run it

```bash
uvicorn gateway.main:app --reload --port 8000
ngrok http 8000
# paste https://<ngrok>/sendblue/inbound into Sendblue dashboard → Inbound Messages webhook
```

## Endpoints

| Method | Path | Auth | Purpose |
|---|---|---|---|
| GET | `/health` | none | `{"ok": true}` |
| POST | `/sessions` | `X-Gateway-Key` | create session, bind participant phones to it |
| POST | `/send` | `X-Gateway-Key` | outbound iMessage via Sendblue |
| POST | `/sendblue/inbound` | `sb-signing-secret` header | Sendblue webhook; dedup + route |
| GET | `/inbound?session_id=&since=` | none | read inbound messages for a session |

### Request/response shapes

**POST /sessions**
```json
// request
{
  "initiator": {"handle": "+1...", "email": "..."},
  "participants": [{"handle": "+1...", "name": "Alex"}],
  "duration_min": 30,
  "window": {"start_iso": "2026-04-19T00:00:00Z", "end_iso": "2026-04-26T00:00:00Z"}
}
// response
{"session_id": "sess_xxxxxxxx"}
```

**POST /send**
```json
// request
{"session_id": "sess_xxx", "to": "+1...", "body": "hi"}
// response
{"message_handle": "uuid", "status": "QUEUED"}
```

**GET /inbound?session_id=sess_xxx&since=<iso-8601-optional>**
```json
// response
[{"message_handle": "...", "from": "+1...", "body": "...", "ts": "2026-04-18T..."}]
```

**POST /sendblue/inbound** (called by Sendblue, not by us)
Response: `{"ok": true, "deduped": bool}`

## In-memory session schema

Keyed by `session_id`. Also a secondary `_handle_index: dict[phone, session_id]` so inbound webhooks can route by `from_number`.

```python
{
  "session_id": "sess_xxx",
  "initiator": {"handle": "+1...", "email": "..."},
  "participants": [
    {"handle": "+1...", "name": "Alex", "status": "pending", "freebusy": [], "declared": None}
  ],
  "duration_min": 30,
  "window": {"start_iso": "...", "end_iso": "..."},
  "inbound": [
    {"message_handle": "...", "from": "+1...", "body": "...", "ts": "..."}
  ],
  "proposed_time": None,
  "confirmed": False,
  "seen_handles": ["<message_handle>", ...]  # dedup set
}
```

Participant `status`: `pending | replied | connected`.

## Sendblue inbound payload (as received on `/sendblue/inbound`)

Fields we read:

| Field | Use |
|---|---|
| `from_number` | sender E.164 — index key |
| `content` | message body |
| `message_handle` | unique ID — **dedup on this** |
| `date_sent` | ISO timestamp |
| `service` | must be `"iMessage"` (`"SMS"` = downgraded, warn) |
| `was_downgraded` | explicit downgrade flag |
| `opted_out` | respect STOP |
| `is_outbound` | skip our own sends |
| `group_id` | non-empty = group chat, skip |

Full payload example lives in CLAUDE.md § "Sendblue payload shape".

## Sendblue outbound body (what `/send` posts to Sendblue)

```json
{
  "number": "+1...",
  "from_number": "+17862139363",
  "content": "...",
  "send_style": ""
}
```

Headers: `sb-api-key-id`, `sb-api-secret-key`, `content-type: application/json`.

**Gotcha (already patched):** Sendblue's free-API plan **requires `from_number` in the request body**. The SDK docs don't mention this; discovered from a 400 response.

## Dedup contract

- Sendblue retries inbound webhooks on slow responses.
- `store.append_inbound` checks `message_handle in session["seen_handles"]` before mutating.
- Returns `True` if newly stored, `False` if dropped as duplicate.
- Handler returns `{"ok": true, "deduped": true}` so ngrok/logs can see it.

## Env vars (gateway reads at import)

```
SB_SECRET=gabecaleb                                # Sendblue signing secret
SENDBLUE_API_KEY_ID=<from Sendblue dashboard>
SENDBLUE_API_SECRET=<from Sendblue dashboard>
SENDBLUE_FROM_NUMBER=+17862139363
GATEWAY_KEY=<any long random string>               # auth between Ara and gateway
```

Uvicorn's `--reload` only watches `.py` files. **Env changes require a full restart.**

## State caveats for Phase 2

- **Store is in-memory.** If you restart uvicorn mid-run, sessions vanish. Ara must tolerate this (recreate the session via `POST /sessions` if it 404s on an inbound call). Trivially — re-registering a session with the same participants is idempotent from Ara's POV.
- **One phone → one session** at a time. Binding a phone to a new session overwrites the old binding. Fine per CLAUDE.md non-goal (one pending session per initiator).
- **Timestamps are ISO-8601 strings.** `since` filter is string comparison — works because ISO-8601 is lexicographically sortable.

## Known stale (leave alone, revisit later)

- `CLAUDE.md` still references Upstash Redis and Fly.io — ignore, those were dropped.
- `docs/gateway.md` references Twilio — stale, delete in a cleanup pass.
- `docs/app.md` references Twilio in comments — stale.
- `app.py` has Twilio mentions in docstrings — fix during Phase 2 when rewriting the tools anyway.
- `inbound.py` — the original scratch webhook. Keep as fallback reference until Phase 2 round-trips end-to-end.

## Verified behavior (what passed)

1. `GET /health` → 200 `{"ok":true}` ✓
2. `POST /sessions` → returns `session_id` ✓
3. `POST /send` → blue bubble on phone, `{"message_handle": ...}` returned ✓
4. Reply from phone → appears in `GET /inbound?session_id=...` ✓
5. Dedup logic: code path inspected (set membership check in `append_inbound`) ✓
6. `since` filter returns `[]` for far-future timestamp ✓
