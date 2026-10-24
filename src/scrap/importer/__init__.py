"""scrap import: a Thoth vault (Obsidian-style Markdown with YAML front matter).

Each content page becomes a scrap page with its kind, fields, tags and dates; links
between pages become ``[[slug|label]]`` links and the images its pages embed become
the page's photos, shown inline. raw/ and inbox/ are dropped, so are index, log and
SCHEMA pages, and anything else that is not a page. See docs/how-to/import-a-vault.md.
"""

from .model import Plan
from .pipeline import plan, report, run

__all__ = ["plan", "run", "report", "Plan"]
