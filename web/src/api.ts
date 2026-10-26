// Calls to the scrap JSON API (docs/reference/api.md).
import type { Item } from "./queue";

export interface Ingest {
  state: "queued" | "processing" | "done" | "failed" | "paused";
  failures: number;
  error: string | null;
  text: string | null;
  description: string | null;
  image_kind: string | null;
  drawing: {
    id: number;
    version: number;
    producer: string;
    width: number | null; // its frame: the photo as sent to Claude
    height: number | null;
  } | null;
}
export interface FileRef {
  sha256: string;
  mime: string;
  size: number;
  filename: string | null;
  ingest?: Ingest | null; // photos: what Claude made of it (null: never queued)
}
export interface Queue {
  enabled: boolean;
  paused: boolean;
  reason: string | null;
  paused_until: string | null;
}
export interface Summary {
  id: string;
  slug: string;
  title: string;
  kind: string;
  fields: Record<string, string | number | boolean>; // e.g. a todo's status: open, done...
  created_at: string;
  updated_at: string;
  thumb: string | null;
  due?: string | null; // a todo's: YYYY-MM-DD
  priority?: string | null; // a todo's: high, medium or low
  snoozed_until?: string | null; // a todo's: out of Now until this day (YYYY-MM-DD)
  tasks?: { done: number; total: number }; // its task boxes: ticked, and in all
}
/** One version of a board page's write-up (writeup.ts). */
export interface WriteupVersion {
  version: number;
  producer: string; // the model that wrote it
  created_at: string;
  prompt_version: string;
  summary: string;
  text: string; // Markdown, its links [[slug]]
  guidance: string | null; // the owner's guidance it was written with
  restored_from: number | null; // a copy of this version, made by Restore
  current?: boolean; // in the versions list
  links?: string[]; // the current one's: the slugs of the pages it links that exist
}
/** A board page's write-up: Claude's explanation, apart from the text (#256). */
export interface Writeup {
  board: boolean; // a whiteboard or diagram page: one can be written
  topic?: boolean; // a topic page: its synthesis (#261)
  on: boolean; // Claude is on
  guidance: string | null; // the owner's, for the next one
  state: "queued" | "processing" | "done" | "failed" | "paused" | null;
  error: string | null;
  versions: number;
  outdated?: boolean; // the current one is older than the page or the prompt (#262)
  current: WriteupVersion | null;
}
export interface Page extends Summary {
  kind_fixed: number; // 1: the user chose the kind
  origin?: "human" | "claude" | "topic" | "gc"; // who made it (store/roles.py)
  body: string;
  rev: number;
  tags: string[];
  captures: { id: string; url: string | null; source: string; blobs: FileRef[] }[];
  removed?: string[]; // files an earlier revision's text embedded and this one doesn't
  model_tags?: string[]; // its tags Claude added (enrich.ts)
  related?: { id: string; slug: string; title: string; kind: string; via: string }[];
  enrich?: {
    on: boolean; // Claude reads text pages
    state: "queued" | "processing" | "done" | "failed" | "paused" | null;
    error: string | null;
    reason?: string | null; // why the queue is paused (state "paused")
    summary: string | null;
  } | null;
  writeup?: Writeup | null; // a board page's, or a topic's synthesis (writeup.ts)
  topics?: PageRef[]; // the topics it is a source of (#261)
  topic?: { key: string; sources: Source[] } | null; // set on a topic page
}
/** A link to a page. */
export interface PageRef {
  id: string;
  slug: string;
  title: string;
}
/** One of a topic's sources (topic.ts): excluded 1 when the owner took it out. */
export interface Source extends PageRef {
  kind: string;
  added_by: string;
  added_at: string;
  excluded: number;
}
/** A row of the topics index (GET /api/topics), grouped by area, the biggest first. */
export interface TopicRow extends PageRef {
  summary: string; // its synthesis's lead ("" before one)
  sources: number; // how many are in
  updated_at: string; // its synthesis's time, else the page's
  area: string | null; // the top-level tag most common among its sources
}
export interface Hit
  extends Pick<
    Summary,
    | "id"
    | "slug"
    | "title"
    | "kind"
    | "fields"
    | "updated_at"
    | "thumb"
    | "due"
    | "priority"
    | "snoozed_until"
    | "tasks"
  > {
  snippet: string;
  topic?: boolean; // a topic page (#261): labelled in the results
  tags: string[]; // for group:tag
  area?: string | null; // a topic's area, as GET /api/topics has it (group:area)
}

/** An error's detail as text: a string as is; a validation list's first "field: msg". */
export const say = (d: unknown): string | undefined => {
  const m = (Array.isArray(d) ? d[0] : d) as { loc?: string[]; msg?: string } | undefined;
  return typeof d === "string" ? d : m?.msg && [...(m.loc ?? []).slice(1), m.msg].join(": ");
};

export class ApiError extends Error {
  constructor(
    public status: number,
    public body: { detail?: unknown; rev?: number; version?: number | null },
  ) {
    super(say(body.detail) ?? `HTTP ${status}`);
  }
}

/** Ticks up as a change (a PATCH, POST, DELETE) starts and again as it ends. A refresh that
 * began at one value and ends at another overlapped a change: what it read may be from before
 * it, so it must not be drawn over the change (a tick shown, then undone). */
let writes = 0;
let inflight = 0;
/** A stamp for a read: compare it before and after (`stamp !== writeClock()`) and a change
 * began, ended or was under way meanwhile, so what was read may predate it. NaN while a change
 * is in flight, and NaN equals nothing. */
export const writeClock = () => (inflight ? Number.NaN : writes);

export async function api<T>(path: string, init?: RequestInit): Promise<T> {
  if (init?.method) {
    writes++;
    inflight++;
  }
  let r: Response;
  try {
    r = await fetch(`/api/${path}`, init);
  } finally {
    if (init?.method) {
      writes++;
      inflight--;
    }
  }
  if (!r.ok) throw new ApiError(r.status, await r.json().catch(() => ({})));
  if (init?.method) dispatchEvent(new Event("scrap:wrote")); // a change: e.g. the Todos badge
  return (r.status === 204 ? null : await r.json()) as T;
}

/** Tick a page off (or not): its status field only, no new revision. */
export const setStatus = (id: string, status: string) =>
  api<Page>(`pages/${id}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ fields: { status } }),
  });

/** Photos were added to a page: CustomEvent detail, the page now, with appended_on (the
 * revision its text was when their embeds went onto it). */
export const ADDED = "scrap:added";

/** Post a queued capture: JSON, or multipart with its files. Rejects if offline or stalled.
 *
 * XMLHttpRequest, not fetch, because only it reports upload progress: a slow upload that keeps
 * moving may take as long as it needs, but one with no progress for a minute is given up, so it
 * cannot hold the queue (and its lock in every tab) for ever. Progress counts bytes handed to
 * the phone's network stack, which may still hold a few MB when the upload "ends", so the answer
 * then gets a generous wait: at least 2 minutes, or the body at 5 KB/s. 15 minutes is the ceiling.
 */
export function send(
  item: Item,
  Xhr: typeof XMLHttpRequest = XMLHttpRequest,
  stallMs = 60_000,
): Promise<{ status: number; detail?: string }> {
  const { id, text, url, kind, hint, source, created_at, tags, due, priority, files } = item;
  const { page } = item; // photos for a page that exists: its own address
  const fields = page
    ? { id, source, created_at }
    : { id, text, url, kind, hint, source, created_at, tags, due, priority };
  let body: string | FormData = JSON.stringify(fields);
  if (files.length || page) {
    body = new FormData(); // its text fields go as CRLF; the server makes them LF
    // a field per tag
    for (const [k, v] of Object.entries(fields))
      for (const x of [v].flat()) if (x) body.append(k, x);
    for (const f of files) body.append("file", f.blob, f.name);
  }
  return new Promise((ok, fail) => {
    const xhr = new Xhr();
    let stall: ReturnType<typeof setTimeout> | undefined;
    const wait = (ms: number) => {
      clearTimeout(stall);
      stall = setTimeout(() => xhr.abort(), ms);
    };
    const moving = () => wait(stallMs);
    const size = files.reduce((n, f) => n + f.blob.size, 0);
    const sent = () => wait(Math.max(120_000, (size / 5120) * 1000));
    const timedOut = () => {
      clearTimeout(stall);
      fail(new DOMException("no upload progress", "TimeoutError"));
    };
    xhr.open("POST", page ? `/api/pages/${encodeURIComponent(page)}/captures` : "/api/captures");
    xhr.timeout = 15 * 60_000;
    xhr.upload.onprogress = moving;
    xhr.upload.onload = sent;
    xhr.onabort = xhr.ontimeout = timedOut;
    xhr.onerror = () => {
      clearTimeout(stall);
      fail(new TypeError("network error"));
    };
    xhr.onload = () => {
      clearTimeout(stall);
      let reply: { detail?: string } | undefined;
      try {
        reply = JSON.parse(xhr.responseText);
      } catch {}
      if (xhr.status >= 300) return ok({ status: xhr.status, detail: reply?.detail });
      // Added to a page: the page as it is now, for an editor open on it (pageedit.ts)
      if (page && reply) dispatchEvent(new CustomEvent(ADDED, { detail: reply }));
      ok({ status: xhr.status, detail: undefined });
    };
    if (typeof body === "string") xhr.setRequestHeader("Content-Type", "application/json");
    moving();
    xhr.send(body);
  });
}

export const blobUrl = (sha: string) => `/api/blobs/${sha}`;
/** A JPEG preview of a photo (HEIC too), upright: 480 px for lists, 2048 to view. */
export const previewUrl = (sha: string, size: 480 | 2048) =>
  `/api/blobs/${sha}/preview?size=${size}`;

/** This device's storage, which never throws: with no value, read key; with one, set it
 * (null removes it). null on any error: a private tab or blocked storage keeps nothing, and the
 * app works without it. Every use of localStorage goes through here. */
export function kept(key: string, value?: string | null): string | null {
  try {
    if (value === undefined) return localStorage.getItem(key);
    if (value === null) localStorage.removeItem(key);
    else localStorage.setItem(key, value);
  } catch {}
  return null;
}

const LIMIT = "scrap.max_upload_bytes";

/** The server's upload limit as last seen (0 if never), so the check works offline. */
export const uploadLimit = () => Number(kept(LIMIT)) || 0;

/** Whether bytes of files are too many to send in one request: over the limit, less room
 * for the form's other fields. False if the limit was never seen. */
export function overLimit(bytes: number) {
  const max = uploadLimit();
  return max > 0 && bytes > max - 64 * 1024;
}

export async function learnLimit() {
  try {
    const { max_upload_bytes } = await (await fetch("/healthz")).json();
    if (max_upload_bytes) kept(LIMIT, String(max_upload_bytes));
  } catch {} // offline: keep the last one
}

/** The stall limit, which tests may shorten (localStorage scrap.stall_ms, 1 s to 10 min). */
export function stallLimit(raw: string | null): number {
  const ms = Number(raw);
  return raw && Number.isFinite(ms) && ms >= 1000 && ms <= 600_000 ? ms : 60_000;
}

/** The file to share for a photo: its address, name and type. The original if other apps
 * can read it and it is not huge, else (HEIC, say) the 2048 px JPEG preview. The name
 * always ends in its type's extension: Android refuses files it can't tell the type of. */
export function shareable(f: FileRef): [string, string, string] {
  const original = /^image\/(jpeg|png|gif|webp)$/.test(f.mime) && f.size <= 20 * 2 ** 20;
  const type = original ? f.mime : "image/jpeg";
  const ext = type === "image/jpeg" ? "jpg" : type.split("/")[1];
  let name = f.filename || f.sha256.slice(0, 12);
  if (!original) name = name.replace(/\.[^.]*$/, ""); // IMG_1.HEIC is shared as IMG_1.jpg
  if (!new RegExp(`\\.(${ext}${ext === "jpg" ? "|jpeg" : ""})$`, "i").test(name))
    name = `${name}.${ext}`;
  return [original ? blobUrl(f.sha256) : previewUrl(f.sha256, 2048), name, type];
}
