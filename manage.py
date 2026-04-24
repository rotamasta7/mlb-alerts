"""Admin CLI for the multi-user MLB alert service.

Commands:
  python manage.py list                       # show current subscribers.yaml
  python manage.py add <name> [--teams NYY,BOS] [--max-diff 1]
  python manage.py remove <name>
  python manage.py gen-topic                  # print a fresh random ntfy topic
  python manage.py validate                   # validate subscribers.yaml
  python manage.py sync                       # push to GitHub secret (needs `gh` CLI)
                                              # or print JSON to paste manually

Typical flow when a mate wants in:
  1. They install ntfy app, subscribe to a topic they pick.
  2. They text you their topic name and which teams they care about.
  3. You run:  python manage.py add dave --topic dave-topic-abc --teams NYY,BOS
  4. You run:  python manage.py sync
  Done.
"""

from __future__ import annotations

import argparse
import json
import secrets
import shutil
import subprocess
import sys
from pathlib import Path

SUBS_FILE = Path("subscribers.yaml")
SECRET_NAME = "SUBSCRIBERS_JSON"


def _load_yaml() -> dict:
    try:
        import yaml
    except ImportError:
        print("PyYAML is required. Install with: pip install pyyaml", file=sys.stderr)
        sys.exit(2)
    if not SUBS_FILE.exists():
        print(f"{SUBS_FILE} not found. Copy subscribers.example.yaml to get started.", file=sys.stderr)
        sys.exit(2)
    data = yaml.safe_load(SUBS_FILE.read_text(encoding="utf-8")) or {}
    if isinstance(data, list):
        data = {"subscribers": data}
    data.setdefault("subscribers", [])
    return data


def _dump_yaml(data: dict) -> None:
    import yaml
    SUBS_FILE.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")


def cmd_list(_: argparse.Namespace) -> int:
    data = _load_yaml()
    subs = data["subscribers"]
    if not subs:
        print("No subscribers yet.")
        return 0
    print(f"{len(subs)} subscriber(s):\n")
    for s in subs:
        teams = ",".join(s.get("team_filter") or []) or "all"
        triggers = ",".join(s.get("triggers") or []) or "close_late"
        print(
            f"  - {s['name']:<12} topic={_mask(s['ntfy_topic'])}  "
            f"teams={teams}  max_diff={s.get('max_run_diff', 1)}  triggers={triggers}"
        )
    return 0


def cmd_add(args: argparse.Namespace) -> int:
    data = _load_yaml()
    existing = {s["name"] for s in data["subscribers"]}
    if args.name in existing:
        print(f"Subscriber '{args.name}' already exists. Use `remove` first or edit subscribers.yaml directly.", file=sys.stderr)
        return 1

    topic = args.topic or _gen_topic(args.name)
    entry = {
        "name": args.name,
        "ntfy_topic": topic,
        "team_filter": [t.strip().upper() for t in (args.teams or "").split(",") if t.strip()],
        "max_run_diff": args.max_diff,
    }
    data["subscribers"].append(entry)
    _dump_yaml(data)
    print(f"Added '{args.name}'. Topic: {topic}")
    print("Next: run `python manage.py sync` to push to GitHub.")
    return 0


def cmd_remove(args: argparse.Namespace) -> int:
    data = _load_yaml()
    before = len(data["subscribers"])
    data["subscribers"] = [s for s in data["subscribers"] if s["name"] != args.name]
    if len(data["subscribers"]) == before:
        print(f"No subscriber named '{args.name}'.", file=sys.stderr)
        return 1
    _dump_yaml(data)
    print(f"Removed '{args.name}'. Run `python manage.py sync` to push.")
    return 0


def cmd_gen_topic(args: argparse.Namespace) -> int:
    topic = _gen_topic(args.prefix or "mlb-alerts")
    print(topic)
    return 0


def cmd_validate(_: argparse.Namespace) -> int:
    # Reuse the real loader so validation stays consistent with the poller.
    import subscribers as subs_mod
    try:
        subs = subs_mod.load_from_file(SUBS_FILE)
    except Exception as e:  # noqa: BLE001
        print(f"INVALID: {e}", file=sys.stderr)
        return 1
    print(f"OK. {len(subs)} subscriber(s) validate cleanly.")
    for s in subs:
        print(
            f"  - {s.name}: topic={_mask(s.ntfy_topic)}, "
            f"filter={sorted(s.team_filter) or 'all'}, "
            f"max_diff={s.max_run_diff}, "
            f"triggers={sorted(s.triggers)}"
        )
    return 0


def cmd_sync(args: argparse.Namespace) -> int:
    import subscribers as subs_mod
    try:
        subs = subs_mod.load_from_file(SUBS_FILE)
    except Exception as e:  # noqa: BLE001
        print(f"Cannot sync, subscribers.yaml is invalid: {e}", file=sys.stderr)
        return 1

    payload = json.dumps([
        {
            "name": s.name,
            "ntfy_topic": s.ntfy_topic,
            "team_filter": sorted(s.team_filter),
            "max_run_diff": s.max_run_diff,
            "triggers": sorted(s.triggers),
        }
        for s in subs
    ])

    if args.print_only or not shutil.which("gh"):
        if not args.print_only:
            print("`gh` CLI not found. Printing JSON for manual paste into GitHub secret.")
            print(f"Install gh from https://cli.github.com to auto-sync next time.\n")
        print(f"Name the secret:  {SECRET_NAME}")
        print(f"Value:\n{payload}")
        return 0

    print(f"Pushing {len(subs)} subscribers to repo secret {SECRET_NAME} via gh...")
    try:
        result = subprocess.run(
            ["gh", "secret", "set", SECRET_NAME, "--body", payload],
            check=True,
            capture_output=True,
            text=True,
        )
        if result.stdout.strip():
            print(result.stdout.strip())
        print("Done. Next poll run will use the updated list.")
        return 0
    except subprocess.CalledProcessError as e:
        print(f"gh failed:\n{e.stderr}", file=sys.stderr)
        print("Try `gh auth login` first, or run with --print-only.", file=sys.stderr)
        return 1


def _gen_topic(prefix: str) -> str:
    suffix = secrets.token_urlsafe(16).lower().replace("_", "").replace("-", "")
    return f"{prefix}-{suffix}"


def _mask(topic: str) -> str:
    if len(topic) <= 8:
        return "***"
    return topic[:6] + "…" + topic[-4:]


def main() -> int:
    parser = argparse.ArgumentParser(description="Admin CLI for MLB alerts.")
    sp = parser.add_subparsers(dest="cmd", required=True)

    sp.add_parser("list", help="List current subscribers").set_defaults(func=cmd_list)

    add = sp.add_parser("add", help="Add a subscriber")
    add.add_argument("name")
    add.add_argument("--topic", help="ntfy topic (generated if omitted)")
    add.add_argument("--teams", default="", help="Comma-separated team abbrevs, e.g. NYY,BOS")
    add.add_argument("--max-diff", type=int, default=1, dest="max_diff")
    add.set_defaults(func=cmd_add)

    rm = sp.add_parser("remove", help="Remove a subscriber")
    rm.add_argument("name")
    rm.set_defaults(func=cmd_remove)

    gen = sp.add_parser("gen-topic", help="Print a new random ntfy topic")
    gen.add_argument("--prefix", default="mlb-alerts")
    gen.set_defaults(func=cmd_gen_topic)

    sp.add_parser("validate", help="Validate subscribers.yaml").set_defaults(func=cmd_validate)

    sync = sp.add_parser("sync", help="Push subscribers to GitHub secret")
    sync.add_argument("--print-only", action="store_true", help="Just print JSON, don't use gh")
    sync.set_defaults(func=cmd_sync)

    args = parser.parse_args()
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
