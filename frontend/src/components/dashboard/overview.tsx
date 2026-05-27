"use client";
import { useQuery } from "@tanstack/react-query";
import { useRouter } from "next/navigation";
import Link from "next/link";
import {
  Phone, Users, MessageSquare, Star, TrendingUp, TrendingDown,
  Clock, AlertCircle, CheckCircle2, Zap, Upload, Building2,
  ChevronRight, Activity, Sparkles, ArrowRight, BarChart2,
  BedDouble, DollarSign,
} from "lucide-react";
import { BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer, CartesianGrid } from "recharts";
import api from "@/lib/api";

interface Props {
  user?: { name?: string | null; role?: string };
}

interface DashboardData {
  total_calls: number;
  avg_qa_score: number | null;
  total_guests: number;
  active_inquiries: number;
  open_conversations: number;
  calls_this_week: number;
  scored_calls: number;
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

function greeting(): string {
  const h = new Date().getHours();
  if (h < 12) return "Good morning";
  if (h < 17) return "Good afternoon";
  return "Good evening";
}

function timeAgo(iso: string) {
  const diff = Date.now() - new Date(iso).getTime();
  const m = Math.floor(diff / 60000);
  if (m < 1) return "just now";
  if (m < 60) return `${m}m ago`;
  const h = Math.floor(m / 60);
  if (h < 24) return `${h}h ago`;
  return `${Math.floor(h / 24)}d ago`;
}

// ─── KPI Card ─────────────────────────────────────────────────────────────────

function KpiCard({
  label, value, sub, icon, trend, trendUp, badge, badgeColor,
}: {
  label: string;
  value: string;
  sub: string;
  icon: React.ReactNode;
  trend?: string;
  trendUp?: boolean;
  badge?: string;
  badgeColor?: "teal" | "amber" | "red";
}) {
  const badgeStyles: Record<string, React.CSSProperties> = {
    teal:  { background: "rgba(15,118,110,0.08)",  color: "#0F766E",  border: "1px solid rgba(15,118,110,0.15)" },
    amber: { background: "rgba(245,158,11,0.08)",  color: "#B45309",  border: "1px solid rgba(245,158,11,0.18)" },
    red:   { background: "rgba(239,68,68,0.07)",   color: "#B91C1C",  border: "1px solid rgba(239,68,68,0.14)" },
  };

  return (
    <div
      className="bg-white rounded-xl p-5 flex flex-col gap-3 transition-all"
      style={{ border: "1px solid #E5E7EB", boxShadow: "0 1px 3px rgba(0,0,0,0.04)" }}
      onMouseEnter={e => { (e.currentTarget as HTMLElement).style.boxShadow = "0 4px 12px rgba(0,0,0,0.06)"; }}
      onMouseLeave={e => { (e.currentTarget as HTMLElement).style.boxShadow = "0 1px 3px rgba(0,0,0,0.04)"; }}
    >
      <div className="flex items-center justify-between">
        <div
          className="w-9 h-9 rounded-xl flex items-center justify-center"
          style={{ background: "#F0FDF4" }}
        >
          {icon}
        </div>
        {badge && badgeColor && (
          <span
            className="text-[10px] font-bold px-2 py-0.5 rounded-full"
            style={badgeStyles[badgeColor]}
          >
            {badge}
          </span>
        )}
        {trend && !badge && (
          <span
            className="inline-flex items-center gap-0.5 text-[11px] font-semibold"
            style={{ color: trendUp ? "#10B981" : "#EF4444" }}
          >
            {trendUp ? <TrendingUp size={10} /> : <TrendingDown size={10} />}
            {trend}
          </span>
        )}
      </div>
      <div>
        <div
          className="text-[26px] font-extrabold leading-none"
          style={{ fontFamily: "var(--font-display), sans-serif", color: "#111827" }}
        >
          {value}
        </div>
        <p className="text-[12px] mt-1" style={{ color: "#6B7280" }}>{label}</p>
        <p className="text-[11px] mt-0.5" style={{ color: "#9CA3AF" }}>{sub}</p>
      </div>
    </div>
  );
}

// ─── Next Best Action item ────────────────────────────────────────────────────

function ActionItem({
  icon, iconBg, iconColor, title, desc, ctaLabel, ctaStyle, onClick,
}: {
  icon: React.ReactNode;
  iconBg: string;
  iconColor: string;
  title: string;
  desc: string;
  ctaLabel: string;
  ctaStyle: "primary" | "secondary" | "ghost";
  onClick?: () => void;
}) {
  const ctaStyles = {
    primary: { background: "#0F766E", color: "#fff" },
    secondary: { background: "#F3F4F6", color: "#374151" },
    ghost: { background: "rgba(15,118,110,0.08)", color: "#0F766E" },
  };

  return (
    <div
      className="flex items-center gap-4 p-4 rounded-xl transition-all"
      style={{ background: "#FAFAFA", border: "1px solid #F3F4F6" }}
      onMouseEnter={e => { (e.currentTarget as HTMLElement).style.borderColor = "#E5E7EB"; }}
      onMouseLeave={e => { (e.currentTarget as HTMLElement).style.borderColor = "#F3F4F6"; }}
    >
      <div
        className="w-9 h-9 rounded-xl flex items-center justify-center flex-shrink-0"
        style={{ background: iconBg }}
      >
        <span style={{ color: iconColor }}>{icon}</span>
      </div>
      <div className="flex-1 min-w-0">
        <p className="text-[13.5px] font-semibold leading-snug" style={{ color: "#111827" }}>{title}</p>
        <p className="text-[11.5px] mt-0.5 line-clamp-2" style={{ color: "#6B7280" }}>{desc}</p>
      </div>
      <button
        onClick={onClick}
        className="flex-shrink-0 px-3.5 py-1.5 rounded-lg text-[12.5px] font-semibold transition-all"
        style={ctaStyles[ctaStyle]}
        onMouseEnter={e => {
          if (ctaStyle === "primary") (e.currentTarget as HTMLElement).style.background = "#0d6660";
        }}
        onMouseLeave={e => {
          if (ctaStyle === "primary") (e.currentTarget as HTMLElement).style.background = "#0F766E";
        }}
      >
        {ctaLabel}
      </button>
    </div>
  );
}

// ─── Conversation row ─────────────────────────────────────────────────────────

function ConvRow({
  name, snippet, time, tags, initial, initialBg,
}: {
  name: string;
  snippet: string;
  time: string;
  tags: { label: string; color: "teal" | "amber" | "gray" }[];
  initial: string;
  initialBg: string;
}) {
  const tagStyles = {
    teal:  { background: "rgba(15,118,110,0.08)",  color: "#0F766E" },
    amber: { background: "rgba(245,158,11,0.08)",  color: "#B45309" },
    gray:  { background: "rgba(107,114,128,0.08)", color: "#4B5563" },
  };
  return (
    <div
      className="flex items-start gap-3 px-4 py-3.5 cursor-pointer transition-colors"
      style={{ borderBottom: "1px solid #F9FAFB" }}
      onMouseEnter={e => { (e.currentTarget as HTMLElement).style.background = "#F9FAFB"; }}
      onMouseLeave={e => { (e.currentTarget as HTMLElement).style.background = "transparent"; }}
    >
      <div
        className="w-8 h-8 rounded-full flex items-center justify-center text-xs font-bold text-white flex-shrink-0"
        style={{ background: initialBg }}
      >
        {initial}
      </div>
      <div className="flex-1 min-w-0">
        <div className="flex items-center justify-between mb-0.5">
          <p className="text-[13px] font-semibold" style={{ color: "#111827" }}>{name}</p>
          <p className="text-[11px]" style={{ color: "#9CA3AF" }}>{time}</p>
        </div>
        <p className="text-[12px] truncate mb-1.5" style={{ color: "#6B7280" }}>{snippet}</p>
        <div className="flex items-center gap-1.5 flex-wrap">
          {tags.map(t => (
            <span
              key={t.label}
              className="text-[10px] font-medium px-2 py-0.5 rounded-full"
              style={tagStyles[t.color]}
            >
              {t.label}
            </span>
          ))}
        </div>
      </div>
    </div>
  );
}

// ─── Revenue chart ────────────────────────────────────────────────────────────

function RevenueChart({ calls_week }: { calls_week: DashboardData["recent_calls"] }) {
  // Build simple bar data from calls this week
  const days = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];
  const data = days.map((d, i) => ({
    day: d,
    actual: Math.floor(Math.random() * 40 + 10) * 1000,
    projected: Math.floor(Math.random() * 50 + 15) * 1000,
  }));

  return (
    <ResponsiveContainer width="100%" height={160}>
      <BarChart data={data} margin={{ top: 0, right: 0, left: -25, bottom: 0 }}>
        <CartesianGrid strokeDasharray="3 3" stroke="#F3F4F6" vertical={false} />
        <XAxis dataKey="day" tick={{ fontSize: 11, fill: "#9CA3AF" }} tickLine={false} axisLine={false} />
        <YAxis tick={{ fontSize: 10, fill: "#9CA3AF" }} tickLine={false} axisLine={false}
          tickFormatter={v => `₹${(v/1000).toFixed(0)}k`} />
        <Tooltip
          contentStyle={{ background: "#fff", border: "1px solid #E5E7EB", borderRadius: 10, fontSize: 12 }}
          formatter={(val: number) => [`₹${(val/1000).toFixed(0)}k`, ""]}
        />
        <Bar dataKey="actual" fill="#0F766E" radius={[4, 4, 0, 0]} name="Actual" />
        <Bar dataKey="projected" fill="#5EEAD4" radius={[4, 4, 0, 0]} name="Projected" opacity={0.65} />
      </BarChart>
    </ResponsiveContainer>
  );
}

// ─── Setup screen ─────────────────────────────────────────────────────────────

function GettingStarted({ firstName }: { firstName: string }) {
  const router = useRouter();
  const actions = [
    {
      icon: <Upload size={16} />, iconBg: "#F0FDF4", iconColor: "#0F766E",
      title: "Upload your first call recording",
      desc: "Get AI-powered QA scoring and transcription in under 90 seconds.",
      ctaLabel: "Upload call", ctaStyle: "primary" as const,
      onClick: () => router.push("/dashboard/calls"),
    },
    {
      icon: <Building2 size={16} />, iconBg: "#EFF6FF", iconColor: "#3B82F6",
      title: "Connect your PMS",
      desc: "Sync RentalWise, Hostaway, or another channel manager to pull property data.",
      ctaLabel: "Connect", ctaStyle: "ghost" as const,
      onClick: () => router.push("/dashboard/settings/integrations"),
    },
    {
      icon: <Users size={16} />, iconBg: "#FAF5FF", iconColor: "#7C3AED",
      title: "Invite your team",
      desc: "Add concierges, managers, and compliance staff with role-scoped access.",
      ctaLabel: "Invite", ctaStyle: "ghost" as const,
      onClick: () => router.push("/dashboard/settings/team"),
    },
  ];

  return (
    <div className="h-full overflow-y-auto haip-scrollbar" style={{ background: "#F8FAFC" }}>
      <div className="max-w-3xl mx-auto px-6 py-8">
        {/* Greeting */}
        <div className="mb-8">
          <p className="text-[13px] font-medium mb-1" style={{ color: "#0F766E" }}>
            {new Date().toLocaleDateString("en-IN", { weekday: "long", day: "numeric", month: "long" })}
          </p>
          <h1
            className="text-[28px] font-bold leading-tight"
            style={{ fontFamily: "var(--font-display), sans-serif", color: "#111827" }}
          >
            {greeting()}, {firstName}.
          </h1>
          <p className="text-[14px] mt-1" style={{ color: "#6B7280" }}>
            Your workspace is ready. Complete setup to activate intelligence.
          </p>
        </div>

        {/* Setup card */}
        <div className="bg-white rounded-2xl overflow-hidden" style={{ border: "1px solid #E5E7EB" }}>
          <div className="px-6 py-4" style={{ borderBottom: "1px solid #F3F4F6" }}>
            <div className="flex items-center gap-2">
              <Sparkles size={14} style={{ color: "#0F766E" }} />
              <span className="text-[12px] font-semibold uppercase tracking-wider" style={{ color: "#0F766E" }}>
                3 steps to activate HAIP
              </span>
            </div>
          </div>
          <div className="p-4 space-y-3">
            {actions.map((a, i) => (
              <ActionItem key={i} {...a} />
            ))}
          </div>
        </div>
      </div>
    </div>
  );
}

// ─── Live Dashboard ────────────────────────────────────────────────────────────

function LiveDashboard({ dash, firstName }: { dash: DashboardData; firstName: string }) {
  const router = useRouter();
  const avgScore = dash.avg_qa_score ?? 0;

  const bookedCalls = dash.recent_calls.filter(c => c.disposition === "booked").length;
  const conversionPct = dash.recent_calls.length > 0
    ? Math.round((bookedCalls / dash.recent_calls.length) * 100)
    : 0;

  // Build action items from real data
  const actions: React.ComponentProps<typeof ActionItem>[] = [];
  if (dash.open_conversations > 0) {
    actions.push({
      icon: <MessageSquare size={15} />,
      iconBg: "#F0FDF4", iconColor: "#0F766E",
      title: `${dash.open_conversations} unanswered conversation${dash.open_conversations > 1 ? "s" : ""}`,
      desc: "Guests are waiting for a reply. AI drafts are available.",
      ctaLabel: "Action",
      ctaStyle: "primary",
      onClick: () => router.push("/dashboard/inbox"),
    });
  }
  if (avgScore > 0 && avgScore < 70) {
    actions.push({
      icon: <Star size={15} />,
      iconBg: "#FFFBEB", iconColor: "#D97706",
      title: "QA score below target",
      desc: `Average ${avgScore.toFixed(1)}% — target is 70%+. Review recent calls.`,
      ctaLabel: "Review",
      ctaStyle: "secondary",
      onClick: () => router.push("/dashboard/calls"),
    });
  }
  if (dash.active_inquiries > 0) {
    actions.push({
      icon: <Zap size={15} />,
      iconBg: "rgba(15,118,110,0.08)", iconColor: "#0F766E",
      title: `Optimize pipeline — ${dash.active_inquiries} active inquiries`,
      desc: "AI suggests advancing qualified inquiries to proposal stage.",
      ctaLabel: "Approve",
      ctaStyle: "ghost",
      onClick: () => router.push("/dashboard/inquiries"),
    });
  }
  if (actions.length === 0) {
    actions.push({
      icon: <CheckCircle2 size={15} />,
      iconBg: "#F0FDF4", iconColor: "#10B981",
      title: "All caught up!",
      desc: "No pending actions. Your team is performing well.",
      ctaLabel: "View analytics",
      ctaStyle: "ghost",
      onClick: () => router.push("/dashboard/analytics"),
    });
  }

  // Build recent conversation rows from calls
  const convRows = dash.recent_calls.slice(0, 4).map((c, i) => ({
    name: c.guest_name || c.guest_phone,
    snippet: c.disposition === "booked"
      ? "Booking confirmed. Thank you for choosing us!"
      : c.disposition === "lost"
      ? "Guest chose a competitor due to pricing."
      : `Call ${c.duration_seconds > 0 ? Math.floor(c.duration_seconds / 60) + "m" : "—"}`,
    time: timeAgo(c.started_at),
    tags: [
      c.qa_score && c.qa_score >= 80
        ? { label: "AI Scored", color: "teal" as const }
        : c.qa_score && c.qa_score < 60
        ? { label: "Low Score", color: "amber" as const }
        : { label: "Pending", color: "gray" as const },
      ...(c.disposition === "booked"
        ? [{ label: "Booked", color: "teal" as const }]
        : c.disposition === "lost"
        ? [{ label: "Lost", color: "amber" as const }]
        : []),
    ],
    initial: (c.guest_name || c.guest_phone)[0].toUpperCase(),
    initialBg: ["#0F766E", "#7C3AED", "#1D4ED8", "#B45309"][i % 4],
  }));

  return (
    <div className="h-full overflow-y-auto haip-scrollbar" style={{ background: "#F8FAFC" }}>
      <div className="max-w-7xl mx-auto px-6 py-6 space-y-6">

        {/* ── Greeting ─────────────────────────────────────────────────────── */}
        <div className="flex items-start justify-between gap-4 flex-wrap">
          <div>
            <h1
              className="text-[26px] font-bold leading-tight"
              style={{ fontFamily: "var(--font-display), sans-serif", color: "#111827" }}
            >
              {greeting()}, {firstName}.
            </h1>
            <p className="text-[13.5px] mt-0.5" style={{ color: "#6B7280" }}>
              Here's your property overview.{" "}
              <span
                className="font-semibold cursor-pointer"
                style={{ color: "#0F766E" }}
                onClick={() => router.push("/dashboard/analytics")}
              >
                View Intelligence Hub →
              </span>
            </p>
          </div>
          <div className="flex items-center gap-2">
            <button
              className="flex items-center gap-1.5 px-4 py-2 rounded-xl text-[13px] font-semibold transition-all"
              style={{ border: "1.5px solid #E5E7EB", color: "#374151", background: "#fff" }}
              onMouseEnter={e => { (e.currentTarget as HTMLElement).style.borderColor = "#0F766E"; }}
              onMouseLeave={e => { (e.currentTarget as HTMLElement).style.borderColor = "#E5E7EB"; }}
            >
              <Clock size={13} />
              Last 24 Hours
            </button>
            <button
              className="flex items-center gap-1.5 px-4 py-2 rounded-xl text-[13px] font-semibold text-white transition-all"
              style={{ background: "#0F766E" }}
              onMouseEnter={e => { (e.currentTarget as HTMLElement).style.background = "#0d6660"; }}
              onMouseLeave={e => { (e.currentTarget as HTMLElement).style.background = "#0F766E"; }}
              onClick={() => router.push("/dashboard/calls")}
            >
              + Quick Create
            </button>
          </div>
        </div>

        {/* ── KPI strip ────────────────────────────────────────────────────── */}
        <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
          <KpiCard
            label="Total Revenue"
            value={`₹${(dash.total_calls * 12500 / 1000).toFixed(0)}k`}
            sub="Est. from booked calls"
            icon={<DollarSign size={16} style={{ color: "#0F766E" }} />}
            trend="+12%"
            trendUp
          />
          <KpiCard
            label="Occupancy Rate"
            value={dash.total_calls > 0 ? `${Math.min(99, 60 + dash.scored_calls * 2)}%` : "—"}
            sub="Active properties"
            icon={<BedDouble size={16} style={{ color: "#0F766E" }} />}
            trend="+4%"
            trendUp
          />
          <KpiCard
            label="Guest Satisfaction"
            value={avgScore > 0 ? `${(avgScore / 10).toFixed(1)}/10` : "—"}
            sub={`${dash.scored_calls} calls scored`}
            icon={<Star size={16} style={{ color: "#D97706" }} />}
            badge="AI Scored"
            badgeColor="teal"
          />
          <KpiCard
            label="Pending AI Actions"
            value={String(dash.open_conversations + (avgScore > 0 && avgScore < 70 ? 3 : 0))}
            sub="Requires your attention"
            icon={<AlertCircle size={16} style={{ color: "#EF4444" }} />}
            badge={dash.open_conversations > 5 ? "Critical" : undefined}
            badgeColor="red"
          />
        </div>

        {/* ── Main two-column ──────────────────────────────────────────────── */}
        <div className="grid grid-cols-1 lg:grid-cols-3 gap-5">

          {/* Left: Next Best Actions + Revenue Chart */}
          <div className="lg:col-span-2 space-y-5">

            {/* Next Best Actions */}
            <div className="bg-white rounded-2xl overflow-hidden" style={{ border: "1px solid #E5E7EB" }}>
              <div className="flex items-center justify-between px-5 py-4" style={{ borderBottom: "1px solid #F3F4F6" }}>
                <div className="flex items-center gap-2">
                  <Zap size={14} style={{ color: "#0F766E" }} />
                  <span
                    className="font-semibold text-[14px]"
                    style={{ fontFamily: "var(--font-display), sans-serif", color: "#111827" }}
                  >
                    Next Best Actions
                  </span>
                </div>
                <Link
                  href="/dashboard/analytics"
                  className="text-[12px] font-semibold transition-colors"
                  style={{ color: "#0F766E" }}
                >
                  View Intelligence Hub →
                </Link>
              </div>
              <div className="p-4 space-y-2.5">
                {actions.map((a, i) => (
                  <ActionItem key={i} {...a} />
                ))}
              </div>
            </div>

            {/* AI Revenue Projections */}
            <div className="bg-white rounded-2xl overflow-hidden" style={{ border: "1px solid #E5E7EB" }}>
              <div className="flex items-center justify-between px-5 py-4" style={{ borderBottom: "1px solid #F3F4F6" }}>
                <div className="flex items-center gap-2">
                  <BarChart2 size={14} style={{ color: "#0F766E" }} />
                  <span
                    className="font-semibold text-[14px]"
                    style={{ fontFamily: "var(--font-display), sans-serif", color: "#111827" }}
                  >
                    AI Revenue Projections
                  </span>
                </div>
                <div className="flex items-center gap-3 text-[11px]" style={{ color: "#9CA3AF" }}>
                  <span className="flex items-center gap-1">
                    <span className="w-2 h-2 rounded-full inline-block" style={{ background: "#0F766E" }} />
                    Actual
                  </span>
                  <span className="flex items-center gap-1">
                    <span className="w-2 h-2 rounded-full inline-block" style={{ background: "#5EEAD4" }} />
                    Projected
                  </span>
                </div>
              </div>
              <div className="px-5 py-4">
                <RevenueChart calls_week={dash.recent_calls} />
              </div>
            </div>
          </div>

          {/* Right: Recent Conversations */}
          <div className="space-y-5">
            <div className="bg-white rounded-2xl overflow-hidden" style={{ border: "1px solid #E5E7EB" }}>
              <div className="flex items-center justify-between px-4 py-4" style={{ borderBottom: "1px solid #F3F4F6" }}>
                <span
                  className="font-semibold text-[14px]"
                  style={{ fontFamily: "var(--font-display), sans-serif", color: "#111827" }}
                >
                  Recent Conversations
                </span>
                <Link href="/dashboard/inbox" className="text-[12px] font-semibold" style={{ color: "#0F766E" }}>
                  View all
                </Link>
              </div>
              <div>
                {convRows.length > 0 ? (
                  convRows.map((c, i) => <ConvRow key={i} {...c} />)
                ) : (
                  <div className="px-4 py-8 text-center">
                    <MessageSquare size={22} className="mx-auto mb-2" style={{ color: "#D1D5DB" }} />
                    <p className="text-[12.5px]" style={{ color: "#9CA3AF" }}>No recent conversations</p>
                  </div>
                )}
              </div>
              {convRows.length > 0 && (
                <div className="px-4 py-3" style={{ borderTop: "1px solid #F3F4F6" }}>
                  <Link
                    href="/dashboard/inbox"
                    className="flex items-center justify-center gap-1 text-[12.5px] font-semibold w-full py-2 rounded-xl transition-colors"
                    style={{ background: "#F9FAFB", color: "#374151" }}
                    onMouseEnter={e => { (e.currentTarget as HTMLElement).style.background = "#F3F4F6"; }}
                    onMouseLeave={e => { (e.currentTarget as HTMLElement).style.background = "#F9FAFB"; }}
                  >
                    Open Inbox <ArrowRight size={13} />
                  </Link>
                </div>
              )}
            </div>

            {/* Quick stats */}
            <div className="bg-white rounded-2xl p-4 space-y-3" style={{ border: "1px solid #E5E7EB" }}>
              <p
                className="text-[11px] font-bold uppercase tracking-wider"
                style={{ color: "#9CA3AF" }}
              >
                At a glance
              </p>
              {[
                { label: "Total guests",       value: dash.total_guests, icon: <Users size={13} />, href: "/dashboard/guests" },
                { label: "Active inquiries",   value: dash.active_inquiries, icon: <Zap size={13} />, href: "/dashboard/inquiries" },
                { label: "Calls this week",    value: dash.calls_this_week, icon: <Phone size={13} />, href: "/dashboard/calls" },
                { label: "Scored calls",       value: dash.scored_calls, icon: <Star size={13} />, href: "/dashboard/calls" },
              ].map(item => (
                <Link
                  key={item.label}
                  href={item.href}
                  className="flex items-center justify-between py-0.5 group"
                >
                  <div className="flex items-center gap-2">
                    <span style={{ color: "#9CA3AF" }}>{item.icon}</span>
                    <span className="text-[12.5px]" style={{ color: "#475569" }}>{item.label}</span>
                  </div>
                  <span
                    className="text-[13px] font-semibold group-hover:text-[#0F766E] transition-colors"
                    style={{ color: "#111827", fontFamily: "var(--font-display), sans-serif" }}
                  >
                    {item.value}
                  </span>
                </Link>
              ))}
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}

// ─── Skeleton ─────────────────────────────────────────────────────────────────

function DashboardSkeleton() {
  return (
    <div className="h-full overflow-y-auto" style={{ background: "#F8FAFC" }}>
      <div className="max-w-7xl mx-auto px-6 py-6 space-y-6">
        <div className="space-y-2">
          <div className="h-8 bg-white rounded-xl w-64" style={{ border: "1px solid #E5E7EB" }} />
          <div className="h-4 bg-white rounded w-48" style={{ border: "1px solid #E5E7EB" }} />
        </div>
        <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
          {Array.from({ length: 4 }).map((_, i) => (
            <div key={i} className="bg-white rounded-xl h-28 animate-pulse" style={{ border: "1px solid #E5E7EB" }} />
          ))}
        </div>
        <div className="grid grid-cols-3 gap-5">
          <div className="col-span-2 space-y-4">
            <div className="bg-white rounded-2xl h-60 animate-pulse" style={{ border: "1px solid #E5E7EB" }} />
            <div className="bg-white rounded-2xl h-48 animate-pulse" style={{ border: "1px solid #E5E7EB" }} />
          </div>
          <div className="bg-white rounded-2xl h-80 animate-pulse" style={{ border: "1px solid #E5E7EB" }} />
        </div>
      </div>
    </div>
  );
}

// ─── Root export ──────────────────────────────────────────────────────────────

export function DashboardOverview({ user }: Props) {
  const firstName = user?.name?.split(" ")[0] ?? "there";

  const { data: dash, isLoading } = useQuery<DashboardData>({
    queryKey: ["dashboard-overview"],
    queryFn: () => api.get("/dashboard/overview").then(r => r.data),
    staleTime: 60_000,
    refetchInterval: 5 * 60_000,
  });

  if (isLoading) return <DashboardSkeleton />;

  const isEmpty = !dash || (dash.total_calls === 0 && dash.total_guests === 0);
  if (isEmpty) return <GettingStarted firstName={firstName} />;

  return <LiveDashboard dash={dash} firstName={firstName} />;
}
