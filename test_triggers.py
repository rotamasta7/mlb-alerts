"""Unit tests for trigger logic — v3, all 7 triggers. Pure, no network."""

from __future__ import annotations

import unittest

from mlb import GameSnapshot
from triggers import (
    NEEDS_BOXSCORE,
    NEEDS_PLAY_BY_PLAY,
    REGISTRY,
    VALID_TRIGGERS,
    TriggerContext,
    check_bases_loaded_clutch,
    check_close_late,
    check_extra_innings,
    check_grand_slam,
    check_lead_change,
    check_pitcher_flirting_history,
    check_walk_off,
    run_trigger,
    should_alert,
)


RUNNERS = {"first": {"id": 1}, "second": {"id": 2}, "third": {"id": 3}}


def make_game(
    *,
    game_pk: int = 1,
    state: str = "Live",
    detailed: str = "In Progress",
    inning: int | None = 7,
    inning_state: str | None = "End",
    home_id: int = 111,       # BOS
    away_id: int = 147,       # NYY
    home_runs: int = 3,
    away_runs: int = 3,
    is_top_inning: bool | None = None,
    outs: int | None = None,
    innings: list[dict] | None = None,
    runners: dict | None = None,
) -> GameSnapshot:
    return GameSnapshot(
        game_pk=game_pk,
        state=state,
        detailed_state=detailed,
        inning=inning,
        inning_state=inning_state,
        home_id=home_id,
        away_id=away_id,
        home_name="Home Team",
        away_name="Away Team",
        home_runs=home_runs,
        away_runs=away_runs,
        game_date_utc="2026-04-23T02:10:00Z",
        is_top_inning=is_top_inning,
        outs=outs,
        innings=innings or [],
        runners=runners or {},
    )


def make_innings(away: list[int], home: list[int]) -> list[dict]:
    assert len(away) == len(home)
    return [
        {"num": i + 1, "away": {"runs": away[i]}, "home": {"runs": home[i]}}
        for i in range(len(away))
    ]


CTX = TriggerContext(max_run_diff=1)


# ---------------------------------------------------------------------------
# close_late
# ---------------------------------------------------------------------------

class TestCloseLate(unittest.TestCase):
    def test_fires_8th_tied(self):
        d = check_close_late(make_game(inning=8, inning_state="Middle"), CTX)
        self.assertTrue(d.should_alert)
        self.assertIn("Close", d.title)

    def test_fires_7th_end(self):
        d = check_close_late(make_game(inning=7, inning_state="End", away_runs=2, home_runs=3), CTX)
        self.assertTrue(d.should_alert)

    def test_fires_9th_within_1(self):
        d = check_close_late(make_game(inning=9, inning_state="Top", away_runs=4, home_runs=3), CTX)
        self.assertTrue(d.should_alert)

    def test_no_fire_7th_not_end(self):
        d = check_close_late(make_game(inning=7, inning_state="Top"), CTX)
        self.assertFalse(d.should_alert)
        self.assertIn("too early", d.reason)

    def test_no_fire_6th(self):
        d = check_close_late(make_game(inning=6, inning_state="End"), CTX)
        self.assertFalse(d.should_alert)

    def test_no_fire_blowout(self):
        d = check_close_late(make_game(inning=8, away_runs=8, home_runs=1), CTX)
        self.assertFalse(d.should_alert)

    def test_no_fire_not_live(self):
        d = check_close_late(make_game(state="Final", inning=8), CTX)
        self.assertFalse(d.should_alert)

    def test_no_fire_delayed(self):
        d = check_close_late(make_game(detailed="Rain Delay", inning=8), CTX)
        self.assertFalse(d.should_alert)

    def test_max_run_diff_2(self):
        ctx = TriggerContext(max_run_diff=2)
        d = check_close_late(make_game(inning=8, away_runs=5, home_runs=3), ctx)
        self.assertTrue(d.should_alert)

    def test_max_run_diff_2_just_over(self):
        ctx = TriggerContext(max_run_diff=2)
        d = check_close_late(make_game(inning=8, away_runs=6, home_runs=3), ctx)
        self.assertFalse(d.should_alert)


# ---------------------------------------------------------------------------
# walk_off
# ---------------------------------------------------------------------------

class TestWalkOff(unittest.TestCase):
    def test_fires_bottom_9th_trailing_1(self):
        d = check_walk_off(make_game(
            inning=9, inning_state="Bottom", is_top_inning=False,
            away_runs=4, home_runs=3,
        ), CTX)
        self.assertTrue(d.should_alert)
        self.assertIn("trailing", d.body)

    def test_fires_bottom_9th_tied(self):
        d = check_walk_off(make_game(
            inning=9, inning_state="Bottom", is_top_inning=False,
            away_runs=3, home_runs=3,
        ), CTX)
        self.assertTrue(d.should_alert)
        self.assertIn("tied", d.body)

    def test_fires_bottom_10th(self):
        d = check_walk_off(make_game(
            inning=10, inning_state="Bottom", is_top_inning=False,
            away_runs=3, home_runs=3,
        ), CTX)
        self.assertTrue(d.should_alert)

    def test_no_fire_end_9th(self):
        # End of 9th means the half-inning is over; no walk-off opportunity remaining
        d = check_walk_off(make_game(
            inning=9, inning_state="End", is_top_inning=False,
            away_runs=3, home_runs=3,
        ), CTX)
        self.assertFalse(d.should_alert)

    def test_no_fire_top_9th(self):
        d = check_walk_off(make_game(
            inning=9, inning_state="Top", is_top_inning=True,
            away_runs=4, home_runs=3,
        ), CTX)
        self.assertFalse(d.should_alert)

    def test_no_fire_8th(self):
        d = check_walk_off(make_game(
            inning=8, inning_state="Bottom", is_top_inning=False,
            away_runs=4, home_runs=3,
        ), CTX)
        self.assertFalse(d.should_alert)

    def test_no_fire_home_trailing_2(self):
        d = check_walk_off(make_game(
            inning=9, inning_state="Bottom", is_top_inning=False,
            away_runs=5, home_runs=3,
        ), CTX)
        self.assertFalse(d.should_alert)

    def test_no_fire_home_leading(self):
        d = check_walk_off(make_game(
            inning=9, inning_state="Bottom", is_top_inning=False,
            away_runs=3, home_runs=5,
        ), CTX)
        self.assertFalse(d.should_alert)

    def test_no_fire_not_live(self):
        d = check_walk_off(make_game(
            state="Final", inning=9, inning_state="Bottom", is_top_inning=False,
        ), CTX)
        self.assertFalse(d.should_alert)


# ---------------------------------------------------------------------------
# extra_innings
# ---------------------------------------------------------------------------

class TestExtraInnings(unittest.TestCase):
    def test_fires_10th(self):
        d = check_extra_innings(make_game(inning=10, inning_state="Top"), CTX)
        self.assertTrue(d.should_alert)
        self.assertIn("Extra", d.title)

    def test_fires_12th(self):
        d = check_extra_innings(make_game(inning=12), CTX)
        self.assertTrue(d.should_alert)

    def test_no_fire_9th(self):
        d = check_extra_innings(make_game(inning=9), CTX)
        self.assertFalse(d.should_alert)

    def test_no_fire_8th(self):
        d = check_extra_innings(make_game(inning=8), CTX)
        self.assertFalse(d.should_alert)

    def test_no_fire_not_live(self):
        d = check_extra_innings(make_game(state="Final", inning=10), CTX)
        self.assertFalse(d.should_alert)

    def test_no_fire_delayed(self):
        d = check_extra_innings(make_game(detailed="Rain Delay", inning=10), CTX)
        self.assertFalse(d.should_alert)


# ---------------------------------------------------------------------------
# lead_change
# ---------------------------------------------------------------------------

class TestLeadChange(unittest.TestCase):
    def test_fires_away_takes_lead_7th(self):
        innings = make_innings([1, 0, 2, 0, 0, 0], [2, 1, 1, 0, 1, 0])
        # away_6=3, home_6=5 -> home led; now away=7, home=5
        d = check_lead_change(make_game(
            inning=7, inning_state="End",
            away_runs=7, home_runs=5, innings=innings,
        ), CTX)
        self.assertTrue(d.should_alert)
        self.assertIn("NYY", d.body)

    def test_fires_home_takes_lead_8th(self):
        innings = make_innings([2, 0, 1, 0, 1, 0], [0, 1, 0, 0, 0, 1])
        # away_6=4, home_6=2 -> away led; now home=6, away=4
        d = check_lead_change(make_game(
            inning=8, inning_state="Top",
            away_runs=4, home_runs=6, innings=innings,
        ), CTX)
        self.assertTrue(d.should_alert)
        self.assertIn("BOS", d.body)

    def test_no_fire_same_leader(self):
        innings = make_innings([1, 0, 0, 0, 0, 0], [2, 1, 0, 0, 0, 0])
        d = check_lead_change(make_game(
            inning=8, away_runs=3, home_runs=5, innings=innings,
        ), CTX)
        self.assertFalse(d.should_alert)

    def test_no_fire_6th(self):
        innings = make_innings([1, 0, 0, 0, 0], [2, 1, 0, 0, 0])
        d = check_lead_change(make_game(inning=6, innings=innings), CTX)
        self.assertFalse(d.should_alert)

    def test_no_fire_tied_after_6(self):
        innings = make_innings([1, 1, 1, 0, 0, 0], [1, 1, 0, 0, 0, 1])
        d = check_lead_change(make_game(
            inning=8, away_runs=5, home_runs=3, innings=innings,
        ), CTX)
        self.assertFalse(d.should_alert)

    def test_no_fire_currently_tied(self):
        innings = make_innings([2, 0, 0, 0, 0, 0], [0, 0, 0, 0, 0, 0])
        d = check_lead_change(make_game(
            inning=8, away_runs=2, home_runs=2, innings=innings,
        ), CTX)
        self.assertFalse(d.should_alert)

    def test_no_fire_not_enough_innings(self):
        innings = make_innings([1, 0, 0, 0], [2, 1, 0, 0])
        d = check_lead_change(make_game(inning=7, innings=innings), CTX)
        self.assertFalse(d.should_alert)

    def test_no_fire_not_live(self):
        innings = make_innings([1, 0, 0, 0, 0, 0], [2, 1, 0, 0, 0, 0])
        d = check_lead_change(make_game(
            state="Final", inning=8, away_runs=5, home_runs=3, innings=innings,
        ), CTX)
        self.assertFalse(d.should_alert)


# ---------------------------------------------------------------------------
# bases_loaded_clutch
# ---------------------------------------------------------------------------

class TestBasesLoadedClutch(unittest.TestCase):
    def test_fires_7th_2_outs(self):
        d = check_bases_loaded_clutch(make_game(
            inning=7, inning_state="Middle", outs=2, runners=RUNNERS,
        ), CTX)
        self.assertTrue(d.should_alert)

    def test_fires_9th(self):
        d = check_bases_loaded_clutch(make_game(
            inning=9, outs=2, runners=RUNNERS, away_runs=5, home_runs=3,
        ), CTX)
        self.assertTrue(d.should_alert)

    def test_fires_within_2(self):
        d = check_bases_loaded_clutch(make_game(
            inning=8, outs=2, runners=RUNNERS, away_runs=6, home_runs=4,
        ), CTX)
        self.assertTrue(d.should_alert)

    def test_no_fire_6th(self):
        d = check_bases_loaded_clutch(make_game(
            inning=6, outs=2, runners=RUNNERS,
        ), CTX)
        self.assertFalse(d.should_alert)

    def test_no_fire_1_out(self):
        d = check_bases_loaded_clutch(make_game(
            inning=8, outs=1, runners=RUNNERS,
        ), CTX)
        self.assertFalse(d.should_alert)

    def test_no_fire_two_on(self):
        two_on = {"first": {"id": 1}, "second": {"id": 2}}
        d = check_bases_loaded_clutch(make_game(
            inning=8, outs=2, runners=two_on,
        ), CTX)
        self.assertFalse(d.should_alert)

    def test_no_fire_3_run_gap(self):
        d = check_bases_loaded_clutch(make_game(
            inning=8, outs=2, runners=RUNNERS, away_runs=6, home_runs=3,
        ), CTX)
        self.assertFalse(d.should_alert)

    def test_no_fire_not_live(self):
        d = check_bases_loaded_clutch(make_game(
            state="Final", inning=8, outs=2, runners=RUNNERS,
        ), CTX)
        self.assertFalse(d.should_alert)


# ---------------------------------------------------------------------------
# pitcher_flirting_history
# ---------------------------------------------------------------------------

def _boxscore(side: str, sp_id: int, ks: int, runs: int, ip: str) -> dict:
    other = "home" if side == "away" else "away"
    return {
        "teams": {
            side: {
                "pitchers": [sp_id],
                "players": {
                    f"ID{sp_id}": {
                        "person": {"id": sp_id, "fullName": "Test Pitcher"},
                        "stats": {"pitching": {
                            "strikeOuts": ks, "runs": runs, "inningsPitched": ip,
                        }},
                    },
                },
            },
            other: {"pitchers": [], "players": {}},
        },
    }


class TestPitcherFlirtingHistory(unittest.TestCase):
    def test_fires_12_strikeouts(self):
        ctx = TriggerContext(boxscore=_boxscore("home", 500, 12, 1, "7.0"))
        d = check_pitcher_flirting_history(make_game(inning=8), ctx)
        self.assertTrue(d.should_alert)
        self.assertIn("12 Ks", d.body)

    def test_fires_15_strikeouts_away_side(self):
        ctx = TriggerContext(boxscore=_boxscore("away", 500, 15, 2, "8.0"))
        d = check_pitcher_flirting_history(make_game(inning=9), ctx)
        self.assertTrue(d.should_alert)

    def test_fires_cg_shutout(self):
        ctx = TriggerContext(boxscore=_boxscore("home", 501, 8, 0, "7.0"))
        d = check_pitcher_flirting_history(make_game(inning=7, inning_state="End"), ctx)
        self.assertTrue(d.should_alert)
        self.assertIn("shutout", d.title.lower())

    def test_no_fire_11_ks(self):
        ctx = TriggerContext(boxscore=_boxscore("home", 500, 11, 1, "7.0"))
        d = check_pitcher_flirting_history(make_game(inning=8), ctx)
        self.assertFalse(d.should_alert)

    def test_no_fire_no_boxscore(self):
        d = check_pitcher_flirting_history(make_game(inning=8), TriggerContext())
        self.assertFalse(d.should_alert)

    def test_no_fire_6th(self):
        ctx = TriggerContext(boxscore=_boxscore("home", 500, 14, 0, "6.0"))
        d = check_pitcher_flirting_history(make_game(inning=6), ctx)
        self.assertFalse(d.should_alert)

    def test_no_fire_cg_but_runs(self):
        ctx = TriggerContext(boxscore=_boxscore("home", 501, 8, 2, "7.0"))
        d = check_pitcher_flirting_history(make_game(inning=7, inning_state="End"), ctx)
        self.assertFalse(d.should_alert)

    def test_no_fire_cg_but_short(self):
        ctx = TriggerContext(boxscore=_boxscore("home", 501, 6, 0, "6.2"))
        d = check_pitcher_flirting_history(make_game(inning=7, inning_state="End"), ctx)
        self.assertFalse(d.should_alert)


# ---------------------------------------------------------------------------
# grand_slam
# ---------------------------------------------------------------------------

def _pbp(inning: int, is_top: bool, event_type: str, rbi: int) -> dict:
    return {
        "allPlays": [{
            "about": {"inning": inning, "isTopInning": is_top},
            "result": {"eventType": event_type, "rbi": rbi},
            "matchup": {"batter": {"fullName": "Test Batter"}},
        }],
    }


class TestGrandSlam(unittest.TestCase):
    def test_fires_current_inning(self):
        ctx = TriggerContext(play_by_play=_pbp(8, True, "home_run", 4))
        d = check_grand_slam(make_game(inning=8), ctx)
        self.assertTrue(d.should_alert)
        self.assertIn("GRAND SLAM", d.title)
        self.assertIn("Test Batter", d.body)

    def test_fires_previous_inning(self):
        ctx = TriggerContext(play_by_play=_pbp(7, False, "home_run", 4))
        d = check_grand_slam(make_game(inning=8), ctx)
        self.assertTrue(d.should_alert)

    def test_no_fire_3_rbi_homer(self):
        ctx = TriggerContext(play_by_play=_pbp(8, True, "home_run", 3))
        d = check_grand_slam(make_game(inning=8), ctx)
        self.assertFalse(d.should_alert)

    def test_no_fire_no_pbp(self):
        d = check_grand_slam(make_game(inning=8), TriggerContext())
        self.assertFalse(d.should_alert)

    def test_no_fire_too_old(self):
        ctx = TriggerContext(play_by_play=_pbp(5, True, "home_run", 4))
        d = check_grand_slam(make_game(inning=8), ctx)
        self.assertFalse(d.should_alert)

    def test_no_fire_not_live(self):
        ctx = TriggerContext(play_by_play=_pbp(8, True, "home_run", 4))
        d = check_grand_slam(make_game(state="Final", inning=8), ctx)
        self.assertFalse(d.should_alert)

    def test_no_fire_strikeout(self):
        ctx = TriggerContext(play_by_play=_pbp(8, True, "strikeout", 0))
        d = check_grand_slam(make_game(inning=8), ctx)
        self.assertFalse(d.should_alert)


# ---------------------------------------------------------------------------
# Registry and dispatch
# ---------------------------------------------------------------------------

class TestRegistry(unittest.TestCase):
    def test_all_triggers_in_registry(self):
        expected = {
            "close_late", "walk_off", "extra_innings", "lead_change",
            "bases_loaded_clutch", "pitcher_flirting_history", "grand_slam",
        }
        self.assertEqual(VALID_TRIGGERS, frozenset(expected))
        self.assertEqual(set(REGISTRY.keys()), expected)

    def test_run_trigger_unknown(self):
        d = run_trigger("nonexistent", make_game(), CTX)
        self.assertFalse(d.should_alert)
        self.assertIn("unknown trigger", d.reason)

    def test_run_trigger_dispatches(self):
        d = run_trigger("close_late", make_game(inning=8, inning_state="Middle"), CTX)
        self.assertTrue(d.should_alert)

    def test_needs_pbp(self):
        self.assertEqual(NEEDS_PLAY_BY_PLAY, frozenset({"grand_slam"}))

    def test_needs_boxscore(self):
        self.assertEqual(NEEDS_BOXSCORE, frozenset({"pitcher_flirting_history"}))


# ---------------------------------------------------------------------------
# Backward-compat should_alert shim
# ---------------------------------------------------------------------------

class TestShouldAlertShim(unittest.TestCase):
    def test_shim_fires_close_late(self):
        g = make_game(inning=8, inning_state="Middle", away_runs=3, home_runs=3)
        self.assertTrue(should_alert(g, max_run_diff=1).should_alert)

    def test_shim_no_fire_not_live(self):
        g = make_game(state="Final", inning=8)
        self.assertFalse(should_alert(g).should_alert)

    def test_shim_team_filter_match(self):
        g = make_game(inning=8, inning_state="Middle", home_id=119, away_id=135)  # LAD/SD
        self.assertTrue(should_alert(g, team_filter=frozenset({"LAD"})).should_alert)

    def test_shim_team_filter_no_match(self):
        g = make_game(inning=8, inning_state="Middle", home_id=119, away_id=135)
        d = should_alert(g, team_filter=frozenset({"NYY"}))
        self.assertFalse(d.should_alert)
        self.assertIn("teams not in filter", d.reason)

    def test_shim_max_run_diff_two(self):
        g = make_game(inning=8, inning_state="Top", away_runs=5, home_runs=3)
        self.assertTrue(should_alert(g, max_run_diff=2).should_alert)


if __name__ == "__main__":
    unittest.main()
