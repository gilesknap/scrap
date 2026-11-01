"""scrap's client of the public site's receiver (docs/reference/public-site.md,
Endpoints): manifest, put, delete and sync, over HTTP/1.1 with keep-alive and the
bearer token. A ``503 busy`` (another write holds the receiver's lock) is retried for
up to BUSY_FOR seconds; any other refusal, and an unreachable receiver, is a
ReceiverError with the receiver's error code (or "unreachable").

httpx2 cannot send ``Expect: 100-continue``, so it is not sent: the contract asks for
it only where the client library supports it, and the receiver's lingering close
still delivers an early refusal."""

import logging
import time
from types import TracebackType
from typing import Any

import httpx2

from .errors import ReceiverError
from .unit import build_unit

__all__ = ["BUSY_FOR", "Receiver"]

BUSY_FOR = 10.0  # seconds a busy receiver is retried before giving up
TIMEOUT = httpx2.Timeout(60.0, connect=5.0)  # a 200 MiB unit on a fast link
log = logging.getLogger(__name__)


class Receiver:
    def __init__(
        self, base: str, token: str, busy_for: float = BUSY_FOR,
        transport: httpx2.BaseTransport | None = None,
    ) -> None:  # fmt: skip
        self.busy_for = busy_for
        self.http = httpx2.Client(
            base_url=base,
            headers={"Authorization": f"Bearer {token}"},
            timeout=TIMEOUT,
            trust_env=False,  # never through a proxy from the environment
            transport=transport,
        )

    def __enter__(self) -> "Receiver":
        return self

    def __exit__(
        self,
        kind: type[BaseException] | None,
        error: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self.http.close()

    def _send(self, method: str, path: str, **kw: Any) -> httpx2.Response:
        """One request, a busy answer retried; ReceiverError for a refusal."""
        give_up = time.monotonic() + self.busy_for
        while True:
            try:
                response = self.http.request(method, path, **kw)
            except httpx2.HTTPError as e:
                raise ReceiverError("unreachable", type(e).__name__) from None
            if response.status_code < 400:
                return response
            try:
                body = response.json()
                code, detail = str(body["error"]), str(body.get("detail", ""))
            except (ValueError, KeyError, TypeError):
                code, detail = f"http_{response.status_code}", ""
            if code == "busy" and time.monotonic() < give_up:
                wait = response.headers.get("Retry-After", "1")
                time.sleep(min(float(wait) if wait.isdigit() else 1.0, 1.0))
                continue
            log.warning("receiver: %s %s: %s", method, path, code)
            raise ReceiverError(code, detail, response.status_code)

    def manifest(self) -> dict[str, Any]:
        """What the site holds: {"units": {unit: {digest, files, bytes, at}}, ...}."""
        return self._send("GET", "/v1/manifest").json()

    def put(self, unit: str, files: dict[str, bytes]) -> str:
        """Replace (or make) a unit; its digest."""
        body, dig = build_unit(files)
        headers = {"Content-Type": "application/x-tar", "Scrap-Digest": dig}
        self._send("PUT", f"/v1/units/{unit}", content=body, headers=headers)
        return dig

    def delete(self, unit: str) -> None:
        self._send("DELETE", f"/v1/units/{unit}")

    def sync(self, keep: list[str]) -> list[str]:
        """Delete every unit not in keep (which holds home); those deleted."""
        return self._send("POST", "/v1/sync", json={"keep": keep}).json()["deleted"]
