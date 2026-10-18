"use client";
// "Publish to case study": freezes today's aggregate numbers into the public page /case-studies/{slug}. Nothing is public before
// the owner clicks it; "Take down" returns the page to "coming soon". No guest data is ever published.
import { useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import api from "@/lib/api";
import { Card, CardBody, CardHeader, StatusPill } from "@/components/ui/kit";
import { Skeleton } from "@/components/ui/skeleton";
import { useToast } from "@/components/ui/toast";
import type { CaseStudyStatus } from "./types";

const field = "mt-1 w-full min-h-11 rounded-lg border border-[var(--haip-border)] bg-[var(--haip-card)] px-3 text-base text-[var(--haip-fg)] focus:outline-none focus:ring-2 focus:ring-primary sm:min-h-10 sm:text-sm";
const label = "block text-xs font-medium text-[var(--haip-fg-subtle)]";

function apiError(e: unknown): string {
  const d = (e as { response?: { data?: { detail?: unknown } } })?.response?.data?.detail;
  if (typeof d === "string") return d;
  if (Array.isArray(d) && d[0] && typeof d[0].msg === "string") return String(d[0].msg).replace(/^Value error, /, "");
  return "Could not publish. Try again.";
}

export function CaseStudyCard({ brand, canRevenue, ready }: { brand: string; canRevenue: boolean; ready: boolean }) {
  const { toast } = useToast();
  const queryClient = useQueryClient();
  const { data, isPending, isError, refetch } = useQuery<CaseStudyStatus>({
    queryKey: ["impact-case-study"], queryFn: () => api.get("/dashboard/impact/case-study").then(r => r.data),
  });
  const [slug, setSlug] = useState("");
  const [brandName, setBrandName] = useState(brand);
  const [headline, setHeadline] = useState("");
  const [summary, setSummary] = useState("");
  const [money, setMoney] = useState(false);
  useEffect(() => {
    if (!data) return;
    const s = data.snapshot;
    setSlug(data.slug ?? brand.toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "").slice(0, 40));
    if (s) { setBrandName(s.brand_name); setHeadline(s.headline ?? ""); setSummary(s.summary ?? ""); setMoney(s.includes_revenue); }
  }, [data, brand]);

  const done = (title: string) => (res: { data: CaseStudyStatus }) => {
    queryClient.setQueryData(["impact-case-study"], { ...res.data, can_edit: data?.can_edit ?? false });
    toast({ variant: "success", title });
  };
  const publish = useMutation({
    mutationFn: () => api.post<CaseStudyStatus>("/dashboard/impact/case-study/publish",
      { slug, brand_name: brandName, headline: headline || null, summary: summary || null, include_revenue: money }),
    onSuccess: done("Published. The case-study page now shows these numbers."),
    onError: e => toast({ variant: "error", title: apiError(e) }),
  });
  const withdraw = useMutation({
    mutationFn: () => api.post<CaseStudyStatus>("/dashboard/impact/case-study/withdraw"),
    onSuccess: done("Taken down. The page says coming soon again."),
    onError: e => toast({ variant: "error", title: apiError(e) }),
  });

  const pill = data?.status === "published" ? <StatusPill tone="success">Published</StatusPill>
    : data?.status === "withdrawn" ? <StatusPill tone="neutral">Taken down</StatusPill> : <StatusPill tone="neutral">Not published</StatusPill>;
  return (
    <Card>
      <CardHeader title="Case study" actions={data && pill}
        description="Publishes a frozen copy of these numbers (no guest data) to the public case-study page. Later changes do not update it until you publish again." />
      <CardBody>
        {isPending ? <Skeleton className="h-40 rounded-xl" /> : isError || !data ? (
          <div role="alert" className="text-sm"><p className="font-semibold text-[var(--haip-fg)]">Couldn&apos;t load the case-study status</p>
            <button type="button" onClick={() => refetch()} className="mt-2 min-h-11 rounded-lg border border-[var(--haip-border)] px-4 font-semibold">Try again</button></div>
        ) : (
          <div className="space-y-3">
            {data.status === "published" && data.slug && (
              <p className="text-[13.5px] text-[var(--haip-fg-muted)]">
                Live at <a className="font-semibold text-primary underline-offset-2 hover:underline" href={`/case-studies/${data.slug}`} target="_blank" rel="noreferrer">/case-studies/{data.slug}</a>
                {data.published_at && <> · published {new Date(data.published_at).toLocaleString("en-IN", { timeZone: "Asia/Kolkata", dateStyle: "medium", timeStyle: "short" })} IST</>}
              </p>
            )}
            {!data.can_edit ? <p className="text-[13px] text-[var(--haip-fg-subtle)]">Only the owner can publish.</p> : (
              <>
                <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
                  <label className={label}>Brand name shown<input className={field} maxLength={80} value={brandName} onChange={e => setBrandName(e.target.value)} /></label>
                  <label className={label}>Link name<input className={field} maxLength={40} value={slug} onChange={e => setSlug(e.target.value.toLowerCase())} autoCapitalize="none" spellCheck={false} />
                    <span className="mt-1 block text-xs text-[var(--haip-fg-subtle)]">/case-studies/{slug || "…"}</span></label>
                  <label className={`${label} sm:col-span-2`}>Headline (optional)<input className={field} maxLength={160} value={headline} onChange={e => setHeadline(e.target.value)} placeholder="Every enquiry answered, day and night" /></label>
                  <label className={`${label} sm:col-span-2`}>Summary (optional)<textarea rows={3} className={`${field} py-2`} maxLength={1200} value={summary} onChange={e => setSummary(e.target.value)} /></label>
                </div>
                <label className="flex min-h-11 items-center gap-2 text-sm text-[var(--haip-fg)]">
                  <input type="checkbox" className="size-5" checked={money} disabled={!canRevenue} onChange={e => setMoney(e.target.checked)} />
                  Include bookings value and cash collected (public)
                </label>
                <div className="flex flex-wrap gap-2">
                  <button type="button" disabled={!ready || !slug || !brandName.trim() || publish.isPending} onClick={() => publish.mutate()}
                    className="min-h-11 rounded-lg bg-primary px-4 text-sm font-semibold text-primary-foreground disabled:opacity-50">
                    {publish.isPending ? "Publishing…" : data.status === "published" ? "Publish again with today’s numbers" : "Publish to case study"}
                  </button>
                  {data.status === "published" && (
                    <button type="button" disabled={withdraw.isPending} onClick={() => withdraw.mutate()}
                      className="min-h-11 rounded-lg border border-[var(--haip-border)] px-4 text-sm font-semibold text-[var(--haip-fg-muted)] disabled:opacity-50">Take down</button>
                  )}
                </div>
                {!ready && <p className="text-[12.5px] text-[var(--haip-fg-subtle)]">Save the go-live date first.</p>}
              </>
            )}
          </div>
        )}
      </CardBody>
    </Card>
  );
}
