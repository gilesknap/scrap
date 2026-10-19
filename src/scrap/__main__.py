"""Interface for ``python -m scrap``."""

from argparse import ArgumentParser
from collections.abc import Sequence

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
    subparsers = parser.add_subparsers(dest="command")
    serve = subparsers.add_parser("serve", help="Run the scrap web service")
    serve.add_argument("--host", default="127.0.0.1", help="Address to bind")
    serve.add_argument("--port", type=int, default=8000, help="Port to listen on")
    parsed = parser.parse_args(args)

    if parsed.command == "serve":
        import uvicorn

        uvicorn.run(
            "scrap.app:create_app", factory=True, host=parsed.host, port=parsed.port
        )
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
