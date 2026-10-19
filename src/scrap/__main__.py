"""Interface for ``python -m scrap``."""

import os
from argparse import ArgumentParser
from collections.abc import Sequence
from pathlib import Path

from . import __version__

__all__ = ["main"]


def main(args: Sequence[str] | None = None) -> None:
    """Argument parser for the CLI."""
    parser = ArgumentParser()
    parser.add_argument(
        "-v",
        "--version",
        action="version",
        version=__version__,
    )
    common = ArgumentParser(add_help=False)
    common.add_argument(
        "--data-dir", type=Path, help="Data folder (default $SCRAP_DATA_DIR or ./data)"
    )
    subparsers = parser.add_subparsers(dest="command")
    serve = subparsers.add_parser(
        "serve", parents=[common], help="Run the scrap web service"
    )
    serve.add_argument("--host", default="127.0.0.1", help="Address to bind")
    serve.add_argument("--port", type=int, default=8000, help="Port to listen on")
    for name, text in [
        ("backup", "Copy the database and files to DIR (safe while serving)"),
        ("restore", "Restore a backup from DIR into an empty data folder"),
        ("export", "Write the pages to DIR as Markdown with their files"),
    ]:
        sub = subparsers.add_parser(name, parents=[common], help=text)
        sub.add_argument("dir", type=Path)
        if name == "restore":
            sub.add_argument(
                "--force",
                action="store_true",
                help="Replace the whole database (pages added since the backup are"
                " lost; files are kept). Stop scrap first: a running server would"
                " go on writing to the old, replaced database and lose those writes",
            )
    parsed = parser.parse_args(args)

    if parsed.command == "serve":
        import uvicorn

        if parsed.data_dir:
            os.environ["SCRAP_DATA_DIR"] = str(parsed.data_dir)
        uvicorn.run(
            "scrap.app:create_app", factory=True, host=parsed.host, port=parsed.port
        )
    elif parsed.command:
        from . import backup
        from .store import Store

        store = Store(parsed.data_dir or os.environ.get("SCRAP_DATA_DIR", "data"))
        if parsed.command == "backup":
            backup.backup(store, parsed.dir)
        elif parsed.command == "restore":
            backup.restore(parsed.dir, store, parsed.force)
        else:
            print(f"exported {backup.export(store, parsed.dir)} pages to {parsed.dir}")
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
