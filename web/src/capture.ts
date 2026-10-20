// Home screen: the capture actions (Camera, Gallery, Note: how, not what kind; the kind is
// chosen in the composer), and what is still waiting to upload.
import { view } from "./app";
import { icon } from "./icons";
import { pageList, pendingList } from "./recent";
import { h, toast } from "./ui";

// The composer is a chunk of its own (composer.ts), with the editor
const compose = (files: File[]) =>
  import("./composer").then(
    (m) => m.compose(files),
    () => toast("Can't open the composer: reload scrap and try again"),
  );

export function picker(
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
  const refresh = async () =>
    pending.replaceChildren(await pendingList(), await pageList(4, "", "Latest"));
  document.addEventListener("queuechange", refresh, { signal: view.signal });
  await refresh();

  // The capture actions, equal tiles under the thumb
  const actions = h(
    "div",
    { className: "actions" },
    picker("Camera", true, (f) => void compose(f)),
    picker("Gallery", false, (f) => void compose(f)),
    h(
      "button",
      { type: "button", className: "tile", onclick: () => void compose([]) },
      icon("note"),
      "Note",
    ),
  );
  root.append(h("h2", { className: "label" }, "Latest"), pending, actions);
  return root;
}
