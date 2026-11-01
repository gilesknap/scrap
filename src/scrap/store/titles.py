"""The titles of the pages a text links to (#508): a page link with no label of its
own shows its page's title, in the PWA (the page's `titles`), downloads and exports.
Read when the page is, so a page renamed since shows its current title."""

import json
import re
import sqlite3

from ..markdown import wiki_targets
from ..public import public_origins

# A page's address anywhere in a text, on any origin: the PWA also links a bare one
# (linkified, which the server's parser doesn't) on the origin it was loaded from
ADDRESS = re.compile(r"/p/([a-z0-9-]+)(?![a-z0-9-])")


def titles(conn: sqlite3.Connection, text: str) -> dict[str, str]:
    """Slug to title for each page (not in the trash) that text links to: [[slug]],
    [[slug|label]] or its address (markdown.wiki_targets), and any page address in
    it (ADDRESS: the PWA decides which are links). A dangling link has none."""
    slugs = wiki_targets(text, public_origins())
    if "/p/" in text:
        slugs = list(dict.fromkeys([*slugs, *ADDRESS.findall(text)]))
    if not slugs:
        return {}
    return dict(
        conn.execute(
            "SELECT slug, title FROM page WHERE deleted_at IS NULL"
            " AND slug IN (SELECT value FROM json_each(?))",
            (json.dumps(slugs),),
        ).fetchall()
    )
