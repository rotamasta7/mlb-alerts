"""Print today's MLB schedule and the trigger decision for each game.

Useful for a quick sanity check: 'is the API working, and would my filters fire?'

Usage:
  python check_today.py
"""

from __future__ import annotations

import logging
import sys

from mlb import fetch_todays_games
from triggers import should_alert


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    log = logging.getLogger("today")

    try:
        games = fetch_todays_games()
    except Exception as e:  # noqa: BLE001
        log.error("Failed to fetch schedule: %s", e)
        return 1

    if not games:
        log.info("No games scheduled today.")
        return 0

    log.info("Today's MLB schedule (%d games):", len(games))
    log.info("")
    for g in sorted(games, key=lambda x: x.game_date_utc):
        decision = should_alert(g)
        marker = "[ALERT]" if decision.should_alert else "       "
        log.info("%s %-10s %-40s diff=%-2d status=%s", marker, g.state, g.headline(), g.run_diff, g.detailed_state)

    alerts = sum(1 for g in games if should_alert(g).should_alert)
    log.info("")
    log.info("Would trigger %d alert(s) right now.", alerts)
    return 0


if __name__ == "__main__":
    sys.exit(main())
