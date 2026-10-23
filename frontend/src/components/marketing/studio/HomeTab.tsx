"use client";
// Studio Home: the setup checklist (GET /marketing/studio/setup), each item with one fix, then the agency's runs.
import Link from "next/link";
import { useQuery } from "@tanstack/react-query";
import api from "@/lib/api";
import { Skeleton } from "@/components/ui/skeleton";
import { Card, CardBody, CardHeader, EmptyState, StatusPill } from "@/components/ui/kit";
import { AgencyTab } from "./AgencyTab";
import { STUDIO, btn, studioError, studioHref } from "./types";

interface SetupItem {
  key: string; label: string; done: boolean; required: boolean; detail: string;
  fix: { tab: string; label: string } | null; admin_keys: string[];
}
interface Setup { items: SetupItem[]; done: number; total: number; ready: boolean }

/** "integrations" is outside the Studio (Settings > Integrations); everything else is a Studio tab. */
const fixHref = (tab: string) => (tab === "integrations" ? "/dashboard/settings/integrations" : studioHref(tab));

export function SetupChecklist() {
  const q = useQuery<Setup>({ queryKey: ["studio-setup"], queryFn: () => api.get(`${STUDIO}/setup`).then(r => r.data) });
  if (q.isLoading) return <Skeleton className="h-48 w-full" />;
  if (q.isError || !q.data) return <Card><EmptyState title="Could not load the setup checklist" hint={studioError(q.error, "Try again.")} /></Card>;
  const s = q.data;
  const open = s.items.filter(i => !i.done);
  return (
    <Card>
      <CardHeader title={s.ready ? "Set up and ready" : `Setup: ${s.done} of ${s.total} done`}
        description={s.ready ? "Everything the agency needs is in place. Optional items below add more." : "Finish these so the agency can work on its own."} />
      <CardBody>
        {!open.length ? <p className="text-sm text-[var(--haip-fg-subtle)]">Nothing left to set up.</p> : (
          <ul className="divide-y divide-[var(--haip-border)]">
            {open.map(i => (
              <li key={i.key} className="flex flex-col gap-2 py-3 sm:flex-row sm:items-center sm:justify-between">
                <div className="min-w-0">
                  <p className="font-semibold text-[var(--haip-fg)]">{i.label} <StatusPill tone={i.required ? "warning" : "neutral"} className="ml-1">{i.required ? "Needed" : "Optional"}</StatusPill></p>
                  {i.detail && <p className="text-xs text-[var(--haip-fg-subtle)]">{i.detail}</p>}
                  {!!i.admin_keys.length && i.key !== "server" && <p className="text-xs text-[var(--haip-fg-subtle)]">Ask your HAIP admin to set {i.admin_keys.join(", ")} first.</p>}
                </div>
                {i.fix && <Link className={btn} href={fixHref(i.fix.tab)}>{i.fix.label}</Link>}
              </li>
            ))}
          </ul>
        )}
        {s.items.some(i => i.done) && (
          <p className="mt-3 text-xs text-[var(--haip-fg-subtle)]">Done: {s.items.filter(i => i.done).map(i => i.label).join(" · ")}</p>
        )}
      </CardBody>
    </Card>
  );
}

export function HomeTab() {
  return <div className="space-y-4"><SetupChecklist /><AgencyTab /></div>;
}
