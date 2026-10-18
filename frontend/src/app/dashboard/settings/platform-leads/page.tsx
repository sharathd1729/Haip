"use client";
// HAIP's own website leads (book-demo, contact, property assessment). Owner of HAIP's sales workspace only
// (backend: GET /platform-leads, 403 for everyone else). Each routed lead also sits in Leads360.
import { useState } from "react";
import Link from "next/link";
import { useQuery } from "@tanstack/react-query";
import api from "@/lib/api";
import { Card, DataTable, FilterBar, FilterChip, PageHeader, StatusPill, type Column, type Tone } from "@/components/ui/kit";

interface PlatformLeadRow {
  id: string;
  kind: "demo" | "contact" | "assessment";
  name: string;
  email?: string | null;
  phone?: string | null;
  company?: string | null;
  message?: string | null;
  details: Record<string, string>;
  is_spam: boolean;
  routing_status: string;
  workspace_inquiry_id?: string | null;
  marketing_opt_in: boolean;
  created_at: string;
}

const KIND_LABEL: Record<PlatformLeadRow["kind"], string> = {
  demo: "Demo",
  contact: "Contact",
  assessment: "Assessment",
};

const ROUTING: Record<string, { label: string; tone: Tone }> = {
  routed: { label: "In Leads360", tone: "success" },
  stored: { label: "Stored", tone: "neutral" },
  not_configured: { label: "Not routed", tone: "warning" },
  failed: { label: "Copy failed", tone: "danger" },
  spam: { label: "Spam", tone: "neutral" },
};

function when(iso: string): string {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "—";
  return d.toLocaleString("en-IN", { timeZone: "Asia/Kolkata", day: "numeric", month: "short", hour: "numeric", minute: "2-digit" });
}

function loadError(err: unknown): string {
  const status = (err as { response?: { status?: number } })?.response?.status;
  if (status === 403) return "Only the owner of HAIP's own sales workspace can see website leads.";
  if (status === 401) return "You are signed out. Sign in again.";
  return "Couldn't load website leads.";
}

export default function PlatformLeadsPage() {
  const [kind, setKind] = useState<"" | PlatformLeadRow["kind"]>("");
  const [spam, setSpam] = useState(false);
  const query = useQuery({
    queryKey: ["platform-leads", kind, spam],
    queryFn: async () => {
      const params: Record<string, string> = { limit: "200" };
      if (kind) params.kind = kind;
      if (spam) params.include_spam = "true";
      const { data } = await api.get<{ items: PlatformLeadRow[]; count: number }>("/platform-leads", { params });
      return data.items;
    },
    retry: false,
  });

  const columns: Column<PlatformLeadRow>[] = [
    { key: "when", header: "Received (IST)", cell: r => <span className="whitespace-nowrap">{when(r.created_at)}</span> },
    { key: "kind", header: "Form", cell: r => <StatusPill tone="brand">{KIND_LABEL[r.kind] ?? r.kind}</StatusPill> },
    {
      key: "who", header: "Who", cell: r => (
        <div className="min-w-0">
          <p className="font-semibold text-[var(--haip-fg)] break-words">{r.name}</p>
          <p className="text-[12.5px] text-[var(--haip-fg-subtle)] break-all">{[r.company, r.phone, r.email].filter(Boolean).join(" · ")}</p>
        </div>
      ),
    },
    {
      key: "note", header: "Message", hideBelow: "md", cell: r => (
        <p className="max-w-[28rem] text-[13px] text-[var(--haip-fg-muted)] line-clamp-2 break-words">
          {r.message || Object.values(r.details || {}).join(" · ") || "—"}
        </p>
      ),
    },
    {
      key: "status", header: "Lead", cell: r => {
        const s = ROUTING[r.routing_status] ?? { label: r.routing_status, tone: "neutral" as Tone };
        return r.workspace_inquiry_id
          ? <Link href={`/dashboard/leads/${r.workspace_inquiry_id}`} className="inline-flex min-h-[44px] items-center"><StatusPill tone={s.tone}>{s.label}</StatusPill></Link>
          : <StatusPill tone={s.tone}>{s.label}</StatusPill>;
      },
    },
  ];

  return (
    <div className="space-y-5">
      <PageHeader title="Website leads" subtitle="Book-demo, contact and assessment forms on HAIP's own site, newest first." />
      <FilterBar>
        <FilterChip active={kind === ""} onClick={() => setKind("")}>All forms</FilterChip>
        <FilterChip active={kind === "demo"} onClick={() => setKind("demo")}>Demo</FilterChip>
        <FilterChip active={kind === "contact"} onClick={() => setKind("contact")}>Contact</FilterChip>
        <FilterChip active={kind === "assessment"} onClick={() => setKind("assessment")}>Assessment</FilterChip>
        <FilterChip active={spam} onClick={() => setSpam(v => !v)}>Show spam</FilterChip>
      </FilterBar>
      <Card className="overflow-hidden">
        <DataTable
          columns={columns}
          rows={query.data ?? []}
          rowKey={r => r.id}
          loading={query.isPending}
          error={query.isError ? loadError(query.error) : null}
          onRetry={() => query.refetch()}
          empty={{ title: "No website leads yet", hint: "When someone books a demo, sends a message or asks for an assessment report, it shows up here and in Leads360." }}
        />
      </Card>
    </div>
  );
}
