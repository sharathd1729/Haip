"use client";
import { useState } from "react";
import { useParams, useRouter } from "next/navigation";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import {
  ArrowLeft, Sparkles, Phone, MessageSquare, Instagram,
  Building2, Clock, RefreshCw, Plus, User, Globe,
  Shield, ChevronDown, ExternalLink,
} from "lucide-react";
import api from "@/lib/api";
import { timeAgo, cn } from "@/lib/utils";
import { Skeleton } from "@/components/ui/skeleton";
import { SignalDrawer } from "@/components/leads/SignalDrawer";
import { useToast } from "@/components/ui/toast";
import { useSession } from "next-auth/react";

// ─── Types ────────────────────────────────────────────────────────────────────

interface TimelineEntry {
  id: string;
  channel: string;
  direction: string;
  occurred_at: string;
  content_preview: string;
  is_ai_generated?: boolean;
  call_summary?: string;
}

interface QuoteHistory {
  id: string;
  amount: number;
  currency: string;
  created_at?: string;
  is_active?: boolean;
  age_days?: number;
}

// ─── Channel icon ─────────────────────────────────────────────────────────────

function ChannelIcon({ channel }: { channel: string }) {
  const c = channel.toLowerCase();
  if (c === "instagram") return <Instagram size={12} className="text-pink-500" />;
  if (c === "whatsapp") return <MessageSquare size={12} className="text-green-500" />;
  if (c === "call") return <Phone size={12} className="text-blue-500" />;
  if (c === "system") return <Shield size={12} className="text-gray-400" />;
  if (c === "web") return <Globe size={12} className="text-gray-400" />;
  return <MessageSquare size={12} className="text-gray-400" />;
}

// ─── Completeness bar ─────────────────────────────────────────────────────────

function CompletenessBar({ pct }: { pct: number }) {
  const color = pct >= 80 ? "#10B981" : pct >= 50 ? "#F59E0B" : "#6B7280";
  return (
    <div className="space-y-1">
      <div className="flex justify-between text-[10px]">
        <span className="text-gray-500">Profile completeness</span>
        <span className="font-medium" style={{ color }}>{pct}%</span>
      </div>
      <div className="h-1.5 rounded-full bg-gray-100">
        <div className="h-1.5 rounded-full transition-all" style={{ width: `${pct}%`, background: color }} />
      </div>
    </div>
  );
}

// ─── SIGNAL type role check ───────────────────────────────────────────────────

const SIGNAL_ROLES = new Set(["owner", "manager", "reservations"]);
const MERGE_ROLES = new Set(["owner", "manager"]);

// ─── Page ─────────────────────────────────────────────────────────────────────

export default function LeadDetailPage() {
  const { inquiryId } = useParams<{ inquiryId: string }>();
  const router = useRouter();
  const { data: session } = useSession();
  const role = (session?.user as any)?.role ?? "";
  const { toast } = useToast();
  const qc = useQueryClient();

  const [showSignalDrawer, setShowSignalDrawer] = useState(false);
  const [timelineExpanded, setTimelineExpanded] = useState(false);

  const { data, isLoading } = useQuery({
    queryKey: ["lead", inquiryId],
    queryFn: async () => {
      const res = await api.get(`/leads/${inquiryId}`);
      return res.data;
    },
  });

  const refreshMutation = useMutation({
    mutationFn: () => api.post(`/leads/${inquiryId}/refresh-summary`),
    onSuccess: () => {
      toast({ title: "Summary queued", description: "AI summary is being regenerated." });
      setTimeout(() => qc.invalidateQueries({ queryKey: ["lead", inquiryId] }), 5000);
    },
  });

  if (isLoading) {
    return (
      <div className="p-5 space-y-3">
        <Skeleton className="h-8 w-48" />
        <Skeleton className="h-32 w-full rounded-xl" />
        <Skeleton className="h-64 w-full rounded-xl" />
      </div>
    );
  }

  if (!data) {
    return (
      <div className="p-8 text-center text-gray-500">
        <p>Lead not found.</p>
        <button onClick={() => router.back()} className="mt-3 text-teal-600 text-sm">← Back</button>
      </div>
    );
  }

  const timelineItems: TimelineEntry[] = data.timeline ?? [];
  const visibleTimeline = timelineExpanded ? timelineItems : timelineItems.slice(0, 10);

  return (
    <div className="flex flex-col h-full overflow-hidden">
      {/* ── Back header ── */}
      <div className="flex-shrink-0 flex items-center gap-3 px-4 py-3 border-b border-gray-100 bg-white">
        <button
          onClick={() => router.back()}
          className="w-7 h-7 flex items-center justify-center rounded-lg text-gray-400 hover:text-gray-600 hover:bg-gray-100 transition-colors"
        >
          <ArrowLeft size={15} />
        </button>
        <div className="flex-1 min-w-0">
          <h2 className="font-bold text-[14px] text-gray-900 truncate">{data.display_name}</h2>
          <p className="text-[10px] text-gray-400">{data.inquiry_stage} · {data.source?.replace(/_/g, " ")}</p>
        </div>
        <div className="flex items-center gap-1.5">
          {SIGNAL_ROLES.has(role) && (
            <button
              onClick={() => setShowSignalDrawer(true)}
              className="flex items-center gap-1 text-[11px] font-medium text-teal-600 border border-teal-200 bg-teal-50 hover:bg-teal-100 px-2.5 py-1.5 rounded-lg transition-colors"
            >
              <Plus size={11} />
              Add Signal
            </button>
          )}
          <button
            onClick={() => refreshMutation.mutate()}
            disabled={refreshMutation.isPending}
            className="w-7 h-7 flex items-center justify-center rounded-lg border border-gray-200 text-gray-400 hover:text-teal-600 hover:border-teal-200 transition-colors"
            title="Refresh AI summary"
          >
            <RefreshCw size={12} className={refreshMutation.isPending ? "animate-spin" : ""} />
          </button>
        </div>
      </div>

      {/* ── Scrollable content ── */}
      <div className="flex-1 overflow-y-auto haip-scrollbar">
        <div className="p-4 space-y-4 max-w-2xl mx-auto">

          {/* Profile card */}
          <div className="bg-white rounded-xl border border-gray-100 p-4 space-y-3">
            <CompletenessBar pct={data.profile_completeness_pct} />

            {/* Identity signals */}
            <div className="flex flex-wrap gap-1.5">
              {(data.identity_signals ?? []).map((sig: string) => (
                <span key={sig} className="text-[10px] bg-teal-50 text-teal-700 border border-teal-100 px-2 py-0.5 rounded-full">
                  {sig.replace(/_/g, " ")}
                </span>
              ))}
              {(data.identity_signals ?? []).length === 0 && (
                <span className="text-[10px] text-gray-400 italic">No identity signals yet</span>
              )}
            </div>

            {/* Trip intent */}
            {(data.occasion || data.check_in || data.budget_estimate) && (
              <div className="flex flex-wrap gap-2 text-[11px] text-gray-600 border-t border-gray-50 pt-2">
                {data.occasion && <span className="capitalize">{data.occasion}</span>}
                {data.group_type && data.group_type !== data.occasion && (
                  <span className="capitalize text-gray-400">{data.group_type?.replace(/_/g, " ")}</span>
                )}
                {data.check_in && <span>{data.check_in}{data.check_out ? ` → ${data.check_out}` : ""}</span>}
                {data.budget_estimate && (
                  <span className="font-medium">₹{Number(data.budget_estimate).toLocaleString("en-IN")}</span>
                )}
              </div>
            )}
          </div>

          {/* AI summary */}
          <div className="bg-teal-50 rounded-xl border border-teal-100 p-3.5">
            <div className="flex items-center justify-between mb-1.5">
              <div className="flex items-center gap-1.5">
                <Sparkles size={13} className="text-teal-600" />
                <span className="text-[11px] font-semibold text-teal-700">AI Summary</span>
              </div>
            </div>
            {data.ai_summary ? (
              <p className="text-[12px] text-teal-800 leading-relaxed">{data.ai_summary}</p>
            ) : (
              <p className="text-[11px] text-teal-500 italic">Generating summary… refresh in a moment.</p>
            )}
            {data.ai_next_action && (
              <p className="text-[11px] text-teal-600 font-medium mt-1.5 border-t border-teal-100 pt-1.5">
                → {data.ai_next_action}
              </p>
            )}
          </div>

          {/* Property interest */}
          {(data.property_interest ?? []).length > 0 && (
            <div className="bg-white rounded-xl border border-gray-100 p-3.5">
              <h3 className="text-[11px] font-semibold text-gray-700 mb-2 flex items-center gap-1.5">
                <Building2 size={12} className="text-gray-400" />
                Property Interest
              </h3>
              <div className="flex flex-wrap gap-1.5">
                {data.property_interest.map((p: string) => (
                  <span key={p} className="text-[11px] bg-gray-50 border border-gray-100 text-gray-700 px-2.5 py-1 rounded-lg">
                    {p}
                  </span>
                ))}
              </div>
            </div>
          )}

          {/* Quote history */}
          {(data.quote_history ?? []).length > 0 && (
            <div className="bg-white rounded-xl border border-gray-100 p-3.5">
              <h3 className="text-[11px] font-semibold text-gray-700 mb-2">Quote History</h3>
              <div className="space-y-1.5">
                {data.quote_history.map((q: QuoteHistory) => (
                  <div key={q.id} className={cn("flex items-center justify-between text-[11px] px-2.5 py-1.5 rounded-lg", q.is_active ? "bg-teal-50 border border-teal-100" : "bg-gray-50")}>
                    <span className={cn("font-medium", q.is_active ? "text-teal-700" : "text-gray-600")}>
                      {q.currency} {Number(q.amount).toLocaleString("en-IN")}
                    </span>
                    <span className="text-gray-400">
                      {q.age_days != null ? `${q.age_days}d ago` : "—"}
                      {q.is_active && <span className="ml-1.5 text-teal-600 font-medium">Active</span>}
                    </span>
                  </div>
                ))}
              </div>
            </div>
          )}

          {/* Timeline */}
          <div className="bg-white rounded-xl border border-gray-100 p-3.5">
            <div className="flex items-center justify-between mb-3">
              <h3 className="text-[11px] font-semibold text-gray-700 flex items-center gap-1.5">
                <Clock size={12} className="text-gray-400" />
                Communication Timeline
                {data.timeline_capped && (
                  <span className="text-[10px] text-gray-400 font-normal">(showing last 50)</span>
                )}
              </h3>
            </div>

            {timelineItems.length === 0 ? (
              <p className="text-[11px] text-gray-400 text-center py-4">No messages yet</p>
            ) : (
              <div className="space-y-2">
                {visibleTimeline.map(entry => (
                  <div key={entry.id} className="flex items-start gap-2.5">
                    <div className="flex-shrink-0 w-6 h-6 rounded-full bg-gray-50 border border-gray-100 flex items-center justify-center mt-0.5">
                      <ChannelIcon channel={entry.channel} />
                    </div>
                    <div className="flex-1 min-w-0">
                      <p className="text-[11px] text-gray-700 leading-relaxed line-clamp-2">
                        {entry.content_preview || entry.call_summary || "—"}
                        {entry.is_ai_generated && (
                          <span className="ml-1.5 text-teal-500 text-[9px]">AI</span>
                        )}
                      </p>
                      <div className="flex items-center gap-2 mt-0.5">
                        <span className="text-[9px] text-gray-400 capitalize">{entry.direction}</span>
                        <span className="text-[9px] text-gray-300">·</span>
                        <span className="text-[9px] text-gray-400">{timeAgo(entry.occurred_at)}</span>
                      </div>
                    </div>
                  </div>
                ))}

                {timelineItems.length > 10 && (
                  <button
                    onClick={() => setTimelineExpanded(!timelineExpanded)}
                    className="w-full text-[11px] text-teal-600 hover:text-teal-700 py-1.5 flex items-center justify-center gap-1 transition-colors"
                  >
                    <ChevronDown size={12} className={timelineExpanded ? "rotate-180" : ""} />
                    {timelineExpanded ? "Show less" : `Show all ${timelineItems.length} entries`}
                  </button>
                )}
              </div>
            )}
          </div>

        </div>
      </div>

      {/* ── Signal drawer ── */}
      {showSignalDrawer && (
        <SignalDrawer
          inquiryId={inquiryId}
          onClose={() => setShowSignalDrawer(false)}
          onSuccess={() => qc.invalidateQueries({ queryKey: ["lead", inquiryId] })}
        />
      )}
    </div>
  );
}
