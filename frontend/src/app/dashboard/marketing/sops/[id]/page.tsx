"use client";
// One Get found checklist (dynamic SOP): its steps as rows; a step opens in a sheet (components/sops/StepSheet.tsx).
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useSession } from "next-auth/react";
import Link from "next/link";
import { useParams } from "next/navigation";
import { useState } from "react";
import { Card, CardBody, CompactRow, EmptyState, PageHeader, RowList, RowTag } from "@/components/ui/kit";
import { Skeleton } from "@/components/ui/skeleton";
import { btn } from "@/components/marketing/studio/types";
import { StepSheet } from "@/components/sops/StepSheet";
import { useToast } from "@/components/ui/toast";
import { errorMessage, fmtDate } from "@/lib/bookings";
import { CheckCircle2 } from "@/lib/icons";
import { SOPS_MANAGE_ROLES, sopsApi, type Step } from "@/lib/sops";

const REASON = { first: "first version", manual: "you asked for new steps", data_changed: "your details changed",
  catalogue_updated: "HAIP updated the platform rules", template_updated: "HAIP improved the steps" } as Record<string, string>;

function stepWords(s: Step) {
  if (s.status === "done") return s.done_by ? "Done" : "Done · checked by HAIP";
  if (s.status === "skipped") return "Not for us";
  if (s.changed) return "Changed since you did it";
  if (s.needs.length) return "Fill something in HAIP first";
  return s.check_result?.result === "fail" ? s.check_result.detail : s.due_at ? `Due ${fmtDate(s.due_at, false)}` : "To do";
}

export default function SopPage() {
  const { id } = useParams<{ id: string }>();
  const { toast } = useToast();
  const qc = useQueryClient();
  const { data: session } = useSession();
  const canManage = SOPS_MANAGE_ROLES.includes(String(session?.user?.role ?? ""));
  const q = useQuery({ queryKey: ["sop", id], queryFn: () => sopsApi.get(id), retry: false,
    refetchInterval: d => (d.state.data?.preparing ? 3000 : false) });
  const [open, setOpen] = useState<string | null>(null);
  const refresh = () => { qc.invalidateQueries({ queryKey: ["sop", id] }); qc.invalidateQueries({ queryKey: ["sops"] }); };
  const act = (fn: () => Promise<unknown>, ok: string) =>
    fn().then(() => { toast({ variant: "success", title: ok }); setTimeout(refresh, 2500); },
      e => toast({ variant: "error", title: errorMessage(e, "That didn't work") }));
  const d = q.data;
  const steps = d?.steps.filter(s => !s.hidden) ?? [];
  const hasAuto = steps.some(s => s.verify === "auto");
  return (
    <div className="h-full overflow-y-auto bg-[var(--haip-bg,var(--background))]">
      <div className="mx-auto max-w-[860px] space-y-5 px-4 py-5 sm:px-6">
        <Link href="/dashboard/marketing/sops" className="text-sm font-semibold text-primary">← Get found</Link>
        {q.isLoading ? <Skeleton className="h-64 w-full" />
          : q.isError ? <Card><EmptyState title="Couldn't load this checklist" hint={errorMessage(q.error, "Try again in a moment.")}
            action={<button className={btn} onClick={() => q.refetch()}>Try again</button>} /></Card>
          : d && <>
            <PageHeader keepOnPhone title={d.title} subtitle={d.summary} actions={<div className="flex flex-wrap gap-2">
              {hasAuto && d.can_work && <button className={btn} onClick={() => act(() => sopsApi.check(id), "HAIP is checking")}>Check now</button>}
              {canManage && <button className={btn} disabled={d.preparing} onClick={() => act(() => sopsApi.regenerate(id), "Making new steps")}>Update steps</button>}
            </div>} />
            <Card><CardBody className="grid gap-1 text-[15px]">
              <b className="text-lg">{d.done} of {d.total} done</b>
              {d.preparing ? <span className="text-[var(--haip-fg-muted)]">Getting your steps ready from your details…</span>
                : d.version && <span className="text-sm text-[var(--haip-fg-muted)]">
                  Version {d.version.no}{d.version.created_at ? `, ${fmtDate(d.version.created_at)}` : ""} ({REASON[d.version.reason] ?? d.version.reason}).
                  {d.version.ai_note ? ` ${d.version.ai_note}` : ""}</span>}
            </CardBody></Card>
            {steps.length === 0 ? (d.preparing ? <Skeleton className="h-48 w-full" /> : <Card><EmptyState title="No steps yet" /></Card>)
              : <RowList label="Steps">
                {steps.map((s, i) => (
                  <CompactRow key={s.key} onClick={() => setOpen(s.key)} title={`${i + 1}. ${s.title}`} subtitle={stepWords(s)}
                    avatar={<CheckCircle2 size={22} className={s.status === "todo" ? "text-[var(--haip-border)]" : "text-primary"} aria-hidden />}
                    extra={s.verify === "evidence" && s.status === "todo" ? <RowTag tone="warning">Screenshot</RowTag>
                      : s.verify === "auto" ? <RowTag tone="brand">HAIP checks</RowTag> : undefined} />
                ))}
              </RowList>}
            <StepSheet sopId={id} step={steps.find(s => s.key === open) ?? null} canWork={d.can_work}
              onClose={() => setOpen(null)} onChanged={refresh} />
          </>}
      </div>
    </div>
  );
}
