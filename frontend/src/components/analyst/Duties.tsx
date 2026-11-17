"use client";
// The HAIP Executive's written duties (workspace redesign Phase 3). GET /chief/duties (services/chief/duties.py): what it
// does, when, whether each is on in this workspace, and when it last did it where that is recorded.
import Link from "next/link";
import { useQuery } from "@tanstack/react-query";
import api from "@/lib/api";
import { Card, CardBody, CardHeader, StatusPill } from "@/components/ui/kit";
import { Skeleton } from "@/components/ui/skeleton";

interface Duty { key: string; title: string; what: string; when: string; on: boolean; on_note: string | null; last: string | null; count?: number | null; href: string }

function ago(iso: string | null): string | null {
  if (!iso) return null;
  const mins = Math.round((Date.now() - new Date(iso).getTime()) / 60000);
  if (mins < 60) return `${Math.max(mins, 1)} min ago`;
  if (mins < 48 * 60) return `${Math.round(mins / 60)} h ago`;
  return new Date(iso).toLocaleDateString("en-IN", { day: "numeric", month: "short" });
}

export function Duties() {
  const { data, isPending, isError } = useQuery<{ duties: Duty[] }>({
    queryKey: ["chief-duties"], queryFn: () => api.get("/chief/duties").then(r => r.data), staleTime: 60_000,
  });
  return (
    <Card>
      <CardHeader title="What the HAIP Executive does" description="Five duties, when they run, and when each last ran" />
      <CardBody>
        {isPending ? <Skeleton className="h-40" /> : isError || !data ? (
          <p className="text-sm text-[var(--haip-fg-subtle)]">Couldn&apos;t load the duties.</p>
        ) : (
          <ol className="divide-y divide-[var(--haip-border)]">
            {data.duties.map(d => (
              <li key={d.key}>
                <Link href={d.href} className="flex flex-wrap items-start gap-x-4 gap-y-1 py-3 hover:bg-[var(--haip-surface)]">
                  <span className="min-w-0 flex-1">
                    <span className="flex flex-wrap items-center gap-2">
                      <span className="font-semibold text-[var(--haip-fg)]">{d.title}</span>
                      <StatusPill tone={d.on ? "success" : "neutral"}>{d.on ? "On" : "Off"}</StatusPill>
                      {d.on_note && <span className="text-[12.5px] text-[var(--haip-fg-subtle)]">{d.on_note}</span>}
                    </span>
                    <span className="mt-0.5 block text-[13px] text-[var(--haip-fg-2)]">{d.what}</span>
                  </span>
                  <span className="text-right text-[12.5px] text-[var(--haip-fg-subtle)]">
                    <span className="block">{d.when}</span>
                    {ago(d.last) && <span className="block">Last: {ago(d.last)}</span>}
                  </span>
                </Link>
              </li>
            ))}
          </ol>
        )}
      </CardBody>
    </Card>
  );
}
