// A page save's text part (pageedit.ts), apart from the editor so it can be tested.
/** The text of a save: base_rev and body, only if the title or text changed. A kind, tags or
 * due date alone has no text to conflict with (ingest may have renamed the page meanwhile). */
export const textPart = (changed: boolean, base: number, body: string) =>
  changed ? { base_rev: base, body } : {};
