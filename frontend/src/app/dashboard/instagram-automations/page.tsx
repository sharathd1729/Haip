"use client";
// Instagram automations (ReplyRush / SuperProfile style): comment / Live / story / DM keyword → DM, with stats.
// Rules are automation_rules rows (GET/PATCH/DELETE /automations); stats from GET /instagram/automations/stats.
import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Plus, Pencil, Trash2, MessageSquare, Link2, Users, BadgeCheck } from "@/lib/icons";
import api from "@/lib/api";
import { cn } from "@/lib/utils";
import { Card, EmptyState, PageHeader, Stat, StatusPill } from "@/components/ui/kit";
import { AutomationBuilder } from "@/components/instagram/AutomationBuilder";
import { isIgRule, triggerMeta, type IgRule, type IgRuleStats } from "@/components/instagram/automationTypes";

const PERIODS = [7, 30, 90] as const;

function scopeLabel(r: IgRule): string {
  if (r.trigger !== "ig_comment_received") return "";
  const s = r.trigger_config.scope ?? (r.trigger_config.media_id ? "post" : "any");
  if (s === "next_post") return r.trigger_config.media_id ? "Next post (running)" : "Next post (waiting)";
  return s === "post" ? "One post" : "Any post";
}

function RuleCard({ rule, stats, onEdit }: { rule: IgRule; stats?: IgRuleStats; onEdit: () => void }) {
  const qc = useQueryClient();
  const toggle = useMutation({
    mutationFn: () => api.patch(`/automations/${rule.id}`, { is_active: !rule.is_active }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["automations"] }),
  });
  const remove = useMutation({
    mutationFn: () => api.delete(`/automations/${rule.id}`),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["automations"] }),
  });
  const tc = rule.trigger_config;
  const words = tc.reply_all ? ["Every comment"] : (tc.keywords ?? []);
  return (
    <Card className="flex gap-3 p-3 sm:p-4">
      <div className="size-16 shrink-0 overflow-hidden rounded-[12px] bg-[var(--haip-surface)]">
        {tc.media_thumb
          ? /* eslint-disable-next-line @next/next/no-img-element */ <img src={tc.media_thumb} alt="" className="size-full object-cover" />
          : <span className="flex size-full items-center justify-center text-primary"><MessageSquare size={22} /></span>}
      </div>
      <div className="min-w-0 flex-1">
        <div className="flex flex-wrap items-center gap-1.5">
          <p className="min-w-0 truncate text-[15px] font-semibold">{rule.name}</p>
          <StatusPill tone={rule.is_active ? "success" : "neutral"}>{rule.is_active ? "On" : "Paused"}</StatusPill>
        </div>
        <p className="mt-0.5 text-[13px] text-[var(--haip-fg-subtle)]">
          {triggerMeta(rule.trigger)?.short ?? rule.trigger}{scopeLabel(rule) && ` · ${scopeLabel(rule)}`}
          {rule.action_config.follow_gate?.enabled && " · Follow first"}{rule.action_config.button?.url && " · Link button"}
        </p>
        {words.length > 0 && (
          <div className="mt-1.5 flex flex-wrap gap-1">
            {words.slice(0, 6).map(w => <span key={w} className="rounded-full bg-[var(--haip-primary-tint)] px-2 py-0.5 text-[12px] font-medium text-primary">{w}</span>)}
          </div>
        )}
        <p className="mt-2 text-[13px] tabular-nums text-[var(--haip-fg-muted)]">
          {stats ? `${stats.people} reached · ${stats.dm_sent} DMs · ${stats.clicked} clicks · ${stats.leads} leads` : "No activity in this period"}
          {stats && stats.dm_failed > 0 && <span className="text-[var(--haip-status-danger-fg)]"> · {stats.dm_failed} failed</span>}
        </p>
      </div>
      <div className="flex shrink-0 flex-col items-end gap-1">
        <button type="button" onClick={() => toggle.mutate()} disabled={toggle.isPending}
          className="min-h-11 rounded-full border border-[var(--haip-border)] px-3 text-[13px] font-medium">
          {rule.is_active ? "Pause" : "Turn on"}
        </button>
        <div className="flex">
          <button type="button" aria-label={`Edit ${rule.name}`} onClick={onEdit} className="flex size-11 items-center justify-center rounded-full text-[var(--haip-fg-muted)] hover:bg-[var(--haip-surface)]"><Pencil size={16} /></button>
          <button type="button" aria-label={`Delete ${rule.name}`} disabled={remove.isPending}
            onClick={() => { if (confirm(`Delete “${rule.name}”? Its stats stay, but it stops replying.`)) remove.mutate(); }}
            className="flex size-11 items-center justify-center rounded-full text-[var(--haip-fg-muted)] hover:bg-[var(--haip-surface)]"><Trash2 size={16} /></button>
        </div>
      </div>
    </Card>
  );
}

export default function InstagramAutomationsPage() {
  const [days, setDays] = useState<number>(30);
  const [editing, setEditing] = useState<IgRule | null>(null);
  const [open, setOpen] = useState(false);

  const rules = useQuery<IgRule[]>({ queryKey: ["automations"], queryFn: () => api.get("/automations").then(r => r.data) });
  const stats = useQuery<{ automations: IgRuleStats[] }>({
    queryKey: ["ig-automation-stats", days],
    queryFn: () => api.get("/instagram/automations/stats", { params: { days } }).then(r => r.data),
  });

  const ig = (rules.data ?? []).filter(isIgRule);
  const byRule = new Map((stats.data?.automations ?? []).map(s => [s.rule_id, s]));
  const total = (k: keyof IgRuleStats) => (stats.data?.automations ?? []).reduce((n, s) => n + (Number(s[k]) || 0), 0);
  const period = `last ${days} days`;
  const openNew = () => { setEditing(null); setOpen(true); };

  return (
    <div className="mx-auto grid max-w-5xl gap-5">
      <PageHeader title="Instagram automations" subtitle="Reply to comments, story replies and DMs automatically: a public reply plus a DM with your link."
        actions={
          <button type="button" onClick={openNew}
            className="inline-flex min-h-11 items-center gap-2 rounded-full bg-primary px-4 text-[14.5px] font-semibold text-primary-foreground transition-transform active:scale-[0.97]">
            <Plus size={16} /> New automation
          </button>
        } />

      <div className="flex gap-1.5" role="group" aria-label="Period">
        {PERIODS.map(d => (
          <button key={d} type="button" onClick={() => setDays(d)} aria-pressed={days === d}
            className={cn("min-h-11 rounded-full border px-4 text-[13.5px] font-medium",
              days === d ? "border-primary bg-[var(--haip-primary-tint)] text-primary" : "border-[var(--haip-border)]")}>{d} days</button>
        ))}
      </div>

      <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
        <Stat label="People reached" value={total("people")} hint={period} icon={Users} loading={stats.isLoading} />
        <Stat label="DMs sent" value={total("dm_sent")} hint={period} icon={MessageSquare} loading={stats.isLoading} />
        <Stat label="Link clicks" value={total("clicked")} hint={period} icon={Link2} loading={stats.isLoading} />
        <Stat label="Leads" value={total("leads")} hint={`shared a number, ${period}`} icon={BadgeCheck} loading={stats.isLoading} />
      </div>

      {rules.isLoading ? (
        <div className="grid gap-3" aria-busy="true">
          {[0, 1, 2].map(i => <div key={i} className="h-28 animate-pulse rounded-[16px] bg-[var(--haip-surface)]" />)}
        </div>
      ) : rules.isError ? (
        <Card><EmptyState title="Couldn't load automations" hint="Check your connection and try again."
          action={<button type="button" onClick={() => rules.refetch()} className="min-h-11 rounded-full border border-[var(--haip-border)] px-4 text-[14px] font-medium">Try again</button>} /></Card>
      ) : ig.length === 0 ? (
        <Card><EmptyState title="No Instagram automations yet"
          hint="Example: when someone comments PRICE on your reel, reply “Sent you a DM 📩” and DM them your packages with a link."
          action={<button type="button" onClick={openNew} className="inline-flex min-h-11 items-center gap-2 rounded-full bg-primary px-4 text-[14px] font-semibold text-primary-foreground"><Plus size={15} /> Create the first one</button>} /></Card>
      ) : (
        <div className="grid gap-3">
          {ig.map(r => <RuleCard key={r.id} rule={r} stats={byRule.get(r.id)} onEdit={() => { setEditing(r); setOpen(true); }} />)}
        </div>
      )}

      {open && <AutomationBuilder key={editing?.id ?? "new"} open={open} onOpenChange={setOpen} initial={editing} />}
    </div>
  );
}
