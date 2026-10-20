// List rows that follow the finger: swiped right, a row opens its page in the editor; swiped
// left, deletes it (with Undo). What letting go would do shows behind it. The page has the
// same Edit and Delete, for those who never swipe. A chunk of its own, loaded with a list
// (which needs the server anyway).
import { go, rerender } from "./app";
import { swipeStep } from "./gesture";
import { icon } from "./icons";
import { deletePage, EDGE, trailOf, trails } from "./swipe";
import { h } from "./ui";

/** A row swiped right opens its page in the editor; swiped left, deletes it (with Undo). It
 * follows the finger, with what letting go would do shown behind it. */
export function swipeRow(li: HTMLLIElement, slug: string, key = slug) {
  const under = h(
    "div",
    { className: "row-under", "aria-hidden": "true" },
    h("span", {}, icon("edit"), "Edit"),
    h("span", {}, icon("trash"), "Delete"),
  );
  li.classList.add("swipe");
  li.prepend(under);
  const row = li.lastElementChild as HTMLAnchorElement;
  const move = (x: number, glide: boolean) => {
    row.style.transition = glide ? "" : "none"; // 1:1 with the finger; glides when let go
    row.style.transform = x ? `translateX(${x}px)` : "";
  };

  let start: { x: number; y: number; t: number; id: number } | null = null;
  let sideways = false;
  li.addEventListener("pointerdown", (e) => {
    if (!e.isPrimary) return; // a second finger changes nothing
    sideways = false; // any new press: a mouse's click, too, opens the page again
    if (e.pointerType === "mouse") return;
    if (e.clientX < EDGE || e.clientX > innerWidth - EDGE) return;
    start = { x: e.clientX, y: e.clientY, t: e.timeStamp, id: e.pointerId };
  });
  li.addEventListener("pointermove", (e) => {
    if (!start || e.pointerId !== start.id) return;
    const dx = e.clientX - start.x;
    const dy = e.clientY - start.y;
    const ms = e.timeStamp - start.t;
    if (!sideways) {
      if (Math.abs(dy) > 8 && Math.abs(dy) >= Math.abs(dx))
        start = null; // a scroll
      else if (Math.abs(dx) > 8) sideways = true; // a touch's pointer is captured already
      if (!sideways) return;
    }
    const d = swipeStep(dx, dy, ms, li.offsetWidth); // let go now: done?
    li.className = `swipe ${dx < 0 ? "to-delete" : "to-edit"}${d ? " armed" : ""}`;
    move(dx, false);
  });
  const end = (e: PointerEvent) => {
    if (!start || e.pointerId !== start.id) return;
    const dx = e.clientX - start.x;
    const d =
      e.type === "pointerup" &&
      swipeStep(dx, e.clientY - start.y, e.timeStamp - start.t, li.offsetWidth);
    start = null;
    if (!sideways) return;
    if (d === 1) {
      move(-li.offsetWidth, true); // off it goes
      void remove(li, slug, key).then(() => {
        if (!li.isConnected) return; // not deleted: back it comes
        move(0, true);
        li.className = "swipe";
      });
    } else {
      move(0, true);
      li.className = "swipe";
      if (d === -1) go(row.pathname, false, { ...trailOf(li), edit: true });
    }
  };
  li.addEventListener("pointerup", end);
  li.addEventListener("pointercancel", end);
  // A touch that moved the row is no tap: no click opens the page
  li.addEventListener(
    "click",
    (e) => {
      if (!sideways || !e.detail) return; // a key's click (detail 0) always opens it
      e.preventDefault();
      e.stopPropagation();
    },
    true,
  );
  return li;
}

async function remove(li: HTMLLIElement, slug: string, key: string) {
  await deletePage(
    encodeURIComponent(key),
    () => {
      const t = trails.get(li.parentElement as Element);
      if (t) t.slugs = t.slugs.filter((s) => s !== slug); // no swiping on to it from its list
      li.remove();
    },
    rerender, // the list again, with it back
  );
}
