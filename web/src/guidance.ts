// "Guidance for Claude": the owner's note for Claude's next write-up of a page (writeup.ts,
// About this page) or reading of one image (#538, ingest.ts and figure.ts, at the bottom of
// its "Claude's reading" fold). One fold for both: closed until opened, "(set)" once there is
// some, a 3-row box, its line saying when it is used, and Save, which only stores it (the
// next Regenerate uses it). What is being typed is kept, with its fold open, when the page is
// drawn again. Its look in a reading is css/reading.css's. Shared by the write-up's and the
// figure's chunks: not the app shell.
import { ApiError } from "./api";
import { h, toast } from "./ui";

/** Guidance being typed, by what it is for (a page's id, an image's capture and sha). */
const typing = new Map<string, string>();
export const why = (err: unknown) =>
  err instanceof ApiError ? err.message : "can't reach the server";

/** A button that does one thing, disabled while it does it. */
export function act(label: string, run: () => Promise<void>, className = "") {
  const b = h("button", { type: "button", className }, label);
  b.onclick = async () => {
    b.disabled = true;
    try {
      await run();
    } finally {
      b.disabled = false;
    }
  };
  return b;
}

/** The owner's guidance for Claude's next one, as a fold: key names what it is for (typing is
 * kept by it), saved is what is stored, put stores the box's text (empty: none) and then
 * shows the result (the page drawn again). */
export function guidanceFold<T>(o: {
  key: string;
  saved: string | null | undefined;
  placeholder: string;
  line: string; // when it is used
  done: string; // the toast once saved
  put: (text: string) => Promise<T>;
  shown: (result: T) => void;
}): HTMLDetailsElement {
  const box = h("textarea", {
    rows: 3,
    maxLength: 2000,
    value: typing.get(o.key) ?? o.saved ?? "",
    placeholder: o.placeholder,
    "aria-label": "Guidance for Claude",
    oninput: () => typing.set(o.key, box.value),
  });
  const save = act(
    "Save",
    async () => {
      try {
        const next = await o.put(box.value);
        typing.delete(o.key);
        o.shown(next);
        toast(box.value.trim() ? o.done : "Guidance removed");
      } catch (err) {
        toast(`Not saved: ${why(err)}`);
      }
    },
    "primary",
  );
  return h(
    "details",
    { className: "claude-text sub guidance", open: typing.has(o.key) },
    h("summary", {}, o.saved ? "Guidance for Claude (set)" : "Guidance for Claude"),
    h("p", { className: "by" }, o.line),
    box,
    h("div", { className: "row" }, save),
  );
}
