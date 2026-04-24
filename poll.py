"""Multi-user MLB alert poller.

Flow per run:
  1. Load config (env).
  2. Load subscribers (SUBSCRIBERS_JSON secret or SUBSCRIBERS_FILE).
  3. Load per-user dedup state (key: "<game_pk>:<trigger>").
  4. Fetch today's games ONCE from MLB API.
  5. For games that are live, fetch play-by-play / boxscore lazily if any
     subscribed trigger needs them.
  6. For each (subscriber, game, trigger), decide whether to alert.
  7. If yes and not already alerted, push and record.
  8. Save state.
"""

from __future__ import annotations

import logging
import sys
from datetime import datetime, timezone

from config import Config
from mlb import GameSnapshot, fetch_boxscore, fetch_play_by_play, fetch_todays_games
from notify import send_alert
from state import load as load_state, save as save_state
from subscribers import Subscriber, load_from_env
from triggers import (
    NEEDS_BOXSCORE,
    NEEDS_PLAY_BY_PLAY,
    TriggerContext,
    run_trigger,
)


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
            "  subscriber: %s (topic=%s, filter=%s, max_diff=%d, triggers=%s)",
            sub.name,
            _mask(sub.ntfy_topic),
            sorted(sub.team_filter) or "all",
            sub.max_run_diff,
            sorted(sub.triggers),
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

    # Determine which extra datasets we need, across ALL subscribers
    union_triggers: frozenset[str] = frozenset().union(*(s.triggers for s in subs))
    needs_pbp = bool(union_triggers & NEEDS_PLAY_BY_PLAY)
    needs_box = bool(union_triggers & NEEDS_BOXSCORE)

    # Per-game fetch caches
    pbp_cache: dict[int, dict] = {}
    box_cache: dict[int, dict] = {}

    if needs_pbp or needs_box:
        for game in games:
            if not game.is_live:
                continue
            if needs_pbp:
                try:
                    pbp_cache[game.game_pk] = fetch_play_by_play(game.game_pk)
                except Exception as e:  # noqa: BLE001
                    log.warning("PBP fetch failed for %s: %s", game.game_pk, e)
            if needs_box:
                try:
                    box_cache[game.game_pk] = fetch_boxscore(game.game_pk)
                except Exception as e:  # noqa: BLE001
                    log.warning("Boxscore fetch failed for %s: %s", game.game_pk, e)

    total_sent = 0
    for sub in subs:
        sent = evaluate_subscriber(sub, games, state, cfg, pbp_cache, box_cache, log)
        total_sent += sent

    save_state(state, cfg.state_path)
    log.info("Done. %d total alerts sent across %d subscribers.", total_sent, len(subs))
    return 0


def evaluate_subscriber(
    sub: Subscriber,
    games: list[GameSnapshot],
    state,
    cfg: Config,
    pbp_cache: dict[int, dict],
    box_cache: dict[int, dict],
    log: logging.Logger,
) -> int:
    sent = 0
    for game in games:
        # Team filter short-circuit
        if sub.team_filter:
            involved = {game.home_abbr, game.away_abbr}
            if not involved.intersection(sub.team_filter):
                continue

        ctx = TriggerContext(
            max_run_diff=sub.max_run_diff,
            play_by_play=pbp_cache.get(game.game_pk),
            boxscore=box_cache.get(game.game_pk),
        )

        for trigger_name in sorted(sub.triggers):
            key = f"{game.game_pk}:{trigger_name}"
            if state.has_alerted(sub.name, key):
                continue

            decision = run_trigger(trigger_name, game, ctx)
            if not decision.should_alert:
                continue

            log.info(
                "  [%s] ALERT %s: %s (%s)",
                sub.name,
                trigger_name,
                game.headline(),
                decision.reason,
            )
            ok = send_alert(
                server=cfg.ntfy_server,
                topic=sub.ntfy_topic,
                title=decision.title,
                body=decision.body,
                priority=cfg.ntfy_priority,
                tags=decision.tags,
                click_url=game.gameday_url(),
                dry_run=cfg.dry_run,
            )
            if ok:
                state.mark_alerted(sub.name, key)
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
