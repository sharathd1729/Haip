"use client";
// Phase 2 parts of the trip file: the guest ID form (private link: copy it, or send it on WhatsApp while the guest's 24-hour
// window is open), the return-vs-handover photo check, and the automatic messages HAIP sent (or could not send).
import { useState } from "react";
import api from "@/lib/api";
import { cn } from "@/lib/utils";
import { Card, CardBody, CardHeader, StatusPill } from "@/components/ui/kit";
import { useToast } from "@/components/ui/toast";
import type { OpsFileFull } from "@/lib/ops";

function errorText(e: unknown): string {
  const d = (e as { response?: { data?: { detail?: unknown } } })?.response?.data?.detail;
  return typeof d === "string" ? d : "Check your connection and try again.";
}

const MSG_LABEL: Record<string, string> = {
  crew_brief: "Crew brief", helper_chase: "Photo reminder", guest_pretrip: "Pre-trip message to the guest",
  deposit_nudge: "Deposit refund reminder",
};

export function GuestFormCard({ f, canWrite, onSent }: { f: OpsFileFull; canWrite: boolean; onSent: () => void }) {
  const { toast } = useToast();
  const [busy, setBusy] = useState<"copy" | "send" | null>(null);
  const g = f.guest_form;
  const copy = async () => {
    setBusy("copy");
    try {
      const url = (await api.post(`/ops/files/${f.id}/guest-form/link`)).data.url as string;
      await navigator.clipboard.writeText(url);
      toast({ title: "Link copied", description: "Paste it to the guest on WhatsApp.", variant: "success" });
    } catch (e) { toast({ title: "Couldn't copy the link", description: errorText(e), variant: "error" }); }
    finally { setBusy(null); }
  };
  const send = async () => {
    setBusy("send");
    try { await api.post(`/ops/files/${f.id}/guest-form/send`); toast({ title: "Sent on WhatsApp", variant: "success" }); onSent(); }
    catch (e) { toast({ title: "Not sent", description: errorText(e), variant: "error" }); }
    finally { setBusy(null); }
  };
  return (
    <Card>
      <CardHeader title="Guest details and ID" tone="plain"
        description={g.submitted_at ? `Filled ${new Date(g.submitted_at).toLocaleString("en-IN", { day: "numeric", month: "short", hour: "numeric", minute: "2-digit" })}`
          : "The guest fills names, ages and ID on a private link"}
        actions={<StatusPill tone={g.submitted_at ? "success" : "warning"}>{g.submitted_at ? "Done" : "Not yet"}</StatusPill>} />
      <CardBody className="flex flex-col gap-2 px-4 pb-4">
        {g.guests.map((x, i) => (
          <p key={i} className="text-[15px]">{x.name}{x.age !== null ? `, ${x.age}` : ""} <span className="text-[13px] text-[var(--haip-fg-subtle)]">· {x.id}</span></p>
        ))}
        {g.submitted_at && (
          <p className="text-[14px] text-[var(--haip-fg-muted)]">
            Emergency: {g.emergency_name} {g.emergency_phone}{g.food ? ` · Food: ${g.food}` : ""}{g.requests ? ` · Requests: ${g.requests}` : ""}
          </p>
        )}
        {canWrite && f.state !== "closed" && f.state !== "cancelled" && (
          <div className="mt-1 flex flex-wrap gap-2">
            <button type="button" className="haip-btn-secondary min-h-12 flex-1" disabled={!!busy} onClick={copy}>
              {busy === "copy" ? "Copying…" : "Copy link"}</button>
            <button type="button" className="haip-btn-secondary min-h-12 flex-1" disabled={!!busy} onClick={send}>
              {busy === "send" ? "Sending…" : "Send on WhatsApp"}</button>
          </div>
        )}
      </CardBody>
    </Card>
  );
}

const DOT = { green: "bg-primary", red: "bg-[var(--haip-status-danger-fg)]", pending: "bg-[var(--haip-border-strong)]" };

export function ReturnCheckCard({ f }: { f: OpsFileFull }) {
  const r = f.return_check;
  if (!r.items.length) return null;
  return (
    <Card>
      <CardHeader title="Back from the trip: photo check" tone="plain" description={r.words}
        actions={r.damage.length ? <StatusPill tone="danger">Possible damage</StatusPill> : undefined} />
      <CardBody className="px-4 pb-3">
        <p className="pb-2 text-[13.5px] text-[var(--haip-fg-subtle)]">The helper sends each part again as &ldquo;return ac&rdquo;, &ldquo;return water&rdquo;… HAIP compares it with the handover photo.</p>
        {r.items.map(i => (
          <div key={i.key} className="flex min-h-[44px] items-start gap-3 border-t border-[var(--haip-border)] py-2 first:border-t-0">
            <span aria-hidden className={cn("mt-1.5 size-2.5 shrink-0 rounded-full", DOT[i.status])} />
            <span className="min-w-0 text-[15px]">{i.label}
              <span className="block text-[13px] text-[var(--haip-fg-subtle)]">
                {i.note ?? (i.status === "green" ? "Matches the handover photo" : i.has_photo ? "Checked" : "Waiting for the return photo")}
              </span>
            </span>
          </div>
        ))}
        {r.damage.length > 0 && <p className="mt-2 text-[14px] font-semibold">Decide on the deposit before you refund it.</p>}
      </CardBody>
    </Card>
  );
}

export function MessagesList({ f }: { f: OpsFileFull }) {
  if (!f.messages.length) return null;
  return (
    <ul className="w-full text-[14px]">
      {f.messages.map((m, i) => (
        <li key={i} className="flex flex-wrap items-center gap-2 py-1">
          <StatusPill tone={m.status === "sent" ? "success" : "warning"}>{m.status === "sent" ? "Sent" : "Not sent"}</StatusPill>
          <span>{MSG_LABEL[m.kind] ?? m.kind}{m.recipient === `staff:${f.details.driver_staff_id}` ? " (driver)"
            : m.recipient === `staff:${f.details.helper_staff_id}` ? " (helper)" : ""}{m.status === "failed" && m.reason ? `: ${m.reason}` : ""}</span>
        </li>
      ))}
    </ul>
  );
}
