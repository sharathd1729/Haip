// Called by HAIP (Celery website.revalidate) after a publish or a settings change.
import { revalidateTag } from "next/cache";
import { timingSafeEqual } from "node:crypto";
import { cleanHost } from "@/lib/haip";

export async function POST(req: Request) {
  const want = process.env.SITES_REVALIDATE_SECRET || "";
  const got = req.headers.get("x-haip-secret") || "";
  if (!want || got.length !== want.length || !timingSafeEqual(Buffer.from(got), Buffer.from(want))) {
    return new Response("Forbidden", { status: 403 });
  }
  const body = await req.json().catch(() => ({}));
  const hosts: string[] = (Array.isArray(body.hosts) ? body.hosts : []).map((h: unknown) => cleanHost(String(h))).filter(Boolean).slice(0, 10);
  for (const h of hosts) revalidateTag(`site:${h}`, "max");
  return Response.json({ revalidated: hosts });
}
