"use client";
// Settings > Lead assignment. How new leads get an owner: one main method
// (like IVR routing), optional rules on top, and who takes new leads.
// Backend: GET/PATCH /tenants/me/lead-assignment (lead_assignment_service).
import { useEffect, useState } from "react";
import Link from "next/link";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { useSession } from "next-auth/react";
import api from "@/lib/api";
import { cn } from "@/lib/utils";
import { useToast } from "@/components/ui/toast";
import { Loader2, Shuffle, Users, ArrowLeft, AlertTriangle } from "@/lib/icons";
import { UserCheck } from "lucide-react";

type Mode = "manual" | "round_robin" | "balanced";

interface Agent { id: string; name: string; role: string; takes_leads: boolean; open_uncontacted: number }
interface Settings {
  mode: Mode;
  returning_guest_same_agent: boolean;
  call_answerer_owns: boolean;
  reassign_if_not_contacted: boolean;
  reassign_after_minutes: number;
  working_hours_only: boolean;
  hours_start: string;
  hours_end: string;
  agents: Agent[];
  unassigned_open: number;
}
type Config = Omit<Settings, "agents" | "unassigned_open">;

const MODES: { id: Mode; title: string; desc: string; icon: React.ComponentType<{ size?: number; className?: string; style?: React.CSSProperties }> }[] = [
  { id: "round_robin", title: "Round robin", icon: Shuffle,
    desc: "Each new lead goes to the next available agent in turn." },
  { id: "balanced", title: "Balanced load", icon: Users,
    desc: "Each new lead goes to the available agent with the fewest open leads they haven't contacted yet." },
  { id: "manual", title: "Manual / first to act", icon: UserCheck,
    desc: "No automatic assignment. The first agent who replies to or calls a lead becomes its owner." },
];

function Toggle({ id, checked, onChange, label, desc, children }: {
  id: string; checked: boolean; onChange: (v: boolean) => void; label: string; desc: string; children?: React.ReactNode;
}) {
  return (
    <div className="py-4 flex gap-4" style={{ borderTop: "1px solid var(--haip-border)" }}>
      <div className="flex-1 min-w-0">
        <label htmlFor={id} className="text-sm font-semibold cursor-pointer" style={{ color: "var(--haip-fg)" }}>{label}</label>
        <p className="text-xs mt-0.5" style={{ color: "var(--haip-fg-subtle)" }}>{desc}</p>
        {checked && children && <div className="mt-3">{children}</div>}
      </div>
      <button id={id} type="button" role="switch" aria-checked={checked} onClick={() => onChange(!checked)}
        className={cn("relative w-10 h-6 rounded-full flex-shrink-0 transition-colors outline-none focus-visible:ring-2 focus-visible:ring-teal-600",
          checked ? "bg-teal-600" : "bg-gray-300 dark:bg-gray-600")}>
        <span className={cn("absolute top-0.5 w-5 h-5 rounded-full bg-white shadow transition-transform", checked ? "translate-x-[18px]" : "translate-x-0.5")} />
      </button>
    </div>
  );
}

const inputCls = "text-sm rounded-lg px-2.5 py-1.5 outline-none focus-visible:ring-2 focus-visible:ring-teal-600";
const inputStyle = { background: "var(--haip-card)", border: "1px solid var(--haip-border)", color: "var(--haip-fg)" };

export default function LeadAssignmentPage() {
  const { data: session } = useSession();
  const role = session?.user?.role;
  const canEdit = role === "owner" || role === "manager";
  const qc = useQueryClient();
  const { toast } = useToast();

  const { data, isLoading, isError } = useQuery<Settings>({
    queryKey: ["lead-assignment"],
    queryFn: () => api.get("/tenants/me/lead-assignment").then(r => r.data),
    enabled: canEdit,
  });

  const [cfg, setCfg] = useState<Config | null>(null);
  const [takes, setTakes] = useState<Record<string, boolean>>({});
  useEffect(() => {
    if (!data) return;
    const { agents, unassigned_open: _u, ...rest } = data;
    setCfg(rest);
    setTakes(Object.fromEntries(agents.map(a => [a.id, a.takes_leads])));
  }, [data]);

  const save = useMutation({
    mutationFn: () => api.patch("/tenants/me/lead-assignment", { config: cfg, agents: takes }).then(r => r.data),
    onSuccess: (fresh: Settings) => {
      qc.setQueryData(["lead-assignment"], fresh);
      toast({ variant: "success", title: "Lead assignment saved", description: "New leads follow these rules from now on." });
    },
    onError: (e: unknown) => {
      const detail = (e as { response?: { data?: { detail?: unknown } } })?.response?.data?.detail;
      const msg = typeof detail === "string" ? detail
        : Array.isArray(detail) ? (detail[0] as { msg?: string })?.msg ?? "Check the values and try again."
        : "Check your connection and try again.";
      toast({ variant: "error", title: "Couldn't save", description: msg });
    },
  });

  if (!canEdit) {
    return (
      <div className="p-8 text-sm" style={{ color: "var(--haip-fg-muted)" }}>
        Only an owner or manager can change how leads are assigned.
      </div>
    );
  }
  if (isLoading || !cfg || !data) {
    return (
      <div className="p-8 flex items-center gap-2 text-sm" style={{ color: "var(--haip-fg-muted)" }}>
        {isError ? "Couldn't load lead assignment settings. Refresh to try again." : <><Loader2 size={16} className="animate-spin" /> Loading…</>}
      </div>
    );
  }

  const set = (patch: Partial<Config>) => setCfg(c => (c ? { ...c, ...patch } : c));
  const takers = data.agents.filter(a => takes[a.id]);
  const noTakers = cfg.mode !== "manual" && takers.length === 0;

  return (
    <div className="h-full overflow-y-auto" style={{ background: "var(--haip-bg, var(--background))" }}>
      <div className="max-w-3xl mx-auto px-4 sm:px-6 py-6 space-y-5">
        <div>
          <Link href="/dashboard/settings/team" className="inline-flex items-center gap-1 text-xs font-semibold mb-2" style={{ color: "var(--haip-fg-subtle)" }}>
            <ArrowLeft size={12} /> Team
          </Link>
          <h1 className="haip-page-title">Lead assignment</h1>
          <p className="text-sm mt-0.5" style={{ color: "var(--haip-fg-subtle)" }}>
            How every new WhatsApp, Instagram and call lead gets an owner, so nothing sits unassigned.
          </p>
        </div>

        {data.unassigned_open > 0 && (
          <div className="flex items-start gap-2.5 rounded-xl px-4 py-3 text-sm bg-amber-50 text-amber-900 dark:bg-amber-950/40 dark:text-amber-200">
            <AlertTriangle size={16} className="mt-0.5 flex-shrink-0" />
            <span>
              <strong>{data.unassigned_open} open lead{data.unassigned_open === 1 ? "" : "s"}</strong> have no owner right now.
              {cfg.mode === "manual" ? " Pick round robin or balanced to hand them out automatically."
                : " Leads from the last 3 days are handed out within 5 minutes of saving."}
            </span>
          </div>
        )}

        <section className="haip-card p-5">
          <h2 className="text-[15px] font-bold" style={{ color: "var(--haip-fg)" }}>Main method</h2>
          <p className="text-xs mb-3" style={{ color: "var(--haip-fg-subtle)" }}>Pick one.</p>
          <div className="grid gap-2" role="radiogroup" aria-label="Main method">
            {MODES.map(m => {
              const on = cfg.mode === m.id;
              const Icon = m.icon;
              return (
                <button key={m.id} type="button" role="radio" aria-checked={on} onClick={() => set({ mode: m.id })}
                  className="text-left flex gap-3 rounded-xl px-4 py-3 border transition-colors outline-none focus-visible:ring-2 focus-visible:ring-teal-600"
                  style={on
                    ? { background: "color-mix(in srgb, var(--primary) 10%, var(--haip-card))", borderColor: "var(--primary)" }
                    : { background: "var(--haip-card)", borderColor: "var(--haip-border)" }}>
                  <Icon size={18} className="mt-0.5 flex-shrink-0" style={{ color: on ? "var(--primary)" : "var(--haip-fg-subtle)" }} />
                  <span>
                    <span className="block text-sm font-semibold" style={{ color: "var(--haip-fg)" }}>{m.title}</span>
                    <span className="block text-xs mt-0.5" style={{ color: "var(--haip-fg-subtle)" }}>{m.desc}</span>
                  </span>
                </button>
              );
            })}
          </div>
        </section>

        <section className="haip-card px-5 pt-5 pb-1">
          <h2 className="text-[15px] font-bold" style={{ color: "var(--haip-fg)" }}>Extra rules</h2>
          <p className="text-xs mb-1" style={{ color: "var(--haip-fg-subtle)" }}>Work with any method above.</p>
          <Toggle id="la-returning" checked={cfg.returning_guest_same_agent} onChange={v => set({ returning_guest_same_agent: v })}
            label="Returning guest → same agent"
            desc="A guest who enquired before goes back to the agent who handled them, if that agent is taking leads." />
          <Toggle id="la-call" checked={cfg.call_answerer_owns} onChange={v => set({ call_answerer_owns: v })}
            label="Call answered → that agent"
            desc="When a guest calls and an agent answers, that agent owns the lead, unless someone else has already contacted the guest." />
          <Toggle id="la-reassign" checked={cfg.reassign_if_not_contacted} onChange={v => set({ reassign_if_not_contacted: v })}
            label="Reassign if not contacted"
            desc="If the owner hasn't replied to or called the lead in time, it moves to the next agent and owners/managers get a notification. Passed on at most twice.">
            <label htmlFor="la-minutes" className="text-xs font-semibold flex items-center gap-2" style={{ color: "var(--haip-fg-muted)" }}>
              Wait
              <select id="la-minutes" value={cfg.reassign_after_minutes} onChange={e => set({ reassign_after_minutes: Number(e.target.value) })}
                className={inputCls} style={inputStyle}>
                {[15, 30, 45, 60, 120, 240].map(m => <option key={m} value={m}>{m < 60 ? `${m} minutes` : `${m / 60} hour${m > 60 ? "s" : ""}`}</option>)}
              </select>
              before passing it on
            </label>
          </Toggle>
          <Toggle id="la-hours" checked={cfg.working_hours_only} onChange={v => set({ working_hours_only: v })}
            label="Only during working hours"
            desc="Leads that arrive outside these hours wait and are handed out when the day starts. Reassigning also pauses after hours.">
            <div className="flex flex-wrap items-center gap-2 text-xs font-semibold" style={{ color: "var(--haip-fg-muted)" }}>
              <label htmlFor="la-start">From</label>
              <input id="la-start" type="time" value={cfg.hours_start} onChange={e => set({ hours_start: e.target.value })} className={inputCls} style={inputStyle} />
              <label htmlFor="la-end">to</label>
              <input id="la-end" type="time" value={cfg.hours_end} onChange={e => set({ hours_end: e.target.value })} className={inputCls} style={inputStyle} />
              <span className="font-normal">(your workspace timezone)</span>
            </div>
          </Toggle>
        </section>

        <section className="haip-card p-5">
          <h2 className="text-[15px] font-bold" style={{ color: "var(--haip-fg)" }}>Who takes new leads</h2>
          <p className="text-xs mb-3" style={{ color: "var(--haip-fg-subtle)" }}>
            Untick someone who is on leave or shouldn't receive leads. Their current leads stay with them.
          </p>
          {noTakers && (
            <p className="text-xs font-semibold text-red-700 dark:text-red-300 mb-2">Nobody is ticked, so new leads will stay unassigned.</p>
          )}
          <ul className="divide-y" style={{ borderColor: "var(--haip-border)" }}>
            {data.agents.map(a => (
              <li key={a.id} className="flex items-center gap-3 py-2.5">
                <input id={`la-agent-${a.id}`} type="checkbox" checked={!!takes[a.id]}
                  onChange={e => setTakes(t => ({ ...t, [a.id]: e.target.checked }))}
                  className="w-4 h-4 accent-teal-600" />
                <label htmlFor={`la-agent-${a.id}`} className="flex-1 min-w-0 cursor-pointer">
                  <span className="block text-sm font-semibold truncate" style={{ color: "var(--haip-fg)" }}>{a.name}</span>
                  <span className="block text-xs capitalize" style={{ color: "var(--haip-fg-subtle)" }}>{a.role}</span>
                </label>
                <span className="text-xs tabular-nums" style={{ color: "var(--haip-fg-muted)" }}>
                  {a.open_uncontacted} not yet contacted
                </span>
              </li>
            ))}
          </ul>
        </section>

        <div className="sticky bottom-0 py-3 flex justify-end" style={{ background: "var(--haip-bg, var(--background))" }}>
          <button type="button" onClick={() => save.mutate()} disabled={save.isPending}
            className="inline-flex items-center gap-2 text-sm font-bold px-5 py-2.5 rounded-xl bg-teal-700 text-white hover:bg-teal-800 disabled:opacity-60 outline-none focus-visible:ring-2 focus-visible:ring-teal-600 focus-visible:ring-offset-2">
            {save.isPending && <Loader2 size={14} className="animate-spin" />} Save
          </button>
        </div>
      </div>
    </div>
  );
}
