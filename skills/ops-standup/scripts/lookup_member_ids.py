#!/usr/bin/env python3
"""Look up Feishu open_ids for ops team members.

Uses the Feishu contact search API to find users by name,
then writes results to ops-standup-members.json.

Usage:
    python3 lookup_member_ids.py                    # Interactive: search all 4 members
    python3 lookup_member_ids.py --search "黄俊贤"  # Search a single name
    python3 lookup_member_ids.py --list-departments  # List department IDs (for scoping)
"""

import argparse
import json
import os
import sys
import urllib.request
import urllib.error

CONFIG_PATH = "/root/.openclaw/openclaw.json"
MEMBERS_PATH = "/root/.openclaw/workspace/memory/ops-standup-members.json"

# Default team members
DEFAULT_MEMBERS = ["黄俊贤", "吴玥", "岳子璇", "ST"]


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
        sys.exit(1)
    return result["tenant_access_token"]


def search_user(token, query):
    """Search for a user by name using the contact search API."""
    url = "https://open.feishu.cn/open-apis/search/v1/user"
    params = urllib.parse.urlencode({"query": query, "page_size": 5})
    full_url = f"{url}?{params}"
    req = urllib.request.Request(full_url, headers={
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    })
    try:
        with urllib.request.urlopen(req) as resp:
            result = json.loads(resp.read())
    except urllib.error.HTTPError as e:
        body = e.read().decode()
        print(f"HTTP {e.code} searching for '{query}': {body}", file=sys.stderr)
        return []

    if result.get("code") != 0:
        print(f"API error searching '{query}': {result.get('msg')}", file=sys.stderr)
        return []

    items = result.get("data", {}).get("items", [])
    return items


def list_departments(token):
    """List root departments to help with scoping."""
    url = "https://open.feishu.cn/open-apis/contact/v3/departments/0/children"
    req = urllib.request.Request(url, headers={
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    })
    try:
        with urllib.request.urlopen(req) as resp:
            result = json.loads(resp.read())
    except urllib.error.HTTPError as e:
        body = e.read().decode()
        print(f"HTTP {e.code}: {body}", file=sys.stderr)
        return
    print(json.dumps(result, indent=2, ensure_ascii=False))


def main():
    import urllib.parse

    parser = argparse.ArgumentParser(description="Look up Feishu open_ids for team members")
    parser.add_argument("--search", help="Search for a single name")
    parser.add_argument("--list-departments", action="store_true", help="List departments")
    parser.add_argument("--set", nargs=2, metavar=("NAME", "OPEN_ID"),
                        help="Manually set a member's open_id")
    args = parser.parse_args()

    app_id, app_secret = get_feishu_creds()

    # Manual set mode
    if args.set:
        name, open_id = args.set
        members = {}
        if os.path.exists(MEMBERS_PATH):
            with open(MEMBERS_PATH) as f:
                members = json.load(f)
        members[name] = {"open_id": open_id}
        os.makedirs(os.path.dirname(MEMBERS_PATH), exist_ok=True)
        with open(MEMBERS_PATH, "w") as f:
            json.dump(members, f, indent=2, ensure_ascii=False)
        print(f"Set {name} → {open_id}")
        return

    token = get_tenant_token(app_id, app_secret)

    if args.list_departments:
        list_departments(token)
        return

    if args.search:
        results = search_user(token, args.search)
        if not results:
            print(f"No results for '{args.search}'")
        for item in results:
            print(f"  Name: {item.get('name', '?')}")
            print(f"  open_id: {item.get('open_id', '?')}")
            print(f"  department: {item.get('department', {}).get('name', '?')}")
            print()
        return

    # Interactive: search all default members
    members = {}
    if os.path.exists(MEMBERS_PATH):
        with open(MEMBERS_PATH) as f:
            members = json.load(f)

    for name in DEFAULT_MEMBERS:
        if name in members and members[name].get("open_id"):
            print(f"[skip] {name} already has open_id: {members[name]['open_id']}")
            continue

        print(f"\nSearching for: {name}")
        results = search_user(token, name)

        if not results:
            print(f"  No results found. Use --set '{name}' <OPEN_ID> to set manually.")
            members[name] = {"open_id": ""}
            continue

        if len(results) == 1:
            open_id = results[0].get("open_id", "")
            print(f"  Found: {results[0].get('name', '?')} → {open_id}")
            members[name] = {"open_id": open_id}
        else:
            print(f"  Multiple results:")
            for i, item in enumerate(results):
                print(f"    [{i}] {item.get('name', '?')} (open_id: {item.get('open_id', '?')})")
            members[name] = {"open_id": "", "_candidates": [
                {"name": r.get("name"), "open_id": r.get("open_id")} for r in results
            ]}
            print(f"  Set manually: --set '{name}' <OPEN_ID>")

    os.makedirs(os.path.dirname(MEMBERS_PATH), exist_ok=True)
    with open(MEMBERS_PATH, "w") as f:
        json.dump(members, f, indent=2, ensure_ascii=False)

    print(f"\nSaved to {MEMBERS_PATH}")
    print(json.dumps(members, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
