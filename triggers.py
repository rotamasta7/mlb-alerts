"""Alert trigger logic. Pure functions only, so it's easy to unit-test."""

from __future__ import annotations

from dataclasses import dataclass

from mlb import GameSnapshot


@dataclass(frozen=True)
class TriggerDecision:
    should_alert: bool
    reason: str


def should_alert(
    game: GameSnapshot,
    max_run_diff: int = 1,
    team_filter: frozenset[str] | None = None,
) -> TriggerDecision:
    """Decide whether this game snapshot warrants a close-late-game alert.

    Fires when:
      - Game is Live (not Preview, not Final, not Delayed/Postponed)
      - It's the END of the 7th inning, or the 8th inning or later
      - Score differential is `max_run_diff` or less (default 1, so 0 or 1 run apart)
      - If team_filter is set, one of the teams is in it
    """
    if not game.is_live:
        return TriggerDecision(False, f"not live (state={game.state})")

    if game.detailed_state and "delay" in game.detailed_state.lower():
        return TriggerDecision(False, f"delayed ({game.detailed_state})")

    inning = game.inning or 0
    inning_state = (game.inning_state or "").lower()

    late_enough = (inning == 7 and inning_state == "end") or inning >= 8
    if not late_enough:
        return TriggerDecision(
            False,
            f"too early (inning={inning} {game.inning_state})",
        )

    if game.run_diff > max_run_diff:
        return TriggerDecision(
            False,
            f"not close (diff={game.run_diff})",
        )

    if team_filter:
        involved = {game.home_abbr, game.away_abbr}
        if not involved.intersection(team_filter):
            return TriggerDecision(
                False,
                f"teams not in filter ({involved} vs {team_filter})",
            )

    return TriggerDecision(
        True,
        f"close & late: diff={game.run_diff}, {_inning_label(inning, game.inning_state)}",
    )


def _inning_label(inning: int, state: str | None) -> str:
    return f"{state or '?'} {inning}"
