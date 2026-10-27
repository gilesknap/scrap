"""Size limits, vocabularies and the annotated argument types the tools share."""

import re
from typing import Annotated

from pydantic import Field

from ..store import CLAUDE

AUTHOR = CLAUDE  # page_rev and capture author of what is written over MCP
MAX_TITLE = 200  # characters
MAX_BODY = 200_000  # bytes of UTF-8, per write
MAX_TAGS = 20
MAX_ORIGIN = 200
MAX_KEY = 128
MAX_BULK = 200  # pages one edit_meta may change
MAX_TRASH = 50  # pages one trash_pages may move to the trash
MAX_DRAWING = 200_000  # bytes of a drawing's elements as JSON; whole elements only
MAX_DIFF = 100_000  # characters of a unified diff returned; the rest is cut
CONTEXT = 3  # lines around a change in a diff
DIFF_WORK = 1_000_000  # changed lines before x after: difflib up to this, else one hunk
HUNK = re.compile(r"^@@ -(\d+)(,\d+)? \+(\d+)(,\d+)? @@")
STATUSES = ("open", "in_progress", "done", "cancelled")
WRITE_KINDS = ("note", "todo", "read", "board", "doc")
MARK = re.compile(r"</?mark>")

Limit = Annotated[int, Field(ge=1, le=100)]
Batch = Annotated[
    str | None, Field(max_length=MAX_KEY, description="A batch id (bulk change)")
]
DryRun = Annotated[
    bool, Field(description="Only say which pages would change, and how")
]
Rev = Annotated[
    int | None,
    Field(ge=1, description="The page's current rev (from read): refused if the page "
          "has changed since"),
]  # fmt: skip
AllowEmpty = Annotated[
    bool, Field(description="Allow leaving the body empty (only if the user asked)")
]
BulkLimit = Annotated[
    int, Field(ge=1, le=MAX_BULK, description="Refuse a change to more pages")
]
