"""What the HTTP route modules share: the error for Claude being off, request text
checked for lone surrogates (Text), and a version restore. Below app.py, pages_api,
ingest_api, drawing_api and writeup_api, which import it."""

from typing import Annotated

from pydantic import AfterValidator, BaseModel, Field, StrictInt

from .store import SURROGATE


class EnrichOffError(Exception):
    """Claude enrichment is off (it needs SCRAP_INGEST=on, and SCRAP_ENRICH not off)."""


SURROGATE_MSG = "a lone surrogate"


def _encodable(value: str) -> str:
    """Refuse a lone surrogate: JSON can escape one, but the database cannot store it
    (a 500). The error does not carry the text, as invalid_request omits the input."""
    if value.isascii() or SURROGATE.search(value) is None:
        return value
    raise ValueError(f"must be valid Unicode ({SURROGATE_MSG})")


# Every request string that can reach the database goes through this
Text = Annotated[str, AfterValidator(_encodable)]


VERSION_NUMBER = Annotated[StrictInt, Field(ge=1, le=2**31)]


class Restore(BaseModel):
    version: VERSION_NUMBER  # the version to make current again
    base_version: VERSION_NUMBER  # the current one as the client saw it, else 409
