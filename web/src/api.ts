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

/** Post a queued capture: JSON, or multipart with its files. Rejects if offline. */
export async function send(item: Item): Promise<{ status: number; detail?: string }> {
  const { id, text, url, hint, source, created_at, files } = item;
  const fields = { id, text, url, hint, source, created_at };
  let init: RequestInit = {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(fields),
  };
  if (files.length) {
    const form = new FormData(); // its text fields go as CRLF; the server makes them LF
    for (const [k, v] of Object.entries(fields)) if (v) form.append(k, v);
    for (const f of files) form.append("file", f.blob, f.name);
    init = { method: "POST", body: form };
  }
  const r = await fetch("/api/captures", init);
  const detail = r.ok ? undefined : (await r.json().catch(() => ({}))).detail;
  return { status: r.status, detail };
}

export const blobUrl = (sha: string) => `/api/blobs/${sha}`;
