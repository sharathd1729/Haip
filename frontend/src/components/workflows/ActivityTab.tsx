"use client";
// Lead workflows, Activity tab: everything the playbooks did, skipped or held, newest first, with the reason.
// Backend: GET /workflows/activity?playbook=&status=&limit= (owner/manager).
import { useState } from "react";
import Link from "next/link";
import { useQuery } from "@tanstack/react-query";
import api from "@/lib/api";
import { Loader2 } from "@/lib/icons";
import { Card, CardBody, EmptyState, StatusPill, type Tone } from "@/components/ui/kit";

export interface Activity {
  id: string; playbook: string; playbook_name: string; action: string; status: string; reason: string | null;
  template: string | null; inquiry_id: string | null; guest_name: string | null; at: string | null;
}

export const ACTION_LABEL: Record<string, string> = {
  wa_template: "WhatsApp template", wa_text: "WhatsApp message", task: "Task", push: "App notification",
  staff_wa: "Team WhatsApp", draft: "AI draft to approve",
};
export const STATUS_TONE: Record<string, Tone> = { queued: "success", done: "success", skipped: "warning", failed: "danger", held: "neutral" };
export const STATUS_LABEL: Record<string, string> = { queued: "Sent", done: "Done", skipped: "Skipped", failed: "Failed", held: "Held overnight" };
export const istTime = new Intl.DateTimeFormat("en-IN", { timeZone: "Asia/Kolkata", day: "numeric", month: "short", hour: "numeric", minute: "2-digit" });

const PLAYBOOKS: [string, string][] = [
  ["", "All playbooks"], ["missed_inbound_call", "Missed call"], ["unanswered_outbound", "No answer"],
  ["callback_requested", "Call me back"], ["new_lead_alert", "New lead alert"], ["sla_escalation", "Escalation"],
  ["proposal_followup", "Proposal follow-up"], ["quiet_lead_nurture", "Quiet lead"], ["lost_reengage", "Win back"],
];
const STATUSES: [string, string][] = [["", "Any result"], ["done", "Done"], ["queued", "Sent"], ["skipped", "Skipped"], ["failed", "Failed"], ["held", "Held"]];
const selectCls = "min-h-[44px] rounded-lg border border-[var(--haip-border)] bg-[var(--haip-card)] px-2.5 text-[16px] text-[var(--haip-fg)] sm:text-sm";

export function ActivityTab() {
  const [playbook, setPlaybook] = useState("");
  const [status, setStatus] = useState("");
  const q = useQuery<{ items: Activity[] }>({
    queryKey: ["workflows-activity", playbook, status],
    queryFn: () => api.get("/workflows/activity", { params: { limit: 100, playbook: playbook || undefined, status: status || undefined } }).then(r => r.data),
  });
  return (
    <Card>
      <CardBody className="space-y-3 pt-4">
        <div className="flex flex-wrap gap-2">
          <select id="activity-playbook" aria-label="Playbook" className={selectCls} value={playbook} onChange={e => setPlaybook(e.target.value)}>
            {PLAYBOOKS.map(([v, l]) => <option key={v} value={v}>{l}</option>)}
          </select>
          <select id="activity-status" aria-label="Result" className={selectCls} value={status} onChange={e => setStatus(e.target.value)}>
            {STATUSES.map(([v, l]) => <option key={v} value={v}>{l}</option>)}
          </select>
        </div>
        <p className="text-xs text-[var(--haip-fg-subtle)]">Newest first, last 100. Times in IST.</p>
        {q.isPending ? (
          <p className="flex items-center gap-2 text-sm text-[var(--haip-fg-muted)]"><Loader2 size={14} className="animate-spin" /> Loading…</p>
        ) : q.isError ? (
          <p className="text-sm text-[var(--haip-fg-muted)]">Couldn&apos;t load the activity. Refresh to try again.</p>
        ) : !q.data?.items.length ? (
          <EmptyState title={playbook || status ? "Nothing matches" : "Nothing yet"}
            hint={playbook || status ? "Try another playbook or result." : "When a switched-on workflow runs, each message, task and skip shows here with the reason."} />
        ) : (
          <ul className="divide-y divide-[var(--haip-border)]">
            {q.data.items.map(a => (
              <li key={a.id} className="flex flex-wrap items-start justify-between gap-x-3 gap-y-1 py-2.5">
                <div className="min-w-0 flex-1">
                  <p className="text-sm text-[var(--haip-fg)]">
                    {a.inquiry_id ? <Link href={`/dashboard/leads/${a.inquiry_id}`} className="font-semibold text-primary">{a.guest_name || "Guest"}</Link>
                      : <span className="font-semibold">{a.guest_name || "Team"}</span>}
                    {" · "}{ACTION_LABEL[a.action] ?? a.action}
                  </p>
                  <p className="text-xs text-[var(--haip-fg-subtle)]">{a.playbook_name}{a.reason ? ` — ${a.reason}` : ""}</p>
                </div>
                <div className="flex items-center gap-2">
                  <StatusPill tone={STATUS_TONE[a.status] ?? "neutral"}>{STATUS_LABEL[a.status] ?? a.status}</StatusPill>
                  <span className="text-xs tabular-nums text-[var(--haip-fg-subtle)]">{a.at ? istTime.format(new Date(a.at)) : ""}</span>
                </div>
              </li>
            ))}
          </ul>
        )}
      </CardBody>
    </Card>
  );
}
