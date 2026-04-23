"""Runtime configuration for the multi-user poller."""

from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Config:
    ntfy_server: str
    ntfy_priority: str
    state_path: str
    dry_run: bool

    @classmethod
    def from_env(cls) -> "Config":
        return cls(
            ntfy_server=os.environ.get("NTFY_SERVER", "https://ntfy.sh").rstrip("/"),
            ntfy_priority=os.environ.get("NTFY_PRIORITY", "high"),
            state_path=os.environ.get("STATE_PATH", "state.json"),
            dry_run=_truthy(os.environ.get("MLB_DRY_RUN")),
        )


def _truthy(value: str | None) -> bool:
    return bool(value) and value.strip().lower() in {"1", "true", "yes", "on"}
