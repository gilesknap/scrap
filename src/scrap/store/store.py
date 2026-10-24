"""The Store: its mixins assembled into one class."""

from .core import Core
from .meta import MetaMixin
from .pages import PagesMixin
from .revisions import RevisionsMixin
from .search import SearchMixin
from .trash import TrashMixin


class Store(PagesMixin, MetaMixin, RevisionsMixin, SearchMixin, TrashMixin, Core):
    """One SQLite database and a folder of content-addressed files."""
