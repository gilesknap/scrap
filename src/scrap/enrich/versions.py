"""Enrich: the current prompt version of the derived data the owner keeps up to date
(#262, #291): a board's write-up. is:outdated (store.health), the write-up view's
outdated flag and scrap enrich --writeups --outdated compare a version with it; the
store is given it by whoever makes it (store.Store.prompts)."""

from .prompts import writeup_prompt


def prompt_versions() -> dict[str, str]:
    """The current prompt versions: writeup (a board's write-up). A topic's synthesis is
    checked by the weekly pass, with its own (enrich TOPIC_DUE)."""
    return {"writeup": writeup_prompt([])[1]}
