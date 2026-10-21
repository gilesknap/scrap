"""The Unix socket ``scrap serve --uds`` listens on (ADR 0018).

Only this user (and root) may connect: the socket is mode 600 in a folder that is
this user's own and closed to everyone else.
"""

import fcntl
import os
import socket
import stat
from pathlib import Path

__all__ = ["UdsError", "bind"]


class UdsError(Exception):
    """The socket cannot be made safely, or at all. No socket was removed unless it
    was stale, and none was made."""


# sun_path holds 108 bytes, including the terminating NUL
MAX_PATH_BYTES = 107


def bind(path: Path) -> socket.socket:
    """A listening socket at ``path``, mode 600, replacing a stale one."""
    if len(os.fsencode(path)) > MAX_PATH_BYTES:
        raise UdsError(
            f"{path} is longer than {MAX_PATH_BYTES} bytes; use a shorter path"
        )
    folder = path.parent
    try:
        folder.mkdir(mode=0o700, parents=True)
    except FileExistsError:
        pass
    except OSError as error:
        raise UdsError(f"cannot make {folder}: {error.strerror}") from None
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
    # Held from the stale check until the new socket listens, so two starts at once
    # cannot both replace the path and leave one of them unreachable.
    lock = os.open(folder / f".{path.name}.lock", os.O_RDWR | os.O_CREAT, 0o600)
    try:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise UdsError(f"{path} is being set up by another process") from None
        _remove_stale(path)
        return _listen(path)
    finally:
        os.close(lock)


def _remove_stale(path: Path) -> None:
    """Remove a socket at ``path`` that nothing listens on; refuse anything else."""
    try:
        old = path.lstat()
    except FileNotFoundError:
        return
    if not stat.S_ISSOCK(old.st_mode):
        raise UdsError(f"{path} exists and is not a socket; not removing it")
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as probe:
        probe.settimeout(1)  # a listener with a full queue would block forever
        try:
            probe.connect(str(path))
        except (ConnectionRefusedError, FileNotFoundError):
            pass  # nobody listens: left by an earlier run that did not stop cleanly
        except OSError as error:  # busy, timed out, ...: maybe alive, so keep it
            raise UdsError(f"{path} may be in use ({error}); not removing it") from None
        else:
            raise UdsError(f"{path} is in use: is scrap already running?")
    path.unlink(missing_ok=True)


def _listen(path: Path) -> socket.socket:
    sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    old_umask = os.umask(0o177)
    try:
        sock.bind(str(path))
    except OSError as error:
        sock.close()
        raise UdsError(f"cannot listen on {path}: {error.strerror}") from None
    finally:
        os.umask(old_umask)
    os.chmod(path, 0o600)
    sock.listen(2048)  # uvicorn's default backlog
    return sock
