"""MLB Stats API client. Thin wrapper around the public statsapi.mlb.com endpoints."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any
from zoneinfo import ZoneInfo

import requests

from teams import abbr

log = logging.getLogger(__name__)

BASE_URL = "https://statsapi.mlb.com/api/v1"
SCHEDULE_URL = f"{BASE_URL}/schedule"
USER_AGENT = "mlb-close-game-alerts/1.0 (personal-use)"
TIMEOUT = 15

# MLB schedules games in Eastern Time. A game from the previous ET day can still
# be live past midnight ET (extra innings, rain delay). We query a 2-day window
# in ET to avoid missing those.
MLB_TZ = ZoneInfo("America/New_York")


@dataclass(frozen=True)
class GameSnapshot:
    """A snapshot of a game's current state, pulled once per poll."""
    game_pk: int
    state: str               # abstractGameState: Preview / Live / Final
    detailed_state: str      # e.g. "In Progress", "Delayed", "Warmup"
    inning: int | None
    inning_state: str | None # Top / Middle / Bottom / End
    home_id: int
    away_id: int
    home_name: str
    away_name: str
    home_runs: int
    away_runs: int
    game_date_utc: str       # ISO UTC string
    # v3 additions — needed by walk_off, lead_change, bases_loaded_clutch
    is_top_inning: bool | None = None
    outs: int | None = None
    innings: list[dict[str, Any]] = field(default_factory=list)  # per-inning run arrays
    runners: dict[str, Any] = field(default_factory=dict)        # offense.first/second/third

    @property
    def home_abbr(self) -> str:
        return abbr(self.home_id)

    @property
    def away_abbr(self) -> str:
        return abbr(self.away_id)

    @property
    def run_diff(self) -> int:
        return abs(self.home_runs - self.away_runs)

    @property
    def is_live(self) -> bool:
        return self.state == "Live"

    def headline(self) -> str:
        """Compact score line, e.g. 'LAD 5 @ SD 5, End 7th'."""
        inning_label = _format_inning(self.inning, self.inning_state)
        return (
            f"{self.away_abbr} {self.away_runs} @ "
            f"{self.home_abbr} {self.home_runs}, {inning_label}"
        )

    def gameday_url(self) -> str:
        return f"https://www.mlb.com/gameday/{self.game_pk}"

    def inning_ordinal(self) -> str:
        return _ordinal(self.inning) if self.inning else "?"


def fetch_todays_games(now_utc: datetime | None = None) -> list[GameSnapshot]:
    """Return MLB games from yesterday ET through today ET.

    Covers games from the previous ET day that are still live after midnight ET
    (e.g. extra innings, rain delays). Deduped by gamePk.
    """
    now_utc = now_utc or datetime.now(timezone.utc)
    now_et = now_utc.astimezone(MLB_TZ)
    start_date = (now_et - timedelta(days=1)).strftime("%Y-%m-%d")
    end_date = now_et.strftime("%Y-%m-%d")
    params = {
        "sportId": 1,
        "startDate": start_date,
        "endDate": end_date,
        "hydrate": "linescore(matchup,runners)",
    }
    log.debug("GET schedule startDate=%s endDate=%s", start_date, end_date)
    resp = requests.get(
        SCHEDULE_URL,
        params=params,
        headers={"User-Agent": USER_AGENT, "Accept": "application/json"},
        timeout=TIMEOUT,
    )
    resp.raise_for_status()
    payload = resp.json()
    snapshots = _parse_schedule(payload)

    seen: set[int] = set()
    unique: list[GameSnapshot] = []
    for s in snapshots:
        if s.game_pk in seen:
            continue
        seen.add(s.game_pk)
        unique.append(s)
    return unique


def fetch_play_by_play(game_pk: int) -> dict[str, Any]:
    """Fetch the full play-by-play for one game. Returns dict with 'allPlays'."""
    url = f"{BASE_URL}/game/{game_pk}/playByPlay"
    resp = requests.get(
        url,
        headers={"User-Agent": USER_AGENT, "Accept": "application/json"},
        timeout=TIMEOUT,
    )
    resp.raise_for_status()
    return resp.json()


def fetch_boxscore(game_pk: int) -> dict[str, Any]:
    """Fetch the boxscore for one game. Returns dict with 'teams' containing per-pitcher stats."""
    url = f"{BASE_URL}/game/{game_pk}/boxscore"
    resp = requests.get(
        url,
        headers={"User-Agent": USER_AGENT, "Accept": "application/json"},
        timeout=TIMEOUT,
    )
    resp.raise_for_status()
    return resp.json()


def _parse_schedule(payload: dict[str, Any]) -> list[GameSnapshot]:
    snapshots: list[GameSnapshot] = []
    for date_block in payload.get("dates", []):
        for game in date_block.get("games", []):
            snap = _parse_game(game)
            if snap is not None:
                snapshots.append(snap)
    return snapshots


def _parse_game(game: dict[str, Any]) -> GameSnapshot | None:
    try:
        status = game.get("status", {})
        teams = game.get("teams", {})
        linescore = game.get("linescore") or {}
        ls_teams = linescore.get("teams") or {}

        home_team = teams.get("home", {}).get("team", {})
        away_team = teams.get("away", {}).get("team", {})

        return GameSnapshot(
            game_pk=int(game["gamePk"]),
            state=status.get("abstractGameState", "Unknown"),
            detailed_state=status.get("detailedState", "Unknown"),
            inning=linescore.get("currentInning"),
            inning_state=linescore.get("inningState"),
            home_id=int(home_team.get("id", 0)),
            away_id=int(away_team.get("id", 0)),
            home_name=home_team.get("name", "Home"),
            away_name=away_team.get("name", "Away"),
            home_runs=int((ls_teams.get("home") or {}).get("runs", 0) or 0),
            away_runs=int((ls_teams.get("away") or {}).get("runs", 0) or 0),
            game_date_utc=game.get("gameDate", ""),
            is_top_inning=linescore.get("isTopInning"),
            outs=linescore.get("outs"),
            innings=linescore.get("innings") or [],
            runners=linescore.get("offense") or {},
        )
    except (KeyError, ValueError, TypeError) as e:
        log.warning("Skipping malformed game: %s", e)
        return None


def _format_inning(inning: int | None, state: str | None) -> str:
    if not inning or not state:
        return "warmup"
    state_map = {"Top": "Top", "Middle": "Mid", "Bottom": "Bot", "End": "End"}
    prefix = state_map.get(state, state)
    return f"{prefix} {_ordinal(inning)}"


def _ordinal(n: int) -> str:
    if 10 <= n % 100 <= 20:
        suffix = "th"
    else:
        suffix = {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")
    return f"{n}{suffix}"
