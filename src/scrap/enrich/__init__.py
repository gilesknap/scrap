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
kept apart from the text, steered by the owner's guidance (writeup_ops). Topic pages
(#261): a weekly discovery call over the whole library makes topics and adds their
sources (topic_finding, scrap enrich --topics), and each topic's synthesis of its
sources is its write-up (synthesis, an enrich job of reason topic). A write-up older
than the page or its prompt is outdated (#262, store.writeups.OUTDATED): the owner
regenerates it, or scrap enrich --writeups --outdated (writeup_pass). Jobs run on
the ingest worker's thread; everything shares its queue pause and daily budget. See
docs/explanations/ingest.md.
"""

from .checking import (
    checked,
    checked_related,
    checked_topics,
    checked_writeup,
    cited,
    clean_tag,
    record,
)
from .constants import (
    AUTO_FILES,
    AUTO_RELATED_FILES,
    BOARDS,
    BY_TAGS,
    BY_WORDS,
    CLAIM,
    DELIMITER,
    DELIMITERS,
    DISCOVERY_SCHEMA,
    FILES,
    IMAGES,
    MAX_BOARDS,
    MAX_BODY,
    MAX_CANDIDATES,
    MAX_FILES,
    MAX_GUIDANCE,
    MAX_IMAGES,
    MAX_INVENTED,
    MAX_NEW_TAGS,
    MAX_NEW_TOPICS,
    MAX_RELATED,
    MAX_SUMMARY,
    MAX_TITLE,
    MAX_VOCAB,
    MAX_WRITEUP,
    QUERY_WORDS,
    RELATED_BODY,
    RELATED_FILES,
    RELATED_IMAGES,
    RELATED_SCHEMA,
    RELATED_WRITEUP,
    SAVE_REREAD,
    SCHEMA,
    SHORT,
    STALE,
    TITLE_CAS,
    TOPIC_DUE,
    TOPIC_INDEX,
    TOPIC_INPUT,
    TOPIC_SCHEMA,
    TOPIC_SOURCE,
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
    file_lines,
    image_lines,
    index_lines,
    one_line,
    page_files,
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
from .synthesis import (
    synthesise,
)
from .topic_finding import (
    discover,
    page_index,
    topics_pass,
)
from .topic_ops import (
    exclude,
)
from .topic_ops import (
    index as topic_index,
)
from .topic_ops import (
    sources as topic_sources,
)
from .topic_prompts import (
    discovery_message,
    topic_message,
)
from .types import (
    Call,
    Fetch,
)
from .versions import (
    prompt_versions,
)
from .writeup_ops import (
    regenerate,
    set_guidance,
)
from .writing import (
    write_up,
    writeup_pass,
)

__all__ = [
    "Enricher",
    "prompt_versions",
    "DISCOVERY_SCHEMA",
    "MAX_NEW_TOPICS",
    "TOPIC_DUE",
    "TOPIC_INDEX",
    "TOPIC_INPUT",
    "TOPIC_SCHEMA",
    "TOPIC_SOURCE",
    "checked_topics",
    "discover",
    "discovery_message",
    "exclude",
    "page_index",
    "synthesise",
    "topic_index",
    "topic_message",
    "topic_sources",
    "topics_pass",
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
    "set_guidance",
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
    "AUTO_FILES",
    "AUTO_RELATED_FILES",
    "BY_TAGS",
    "BY_WORDS",
    "CANDIDATES",
    "CLAIM",
    "DELIMITER",
    "DELIMITERS",
    "FILES",
    "IMAGES",
    "Image",
    "Call",
    "Fetch",
    "MAX_BODY",
    "MAX_CANDIDATES",
    "MAX_FILES",
    "MAX_IMAGES",
    "MAX_INVENTED",
    "MAX_NEW_TAGS",
    "MAX_RELATED",
    "MAX_SUMMARY",
    "MAX_TITLE",
    "MAX_VOCAB",
    "QUERY_WORDS",
    "RELATED_BODY",
    "RELATED_FILES",
    "RELATED_IMAGES",
    "SAVE_REREAD",
    "SHORT",
    "STALE",
    "TITLE_CAS",
    "WORD",
    "checked",
    "checked_related",
    "clean_tag",
    "file_lines",
    "image_lines",
    "index_lines",
    "log",
    "one_line",
    "page_files",
    "page_images",
    "page_message",
    "quoted",
    "record",
    "related_message",
    "related_prompt",
    "system_prompt",
    "vocabulary",
]
