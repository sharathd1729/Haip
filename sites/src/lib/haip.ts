// Server-side access to the HAIP guest API. HAIP_API_URL is the internal API address (never sent to browsers).
import type { LiveData, SiteEnv, Stay } from "@/site-blocks/types";

export function apiRoot(): string {
  const raw = (process.env.HAIP_API_URL || "http://localhost:8000").replace(/\/$/, "");
  return raw.endsWith("/api/v1") ? raw : `${raw}/api/v1`;
}

export function cleanHost(raw: string | null | undefined): string {
  const h = (raw || "").split(",")[0].trim().toLowerCase().split(":")[0].replace(/\.$/, "");
  return /^[a-z0-9.-]{3,253}$/.test(h) ? h : "";
}

/** The hostname this request is for. Local development maps localhost to DEV_SITE_HOST. */
export function siteHost(headerHost: string | null): string {
  const h = cleanHost(headerHost);
  if ((h === "localhost" || h === "127.0.0.1") && process.env.DEV_SITE_HOST) return cleanHost(process.env.DEV_SITE_HOST);
  return h;
}

export async function getLive(host: string): Promise<LiveData | null> {
  const r = await fetch(`${apiRoot()}/public/sites/${encodeURIComponent(host)}/bootstrap`,
    { next: { revalidate: 300, tags: [`site:${host}`] } });
  if (r.status === 404) return null;
  if (!r.ok) throw new Error(`HAIP ${r.status}`);
  return r.json();
}

export async function getPreview(token: string): Promise<LiveData | null> {
  const r = await fetch(`${apiRoot()}/public/preview/${encodeURIComponent(token)}/bootstrap`, { cache: "no-store" });
  return r.ok ? r.json() : null;
}

export async function getStay(host: string, slug: string, preview?: string): Promise<Stay | null> {
  const url = preview ? `${apiRoot()}/public/preview/${encodeURIComponent(preview)}/stays/${slug}`
    : `${apiRoot()}/public/sites/${encodeURIComponent(host)}/stays/${slug}`;
  const r = await fetch(url, preview ? { cache: "no-store" } : { next: { revalidate: 300, tags: [`site:${host}`] } });
  return r.ok ? r.json() : null;
}

export function envFor(live: LiveData, opts: { mode: "live" | "preview"; base: string; query: Record<string, string>; stay?: Stay | null; mediaBase: string }): SiteEnv {
  const assets: SiteEnv["assets"] = {};
  for (const [id, a] of Object.entries(live.assets)) assets[id] = { src: `${opts.mediaBase}/${id}`, alt: a.alt };
  return { mode: opts.mode, base: opts.base, apiBase: opts.mode === "live" ? "/_haip/api" : null, assets, stay: opts.stay ?? null, query: opts.query };
}

export function queryOf(sp: Record<string, string | string[] | undefined>): Record<string, string> {
  const out: Record<string, string> = {};
  for (const [k, v] of Object.entries(sp)) if (typeof v === "string" && v.length < 200) out[k] = v;
  return out;
}
