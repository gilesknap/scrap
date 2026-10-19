// Home screen: big capture buttons, a composer, and what is still waiting to upload.
import { queue, view } from "./app";
import type { Hint } from "./queue";
import { pageList, pendingList } from "./recent";
import { h, toast } from "./ui";

const HINTS: [string, Hint | ""][] = [
  ["Note", ""],
  ["Todo", "todo"],
  ["Read later", "consume"],
];

function picker(label: string, camera: boolean, onPick: (files: File[]) => void) {
  const input = h("input", { type: "file", accept: "image/*", multiple: !camera, hidden: true });
  if (camera) input.setAttribute("capture", "environment");
  input.onchange = () => {
    if (input.files?.length) onPick([...input.files]);
    input.value = "";
  };
  return h("label", { className: camera ? "big photo" : "big" }, label, input);
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
    picker("Photo", true, (f) => compose("", f)),
    picker("Gallery", false, (f) => compose("", f)),
    ...HINTS.map(([label, hint]) =>
      h("button", { className: "big", onclick: () => compose(hint, []) }, label),
    ),
  );
  root.append(pending, actions);

  function compose(hint: Hint | "", files: File[]) {
    const text = h("textarea", {
      placeholder: files.length ? "Caption (optional)" : "Note or link",
      rows: 6,
    });
    const thumbs = h("div", { className: "thumbs" });
    const showThumbs = () =>
      thumbs.replaceChildren(
        ...files.map((f) => h("img", { src: URL.createObjectURL(f), alt: f.name })),
        picker("+ Photo", false, (more) => {
          files.push(...more);
          showThumbs();
        }),
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
    };
    const form = h(
      "form",
      { className: "composer" },
      chips,
      text,
      thumbs,
      h(
        "div",
        { className: "bar" },
        h("button", { type: "button", onclick: close }, "Cancel"),
        h("button", { type: "submit", className: "primary" }, "Save"),
      ),
    );
    form.onsubmit = async (e) => {
      e.preventDefault();
      const body = text.value.trim();
      if (!body && !files.length) return text.focus();
      const chosen = (new FormData(form).get("hint") || undefined) as Hint | undefined;
      close();
      await queue.add({
        text: body || undefined,
        hint: chosen,
        source: "pwa",
        files: files.map((f) => ({ name: f.name, blob: f })),
      });
      toast(navigator.onLine ? "Saved" : "Saved on the phone: uploads when online");
    };
    actions.replaceWith(form);
    pending.hidden = true; // the composer gets the whole screen
    if (!files.length) text.focus();
  }
  return root;
}
