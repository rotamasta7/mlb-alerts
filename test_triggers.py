"""Unit tests for the trigger logic. Run with: python -m unittest test_triggers"""

from __future__ import annotations

import unittest

from mlb import GameSnapshot
from triggers import should_alert


def make_game(
    game_pk: int = 1,
    state: str = "Live",
    detailed: str = "In Progress",
    inning: int | None = 7,
    inning_state: str | None = "End",
    home_id: int = 119,  # LAD
    away_id: int = 135,  # SD
    home_runs: int = 5,
    away_runs: int = 5,
) -> GameSnapshot:
    return GameSnapshot(
        game_pk=game_pk,
        state=state,
        detailed_state=detailed,
        inning=inning,
        inning_state=inning_state,
        home_id=home_id,
        away_id=away_id,
        home_name="Los Angeles Dodgers",
        away_name="San Diego Padres",
        home_runs=home_runs,
        away_runs=away_runs,
        game_date_utc="2026-04-23T02:10:00Z",
    )


class TestShouldAlert(unittest.TestCase):

    # --- positive cases ---

    def test_tie_game_end_of_seventh_alerts(self):
        g = make_game(inning=7, inning_state="End", home_runs=5, away_runs=5)
        self.assertTrue(should_alert(g).should_alert)

    def test_one_run_game_eighth_alerts(self):
        g = make_game(inning=8, inning_state="Top", home_runs=4, away_runs=5)
        self.assertTrue(should_alert(g).should_alert)

    def test_tie_game_bottom_ninth_alerts(self):
        g = make_game(inning=9, inning_state="Bottom", home_runs=3, away_runs=3)
        self.assertTrue(should_alert(g).should_alert)

    def test_extras_one_run_game_alerts(self):
        g = make_game(inning=11, inning_state="Top", home_runs=6, away_runs=7)
        self.assertTrue(should_alert(g).should_alert)

    # --- negative cases ---

    def test_blowout_does_not_alert(self):
        g = make_game(inning=8, inning_state="Bottom", home_runs=10, away_runs=2)
        result = should_alert(g)
        self.assertFalse(result.should_alert)
        self.assertIn("not close", result.reason)

    def test_middle_of_seventh_does_not_alert(self):
        # User wants alert at END of 7 or later, not during the 7th
        g = make_game(inning=7, inning_state="Middle", home_runs=5, away_runs=5)
        result = should_alert(g)
        self.assertFalse(result.should_alert)
        self.assertIn("too early", result.reason)

    def test_top_of_seventh_does_not_alert(self):
        g = make_game(inning=7, inning_state="Top", home_runs=5, away_runs=5)
        result = should_alert(g)
        self.assertFalse(result.should_alert)

    def test_bottom_of_seventh_does_not_alert(self):
        # Still in the 7th, not at the end yet
        g = make_game(inning=7, inning_state="Bottom", home_runs=5, away_runs=5)
        result = should_alert(g)
        self.assertFalse(result.should_alert)

    def test_sixth_inning_close_does_not_alert(self):
        g = make_game(inning=6, inning_state="End", home_runs=5, away_runs=5)
        result = should_alert(g)
        self.assertFalse(result.should_alert)

    def test_preview_game_does_not_alert(self):
        g = make_game(state="Preview", detailed="Scheduled")
        result = should_alert(g)
        self.assertFalse(result.should_alert)
        self.assertIn("not live", result.reason)

    def test_final_game_does_not_alert(self):
        g = make_game(state="Final", detailed="Final")
        result = should_alert(g)
        self.assertFalse(result.should_alert)

    def test_delayed_game_does_not_alert(self):
        g = make_game(state="Live", detailed="Delayed: Rain")
        result = should_alert(g)
        self.assertFalse(result.should_alert)
        self.assertIn("delayed", result.reason.lower())

    def test_two_run_game_does_not_alert(self):
        g = make_game(inning=8, inning_state="Top", home_runs=3, away_runs=5)
        result = should_alert(g)
        self.assertFalse(result.should_alert)

    # --- team filter ---

    def test_team_filter_matches(self):
        g = make_game(home_id=119, away_id=135)  # LAD vs SD
        self.assertTrue(should_alert(g, team_filter=frozenset({"LAD"})).should_alert)

    def test_team_filter_excludes(self):
        g = make_game(home_id=119, away_id=135)  # LAD vs SD
        result = should_alert(g, team_filter=frozenset({"NYY"}))
        self.assertFalse(result.should_alert)
        self.assertIn("teams not in filter", result.reason)

    # --- custom max_run_diff ---

    def test_max_run_diff_two(self):
        g = make_game(inning=8, inning_state="Top", home_runs=3, away_runs=5)
        self.assertTrue(should_alert(g, max_run_diff=2).should_alert)


if __name__ == "__main__":
    unittest.main()
