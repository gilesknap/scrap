"""Interface for ``python -m scrap``."""

import os
from argparse import ArgumentParser, ArgumentTypeError
from collections.abc import Sequence
from pathlib import Path

from . import __version__

__all__ = ["main"]


def month_arg(value: str) -> str:
    """A month as YYYY-MM."""
    import re

    if not re.fullmatch(r"\d{4}-(0[1-9]|1[0-2])", value):
        raise ArgumentTypeError(f"not a month (YYYY-MM): {value!r}")
    return value


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
    imp = subparsers.add_parser(
        "import",
        parents=[common],
        help="Import a Thoth vault (Markdown pages with YAML front matter) from DIR",
    )
    imp.add_argument("dir", type=Path)
    imp.add_argument(
        "--dry-run",
        action="store_true",
        help="Write nothing; list what would be imported and every problem found",
    )
    imp.add_argument(
        "--ingest",
        action="store_true",
        help="Also queue the imported images for Claude (off: their pages describe"
        " them already)",
    )
    once = subparsers.add_parser(
        "ingest-once",
        help="Send one image to Claude as ingest would (no database) and print the"
        " outcome in numbers; needs ANTHROPIC_API_KEY",
    )
    once.add_argument("image", type=Path)
    once.add_argument(
        "--save",
        type=Path,
        help="Also write the full result, with all the text Claude read from the"
        " image, to this new file (mode 600; an existing file is refused)",
    )
    spending = subparsers.add_parser(
        "spend",
        parents=[common],
        help="Print Claude spend for a month (UTC) by day and model, and the cap",
    )
    spending.add_argument(
        "--month", help="YYYY-MM (default: this month)", type=month_arg
    )
    parsed = parser.parse_args(args)

    if parsed.command == "ingest-once":
        import json

        from .ingest import once as ingest_once

        print(json.dumps(ingest_once(parsed.image, parsed.save), indent=1))
        return

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
        if parsed.command == "spend":
            from . import spend
            from .store import connect, now

            if not store.db.exists():
                raise SystemExit(f"no database at {store.db}")
            conn = connect(store.db)
            try:
                if conn.execute("PRAGMA user_version").fetchone()[0] < 4:
                    raise SystemExit("this database has no spend ledger yet: run serve")
                print(spend.report(conn, parsed.month or now()[:7]))
            finally:
                conn.close()
        elif parsed.command == "import":
            from . import importer

            if not parsed.dir.is_dir():
                raise SystemExit(f"no folder {parsed.dir}")
            plan = importer.plan(parsed.dir, store)
            print(importer.report(plan, details=parsed.dry_run))
            if not parsed.dry_run:
                n = importer.run(store, plan, ingest=parsed.ingest)
                print(f"imported {n} pages into {store.dir} (--dry-run lists problems)")
        elif parsed.command == "backup":
            backup.backup(store, parsed.dir)
        elif parsed.command == "restore":
            backup.restore(parsed.dir, store, parsed.force)
        else:
            print(f"exported {backup.export(store, parsed.dir)} pages to {parsed.dir}")
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
