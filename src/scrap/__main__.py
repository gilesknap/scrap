"""Interface for ``python -m scrap``."""

import os
from argparse import ArgumentParser
from collections.abc import Sequence
from pathlib import Path
from typing import Any

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
    serve.add_argument("--host", help="Address to bind (default 127.0.0.1)")
    serve.add_argument("--port", type=int, help="Port to listen on (default 8000)")
    serve.add_argument(
        "--uds",
        type=Path,
        help="Listen only on this Unix socket (mode 600) instead of TCP. Its folder"
        " must be yours and closed to others (it is made mode 700 if missing); a"
        " socket left by an earlier run is replaced. Not with --host or --port",
    )
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
    gc = subparsers.add_parser(
        "gc",
        parents=[common],
        help="Find the stored files nothing uses any more (no page, trashed ones too,"
        " capture, Claude result or model run), and gather capture files no page shows"
        " onto the month's Orphaned assets page; a dry run unless --delete",
    )
    gc.add_argument(
        "--delete",
        action="store_true",
        help="Delete them and gather the orphans (default: only count them)",
    )
    gc.add_argument(
        "--dry-run",
        action="store_true",
        help="Only count them, delete nothing (the default; overrides --delete)",
    )
    gc.add_argument(
        "--grace-hours",
        type=float,
        default=24.0,
        help="Keep files younger than this, used or not: an upload may be on its way"
        " (default 24)",
    )
    gc.add_argument(
        "--run-days",
        type=float,
        default=30.0,
        help="Keep model and enrich run records younger than this many days (at least"
        " 1); older ones are deleted unless something refers to them or they are the"
        " latest for their page (default 30)",
    )
    once = subparsers.add_parser(
        "ingest-once",
        help="Send one image to Claude as ingest would (no database) and print the"
        " outcome in numbers; needs ANTHROPIC_API_KEY, or CLAUDE_CODE_OAUTH_TOKEN"
        " with SCRAP_LLM_BACKEND=cli",
    )
    once.add_argument("image", type=Path)
    once.add_argument(
        "--save",
        type=Path,
        help="Also write the full result, with all the text Claude read from the"
        " image, to this new file (mode 600; an existing file is refused)",
    )
    enr = subparsers.add_parser(
        "enrich",
        parents=[common],
        help="Queue pages for Claude to tag, summarise and link (the service's worker"
        " runs them, within the daily budget)",
    )
    enr.add_argument(
        "--backfill",
        action="store_true",
        help="Queue every page with no tags that Claude has not read yet",
    )
    enr.add_argument(
        "--related",
        action="store_true",
        help="Pick related pages, here and now, for every page changed since its last"
        " picks (the nightly pass; stops at a queue pause or the day's budget)",
    )
    enr.add_argument(
        "--writeups",
        action="store_true",
        help="Write Claude's write-up, here and now, for every whiteboard or diagram"
        " page with none (stops at a queue pause or the day's budget)",
    )
    enr.add_argument(
        "--outdated",
        action="store_true",
        help="With --writeups: instead, write again each write-up that is outdated (a"
        " board photo read, or the page's text, title, kind or tags changed, since it"
        " was made, or an older prompt; never one the owner restored), as after a"
        " prompt change",
    )
    enr.add_argument(
        "--topics",
        action="store_true",
        help="Find topics, here and now (one call over every page: new topics are"
        " made, sources added), then queue a synthesis for each topic due (the"
        " weekly pass; stops at a queue pause or the day's budget). With --dry-run"
        " the call is made and its proposals printed, but nothing is written",
    )
    enr.add_argument(
        "--all",
        action="store_true",
        help="With --related: every page, changed or not; with --writeups: every"
        " board page, written up or not; with --topics: every topic's synthesis",
    )
    enr.add_argument(
        "--limit",
        type=int,
        help="At most this many pages (with --topics: syntheses queued)",
    )
    enr.add_argument(
        "--dry-run",
        action="store_true",
        help="Only count them, queue nothing (with --topics: the discovery call is"
        " still made, and paid for)",
    )
    parsed = parser.parse_args(args)

    if parsed.command == "ingest-once":
        import json

        from .ingest import once as ingest_once

        print(json.dumps(ingest_once(parsed.image, parsed.save), indent=1))
        return

    if parsed.command == "serve":
        import uvicorn

        tcp = parsed.host is not None or parsed.port is not None
        if parsed.uds is not None and tcp:
            parser.error("serve: --uds listens on a socket only; drop --host/--port")
        if parsed.data_dir:
            os.environ["SCRAP_DATA_DIR"] = str(parsed.data_dir)
        if parsed.uds is None:
            uvicorn.run(
                "scrap.app:create_app",
                factory=True,
                host="127.0.0.1" if parsed.host is None else parsed.host,
                port=8000 if parsed.port is None else parsed.port,
            )
            return
        from .uds import UdsError, bind

        try:
            sock = bind(parsed.uds)
        except UdsError as error:
            raise SystemExit(f"scrap serve: {error}") from None
        # Bound here, not by uvicorn, which would leave the socket mode 666. It is
        # left behind on stop and replaced by the next start.
        config = uvicorn.Config("scrap.app:create_app", factory=True)
        uvicorn.Server(config).run(sockets=[sock])
    elif parsed.command:
        from . import backup
        from .store import Store

        store = Store(parsed.data_dir or os.environ.get("SCRAP_DATA_DIR", "data"))
        if parsed.command == "gc":
            from .gc import GcError, collect

            try:
                report = collect(
                    store,
                    parsed.delete and not parsed.dry_run,
                    parsed.grace_hours,
                    parsed.run_days,
                )
            except GcError as error:
                raise SystemExit(f"scrap gc: {error}") from None
            print(report.text())
        elif parsed.command == "import":
            from . import importer

            if not parsed.dir.is_dir():
                raise SystemExit(f"no folder {parsed.dir}")
            plan = importer.plan(parsed.dir, store)
            print(importer.report(plan, details=parsed.dry_run))
            if not parsed.dry_run:
                n = importer.run(store, plan, ingest=parsed.ingest)
                print(f"imported {n} pages into {store.dir} (--dry-run lists problems)")
        elif parsed.command == "enrich":
            from . import claude_cli
            from .enrich import backfill, related_pass, writeup_pass
            from .store import enrich_on

            asked = [parsed.backfill, parsed.related, parsed.writeups, parsed.topics]
            if asked.count(True) != 1:
                parser.error(
                    "enrich: say --backfill, --related, --writeups or --topics"
                )
            if parsed.outdated and not parsed.writeups:
                parser.error("enrich: --outdated goes with --writeups")
            store.migrate()
            # made here, not queued
            calls = parsed.related or parsed.writeups or parsed.topics
            if calls and not (
                enrich_on() and claude_cli.configured()
            ):  # nothing to do, and not a failure (the nightly timer runs anyway)
                what = (
                    "related pages" if parsed.related
                    else "write-ups" if parsed.writeups else "topics"
                )  # fmt: skip
                print(
                    f"{what}: Claude enrichment is off (needs SCRAP_INGEST=on"
                    " and ANTHROPIC_API_KEY, or CLAUDE_CODE_OAUTH_TOKEN with"
                    " SCRAP_LLM_BACKEND=cli; SCRAP_ENRICH not off); nothing done"
                )
            elif parsed.topics:
                topics_report(store, parsed.all, parsed.limit, parsed.dry_run)
            elif parsed.writeups:
                c = writeup_pass(store, None, parsed.all, parsed.limit, parsed.dry_run,
                                 parsed.outdated)  # fmt: skip
                if parsed.dry_run:
                    print(f"would write up {c['pages']} board pages")
                else:
                    print(f"write-ups made for {c['done']} of {c['pages']} board pages,"
                          f" {c['failed']} failed (scrap enrich --related picks"
                          " their related pages again)")  # fmt: skip
                    if c["stopped"]:
                        raise SystemExit(
                            f"stopped: the queue is paused ({c['stopped']})"
                        )
            elif parsed.related:
                c = related_pass(store, None, parsed.all, parsed.limit, parsed.dry_run)
                if parsed.dry_run:
                    print(f"would pick related pages for {c['pages']} pages")
                else:
                    print(f"related pages picked for {c['done']} of {c['pages']} pages,"
                          f" {c['failed']} failed")  # fmt: skip
                    if c["stopped"]:
                        raise SystemExit(
                            f"stopped: the queue is paused ({c['stopped']})"
                        )
            else:
                n = backfill(store, parsed.limit, parsed.dry_run)
                verb = "would queue" if parsed.dry_run else "queued"
                print(f"{verb} {n} untagged pages for Claude")
        elif parsed.command == "backup":
            backup.backup(store, parsed.dir)
        elif parsed.command == "restore":
            backup.restore(parsed.dir, store, parsed.force)
        else:
            print(f"exported {backup.export(store, parsed.dir)} pages to {parsed.dir}")
    else:
        parser.print_help()


def topics_report(store: Any, every: bool, limit: int | None, dry_run: bool) -> None:
    """scrap enrich --topics: the pass, and what it found or would make printed."""
    from .enrich import topics_pass

    c = topics_pass(store, None, every, limit, dry_run)
    made = "would make" if dry_run else "made"
    for t in c["new"]:
        names = "; ".join(s["title"] for s in t["sources"])
        print(f"{made} topic {t['title']!r} ({t['key']}) from: {names}")
    for a in c["add"]:
        names = "; ".join(s["title"] for s in a["sources"])
        print(f"{'would add' if dry_run else 'added'} to {a['title']!r}: {names}")
    queued = "would queue" if dry_run else "queued"
    print(f"topics: {len(c['new'])} new, {len(c['add'])} with new sources;"
          f" {queued} {c['queued']} syntheses")  # fmt: skip
    if c["stopped"]:
        raise SystemExit(f"stopped: the queue is paused ({c['stopped']})")
    if c["failed"]:
        raise SystemExit("topic discovery failed (see its topic_run)")


if __name__ == "__main__":
    main()
