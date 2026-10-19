// Calls to the scrap JSON API (docs/reference/api.md).
import type { Item } from "./queue";

export interface FileRef {
  sha256: string;
  mime: string;
  size: number;
  filename: string | null;
}
export interface Summary {
  id: string;
  slug: string;
  title: string;
  kind: string;
  created_at: string;
  updated_at: string;
  thumb: string | null;
}
export interface Page extends Summary {
  body: string;
  rev: number;
  captures: { id: string; url: string | null; blobs: FileRef[] }[];
}
export interface Hit {
  slug: string;
  title: string;
  kind: string;
  snippet: string;
}

export class ApiError extends Error {
  constructor(
    public status: number,
    public body: { detail?: string; rev?: number },
  ) {
    super(body.detail ?? `HTTP ${status}`);
  }
}

export async function api<T>(path: string, init?: RequestInit): Promise<T> {
  const r = await fetch(`/api/${path}`, init);
  if (!r.ok) throw new ApiError(r.status, await r.json().catch(() => ({})));
  return (r.status === 204 ? null : await r.json()) as T;
}

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
  const { id, text, url, hint, source, created_at, files } = item;
  const fields = { id, text, url, hint, source, created_at };
  let body: string | FormData = JSON.stringify(fields);
  if (files.length) {
    body = new FormData(); // its text fields go as CRLF; the server makes them LF
    for (const [k, v] of Object.entries(fields)) if (v) body.append(k, v);
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

const LIMIT = "scrap.max_upload_bytes";

/** The server's upload limit as last seen (0 if never), so the check works offline. */
export const uploadLimit = () => Number(localStorage.getItem(LIMIT)) || 0;

export async function learnLimit() {
  try {
    const { max_upload_bytes } = await (await fetch("/healthz")).json();
    if (max_upload_bytes) localStorage.setItem(LIMIT, String(max_upload_bytes));
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
