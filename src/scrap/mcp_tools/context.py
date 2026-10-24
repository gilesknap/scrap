"""The state and helpers the tool groups share: one Ctx per server."""

import hashlib
import html
from typing import Any

from mcp.server.mcpserver.exceptions import ToolError

from ..store import (
    CROCKFORD,
    ConflictError,
    InvalidError,
    NoSuchRevision,
    NotFoundError,
    Store,
)
from .limits import MARK, MAX_BODY
from .textdiff import unified


def key_id(key: str, target: str = "") -> str:
    """A capture id (ULID-shaped) from a client's idempotency key and the id of the
    page appended to ("" for a new page): the same key and target are the same
    capture, so a retried write adds nothing, while a key reused for another target
    is a different capture rather than a silent no-op."""
    seed = key.encode() + (b"\0" + target.encode() if target else b"")
    n = int.from_bytes(hashlib.sha256(b"scrap-mcp\0" + seed).digest()[:16])
    return "".join(CROCKFORD[(n >> shift) & 31] for shift in range(125, -1, -5))


def text(value: str, name: str) -> str:
    """Refuse text that cannot be stored or served: a lone surrogate, or NUL."""
    try:
        value.encode()
    except UnicodeEncodeError:
        raise ToolError(f"{name} must be valid Unicode (a lone surrogate)") from None
    if "\x00" in value:
        raise ToolError(f"{name} must not hold NUL characters")
    return value


def drawing_info(d: dict[str, Any] | None) -> dict[str, Any] | None:
    """The small drawing object read gives an image: null if it has none."""
    if not d:
        return None
    keys = ("version", "producer", "width", "height", "element_count")
    return {k: d.get(k) for k in keys}


class Ctx:
    """What the tools of every group share: the store, the base URL page links are
    made on and whether the text-editing tools are served, and the helpers that
    shape a tool's result or turn a store error into a ToolError."""

    def __init__(self, store: Store, base: str, editable: bool) -> None:
        self.store = store
        self.base = base
        self.editable = editable

    def link(self, slug: str) -> str:
        return f"{self.base}/p/{slug}"

    def row(
        self, hit: dict[str, Any], tags: list[str], image: dict[str, Any] | None
    ) -> dict[str, Any]:
        out = {
            "id": hit["id"],
            "slug": hit["slug"],
            "url": self.link(hit["slug"]),
            "kind": hit["kind"],
            "status": hit["fields"].get("status"),
            "due": hit.get("due"),  # a todo's (YYYY-MM-DD), else None
            "priority": hit.get("priority"),  # a todo's: high, medium, low; else None
            "snoozed_until": hit.get("snoozed_until"),  # a todo's, hidden till then
            "tasks": hit.get("tasks"),  # its task boxes: {done, total}
            "updated_at": hit["updated_at"],
            "tags": tags,
            "title": hit["title"],
        }
        if "snippet" in hit:  # HTML-escaped with <mark>: plain text here
            out["snippet"] = html.unescape(MARK.sub("", hit["snippet"]))
        # Its images: how many, and what Claude made of the first (a photo page's
        # body is only an embed, so this is often all there is to go on)
        out["image_count"] = image["count"] if image else 0
        if image:
            out |= {
                "image_kind": image["image_kind"],
                "image_description": image["description"],
                "image_url": f"{self.base}/api/blobs/{image['sha256']}",
                "thumbnail_url": f"{self.base}/api/blobs/{image['sha256']}"
                "/preview?size=480",
            }
        return out

    def rows(self, hits: list[dict[str, Any]]) -> list[dict[str, Any]]:
        ids = [h["id"] for h in hits]
        tags, images = self.store.tags_of(ids), self.store.images_of(ids)
        return [self.row(h, tags[h["id"]], images.get(h["id"])) for h in hits]

    @staticmethod
    def checked(call, *args, **kwargs):
        try:
            return call(*args, **kwargs)
        except NotFoundError as e:
            if isinstance(e, NoSuchRevision):
                raise ToolError(f"no such {e}") from None
            raise ToolError(f"no such page: {e}") from None
        except InvalidError as e:
            raise ToolError(str(e)) from None
        except ConflictError as e:
            raise ToolError(
                f"the page has changed: it is at rev {e}, not the rev given; read it"
                " again (nothing was saved)"
            ) from None

    def changes(self, found: dict[str, Any], dry_run: bool) -> dict[str, Any]:
        pages = [{**c, "url": self.link(c["slug"])} for c in found["pages"]]
        return {
            "dry_run": dry_run, "batch": found["batch"], "matched": len(pages),
            "changed": sum(c["changed"] for c in pages), "pages": pages,
        }  # fmt: skip

    def tag_list(self, tags: list[str], name: str) -> list[str]:
        return [text(t, name) for t in tags]

    def edited(
        self, found: dict[str, Any], dry_run: bool, **extra: Any
    ) -> dict[str, Any]:
        diff, cut = unified(found["slug"], found["rev_before"], found["body_before"],
                            found["body"])  # fmt: skip
        return {
            "id": found["id"], "slug": found["slug"], "url": self.link(found["slug"]),
            "dry_run": dry_run, "changed": found["changed"],
            "rev_before": found["rev_before"], "rev": found["rev"],
            "folded": found["folded"], **extra,
            "title_before": found["title_before"], "title": found["title"],
            "diff": diff, "diff_cut": cut,
        }  # fmt: skip

    def sized(self, value: str, name: str) -> str:
        value = text(value, name).replace("\r\n", "\n").replace("\r", "\n")
        if len(value.encode()) > MAX_BODY:
            raise ToolError(f"{name} is over {MAX_BODY} bytes")
        return value
