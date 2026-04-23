"""Unit tests for the multi-user dedup state."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from state import State, load, save


class TestState(unittest.TestCase):
    def test_mark_and_check(self):
        s = State()
        self.assertFalse(s.has_alerted("mitch", 123))
        s.mark_alerted("mitch", 123)
        self.assertTrue(s.has_alerted("mitch", 123))
        # Different user, same game: independent
        self.assertFalse(s.has_alerted("dave", 123))

    def test_independent_per_user(self):
        s = State()
        s.mark_alerted("mitch", 1)
        s.mark_alerted("mitch", 2)
        s.mark_alerted("dave", 1)
        self.assertEqual(s.alerted["mitch"], {1, 2})
        self.assertEqual(s.alerted["dave"], {1})

    def test_reset_on_new_day(self):
        s = State(date_utc="2026-04-22", alerted={"mitch": {1, 2}})
        s.reset_if_new_day("2026-04-23")
        self.assertEqual(s.date_utc, "2026-04-23")
        self.assertEqual(s.alerted, {})

    def test_no_reset_same_day(self):
        s = State(date_utc="2026-04-23", alerted={"mitch": {1}})
        s.reset_if_new_day("2026-04-23")
        self.assertEqual(s.alerted, {"mitch": {1}})

    def test_prune_unknown(self):
        s = State(alerted={"mitch": {1}, "dave": {2}, "old_mate": {3}})
        s.prune_unknown({"mitch", "dave"})
        self.assertEqual(set(s.alerted.keys()), {"mitch", "dave"})

    def test_roundtrip(self):
        s = State(date_utc="2026-04-23", alerted={"mitch": {7, 42}, "dave": {99}})
        reloaded = State.from_json(s.to_json())
        self.assertEqual(reloaded.date_utc, "2026-04-23")
        self.assertEqual(reloaded.alerted, {"mitch": {7, 42}, "dave": {99}})

    def test_legacy_v1_state_migrates(self):
        """Old state format had a flat alerted_game_pks; should still load."""
        legacy = '{"date_utc": "2026-04-23", "alerted_game_pks": [1, 2]}'
        s = State.from_json(legacy)
        self.assertEqual(s.alerted.get("_legacy", set()), {1, 2})

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
            s = State(date_utc="2026-04-23", alerted={"mitch": {1, 2}})
            save(s, p)
            loaded = load(p)
            self.assertEqual(loaded.date_utc, "2026-04-23")
            self.assertEqual(loaded.alerted, {"mitch": {1, 2}})


if __name__ == "__main__":
    unittest.main()
