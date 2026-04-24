"""Subscriber configuration. One poller, many people.

Source of truth in production is the `SUBSCRIBERS_JSON` GitHub Actions secret
(a JSON array). For local dev / CI testing, you can point `SUBSCRIBERS_FILE`
at a YAML or JSON file.
"""

from __future__ import annotations

import json
import logging
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)


_NAME_RE = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9_.-]{0,31}$")
_DEFAULT_TRIGGERS: frozenset[str] = frozenset({"close_late"})


@dataclass(frozen=True)
class Subscriber:
    name: str
    ntfy_topic: str
    team_filter: frozenset[str] = field(default_factory=frozenset)
    max_run_diff: int = 1
    triggers: frozenset[str] = field(default_factory=lambda: _DEFAULT_TRIGGERS)

    def __post_init__(self) -> None:
        if not _NAME_RE.match(self.name):
            raise ValueError(
                f"Invalid subscriber name '{self.name}'. "
                "Must be 1-32 chars of [a-zA-Z0-9._-], starting alphanumeric."
            )
        if not self.ntfy_topic or len(self.ntfy_topic) < 6:
            raise ValueError(
                f"Subscriber '{self.name}' has a bad ntfy_topic "
                f"(must be at least 6 chars). Got: '{self.ntfy_topic}'."
            )
        if self.max_run_diff < 0:
            raise ValueError(
                f"Subscriber '{self.name}' max_run_diff must be >= 0."
            )
        # Lazy import to avoid cycles
        from triggers import VALID_TRIGGERS
        unknown = self.triggers - VALID_TRIGGERS
        if unknown:
            raise ValueError(
                f"Subscriber '{self.name}' has unknown triggers: {sorted(unknown)}. "
                f"Valid triggers: {sorted(VALID_TRIGGERS)}"
            )
        if not self.triggers:
            raise ValueError(f"Subscriber '{self.name}' has no triggers configured.")

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Subscriber":
        raw_filter = data.get("team_filter") or []
        if isinstance(raw_filter, str):
            raw_filter = [p.strip() for p in raw_filter.split(",") if p.strip()]

        raw_triggers = data.get("triggers")
        if raw_triggers is None:
            triggers = _DEFAULT_TRIGGERS
        else:
            if isinstance(raw_triggers, str):
                raw_triggers = [p.strip() for p in raw_triggers.split(",") if p.strip()]
            triggers = frozenset(str(t).strip() for t in raw_triggers if str(t).strip())

        return cls(
            name=str(data["name"]).strip(),
            ntfy_topic=str(data["ntfy_topic"]).strip(),
            team_filter=frozenset(str(t).strip().upper() for t in raw_filter if str(t).strip()),
            max_run_diff=int(data.get("max_run_diff", 1)),
            triggers=triggers,
        )


def load_from_env() -> list[Subscriber]:
    """Load subscribers from SUBSCRIBERS_JSON or SUBSCRIBERS_FILE."""
    json_blob = os.environ.get("SUBSCRIBERS_JSON", "").strip()
    file_path = os.environ.get("SUBSCRIBERS_FILE", "").strip()

    if json_blob:
        return _parse_json(json_blob)

    if file_path:
        return load_from_file(file_path)

    raise RuntimeError(
        "No subscriber config found. Set SUBSCRIBERS_JSON (secret) or "
        "SUBSCRIBERS_FILE (path to YAML/JSON file)."
    )


def load_from_file(path: str | Path) -> list[Subscriber]:
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"Subscriber file not found: {p}")
    text = p.read_text(encoding="utf-8")
    if p.suffix.lower() in {".yaml", ".yml"}:
        return _parse_yaml(text)
    return _parse_json(text)


def _parse_json(text: str) -> list[Subscriber]:
    try:
        data = json.loads(text)
    except json.JSONDecodeError as e:
        raise ValueError(f"SUBSCRIBERS_JSON is not valid JSON: {e}") from e
    return _build(data)


def _parse_yaml(text: str) -> list[Subscriber]:
    try:
        import yaml  # lazy import; only needed for local YAML editing
    except ImportError as e:
        raise RuntimeError(
            "PyYAML is not installed. Install it with: pip install pyyaml"
        ) from e
    data = yaml.safe_load(text)
    return _build(data)


def _build(data: Any) -> list[Subscriber]:
    # Accept either a plain array OR {"subscribers": [...]}
    if isinstance(data, dict):
        data = data.get("subscribers", [])
    if not isinstance(data, list):
        raise ValueError("Subscriber config must be a list of objects.")
    subs = [Subscriber.from_dict(entry) for entry in data]
    _assert_unique_names(subs)
    return subs


def _assert_unique_names(subs: list[Subscriber]) -> None:
    names = [s.name for s in subs]
    if len(set(names)) != len(names):
        dups = [n for n in names if names.count(n) > 1]
        raise ValueError(f"Duplicate subscriber names: {sorted(set(dups))}")
