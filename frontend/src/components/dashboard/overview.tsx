"use client";
import { useQuery } from "@tanstack/react-query";
import { useRouter } from "next/navigation";
import { Upload, Phone, Users, TrendingUp, MessageSquare, Star, ArrowRight, Zap } from "lucide-react";
import api from "@/lib/api";
import { ScoreRing } from "@/components/calls/ScoreRing";

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

// ─── Empty / getting-started screen ───────────────────────────────────────────

function GettingStarted({ firstName }: { firstName: string }) {
  const router = useRouter();
  const today = new Date().toLocaleDateString("en-IN", {
    weekday: "long", day: "numeric", month: "long", year: "numeric",
  });

  const steps = [
    {
      icon: <Upload size={20} className="text-teal-500" />,
      title: "Upload your first call",
      desc: "Drop an MP3/WAV recording and get an AI-powered QA score in under 90 seconds.",
      action: () => router.push("/dashboard/calls"),
      cta: "Upload a recording →",
      done: false,
    },
    {
      icon: <Users size={20} className="text-blue-500" />,
      title: "Invite your team",
      desc: "Add concierges, managers, or compliance staff — each gets role-scoped access.",
      action: () => router.push("/dashboard/settings/team"),
      cta: "Go to Team settings →",
      done: false,
    },
    {
      icon: <Phone size={20} className="text-purple-500" />,
      title: "Connect your IVR",
      desc: "Link CallerDesk or Acefone so live calls auto-flow into the pipeline.",
      action: () => router.push("/dashboard/settings/integrations"),
      cta: "Set up integration →",
      done: false,
    },
  ];

  return (
    <div className="p-6 max-w-[900px] mx-auto space-y-6">
      {/* Header */}
      <div>
        <h1 className="text-[22px] font-bold text-gray-900">Good morning, {firstName} 👋</h1>
        <p className="text-[13px] text-gray-400 mt-0.5">{today}</p>
      </div>

      {/* Welcome banner */}
      <div className="bg-gradient-to-br from-[#0B1F3A] to-[#163458] rounded-2xl p-6 text-white relative overflow-hidden">
        <div className="absolute top-0 right-0 w-48 h-48 bg-teal-500/10 rounded-full -translate-y-1/2 translate-x-1/4" />
        <div className="relative">
          <div className="flex items-center gap-2 mb-2">
            <Zap size={18} className="text-teal-400" />
            <span className="text-xs font-bold uppercase tracking-widest text-teal-400">Your workspace is ready</span>
          </div>
          <h2 className="text-xl font-bold mb-1">Welcome to HAIP</h2>
          <p className="text-sm text-white/70 max-w-lg">
            Every call becomes structured intelligence. Upload your first recording to see QA scoring, transcription, and AI insights in action.
          </p>
          <button
            onClick={() => router.push("/dashboard/calls")}
            className="mt-4 flex items-center gap-2 bg-teal-500 hover:bg-teal-400 text-white text-sm font-semibold px-4 py-2.5 rounded-xl transition-colors"
          >
            <Upload size={15} /> Upload first recording
          </button>
        </div>
      </div>

      {/* Setup checklist */}
      <div>
        <h2 className="text-sm font-bold text-gray-900 mb-3">Get started — 3 steps</h2>
        <div className="grid gap-3">
          {steps.map((step, i) => (
            <button
              key={i}
              onClick={step.action}
              className="text-left bg-white border border-gray-100 rounded-2xl p-5 hover:shadow-sm hover:border-gray-200 transition-all group"
            >
              <div className="flex items-start gap-4">
                <div className="w-10 h-10 rounded-xl bg-gray-50 flex items-center justify-center flex-shrink-0 group-hover:bg-gray-100 transition-colors">
                  {step.icon}
                </div>
                <div className="flex-1 min-w-0">
                  <div className="flex items-center justify-between gap-2">
                    <p className="text-sm font-semibold text-gray-900">{step.title}</p>
                    <ArrowRight size={14} className="text-gray-300 group-hover:text-gray-500 transition-colors flex-shrink-0" />
                  </div>
                  <p className="text-xs text-gray-500 mt-0.5 leading-relaxed">{step.desc}</p>
                  <p className="text-xs text-teal-600 font-medium mt-2">{step.cta}</p>
                </div>
              </div>
            </button>
          ))}
        </div>
      </div>
    </div>
  );
}

// ─── Live dashboard (when data exists) ────────────────────────────────────────

function LiveDashboard({ dash, firstName }: { dash: DashboardData; firstName: string }) {
  const router = useRouter();
  const today = new Date().toLocaleDateString("en-IN", {
    weekday: "long", day: "numeric", month: "long", year: "numeric",
  });

  const avgScore = dash.avg_qa_score ?? 0;

  function timeAgo(iso: string) {
    const diff = Date.now() - new Date(iso).getTime();
    const m = Math.floor(diff / 60000);
    if (m < 1) return "just now";
    if (m < 60) return `${m}m ago`;
    const h = Math.floor(m / 60);
    if (h < 24) return `${h}h ago`;
    return `${Math.floor(h / 24)}d ago`;
  }

  function formatDur(s: number) {
    return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}`;
  }

  const DISP_COLOR: Record<string, string> = {
    booked:    "bg-teal-50 text-teal-700",
    qualified: "bg-blue-50 text-blue-700",
    lost:      "bg-red-50 text-red-600",
    callback:  "bg-amber-50 text-amber-700",
    pending:   "bg-gray-50 text-gray-500",
    no_answer: "bg-gray-50 text-gray-400",
  };

  return (
    <div className="p-6 max-w-[1280px] mx-auto space-y-5">
      {/* Header */}
      <div className="flex items-start justify-between flex-wrap gap-3">
        <div>
          <h1 className="text-[22px] font-bold text-gray-900">Good morning, {firstName}</h1>
          <p className="text-[13px] text-gray-400 mt-0.5">{today}</p>
        </div>
        <button
          onClick={() => router.push("/dashboard/calls")}
          className="flex items-center gap-2 bg-[#0B1F3A] text-white text-xs font-semibold px-4 py-2 rounded-xl hover:bg-[#163458] transition-colors"
        >
          <Upload size={13} /> Upload call
        </button>
      </div>

      {/* KPI cards */}
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
        {[
          {
            label: "Total Calls",
            value: dash.total_calls.toLocaleString(),
            sub: `${dash.calls_this_week} this week`,
            bar: "bg-teal-500",
            icon: <Phone size={16} className="text-teal-500" />,
          },
          {
            label: "Avg QA Score",
            value: avgScore > 0 ? `${avgScore.toFixed(1)}%` : "—",
            sub: `${dash.scored_calls} calls scored`,
            bar: avgScore >= 80 ? "bg-teal-500" : avgScore >= 60 ? "bg-amber-400" : "bg-red-400",
            icon: <Star size={16} className="text-amber-500" />,
          },
          {
            label: "Total Guests",
            value: dash.total_guests.toLocaleString(),
            sub: `${dash.active_inquiries} active inquiries`,
            bar: "bg-blue-500",
            icon: <Users size={16} className="text-blue-500" />,
          },
          {
            label: "Open Conversations",
            value: dash.open_conversations.toLocaleString(),
            sub: "Across all channels",
            bar: "bg-purple-500",
            icon: <MessageSquare size={16} className="text-purple-500" />,
          },
        ].map((kpi) => (
          <div key={kpi.label} className="bg-white border border-gray-200 rounded-xl p-4 shadow-sm relative overflow-hidden">
            <div className={`absolute top-0 left-0 right-0 h-[3px] ${kpi.bar}`} />
            <div className="flex items-center justify-between mb-2">
              <span className="text-[11px] uppercase tracking-wider text-gray-500 font-semibold">{kpi.label}</span>
              {kpi.icon}
            </div>
            <div className="text-[26px] font-bold text-gray-900 leading-none">{kpi.value}</div>
            <div className="text-xs text-gray-400 mt-1">{kpi.sub}</div>
          </div>
        ))}
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
        {/* Recent calls */}
        <div className="lg:col-span-2 bg-white border border-gray-200 rounded-xl shadow-sm overflow-hidden">
          <div className="px-5 py-3.5 border-b border-gray-100 flex items-center justify-between">
            <div className="flex items-center gap-2">
              <span className="w-[3px] h-[14px] rounded-full bg-teal-500 inline-block" />
              <span className="text-[13.5px] font-bold text-gray-900">Recent Calls</span>
            </div>
            <button
              onClick={() => router.push("/dashboard/calls")}
              className="text-xs text-teal-600 font-medium hover:underline flex items-center gap-1"
            >
              View all <ArrowRight size={11} />
            </button>
          </div>
          <div className="divide-y divide-gray-50">
            {dash.recent_calls.length === 0 ? (
              <div className="py-12 text-center">
                <Phone size={28} className="text-gray-200 mx-auto mb-2" />
                <p className="text-sm text-gray-400">No calls yet — upload a recording to get started.</p>
                <button
                  onClick={() => router.push("/dashboard/calls")}
                  className="mt-3 text-xs text-teal-600 font-medium hover:underline"
                >
                  Upload first call →
                </button>
              </div>
            ) : (
              dash.recent_calls.slice(0, 8).map(call => (
                <button
                  key={call.id}
                  onClick={() => router.push(`/dashboard/calls/${call.id}`)}
                  className="w-full text-left px-5 py-3 hover:bg-gray-50 transition-colors group flex items-center gap-3"
                >
                  {call.qa_score != null ? (
                    <ScoreRing score={call.qa_score} size={38} strokeWidth={4} className="flex-shrink-0" />
                  ) : (
                    <div className="w-[38px] h-[38px] rounded-full bg-blue-50 flex items-center justify-center flex-shrink-0">
                      <Phone size={14} className="text-blue-400" />
                    </div>
                  )}
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center justify-between gap-2">
                      <span className="text-sm font-semibold text-gray-800 truncate">
                        {call.guest_name || call.guest_phone}
                      </span>
                      <span className="text-[11px] text-gray-400 flex-shrink-0">{timeAgo(call.started_at)}</span>
                    </div>
                    <div className="flex items-center gap-2 mt-0.5">
                      {call.duration_seconds > 0 && (
                        <span className="text-xs text-gray-400">{formatDur(call.duration_seconds)}</span>
                      )}
                      <span className={`text-[10px] font-semibold px-2 py-0.5 rounded-full capitalize ${DISP_COLOR[call.disposition] ?? "bg-gray-50 text-gray-500"}`}>
                        {call.disposition.replace("_", " ")}
                      </span>
                    </div>
                  </div>
                  <ArrowRight size={13} className="text-gray-200 group-hover:text-gray-400 flex-shrink-0" />
                </button>
              ))
            )}
          </div>
        </div>

        {/* QA overview */}
        <div className="bg-white border border-gray-200 rounded-xl shadow-sm overflow-hidden">
          <div className="px-5 py-3.5 border-b border-gray-100 flex items-center gap-2">
            <span className="w-[3px] h-[14px] rounded-full bg-teal-500 inline-block" />
            <span className="text-[13.5px] font-bold text-gray-900">QA Overview</span>
          </div>
          <div className="p-5 flex flex-col items-center gap-5">
            {avgScore > 0 ? (
              <>
                <ScoreRing score={avgScore} size={100} strokeWidth={9} />
                <div className="text-center">
                  <p className="text-sm font-semibold text-gray-700">Average QA Score</p>
                  <p className="text-xs text-gray-400 mt-0.5">{dash.scored_calls} calls scored</p>
                </div>
                <div className="w-full space-y-2.5">
                  {[
                    { label: "Excellent (80–100%)", pct: Math.round(dash.recent_calls.filter(c => (c.qa_score ?? 0) >= 80).length / Math.max(dash.scored_calls, 1) * 100), color: "bg-teal-500" },
                    { label: "Good (60–79%)",       pct: Math.round(dash.recent_calls.filter(c => (c.qa_score ?? 0) >= 60 && (c.qa_score ?? 0) < 80).length / Math.max(dash.scored_calls, 1) * 100), color: "bg-amber-400" },
                    { label: "Needs work (<60%)",   pct: Math.round(dash.recent_calls.filter(c => (c.qa_score ?? 0) < 60 && c.qa_score != null).length / Math.max(dash.scored_calls, 1) * 100), color: "bg-red-400" },
                  ].map(b => (
                    <div key={b.label}>
                      <div className="flex justify-between text-[11px] text-gray-500 mb-1">
                        <span>{b.label}</span><span>{b.pct}%</span>
                      </div>
                      <div className="h-1.5 bg-gray-100 rounded-full">
                        <div className={`h-1.5 rounded-full ${b.color}`} style={{ width: `${b.pct}%` }} />
                      </div>
                    </div>
                  ))}
                </div>
              </>
            ) : (
              <div className="py-8 text-center">
                <TrendingUp size={32} className="text-gray-200 mx-auto mb-3" />
                <p className="text-sm font-semibold text-gray-600">No scored calls yet</p>
                <p className="text-xs text-gray-400 mt-1 leading-relaxed">
                  Upload a call recording and run QA analysis to see your team's performance here.
                </p>
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}

// ─── Main component ────────────────────────────────────────────────────────────

export function DashboardOverview({ user }: Props) {
  const { data: dash, isLoading } = useQuery<DashboardData>({
    queryKey: ["dashboard"],
    queryFn: () => api.get("/dashboard").then(r => r.data),
    staleTime: 60_000,
    retry: 1,
  });

  const firstName = user?.name?.split(" ")[0] ?? "there";
  const isEmpty = !isLoading && (!dash || dash.total_calls === 0);

  if (isLoading) {
    return (
      <div className="p-6 max-w-[1280px] mx-auto space-y-5">
        <div className="animate-pulse space-y-4">
          <div className="h-8 bg-gray-100 rounded-xl w-48" />
          <div className="grid grid-cols-4 gap-3">
            {[...Array(4)].map((_, i) => <div key={i} className="h-24 bg-gray-100 rounded-xl" />)}
          </div>
          <div className="grid grid-cols-3 gap-4">
            <div className="col-span-2 h-64 bg-gray-100 rounded-xl" />
            <div className="h-64 bg-gray-100 rounded-xl" />
          </div>
        </div>
      </div>
    );
  }

  if (isEmpty) {
    return <GettingStarted firstName={firstName} />;
  }

  return <LiveDashboard dash={dash!} firstName={firstName} />;
}
