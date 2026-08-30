"use client";
import { useState, useMemo } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { useSession } from "next-auth/react";
import { Target, TrendingUp, Users, Home, Loader2, AlertCircle, Check, Pencil } from "@/lib/icons";
import api from "@/lib/api";
import { Skeleton } from "@/components/ui/skeleton";

/* ── types ─────────────────────────────────────────────────────────────── */

interface PickupRow {
  date: string; is_future: boolean;
  target_per_day: number; target_till_date: number;
  pickup_of_day: number; pickup_till_date: number;
  this_month: number; next_month: number; future: number;
  variance: number | null;
}
interface Pickup {
  month: string; as_of: string; has_target: boolean;
  monthly_target: number; target_per_day: number;
  picked_up: number; variance: number; achieved_pct: number | null;
  split: { this_month: number; next_month: number; future: number };
  rows: PickupRow[];
}
interface AgentRow {
  agent_id: string; name: string; role: string;
  revenue: number; target: number; achieved_pct: number | null; variance: number | null;
}
interface Agents {
  agents: AgentRow[]; unattributed: number;
  total_revenue: number; total_target: number;
}
interface PropRow {
  property_id: string; name: string; type: string;
  revenue: number; target: number; achieved_pct: number | null;
  variance: number | null; holding_next_month: number;
}
interface Props {
  properties: PropRow[]; next_month: string;
  total_revenue: number; total_target: number; total_holding: number;
}
interface Scopes {
  properties: { id: string; name: string; type: string }[];
  agents: { id: string; name: string; role: string }[];
}

type TabKey = "pickup" | "agents" | "properties";

/* ── helpers ───────────────────────────────────────────────────────────── */

// Indian grouping (₹62,96,252) — how the team actually reads these numbers.
const inr = (n: number) =>
  new Intl.NumberFormat("en-IN", { maximumFractionDigits: 0 }).format(Math.round(n || 0));

function monthKey(d: Date) {
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}`;
}
function monthLabel(key: string) {
  const [y, m] = key.split("-").map(Number);
  return new Date(y, m - 1, 1).toLocaleString(undefined, { month: "long", year: "numeric" });
}
function recentMonths(count = 12) {
  const now = new Date();
  return Array.from({ length: count }, (_, i) => monthKey(new Date(now.getFullYear(), now.getMonth() - i, 1)));
}
function dayNum(iso: string) {
  return Number(iso.split("-")[2]);
}

function Variance({ value }: { value: number | null }) {
  if (value === null || value === undefined) return <span style={{ color: "var(--haip-fg-subtle)" }}>—</span>;
  const good = value >= 0;
  return (
    <span
      className="inline-block px-2 py-0.5 rounded-full text-[11px] font-semibold tabular-nums"
      style={{
        background: good
          ? "color-mix(in srgb, var(--haip-green, #16a34a) 13%, transparent)"
          : "color-mix(in srgb, var(--haip-red, #dc2626) 13%, transparent)",
        color: good ? "var(--haip-green, #16a34a)" : "var(--haip-red, #dc2626)",
      }}
    >
      {good ? "+" : "−"}{inr(Math.abs(value))}
    </span>
  );
}

function Bar({ pct }: { pct: number | null }) {
  if (pct === null || pct === undefined) {
    return <span className="text-[11px]" style={{ color: "var(--haip-fg-subtle)" }}>no target</span>;
  }
  const clamped = Math.min(100, Math.max(0, pct));
  const hit = pct >= 100;
  return (
    <div className="flex items-center gap-2">
      <div className="h-1.5 rounded-full flex-1 min-w-[54px]" style={{ background: "var(--haip-border)" }}>
        <div
          className="h-full rounded-full"
          style={{
            width: `${clamped}%`,
            background: hit ? "var(--haip-green, #16a34a)" : "var(--primary)",
          }}
        />
      </div>
      <span className="text-[11px] font-semibold tabular-nums w-10 text-right" style={{ color: "var(--haip-fg-muted)" }}>
        {Math.round(pct)}%
      </span>
    </div>
  );
}

/* ── target editor ─────────────────────────────────────────────────────── */

function TargetCell({
  scopeType, scopeId, month, current, canEdit,
}: {
  scopeType: "tenant" | "property" | "agent";
  scopeId: string | null;
  month: string;
  current: number;
  canEdit: boolean;
}) {
  const qc = useQueryClient();
  const [editing, setEditing] = useState(false);
  const [val, setVal] = useState(String(current || ""));

  const save = useMutation({
    mutationFn: () =>
      api.put("/targets", {
        scope_type: scopeType,
        scope_id: scopeId,
        period_month: `${month}-01`,
        target_amount: val === "" ? "0" : val,
      }),
    onSuccess: () => {
      // Every report reads targets, so refresh all of them together --
      // a stale agent table beside a fresh pick-up table would show two
      // different targets for the same month.
      ["targets", "pickup", "agents-perf", "props-perf"].forEach(k =>
        qc.invalidateQueries({ queryKey: [k] })
      );
      setEditing(false);
    },
  });

  if (!canEdit) {
    return <span className="tabular-nums">{current ? inr(current) : "—"}</span>;
  }

  if (!editing) {
    return (
      <button
        onClick={() => { setVal(String(current || "")); setEditing(true); }}
        className="inline-flex items-center gap-1.5 tabular-nums hover:underline"
        style={{ color: current ? "var(--haip-fg)" : "var(--haip-fg-subtle)" }}
      >
        {current ? inr(current) : "Set"}
        <Pencil size={11} style={{ color: "var(--haip-fg-subtle)" }} />
      </button>
    );
  }

  return (
    <div className="flex items-center gap-1.5 justify-end">
      <input
        autoFocus
        type="number"
        min={0}
        value={val}
        onChange={e => setVal(e.target.value)}
        onKeyDown={e => {
          if (e.key === "Enter") save.mutate();
          if (e.key === "Escape") setEditing(false);
        }}
        className="w-28 px-2 py-1 rounded-md text-xs text-right tabular-nums"
        style={{ background: "var(--haip-card)", border: "1px solid var(--primary)", color: "var(--haip-fg)" }}
      />
      <button
        onClick={() => save.mutate()}
        disabled={save.isPending}
        className="p-1 rounded-md"
        style={{ background: "var(--primary)", color: "#fff" }}
      >
        {save.isPending ? <Loader2 size={12} className="animate-spin" /> : <Check size={12} />}
      </button>
    </div>
  );
}

/* ── page ──────────────────────────────────────────────────────────────── */

export default function TargetsPage() {
  const { data: session } = useSession();
  const role = session?.user?.role;
  const canEdit = role === "owner" || role === "manager";

  const [month, setMonth] = useState(() => monthKey(new Date()));
  const [tab, setTab] = useState<TabKey>("pickup");
  const months = useMemo(() => recentMonths(12), []);

  const pickup = useQuery<Pickup>({
    queryKey: ["pickup", month],
    queryFn: () => api.get(`/targets/pickup?month=${month}`).then(r => r.data),
  });
  const agents = useQuery<Agents>({
    queryKey: ["agents-perf", month],
    queryFn: () => api.get(`/targets/agents?month=${month}`).then(r => r.data),
    enabled: tab === "agents",
  });
  const props = useQuery<Props>({
    queryKey: ["props-perf", month],
    queryFn: () => api.get(`/targets/properties?month=${month}`).then(r => r.data),
    enabled: tab === "properties",
  });
  const scopes = useQuery<Scopes>({
    queryKey: ["targets-scopes"],
    queryFn: () => api.get("/targets/scopes").then(r => r.data),
  });

  const p = pickup.data;
  const TABS: { key: TabKey; label: string; icon: React.ReactNode }[] = [
    { key: "pickup", label: "Pick-up", icon: <TrendingUp size={14} /> },
    { key: "agents", label: "Agents", icon: <Users size={14} /> },
    { key: "properties", label: "Portfolio", icon: <Home size={14} /> },
  ];

  return (
    <div className="h-full flex flex-col overflow-y-auto">
      {/* header */}
      <div className="px-6 py-5 flex-shrink-0" style={{ background: "var(--haip-card)", borderBottom: "1px solid var(--haip-border)" }}>
        <div className="flex items-start justify-between gap-4 flex-wrap">
          <div>
            <h1 className="haip-page-title">Targets</h1>
            <p className="text-sm mt-0.5" style={{ color: "var(--haip-fg-subtle)" }}>
              Set a monthly number — HAIP splits it across the days and tracks it against real bookings.
            </p>
          </div>
          <select
            value={month}
            onChange={e => setMonth(e.target.value)}
            className="px-3 py-1.5 rounded-lg text-xs"
            style={{ background: "var(--haip-card)", border: "1px solid var(--haip-border)", color: "var(--haip-fg)" }}
          >
            {months.map(m => <option key={m} value={m}>{monthLabel(m)}</option>)}
          </select>
        </div>
      </div>

      <div className="flex-1 p-6">
        <div className="max-w-5xl mx-auto space-y-4">

          {/* monthly target + KPIs */}
          {pickup.isLoading ? (
            <Skeleton className="h-28 rounded-xl" />
          ) : pickup.isError ? (
            <div className="haip-card p-4 flex items-center gap-3" style={{ color: "var(--haip-red, #dc2626)" }}>
              <AlertCircle size={16} /> <span className="text-sm font-medium">Couldn&apos;t load targets.</span>
            </div>
          ) : p && (
            <>
              {!p.has_target && (
                <div
                  className="rounded-xl p-4 flex items-start gap-3"
                  style={{
                    background: "color-mix(in srgb, var(--haip-amber, #d97706) 10%, transparent)",
                    border: "1px solid color-mix(in srgb, var(--haip-amber, #d97706) 30%, transparent)",
                  }}
                >
                  <Target size={16} style={{ color: "var(--haip-amber, #d97706)", marginTop: 2 }} />
                  <div className="text-sm" style={{ color: "var(--haip-fg-2, var(--haip-fg))" }}>
                    <b>No target set for {monthLabel(month)}.</b>{" "}
                    {canEdit
                      ? "Enter a monthly figure below and it will be divided across the days automatically."
                      : "Ask an owner or manager to set one."}
                  </div>
                </div>
              )}

              <div className="grid grid-cols-2 lg:grid-cols-4 gap-2.5">
                <div className="haip-card p-3.5">
                  <p className="text-[10.5px] uppercase tracking-wide font-bold" style={{ color: "var(--haip-fg-subtle)" }}>Monthly target</p>
                  <div className="text-xl font-extrabold tabular-nums mt-1.5">
                    <TargetCell
                      scopeType="tenant" scopeId={null} month={month}
                      current={p.monthly_target} canEdit={canEdit}
                    />
                  </div>
                  <p className="text-[11px] mt-1" style={{ color: "var(--haip-fg-subtle)" }}>
                    {p.target_per_day ? `₹${inr(p.target_per_day)} / day` : "not set"}
                  </p>
                </div>
                <div className="haip-card p-3.5">
                  <p className="text-[10.5px] uppercase tracking-wide font-bold" style={{ color: "var(--haip-fg-subtle)" }}>Picked up</p>
                  <p className="text-xl font-extrabold tabular-nums mt-1.5">{inr(p.picked_up)}</p>
                  <p className="text-[11px] mt-1" style={{ color: "var(--haip-fg-subtle)" }}>
                    {p.achieved_pct !== null ? `${Math.round(p.achieved_pct)}% of target` : "—"}
                  </p>
                </div>
                <div className="haip-card p-3.5">
                  <p className="text-[10.5px] uppercase tracking-wide font-bold" style={{ color: "var(--haip-fg-subtle)" }}>Variance</p>
                  <p className="text-xl font-extrabold tabular-nums mt-1.5"
                     style={{ color: p.variance >= 0 ? "var(--haip-green, #16a34a)" : "var(--haip-red, #dc2626)" }}>
                    {p.variance >= 0 ? "+" : "−"}{inr(Math.abs(p.variance))}
                  </p>
                  <p className="text-[11px] mt-1" style={{ color: "var(--haip-fg-subtle)" }}>
                    {p.has_target ? (p.variance >= 0 ? "ahead" : "behind") : "no target"}
                  </p>
                </div>
                <div className="haip-card p-3.5">
                  <p className="text-[10.5px] uppercase tracking-wide font-bold" style={{ color: "var(--haip-fg-subtle)" }}>Booked forward</p>
                  <p className="text-xl font-extrabold tabular-nums mt-1.5">{inr(p.split.next_month + p.split.future)}</p>
                  <p className="text-[11px] mt-1" style={{ color: "var(--haip-fg-subtle)" }}>for later months</p>
                </div>
              </div>
            </>
          )}

          {/* tabs */}
          <div className="flex gap-2">
            {TABS.map(t => (
              <button
                key={t.key}
                onClick={() => setTab(t.key)}
                className="inline-flex items-center gap-1.5 px-3.5 py-2 rounded-lg text-xs font-semibold transition-colors"
                style={tab === t.key
                  ? { background: "var(--primary)", color: "#fff" }
                  : { background: "var(--haip-card)", border: "1px solid var(--haip-border)", color: "var(--haip-fg-muted)" }}
              >
                {t.icon}{t.label}
              </button>
            ))}
          </div>

          {/* ── pick-up ─────────────────────────────────────────────── */}
          {tab === "pickup" && (
            <div className="haip-card overflow-hidden">
              <div className="px-4 py-3" style={{ borderBottom: "1px solid var(--haip-border)" }}>
                <p className="text-sm font-semibold">Daily pick-up</p>
                <p className="text-[11px]" style={{ color: "var(--haip-fg-subtle)" }}>
                  Revenue by the day the booking was made, split by the month the guest stays in
                </p>
              </div>
              {pickup.isLoading ? (
                <div className="p-4 space-y-2">{[1, 2, 3].map(i => <Skeleton key={i} className="h-9 rounded-lg" />)}</div>
              ) : (
                <div className="overflow-x-auto">
                  <table className="w-full text-[13px]" style={{ minWidth: 720 }}>
                    <thead>
                      <tr style={{ background: "var(--muted)" }}>
                        <th className="text-left px-3 py-2 font-semibold text-[11px] uppercase tracking-wide">Day</th>
                        <th className="text-right px-3 py-2 font-semibold text-[11px] uppercase tracking-wide">Target till date</th>
                        <th className="text-right px-3 py-2 font-semibold text-[11px] uppercase tracking-wide">Pick-up of day</th>
                        <th className="text-right px-3 py-2 font-semibold text-[11px] uppercase tracking-wide">Pick-up till date</th>
                        <th className="text-right px-3 py-2 font-semibold text-[11px] uppercase tracking-wide">This month</th>
                        <th className="text-right px-3 py-2 font-semibold text-[11px] uppercase tracking-wide">Next</th>
                        <th className="text-right px-3 py-2 font-semibold text-[11px] uppercase tracking-wide">Future</th>
                        <th className="text-right px-3 py-2 font-semibold text-[11px] uppercase tracking-wide">Surplus / deficit</th>
                      </tr>
                    </thead>
                    <tbody>
                      {p?.rows.map(r => (
                        <tr key={r.date} style={{
                          borderTop: "1px solid var(--haip-border)",
                          opacity: r.is_future ? 0.45 : 1,
                        }}>
                          <td className="px-3 py-2 font-semibold">{dayNum(r.date)}</td>
                          <td className="px-3 py-2 text-right tabular-nums" style={{ color: "var(--haip-fg-muted)" }}>{inr(r.target_till_date)}</td>
                          <td className="px-3 py-2 text-right tabular-nums font-semibold">{r.pickup_of_day ? inr(r.pickup_of_day) : "—"}</td>
                          <td className="px-3 py-2 text-right tabular-nums">{inr(r.pickup_till_date)}</td>
                          <td className="px-3 py-2 text-right tabular-nums" style={{ color: "var(--haip-fg-muted)" }}>{r.this_month ? inr(r.this_month) : "—"}</td>
                          <td className="px-3 py-2 text-right tabular-nums" style={{ color: "var(--haip-fg-muted)" }}>{r.next_month ? inr(r.next_month) : "—"}</td>
                          <td className="px-3 py-2 text-right tabular-nums" style={{ color: "var(--haip-fg-muted)" }}>{r.future ? inr(r.future) : "—"}</td>
                          <td className="px-3 py-2 text-right"><Variance value={r.variance} /></td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </div>
          )}

          {/* ── agents ──────────────────────────────────────────────── */}
          {tab === "agents" && (
            <div className="haip-card overflow-hidden">
              <div className="px-4 py-3" style={{ borderBottom: "1px solid var(--haip-border)" }}>
                <p className="text-sm font-semibold">Individual performance</p>
                <p className="text-[11px]" style={{ color: "var(--haip-fg-subtle)" }}>
                  Revenue credited via the lead each booking came from
                </p>
              </div>
              {agents.isLoading ? (
                <div className="p-4 space-y-2">{[1, 2].map(i => <Skeleton key={i} className="h-9 rounded-lg" />)}</div>
              ) : (
                <div className="overflow-x-auto">
                  <table className="w-full text-[13px]" style={{ minWidth: 560 }}>
                    <thead>
                      <tr style={{ background: "var(--muted)" }}>
                        <th className="text-left px-3 py-2 font-semibold text-[11px] uppercase tracking-wide">Agent</th>
                        <th className="text-right px-3 py-2 font-semibold text-[11px] uppercase tracking-wide">Revenue</th>
                        <th className="text-right px-3 py-2 font-semibold text-[11px] uppercase tracking-wide">Target</th>
                        <th className="text-left px-3 py-2 font-semibold text-[11px] uppercase tracking-wide" style={{ width: 150 }}>Achieved</th>
                        <th className="text-right px-3 py-2 font-semibold text-[11px] uppercase tracking-wide">Variance</th>
                      </tr>
                    </thead>
                    <tbody>
                      {agents.data?.agents.map(a => (
                        <tr key={a.agent_id} style={{ borderTop: "1px solid var(--haip-border)" }}>
                          <td className="px-3 py-2.5 font-semibold">{a.name}</td>
                          <td className="px-3 py-2.5 text-right tabular-nums font-semibold">{inr(a.revenue)}</td>
                          <td className="px-3 py-2.5 text-right">
                            <TargetCell scopeType="agent" scopeId={a.agent_id} month={month} current={a.target} canEdit={canEdit} />
                          </td>
                          <td className="px-3 py-2.5"><Bar pct={a.achieved_pct} /></td>
                          <td className="px-3 py-2.5 text-right"><Variance value={a.variance} /></td>
                        </tr>
                      ))}
                      {!!agents.data?.unattributed && (
                        <tr style={{ borderTop: "1px solid var(--haip-border)" }}>
                          <td className="px-3 py-2.5" style={{ color: "var(--haip-fg-subtle)" }}>
                            Unattributed
                            <span className="block text-[10.5px]">bookings with no lead owner</span>
                          </td>
                          <td className="px-3 py-2.5 text-right tabular-nums" style={{ color: "var(--haip-fg-muted)" }}>{inr(agents.data.unattributed)}</td>
                          <td className="px-3 py-2.5 text-right" style={{ color: "var(--haip-fg-subtle)" }}>—</td>
                          <td className="px-3 py-2.5" style={{ color: "var(--haip-fg-subtle)" }}>—</td>
                          <td className="px-3 py-2.5 text-right" style={{ color: "var(--haip-fg-subtle)" }}>—</td>
                        </tr>
                      )}
                    </tbody>
                    <tfoot>
                      <tr style={{ borderTop: "2px solid var(--haip-border)", background: "var(--muted)" }}>
                        <td className="px-3 py-2.5 font-bold">Total</td>
                        <td className="px-3 py-2.5 text-right tabular-nums font-bold">{inr(agents.data?.total_revenue ?? 0)}</td>
                        <td className="px-3 py-2.5 text-right tabular-nums font-bold">{inr(agents.data?.total_target ?? 0)}</td>
                        <td colSpan={2} />
                      </tr>
                    </tfoot>
                  </table>
                </div>
              )}
            </div>
          )}

          {/* ── properties ──────────────────────────────────────────── */}
          {tab === "properties" && (
            <div className="haip-card overflow-hidden">
              <div className="px-4 py-3" style={{ borderBottom: "1px solid var(--haip-border)" }}>
                <p className="text-sm font-semibold">Portfolio performance</p>
                <p className="text-[11px]" style={{ color: "var(--haip-fg-subtle)" }}>
                  Revenue per property, with what&apos;s already booked for next month
                </p>
              </div>
              {props.isLoading ? (
                <div className="p-4 space-y-2">{[1, 2].map(i => <Skeleton key={i} className="h-9 rounded-lg" />)}</div>
              ) : (
                <div className="overflow-x-auto">
                  <table className="w-full text-[13px]" style={{ minWidth: 600 }}>
                    <thead>
                      <tr style={{ background: "var(--muted)" }}>
                        <th className="text-left px-3 py-2 font-semibold text-[11px] uppercase tracking-wide">Property</th>
                        <th className="text-right px-3 py-2 font-semibold text-[11px] uppercase tracking-wide">Revenue</th>
                        <th className="text-right px-3 py-2 font-semibold text-[11px] uppercase tracking-wide">Target</th>
                        <th className="text-left px-3 py-2 font-semibold text-[11px] uppercase tracking-wide" style={{ width: 150 }}>Achieved</th>
                        <th className="text-right px-3 py-2 font-semibold text-[11px] uppercase tracking-wide">Holding next month</th>
                      </tr>
                    </thead>
                    <tbody>
                      {props.data?.properties.map(pr => (
                        <tr key={pr.property_id} style={{ borderTop: "1px solid var(--haip-border)" }}>
                          <td className="px-3 py-2.5 font-semibold">{pr.name}</td>
                          <td className="px-3 py-2.5 text-right tabular-nums font-semibold">{inr(pr.revenue)}</td>
                          <td className="px-3 py-2.5 text-right">
                            <TargetCell scopeType="property" scopeId={pr.property_id} month={month} current={pr.target} canEdit={canEdit} />
                          </td>
                          <td className="px-3 py-2.5"><Bar pct={pr.achieved_pct} /></td>
                          <td className="px-3 py-2.5 text-right tabular-nums" style={{ color: "var(--haip-fg-muted)" }}>{inr(pr.holding_next_month)}</td>
                        </tr>
                      ))}
                    </tbody>
                    <tfoot>
                      <tr style={{ borderTop: "2px solid var(--haip-border)", background: "var(--muted)" }}>
                        <td className="px-3 py-2.5 font-bold">Total</td>
                        <td className="px-3 py-2.5 text-right tabular-nums font-bold">{inr(props.data?.total_revenue ?? 0)}</td>
                        <td className="px-3 py-2.5 text-right tabular-nums font-bold">{inr(props.data?.total_target ?? 0)}</td>
                        <td />
                        <td className="px-3 py-2.5 text-right tabular-nums font-bold">{inr(props.data?.total_holding ?? 0)}</td>
                      </tr>
                    </tfoot>
                  </table>
                </div>
              )}
            </div>
          )}

          {scopes.data && (scopes.data.properties.length === 0 || scopes.data.agents.length === 0) && (
            <p className="text-[11.5px]" style={{ color: "var(--haip-fg-subtle)" }}>
              Targets are driven by your own portfolio and team — add properties or agents and they appear here automatically.
            </p>
          )}
        </div>
      </div>
    </div>
  );
}
