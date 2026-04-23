"""Unit tests for subscriber parsing."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from subscribers import Subscriber, load_from_file, _build, _parse_json


class TestSubscriber(unittest.TestCase):
    def test_minimal_valid(self):
        s = Subscriber.from_dict({"name": "mitch", "ntfy_topic": "abc123456"})
        self.assertEqual(s.name, "mitch")
        self.assertEqual(s.ntfy_topic, "abc123456")
        self.assertEqual(s.team_filter, frozenset())
        self.assertEqual(s.max_run_diff, 1)

    def test_full(self):
        s = Subscriber.from_dict({
            "name": "dave",
            "ntfy_topic": "dave-random-topic-abcdef",
            "team_filter": ["NYY", "bos"],
            "max_run_diff": 2,
        })
        self.assertEqual(s.team_filter, frozenset({"NYY", "BOS"}))
        self.assertEqual(s.max_run_diff, 2)

    def test_filter_as_csv_string(self):
        s = Subscriber.from_dict({
            "name": "eve",
            "ntfy_topic": "abc123456",
            "team_filter": "NYY, BOS , LAD",
        })
        self.assertEqual(s.team_filter, frozenset({"NYY", "BOS", "LAD"}))

    def test_bad_name_rejected(self):
        with self.assertRaises(ValueError):
            Subscriber.from_dict({"name": "!bad", "ntfy_topic": "abc123456"})

    def test_short_topic_rejected(self):
        with self.assertRaises(ValueError):
            Subscriber.from_dict({"name": "dave", "ntfy_topic": "abc"})

    def test_negative_diff_rejected(self):
        with self.assertRaises(ValueError):
            Subscriber.from_dict({"name": "dave", "ntfy_topic": "abc123456", "max_run_diff": -1})


class TestParsing(unittest.TestCase):
    def test_parse_array(self):
        subs = _parse_json(json.dumps([
            {"name": "mitch", "ntfy_topic": "abc123456"},
        ]))
        self.assertEqual(len(subs), 1)
        self.assertEqual(subs[0].name, "mitch")

    def test_parse_wrapped(self):
        subs = _build({"subscribers": [{"name": "dave", "ntfy_topic": "abc123456"}]})
        self.assertEqual(subs[0].name, "dave")

    def test_duplicate_names_rejected(self):
        with self.assertRaises(ValueError):
            _build([
                {"name": "mitch", "ntfy_topic": "abc123456"},
                {"name": "mitch", "ntfy_topic": "xyz123456"},
            ])

    def test_load_from_yaml_file(self):
        try:
            import yaml  # noqa: F401
        except ImportError:
            self.skipTest("PyYAML not available")
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "subs.yaml"
            p.write_text(
                "subscribers:\n"
                "  - name: mitch\n"
                "    ntfy_topic: mlb-alerts-xbgog1tjw5qmoqqznovybq\n"
                "    team_filter: [LAD, NYY]\n"
            )
            subs = load_from_file(p)
            self.assertEqual(len(subs), 1)
            self.assertEqual(subs[0].team_filter, frozenset({"LAD", "NYY"}))


if __name__ == "__main__":
    unittest.main()
