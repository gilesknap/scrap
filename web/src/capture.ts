// Home screen: big capture buttons, a composer, and what is still waiting to upload.

import { uploadLimit } from "./api";
import { queue, view } from "./app";
import { drafts } from "./db";
import { editor } from "./editor";
import { type Icon, icon } from "./icons";
import { type Capture, type Hint, split } from "./queue";
import { pageList, pendingList } from "./recent";
import { blobImg, clearToasts, h, toast } from "./ui";

const DRAFT = "new"; // the composer's draft
interface Draft {
  text: string;
  hint: Hint | "";
  files: File[]; // IndexedDB keeps them, so photos survive a killed app too
}

const HINTS: [string, Hint | "", Icon][] = [
  ["Note", "", "note"],
  ["Todo", "todo", "todo"],
  ["Read later", "consume", "later"],
];

function picker(
  label: string,
  camera: boolean,
  onPick: (files: File[]) => void,
  className = "tile",
) {
  // A real button (Tab and TalkBack reach it) opening a file input kept out of the page.
  const input = h("input", { type: "file", accept: "image/*", multiple: !camera });
  if (camera) input.setAttribute("capture", "environment");
  input.onchange = () => {
    if (input.files?.length) onPick([...input.files]);
    input.value = ""; // so the same shot again still fires change
  };
  const glyph = icon(camera ? "camera" : "image");
  return h("button", { type: "button", className, onclick: () => input.click() }, glyph, label);
}

export async function capture(): Promise<Node> {
  if (new URLSearchParams(location.search).has("shared")) {
    history.replaceState(null, "", "/");
    toast("Shared item saved");
  }
  const root = h("section", { className: "capture" });
  const pending = h("div", { className: "strip" });
  const refresh = async () => pending.replaceChildren(await pendingList(), await pageList(4));
  document.addEventListener("queuechange", refresh, { signal: view.signal });
  await refresh();

  // The capture cluster: the camera as the hero, the other four as tiles under it.
  const actions = h(
    "div",
    { className: "actions" },
    picker("Photo", true, (f) => void compose("", f), "hero"),
    h(
      "div",
      { className: "tiles" },
      picker("Gallery", false, (f) => void compose("", f)),
      ...HINTS.map(([label, hint, glyph]) =>
        h(
          "button",
          { type: "button", className: "tile", onclick: () => void compose(hint, []) },
          icon(glyph),
          label,
        ),
      ),
    ),
  );
  root.append(h("h2", { className: "label" }, "Latest"), pending, actions);

  async function compose(hint: Hint | "", picked: File[]) {
    // An unsaved draft comes back, with any photos just picked added to it.
    const kept = await drafts.get<Draft>(DRAFT).catch(() => undefined);
    const files = [...(kept?.files ?? []), ...picked];
    const text = h("textarea", { rows: 5, value: kept?.text ?? "" });
    if (kept) hint = kept.hint;
    const thumbs = h("div", { className: "thumbs" });
    // One capture, many photos: add from the camera (one at a time) or the gallery.
    const add = (more: File[]) => {
      files.push(...more);
      showThumbs();
      ed.keep();
    };
    const showThumbs = () => {
      text.placeholder = files.length ? "Caption (optional)" : "Note or link";
      thumbs.replaceChildren(
        ...files.map((f, i) =>
          h(
            "span",
            { className: "thumb" },
            blobImg(f, f.name),
            h(
              "button",
              {
                type: "button",
                "aria-label": `Remove photo ${i + 1}`,
                onclick: () => {
                  files.splice(i, 1);
                  showThumbs();
                  ed.keep();
                },
              },
              icon("close"),
            ),
          ),
        ),
      );
    };
    const adders = h(
      "div",
      { className: "bar" },
      picker("Camera", true, add, "add"),
      picker("Gallery", false, add, "add"),
    );
    showThumbs();
    const chips = h(
      "div",
      { className: "chips", role: "radiogroup", "aria-label": "Kind" },
      ...HINTS.map(([label, value, glyph]) =>
        h(
          "label",
          {},
          h("input", { type: "radio", name: "hint", value, checked: value === hint }),
          icon(glyph),
          label,
        ),
      ),
    );
    const chosen = () =>
      ((chips.querySelector("input:checked") as HTMLInputElement | null)?.value ?? "") as Hint | "";
    const ed = editor({
      text,
      before: [chips],
      after: [thumbs, adders],
      key: DRAFT,
      draft: (): Draft => ({ text: text.value, hint: chosen(), files }),
      dirty: () => !!text.value.trim() || files.length > 0,
      restored: !!kept,
      ondiscard: () => {
        text.value = "";
        files.length = 0;
        showThumbs();
      },
      onsave: () => void store(false),
    });
    const { form, save } = ed;
    const close = async () => {
      clearToasts(); // e.g. a "Save separately" offer for this composer
      await ed.done();
    };
    const mb = (n: number) => `${(n / 2 ** 20).toFixed(1)} MB`;
    const store = async (separately: boolean) => {
      const body = text.value.trim();
      if (!body && !files.length) return text.focus();
      const capture: Capture = {
        text: body || undefined,
        hint: (new FormData(form).get("hint") || undefined) as Hint | undefined,
        source: "pwa",
        files: files.map((f) => ({ name: f.name, blob: f })),
      };
      // Check the server's limit now: a capture it refuses could only be split or discarded.
      const size = files.reduce((n, f) => n + f.size, 0);
      const max = uploadLimit();
      if (max && size > max - 64 * 1024 && !separately) {
        const over = `${mb(size)} of photos is over the server's ${mb(max)} limit.`;
        if (files.length < 2)
          return toast(`${over} Remove it to save the text.`, "", undefined, 10000);
        return toast(`${over} Remove some, or`, "Save separately", () => void store(true), 15000);
      }
      save.disabled = true;
      try {
        await queue.addAll(separately ? split(capture) : [capture]);
      } catch (err) {
        save.disabled = false; // keep everything in the composer to try again
        return toast(
          `Not saved: the phone refused to store it (${(err as Error).name}). Free some space and try again.`,
          "",
          undefined,
          10000,
        );
      }
      await close();
      toast(navigator.onLine ? "Saved" : "Saved on the phone: uploads when online");
    };
    if (!files.length) text.focus();
  }
  return root;
}
