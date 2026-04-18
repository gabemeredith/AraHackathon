import os
import pickle
from datetime import datetime, timezone, timedelta

from google.auth.transport.requests import Request
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

SCOPES = ["https://www.googleapis.com/auth/calendar.readonly"]
TOKEN_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "token.pickle")
EASTERN = timezone(timedelta(hours=-5))  # fixed EST (UTC-5)

DIM   = "\033[2m"
BOLD  = "\033[1m"
GREEN = "\033[32m"
RED   = "\033[31m"
CYAN  = "\033[36m"
RESET = "\033[0m"

SEP = "  " + "─" * 46


def fmt_range(start_iso: str, end_iso: str) -> str:
    s = datetime.fromisoformat(start_iso.replace("Z", "+00:00")).astimezone(EASTERN)
    e = datetime.fromisoformat(end_iso.replace("Z", "+00:00")).astimezone(EASTERN)
    day = s.strftime("%a %b %-d")
    if s.strftime("%p") == e.strftime("%p"):
        return f"{day}   {s.strftime('%-I:%M')} – {e.strftime('%-I:%M %p')} EST"
    return f"{day}   {s.strftime('%-I:%M %p')} – {e.strftime('%-I:%M %p')} EST"


def get_credentials():
    creds = None
    if os.path.exists(TOKEN_PATH):
        with open(TOKEN_PATH, "rb") as f:
            creds = pickle.load(f)

    if creds and creds.expired and creds.refresh_token:
        creds.refresh(Request())
        with open(TOKEN_PATH, "wb") as f:
            pickle.dump(creds, f)
        return creds

    if not creds or not creds.valid:
        print(f"\n  {DIM}opening browser for Google sign-in...{RESET}\n")
        flow = InstalledAppFlow.from_client_secrets_file("client_secrets.json", SCOPES)
        creds = flow.run_local_server(port=0)
        with open(TOKEN_PATH, "wb") as f:
            pickle.dump(creds, f)

    return creds


def prompt_emails():
    print(f"  {DIM}enter emails to check  (blank line to finish){RESET}\n")
    emails = []
    while True:
        try:
            raw = input(f"  {CYAN}›{RESET} ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break
        if not raw:
            break
        if "@" not in raw:
            print(f"  {RED}not a valid email — skipping{RESET}")
            continue
        emails.append(raw)
    return emails


def main():
    print()
    print(f"  {CYAN}╭────────────────────────────────────────╮{RESET}")
    print(f"  {CYAN}│{RESET}   {BOLD}group scheduler{RESET}   {DIM}·{RESET}   free / busy    {CYAN}│{RESET}")
    print(f"  {CYAN}╰────────────────────────────────────────╯{RESET}")
    print()

    emails = prompt_emails()
    if not emails:
        print(f"\n  {RED}no emails entered — exiting{RESET}\n")
        return

    print(f"\n  {DIM}authenticating...{RESET}")
    creds = get_credentials()
    service = build("calendar", "v3", credentials=creds)

    now      = datetime.now(timezone.utc)
    one_week = now + timedelta(days=7)
    now_e    = now.astimezone(EASTERN)
    end_e    = one_week.astimezone(EASTERN)

    print(f"  {DIM}fetching calendars...{RESET}\n")
    body = {
        "timeMin": now.isoformat(),
        "timeMax": one_week.isoformat(),
        "items": [{"id": e} for e in emails],
    }
    result = service.freebusy().query(body=body).execute()

    date_range = f"{now_e.strftime('%b %-d')} – {end_e.strftime('%b %-d')}"
    print(f"  {DIM}busy blocks  ·  {date_range}  ·  Eastern{RESET}")
    print(SEP)

    all_busy = []
    for email in emails:
        cal    = result["calendars"].get(email, {})
        busy   = cal.get("busy", [])
        errors = cal.get("errors", [])

        print()
        if errors:
            print(f"  {BOLD}{email}{RESET}  {DIM}— private or not found{RESET}")
            print(f"  {DIM}  fix: share their calendar with your Google account{RESET}")
        elif not busy:
            print(f"  {BOLD}{email}{RESET}")
            print(f"  {DIM}  no busy blocks visible{RESET}")
        else:
            n = len(busy)
            print(f"  {BOLD}{email}{RESET}  {DIM}— {n} busy block{'s' if n != 1 else ''}{RESET}")
            for b in busy:
                print(f"  {DIM}  {fmt_range(b['start'], b['end'])}{RESET}")
            all_busy.extend(busy)

    print()
    print(SEP)

    from scheduling import propose_time
    slot = propose_time(
        busy_blocks=all_busy,
        window_start_iso=now.isoformat(),
        window_end_iso=one_week.isoformat(),
        duration_min=30,
    )

    print()
    if slot.get("start"):
        time_str = fmt_range(slot["start"], slot["end"])
        print(f"  {BOLD}best 30-min slot{RESET}  {DIM}·{RESET}  {GREEN}{time_str}{RESET}")
    else:
        print(f"  {RED}no slot found in the next 7 days{RESET}")
    print()


if __name__ == "__main__":
    main()
