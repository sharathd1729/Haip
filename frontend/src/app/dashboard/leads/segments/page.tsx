"use client";
// Leads > Segments (owner / manager). Ready-made segments are the WhatsApp campaign presets, counted exactly as a campaign
// would reach them; AI tag segments are open leads per tag the lead summary wrote. Each opens the leads list filtered,
// or the campaign builder. Backend: GET /leads/segments (cached 10 min; Refresh recounts).
import Link from "next/link";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useSession } from "next-auth/react";
import api from "@/lib/api";
import { Loader2, RefreshCw } from "@/lib/icons";
import { Card, CardBody, CardHeader, EmptyState, PageHeader } from "@/components/ui/kit";

interface Preset { id: string; label: string; description: string; people: number; reachable: number; opted_out: number }
interface TagGroup { label: string; tags: { tag: string; open_leads: number }[] }
interface Segments { presets: Preset[]; tags: TagGroup[] }

const n = (v: number) => v.toLocaleString("en-IN");

export default function SegmentsPage() {
  const { data: session } = useSession();
  const role = session?.user?.role;
  const qc = useQueryClient();
  const q = useQuery<Segments>({
    queryKey: ["lead-segments"],
    queryFn: () => api.get("/leads/segments").then(r => r.data),
    enabled: role === "owner" || role === "manager",
  });
  const refresh = async () => {
    const fresh = await api.get("/leads/segments", { params: { refresh: true } }).then(r => r.data);
    qc.setQueryData(["lead-segments"], fresh);
  };
  if (role && role !== "owner" && role !== "manager") {
    return <div className="p-8 text-sm text-[var(--haip-fg-muted)]">Segments are for owners and managers.</div>;
  }
  const anyTagged = (q.data?.tags ?? []).some(g => g.tags.some(t => t.open_leads > 0));

  return (
    <div className="h-full overflow-y-auto">
      <div className="mx-auto max-w-5xl space-y-4 px-4 py-6 sm:px-6">
        <PageHeader title="Segments" subtitle="Groups of leads to act on. Counts are people, as of the last 10 minutes."
          actions={<button type="button" onClick={refresh} className="inline-flex min-h-[44px] items-center gap-2 rounded-full border border-[var(--haip-border)] px-4 text-sm font-semibold text-[var(--haip-fg)]">
            <RefreshCw size={14} /> Refresh
          </button>} />
        {q.isPending ? <p className="flex items-center gap-2 p-6 text-sm text-[var(--haip-fg-muted)]"><Loader2 size={16} className="animate-spin" /> Counting your leads…</p>
          : q.isError ? <Card><CardBody className="pt-4"><p className="text-sm text-[var(--haip-fg-muted)]">Couldn&apos;t load segments. Refresh to try again.</p></CardBody></Card>
          : (
            <>
              <Card>
                <CardHeader title="Ready-made" description="The same groups the WhatsApp campaign builder offers." tone="plain" />
                <CardBody>
                  <ul className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
                    {q.data!.presets.map(p => (
                      <li key={p.id} className="rounded-2xl border border-[var(--haip-border)] p-4">
                        <p className="text-sm font-semibold text-[var(--haip-fg)]">{p.label}</p>
                        <p className="mt-0.5 text-xs text-[var(--haip-fg-subtle)]">{p.description}</p>
                        <p className="mt-3 font-[family-name:var(--font-display)] text-2xl font-semibold tabular-nums text-[var(--haip-fg)]">{n(p.people)}</p>
                        <p className="text-xs text-[var(--haip-fg-muted)]">{n(p.reachable)} can get a WhatsApp{p.opted_out ? ` · ${n(p.opted_out)} opted out` : ""}</p>
                        <Link href="/dashboard/messaging/campaigns" className="mt-3 inline-flex min-h-[44px] items-center text-sm font-semibold text-primary">Message them in a campaign</Link>
                      </li>
                    ))}
                  </ul>
                </CardBody>
              </Card>
              <Card>
                <CardHeader title="AI tags" description="Open leads by what the AI read from their chats and calls." tone="plain" />
                <CardBody>
                  {!anyTagged ? <EmptyState title="No tags yet" hint="Tags appear as the AI updates each lead's summary." /> : (
                    <div className="grid gap-5">
                      {q.data!.tags.map(g => (
                        <section key={g.label}>
                          <h3 className="mb-2 text-xs font-semibold uppercase tracking-wide text-[var(--haip-fg-subtle)]">{g.label}</h3>
                          <div className="flex flex-wrap gap-2">
                            {g.tags.filter(t => t.open_leads > 0).map(t => (
                              <Link key={t.tag} href={`/dashboard/leads?tag=${encodeURIComponent(t.tag)}`}
                                className="inline-flex min-h-[44px] items-center gap-2 rounded-full border border-[var(--haip-border)] px-4 text-sm text-[var(--haip-fg)] hover:border-primary">
                                {t.tag} <span className="font-semibold tabular-nums">{n(t.open_leads)}</span>
                              </Link>
                            ))}
                            {g.tags.every(t => t.open_leads === 0) && <p className="text-sm text-[var(--haip-fg-subtle)]">None yet.</p>}
                          </div>
                        </section>
                      ))}
                    </div>
                  )}
                </CardBody>
              </Card>
            </>
          )}
      </div>
    </div>
  );
}
