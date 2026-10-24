"""Errors the store raises."""


class NotFoundError(Exception):
    """No such page or blob (or it is in the trash)."""


class NoSuchPage(NotFoundError):  # noqa: N818
    """No such page (or it is in the trash); the message is the key given."""


class NoSuchRevision(NotFoundError):  # noqa: N818
    """No such revision or batch; the message names it ("revision 9")."""


class ConflictError(Exception):
    """A page edit was based on an older revision."""


class TooLargeError(Exception):
    """An upload is over the size limit."""


class InvalidError(Exception):
    """A request is malformed."""
