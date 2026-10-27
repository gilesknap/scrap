// List rows that follow the finger: swiped right, a row opens its page in the editor; swiped
// left, deletes it (with Undo). What letting go would do shows behind it. The page has the
// same Edit and Delete, for those who never swipe. A todo's or a Later's row also has a tick.
// A chunk of its own, loaded with a list (which needs the server anyway).
import { setStatus } from "./api";
import { go, rerender } from "./app";
import { swipeStep } from "./gesture";
import { icon } from "./icons";
import { tidy } from "./snipclean";
import { echoes } from "./snippet";
import { chipOf, dueOf, partly, statusOf } from "./status";
import { deletePage, EDGE, type RowPage, trailOf, trails, why } from "./swipe";
import { h, toast } from "./ui";

/** A row swiped right opens its page in the editor; swiped left, deletes it (with Undo). It
 * follows the finger, with what letting go would do shown behind it. */
export function swipeRow(li: HTMLLIElement, p: RowPage) {
  const { slug, id: key } = p;
  const row = li.querySelector(":scope > a") as HTMLAnchorElement;
  // A search hit's snippet: tidied (no task boxes, no title leading it), and gone if it only
  // says the title again
  const snip = li.querySelector(".snip");
  if (snip) tidy(snip, p.title);
  if (snip && echoes(p.title, snip.textContent ?? "")) snip.remove();
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

/** A todo's or a Later's tick, beside its row (not in its link: tapping it opens nothing):
 * pressed when done; pressing it sets done (a cancelled one, too), or open again. The chip
 * follows. */
function tickBox(li: HTMLLIElement, p: RowPage) {
  const first = statusOf(p.kind, p.fields);
  if (first === null) return null;
  let status: string = first;
  let before = "open"; // its status before the tick: an untick restores it (in progress stays so)
  const b = h(
    "button",
    { type: "button", className: "tick", "aria-label": `Done: ${p.title}` },
    icon("tick"),
  );
  const show = () => {
    // Done; else some of its task boxes ticked: partly ("mixed", a bar in the box)
    const some = status !== "cancelled" && partly(p);
    b.setAttribute("aria-pressed", status === "done" ? "true" : some ? "mixed" : "false");
    b.title = some ? `${some} ticked` : "";
    li.classList.toggle("cancelled", status === "cancelled"); // struck, a grey dash in its box
    // Its chip comes with done or cancelled and goes when open again (an open row has none);
    // after the edit date, and so (the Todos screen hides that) after the due date
    const ends = chipOf(p.kind, { status });
    li.querySelector(".sub em")?.remove();
    if (ends) li.querySelector(".sub > small")?.after(h("em", { className: ends }, ends));
    // A todo's due date: greyed, and overdue no longer, once done
    const due = li.querySelector(".due");
    const said = dueOf({ ...p, fields: { status } });
    if (due && said) {
      due.textContent = said[0];
      due.className = said[1];
    }
  };
  let busy = false; // taps meanwhile are ignored (not disabled: that would drop its focus)
  b.onclick = () => {
    if (busy) return;
    busy = true;
    setStatus(p.id, status === "done" ? before : "done")
      .then(
        (page) => {
          const now = statusOf(page.kind, page.fields);
          // Its kind changed since the list loaded, to one with no status: not ticked, so
          // the list is shown again as it is now (no empty chip, no stuck tick)
          if (now === null) return rerender();
          before = status;
          status = now;
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
