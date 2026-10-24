"""Enrich: the callables a job is given."""

from collections.abc import Callable

from .. import claude, fetch

Call = Callable[..., claude.Completion]
Fetch = Callable[[str], fetch.Fetched]
