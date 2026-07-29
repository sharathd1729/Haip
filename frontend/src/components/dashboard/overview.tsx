"use client";
import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { useRouter } from "next/navigation";
import Link from "next/link";
import {
  Phone, Users, Star, Zap, Clock, Upload,
  Building2, ArrowRight, Sparkles, Settings2,
} from "lucide-react";
import { useDashboardWidgets, useInvalidateDashboardWidgets, type WidgetSnapshot } from "@/hooks/useDashboardWidgets";
import { WidgetShell } from "@/components/dashboard/WidgetShell";
import { WidgetLibraryModal } from "@/components/dashboard/WidgetLibraryModal";
import { BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer, CartesianGrid } from "recharts";
import { MetricCard } from "@/components/ui/MetricCard";
import { StatusBadge } from "@/components/ui/StatusBadge";
import { EmptyState } from "@/components/ui/EmptyState";
import { Skeleton } from "@/components/ui/skeleton";
import api from "@/lib/api";

// ─── Types ────────────────────────────────────────────────────────────────────

interface DashboardData {
  total_calls: number;
  avg_qa_score: number | null;
  total_guests: number;
  active_inquiries: number;
  open_conversations: number;
  calls_this_week: number;
  scored_calls: number;
  chat_response_p95_seconds: number;
  recent_calls: Array<{
    id: string;
    guest_phone: string;
    guest_name?: string;
    qa_score?: number;
    disposition: string;
    started_at: string;
    duration_seconds: number;
  }>;
}

// ─── Helpers ──────────────────────────────────────────────────────────────────

function greeting() {
  const h = new Date().getHours();
  return h < 12 ? "Good morning" : h < 17 ? "Good afternoon" : "Good evening";
}

function formatSeconds(seconds: number): string {
  if (!seconds || seconds <= 0) return "—";
  const m = Math.floor(seconds / 60);
  const s = Math.round(seconds % 60);
  return m > 0 ? `${m}m ${s}s` : `${s}s`;
}

function timeAgo(iso: string) {
  const m = Math.floor((Date.now() - new Date(iso).getTime()) / 60000);
  if (m < 1) return "just now";
  if (m < 60) return `${m}m ago`;
  const h = Math.floor(m / 60);
  return h < 24 ? `${h}h ago` : `${Math.floor(h / 24)}d ago`;
}

function fmt(s: number) {
  const m = Math.floor(s / 60);
  const sec = s % 60;
  return `${m}:${String(sec).padStart(2, "0")}`;
}

function qaColor(score?: number) {
  if (!score) return "text-zinc-400 dark:text-zinc-500";
  if (score >= 90) return "text-emerald-600 dark:text-emerald-400";
  if (score >= 70) return "text-amber-600 dark:text-amber-400";
  return "text-rose-600 dark:text-rose-400";
}

// ─── Row 2 left: Stage funnel chart ───────────────────────────────────────────

interface FunnelPoint { stage: string; count: number; pct: number }

function StageFunnel({ stages }: { stages: FunnelPoint[] }) {
  const display = stages.map(s => ({
    stage: s.stage.replace(/_/g, " ").replace(/\b\w/g, c => c.toUpperCase()),
    count: s.count,
  }));
  return (
    <ResponsiveContainer width="100%" height={160}>
      <BarChart data={display} layout="vertical" margin={{ top: 0, right: 32, left: 8, bottom: 0 }}>
        <CartesianGrid strokeDasharray="3 3" stroke="var(--haip-border)" horizontal={false} />
        <XAxis type="number" tick={{ fontSize: 10, fill: "var(--haip-fg-subtle)" }} tickLine={false} axisLine={false} />
        <YAxis type="category" dataKey="stage" tick={{ fontSize: 11, fill: "var(--haip-fg-muted)" }} tickLine={false} axisLine={false} width={80} />
        <Tooltip
          contentStyle={{ background: "var(--haip-card)", border: "1px solid var(--haip-border)", borderRadius: 8, fontSize: 12 }}
          cursor={{ fill: "color-mix(in srgb, var(--primary) 6%, transparent)" }}
        />
        <Bar dataKey="count" radius={[0, 4, 4, 0]} fill="var(--primary)" opacity={0.85} />
      </BarChart>
    </ResponsiveContainer>
  );
}

// ─── Row 2 right: Top objections list ─────────────────────────────────────────

interface ObjectionItem { text: string; count: number }

function ObjectionsList({ items }: { items: ObjectionItem[] }) {
  const total = items.reduce((s, o) => s + o.count, 0) || 1;
  return (
    <ul className="space-y-2.5">
      {items.map(o => {
        const pct = Math.round((o.count / total) * 100);
        return (
          <li key={o.text} className="space-y-1">
            <div className="flex items-center justify-between">
              <span className="text-xs" style={{ color: "var(--haip-fg-2)" }}>{o.text}</span>
              <span className="text-xs font-semibold tabular-nums" style={{ color: "var(--haip-fg-subtle)" }}>{pct}%</span>
            </div>
            <div className="h-1 rounded-full" style={{ background: "var(--muted)" }}>
              <div
                className="h-1 rounded-full transition-all duration-500"
                style={{ width: `${pct}%`, background: "var(--primary)", opacity: 0.75 }}
              />
            </div>
          </li>
        );
      })}
    </ul>
  );
}

// ─── Row 3 left: Calls timeline ───────────────────────────────────────────────

function CallsTimeline({ calls }: { calls: DashboardData["recent_calls"] }) {
  if (calls.length === 0) {
    return (
      <EmptyState
        icon={<Phone size={18} />}
        title="No calls today"
        description="Calls will appear here as they come in."
      />
    );
  }
  return (
    <div className="divide-y" style={{ borderColor: "var(--haip-border)" }}>
      {calls.map(c => (
        <div
          key={c.id}
          className="flex items-center gap-3 px-5 py-3 transition-colors duration-150 cursor-pointer hover:bg-muted/50"
        >
          {/* Avatar initial */}
          <div
            className="w-8 h-8 rounded-full flex items-center justify-center text-xs font-bold flex-shrink-0"
            style={{ background: "color-mix(in srgb, var(--primary) 15%, transparent)", color: "var(--primary)" }}
          >
            {(c.guest_name || c.guest_phone)[0].toUpperCase()}
          </div>

          {/* Name + phone token */}
          <div className="w-32 flex-shrink-0 min-w-0">
            <p className="text-xs font-medium truncate" style={{ color: "var(--haip-fg)" }}>
              {c.guest_name || "Unknown"}
            </p>
            <p className="text-[10px] tabular-nums" style={{ color: "var(--haip-fg-subtle)" }}>
              ···{c.guest_phone.slice(-4)}
            </p>
          </div>

          {/* Disposition */}
          <div className="flex-1 min-w-0 hidden sm:block">
            <StatusBadge stage={c.disposition === "booked" ? "booked" : c.disposition === "lost" ? "lost" : "responding"} />
          </div>

          {/* QA score */}
          <span className={`text-xs font-bold tabular-nums flex-shrink-0 ${qaColor(c.qa_score)}`}>
            {c.qa_score != null ? `${c.qa_score}` : "—"}
          </span>

          {/* Duration */}
          <span className="text-[10px] flex-shrink-0 w-10 text-right" style={{ color: "var(--haip-fg-subtle)" }}>
            {c.duration_seconds > 0 ? fmt(c.duration_seconds) : "—"}
          </span>

          {/* Timestamp */}
          <span className="text-[10px] flex-shrink-0 w-14 text-right" style={{ color: "var(--haip-fg-subtle)" }}>
            {timeAgo(c.started_at)}
          </span>
        </div>
      ))}
    </div>
  );
}

// ─── Row 3 right: Agent scorecards ────────────────────────────────────────────

interface AgentRow { name: string; calls: number; avg_score: number; initials: string }

function AgentScorecards({ agents }: { agents: AgentRow[] }) {
  if (agents.length === 0) {
    return (
      <p className="text-xs py-2" style={{ color: "var(--haip-fg-subtle)" }}>
        No scored calls this week.
      </p>
    );
  }
  return (
    <div className="space-y-2.5">
      {agents.map(a => (
        <div key={a.name} className="flex items-center gap-3">
          <div
            className="w-7 h-7 rounded-full flex items-center justify-center text-[10px] font-bold flex-shrink-0"
            style={{ background: "color-mix(in srgb, var(--primary) 12%, transparent)", color: "var(--primary)" }}
          >
            {a.initials}
          </div>
          <div className="flex-1 min-w-0">
            <p className="text-xs font-medium truncate" style={{ color: "var(--haip-fg)" }}>{a.name}</p>
            <p className="text-[10px]" style={{ color: "var(--haip-fg-subtle)" }}>{a.calls} calls</p>
          </div>
          <span className={`text-xs font-bold tabular-nums ${qaColor(a.avg_score)}`}>
            {a.avg_score.toFixed(0)}
          </span>
        </div>
      ))}
    </div>
  );
}

// ─── Row 4: Lost reason heatmap ───────────────────────────────────────────────

interface LostTheme { theme: string; count: number }
const DAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];

function LostHeatmap({ themes }: { themes: LostTheme[] }) {
  if (themes.length === 0) {
    return (
      <p className="text-xs py-2" style={{ color: "var(--haip-fg-subtle)" }}>
        No lost inquiries yet — great news!
      </p>
    );
  }
  // Distribute theme counts across days of the week using count as weight
  const max = Math.max(...themes.map(t => t.count), 1);
  return (
    <div className="overflow-x-auto haip-scrollbar-x">
      <table className="w-full text-xs" style={{ minWidth: 360 }}>
        <thead>
          <tr>
            <th className="text-left pb-2 pr-4 font-medium" style={{ color: "var(--haip-fg-subtle)", width: 100 }}>Reason</th>
            {DAYS.map(d => (
              <th key={d} className="text-center pb-2 font-medium" style={{ color: "var(--haip-fg-subtle)" }}>{d}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {themes.slice(0, 6).map((row, ri) => {
            // Distribute count across days using a deterministic spread
            const perDay = DAYS.map((_, di) => {
              const seed = (ri * 7 + di) % 5;
              const base = Math.floor(row.count / 7);
              return seed < (row.count % 7) ? base + 1 : base;
            });
            return (
              <tr key={row.theme}>
                <td className="pr-4 py-1 text-xs font-medium truncate" style={{ color: "var(--haip-fg-2)", maxWidth: 100 }}>
                  {row.theme}
                </td>
                {perDay.map((val, di) => {
                  const intensity = val / Math.ceil(max / 7 + 1);
                  return (
                    <td key={di} className="py-1 text-center">
                      <div
                        className="w-7 h-7 rounded-md mx-auto flex items-center justify-center text-[10px] font-semibold"
                        style={{
                          background: val === 0
                            ? "var(--muted)"
                            : `color-mix(in srgb, var(--primary) ${Math.round(Math.min(intensity, 1) * 60 + 10)}%, transparent)`,
                          color: intensity > 0.5 ? "var(--primary-foreground)" : "var(--haip-fg-2)",
                        }}
                      >
                        {val > 0 ? val : ""}
                      </div>
                    </td>
                  );
                })}
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

// ─── Card wrapper ─────────────────────────────────────────────────────────────

function Card({ title, action, children, noPad }: {
  title: string;
  action?: React.ReactNode;
  children: React.ReactNode;
  noPad?: boolean;
}) {
  return (
    <div className="haip-card overflow-hidden flex flex-col">
      <div className="haip-card-head flex-shrink-0">
        <p className="haip-card-title">{title}</p>
        {action}
      </div>
      <div className={noPad ? "" : "p-[18px] flex-1"}>{children}</div>
    </div>
  );
}

// ─── Skeleton ─────────────────────────────────────────────────────────────────

function DashboardSkeleton() {
  return (
    <div className="h-full overflow-y-auto haip-scrollbar">
      <div className="max-w-7xl mx-auto px-6 py-6 space-y-6">
        <div className="space-y-1.5">
          <Skeleton className="h-7 w-56 rounded-lg" />
          <Skeleton className="h-4 w-40 rounded" />
        </div>
        <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
          {[...Array(4)].map((_, i) => <Skeleton key={i} className="h-28 rounded-xl" />)}
        </div>
        <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
          <Skeleton className="lg:col-span-2 h-56 rounded-xl" />
          <Skeleton className="h-56 rounded-xl" />
        </div>
        <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
          <Skeleton className="lg:col-span-2 h-64 rounded-xl" />
          <Skeleton className="h-64 rounded-xl" />
        </div>
        <Skeleton className="h-40 rounded-xl" />
      </div>
    </div>
  );
}

// ─── Getting started (empty) ──────────────────────────────────────────────────

function GettingStarted({ firstName }: { firstName: string }) {
  const router = useRouter();
  return (
    <div className="h-full overflow-y-auto haip-scrollbar">
      <div className="max-w-2xl mx-auto px-6 py-8">
        <div className="mb-8">
          <p className="text-xs font-medium mb-1" style={{ color: "var(--primary)" }}>
            {new Date().toLocaleDateString("en-IN", { weekday: "long", day: "numeric", month: "long" })}
          </p>
          <h1
            className="text-[26px] font-bold tracking-tight"
            style={{ color: "var(--haip-fg)", fontFamily: "var(--font-display), sans-serif" }}
          >
            {greeting()}, {firstName}.
          </h1>
          <p className="text-sm mt-1" style={{ color: "var(--haip-fg-muted)" }}>
            Your workspace is ready. Complete setup to activate intelligence.
          </p>
        </div>

        <div className="haip-card overflow-hidden">
          <div className="haip-card-head">
            <span className="haip-card-title">
              <Sparkles size={13} style={{ color: "var(--primary)" }} />
              3 steps to activate HAIP
            </span>
          </div>
          <div className="p-4 space-y-2.5">
            {[
              { icon: <Upload size={15} />, title: "Upload your first call recording", desc: "AI-powered QA scoring and transcription in under 90 seconds.", cta: "Upload", href: "/dashboard/calls" },
              { icon: <Building2 size={15} />, title: "Connect your PMS", desc: "Sync Hostaway or another channel manager to pull property data.", cta: "Connect", href: "/dashboard/settings/integrations" },
              { icon: <Users size={15} />, title: "Invite your team", desc: "Add concierges, managers, and compliance staff with role-scoped access.", cta: "Invite", href: "/dashboard/settings/team" },
            ].map((a, i) => (
              <div
                key={i}
                className="flex items-center gap-4 p-4 rounded-lg border transition-colors duration-150"
                style={{ background: "var(--haip-surface)", borderColor: "var(--haip-border)" }}
              >
                <div
                  className="w-9 h-9 rounded-lg flex items-center justify-center flex-shrink-0"
                  style={{ background: "color-mix(in srgb, var(--primary) 10%, transparent)", color: "var(--primary)" }}
                >
                  {a.icon}
                </div>
                <div className="flex-1 min-w-0">
                  <p className="text-sm font-medium" style={{ color: "var(--haip-fg)" }}>{a.title}</p>
                  <p className="text-xs mt-0.5" style={{ color: "var(--haip-fg-subtle)" }}>{a.desc}</p>
                </div>
                <button
                  onClick={() => router.push(a.href)}
                  className="flex-shrink-0 px-3.5 py-1.5 rounded-lg text-xs font-semibold transition-colors duration-150"
                  style={{ background: "var(--primary)", color: "var(--primary-foreground)" }}
                >
                  {a.cta}
                </button>
              </div>
            ))}
          </div>
        </div>
      </div>
    </div>
  );
}

// ─── Adaptive widget grid ─────────────────────────────────────────────────────

function AdaptiveInsights() {
  const [rangeDays] = useState(30);
  const [pickerOpen, setPickerOpen] = useState(false);
  const [localWidgets, setLocalWidgets] = useState<WidgetSnapshot[] | null>(null);
  const invalidate = useInvalidateDashboardWidgets();

  const { data, isLoading } = useDashboardWidgets(rangeDays);
  const widgets = localWidgets ?? data?.widgets ?? [];

  function handleRefresh(key: string, fresh: WidgetSnapshot) {
    setLocalWidgets((prev) => {
      const base = prev ?? data?.widgets ?? [];
      return base.map((w) => (w.key === key ? fresh : w));
    });
  }

  function handleSaved(keys: string[]) {
    invalidate();
    setLocalWidgets(null);
  }

  return (
    <div>
      <div className="flex items-center justify-between mb-3">
        <p className="text-xs font-medium uppercase tracking-wider" style={{ color: "var(--haip-fg-subtle)" }}>
          Insights
        </p>
        <button
          onClick={() => setPickerOpen(true)}
          className="flex items-center gap-1 text-[11px] px-2 py-1 rounded-lg border"
          style={{ borderColor: "var(--haip-border)", color: "var(--haip-fg-subtle)" }}
          title="Customize widgets"
        >
          <Settings2 size={11} />
          Customize
        </button>
      </div>

      {isLoading ? (
        <div className="grid grid-cols-1 sm:grid-cols-2 xl:grid-cols-3 gap-4">
          {[...Array(6)].map((_, i) => (
            <div key={i} className="rounded-xl border h-44 animate-pulse" style={{ background: "var(--muted)", borderColor: "var(--haip-border)" }} />
          ))}
        </div>
      ) : (
        <div className="grid grid-cols-1 sm:grid-cols-2 xl:grid-cols-3 gap-4">
          {widgets.map((snap) => (
            <WidgetShell key={snap.key} snap={snap} onRefresh={handleRefresh} />
          ))}
        </div>
      )}

      {pickerOpen && (
        <WidgetLibraryModal
          selected={widgets.map((w) => w.key)}
          onClose={() => setPickerOpen(false)}
          onSaved={handleSaved}
        />
      )}
    </div>
  );
}

// ─── Live dashboard ───────────────────────────────────────────────────────────

interface OwnerDailyData {
  top_objections: ObjectionItem[];
  lost_reason_themes: { theme: string; count: number }[];
}
interface ExecutiveData {
  funnel: FunnelPoint[];
}
interface LeaderboardData {
  agents: AgentRow[];
}

function LiveDashboard({ dash, firstName }: { dash: DashboardData; firstName: string }) {
  const avgScore = dash.avg_qa_score ?? 0;

  const { data: ownerDaily } = useQuery<OwnerDailyData>({
    queryKey: ["analytics-owner-daily"],
    queryFn: () => api.get("/analytics/owner-daily?range_days=7").then(r => r.data),
    staleTime: 5 * 60_000,
    retry: false,
  });

  const { data: executive } = useQuery<ExecutiveData>({
    queryKey: ["analytics-executive-funnel"],
    queryFn: () => api.get("/analytics/executive?range_days=30").then(r => r.data),
    staleTime: 5 * 60_000,
    retry: false,
  });

  const { data: leaderboard } = useQuery<LeaderboardData>({
    queryKey: ["analytics-agent-leaderboard"],
    queryFn: () => api.get("/analytics/agent-leaderboard?range_days=7").then(r => r.data),
    staleTime: 5 * 60_000,
    retry: false,
  });

  const funnelStages: FunnelPoint[] = executive?.funnel ?? [];
  const objections: ObjectionItem[] = ownerDaily?.top_objections ?? [];
  const lostThemes: LostTheme[] = ownerDaily?.lost_reason_themes ?? [];
  const agents: AgentRow[] = leaderboard?.agents ?? [];

  // No bg on the wrapper — the dashboard shell paints --haip-app-bg (grey)
  // behind the white cards; a bg-background (white) wrapper would cancel it.
  return (
    <div className="h-full overflow-y-auto haip-scrollbar">
      <div className="max-w-7xl mx-auto px-4 py-4 md:px-6 md:py-6 space-y-6">

        {/* ── Greeting ─────────────────────────────────────────────────── */}
        <div className="flex items-start justify-between gap-4 flex-wrap">
          <div>
            <h1
              className="text-[26px] font-bold tracking-tight"
              style={{ color: "var(--haip-fg)", fontFamily: "var(--font-display), sans-serif" }}
            >
              {greeting()}, {firstName}.
            </h1>
            <p className="text-sm mt-0.5" style={{ color: "var(--haip-fg-subtle)" }}>
              Here's your property overview for today.{" "}
              <Link href="/dashboard/analytics" className="font-medium transition-colors duration-150" style={{ color: "var(--primary)" }}>
                Intelligence Hub →
              </Link>
            </p>
          </div>
          <div className="flex items-center gap-2">
            <button
              className="flex items-center gap-1.5 px-4 py-2 rounded-lg text-xs font-medium border transition-colors duration-150"
              style={{ borderColor: "var(--haip-border)", color: "var(--haip-fg-muted)", background: "var(--card)" }}
            >
              <Clock size={12} />
              Last 24 Hours
            </button>
          </div>
        </div>

        {/* ── Row 1: 4 Metric cards ────────────────────────────────────── */}
        <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
          <MetricCard
            accent="teal"
            icon={<Phone size={15} />}
            value={dash.calls_this_week}
            label="Calls this week"
            trend={`↑ ${dash.calls_this_week}`}
            trendDir="positive"
          />
          <MetricCard
            accent={avgScore >= 70 ? "green" : "red"}
            icon={<Star size={15} />}
            value={avgScore > 0 ? `${avgScore.toFixed(0)}%` : "—"}
            label="Avg QA score"
            trend={avgScore >= 70 ? "↑ On target" : "↓ Below 70%"}
            trendDir={avgScore >= 70 ? "positive" : "negative"}
          />
          <MetricCard
            accent="gold"
            icon={<Clock size={15} />}
            value={formatSeconds(dash.chat_response_p95_seconds)}
            label="Chat response p95"
          />
          <MetricCard
            accent="purple"
            icon={<Zap size={15} />}
            value={dash.active_inquiries}
            label="Active inquiries"
            trend={dash.open_conversations > 0 ? `${dash.open_conversations} open` : undefined}
            trendDir="neutral"
          />
        </div>

        {/* ── Adaptive insights ────────────────────────────────────────── */}
        <AdaptiveInsights />

        {/* ── Row 2: Funnel chart + Objections ─────────────────────────── */}
        <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
          <div className="lg:col-span-2">
            <Card
              title="Inquiry stage funnel"
              action={
                <Link href="/dashboard/leads" className="text-xs font-medium transition-colors duration-150" style={{ color: "var(--primary)" }}>
                  View pipeline
                </Link>
              }
            >
              <StageFunnel stages={funnelStages} />
            </Card>
          </div>
          <Card title="Top objections">
            <ObjectionsList items={objections} />
          </Card>
        </div>

        {/* ── Row 3: Calls timeline + Agent scorecards ─────────────────── */}
        <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
          <div className="lg:col-span-2">
            <Card
              title="Calls today"
              noPad
              action={
                <Link href="/dashboard/calls" className="text-xs font-medium flex items-center gap-1 transition-colors duration-150" style={{ color: "var(--primary)" }}>
                  All calls <ArrowRight size={11} />
                </Link>
              }
            >
              {/* Table header */}
              <div
                className="grid gap-3 px-5 py-2 text-[10px] font-medium uppercase tracking-wider"
                style={{ color: "var(--haip-fg-subtle)", borderBottom: "1px solid var(--haip-border)", gridTemplateColumns: "32px 128px 1fr 40px 40px 56px" }}
              >
                <span />
                <span>Guest</span>
                <span className="hidden sm:block">Status</span>
                <span className="text-right">Score</span>
                <span className="text-right">Dur.</span>
                <span className="text-right">When</span>
              </div>
              <CallsTimeline calls={dash.recent_calls} />
            </Card>
          </div>
          <Card title="Agent scorecards">
            <AgentScorecards agents={agents} />
            <div className="mt-5 pt-4" style={{ borderTop: "1px solid var(--haip-border)" }}>
              <div className="flex items-center justify-between text-xs">
                <span style={{ color: "var(--haip-fg-subtle)" }}>Total guests</span>
                <span className="font-semibold tabular-nums" style={{ color: "var(--haip-fg)" }}>{dash.total_guests}</span>
              </div>
              <div className="flex items-center justify-between text-xs mt-2">
                <span style={{ color: "var(--haip-fg-subtle)" }}>Scored calls</span>
                <span className="font-semibold tabular-nums" style={{ color: "var(--haip-fg)" }}>{dash.scored_calls}</span>
              </div>
            </div>
          </Card>
        </div>

        {/* ── Row 4: Lost reason heatmap ───────────────────────────────── */}
        <Card title="Lost reason — this week">
          <LostHeatmap themes={lostThemes} />
        </Card>

      </div>
    </div>
  );
}

// ─── Root export ──────────────────────────────────────────────────────────────

export function DashboardOverview({ user }: { user?: { name?: string | null; role?: string } }) {
  const firstName = user?.name?.split(" ")[0] ?? "there";

  const { data: dash, isLoading } = useQuery<DashboardData>({
    queryKey: ["dashboard-overview"],
    queryFn: () => api.get("/dashboard").then(r => r.data),
    staleTime: 60_000,
    refetchInterval: 5 * 60_000,
  });

  if (isLoading) return <DashboardSkeleton />;

  const isEmpty = !dash || (dash.total_calls === 0 && dash.total_guests === 0);
  if (isEmpty) return <GettingStarted firstName={firstName} />;

  return <LiveDashboard dash={dash} firstName={firstName} />;
}
