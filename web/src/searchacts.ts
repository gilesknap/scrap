// A search's own actions, at the end of its results header (design mock, #309 phase 2): Pin
// and Copy link, two ghost icon buttons. Pin adds the search to the Pinned page (pins.ts),
// named for its query; once pinned its pin is filled on --accent-soft, and a tap unpins.
// Copy link copies the search's full address.
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

/** Pin and Copy link for query q (one with results), for the end of its results header. */
export function actions(q: string): HTMLElement {
  const href = searchHref(q);
  const key = keyOf(href);
  const url = new URL(href, location.origin).href;
  const pinBtn = h("button", { type: "button", className: "ghost act" }, icon("pin"));
  const copyBtn = h(
    "button",
    { type: "button", className: "ghost act", "aria-label": "Copy link", title: "Copy link" },
    icon("link"),
  );
  const state = (on: boolean) => {
    pinBtn.classList.toggle("on", on);
    pinBtn.ariaLabel = on ? "Unpin search" : "Pin search";
    pinBtn.title = on ? "Pinned: tap to unpin" : "Pin search";
  };
  const show = () => void isPinned(key).then(state);
  pinBtn.onclick = async () => {
    if (await isPinned(key)) await unpin(key);
    else await pin(nameOf(q), href);
  };
  copyBtn.onclick = () => void copy(url);
  document.addEventListener(CHANGED, show, { signal: view.signal });
  state(false);
  show();
  return h("span", { className: "acts" }, pinBtn, copyBtn);
}
