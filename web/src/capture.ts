// Home screen: big capture buttons, a composer, and what is still waiting to upload.

import { uploadLimit } from "./api";
import { queue, view } from "./app";
import { type Capture, type Hint, split } from "./queue";
import { pageList, pendingList } from "./recent";
import { clearToasts, h, toast } from "./ui";

const HINTS: [string, Hint | ""][] = [
  ["Note", ""],
  ["Todo", "todo"],
  ["Read later", "consume"],
];

function picker(
  label: string,
  camera: boolean,
  onPick: (files: File[]) => void,
  className = "big",
) {
  // A real button (Tab and TalkBack reach it) opening a file input kept out of the page.
  const input = h("input", { type: "file", accept: "image/*", multiple: !camera });
  if (camera) input.setAttribute("capture", "environment");
  input.onchange = () => {
    if (input.files?.length) onPick([...input.files]);
    input.value = ""; // so the same shot again still fires change
  };
  return h("button", { type: "button", className, onclick: () => input.click() }, label);
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

  const actions = h(
    "div",
    { className: "actions" },
    picker("Photo", true, (f) => compose("", f), "big photo"),
    picker("Gallery", false, (f) => compose("", f)),
    ...HINTS.map(([label, hint]) =>
      h("button", { className: "big", onclick: () => compose(hint, []) }, label),
    ),
  );
  root.append(pending, actions);

  function compose(hint: Hint | "", files: File[]) {
    const text = h("textarea", { rows: 5 });
    const thumbs = h("div", { className: "thumbs" });
    // One capture, many photos: add from the camera (one at a time) or the gallery.
    const add = (more: File[]) => {
      files.push(...more);
      showThumbs();
    };
    const showThumbs = () => {
      text.placeholder = files.length ? "Caption (optional)" : "Note or link";
      thumbs.replaceChildren(
        ...files.map((f, i) =>
          h(
            "span",
            { className: "thumb" },
            h("img", { src: URL.createObjectURL(f), alt: f.name }),
            h("button", {
              type: "button",
              textContent: "×",
              "aria-label": `Remove photo ${i + 1}`,
              onclick: () => {
                files.splice(i, 1);
                showThumbs();
              },
            }),
          ),
        ),
      );
    };
    const adders = h(
      "div",
      { className: "bar" },
      picker("+ Camera", true, add, "big add"),
      picker("+ Gallery", false, add, "big add"),
    );
    showThumbs();
    const chips = h(
      "div",
      { className: "chips", role: "radiogroup" },
      ...HINTS.map(([label, value]) =>
        h(
          "label",
          {},
          h("input", { type: "radio", name: "hint", value, checked: value === hint }),
          label,
        ),
      ),
    );
    const close = () => {
      form.replaceWith(actions);
      pending.hidden = false;
      clearToasts(); // e.g. a "Save separately" offer for this composer
    };
    const save = h("button", { type: "submit", className: "primary" }, "Save");
    const form = h(
      "form",
      { className: "composer" },
      chips,
      text,
      thumbs,
      adders,
      h(
        "div",
        { className: "bar" },
        h("button", { type: "button", onclick: close }, "Cancel"),
        save,
      ),
    );
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
        for (const part of separately ? split(capture) : [capture]) await queue.add(part);
      } catch (err) {
        save.disabled = false; // keep everything in the composer to try again
        return toast(
          `Not saved: the phone refused to store it (${(err as Error).name}). Free some space and try again.`,
          "",
          undefined,
          10000,
        );
      }
      close();
      toast(navigator.onLine ? "Saved" : "Saved on the phone: uploads when online");
    };
    form.onsubmit = (e) => {
      e.preventDefault();
      void store(false);
    };
    actions.replaceWith(form);
    pending.hidden = true; // the composer gets the whole screen
    if (!files.length) text.focus();
  }
  return root;
}
