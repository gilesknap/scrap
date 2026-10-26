"""The Store: its mixins assembled into one class."""

from .capture import CaptureMixin
from .core import Core
from .edits import EditsMixin
from .meta import MetaMixin
from .pages import PagesMixin
from .photos import PhotosMixin
from .pinned import PinnedMixin
from .revisions import RevisionsMixin
from .search import SearchMixin
from .trash import TrashMixin


class Store(
    CaptureMixin,
    PinnedMixin,
    PagesMixin,
    EditsMixin,
    PhotosMixin,
    MetaMixin,
    RevisionsMixin,
    SearchMixin,
    TrashMixin,
    Core,
):
    """One SQLite database and a folder of content-addressed files."""
