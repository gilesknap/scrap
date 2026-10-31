"""The MCP server's tools (#232), one module per group; each register_* adds its
group's tools to the server, sharing the state in a Ctx. mcp_server.server builds
the Ctx and calls them in the order the tools are listed."""

from .browsing import register_browsing
from .context import Ctx
from .drawing import register_drawing
from .editing import register_editing
from .history import register_history
from .images import register_images
from .meta import register_meta
from .reading import register_reading
from .writeup import register_writeup
from .writing import register_writing

__all__ = [
    "Ctx",
    "register_browsing",
    "register_drawing",
    "register_editing",
    "register_history",
    "register_images",
    "register_meta",
    "register_reading",
    "register_writeup",
    "register_writing",
]
