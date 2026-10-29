"""scrap import: Markdown pages with YAML front matter, from a folder or a zip (scrap's
own export, or an Obsidian vault).

Each page becomes a scrap page with its kind, fields, tags and dates, and the tag
import/<date>; links between pages become `[[slug|label]]` links (a link that names
its page's slug already is kept as it is) and the files its pages embed or link become
the page's, shown inline. `_`- and `.`-prefixed folders are not read: a scrap export's
`_claude/` (what a model wrote) never becomes a page's text. Nothing is overwritten. See
docs/how-to/import-and-export.md.
"""

from .cost import per_page, per_photo
from .model import Plan
from .pipeline import Done, import_tag, plan, report, run, summary
from .sources import RefusedError, Source, source

__all__ = [
    "Done",
    "Plan",
    "RefusedError",
    "Source",
    "import_tag",
    "per_page",
    "per_photo",
    "plan",
    "report",
    "run",
    "source",
    "summary",
]
