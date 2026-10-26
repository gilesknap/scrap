"""Enrich: the current prompt versions of Claude's derived data that can be outdated
(#262): a board's write-up and a topic's synthesis. is:outdated (store.health), the
write-up view's outdated flag and scrap enrich --writeups --outdated compare a version
with these; the store is given them by whoever makes it (store.Store.prompts)."""

from .prompts import writeup_prompt
from .topic_prompts import topic_prompt


def prompt_versions() -> dict[str, str]:
    """The current prompt versions: writeup (a board's write-up) and topic (a topic's
    synthesis)."""
    return {"writeup": writeup_prompt([])[1], "topic": topic_prompt()[1]}
