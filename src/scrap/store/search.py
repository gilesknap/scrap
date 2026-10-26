"""Reading many pages at once: tags, images, backlinks, search."""

import html
import json
import sqlite3
from collections import Counter
from datetime import date
from typing import Any

from ..markdown import plain
from ..query import (
    CONTROL,
    MEDIA,
    SUBTYPES,
    Query,
    bound,
    due,
)
from .constants import (
    CLAUDE,
    GONE,
    HAS,
    IMAGE_KIND,
    KIND_NAMES,
    MCP,
    PRIORITY_NAMES,
    RANK,
    SORT_SQL,
    THUMB,
    TODO_SQL,
    WEIGHTS,
)
from .core import Core
from .db import _rows
from .grouping import order as group_order
from .health import CHECKS, condition
from .helpers import checked_query, tag_counts, todo_only, unlink
from .topics import IS_TOPIC

# media:M and later:T filter by a Later's medium and what it is for: the column of
# its fields, and the values it takes. A Later with no subtype is to read.
LATER = {
    "media": ("json_extract(p.fields, '$.media_type')", MEDIA),
    "later": (
        "CASE WHEN p.kind = 'consume' THEN"
        " coalesce(json_extract(p.fields, '$.subtype'), 'read') END",
        SUBTYPES,
    ),
}


class SearchMixin(Core):
    def tags_of(self, ids: list[str]) -> dict[str, list[str]]:
        """Each page's tags, most used first: for list rows, which lack them."""
        out: dict[str, list[str]] = {page_id: [] for page_id in ids}
        with self.connect() as conn:
            for page_id, tag in conn.execute(
                "SELECT page_id, tag FROM tag WHERE page_id IN"
                " (SELECT value FROM json_each(?)) ORDER BY"
                " (SELECT count(*) FROM tag t WHERE t.tag = tag.tag) DESC, tag",
                (json.dumps(ids),),
            ):
                out[page_id].append(tag)
        return out

    def images_of(self, ids: list[str]) -> dict[str, dict[str, Any]]:
        """Each page's images, for list rows: how many (distinct image files of its
        captures, one per SHA-256, not those whose embed was deleted: GONE) and its
        first one's SHA-256 and what Claude made of it
        (its current description and kind; None if not read yet). A page with none is
        left out."""
        out: dict[str, dict[str, Any]] = {}
        with self.connect() as conn:
            for row in conn.execute(
                "WITH once AS (SELECT c.page_id, c.id AS capture_id, cb.sha256,"
                " c.received_at, cb.ord, row_number() OVER (PARTITION BY c.page_id,"
                "  cb.sha256 ORDER BY c.received_at, cb.ord) AS copy"  # the same file
                " FROM capture c JOIN capture_blob cb ON cb.capture_id = c.id"  # again
                " JOIN blob b USING (sha256) JOIN page p ON p.id = c.page_id"
                " WHERE b.mime LIKE 'image/%'"
                f" AND NOT {GONE.format(p='p', sha='cb.sha256')}"  # embed deleted
                " AND c.page_id IN (SELECT value FROM json_each(?))),"
                " image AS (SELECT page_id, capture_id, sha256,"
                " row_number() OVER (PARTITION BY page_id"
                "  ORDER BY received_at, ord) AS n,"
                " count(*) OVER (PARTITION BY page_id) AS total"
                " FROM once WHERE copy = 1)"
                " SELECT i.page_id, i.total, i.sha256, d.text,"
                " json_extract(d.data, '$.kind') FROM image i LEFT JOIN derived d"
                " ON d.capture_id = i.capture_id AND d.source_sha256 = i.sha256"
                " AND d.kind = 'description' AND d.superseded_at IS NULL"
                " WHERE i.n = 1",
                (json.dumps(ids),),
            ):
                out[row[0]] = {
                    "count": row[1], "sha256": row[2], "description": row[3],
                    "image_kind": row[4],
                }  # fmt: skip
        return out

    def backlinks(self, slug: str) -> list[dict[str, str]]:
        """The pages (not in the trash) whose text links to slug: [[slug]], or its
        /p/ address (SQL wiki_links). Only texts holding the slug as typed are parsed
        (instr), so a link whose slug is written escaped (`&#97;`, `\\-`) is missed,
        though has:dangling and is:orphan, which parse every text, count it."""
        with self.connect() as conn:
            return [
                {k: r[k] for k in ("id", "slug", "title")}
                for r in self._backlinks(conn, slug)
            ]

    def _backlinks(self, conn: sqlite3.Connection, slug: str) -> list[dict[str, str]]:
        return _rows(
            conn,
            "SELECT id, slug, title, kind FROM page WHERE deleted_at IS NULL"
            " AND slug <> ? AND instr(body, ?) > 0 AND EXISTS (SELECT 1 FROM"
            " json_each(wiki_links(body)) l WHERE l.value = ?)"
            " ORDER BY updated_at DESC",
            slug, slug, slug,
        )  # fmt: skip

    def search(self, query: str, limit: int, offset: int = 0) -> list[dict[str, Any]]:
        """Pages matching a query (see scrap.query): every word somewhere in the page
        (its title, tags, summary, body, or a photo's text or description; each
        word as a prefix), no NOT word anywhere, and all the filters. Ranked by bm25 of
        the page's best chunk, title, tag and summary matches weighing most, a
        topic page (#261: is:topic lists them) first within the title tier and the
        title, tags and summary tier; a query
        of filters alone lists its pages newest first; sort: orders either its own
        way, and group: puts the pages in their sections first (grouping.py), each page
        with its tags. offset: skip that many hits (the next page of results)."""
        q = checked_query(query)
        if not q.terms and not q.filters:
            return []
        where, args = self._where(q)
        # sort: first, then the default order (a page's chunks share its sort key, so
        # its best chunk still comes first). Pages with no due date or priority last.
        order = ""
        sort = q.sort or (("title", False) if q.group == "letter" else None)  # A-Z
        if sort:
            key, desc = sort
            way = "DESC" if desc else "ASC"
            order = f"{SORT_SQL[key]} {way} NULLS LAST, p.id {way}, "
        sections, section_args = group_order(q)  # group: first of all
        order = sections + order
        hits: dict[str, dict[str, Any]] = {}  # a page once, at its best chunk
        with self.connect() as conn:
            if q.positive:  # bm25() and snippet() refuse GROUP BY: group here instead
                # First the pages with every word in the title, then those with every
                # word in the title, tags or summary: bm25 alone lets a short body
                # that says a word twice beat a long page tagged with it. Within
                # each of those tiers a topic page comes first (it gathers the
                # others); one matching only in its synthesis or text does not.
                every = " AND ".join(q.fts(t) for t in q.positive)
                topic = IS_TOPIC.format(p="p")
                tier = " c.id IN (SELECT rowid FROM chunk_fts WHERE chunk_fts MATCH ?)"
                rows = conn.execute(
                    "SELECT p.id, p.slug, p.title, p.kind, p.fields, p.due, p.priority,"
                    " p.snoozed_until, p.task_done, p.task_total,"
                    " snippet(chunk_fts, 3, char(2), char(3), '…', 16) AS snippet"
                    " FROM chunk_fts JOIN chunk c ON c.id = chunk_fts.rowid"
                    " JOIN page p ON p.id = c.page_id"
                    f" WHERE chunk_fts MATCH ? AND {where}"
                    f" ORDER BY {order}({topic} AND {tier}) DESC, {tier} DESC,"
                    f" ({topic} AND {tier}) DESC, {tier} DESC,"
                    f" bm25(chunk_fts, {WEIGHTS}), c.id",
                    (" OR ".join(q.fts(t) for t in q.positive), *args, *section_args,
                     f"title : ({every})", f"title : ({every})",
                     f"{{title tags summary}} : ({every})",
                     f"{{title tags summary}} : ({every})"),
                )  # fmt: skip
            else:
                rows = conn.execute(
                    "SELECT p.id, p.slug, p.title, p.kind, p.fields, p.due, p.priority,"
                    " p.snoozed_until, p.task_done, p.task_total, p.body AS snippet"
                    f" FROM page p WHERE {where}"
                    f" ORDER BY {order}p.updated_at DESC, p.id DESC LIMIT ? OFFSET ?",
                    (*args, *section_args, limit, offset),
                )
                offset = 0  # done by SQL
            for row in rows:
                hits.setdefault(row["id"], dict(row))
                if len(hits) == offset + limit:
                    break
            hits = dict(list(hits.items())[offset:])
            # Each hit's thumbnail and last edit, as /api/pages has them: one query
            for row in conn.execute(
                f"SELECT p.id, p.updated_at, {THUMB} AS thumb FROM page p"
                " WHERE p.id IN (SELECT value FROM json_each(?))",
                (json.dumps(list(hits)),),
            ):
                hits[row["id"]] |= {"updated_at": row[1], "thumb": row[2]}
        for page_id, tags in self.tags_of(list(hits)).items():  # for group:tag
            hits[page_id]["tags"] = tags
        for hit in hits.values():  # HTML-safe, with matches in <mark>
            hit["fields"] = json.loads(hit["fields"])
            todo_only(hit)
            if not q.positive:  # no match to show: its summary, else its start
                summary = hit["fields"].get("summary")
                text = (
                    summary
                    if isinstance(summary, str)
                    else plain(unlink(hit["snippet"][:2000]))
                )
                hit["snippet"] = " ".join(CONTROL.sub(" ", text).split()[:24])
            snippet = html.escape(hit["snippet"])
            hit["snippet"] = snippet.replace("\x02", "<mark>").replace(
                "\x03", "</mark>"
            )
        return list(hits.values())

    def facets(self, query: str, top: int = 12) -> dict[str, Any]:
        """What the pages a query matches have in common, to narrow it with a tap: how
        many there are, their kinds, their most used tags (a/b counts for a too) and
        how many are personal or work; and the query's filters, as typed."""
        q = checked_query(query)
        out: dict[str, Any] = {
            "total": 0, "kinds": [], "tags": [], "personal": {"work": 0, "personal": 0},
            "active": [{"token": f.token, "key": f.key, "value": f.value, "neg": f.neg}
                       for f in q.filters],
        }  # fmt: skip
        if not q.terms and not q.filters:
            return out
        where, args = self._where(q)
        with self.connect() as conn:
            ids = json.dumps([r[0] for r in conn.execute(
                f"SELECT p.id FROM page p WHERE {where}", args
            )])  # fmt: skip
            pages = "(SELECT value FROM json_each(?))"
            out["kinds"] = [list(r) for r in conn.execute(
                f"SELECT kind, count(*) AS n FROM page WHERE id IN {pages}"
                " GROUP BY kind ORDER BY n DESC, kind", (ids,),
            )]  # fmt: skip
            personal = conn.execute(
                "SELECT count(*), coalesce(sum(json_extract(fields, '$.personal') = 1),"
                f" 0) FROM page WHERE id IN {pages}",
                (ids,),
            ).fetchone()
            tags = conn.execute(
                f"SELECT page_id, tag FROM tag WHERE page_id IN {pages}", (ids,)
            ).fetchall()
        total = personal[0]
        out["total"] = total
        out["personal"] = {"work": total - personal[1], "personal": personal[1]}
        counts = tag_counts(tags)
        chosen = [f.value for f in q.filters if f.key == "tag" and not f.neg]
        ranked = sorted(
            ((tag, n) for tag, n in counts.items()
             if tag not in chosen and (n < total or total == 1)),
            key=lambda t: (-t[1], t[0]),
        )  # fmt: skip
        out["tags"] = [list(t) for t in ranked[:top]]
        return out

    def tags(self) -> list[list[Any]]:
        """Every tag on a page (not in the trash), a/b's parent a too, with how many
        pages have it (a: those with a or a/anything) and how many have that very tag
        (0 for a parent nobody gave a page), in order."""
        with self.connect() as conn:
            rows = conn.execute(
                "SELECT page_id, tag FROM tag JOIN page p ON p.id = tag.page_id"
                " WHERE p.deleted_at IS NULL"
            ).fetchall()
        own = Counter(tag for _, tag in rows)
        return [[t, n, own[t]] for t, n in sorted(tag_counts(rows).items())]

    def _where(self, q: Query) -> tuple[str, list[Any]]:
        """SQL conditions on page p for a query's words and filters, and their args."""
        sql, args = ["p.deleted_at IS NULL"], []
        in_page = (
            "p.id {} IN (SELECT c.page_id FROM chunk_fts JOIN chunk c"
            " ON c.id = chunk_fts.rowid WHERE chunk_fts MATCH ?)"
        )
        for term in q.terms:
            sql.append(in_page.format("NOT" if term.neg else ""))
            args.append(q.fts(term))
        kinds = [KIND_NAMES.get(f.value, f.value) for f in q.filters
                 if f.key == "kind" and not f.neg]  # fmt: skip
        if kinds:  # a page has one kind: two kinds mean either
            sql.append("p.kind IN (SELECT value FROM json_each(?))")
            args.append(json.dumps(kinds))
        priorities = [f.value for f in q.filters if f.key == "priority" and not f.neg]
        if priorities:  # one each, as kinds: priority:high priority:medium is either
            sql.append(f"{TODO_SQL}{RANK} IN (SELECT value FROM json_each(?))")
            args.append(json.dumps([PRIORITY_NAMES.get(v, v) for v in priorities]))
        for key, (column, values) in LATER.items():  # a Later's: either of the positive
            asked = [f.value for f in q.filters if f.key == key and not f.neg]
            if asked:  # (a value that is none of the known ones finds nothing)
                sql.append(f"coalesce({column} IN (SELECT value FROM json_each(?)), 0)")
                args.append(json.dumps([v for v in asked if v in values]))
        dated = "created_at" if ("date", "created") in [
            (f.key, f.value) for f in q.filters if not f.neg
        ] else "updated_at"  # fmt: skip
        for f in q.filters:
            no = "NOT " if f.neg else ""
            if f.key in ("after", "before"):  # UTC: see query.bound
                cut = bound(f.key, f.value)
                op = ">=" if f.key == "after" else "<"
                # not a date or a time ago: nothing (and with -, everything)
                sql.append(f"{no}(p.{dated} {op} ?)" if cut else f"{no}0")
                args.extend([cut] if cut else [])
            elif f.key == "kind" and f.neg:
                sql.append("p.kind <> ?")
                args.append(KIND_NAMES.get(f.value, f.value))
            elif f.key == "tag" and not f.value.strip("/"):  # tag:/ is no tag
                sql.append(f"{no}0")
            elif f.key == "tag":  # whole segments: tag:b finds a/b, tag:a finds a/b
                sql.append(
                    f"{no}EXISTS (SELECT 1 FROM tag t WHERE t.page_id = p.id"
                    " AND instr('/' || t.tag || '/', ?) > 0)"
                )
                args.append(f"/{f.value.strip('/')}/")
            elif (f.key, f.value) in CHECKS:  # the store's health checks (#262)
                check, more = condition(f.key, f.value, self.prompts)
                sql.append(f"{no}({check})")
                args.extend(more)
            elif f.key == "has":  # has:image, has:drawing; any other value: nothing
                sql.append(f"{no}{HAS[f.value]}" if f.value in HAS else f"{no}0")
            elif f.key == "image":  # image:photo, image:whiteboard...
                sql.append(f"{no}{IMAGE_KIND}")
                args.append(f.value)
            elif f.key == "is" and f.value == "claude":  # written over MCP
                sql.append(
                    f"{no}EXISTS (SELECT 1 FROM capture c WHERE c.page_id = p.id"
                    " AND c.source = ?)"
                )
                args.append(MCP)
            elif f.key == "is" and f.value == "claude-edited":  # text changed by MCP
                # a text revision by Claude after the first: an edit_page, a
                # revert to a text revision, or an append to a page Claude wrote
                sql.append(
                    f"{no}EXISTS (SELECT 1 FROM page_rev r WHERE r.page_id = p.id"
                    " AND r.rev > 1 AND r.author = ?)"
                )
                args.append(CLAUDE)
            elif f.key == "is" and f.value == "topic":  # Claude's topic pages (#261)
                sql.append(f"{no}{IS_TOPIC.format(p='p')}")
            elif f.key == "is" and f.value == "snoozed":  # a todo hidden until later
                # An open one: a done or cancelled one's snooze hides nothing (#131)
                sql.append(
                    f"{no}coalesce({TODO_SQL}p.snoozed_until > ?"
                    " AND coalesce(json_extract(p.fields, '$.status'), 'open')"
                    " NOT IN ('done', 'cancelled'), 0)"
                )
                args.append(date.today().isoformat())  # the server's day, as due:'s
            elif f.key == "is" and f.value in ("personal", "work"):
                want = "IS 1" if f.value == "personal" else "IS NOT 1"
                sql.append(f"{no}(json_extract(p.fields, '$.personal') {want})")
            elif f.key in ("sort", "group"):  # an order, not a condition: see search()
                continue
            elif f.key in LATER and not f.neg:
                continue  # see above: either of them
            elif f.key in LATER:  # -media:book: a page of another medium (or none)
                sql.append(f"coalesce({LATER[f.key][0]} <> ?, 1)")
                args.append(f.value)
            elif f.key == "due":  # a todo's: due:<today, due:2026-11-01, due:none
                asked = due(f.value)
                if asked is None:  # not a day: nothing (and with -, everything)
                    sql.append(f"{no}0")
                elif asked[0] == "none":
                    sql.append(f"{no}coalesce({TODO_SQL}p.due IS NULL, 0)")
                else:  # the operator is one of query.COMPARE's
                    sql.append(f"{no}coalesce({TODO_SQL}p.due {asked[0]} ?, 0)")
                    args.append(asked[1])
            elif f.key == "priority" and f.neg:  # priority:none: a todo with none
                sql.append(f"NOT ({TODO_SQL}{RANK} = ?)")
                args.append(PRIORITY_NAMES.get(f.value, f.value))
            elif f.key == "priority":  # see above: either of them
                continue
            elif f.key == "is":  # a status: is:done, is:open...
                status = "coalesce(json_extract(p.fields, '$.status'), '')"
                sql.append(f"{no}({status} = ?)")
                args.append(f.value.replace(" ", "_"))
        return " AND ".join(sql), args
