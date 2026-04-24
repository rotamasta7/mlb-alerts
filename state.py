"""Per-subscriber dedup state. One alert per (subscriber, game_pk, trigger) per UTC day.

Keys inside each subscriber's alerted set are strings of the form "<game_pk>:<trigger_name>".

Migration: v2 stored bare integer gamePks (one alert per game per day, close_late only).
On load, bare int entries are upgraded to "<pk>:close_late" so v2 state doesn't re-fire
close_late on the first v3 run.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

log = logging.getLogger(__name__)


@dataclass
class State:
    """Per-subscriber dedup set, stored as one JSON file."""
    date_utc: str = ""
    alerted: dict[str, set[str]] = field(default_factory=dict)

    def has_alerted(self, subscriber: str, alert_key: str) -> bool:
        return alert_key in self.alerted.get(subscriber, set())

    def mark_alerted(self, subscriber: str, alert_key: str) -> None:
        self.alerted.setdefault(subscriber, set()).add(alert_key)

    def reset_if_new_day(self, today_utc: str) -> None:
        if self.date_utc != today_utc:
            log.info(
                "New UTC day (%s -> %s); resetting alert history",
                self.date_utc or "fresh",
                today_utc,
            )
            self.date_utc = today_utc
            self.alerted = {}

    def prune_unknown(self, known_names: set[str]) -> None:
        """Drop entries for subscribers that no longer exist."""
        stale = [name for name in self.alerted if name not in known_names]
        for name in stale:
            log.info("Pruning state for removed subscriber '%s'", name)
            self.alerted.pop(name, None)

    def to_json(self) -> str:
        return json.dumps(
            {
                "date_utc": self.date_utc,
                "alerted": {
                    name: sorted(keys) for name, keys in sorted(self.alerted.items())
                },
                "updated_at": datetime.now(timezone.utc).isoformat(),
            },
            indent=2,
        )

    @classmethod
    def from_json(cls, text: str) -> "State":
        data = json.loads(text)
        alerted_raw = data.get("alerted", {}) or {}
        # v1 legacy: flat "alerted_game_pks"
        if not alerted_raw and "alerted_game_pks" in data:
            alerted_raw = {"_legacy": data.get("alerted_game_pks") or []}
        alerted: dict[str, set[str]] = {}
        for name, keys in alerted_raw.items():
            upgraded: set[str] = set()
            for k in (keys or []):
                upgraded.add(_upgrade_key(k))
            alerted[name] = upgraded
        return cls(
            date_utc=data.get("date_utc", ""),
            alerted=alerted,
        )


def _upgrade_key(raw: object) -> str:
    """v2 stored bare int game_pks; v3 uses '<pk>:<trigger>'."""
    if isinstance(raw, int):
        return f"{raw}:close_late"
    s = str(raw)
    if ":" not in s:
        return f"{s}:close_late"
    return s


def load(path: str | Path) -> State:
    p = Path(path)
    if not p.exists():
        log.info("No existing state at %s; starting fresh", p)
        return State()
    try:
        return State.from_json(p.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, ValueError) as e:
        log.warning("State file at %s is corrupt (%s); starting fresh", p, e)
        return State()


def save(state: State, path: str | Path) -> None:
    p = Path(path)
    p.write_text(state.to_json() + "\n", encoding="utf-8")
    log.debug("Saved state to %s", p)
