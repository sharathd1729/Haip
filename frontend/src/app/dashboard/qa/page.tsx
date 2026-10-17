"use client";
import { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { Star, TrendingUp, TrendingDown, ChevronRight, Award, Loader2 } from "@/lib/icons";
import api from "@/lib/api";
import { cn } from "@/lib/utils";
import { ScoreRing } from "@/components/calls/ScoreRing";
import { Badge } from "@/components/ui/badge";
import { Skeleton } from "@/components/ui/skeleton";
import { useToast } from "@/components/ui/toast";

// ─── Types ─────────────────────────────────────────────────────────────────────

interface AgentScore {
  agent_id: string;
  agent_name: string;
  avg_score: number;
  call_count: number;
  trend: "up" | "down" | "neutral";
  top_criteria: string[];
  weak_criteria: string[];
}

interface RubricCriterion {
  id: string;
  name: string;
  description?: string;
  max_score: number;
  weight: number;
}

type Tab = "leaderboard" | "rubric" | "coaching";

// ─── Page ─────────────────────────────────────────────────────────────────────

export default function QAPage() {
  const [tab, setTab] = useState<Tab>("leaderboard");
  const { toast } = useToast();

  const { data: agents = [], isLoading: agentsLoading } = useQuery<AgentScore[]>({
    queryKey: ["qa-leaderboard"],
    queryFn: async () => {
      try {
        const res = await api.get("/analytics/personal-scorecard");
        const d = res.data;
        // Endpoint returns a single scorecard object — wrap into leaderboard format
        if (d && typeof d === "object" && !Array.isArray(d)) {
          if (d.avg_qa_score !== undefined) {
            return [{
              agent_id: d.user_id,
              agent_name: d.user_name,
              avg_score: d.avg_qa_score ?? 0,
              call_count: d.calls_handled ?? 0,
              trend: "neutral" as const,
              top_criteria: [],
              weak_criteria: [],
            }];
          }
        }
        return Array.isArray(d) ? d : [];
      } catch {
        return [];
      }
    },
    staleTime: 60_000,
  });

  const { data: rubric = [], isLoading: rubricLoading } = useQuery<RubricCriterion[]>({
    queryKey: ["qa-rubric"],
    queryFn: () => api.get("/qa/rubrics").then(r => r.data[0]?.criteria ?? DEMO_RUBRIC).catch(() => DEMO_RUBRIC),
    enabled: tab === "rubric",
  });

  const TrendIcon = ({ t }: { t: "up" | "down" | "neutral" }) =>
    t === "up" ? <TrendingUp size={13} className="text-primary" /> :
    t === "down" ? <TrendingDown size={13} className="text-red-400" /> :
    <span className="w-3 h-0.5 bg-[var(--haip-border-strong)] inline-block" />;

  return (
    <div className="h-full flex flex-col bg-white">
      <div className="px-5 py-4 border-b border-[var(--haip-border)] flex-shrink-0">
        <div className="flex items-center gap-3 mb-4">
          <div className="w-9 h-9 rounded-xl bg-amber-100 flex items-center justify-center">
            <Star size={18} className="text-amber-500" />
          </div>
          <div>
            <h1 className="haip-page-title">QA & Coaching</h1>
            <p className="text-xs text-[var(--haip-fg-subtle)]">Agent leaderboard · rubric editor · coaching nudges</p>
          </div>
        </div>
        <div className="flex gap-1">
          {(["leaderboard", "rubric", "coaching"] as Tab[]).map(t => (
            <button
              key={t}
              onClick={() => setTab(t)}
              className={cn(
                "px-3 py-1.5 rounded-lg text-xs font-medium transition-colors capitalize",
                tab === t ? "bg-primary text-white" : "text-[var(--haip-fg-subtle)] hover:bg-[var(--haip-status-neutral-bg)]"
              )}
            >
              {t}
            </button>
          ))}
        </div>
      </div>

      {/* Leaderboard */}
      {tab === "leaderboard" && (
        <div className="flex-1 overflow-y-auto p-5">
          {agentsLoading ? (
            <div className="space-y-3">
              {Array.from({ length: 5 }).map((_, i) => <Skeleton key={i} className="h-20 rounded-2xl" />)}
            </div>
          ) : agents.length === 0 ? (
            <div className="py-16 text-center text-sm text-[var(--haip-fg-subtle)]">
              <Award size={32} className="text-[var(--haip-fg-subtle)]/70 mx-auto mb-3" />
              No QA data yet — scores will appear after calls are analyzed
            </div>
          ) : (
            <div className="space-y-3">
              {[...agents].sort((a, b) => b.avg_score - a.avg_score).map((agent, idx) => (
                <div
                  key={agent.agent_id}
                  className="haip-card p-4 shadow-sm flex items-center gap-4 hover:shadow-md transition-shadow"
                >
                  {/* Rank */}
                  <div className={cn(
                    "w-8 h-8 rounded-full flex items-center justify-center text-sm font-black flex-shrink-0",
                    idx === 0 ? "bg-amber-100 text-amber-600" :
                    idx === 1 ? "bg-[var(--haip-status-neutral-bg)] text-[var(--haip-fg-muted)]" :
                    idx === 2 ? "bg-orange-50 text-orange-600" :
                    "bg-[var(--haip-surface)] text-[var(--haip-fg-subtle)]"
                  )}>
                    {idx + 1}
                  </div>

                  {/* Agent info */}
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-2 mb-1">
                      <span className="text-sm font-semibold text-[var(--haip-fg)]">{agent.agent_name}</span>
                      <TrendIcon t={agent.trend} />
                    </div>
                    <div className="flex items-center gap-3 text-xs text-[var(--haip-fg-subtle)]">
                      <span>{agent.call_count} calls scored</span>
                      {agent.top_criteria[0] && (
                        <span className="text-primary">✓ {agent.top_criteria[0]}</span>
                      )}
                      {agent.weak_criteria[0] && (
                        <span className="text-amber-500">↗ {agent.weak_criteria[0]}</span>
                      )}
                    </div>
                  </div>

                  <ScoreRing score={agent.avg_score} size={52} strokeWidth={5} />
                </div>
              ))}
            </div>
          )}
        </div>
      )}

      {/* Rubric */}
      {tab === "rubric" && (
        <div className="flex-1 overflow-y-auto p-5">
          <div className="flex items-center justify-between mb-4">
            <p className="text-sm text-[var(--haip-fg-subtle)]">hospitality_v1 rubric · {rubric.length} criteria · {rubric.reduce((s, c) => s + c.max_score, 0)} total points</p>
          </div>
          {rubricLoading ? (
            <div className="space-y-3">
              {Array.from({ length: 8 }).map((_, i) => <Skeleton key={i} className="h-14 rounded-xl" />)}
            </div>
          ) : (
            <div className="space-y-2">
              {rubric.map((c, i) => (
                <div key={c.id || i} className="flex items-center gap-4 p-4 bg-[var(--haip-surface)] rounded-xl border border-[var(--haip-border)]">
                  <div className="flex-1 min-w-0">
                    <p className="text-sm font-semibold text-[var(--haip-fg)] capitalize">{c.name.replace(/_/g, " ")}</p>
                    {c.description && <p className="text-xs text-[var(--haip-fg-subtle)] mt-0.5">{c.description}</p>}
                  </div>
                  <div className="flex items-center gap-3 flex-shrink-0">
                    <span className="text-xs text-[var(--haip-fg-subtle)]">Weight: {c.weight}</span>
                    <Badge variant="outline" className="text-xs font-mono">{c.max_score} pts</Badge>
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>
      )}

      {/* Coaching nudges */}
      {tab === "coaching" && (
        <div className="flex-1 overflow-y-auto p-5">
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
            {[...agents].sort((a, b) => a.avg_score - b.avg_score).slice(0, 4).map(agent => (
              agent.weak_criteria.length > 0 && (
                <div key={agent.agent_id} className="haip-card p-5 shadow-sm">
                  <div className="flex items-center gap-3 mb-3">
                    <ScoreRing score={agent.avg_score} size={40} strokeWidth={4} />
                    <div>
                      <p className="text-sm font-semibold text-[var(--haip-fg)]">{agent.agent_name}</p>
                      <p className="text-xs text-[var(--haip-fg-subtle)]">{agent.call_count} calls scored</p>
                    </div>
                  </div>
                  <div>
                    <p className="text-xs font-semibold text-amber-600 uppercase tracking-wide mb-2">Focus areas</p>
                    <ul className="space-y-1.5">
                      {agent.weak_criteria.map((c, i) => (
                        <li key={i} className="flex items-start gap-2 text-xs text-[var(--haip-fg-2)]">
                          <span className="text-amber-400 flex-shrink-0 mt-0.5">→</span>
                          <span className="capitalize">{c.replace(/_/g, " ")}</span>
                        </li>
                      ))}
                    </ul>
                  </div>
                </div>
              )
            ))}
            {agents.length === 0 && (
              <div className="col-span-2 py-16 text-center text-sm text-[var(--haip-fg-subtle)]">
                Coaching nudges will appear after agents have been scored on 3+ calls.
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  );
}

// ─── Demo data (shown when API unavailable) ───────────────────────────────────

const DEMO_AGENTS: AgentScore[] = [
  { agent_id: "1", agent_name: "Ravi Kumar",   avg_score: 88, call_count: 42, trend: "up",      top_criteria: ["warm_greeting", "needs_discovery"], weak_criteria: ["objection_handling"] },
  { agent_id: "2", agent_name: "Priya Menon",  avg_score: 82, call_count: 37, trend: "neutral",  top_criteria: ["rapport_building"],                 weak_criteria: ["upsell_attempt", "follow_up_commitment"] },
  { agent_id: "3", agent_name: "Ananya Singh", avg_score: 76, call_count: 28, trend: "up",       top_criteria: ["dpdp_compliance"],                  weak_criteria: ["emotional_intelligence"] },
  { agent_id: "4", agent_name: "Deepa Nair",   avg_score: 71, call_count: 19, trend: "down",     top_criteria: ["property_knowledge"],               weak_criteria: ["needs_discovery", "urgency_creation"] },
];

const DEMO_RUBRIC: RubricCriterion[] = [
  { id: "1",  name: "warm_greeting",           description: "Opens warmly, uses guest name", max_score: 10, weight: 1 },
  { id: "2",  name: "needs_discovery",          description: "Asks about dates, group size, purpose", max_score: 15, weight: 1.5 },
  { id: "3",  name: "property_knowledge",       description: "Accurately describes amenities & policies", max_score: 15, weight: 1.5 },
  { id: "4",  name: "rapport_building",         description: "Creates connection beyond transactional Q&A", max_score: 10, weight: 1 },
  { id: "5",  name: "objection_handling",       description: "Addresses price/dates concerns calmly & confidently", max_score: 15, weight: 1.5 },
  { id: "6",  name: "upsell_attempt",           description: "Suggests add-ons, upgrades, or sister properties", max_score: 10, weight: 1 },
  { id: "7",  name: "urgency_creation",         description: "Communicates scarcity / limited availability", max_score: 10, weight: 1 },
  { id: "8",  name: "follow_up_commitment",     description: "Confirms next step (quote sent, callback time)", max_score: 5,  weight: 0.5 },
  { id: "9",  name: "emotional_intelligence",   description: "Handles frustration, disappointment with empathy", max_score: 10, weight: 1 },
  { id: "10", name: "dpdp_compliance",          description: "Mentions recording notice if required", max_score: 5,  weight: 0.5 },
];
