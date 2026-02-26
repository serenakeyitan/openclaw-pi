#!/usr/bin/env python3
"""Check Feishu calendar for 'kael regular' event today.

Exit code 0 = standup should run, 1 = skip.
Fallback: if calendar API fails, defaults to running on weekdays (Mon-Fri).

Usage:
    python3 feishu_calendar_check.py
    python3 feishu_calendar_check.py --verbose
"""

import argparse
import datetime
import json
import sys
import urllib.request
import urllib.error

CONFIG_PATH = "/root/.openclaw/openclaw.json"
TARGET_KEYWORD = "kael regular"
TZ_OFFSET = datetime.timezone(datetime.timedelta(hours=8))  # Asia/Shanghai


def get_feishu_creds():
    with open(CONFIG_PATH) as f:
        cfg = json.load(f)
    acct = cfg["channels"]["feishu"]["accounts"]["main"]
    return acct["appId"], acct["appSecret"]


def get_tenant_token(app_id, app_secret):
    url = "https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal"
    data = json.dumps({"app_id": app_id, "app_secret": app_secret}).encode()
    req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req) as resp:
        result = json.loads(resp.read())
    if result.get("code") != 0:
        print(f"Error getting token: {result}", file=sys.stderr)
        return None
    return result["tenant_access_token"]


def get_primary_calendar_id(token):
    """Get the primary calendar ID for the bot."""
    url = "https://open.feishu.cn/open-apis/calendar/v4/calendars/primary"
    req = urllib.request.Request(url, headers={
        "Authorization": f"Bearer {token}",
    })
    try:
        with urllib.request.urlopen(req) as resp:
            result = json.loads(resp.read())
    except urllib.error.HTTPError as e:
        body = e.read().decode()
        print(f"Calendar primary error: HTTP {e.code}: {body}", file=sys.stderr)
        return None

    if result.get("code") != 0:
        print(f"Calendar API error: {result.get('msg')}", file=sys.stderr)
        return None

    return result.get("data", {}).get("calendars", [{}])[0].get("calendar", {}).get("calendar_id")


def list_calendar_events(token, calendar_id, verbose=False):
    """List events for today on the given calendar."""
    now = datetime.datetime.now(TZ_OFFSET)
    start_of_day = now.replace(hour=0, minute=0, second=0, microsecond=0)
    end_of_day = start_of_day + datetime.timedelta(days=1)

    start_ts = str(int(start_of_day.timestamp()))
    end_ts = str(int(end_of_day.timestamp()))

    import urllib.parse
    params = urllib.parse.urlencode({
        "start_time": start_ts,
        "end_time": end_ts,
        "page_size": 50,
    })
    url = f"https://open.feishu.cn/open-apis/calendar/v4/calendars/{calendar_id}/events?{params}"
    req = urllib.request.Request(url, headers={
        "Authorization": f"Bearer {token}",
    })
    try:
        with urllib.request.urlopen(req) as resp:
            result = json.loads(resp.read())
    except urllib.error.HTTPError as e:
        body = e.read().decode()
        print(f"Events list error: HTTP {e.code}: {body}", file=sys.stderr)
        return None

    if result.get("code") != 0:
        print(f"Events API error: {result.get('msg')}", file=sys.stderr)
        return None

    items = result.get("data", {}).get("items", [])
    if verbose:
        print(f"Found {len(items)} events today:")
        for item in items:
            print(f"  - {item.get('summary', '(no title)')}")
    return items


def check_for_kael_regular(events):
    """Check if any event matches 'kael regular' (case-insensitive)."""
    for event in events:
        summary = (event.get("summary") or "").lower()
        if TARGET_KEYWORD in summary:
            return True
    return False


def is_weekday():
    now = datetime.datetime.now(TZ_OFFSET)
    return now.weekday() < 5  # Mon=0, Fri=4


def main():
    parser = argparse.ArgumentParser(description="Check calendar for kael regular")
    parser.add_argument("--verbose", "-v", action="store_true")
    args = parser.parse_args()

    app_id, app_secret = get_feishu_creds()
    token = get_tenant_token(app_id, app_secret)

    if not token:
        if args.verbose:
            print("Token failed, falling back to weekday check")
        if is_weekday():
            print("PROCEED (weekday fallback)")
            sys.exit(0)
        else:
            print("SKIP (weekend, no calendar access)")
            sys.exit(1)

    cal_id = get_primary_calendar_id(token)
    if not cal_id:
        if args.verbose:
            print("No primary calendar, trying to list all calendars...")
        # Try listing all calendars
        url = "https://open.feishu.cn/open-apis/calendar/v4/calendars"
        req = urllib.request.Request(url, headers={"Authorization": f"Bearer {token}"})
        try:
            with urllib.request.urlopen(req) as resp:
                result = json.loads(resp.read())
            calendars = result.get("data", {}).get("calendar_list", [])
            if args.verbose:
                for c in calendars:
                    print(f"  Calendar: {c.get('summary', '?')} (id: {c.get('calendar_id', '?')})")
            # Search all calendars for kael regular
            for c in calendars:
                cid = c.get("calendar_id")
                if cid:
                    events = list_calendar_events(token, cid, verbose=args.verbose)
                    if events and check_for_kael_regular(events):
                        print("PROCEED (kael regular found)")
                        sys.exit(0)
        except Exception as e:
            if args.verbose:
                print(f"Calendar list failed: {e}")

        # Fallback
        if is_weekday():
            print("PROCEED (weekday fallback, no calendar match)")
            sys.exit(0)
        else:
            print("SKIP (weekend)")
            sys.exit(1)

    events = list_calendar_events(token, cal_id, verbose=args.verbose)
    if events is None:
        if is_weekday():
            print("PROCEED (weekday fallback)")
            sys.exit(0)
        else:
            print("SKIP (weekend)")
            sys.exit(1)

    if check_for_kael_regular(events):
        print("PROCEED (kael regular found)")
        sys.exit(0)
    else:
        if is_weekday():
            print("PROCEED (weekday, no kael regular)")
            sys.exit(0)
        else:
            print("SKIP (weekend, no kael regular)")
            sys.exit(1)


if __name__ == "__main__":
    main()
