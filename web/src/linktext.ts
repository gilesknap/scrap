// The words a link to a page shows (#508): the label typed for it, else the page's title, else
// the link as typed (a dangling link, or one whose title isn't known yet, so it never shows
// empty). One rule for every view that draws page links (render.ts); public pages may share it.

/** Slug to title, for the pages a text links to (a page's titles, from the server). */
export type Titles = Readonly<Record<string, string>>;

/** The title of the page slug names, if titles has it (its own key: never Object's
 * "constructor"). */
export const titleOf = (slug: string, titles?: Titles): string | undefined =>
  titles && Object.hasOwn(titles, slug) ? titles[slug] || undefined : undefined;

/** A page link's text: label if one was typed, else the page's title, else typed. */
export const linkText = (slug: string, typed: string, label?: string, titles?: Titles): string =>
  label || titleOf(slug, titles) || typed;
