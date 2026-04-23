"""Multi-user MLB close-game alert poller.

Flow per run:
  1. Load config (env).
  2. Load subscribers (SUBSCRIBERS_JSON secret or SUBSCRIBERS_FILE).
  3. Load per-user dedup state.
  4. Fetch today's games ONCE from MLB API.
  5. For each (subscriber, game), decide whether to alert.
  6. If yes and not already alerted, push to their topic and record.
  7. Save state.
"""

from __future__ import annotations

import logging
import sys
from datetime import datetime, timezone

from config import Config
from mlb import GameSnapshot, fetch_todays_games
from notify import send_close_game_alert
from state import load as load_state, save as save_state
from subscribers import Subscriber, load_from_env
from triggers import should_alert


def configure_logging() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        datefmt="%Y-%m-%dT%H:%M:%S%z",
    )


def run() -> int:
    configure_logging()
    log = logging.getLogger("poll")

    cfg = Config.from_env()

    try:
        subs = load_from_env()
    except (RuntimeError, ValueError, FileNotFoundError) as e:
        log.error("Subscriber config error: %s", e)
        return 2

    if not subs:
        log.warning("No subscribers configured. Nothing to do.")
        return 0

    log.info(
        "Starting poll (server=%s, priority=%s, dry_run=%s, subscribers=%d)",
        cfg.ntfy_server,
        cfg.ntfy_priority,
        cfg.dry_run,
        len(subs),
    )
    for sub in subs:
        log.info(
            "  subscriber: %s (topic=%s, filter=%s, max_diff=%d)",
            sub.name,
            _mask(sub.ntfy_topic),
            sorted(sub.team_filter) or "all",
            sub.max_run_diff,
        )

    today_utc = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    state = load_state(cfg.state_path)
    state.reset_if_new_day(today_utc)
    state.prune_unknown({s.name for s in subs})

    try:
        games = fetch_todays_games()
    except Exception as e:  # noqa: BLE001
        log.error("Failed to fetch MLB schedule: %s", e)
        return 1

    log.info("Fetched %d games for %s", len(games), today_utc)
    for game in games:
        _log_game(log, game)

    total_sent = 0
    for sub in subs:
        sent = evaluate_subscriber(sub, games, state, cfg, log)
        total_sent += sent

    save_state(state, cfg.state_path)
    log.info("Done. %d total alerts sent across %d subscribers.", total_sent, len(subs))
    return 0


def evaluate_subscriber(
    sub: Subscriber,
    games: list[GameSnapshot],
    state,
    cfg: Config,
    log: logging.Logger,
) -> int:
    sent = 0
    for game in games:
        decision = should_alert(
            game,
            max_run_diff=sub.max_run_diff,
            team_filter=sub.team_filter or None,
        )
        if not decision.should_alert:
            continue
        if state.has_alerted(sub.name, game.game_pk):
            log.info("  [%s] skip: already alerted for game %s", sub.name, game.game_pk)
            continue
        log.info("  [%s] ALERT: %s (%s)", sub.name, game.headline(), decision.reason)
        ok = send_close_game_alert(
            server=cfg.ntfy_server,
            topic=sub.ntfy_topic,
            game=game,
            priority=cfg.ntfy_priority,
            dry_run=cfg.dry_run,
        )
        if ok:
            state.mark_alerted(sub.name, game.game_pk)
            sent += 1
    return sent


def _log_game(log: logging.Logger, game: GameSnapshot) -> None:
    marker = "LIVE" if game.is_live else game.state.upper()
    log.info(
        "  [%s] %s — diff %d, status=%s",
        marker,
        game.headline(),
        game.run_diff,
        game.detailed_state,
    )


def _mask(topic: str) -> str:
    if len(topic) <= 8:
        return "***"
    return topic[:4] + "…" + topic[-4:]


if __name__ == "__main__":
    sys.exit(run())
