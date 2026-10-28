// Home screen: the capture actions (Camera, Gallery, File, Note: how, not what kind; the kind is
// chosen in the composer), a kept draft over them, and what is still waiting to upload.
import { view } from "./app";
import type { Draft } from "./composer";
import { drafts } from "./db";
import { DRAFT, recover } from "./fresh";
import { icon, kindIcon } from "./icons";
import { pageList, pendingList } from "./lists";
import { says } from "./says";
import { h, toast } from "./ui";

// The composer is a chunk of its own (composer.ts), with the editor
const compose = (files: File[], resume?: boolean) =>
  import("./composer").then(
    (m) => m.compose(files, undefined, resume),
    () => toast("Can't open the composer: reload scrap and try again"),
  );

/** What File takes (#380): PDFs, text and Markdown, by name too (a phone's .md often has no
 * type). Gallery takes photos only, so phones open their photo picker for it. */
export const FILES = "application/pdf,text/plain,text/markdown,.md,.txt";

/** A Camera, Gallery or File button (shown: its icon). accept is the file input's: photos,
 * unless the caller takes files (FILES). */
export function picker(
  label: string,
  camera: boolean,
  onPick: (files: File[]) => void,
  className = "tile",
  accept = "image/*",
) {
  // A real button (Tab and TalkBack reach it) opening a file input kept out of the page.
  const input = h("input", { type: "file", accept, multiple: !camera });
  if (camera) input.setAttribute("capture", "environment");
  input.onchange = () => {
    if (input.files?.length) onPick([...input.files]);
    input.value = ""; // so the same shot again still fires change
  };
  const glyph = icon(camera ? "camera" : accept === FILES ? "file" : "image");
  return h("button", { type: "button", className, onclick: () => input.click() }, glyph, label);
}

export async function capture(): Promise<Node> {
  if (new URLSearchParams(location.search).has("shared")) {
    history.replaceState(null, "", "/");
    toast("Shared item saved");
  }
  const root = h("section", { className: "capture" });
  const pending = h("div", { className: "strip" });
  // Offline, the waiting rows (and the header's badge) say so: one quiet line, no card
  const latest = () =>
    navigator.onLine
      ? pageList(4, "", "Latest")
      : h("p", { className: "offline" }, "Offline: showing what's on this phone");
  const refresh = async () => pending.replaceChildren(await pendingList(), await latest());
  document.addEventListener("queuechange", refresh, { signal: view.signal });
  // Back online with nothing waiting, no upload redraws it: no Retry needed
  addEventListener("online", refresh, { signal: view.signal });
  addEventListener("offline", refresh, { signal: view.signal });
  await refresh();

  // The capture actions, equal tiles under the thumb
  const actions = h(
    "div",
    { className: "actions" },
    picker("Camera", true, (f) => void compose(f)),
    picker("Gallery", false, (f) => void compose(f)),
    picker("File", false, (f) => void compose(f), "tile", FILES),
    h(
      "button",
      { type: "button", className: "tile", onclick: () => void compose([]) },
      icon("note"),
      "Note",
    ),
  );
  // The composer's kept draft (left by Back), one line over the tiles: tap to carry on, ✕ to
  // drop it. Read from IndexedDB here, so the composer's chunk loads only when it opens.
  const row = h("div", { className: "draft", hidden: true });
  const draw = async () => {
    const d = await drafts.get<Draft>(DRAFT).catch(() => undefined);
    row.hidden = !d;
    if (!d) return;
    const n = d.files.length;
    const discard = async () => {
      await drafts.del(DRAFT).catch(() => {});
      await draw();
      toast("Draft discarded", "Undo", () => void drafts.put(DRAFT, d).then(draw, () => {}));
    };
    row.replaceChildren(
      h(
        "button",
        { type: "button", onclick: () => void compose([], true) },
        icon(n ? "image" : kindIcon(d.kind ?? d.hint)),
        h("span", {}, "Draft: ", says(d.text, d.files) || "Untitled"),
      ),
      h(
        "button",
        { type: "button", "aria-label": "Discard draft", onclick: () => void discard() },
        icon("close"),
      ),
    );
  };
  document.addEventListener("draftchange", draw, { signal: view.signal });
  // A fresh capture the app was closed or killed on (no Back): the kept draft now
  if (!document.body.classList.contains("editing")) await recover();
  await draw();
  actions.prepend(row);
  root.append(h("h2", { className: "label" }, "Latest"), pending, actions);
  return root;
}
