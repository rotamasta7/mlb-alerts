"""Send notifications via ntfy.sh."""

from __future__ import annotations

import logging

import requests

log = logging.getLogger(__name__)

TIMEOUT = 10


def send_alert(
    server: str,
    topic: str,
    title: str,
    body: str,
    priority: str = "high",
    tags: str = "baseball",
    click_url: str | None = None,
    dry_run: bool = False,
) -> bool:
    """POST a push alert to ntfy. Returns True on success (or dry-run)."""
    url = f"{server}/{topic}"
    headers = {
        "Title": title,
        "Priority": priority,
        "Tags": tags,
    }
    if click_url:
        headers["Click"] = click_url
        headers["Actions"] = f"view, Open Gameday, {click_url}, clear=true"

    if dry_run:
        log.info("[DRY RUN] POST %s", url)
        log.info("[DRY RUN] title: %s", title)
        log.info("[DRY RUN] body:  %s", body.replace("\n", " | "))
        return True

    try:
        resp = requests.post(url, data=body.encode("utf-8"), headers=headers, timeout=TIMEOUT)
        resp.raise_for_status()
        log.info("Sent alert '%s' to %s", title, _mask(topic))
        return True
    except requests.RequestException as e:
        log.error("Failed to send ntfy alert '%s': %s", title, e)
        return False


def send_plain(
    server: str,
    topic: str,
    title: str,
    body: str,
    priority: str = "default",
    tags: str = "",
) -> bool:
    """Send an arbitrary notification. Used by the manual test script."""
    url = f"{server}/{topic}"
    headers = {"Title": title, "Priority": priority}
    if tags:
        headers["Tags"] = tags
    try:
        resp = requests.post(url, data=body.encode("utf-8"), headers=headers, timeout=TIMEOUT)
        resp.raise_for_status()
        return True
    except requests.RequestException as e:
        log.error("ntfy send failed: %s", e)
        return False


def _mask(topic: str) -> str:
    if len(topic) <= 8:
        return "***"
    return topic[:4] + "…" + topic[-4:]
