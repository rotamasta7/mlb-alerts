"""Send a simple test ping to one or all subscribers.

Usage:
  python send_test_alert.py               # all subscribers in subscribers.yaml
  python send_test_alert.py --only mitch  # just one
"""

from __future__ import annotations

import argparse
import logging
import os
import sys

from notify import send_plain
from subscribers import load_from_file


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--only", help="Only ping this subscriber name.")
    parser.add_argument(
        "--file",
        default=os.environ.get("SUBSCRIBERS_FILE", "subscribers.yaml"),
    )
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    log = logging.getLogger("test-alert")

    try:
        subs = load_from_file(args.file)
    except FileNotFoundError:
        log.error("Subscriber file '%s' not found.", args.file)
        return 2

    server = os.environ.get("NTFY_SERVER", "https://ntfy.sh").rstrip("/")
    count = 0
    for sub in subs:
        if args.only and sub.name != args.only:
            continue
        log.info("Pinging %s (%s)", sub.name, _mask(sub.ntfy_topic))
        ok = send_plain(
            server=server,
            topic=sub.ntfy_topic,
            title="MLB alerts: test ping",
            body=f"Hi {sub.name}! If you see this, your ntfy setup works.",
            priority="default",
            tags="baseball,white_check_mark",
        )
        if ok:
            count += 1

    log.info("Sent %d test alert(s).", count)
    return 0 if count > 0 else 1


def _mask(s: str) -> str:
    if len(s) <= 8:
        return "***"
    return s[:6] + "…" + s[-4:]


if __name__ == "__main__":
    sys.exit(main())
