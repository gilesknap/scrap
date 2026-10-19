"""The scrap web application."""

from fastapi import FastAPI

from . import __version__

__all__ = ["create_app"]


def create_app() -> FastAPI:
    """Build the scrap FastAPI application."""
    app = FastAPI(title="scrap", version=__version__)

    @app.get("/healthz")
    def healthz() -> dict[str, str]:
        """Liveness check: the process is up and serving requests."""
        return {"status": "ok", "version": __version__}

    return app
