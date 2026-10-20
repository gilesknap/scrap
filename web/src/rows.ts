// List rows that follow the finger: swiped right, a row opens its page in the editor; swiped
// left, deletes it (with Undo). What letting go would do shows behind it. The page has the
// same Edit and Delete, for those who never swipe. A todo's or a Read's row also has a tick.
// A chunk of its own, loaded with a list (which needs the server anyway).
import { setStatus } from "./api";
import { go, rerender } from "./app";
import { swipeStep } from "./gesture";
import { icon } from "./icons";
import { chipOf, statusOf } from "./status";
import { deletePage, EDGE, type RowPage, trailOf, trails, why } from "./swipe";
import { h, toast } from "./ui";

/** A row swiped right opens its page in the editor; swiped left, deletes it (with Undo). It
 * follows the finger, with what letting go would do shown behind it. */
export function swipeRow(li: HTMLLIElement, p: RowPage) {
  const { slug, id: key } = p;
  const row = li.querySelector(":scope > a") as HTMLAnchorElement;
  const tick = tickBox(li, p);
  const under = h(
    "div",
    { className: "row-under", "aria-hidden": "true" },
    h("span", {}, icon("edit"), "Edit"),
    h("span", {}, icon("trash"), "Delete"),
  );
  li.classList.add("swipe");
  li.prepend(under);
  if (tick) li.append(tick);
  const move = (x: number, glide: boolean) => {
    for (const el of tick ? [row, tick] : [row]) {
      el.style.transition = glide ? "" : "none"; // 1:1 with the finger; glides when let go
      el.style.transform = x ? `translateX(${x}px)` : "";
    }
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
    li.classList.toggle("to-delete", dx < 0);
    li.classList.toggle("to-edit", dx >= 0);
    li.classList.toggle("armed", !!d);
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
        li.classList.remove("to-edit", "to-delete", "armed");
      });
    } else {
      move(0, true);
      li.classList.remove("to-edit", "to-delete", "armed");
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

/** A todo's or a Read's tick, beside its row (not in its link: tapping it opens nothing):
 * pressed when done; pressing it sets done, or open again. The chip follows. */
function tickBox(li: HTMLLIElement, p: RowPage) {
  let status = statusOf(p.kind, p.fields);
  if (status === null) return null;
  const b = h(
    "button",
    { type: "button", className: "tick", "aria-label": `Done: ${p.title}` },
    icon("todo"),
  );
  const show = () => {
    b.setAttribute("aria-pressed", String(status === "done"));
    const chip = li.querySelector("em");
    if (chip) chip.textContent = chipOf(p.kind, { status });
  };
  let busy = false; // taps meanwhile are ignored (not disabled: that would drop its focus)
  b.onclick = () => {
    if (busy) return;
    busy = true;
    setStatus(p.id, status === "done" ? "open" : "done")
      .then(
        (page) => {
          status = statusOf(page.kind, page.fields);
          show();
        },
        (err) => toast(`Not changed: ${why(err)}`),
      )
      .finally(() => (busy = false));
  };
  li.classList.add("ticks");
  show();
  return b;
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
