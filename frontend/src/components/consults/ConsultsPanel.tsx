"use client";
// The AI's open questions to the team. `ConsultsPanel` = My day (every open consult, with loading / error states; renders nothing
// when there is none, the queue below has its own empty state). `ConsultBanner` = the Inbox thread (this conversation's open
// consult only). Both refresh every 30 s; a push / WhatsApp alert deep-links here with ?consult=.
// The banner sits above the chat, so it starts as a one-line bar and opens into a height-capped, scrollable card: the
// thread must stay readable. A ?consult= deep link opens it.
import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import api from "@/lib/api";
import { ChevronDown } from "@/lib/icons";
import { cn } from "@/lib/utils";
import { Card, CardBody, StatusPill } from "@/components/ui/kit";
import { Skeleton } from "@/components/ui/skeleton";
import { ConsultCard, type Consult } from "./ConsultCard";

const noRetryOn403 = (n: number, e: unknown) => (e as { response?: { status?: number } })?.response?.status !== 403 && n < 1;

export function ConsultsPanel() {
  const { data, isPending, isError, refetch } = useQuery<Consult[]>({
    queryKey: ["consults", "open"],
    queryFn: () => api.get("/consults", { params: { status: "open" } }).then(r => r.data),
    refetchInterval: 30_000,
    retry: noRetryOn403,
  });
  if (isPending) return <Skeleton className="h-24 w-full rounded-2xl" />;
  if (isError) {
    return (
      <Card><CardBody className="flex flex-wrap items-center gap-2 text-sm text-[var(--haip-fg-subtle)]">
        Couldn't load the AI's questions. <button type="button" className="font-semibold text-primary underline" onClick={() => refetch()}>Try again</button>
      </CardBody></Card>
    );
  }
  if (!data?.length) return null;
  return (
    <section aria-labelledby="consults-heading" className="space-y-2">
      <h2 id="consults-heading" className="text-sm font-semibold text-[var(--haip-fg)]">
        The AI is asking you ({data.length})
      </h2>
      <div className="grid gap-2 lg:grid-cols-2">
        {data.map(c => <ConsultCard key={c.id} consult={c} compact />)}
      </div>
    </section>
  );
}

export function ConsultBanner({ conversationId }: { conversationId: string | null }) {
  const { data } = useQuery<Consult[]>({
    queryKey: ["consults", "conversation", conversationId],
    queryFn: () => api.get("/consults", { params: { status: "open", conversation_id: conversationId } }).then(r => r.data),
    enabled: Boolean(conversationId),
    refetchInterval: 30_000,
    retry: noRetryOn403,
  });
  if (!data?.length) return null;                 // nothing waiting on this thread (or no access): no banner
  return <div className="space-y-2 px-3 pt-2 sm:px-4">{data.map(c => <CollapsibleConsult key={c.id} consult={c} />)}</div>;
}

function linkedConsultId(): string | null {
  if (typeof window === "undefined") return null;
  return new URLSearchParams(window.location.search).get("consult");
}

function CollapsibleConsult({ consult: c }: { consult: Consult }) {
  const [open, setOpen] = useState(() => linkedConsultId() === c.id);
  const panelId = `consult-${c.id}`;
  return (
    <div className="rounded-2xl border border-[var(--haip-border)] bg-[var(--haip-surface)]">
      <button
        type="button"
        aria-expanded={open}
        aria-controls={panelId}
        onClick={() => setOpen(o => !o)}
        className="flex min-h-[44px] w-full items-center gap-2 px-3 py-2 text-left"
      >
        <span className="min-w-0 flex-1 truncate text-[14px] text-[var(--haip-fg)]">
          <span className="font-semibold">{c.guest_name} asked:</span> “{c.question}”
        </span>
        <StatusPill tone={c.overdue ? "danger" : "warning"}>{c.overdue ? "Overdue" : "Needs you"}</StatusPill>
        <span className="hidden text-[13px] font-semibold text-primary sm:inline">{open ? "Hide" : "Review answer"}</span>
        <ChevronDown aria-hidden className={cn("h-4 w-4 shrink-0 text-[var(--haip-fg-subtle)] transition-transform motion-reduce:transition-none", open && "rotate-180")} />
      </button>
      {open && (
        <div id={panelId} className="max-h-[45vh] overflow-y-auto overscroll-contain border-t border-[var(--haip-border)]">
          <ConsultCard consult={c} compact />
        </div>
      )}
    </div>
  );
}
