"""Enrich: Claude reads a text page and adds tags and a summary; related pages (#85).

A page's text is the user's and is never edited. On capture, save, backfill or Ask,
one tool-less, schema-checked call per page, on a small model (claude.text_model()),
gives tags (preferring the vocabulary in use), a summary, and for a saved link a
title; a link is fetched first (fetch.py: public addresses only, size and time
limits). Related pages are a call of their own (relate): on Ask, and in the nightly
pass (related_pass, scrap enrich --related) for every page changed since its last
picks, from candidates found by shared tags and full-text search, so the library's
size does not matter. What it adds is kept apart from the text (enrichment,
model_tag, related) and the user wins: a tag the user took off never comes back,
their tags are never removed, a title is replaced only while it is still the link as
captured, the kind only while it is an unfixed note. A board page (a whiteboard or
diagram photo) gets Claude's write-up instead (write_up, #256): a versioned explanation
kept apart from the text, steered by the owner's guidance (writeup_ops). Jobs run on
the ingest worker's thread; everything shares its queue pause and daily budget. See
docs/explanations/ingest.md.
"""

from .checking import (
    checked,
    checked_related,
    checked_writeup,
    cited,
    clean_tag,
    record,
)
from .constants import (
    BOARDS,
    BY_TAGS,
    BY_WORDS,
    CLAIM,
    DELIMITER,
    DELIMITERS,
    IMAGES,
    MAX_BOARDS,
    MAX_BODY,
    MAX_CANDIDATES,
    MAX_GUIDANCE,
    MAX_IMAGES,
    MAX_INVENTED,
    MAX_NEW_TAGS,
    MAX_RELATED,
    MAX_SUMMARY,
    MAX_TITLE,
    MAX_VOCAB,
    MAX_WRITEUP,
    QUERY_WORDS,
    RELATED_BODY,
    RELATED_IMAGES,
    RELATED_SCHEMA,
    RELATED_WRITEUP,
    SAVE_REREAD,
    SCHEMA,
    SHORT,
    STALE,
    TITLE_CAS,
    WORD,
    WRITEUP_BODY,
    WRITEUP_IMAGES,
    WRITEUP_SCHEMA,
)
from .enricher import (
    Enricher,
    log,
)
from .finding import (
    CANDIDATES,
    candidates,
    page_texts,
    search_words,
)
from .prompts import (
    Image,
    image_lines,
    index_lines,
    one_line,
    page_images,
    page_message,
    quoted,
    related_message,
    related_prompt,
    system_prompt,
    vocabulary,
    writeup_message,
    writeup_prompt,
)
from .queueing import (
    ask,
    backfill,
)
from .relating import (
    relate,
    related_pass,
    run_pass,
)
from .types import (
    Call,
    Fetch,
)
from .writeup_ops import (
    StaleWriteupError,
    regenerate,
    restore,
    set_guidance,
    versions,
)
from .writing import (
    write_up,
    writeup_pass,
)

__all__ = [
    "Enricher",
    "SCHEMA",
    "RELATED_SCHEMA",
    "backfill",
    "ask",
    "candidates",
    "page_texts",
    "search_words",
    "relate",
    "related_pass",
    "run_pass",
    "write_up",
    "writeup_pass",
    "regenerate",
    "restore",
    "set_guidance",
    "versions",
    "StaleWriteupError",
    "WRITEUP_SCHEMA",
    "WRITEUP_BODY",
    "WRITEUP_IMAGES",
    "BOARDS",
    "MAX_BOARDS",
    "MAX_GUIDANCE",
    "MAX_WRITEUP",
    "RELATED_WRITEUP",
    "checked_writeup",
    "cited",
    "writeup_message",
    "writeup_prompt",
    "BY_TAGS",
    "BY_WORDS",
    "CANDIDATES",
    "CLAIM",
    "DELIMITER",
    "DELIMITERS",
    "IMAGES",
    "Image",
    "Call",
    "Fetch",
    "MAX_BODY",
    "MAX_CANDIDATES",
    "MAX_IMAGES",
    "MAX_INVENTED",
    "MAX_NEW_TAGS",
    "MAX_RELATED",
    "MAX_SUMMARY",
    "MAX_TITLE",
    "MAX_VOCAB",
    "QUERY_WORDS",
    "RELATED_BODY",
    "RELATED_IMAGES",
    "SAVE_REREAD",
    "SHORT",
    "STALE",
    "TITLE_CAS",
    "WORD",
    "checked",
    "checked_related",
    "clean_tag",
    "image_lines",
    "index_lines",
    "log",
    "one_line",
    "page_images",
    "page_message",
    "quoted",
    "record",
    "related_message",
    "related_prompt",
    "system_prompt",
    "vocabulary",
]
