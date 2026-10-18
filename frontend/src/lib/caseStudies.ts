// Server-side reads of the PUBLIC case-study snapshots (GET /api/v1/case-studies[/{slug}], no auth). Any failure reads as
// "nothing published" so the marketing page shows "coming soon" rather than an error or stale placeholder numbers.
import type { PublicSnapshot } from "@/components/impact/types";

export interface PublishedCaseStudy { slug: string; snapshot: PublicSnapshot; published_at: string | null }

function apiBase(): string {
  const raw = (process.env.BACKEND_URL ?? process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000").replace(/\/$/, "");
  return raw.endsWith("/api/v1") ? raw : `${raw}/api/v1`;
}

async function getJson<T>(path: string): Promise<T | null> {
  try {
    const r = await fetch(`${apiBase()}${path}`, { next: { revalidate: 300 } });
    if (!r.ok) return null;
    return (await r.json()) as T;
  } catch {
    return null;
  }
}

export async function fetchCaseStudy(slug: string): Promise<PublishedCaseStudy | null> {
  const d = await getJson<{ status: string } & Partial<PublishedCaseStudy>>(`/case-studies/${encodeURIComponent(slug)}`);
  return d && d.status === "published" && d.snapshot ? { slug: d.slug ?? slug, snapshot: d.snapshot, published_at: d.published_at ?? null } : null;
}

export async function fetchCaseStudies(): Promise<PublishedCaseStudy[]> {
  const d = await getJson<{ items: PublishedCaseStudy[] }>("/case-studies");
  return d?.items ?? [];
}
