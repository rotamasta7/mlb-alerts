"""Alert trigger logic. Pure functions only, so it's easy to unit-test.

Each trigger function signature:
    check_<name>(game: GameSnapshot, ctx: TriggerContext) -> TriggerDecision

Triggers that need data beyond the schedule linescore (play-by-play, boxscore)
declare that in NEEDS_PLAY_BY_PLAY / NEEDS_BOXSCORE so poll.py knows to fetch.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable

from mlb import GameSnapshot


@dataclass(frozen=True)
class TriggerContext:
    max_run_diff: int = 1
    play_by_play: dict[str, Any] | None = None
    boxscore: dict[str, Any] | None = None


@dataclass(frozen=True)
class TriggerDecision:
    should_alert: bool
    reason: str
    title: str = ""
    body: str = ""
    tags: str = "baseball"


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

def _live_check(game: GameSnapshot) -> TriggerDecision | None:
    """Return a negative TriggerDecision if the game isn't eligible; else None."""
    if not game.is_live:
        return TriggerDecision(False, f"not live (state={game.state})")
    if game.detailed_state and "delay" in game.detailed_state.lower():
        return TriggerDecision(False, f"delayed ({game.detailed_state})")
    return None


def _score_line(game: GameSnapshot) -> str:
    return f"{game.away_abbr} {game.away_runs} - {game.home_abbr} {game.home_runs}"


# ---------------------------------------------------------------------------
# Tier 1 — linescore only, no extra API calls
# ---------------------------------------------------------------------------

def check_close_late(game: GameSnapshot, ctx: TriggerContext) -> TriggerDecision:
    """Tied or within max_run_diff in the 7th inning (End) or later."""
    if (neg := _live_check(game)):
        return neg

    inning = game.inning or 0
    inning_state = (game.inning_state or "").lower()
    late_enough = (inning == 7 and inning_state == "end") or inning >= 8
    if not late_enough:
        return TriggerDecision(False, f"too early (inning={inning} {game.inning_state})")

    if game.run_diff > ctx.max_run_diff:
        return TriggerDecision(False, f"not close (diff={game.run_diff})")

    label = "tied" if game.run_diff == 0 else f"within {game.run_diff}"
    title = f"Close MLB game: {_score_line(game)}"
    body = (
        f"{game.headline()}\n"
        f"{game.away_name} vs {game.home_name}\n"
        f"{label.capitalize()} in the {game.inning_ordinal()}\n"
        f"Tap to open Gameday."
    )
    return TriggerDecision(
        True,
        f"close & late: diff={game.run_diff}, {game.inning_state} {inning}",
        title=title,
        body=body,
        tags="baseball,fire",
    )


def check_walk_off(game: GameSnapshot, ctx: TriggerContext) -> TriggerDecision:
    """Bottom 9th+, home team tied or trailing by 1."""
    if (neg := _live_check(game)):
        return neg

    inning = game.inning or 0
    if inning < 9:
        return TriggerDecision(False, f"too early (inning={inning})")

    inning_state = game.inning_state or ""
    # Home must be at the plate. "Bottom" is the only half where a walk-off can happen.
    if inning_state != "Bottom":
        return TriggerDecision(False, f"not home at-bat (state={inning_state})")

    deficit = game.away_runs - game.home_runs  # positive means home trailing
    if deficit not in (0, 1):
        return TriggerDecision(False, f"home not tied or trailing by 1 (diff={deficit})")

    situation = "tied" if deficit == 0 else "trailing by 1"
    title = "Walk-off watch"
    body = (
        f"{game.home_abbr} {situation} in the bottom {game.inning_ordinal()}.\n"
        f"{_score_line(game)}\n"
        f"Tap to open Gameday."
    )
    return TriggerDecision(
        True,
        f"walk-off setup: home {situation}, bot {inning}",
        title=title,
        body=body,
        tags="baseball,boom",
    )


def check_extra_innings(game: GameSnapshot, ctx: TriggerContext) -> TriggerDecision:
    """Live game has gone past the 9th inning."""
    if (neg := _live_check(game)):
        return neg

    inning = game.inning or 0
    if inning <= 9:
        return TriggerDecision(False, f"not extras (inning={inning})")

    title = "Extra innings!"
    body = (
        f"{game.away_name} vs {game.home_name} into the {game.inning_ordinal()}.\n"
        f"{_score_line(game)}\n"
        f"Tap to open Gameday."
    )
    return TriggerDecision(
        True,
        f"extras: inning={inning}",
        title=title,
        body=body,
        tags="baseball,hourglass",
    )


def check_lead_change(game: GameSnapshot, ctx: TriggerContext) -> TriggerDecision:
    """Team trailing after the 6th takes the lead in the 7th+.

    Stateless: derives post-6 leader from the innings array in the linescore.
    """
    if (neg := _live_check(game)):
        return neg

    inning = game.inning or 0
    if inning < 7:
        return TriggerDecision(False, f"too early (inning={inning})")

    if len(game.innings) < 6:
        return TriggerDecision(False, f"only {len(game.innings)} innings in linescore")

    away_6 = sum((inn.get("away") or {}).get("runs", 0) or 0 for inn in game.innings[:6])
    home_6 = sum((inn.get("home") or {}).get("runs", 0) or 0 for inn in game.innings[:6])

    if away_6 == home_6:
        return TriggerDecision(False, "tied after 6 (no leader to track)")

    leader_after_6 = "home" if home_6 > away_6 else "away"

    if game.home_runs == game.away_runs:
        return TriggerDecision(False, "currently tied (no definitive change)")

    current_leader = "home" if game.home_runs > game.away_runs else "away"
    if current_leader == leader_after_6:
        return TriggerDecision(False, f"{current_leader} still leads")

    new_leader = game.home_abbr if current_leader == "home" else game.away_abbr
    title = "Lead change!"
    body = (
        f"{new_leader} have taken the lead in the {game.inning_ordinal()}.\n"
        f"{_score_line(game)}\n"
        f"Tap to open Gameday."
    )
    return TriggerDecision(
        True,
        f"lead change: {leader_after_6}->{current_leader} by inning {inning}",
        title=title,
        body=body,
        tags="baseball,zap",
    )


def check_bases_loaded_clutch(game: GameSnapshot, ctx: TriggerContext) -> TriggerDecision:
    """Bases loaded, 2 outs, inning >= 7, within 2 runs."""
    if (neg := _live_check(game)):
        return neg

    inning = game.inning or 0
    if inning < 7:
        return TriggerDecision(False, f"too early (inning={inning})")

    if game.outs != 2:
        return TriggerDecision(False, f"not 2 outs (outs={game.outs})")

    runners = game.runners or {}
    if not (runners.get("first") and runners.get("second") and runners.get("third")):
        return TriggerDecision(False, "bases not loaded")

    if game.run_diff > 2:
        return TriggerDecision(False, f"not close enough (diff={game.run_diff})")

    title = "Bases loaded, 2 outs"
    body = (
        f"In the {game.inning_ordinal()}: bases loaded, 2 outs.\n"
        f"{_score_line(game)}\n"
        f"Tap to open Gameday."
    )
    return TriggerDecision(
        True,
        f"bases loaded 2 outs inning={inning}",
        title=title,
        body=body,
        tags="baseball,bomb",
    )


# ---------------------------------------------------------------------------
# Tier 2 — require extra API calls (play-by-play or boxscore)
# ---------------------------------------------------------------------------

def check_pitcher_flirting_history(game: GameSnapshot, ctx: TriggerContext) -> TriggerDecision:
    """Starting pitcher has 12+ Ks, or is pitching a CG shutout past the 7th."""
    if (neg := _live_check(game)):
        return neg

    inning = game.inning or 0
    if inning < 7:
        return TriggerDecision(False, f"too early (inning={inning})")

    if not ctx.boxscore:
        return TriggerDecision(False, "no boxscore available")

    for side in ("home", "away"):
        bs_team = (ctx.boxscore.get("teams") or {}).get(side) or {}
        pitchers = bs_team.get("pitchers") or []
        players = bs_team.get("players") or {}
        if not pitchers:
            continue

        sp_key = f"ID{pitchers[0]}"
        sp_data = players.get(sp_key) or {}
        sp_stats = (sp_data.get("stats") or {}).get("pitching") or {}
        if not sp_stats:
            continue

        sp_name = (sp_data.get("person") or {}).get("fullName", "SP")
        strikeouts = int(sp_stats.get("strikeOuts", 0) or 0)
        runs_allowed = int(sp_stats.get("runs", 0) or 0)
        try:
            ip = float(sp_stats.get("inningsPitched", "0.0") or 0.0)
        except (ValueError, TypeError):
            ip = 0.0

        if strikeouts >= 12:
            title = "Pitching gem"
            body = (
                f"{sp_name} has {strikeouts} Ks in the {game.inning_ordinal()}.\n"
                f"{_score_line(game)}\n"
                f"Tap to open Gameday."
            )
            return TriggerDecision(
                True,
                f"{side} SP {sp_name} {strikeouts} Ks",
                title=title,
                body=body,
                tags="baseball,fire",
            )

        if len(pitchers) == 1 and runs_allowed == 0 and ip >= 7:
            title = "Complete-game shutout watch"
            body = (
                f"{sp_name} through the {game.inning_ordinal()}, no runs.\n"
                f"{_score_line(game)}\n"
                f"Tap to open Gameday."
            )
            return TriggerDecision(
                True,
                f"{side} SP {sp_name} CG shutout through {ip} ip",
                title=title,
                body=body,
                tags="baseball,shield",
            )

    return TriggerDecision(False, "no starter meets criteria")


def check_grand_slam(game: GameSnapshot, ctx: TriggerContext) -> TriggerDecision:
    """Grand slam hit in the current or immediately previous inning."""
    if (neg := _live_check(game)):
        return neg

    if not ctx.play_by_play:
        return TriggerDecision(False, "no play-by-play available")

    current_inning = game.inning or 0
    target_innings = {current_inning, current_inning - 1}

    for play in reversed(ctx.play_by_play.get("allPlays") or []):
        about = play.get("about") or {}
        play_inning = about.get("inning", 0)
        if play_inning < min(target_innings) - 1:
            break
        if play_inning not in target_innings:
            continue

        result = play.get("result") or {}
        if result.get("eventType") == "home_run" and int(result.get("rbi", 0) or 0) == 4:
            batter = ((play.get("matchup") or {}).get("batter") or {}).get("fullName", "Unknown")
            half = "top" if about.get("isTopInning", True) else "bottom"
            title = "GRAND SLAM"
            body = (
                f"{batter} with the bases loaded in the {half} "
                f"{_inning_ordinal(play_inning)}.\n"
                f"{_score_line(game)}\n"
                f"Tap to open Gameday."
            )
            return TriggerDecision(
                True,
                f"grand slam by {batter} in {half} {play_inning}",
                title=title,
                body=body,
                tags="baseball,boom,fire",
            )

    return TriggerDecision(False, "no recent grand slam")


def _inning_ordinal(n: int) -> str:
    if 10 <= n % 100 <= 20:
        suffix = "th"
    else:
        suffix = {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")
    return f"{n}{suffix}"


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------

TriggerFn = Callable[[GameSnapshot, TriggerContext], TriggerDecision]

REGISTRY: dict[str, TriggerFn] = {
    "close_late": check_close_late,
    "walk_off": check_walk_off,
    "extra_innings": check_extra_innings,
    "lead_change": check_lead_change,
    "bases_loaded_clutch": check_bases_loaded_clutch,
    "pitcher_flirting_history": check_pitcher_flirting_history,
    "grand_slam": check_grand_slam,
}

VALID_TRIGGERS: frozenset[str] = frozenset(REGISTRY.keys())

NEEDS_PLAY_BY_PLAY: frozenset[str] = frozenset({"grand_slam"})
NEEDS_BOXSCORE: frozenset[str] = frozenset({"pitcher_flirting_history"})


def run_trigger(name: str, game: GameSnapshot, ctx: TriggerContext) -> TriggerDecision:
    """Dispatch a named trigger. Unknown names return a non-firing decision."""
    fn = REGISTRY.get(name)
    if fn is None:
        return TriggerDecision(False, f"unknown trigger '{name}'")
    return fn(game, ctx)


# ---------------------------------------------------------------------------
# Backward-compat shim — old call signature used a frozenset team_filter and
# returned a 2-field TriggerDecision. Kept so check_today.py and any remaining
# callers keep working without a rewrite.
# ---------------------------------------------------------------------------

def should_alert(
    game: GameSnapshot,
    max_run_diff: int = 1,
    team_filter: frozenset[str] | None = None,
) -> TriggerDecision:
    """Legacy single-trigger (close_late) check with optional team filter."""
    if team_filter:
        involved = {game.home_abbr, game.away_abbr}
        if not involved.intersection(team_filter):
            return TriggerDecision(False, f"teams not in filter ({involved} vs {team_filter})")
    return check_close_late(game, TriggerContext(max_run_diff=max_run_diff))
