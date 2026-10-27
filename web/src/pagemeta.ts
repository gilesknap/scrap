// What a page's quiet meta line under its title says (#page-header mock): what it is, as
// " · "-separated parts ("Later · TV · to watch", "Todo · snoozed till 3 Nov", "Note"), and
// whether it was edited after it was made (the dates line under it says when).
// No DOM here (the unit tests run it); pagehead.ts draws them.
import { closed, partly, short, snoozed, statusOf, today } from "./status";

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

/** What a Later is for, once done: "read", "watched". */
const DONE: Record<string, string> = {
  read: "read",
  watch: "watched",
  listen: "listened to",
  play: "played",
};

/** A Later's medium as a word: "Book", "TV". */
const medium = (m: string) => (m === "tv" ? "TV" : m.charAt(0).toUpperCase() + m.slice(1));

/** The line's parts: its kind (label: KINDS' short name, if it has one), then a Later's medium
 * and what it is for, its status when it isn't open, and a todo's snooze and tasks. A todo's
 * due day and priority are its due chip's alone. */
export function metaParts(p: Meta, label: string | undefined, now = today()): string[] {
  const parts: string[] = label ? [label] : [];
  if (p.kind === "consume") {
    const m = String(p.fields?.media_type ?? "");
    const sub = String(p.fields?.subtype ?? "");
    if (m) parts.push(medium(m));
    // Done, it says what was done ("read"), not "to read · done"
    if (sub && statusOf(p.kind, p.fields) === "done" && DONE[sub]) return [...parts, DONE[sub]];
    if (sub) parts.push(`to ${sub}`);
  }
  const s = statusOf(p.kind, p.fields);
  if (s && s !== "open") parts.push(s.replace("_", " "));
  if (p.kind === "todo") {
    if (snoozed(p, now) && p.snoozed_until)
      parts.push(`snoozed till ${short(p.snoozed_until, now)}`);
    const part = !closed(p) && partly(p);
    if (part) parts.push(part);
  }
  return parts;
}

/** Edited after it was made: its last change more than a minute after it was created. */
export const edited = (p: Meta) =>
  Math.abs(Date.parse(p.updated_at) - Date.parse(p.created_at)) > 60_000;

/** What a page's tag chips say: each tag's last part ("kind/project-management" is
 * "project-management"), with as many parts before it as tell it from the page's other tags
 * that end the same ("epics/thoth" beside "other/thoth"). */
export function tagNames(tags: string[]): Map<string, string> {
  const parts = tags.map((t) => t.split("/"));
  const depth = tags.map(() => 1);
  const said = (i: number) => parts[i].slice(-depth[i]).join("/");
  for (let more = true; more; ) {
    // every tag whose name another shares takes one more part, all at once
    const now = tags.map((_, i) => said(i));
    const clash = now.map((n, i) => now.some((m, j) => i !== j && m === n));
    more = false;
    clash.forEach((c, i) => {
      if (c && depth[i] < parts[i].length) {
        depth[i]++;
        more = true;
      }
    });
  }
  return new Map(tags.map((t, i) => [t, said(i)]));
}
