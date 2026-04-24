"""Unit tests for the multi-user dedup state."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from state import State, load, save


class TestState(unittest.TestCase):
    def test_mark_and_check(self):
        s = State()
        self.assertFalse(s.has_alerted("mitch", "123:close_late"))
        s.mark_alerted("mitch", "123:close_late")
        self.assertTrue(s.has_alerted("mitch", "123:close_late"))
        # Different trigger on same game: independent
        self.assertFalse(s.has_alerted("mitch", "123:walk_off"))
        # Different user: independent
        self.assertFalse(s.has_alerted("dave", "123:close_late"))

    def test_independent_per_user(self):
        s = State()
        s.mark_alerted("mitch", "1:close_late")
        s.mark_alerted("mitch", "2:close_late")
        s.mark_alerted("dave", "1:close_late")
        self.assertEqual(s.alerted["mitch"], {"1:close_late", "2:close_late"})
        self.assertEqual(s.alerted["dave"], {"1:close_late"})

    def test_reset_on_new_day(self):
        s = State(date_utc="2026-04-22", alerted={"mitch": {"1:close_late"}})
        s.reset_if_new_day("2026-04-23")
        self.assertEqual(s.date_utc, "2026-04-23")
        self.assertEqual(s.alerted, {})

    def test_no_reset_same_day(self):
        s = State(date_utc="2026-04-23", alerted={"mitch": {"1:close_late"}})
        s.reset_if_new_day("2026-04-23")
        self.assertEqual(s.alerted, {"mitch": {"1:close_late"}})

    def test_prune_unknown(self):
        s = State(alerted={
            "mitch": {"1:close_late"},
            "dave": {"2:walk_off"},
            "old_mate": {"3:close_late"},
        })
        s.prune_unknown({"mitch", "dave"})
        self.assertEqual(set(s.alerted.keys()), {"mitch", "dave"})

    def test_roundtrip(self):
        s = State(date_utc="2026-04-23", alerted={
            "mitch": {"7:close_late", "42:walk_off"},
            "dave": {"99:grand_slam"},
        })
        reloaded = State.from_json(s.to_json())
        self.assertEqual(reloaded.date_utc, "2026-04-23")
        self.assertEqual(reloaded.alerted, {
            "mitch": {"7:close_late", "42:walk_off"},
            "dave": {"99:grand_slam"},
        })

    def test_legacy_v2_bare_int_keys_migrate(self):
        """v2 stored bare integer gamePks. On load, upgrade to '<pk>:close_late'."""
        legacy = '{"date_utc": "2026-04-23", "alerted": {"mitch": [123, 456]}}'
        s = State.from_json(legacy)
        self.assertEqual(s.alerted["mitch"], {"123:close_late", "456:close_late"})

    def test_legacy_v1_state_migrates(self):
        """v1 state had a flat 'alerted_game_pks' list."""
        legacy = '{"date_utc": "2026-04-23", "alerted_game_pks": [1, 2]}'
        s = State.from_json(legacy)
        self.assertEqual(s.alerted.get("_legacy"), {"1:close_late", "2:close_late"})

    def test_load_missing_file(self):
        with tempfile.TemporaryDirectory() as d:
            s = load(Path(d) / "nope.json")
            self.assertEqual(s.alerted, {})

    def test_load_corrupt_file(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "bad.json"
            p.write_text("not json{{")
            s = load(p)
            self.assertEqual(s.alerted, {})

    def test_save_and_load(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "state.json"
            s = State(date_utc="2026-04-23", alerted={"mitch": {"1:close_late", "2:walk_off"}})
            save(s, p)
            loaded = load(p)
            self.assertEqual(loaded.date_utc, "2026-04-23")
            self.assertEqual(loaded.alerted, {"mitch": {"1:close_late", "2:walk_off"}})


if __name__ == "__main__":
    unittest.main()
