"use client";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { AlertTriangle, Info, RefreshCw, Loader2 } from "@/lib/icons";
import api from "@/lib/api";
import { cn, timeAgo } from "@/lib/utils";
import { Skeleton } from "@/components/ui/skeleton";
import { useToast } from "@/components/ui/toast";
import { Card, CardBody, CardHeader, StatusPill } from "@/components/ui/kit";
import { SourceBadge } from "./SourceBadge";

/** GET /knowledge/freshness (backend services/knowledge_freshness.py). Hand-written: there is no OpenAPI generator. */
export interface FreshnessSource {
  source: string;
  label: string;
  total: number;
  used_by_bot: number;
  waiting_approval: number;
  indexing: number;
  failed: number;
  gave_up: number;
  out_of_date: number;
  flagged_price: number;
  last_updated: string | null;
  last_indexed: string | null;
}

export interface KnowledgeSettings {
  auto_approve_social: boolean;
  social_sync: boolean;
  website_recrawl: boolean;
  social_max_age_days: number;
}

export interface FreshnessReport {
  generated_at: string;
  settings: KnowledgeSettings;
  price_mode: string;
  sources: FreshnessSource[];
  business_data: { published: number; drafts: number; scheduled: number; last_published_at: string | null };
  records: { properties: number; properties_last_updated: string | null; rate_tables_last_updated: string | null };
  instagram: { connected: boolean; sync_enabled: boolean; last_run_at: string | null; last_ok_at: string | null; last_error: string | null };
  website: { pages: number; recrawl_enabled: boolean; last_read_at: string | null };
  warnings: { code: string; level: "warning" | "info"; text: string }[];
}

const when = (iso: string | null | undefined) => (iso ? timeAgo(iso) : "never");

function SettingToggle({ label, hint, checked, disabled, onChange }: {
  label: string; hint: string; checked: boolean; disabled?: boolean; onChange: (v: boolean) => void;
}) {
  return (
    <label className="flex min-h-11 cursor-pointer items-start gap-3 py-2">
      <input
        type="checkbox"
        className="mt-1 h-5 w-5 flex-shrink-0 accent-[var(--primary)]"
        checked={checked}
        disabled={disabled}
        onChange={(e) => onChange(e.target.checked)}
      />
      <span className="min-w-0">
        <span className="block text-[14px] font-semibold text-[var(--haip-fg)]">{label}</span>
        <span className="block text-[12.5px] text-[var(--haip-fg-subtle)]">{hint}</span>
      </span>
    </label>
  );
}

export function KnowledgeFreshnessPanel() {
  const queryClient = useQueryClient();
  const { toast } = useToast();
  const { data, isPending, isError, error, refetch } = useQuery<FreshnessReport>({
    queryKey: ["knowledge-freshness"],
    queryFn: () => api.get("/knowledge/freshness").then((r) => r.data),
    retry: (count, err) => (err as { response?: { status?: number } })?.response?.status !== 403 && count < 1,
  });

  const invalidate = () => {
    for (const key of ["knowledge-freshness", "knowledge", "knowledge-stats", "knowledge-approvals"]) {
      queryClient.invalidateQueries({ queryKey: [key] });
    }
  };

  const refresh = useMutation({
    mutationFn: () => api.post("/knowledge/refresh").then((r) => r.data as { queued_for_indexing: number; instagram_sync_queued: boolean }),
    onSuccess: (d) => {
      invalidate();
      const parts = [d.queued_for_indexing ? `${d.queued_for_indexing} item(s) re-indexing` : "Nothing needed re-indexing"];
      if (d.instagram_sync_queued) parts.push("reading Instagram now");
      toast({ variant: "success", title: "Refresh started", description: parts.join("; ") + "." });
    },
    onError: () => toast({ variant: "error", title: "Couldn't start the refresh", description: "Try again in a minute." }),
  });

  const saveSetting = useMutation({
    mutationFn: (patch: Partial<KnowledgeSettings>) => api.put("/knowledge/source-settings", patch).then((r) => r.data),
    onSuccess: () => {
      invalidate();
      toast({ variant: "success", title: "Saved" });
    },
    onError: () => toast({ variant: "error", title: "Couldn't save that setting" }),
  });

  // Owner and manager only: everyone else simply does not see the panel.
  if (isError && (error as { response?: { status?: number } })?.response?.status === 403) return null;

  return (
    <Card>
      <CardHeader
        title="What the bot knows"
        description="Right now, per source: what the bot uses, and why the rest is not used yet."
        actions={
          <button
            type="button"
            onClick={() => refresh.mutate()}
            disabled={refresh.isPending || isPending}
            className="inline-flex min-h-11 items-center gap-1.5 rounded-full bg-primary px-4 text-[14px] font-semibold text-white disabled:opacity-50 sm:min-h-9"
          >
            {refresh.isPending ? <Loader2 size={15} className="animate-spin" /> : <RefreshCw size={15} />} Re-index now
          </button>
        }
      />
      <CardBody className="space-y-4">
        {isPending ? (
          <div className="space-y-2" aria-label="Loading">
            <Skeleton className="h-6 w-2/3" />
            <Skeleton className="h-16" />
            <Skeleton className="h-16" />
          </div>
        ) : isError || !data ? (
          <div className="flex flex-wrap items-center gap-3 text-[14px] text-[var(--haip-status-danger-fg)]">
            Couldn&apos;t load what the bot knows.
            <button type="button" onClick={() => refetch()} className="min-h-11 font-semibold underline sm:min-h-0">Try again</button>
          </div>
        ) : (
          <>
            {data.warnings.length > 0 && (
              <ul className="space-y-1.5">
                {data.warnings.map((w) => (
                  <li key={w.code} className="flex items-start gap-2 text-[13.5px] leading-snug">
                    {w.level === "warning"
                      ? <AlertTriangle size={15} className="mt-0.5 flex-shrink-0 text-[var(--haip-status-warning-fg)]" />
                      : <Info size={15} className="mt-0.5 flex-shrink-0 text-[var(--haip-fg-subtle)]" />}
                    <span className={cn(w.level === "warning" ? "text-[var(--haip-fg)]" : "text-[var(--haip-fg-muted)]")}>{w.text}</span>
                  </li>
                ))}
              </ul>
            )}

            {data.sources.length === 0 ? (
              <p className="text-[13.5px] text-[var(--haip-fg-subtle)]">No knowledge yet. Add some below, import your website, or connect Instagram.</p>
            ) : (
              <ul className="divide-y divide-[var(--haip-border)] rounded-xl border border-[var(--haip-border)]">
                {data.sources.map((s) => (
                  <li key={s.source} className="flex flex-wrap items-center gap-x-3 gap-y-1.5 px-3 py-2.5">
                    <SourceBadge source={s.source} />
                    <span className="text-[14px] font-semibold tabular-nums text-[var(--haip-fg)]">{s.used_by_bot} used</span>
                    <span className="text-[12.5px] text-[var(--haip-fg-subtle)]">of {s.total}</span>
                    {s.waiting_approval > 0 && <StatusPill tone="warning">{s.waiting_approval} waiting approval</StatusPill>}
                    {s.indexing > 0 && <StatusPill tone="info">{s.indexing} indexing</StatusPill>}
                    {s.failed > 0 && <StatusPill tone="danger">{s.failed} failed</StatusPill>}
                    {s.out_of_date > 0 && <StatusPill tone="neutral">{s.out_of_date} out of date</StatusPill>}
                    <span className="w-full text-[12px] text-[var(--haip-fg-subtle)] sm:ml-auto sm:w-auto">
                      updated {when(s.last_updated)} · indexed {when(s.last_indexed)}
                    </span>
                  </li>
                ))}
              </ul>
            )}

            <dl className="grid grid-cols-1 gap-x-6 gap-y-2 text-[13px] sm:grid-cols-2">
              <div>
                <dt className="text-[var(--haip-fg-subtle)]">Packages, routes and policies</dt>
                <dd className="text-[var(--haip-fg)]">
                  {data.business_data.published} published (used) · {data.business_data.drafts} draft(s) (not used)
                  {data.business_data.scheduled > 0 && ` · ${data.business_data.scheduled} scheduled`} · last published {when(data.business_data.last_published_at)}
                </dd>
              </div>
              <div>
                <dt className="text-[var(--haip-fg-subtle)]">Property records</dt>
                <dd className="text-[var(--haip-fg)]">{data.records.properties} active · updated {when(data.records.properties_last_updated)}</dd>
              </div>
              <div>
                <dt className="text-[var(--haip-fg-subtle)]">Instagram</dt>
                <dd className="text-[var(--haip-fg)]">
                  {data.instagram.connected
                    ? `read ${when(data.instagram.last_ok_at)}${data.instagram.last_error ? ` · last try failed: ${data.instagram.last_error}` : ""}`
                    : "not connected"}
                </dd>
              </div>
              <div>
                <dt className="text-[var(--haip-fg-subtle)]">Website</dt>
                <dd className="text-[var(--haip-fg)]">{data.website.pages} page(s) imported · read {when(data.website.last_read_at)}</dd>
              </div>
            </dl>

            <div className="border-t border-[var(--haip-border)] pt-2">
              <SettingToggle
                label="Read Instagram posts and running ads"
                hint="Every 4 hours. New posts wait for your approval below unless you turn on auto-approve."
                checked={data.settings.social_sync}
                disabled={saveSetting.isPending}
                onChange={(v) => saveSetting.mutate({ social_sync: v })}
              />
              <SettingToggle
                label="Use new posts without asking me"
                hint="Posts that quote a price still wait for you. Prices always come from your published rates."
                checked={data.settings.auto_approve_social}
                disabled={saveSetting.isPending}
                onChange={(v) => saveSetting.mutate({ auto_approve_social: v })}
              />
              <SettingToggle
                label="Re-read my website pages every week"
                hint="Changed text waits for your approval; text removed from a page stops being used."
                checked={data.settings.website_recrawl}
                disabled={saveSetting.isPending}
                onChange={(v) => saveSetting.mutate({ website_recrawl: v })}
              />
            </div>
          </>
        )}
      </CardBody>
    </Card>
  );
}
