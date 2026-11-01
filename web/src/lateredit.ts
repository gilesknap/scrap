// A Later page's type (#309): Book, Article, Film ... in a menu, in the editor's folded
// "Type" line. Its subtype (To read, To watch ...) follows from it.
import { MEDIA } from "./termedit";
import { h } from "./ui";

/** What each type is for: read, watch, listen or play. */
const SUBTYPE: Record<string, string> = {
  book: "read",
  article: "read",
  film: "watch",
  tv: "watch",
  video: "watch",
  podcast: "listen",
  music: "listen",
  game: "play",
};
const TO: Record<string, string> = {
  read: "To read",
  watch: "To watch",
  listen: "To listen",
  play: "To play",
};

/** The type a page has now (its media_type if it is one we know), else "". */
export const mediaNow = (fields: Record<string, unknown> | undefined) => {
  const m = String(fields?.media_type ?? "");
  return m in SUBTYPE ? m : "";
};

/** What the Type line says: "Book · To read". */
export const mediaSays = (media: string, subtype = "") =>
  media
    ? `${MEDIA_NAME[media] ?? media} · ${TO[SUBTYPE[media]]}`
    : subtype
      ? (TO[subtype] ?? "none")
      : "none";

const MEDIA_NAME: Record<string, string> = {
  book: "Book",
  article: "Article",
  film: "Film",
  tv: "TV",
  video: "Video",
  podcast: "Podcast",
  music: "Music",
  game: "Game",
};

/** A menu of types, starting at media. */
export function laterField(media: string) {
  const pick = h(
    "select",
    { "aria-label": "Type" },
    h("option", { value: "" }, "No type"),
    ...Object.keys(MEDIA).map((m) => h("option", { value: m }, MEDIA_NAME[m] ?? m)),
  );
  pick.value = media;
  return {
    el: h("div", { className: "todoedit" }, h("label", {}, "Type", pick)),
    value: () => pick.value,
    reset: (m: string) => {
      pick.value = m;
    },
  };
}

/** The fields to send for a type chosen: its media_type, and the subtype it is for (a type
 * taken off leaves the subtype as it was). */
export const mediaFields = (media: string) =>
  media ? { media_type: media, subtype: SUBTYPE[media] } : { media_type: null };
