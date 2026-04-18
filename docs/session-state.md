# Session State — April 18, 2026

## What we're building
iMessage-native group scheduler. User texts Ara's Linq number → Ara checks Google Calendar freebusy → proposes a time → books it. No Sendblue. No gateway for the core flow.

## Architecture (current)

```
User texts Ara's Linq number
    → ara.Automation in app.py triggers natively
    → check_participant_freebusy() hits Google Calendar freebusy API
    → propose_time() walks window, finds first free slot
    → Ara replies via Linq
    → On "yes": create_event + send_email
```

## Files

| File | Status | Purpose |
|---|---|---|
| `app.py` | ✅ done | 2 tools + 2 skills + system prompt. No gateway code. |
| `scheduling.py` | ✅ done | Pure Python: `check_participant_freebusy` + `propose_time`. No ara_sdk dep. |
| `test_freebusy.py` | ✅ done | Saves token.pickle on first run. Tests both tools. |
| `gateway/` | ✅ unchanged | Sendblue gateway — not needed for core flow, leave alone. |
| `token.pickle` | ✅ on disk | Google OAuth creds from earlier test run. |
| `client_secrets.json` | ✅ on disk | Google OAuth client config. |

## Tools in app.py

```python
check_participant_freebusy(email, window_start_iso, window_end_iso)
# → loads token.pickle (local) or GOOGLE_CREDS_B64 secret (deployed)
# → calls Google freebusy API
# → returns {"busy": [{start, end}], "email": email}
#    or {"error": "no_token" | "calendar_private"}

propose_time(busy_blocks, window_start_iso, window_end_iso, duration_min=30, skip_count=0)
# → walks Mon-Fri 9am-6pm UTC in 30-min steps
# → returns {start, end, start_human} or {error: no_slot_found}
# → skip_count lets agent cycle through slots on "no"
```

## System prompt summary
Parse email + duration + window from message → check_participant_freebusy → propose_time → "X is free [time]. Book it?" → on yes: create_event + send_email.

## Verified working (Tier 1)
```bash
python -c "
from scheduling import check_participant_freebusy, propose_time
import json
r = check_participant_freebusy('yh2356@cornell.edu', '2026-04-20T00:00:00Z', '2026-04-27T00:00:00Z')
print(json.dumps(r, indent=2))
slot = propose_time(r['busy'], '2026-04-20T00:00:00Z', '2026-04-27T00:00:00Z', 30)
print(json.dumps(slot, indent=2))
"
# Returns: 3 busy blocks + first free slot Monday 9:00 AM
```

## Deployed (Tier 3)
```
app_id:      app_7fe2163430b14224bf4371052ce3f6fb
runtime_key: ak_app_dd2f52442c1f4c33056ae5a5d39258b6dc3ca4f7
slug:        group-scheduler
GOOGLE_CREDS_B64: synced to Ara secret store during deploy
```

Deploy command (needed every time GOOGLE_CREDS_B64 isn't already in Ara):
```bash
GOOGLE_CREDS_B64=$(python -c "import pickle,base64; print(base64.b64encode(open('token.pickle','rb').read()).decode())") ara deploy app.py
```

## What's NOT working yet
- **Triggering from terminal**: `ara run app.py` completes immediately with no message — it's a one-shot trigger with no input. Real test requires texting Ara's Linq number from a phone.
- **Messages connector was down** during session — couldn't verify live text → response loop.
- `client.events()` API path found in SDK but HTTP calls timeout (Ara API may require SDK routing, not raw HTTP).

## What to do next
1. Text Ara's Linq number: `"schedule 30 min with yh2356@cornell.edu next week"`
2. Watch `ara logs app.py` in terminal to see tool calls fire
3. If it works, add multi-participant support (combine busy_blocks from multiple freebusy calls)
4. If it doesn't trigger: check app.ara.so that the automation is active and the Linq connector is enabled

## Remaining features (not yet built)
- Multiple participants (system prompt says combine busy_blocks — tools already support it)
- Initiator's own GCal check (call check_participant_freebusy with initiator's email too)
- GCal event creation + Gmail confirmation (connector skills wired, not yet tested)
- Sendblue iMessages to non-Ara participants (gateway exists if needed later)

## Key commands
```bash
ara deploy app.py          # redeploy after code changes
ara logs app.py            # tail live logs
ara run app.py             # fires empty run (not useful for testing)
python test_freebusy.py    # test freebusy + propose_time locally
```
