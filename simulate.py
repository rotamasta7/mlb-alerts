"""End-to-end simulator with a fake game per trigger.

Usage:
  python simulate.py                                 # dry-run close_late
  python simulate.py --trigger walk_off              # dry-run any trigger
  python simulate.py --trigger all                   # dry-run every trigger
  python simulate.py --send                          # actually push close_late
  python simulate.py --trigger all --send            # push every trigger
  python simulate.py --send --only Mitch             # only to one subscriber
"""

from __future__ import annotations

import argparse
import logging
import os
import sys

from mlb import GameSnapshot
from notify import send_alert
from subscribers import load_from_file
from triggers import TriggerContext, run_trigger


# ---------------------------------------------------------------------------
# Fake game factories per trigger
# ---------------------------------------------------------------------------

RUNNERS = {"first": {"id": 1}, "second": {"id": 2}, "third": {"id": 3}}


def _base_snapshot(
    *,
    inning: int,
    inning_state: str,
    home_runs: int,
    away_runs: int,
    is_top_inning: bool | None = None,
    outs: int | None = None,
    innings: list[dict] | None = None,
    runners: dict | None = None,
) -> GameSnapshot:
    return GameSnapshot(
        game_pk=99999999,
        state="Live",
        detailed_state="In Progress",
        inning=inning,
        inning_state=inning_state,
        home_id=135,   # SD
        away_id=119,   # LAD
        home_name="San Diego Padres",
        away_name="Los Angeles Dodgers",
        home_runs=home_runs,
        away_runs=away_runs,
        game_date_utc="2026-04-23T02:10:00Z",
        is_top_inning=is_top_inning,
        outs=outs,
        innings=innings or [],
        runners=runners or {},
    )


def _innings(away: list[int], home: list[int]) -> list[dict]:
    return [
        {"num": i + 1, "away": {"runs": away[i]}, "home": {"runs": home[i]}}
        for i in range(len(away))
    ]


def fake_game(trigger_name: str) -> tuple[GameSnapshot, TriggerContext]:
    if trigger_name == "close_late":
        return _base_snapshot(inning=8, inning_state="Middle", home_runs=3, away_runs=3), \
               TriggerContext(max_run_diff=1)

    if trigger_name == "walk_off":
        return _base_snapshot(
            inning=9, inning_state="Bottom", is_top_inning=False,
            home_runs=3, away_runs=4,
        ), TriggerContext()

    if trigger_name == "extra_innings":
        return _base_snapshot(inning=10, inning_state="Top", home_runs=3, away_runs=3), \
               TriggerContext()

    if trigger_name == "lead_change":
        # home led 5-3 after 6; now away leads 7-5
        innings = _innings([1, 0, 2, 0, 0, 0], [2, 1, 1, 0, 1, 0])
        return _base_snapshot(
            inning=7, inning_state="End",
            home_runs=5, away_runs=7, innings=innings,
        ), TriggerContext()

    if trigger_name == "bases_loaded_clutch":
        return _base_snapshot(
            inning=8, inning_state="Middle",
            home_runs=3, away_runs=3, outs=2, runners=RUNNERS,
        ), TriggerContext()

    if trigger_name == "pitcher_flirting_history":
        game = _base_snapshot(inning=8, inning_state="Middle", home_runs=3, away_runs=0)
        boxscore = {
            "teams": {
                "home": {
                    "pitchers": [600001],
                    "players": {
                        "ID600001": {
                            "person": {"id": 600001, "fullName": "Sim Pitcher"},
                            "stats": {"pitching": {
                                "strikeOuts": 13, "runs": 0, "inningsPitched": "8.0",
                            }},
                        },
                    },
                },
                "away": {"pitchers": [], "players": {}},
            },
        }
        return game, TriggerContext(boxscore=boxscore)

    if trigger_name == "grand_slam":
        game = _base_snapshot(inning=8, inning_state="Middle", home_runs=3, away_runs=7)
        pbp = {
            "allPlays": [
                {
                    "about": {"inning": 8, "isTopInning": True},
                    "result": {"eventType": "home_run", "rbi": 4},
                    "matchup": {"batter": {"fullName": "Sim Slugger"}},
                },
            ],
        }
        return game, TriggerContext(play_by_play=pbp)

    raise ValueError(f"No fake game defined for trigger '{trigger_name}'")


TRIGGER_NAMES = [
    "close_late", "walk_off", "extra_innings", "lead_change",
    "bases_loaded_clutch", "pitcher_flirting_history", "grand_slam",
]


def simulate_one(
    trigger_name: str,
    subs,
    server: str,
    send: bool,
    only: str | None,
    log: logging.Logger,
) -> int:
    game, ctx = fake_game(trigger_name)
    decision = run_trigger(trigger_name, game, ctx)
    if not decision.should_alert:
        log.warning("[%s] fake game did NOT fire (%s)", trigger_name, decision.reason)
        return 0

    log.info("[%s] would alert: %s", trigger_name, decision.title)
    log.info("[%s]   body: %s", trigger_name, decision.body.replace("\n", " | "))

    sent = 0
    for sub in subs:
        if only and sub.name != only:
            continue
        if trigger_name not in sub.triggers:
            log.info("[%s]   skip %s (trigger not subscribed)", trigger_name, sub.name)
            continue
        if sub.team_filter and not {game.home_abbr, game.away_abbr} & sub.team_filter:
            log.info("[%s]   skip %s (team filter)", trigger_name, sub.name)
            continue
        ok = send_alert(
            server=server,
            topic=sub.ntfy_topic,
            title=decision.title,
            body=decision.body,
            priority="high",
            tags=decision.tags,
            click_url=game.gameday_url(),
            dry_run=not send,
        )
        if ok:
            sent += 1
            log.info("[%s]   %s %s", trigger_name, "SENT" if send else "DRY", sub.name)
    return sent


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--trigger",
        default="close_late",
        choices=TRIGGER_NAMES + ["all"],
        help="Trigger to simulate (default: close_late). Use 'all' for every trigger.",
    )
    parser.add_argument("--send", action="store_true", help="Really POST to ntfy.")
    parser.add_argument("--only", help="Only target this subscriber name.")
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

    server = os.environ.get("NTFY_SERVER", "https://ntfy.sh").rstrip("/")

    triggers = TRIGGER_NAMES if args.trigger == "all" else [args.trigger]
    total = 0
    for t in triggers:
        total += simulate_one(t, subs, server, args.send, args.only, log)

    verb = "sent" if args.send else "would-be"
    log.info("Total %s across %d trigger(s): %d", verb, len(triggers), total)
    return 0


if __name__ == "__main__":
    sys.exit(main())
