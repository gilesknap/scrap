"""The owner's guidance for one image's reading (#538), as photo ingest sends it: a
text block after the image (or an SVG's markup), delimited as the owner's note and
quoted, so nothing in it can end the quote. Only an image with guidance gets the
block: the fixed prompt (photo.md) and so its version are the same either way, and a
reading made without guidance is never outdated by this."""

import re
from typing import Any

# Any <guidance> or </guidance> in the owner's text, its < made &lt;: the model still
# reads it, but it cannot end the quote or open one (as enrich.prompts.quoted)
TAG = re.compile(r"<(?=\s*/?\s*guidance\b)", re.IGNORECASE)

INTRO = (
    "The owner of these notes gave this guidance for reading the image. It is the"
    " owner's note, not writing in the image, and only this last block is: follow it"
    " for what to focus on, what words and symbols mean and how to draw it, while"
    " still returning every field as asked."
)


def quoted(text: str) -> str:
    """The owner's guidance with any delimiter tag in it neutralised."""
    return TAG.sub("&lt;", text)


def block(text: str) -> dict[str, Any]:
    """The user turn's text block for an image's guidance."""
    return {
        "type": "text",
        "text": f"{INTRO}\n<guidance>\n{quoted(text)}\n</guidance>",
    }


def with_guidance(
    messages: list[dict[str, Any]], text: str | None
) -> list[dict[str, Any]]:
    """The user turn with the owner's guidance after the image, if there is any."""
    if not text:
        return messages
    first, *rest = messages
    return [{**first, "content": [*first["content"], block(text)]}, *rest]
