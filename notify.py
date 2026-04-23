"""Send notifications via ntfy.sh."""

from __future__ import annotations

import logging

import requests

from mlb import GameSnapshot

log = logging.getLogger(__name__)

TIMEOUT = 10


def send_close_game_alert(
    server: str,
    topic: str,
    game: GameSnapshot,
    priority: str = "high",
    dry_run: bool = False,
) -> bool:
    """Push a close-late-game alert to ntfy. Returns True on success (or dry-run)."""
    url = f"{server}/{topic}"
    title = f"Close MLB game: {game.away_abbr} {game.away_runs} @ {game.home_abbr} {game.home_runs}"
    body = (
        f"{game.headline()}\n"
        f"{game.away_name} vs {game.home_name}\n"
        f"Run differential: {game.run_diff}\n"
        f"Tap to open Gameday."
    )

    headers = {
        "Title": title,
        "Priority": priority,
        "Tags": "baseball,fire",
        "Click": game.gameday_url(),
        "Actions": f"view, Open Gameday, {game.gameday_url()}, clear=true",
    }

    if dry_run:
        log.info("[DRY RUN] would POST to %s", url)
        log.info("[DRY RUN] title: %s", title)
        log.info("[DRY RUN] body: %s", body.replace("\n", " | "))
        return True

    try:
        resp = requests.post(
            url,
            data=body.encode("utf-8"),
            headers=headers,
            timeout=TIMEOUT,
        )
        resp.raise_for_status()
        log.info("Sent alert for game %s (%s)", game.game_pk, game.headline())
        return True
    except requests.RequestException as e:
        log.error("Failed to send ntfy alert for game %s: %s", game.game_pk, e)
        return False


def send_plain(
    server: str,
    topic: str,
    title: str,
    body: str,
    priority: str = "default",
    tags: str = "",
) -> bool:
    """Send an arbitrary notification. Used by the manual test script."""
    url = f"{server}/{topic}"
    headers = {"Title": title, "Priority": priority}
    if tags:
        headers["Tags"] = tags
    try:
        resp = requests.post(url, data=body.encode("utf-8"), headers=headers, timeout=TIMEOUT)
        resp.raise_for_status()
        return True
    except requests.RequestException as e:
        log.error("ntfy send failed: %s", e)
        return False
