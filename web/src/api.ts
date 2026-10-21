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
export interface Page extends Summary {
  kind_fixed: number; // 1: the user chose the kind
  body: string;
  rev: number;
  tags: string[];
  captures: { id: string; url: string | null; source: string; blobs: FileRef[] }[];
  removed?: string[]; // files an earlier revision's text embedded and this one doesn't
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
}

export class ApiError extends Error {
  constructor(
    public status: number,
    public body: { detail?: string; rev?: number; version?: number | null },
  ) {
    super(body.detail ?? `HTTP ${status}`);
  }
}

export async function api<T>(path: string, init?: RequestInit): Promise<T> {
  const r = await fetch(`/api/${path}`, init);
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
  const fields = { id, text, url, kind, hint, source, created_at, tags, due, priority };
  let body: string | FormData = JSON.stringify(fields);
  if (files.length) {
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
    xhr.open("POST", "/api/captures");
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
      let detail: string | undefined;
      if (xhr.status >= 300) {
        try {
          detail = JSON.parse(xhr.responseText).detail;
        } catch {}
      }
      ok({ status: xhr.status, detail });
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

/** A setting kept on this phone (localStorage): set it (null: drop it) if v is given; read
 * it. Nothing, never an error, where the phone keeps none (a private tab, blocked storage). */
export function kept(k: string, v?: string | null): string | null {
  try {
    if (v === null) localStorage.removeItem(k);
    else if (v !== undefined) localStorage.setItem(k, v);
    return localStorage.getItem(k);
  } catch {
    return null;
  }
}

const LIMIT = "scrap.max_upload_bytes";

/** The server's upload limit as last seen (0 if never), so the check works offline. */
export const uploadLimit = () => Number(kept(LIMIT)) || 0;

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
