"""The Unix socket ``scrap serve --uds`` listens on (ADR 0018).

Only this user (and root) may connect: the socket is mode 600 in a folder that is
this user's own and closed to everyone else.
"""

import os
import socket
import stat
from pathlib import Path

__all__ = ["UdsError", "bind"]


class UdsError(Exception):
    """The socket cannot be made safely; nothing was changed."""


def bind(path: Path) -> socket.socket:
    """A listening socket at ``path``, mode 600, replacing a stale one."""
    folder = path.parent
    try:
        folder.mkdir(mode=0o700, parents=True)
    except FileExistsError:
        pass
    info = folder.lstat()
    if not stat.S_ISDIR(info.st_mode):
        raise UdsError(f"{folder} is not a folder")
    if info.st_uid != os.geteuid():
        raise UdsError(f"{folder} belongs to another user; use a folder of your own")
    if info.st_mode & 0o077:
        raise UdsError(
            f"{folder} is open to other users (mode {stat.S_IMODE(info.st_mode):o});"
            " chmod 700 it or use a folder of its own"
        )
    try:
        old = path.lstat()
    except FileNotFoundError:
        pass
    else:
        if not stat.S_ISSOCK(old.st_mode):
            raise UdsError(f"{path} exists and is not a socket; not removing it")
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as probe:
            try:
                probe.connect(str(path))
            except OSError:
                pass
            else:
                raise UdsError(f"{path} is in use: is scrap already running?")
        path.unlink()  # left by an earlier run that did not stop cleanly
    sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    old_umask = os.umask(0o177)
    try:
        sock.bind(str(path))
    except OSError:
        sock.close()
        raise
    finally:
        os.umask(old_umask)
    os.chmod(path, 0o600)
    sock.listen(2048)  # uvicorn's default backlog
    return sock
