// The app's icons: 24 px line drawings in currentColor, always beside a label or with an
// aria-label on their button, so they are hidden from screen readers.
const PATHS = {
  camera: '<path d="M4 8h3l2-3h6l2 3h3v11H4z"/><circle cx="12" cy="13" r="3.5"/>',
  image:
    '<rect x="3.5" y="4.5" width="17" height="15" rx="2"/><circle cx="9" cy="10" r="1.6"/><path d="m4 18 5-5 4 4 3-3 4 4"/>',
  note: '<path d="M6 3.5h9l4 4v13H6z"/><path d="M15 3.5v4h4M9 12h7M9 16h5"/>',
  // The Todo kind: a checklist (not a ticked box, which beside a row's tick box reads as done)
  todo: '<path d="m3.5 6.5 2 2 4-4.5M12.5 6.5h8M4.5 12h2m6 0h8m-16 5.5h2m6 0h8"/>',
  // A tick box: a todo's or a Later's done control, and the Todos screen
  tick: '<rect x="4" y="4" width="16" height="16" rx="3"/><path d="m8.5 12 2.5 2.5 4.5-5"/>',
  all: '<rect x="4" y="4" width="7" height="7" rx="1.5"/><rect x="13" y="4" width="7" height="7" rx="1.5"/><rect x="4" y="13" width="7" height="7" rx="1.5"/><rect x="13" y="13" width="7" height="7" rx="1.5"/>',
  now: '<circle cx="12" cy="12" r="8"/><path d="M12 7.5V12l3 2"/>',
  add: '<path d="M12 5v14M5 12h14"/>',
  done: '<path d="m5 12.5 4.5 4.5L19 7"/>',
  due: '<rect x="4" y="5" width="16" height="15" rx="2"/><path d="M4 10h16M8.5 3v4m7-4v4"/>',
  later: '<path d="M7 3.5h10v17l-5-3.5-5 3.5z"/>',
  download: '<path d="M12 4v11m-4.5-4.5L12 15l4.5-4.5M5 19.5h14"/>',
  share:
    '<circle cx="17.5" cy="5.5" r="2.5"/><circle cx="6.5" cy="12" r="2.5"/><circle cx="17.5" cy="18.5" r="2.5"/><path d="m8.7 10.7 6.6-3.9m-6.6 6.5 6.6 3.9"/>',
  edit: '<path d="M4 20h4L19 9l-4-4L4 16z"/><path d="m13.5 6.5 4 4"/>',
  trash: '<path d="M4 7h16M9.5 7V4.5h5V7M6.5 7l1 13h9l1-13M10 11v5.5M14 11v5.5"/>',
  search: '<circle cx="11" cy="11" r="6.5"/><path d="m16 16 4.5 4.5"/>',
  close: '<path d="M6 6l12 12M18 6 6 18"/>',
  back: '<path d="M15 5l-7 7 7 7"/>',
  up: '<path d="m5 15 7-7 7 7"/>',
  down: '<path d="m5 9 7 7 7-7"/>',
  next: '<path d="m9 5 7 7-7 7"/>',
  fit: '<path d="M4 9V4h5M20 9V4h-5M4 15v5h5M20 15v5h-5"/>',
  retry: '<path d="M19.5 12a7.5 7.5 0 1 1-2.2-5.3M19.5 4v5h-5"/>',
  offline:
    '<path d="M7 18.5h10a4 4 0 0 0 .6-8A6 6 0 0 0 6.3 9.6 4.5 4.5 0 0 0 7 18.5zM4 4l16 16"/>',
  link: '<path d="M10 14a4 4 0 0 0 5.7 0l3-3a4 4 0 0 0-5.7-5.7l-1 1M14 10a4 4 0 0 0-5.7 0l-3 3a4 4 0 0 0 5.7 5.7l1-1"/>',
  // Opens elsewhere (a Later page's link card): an arrow out of a box
  open: '<path d="M13.5 4.5h6v6M19.5 4.5 11 13M17.5 14v5.5h-13v-13H10"/>',
  file: '<path d="M6 3.5h9l4 4v13H6z"/><path d="M15 3.5v4h4"/>',
  filter:
    '<path d="M4 7h9M17 7h3M4 17h3M11 17h9"/><circle cx="15" cy="7" r="2"/><circle cx="9" cy="17" r="2"/>',
  tag: '<path d="M3.5 12.5v-8h8l9 9-8 8z"/><circle cx="8" cy="9" r="1.5"/>',
  // Settings
  // A toothed cog (8 teeth): read as Settings, as a sun-like one was not
  cog: '<path d="M18.9 9.9L21.4 10.4L21.4 13.6L18.9 14.1L18.4 15.4L19.8 17.5L17.5 19.8L15.4 18.4L14.1 18.9L13.6 21.4L10.4 21.4L9.9 18.9L8.6 18.4L6.5 19.8L4.2 17.5L5.6 15.4L5.1 14.1L2.6 13.6L2.6 10.4L5.1 9.9L5.6 8.6L4.2 6.5L6.5 4.2L8.6 5.6L9.9 5.1L10.4 2.6L13.6 2.6L14.1 5.1L15.4 5.6L17.5 4.2L19.8 6.5L18.4 8.6Z"/><circle cx="12" cy="12" r="3"/>',
  // A topic (#261): an open book, a page gathered from many (the nav's Topics draws the same)
  topic:
    '<path d="M12 6.5C10 5 7 4.5 4 5v13.5c3-.5 6 0 8 1.5 2-1.5 5-2 8-1.5V5c-3-.5-6 0-8 1.5zm0 0V20"/>',
  board:
    '<rect x="3.5" y="4.5" width="17" height="12" rx="1.5"/><path d="M8 20l2-3.5m6 3.5-2-3.5M7 9h6m-6 3h9"/>',
};
export type Icon = keyof typeof PATHS;

export function icon(name: Icon): SVGSVGElement {
  const t = document.createElement("template");
  t.innerHTML = `<svg class="i" viewBox="0 0 24 24" aria-hidden="true">${PATHS[name]}</svg>`;
  return t.content.firstChild as SVGSVGElement;
}

const KINDS: Record<string, Icon> = {
  todo: "todo",
  consume: "later",
  whiteboard: "board",
  document: "file",
  photo: "image",
  url: "link",
  file: "file",
};
/** The icon for a page kind (as the API names them). */
export const kindIcon = (kind?: string): Icon => KINDS[kind ?? ""] ?? "note";
