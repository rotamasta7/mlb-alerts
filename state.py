"""Per-subscriber dedup state. One alert per (subscriber, game) per UTC day."""

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
    alerted: dict[str, set[int]] = field(default_factory=dict)

    def has_alerted(self, subscriber: str, game_pk: int) -> bool:
        return game_pk in self.alerted.get(subscriber, set())

    def mark_alerted(self, subscriber: str, game_pk: int) -> None:
        self.alerted.setdefault(subscriber, set()).add(game_pk)

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
                    name: sorted(pks) for name, pks in sorted(self.alerted.items())
                },
                "updated_at": datetime.now(timezone.utc).isoformat(),
            },
            indent=2,
        )

    @classmethod
    def from_json(cls, text: str) -> "State":
        data = json.loads(text)
        alerted_raw = data.get("alerted", {}) or {}
        # Backwards compatibility: old v1 state had a flat "alerted_game_pks".
        if not alerted_raw and "alerted_game_pks" in data:
            alerted_raw = {"_legacy": data.get("alerted_game_pks") or []}
        alerted: dict[str, set[int]] = {}
        for name, pks in alerted_raw.items():
            alerted[name] = set(int(x) for x in (pks or []))
        return cls(
            date_utc=data.get("date_utc", ""),
            alerted=alerted,
        )


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
