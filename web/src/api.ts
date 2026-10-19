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

/** Post a queued capture as multipart; the status, for the queue to act on. */
export async function send(item: Item): Promise<number> {
  const form = new FormData();
  for (const k of ["id", "text", "url", "hint", "source", "created_at"] as const) {
    const v = item[k];
    if (v) form.append(k, v);
  }
  for (const f of item.files) form.append("file", f.blob, f.name);
  return (await fetch("/api/captures", { method: "POST", body: form })).status;
}

export const blobUrl = (sha: string) => `/api/blobs/${sha}`;
