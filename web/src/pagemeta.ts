// What a page's quiet meta line under its title says (#page-header mock): one line of parts,
// "Later · TV · to watch · 26 Oct", "Todo · high · overdue 24 Oct · added 12 Oct · edited 26 Oct".
// No DOM here (the unit tests run it); pagehead.ts draws it.
import { dueParts, short, statusOf, today } from "./status";

/** A part of the line, and whether it is the overdue one (the only part drawn in red). */
export type Part = [string, boolean];

interface Meta {
  kind: string;
  fields?: Record<string, unknown>;
  created_at: string;
  updated_at: string;
  due?: string | null;
  priority?: string | null;
  snoozed_until?: string | null;
  tasks?: { done: number; total: number };
}

/** A time as the day it fell on here (YYYY-MM-DD, local). */
const localDay = (iso: string) => {
  const d = new Date(iso);
  return today(d);
};

/** A Later's medium as a word: "Book", "TV". */
const medium = (m: string) => (m === "tv" ? "TV" : m.charAt(0).toUpperCase() + m.slice(1));

/** Its dates, as days: "26 Oct" when added and last edited the same day, else "added 12 Oct ·
 * edited 26 Oct". No times; the year only when it isn't this one. */
export function dateParts(p: Meta, now = today()): Part[] {
  const added = localDay(p.created_at);
  const edited = localDay(p.updated_at);
  return edited === added
    ? [[short(added, now), false]]
    : [
        [`added ${short(added, now)}`, false],
        [`edited ${short(edited, now)}`, false],
      ];
}

/** The line's parts: its kind (label: KINDS' short name, if it has one), then a Later's
 * medium and what it is for, or a todo's priority, due day, snooze and tasks; its status
 * when it isn't open; then its dates. */
export function metaParts(p: Meta, label: string | undefined, now = today()): Part[] {
  const parts: Part[] = label ? [[label, false]] : [];
  if (p.kind === "consume") {
    const m = String(p.fields?.media_type ?? "");
    const sub = String(p.fields?.subtype ?? "");
    if (m) parts.push([medium(m), false]);
    if (sub) parts.push([`to ${sub}`, false]);
  }
  parts.push(...(dueParts(p, now) ?? []));
  const s = statusOf(p.kind, p.fields);
  if (s && s !== "open") parts.push([s.replace("_", " "), false]);
  return [...parts, ...dateParts(p, now)];
}
