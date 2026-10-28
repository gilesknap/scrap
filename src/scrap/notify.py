"""The one POST to SCRAP_NOTIFY_URL (an ntfy topic, say), for ingest pauses and gc."""

import logging
import os
import urllib.request

log = logging.getLogger(__name__)


def notify(message: str) -> None:
    """POST one fixed line to SCRAP_NOTIFY_URL, if set; a lost notice is only logged."""
    url = os.environ.get("SCRAP_NOTIFY_URL")
    if not url:
        return
    try:
        urllib.request.urlopen(url, message.encode(), timeout=10).close()
    except Exception:  # noqa: BLE001  a lost notice must not stop its caller
        log.warning("notification failed")
