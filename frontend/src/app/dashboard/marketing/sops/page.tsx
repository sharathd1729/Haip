"use client";
// Marketing › Get found (dynamic SOPs, docs/sops/DYNAMIC_SOPS_PLAN.md): step-by-step checklists for the work HAIP cannot do
// for you (Google profile, Instagram, WhatsApp profile), filled with your own data. Server gates: sops.read / sops.manage.
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useSession } from "next-auth/react";
import { useRouter } from "next/navigation";
import { Card, CompactRow, EmptyState, PageHeader, RowList, RowSection, RowTag } from "@/components/ui/kit";
import { Skeleton } from "@/components/ui/skeleton";
import { btn, btnPrimary } from "@/components/marketing/studio/types";
import { useToast } from "@/components/ui/toast";
import { errorMessage, fmtDate } from "@/lib/bookings";
import { PLATFORM_LABEL, PLATFORM_ORDER, SOPS_MANAGE_ROLES, sopsApi, type Available, type SopSummary } from "@/lib/sops";

function statusWords(s: SopSummary) {
  if (s.preparing) return "Getting your steps ready";
  if (s.status === "done") return "All done";
  if (s.status === "paused") return "Paused";
  return s.next_due_at ? `Next step due ${fmtDate(s.next_due_at)}` : "No dates set";
}

export default function GetFoundPage() {
  const { toast } = useToast();
  const router = useRouter();
  const qc = useQueryClient();
  const { data: session } = useSession();
  const canManage = SOPS_MANAGE_ROLES.includes(String(session?.user?.role ?? ""));
  const q = useQuery({ queryKey: ["sops"], queryFn: sopsApi.list, retry: false });
  const start = useMutation({
    mutationFn: (a: Available) => sopsApi.start(a.template_key, a.property_id),
    onSuccess: r => { qc.invalidateQueries({ queryKey: ["sops"] }); router.push(`/dashboard/marketing/sops/${r.id}`); },
    onError: e => toast({ variant: "error", title: errorMessage(e, "Could not start the checklist") }),
  });
  const d = q.data;
  return (
    <div className="h-full overflow-y-auto bg-[var(--haip-bg,var(--background))]">
      <div className="mx-auto max-w-[860px] space-y-5 px-4 py-5 sm:px-6">
        <PageHeader title="Get found" subtitle="Step-by-step checklists for your Google, social and booking-site listings, filled in with your own details" />
        {q.isLoading ? <Skeleton className="h-48 w-full" />
          : q.isError ? <Card><EmptyState title="Couldn't load your checklists" hint={errorMessage(q.error, "Try again in a moment.")}
            action={<button className={btn} onClick={() => q.refetch()}>Try again</button>} /></Card>
          : d && <>
            {d.instances.length === 0 && d.available.length === 0 &&
              <Card><EmptyState title="No checklists for this business yet" /></Card>}
            {PLATFORM_ORDER.map(p => {
              const rows = d.instances.filter(i => i.platform === p);
              return rows.length > 0 && (
                <RowSection key={p} title={PLATFORM_LABEL[p]} count={rows.length}>
                  <RowList label={PLATFORM_LABEL[p]}>
                    {rows.map(s => (
                      <CompactRow key={s.id} href={`/dashboard/marketing/sops/${s.id}`} title={s.title}
                        subtitle={s.property_name ? `${s.property_name} · ${statusWords(s)}` : statusWords(s)}
                        meta={`${s.done} of ${s.total}`} metaTone={s.status === "done" ? "success" : "neutral"}
                        extra={s.status === "paused" ? <RowTag>Paused</RowTag> : undefined} />
                    ))}
                  </RowList>
                </RowSection>
              );
            })}
            {d.available.length > 0 && (
              <RowSection title="Not started" count={d.available.length}>
                <RowList label="Not started">
                  {d.available.map(a => (
                    <CompactRow key={`${a.template_key}:${a.property_id ?? ""}`} title={a.title}
                      subtitle={a.property_name ? `${a.property_name} · ${a.summary}` : a.summary} meta={`${a.steps} steps`}
                      actions={canManage ? <button className={btnPrimary} disabled={start.isPending}
                        onClick={() => start.mutate(a)}>Start</button> : undefined} />
                  ))}
                </RowList>
                {!canManage && <p className="px-0.5 text-sm text-[var(--haip-fg-muted)]">An owner or manager can start these.</p>}
              </RowSection>
            )}
          </>}
      </div>
    </div>
  );
}
