// A search's own actions, after its count (design mock, #309 phase 2): "23 pages · Pin · Copy
// link", quiet links as the Todos screen's Refine is. Pin adds the search to the Pinned page
// (pins.ts), named for its query; once pinned it says Pinned, and a tap unpins. Copy link
// copies the search's full address. When the line is crowded (the filters on no longer fit
// beside them), the two fold into a ⋯ at the count, a small menu as Share's is.
import { view } from "./app";
import { icon } from "./icons";
import { CHANGED, isPinned, keyOf, nameOf, pin, searchHref, unpin } from "./pins";
import { h, toast } from "./ui";

async function copy(text: string) {
  try {
    await navigator.clipboard.writeText(text);
  } catch {
    // (no clipboard API here, or refused: the old way)
    const t = h("textarea", { value: text, readOnly: true });
    t.style.position = "fixed";
    t.style.opacity = "0";
    document.body.append(t);
    t.select();
    const ok = document.execCommand("copy");
    t.remove();
    if (!ok)
      return toast("Can't copy here: long-press the address bar instead", "", undefined, 6000);
  }
  toast("Link copied");
}

/** Pin and Copy link for query q (one with results), to follow its count. */
export function actions(q: string): HTMLElement {
  const href = searchHref(q);
  const key = keyOf(href);
  const url = new URL(href, location.origin).href;
  const pinBtn = h("button", { type: "button", className: "act" }, "Pin");
  const copyBtn = h("button", { type: "button", className: "act" }, "Copy link");
  // The ⋯ menu's rows, for a crowded line
  const pinRow = h("button", { type: "button" }, icon("pin"), "Pin search");
  const copyRow = h("button", { type: "button" }, icon("link"), "Copy link");
  const menu = h("div", { className: "share-menu acts-menu", popover: "auto" }, pinRow, copyRow);
  const more = h(
    "button",
    { type: "button", className: "act more", "aria-label": "More: pin or copy link" },
    icon("more"),
  );
  const state = (on: boolean) => {
    pinBtn.textContent = on ? "Pinned" : "Pin";
    pinBtn.ariaPressed = String(on);
    pinBtn.ariaLabel = on ? "Pinned: tap to unpin" : "Pin this search";
    pinRow.replaceChildren(icon("pin"), on ? "Unpin search" : "Pin search");
  };
  const show = () => void isPinned(key).then(state);
  const toggle = async () => {
    if (await isPinned(key)) await unpin(key);
    else await pin(nameOf(q), href);
  };
  pinBtn.onclick = toggle;
  copyBtn.onclick = () => void copy(url);
  pinRow.onclick = () => {
    menu.hidePopover();
    void toggle();
  };
  copyRow.onclick = () => {
    menu.hidePopover();
    void copy(url);
  };
  more.setAttribute("aria-expanded", "false");
  menu.addEventListener("beforetoggle", (e) =>
    more.setAttribute("aria-expanded", String((e as ToggleEvent).newState === "open")),
  );
  more.onclick = () => {
    if (!menu.isConnected) document.body.append(menu);
    (menu.showPopover as (o?: { source?: HTMLElement }) => void)({ source: more });
    const r = more.getBoundingClientRect();
    menu.style.top = `${Math.round(r.bottom + 4)}px`;
    menu.style.left = `${Math.round(Math.max(8, Math.min(r.left, innerWidth - menu.offsetWidth - 8)))}px`;
    pinRow.focus();
  };
  menu.addEventListener("toggle", () => menu.matches(":popover-open") || menu.remove());
  view.signal.addEventListener("abort", () => menu.remove());
  document.addEventListener(CHANGED, show, { signal: view.signal });
  state(false);
  show();
  return h(
    "span",
    { className: "acts" },
    h("span", { className: "inline" }, " · ", pinBtn, " · ", copyBtn),
    more,
  );
}

/** Fold the actions into ⋯ while row (the count and the filters on) is wider than the screen. */
export function fitActs(row: HTMLElement) {
  const measure = () => {
    row.classList.remove("tight");
    if (row.scrollWidth > row.clientWidth + 1) row.classList.add("tight");
  };
  requestAnimationFrame(measure);
  const ro = new ResizeObserver(() => requestAnimationFrame(measure));
  ro.observe(row);
  view.signal.addEventListener("abort", () => ro.disconnect());
}
