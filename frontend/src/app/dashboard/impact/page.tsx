"use client";
// Impact: "Before HAIP" vs "With HAIP" for the go-live date (owner + manager). Before = the owner's own figures (owner-entered)
// or what HAIP recorded before go-live (measured); With HAIP = measured in the latest window. Backend: GET /dashboard/impact.
import { useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Download, SlidersHorizontal } from "lucide-react";
import api from "@/lib/api";
import { Card, CardBody, CardHeader, EmptyState, PageHeader } from "@/components/ui/kit";
import { Skeleton } from "@/components/ui/skeleton";
import { useToast } from "@/components/ui/toast";
import { BaselineEditor } from "@/components/impact/BaselineEditor";
import { CaseStudyCard } from "@/components/impact/CaseStudyCard";
import { ImpactTile } from "@/components/impact/ImpactTile";
import { RevenueChart } from "@/components/impact/RevenueChart";
import { AfterHoursCard, CallsCard, CohortCard, LostCard, RepliesCard } from "@/components/impact/Sections";
import { formatDay, formatPeriod, type ImpactView } from "@/components/impact/types";

const field = "mt-1 w-full min-h-11 rounded-lg border border-[var(--haip-border)] bg-[var(--haip-card)] px-3 text-base text-[var(--haip-fg)] focus:outline-none focus:ring-2 focus:ring-primary sm:min-h-10 sm:text-sm";
const WINDOWS = [7, 14, 30, 60, 90];
const btn = "inline-flex min-h-11 items-center gap-2 rounded-lg border border-[var(--haip-border)] bg-[var(--haip-card)] px-4 text-sm font-semibold text-[var(--haip-fg)] disabled:opacity-50 sm:min-h-10";

function apiError(e: unknown): string {
  const d = (e as { response?: { data?: { detail?: unknown } } })?.response?.data?.detail;
  if (typeof d === "string") return d;
  if (Array.isArray(d) && d[0] && typeof d[0].msg === "string") return String(d[0].msg);
  return "Something went wrong. Try again.";
}

export default function ImpactPage() {
  const { toast } = useToast();
  const queryClient = useQueryClient();
  const [goLive, setGoLive] = useState<string>("");
  const [days, setDays] = useState<number | null>(null);
  const [editing, setEditing] = useState(false);
  const [downloading, setDownloading] = useState(false);

  const params = { ...(goLive ? { go_live: goLive } : {}), ...(days ? { days } : {}) };
  const { data, isPending, isError, error, refetch, isFetching } = useQuery<ImpactView>({
    queryKey: ["impact", params], queryFn: () => api.get("/dashboard/impact", { params }).then(r => r.data),
    placeholderData: prev => prev,
  });
  useEffect(() => {
    if (data && !goLive && data.saved.go_live) setGoLive(data.saved.go_live);
    if (data && days == null) setDays(data.saved.days);
  }, [data, goLive, days]);

  const saveSettings = useMutation({
    mutationFn: () => api.put("/dashboard/impact/settings", { go_live_date: goLive, window_days: days ?? 30 }),
    onSuccess: () => { queryClient.invalidateQueries({ queryKey: ["impact"] }); toast({ variant: "success", title: "Go-live date saved" }); },
    onError: e => toast({ variant: "error", title: apiError(e) }),
  });

  async function downloadPdf() {
    setDownloading(true);
    try {
      const r = await api.get("/dashboard/impact/export.pdf", { params, responseType: "blob" });
      const url = URL.createObjectURL(r.data as Blob);
      const a = document.createElement("a");
      a.href = url; a.download = `impact-${new Date().toISOString().slice(0, 10)}.pdf`; a.click();
      URL.revokeObjectURL(url);
    } catch {
      toast({ variant: "error", title: "Couldn't make the PDF. Try again." });
    } finally {
      setDownloading(false);
    }
  }

  if (isPending) {
    return (
      <div className="mx-auto max-w-6xl space-y-4 p-4 sm:p-6">
        <Skeleton className="h-10 w-56 rounded-lg" /><Skeleton className="h-24 rounded-2xl" />
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3">{[0, 1, 2, 3, 4, 5].map(i => <Skeleton key={i} className="h-40 rounded-2xl" />)}</div>
      </div>
    );
  }
  if (isError || !data) {
    const status = (error as { response?: { status?: number } } | null)?.response?.status;
    return (
      <div role="alert" className="mx-auto max-w-2xl p-6 py-16 text-center">
        <p className="text-base font-semibold text-[var(--haip-fg)]">{status === 403 ? "Only owners and managers can see this page" : "Couldn't load the impact view"}</p>
        {status !== 403 && <p className="mt-1 text-sm text-[var(--haip-fg-subtle)]">{apiError(error)}</p>}
        {status !== 403 && <button type="button" onClick={() => refetch()} className="mt-4 min-h-11 rounded-lg bg-primary px-4 text-sm font-semibold text-primary-foreground">Try again</button>}
      </div>
    );
  }

  const canEdit = data.can_edit;
  const unsaved = !!goLive && (goLive !== data.saved.go_live || (days ?? 30) !== data.saved.days);
  const brand = data.tenant_name || "Our workspace";

  return (
    <div className="mx-auto max-w-6xl space-y-5 p-4 sm:p-6">
      <PageHeader title="Impact" subtitle="What changed since HAIP went live: your own before-figures next to what HAIP measures now."
        actions={<>
          <button type="button" className={btn} onClick={() => setEditing(true)}><SlidersHorizontal size={16} />Before-HAIP figures</button>
          <button type="button" className={btn} disabled={data.needs_go_live || downloading} onClick={downloadPdf}>
            <Download size={16} />{downloading ? "Preparing…" : "Download PDF"}
          </button>
        </>} />

      <Card>
        <CardBody className="flex flex-wrap items-end gap-3">
          <label className="block w-full text-xs font-medium text-[var(--haip-fg-subtle)] sm:w-48">Go-live date (IST)
            <input type="date" className={field} value={goLive} max={new Date().toLocaleDateString("en-CA", { timeZone: "Asia/Kolkata" })} onChange={e => setGoLive(e.target.value)} />
          </label>
          <label className="block w-full text-xs font-medium text-[var(--haip-fg-subtle)] sm:w-40">Compare windows of
            <select className={field} value={days ?? 30} onChange={e => setDays(Number(e.target.value))}>
              {WINDOWS.map(d => <option key={d} value={d}>{d} days</option>)}
            </select>
          </label>
          {canEdit && unsaved && (
            <button type="button" disabled={saveSettings.isPending} onClick={() => saveSettings.mutate()}
              className="min-h-11 rounded-lg bg-primary px-4 text-sm font-semibold text-primary-foreground disabled:opacity-50 sm:min-h-10">
              {saveSettings.isPending ? "Saving…" : "Save as default"}
            </button>
          )}
          {!data.needs_go_live && (
            <p className="w-full text-[12.5px] text-[var(--haip-fg-subtle)] sm:w-auto sm:flex-1 sm:text-right" aria-live="polite">
              {isFetching ? "Updating…" : <>Before: {formatPeriod(data.windows.before)} · With HAIP: {formatPeriod(data.windows.with)}</>}
            </p>
          )}
        </CardBody>
      </Card>

      {data.needs_go_live ? (
        <Card><EmptyState title="When did HAIP go live?"
          hint={canEdit ? "Pick the go-live date above and save it. The page compares the days before it with the latest days since."
            : "Pick a go-live date above to preview, or ask the owner to save one."} /></Card>
      ) : (
        <>
          <section aria-label="Before and after" className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3">
            {data.tiles.map(t => <ImpactTile key={t.key} tile={t} />)}
          </section>
          <RepliesCard before={data.before} after={data.with} />
          <AfterHoursCard after={data.with} />
          <div className="grid grid-cols-1 gap-5 lg:grid-cols-2">
            <CohortCard before={data.before} after={data.with} />
            <CallsCard before={data.before} after={data.with} />
          </div>
          <LostCard before={data.before} after={data.with} />
          <Card>
            <CardHeader title="Revenue per month" description={`IST calendar months; HAIP went live on ${formatDay(data.go_live)}. Bookings by the day they were made; cash by payment date.`} />
            <CardBody>
              {data.revenue.restricted
                ? <p className="text-[13.5px] text-[var(--haip-fg-subtle)]">Needs revenue access to show.</p>
                : <RevenueChart months={data.revenue.months} goLiveMonth={data.revenue.go_live_month} />}
            </CardBody>
          </Card>
          <ul className="list-disc space-y-1 pl-5 text-[12.5px] text-[var(--haip-fg-subtle)]">
            {data.notes.map(n => <li key={n}>{n}</li>)}
          </ul>
        </>
      )}

      <CaseStudyCard brand={brand} canRevenue={data.can_revenue} ready={!!data.saved.go_live} />
      <BaselineEditor open={editing} onOpenChange={setEditing} />
    </div>
  );
}
