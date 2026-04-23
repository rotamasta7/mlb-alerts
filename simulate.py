"""End-to-end simulator with a fake close game.

In dry-run mode, prints what would be sent to each subscriber.
With --send, actually pushes to every subscriber in subscribers.yaml.

Usage:
  python simulate.py                      # dry-run
  python simulate.py --send               # real push to every subscriber
  python simulate.py --send --only mitch  # real push to one subscriber
"""

from __future__ import annotations

import argparse
import logging
import os
import sys

from mlb import GameSnapshot
from notify import send_close_game_alert
from subscribers import load_from_file
from triggers import should_alert


def fake_close_game() -> GameSnapshot:
    return GameSnapshot(
        game_pk=99999999,
        state="Live",
        detailed_state="In Progress",
        inning=7,
        inning_state="End",
        home_id=135,
        away_id=119,
        home_name="San Diego Padres",
        away_name="Los Angeles Dodgers",
        home_runs=5,
        away_runs=5,
        game_date_utc="2026-04-23T02:10:00Z",
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--send", action="store_true", help="Really send notifications.")
    parser.add_argument("--only", help="Only send to this subscriber name.")
    parser.add_argument(
        "--file",
        default=os.environ.get("SUBSCRIBERS_FILE", "subscribers.yaml"),
        help="Subscriber file (default: subscribers.yaml)",
    )
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    log = logging.getLogger("simulate")

    try:
        subs = load_from_file(args.file)
    except FileNotFoundError:
        log.error("Subscriber file '%s' not found.", args.file)
        return 2
    except Exception as e:  # noqa: BLE001
        log.error("Could not load subscribers: %s", e)
        return 2

    game = fake_close_game()
    log.info("Fake game: %s", game.headline())

    server = os.environ.get("NTFY_SERVER", "https://ntfy.sh").rstrip("/")
    total = 0
    for sub in subs:
        if args.only and sub.name != args.only:
            continue
        decision = should_alert(game, max_run_diff=sub.max_run_diff, team_filter=sub.team_filter or None)
        if not decision.should_alert:
            log.info("[%s] would NOT alert (%s)", sub.name, decision.reason)
            continue
        log.info("[%s] would ALERT via topic %s", sub.name, _mask(sub.ntfy_topic))
        ok = send_close_game_alert(
            server=server,
            topic=sub.ntfy_topic,
            game=game,
            priority="high",
            dry_run=not args.send,
        )
        if ok:
            total += 1

    verb = "sent" if args.send else "would-be"
    log.info("Total %s: %d", verb, total)
    return 0


def _mask(s: str) -> str:
    if len(s) <= 8:
        return "***"
    return s[:6] + "…" + s[-4:]


if __name__ == "__main__":
    sys.exit(main())
