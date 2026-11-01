"""The errors of publishing (docs/reference/public-site.md, "The PWA's API in scrap"):
each has the HTTP status and the ``error`` code the API answers with, and a sentence
(``detail``)."""

__all__ = [
    "BadRequest",
    "Busy",
    "CheckError",
    "NotConfigured",
    "NotPublic",
    "PublishError",
    "PublishFailed",
    "ReceiverError",
    "Stale",
    "TooLarge",
    "Unconfirmed",
]


class PublishError(Exception):
    """A publish refused or failed: answered as {"error": code, "detail": detail}."""

    status = 500
    code = "server_error"

    def __init__(self, detail: str, code: str | None = None) -> None:
        super().__init__(detail)
        self.detail = detail
        if code is not None:
            self.code = code


class NotPublic(PublishError):  # noqa: N818
    """The page is not public, or it is in the trash."""

    status, code = 409, "not_public"


class Unconfirmed(PublishError):  # noqa: N818
    """A first publish (the page has no kept copy: never published, or not since it
    was unpublished) without "confirmed": true."""

    status, code = 409, "unconfirmed"

    def __init__(self) -> None:
        super().__init__(
            "the page is not on the public site yet: confirm the first publish"
            " (confirmed: true)"
        )


class Stale(PublishError):  # noqa: N818
    """base_rev is not the page's current revision (rev)."""

    status, code = 409, "stale"

    def __init__(self, rev: int) -> None:
        super().__init__(f"the page is at revision {rev}: render it again")
        self.rev = rev


class TooLarge(PublishError):  # noqa: N818
    """The request body is over the limit."""

    status, code = 413, "too_large"


class CheckError(PublishError):
    """The HTML fails a rule (bad_html, bad_placeholder), a cap (too_many_files,
    file_too_large, unit_too_large) or names a tag the page no longer has
    (stale_tags)."""

    status, code = 422, "bad_html"


class PublishFailed(PublishError):  # noqa: N818
    """The receiver refused or failed: detail holds its error code."""

    status, code = 502, "publish_failed"


class NotConfigured(PublishError):  # noqa: N818
    """Publishing is off: no SCRAP_PUBLISH_TO, or no token."""

    status, code = 503, "not_configured"

    def __init__(self) -> None:
        super().__init__(
            "publishing is off: set SCRAP_PUBLISH_TO and SCRAP_PUBLISH_TOKEN_FILE"
        )


class Busy(PublishError):  # noqa: N818
    """A photo's preview, which the publish reads, is being made: answered 503 with
    Retry-After (retry_after seconds)."""

    status, code = 503, "busy"
    retry_after = 5

    def __init__(self) -> None:
        super().__init__("a photo's preview is being made: try again shortly")


class ReceiverError(Exception):
    """What the receiver answered (its error code, else unreachable), inside the
    client; publish turns it into PublishFailed."""

    def __init__(self, code: str, detail: str, status: int | None = None) -> None:
        super().__init__(f"{code}: {detail}")
        self.code, self.detail, self.status = code, detail, status


class BadRequest(PublishError):  # noqa: N818
    """A publish's body is not the JSON it should be."""

    status, code = 422, "bad_request"
