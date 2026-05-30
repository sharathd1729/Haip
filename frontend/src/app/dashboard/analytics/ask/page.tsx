"use client";

/**
 * Ask HAIP — Hospitality Intelligence Analyst
 *
 * ThinkPath-style investigation paths + Root Cause Engine.
 * NOT a chatbot. A structured intelligence analyst.
 */

import { useState, useRef, useEffect } from "react";
import { useMutation, useQuery } from "@tanstack/react-query";
import {
  Sparkles, ChevronRight, AlertCircle,
  Send, Loader2, RotateCcw, ExternalLink, Info,
  PlayCircle, CheckCircle2, ChevronDown,
} from "lucide-react";
import { useRouter } from "next/navigation";
import { cn } from "@/lib/utils";
import api from "@/lib/api";

// ─── Types ─────────────────────────────────────────────────────────────────

interface PathStep {
  step: number;
  label: string;
  description: string;
  status: "pending" | "complete" | "running";
  data: null;
}

interface InvestigationPath {
  id: string;
  name: string;
  icon: string;
  domains: string[];
  steps: PathStep[];
  snapshot: Record<string, unknown>;
}

interface Recommendation {
  action: string;
  expected_impact: string;
  module: string;
  href: string;
}

interface AgentKPI {
  label: string;
  value: string | number;
  prev?: string | number;
  delta_pct?: number;
  trend?: "up" | "down" | "flat";
  unit?: string;
  severity?: "critical" | "warning" | "good" | "normal";
}

interface AgentOutput {
  agent: string;
  domain: string;
  status: "ok" | "no_data" | "error";
  kpis: AgentKPI[];
  findings: string[];
  top_concern?: string;
  top_positive?: string;
  summary: string;
}

interface Finding {
  title: string;
  evidence: string[];
  impact: { revenue_loss: number; currency: string; severity: string; description?: string };
  root_cause: string;
  recommendations: Recommendation[];
}

interface Signal {
  message: string;
  severity: "critical" | "warning" | "info" | "positive";
  domains: string[];
}

interface HistoryItem {
  id: string;
  summary: string;
  confidence: number;
  confidence_label: string;
  findings_count: number;
  top_finding: string;
  created_at: string;
  range_days: number;
}

interface AskHaipResponse {
  session_id: string;
  question: string;
  intent: { domains: string[]; type: string };
  paths: InvestigationPath[];
  correlations: string[];
  structured_signals: Signal[];       // Phase 4
  findings: Finding[];
  summary: string;
  root_cause_chain: string;           // Phase 4
  confidence: number;
  confidence_label: string;           // Phase 4: high | medium | low
  data_completeness: string;
  missing_domains: string[];          // Phase 4
  investigation_paths_used: string[];
  compare_mode: boolean;              // Phase 4
  agents: Record<string, AgentOutput>;
}

// ─── Suggested Questions ───────────────────────────────────────────────────

const SUGGESTED = [
  "Why did revenue drop this month?",
  "Which properties are underperforming?",
  "Which channel converts best?",
  "What objections are increasing?",
  "Why are bookings declining?",
  "Which guests generate the highest revenue?",
  "Which travel intent converts best?",
  "Why is occupancy low?",
];

// ─── Severity Config ────────────────────────────────────────────────────────

const SEVERITY_CFG = {
  high:   { bg: "bg-red-50",   border: "border-red-200",   badge: "bg-red-100 text-red-700",   icon: <AlertCircle size={14} className="text-red-500" /> },
  medium: { bg: "bg-amber-50", border: "border-amber-200", badge: "bg-amber-100 text-amber-700", icon: <AlertCircle size={14} className="text-amber-500" /> },
  low:    { bg: "bg-blue-50",  border: "border-blue-200",  badge: "bg-blue-100 text-blue-600",  icon: <Info size={14} className="text-blue-500" /> },
};

function fmt_inr(n: number) {
  if (!n) return "—";
  if (n >= 10000000) return `₹${(n / 10000000).toFixed(1)}Cr`;
  if (n >= 100000)   return `₹${(n / 100000).toFixed(1)}L`;
  if (n >= 1000)     return `₹${(n / 1000).toFixed(0)}k`;
  return `₹${Math.round(n)}`;
}

// ─── Phase 3 Step Types ──────────────────────────────────────────────────────

interface StepKPI { label: string; value: string|number; delta_pct?: number; trend?: string; severity?: string; }
interface StepRow { name: string; primary: string; secondary?: string; delta?: string; severity?: string; }
interface StepAction { action: string; impact: string; module: string; href: string; priority: number; }
interface StepData {
  path_id: string; step: number; label: string; headline: string;
  kpis: StepKPI[]; rows: StepRow[]; actions: StepAction[]; finding: string; evidence: string[];
}
interface StepResult {
  path_id: string; steps_executed: number;
  cumulative: StepData[];
}

// ─── Step KPI chip ───────────────────────────────────────────────────────────

const SEV_CHIP: Record<string, string> = {
  critical: "bg-red-50 border-red-200 text-red-700",
  warning:  "bg-amber-50 border-amber-200 text-amber-700",
  good:     "bg-green-50 border-green-200 text-green-700",
  normal:   "bg-gray-50 border-gray-100 text-gray-700",
};

function StepResultPanel({ stepData }: { stepData: StepData }) {
  const router = useRouter();
  return (
    <div className="mt-3 space-y-3 border-t border-gray-100 pt-3">
      {/* Headline */}
      <p className="text-xs font-semibold text-gray-800">{stepData.headline}</p>

      {/* KPIs */}
      {stepData.kpis.length > 0 && (
        <div className="grid grid-cols-2 gap-1.5">
          {stepData.kpis.slice(0, 6).map((k, i) => (
            <div key={i} className={cn("rounded-xl px-2.5 py-1.5 border text-[10px]",
              SEV_CHIP[k.severity ?? "normal"])}>
              <p className="font-bold text-sm leading-none mb-0.5">{k.value}</p>
              <p className="opacity-70">{k.label}</p>
              {k.delta_pct != null && (
                <p className={cn("text-[9px] mt-0.5 font-medium",
                  k.delta_pct > 0 ? "text-green-600" : "text-red-600")}>
                  {k.delta_pct > 0 ? "+" : ""}{k.delta_pct?.toFixed(1)}%
                </p>
              )}
            </div>
          ))}
        </div>
      )}

      {/* Rows (Diagnose table) */}
      {stepData.rows.length > 0 && (
        <div className="space-y-1">
          {stepData.rows.slice(0, 8).map((row, i) => (
            <div key={i} className={cn(
              "flex items-center justify-between px-3 py-2 rounded-xl text-xs",
              row.severity === "critical" ? "bg-red-50" :
              row.severity === "warning"  ? "bg-amber-50" :
              row.severity === "good"     ? "bg-green-50" : "bg-gray-50",
            )}>
              <span className="font-medium text-gray-700 truncate flex-1">{row.name}</span>
              <span className="text-gray-600 shrink-0 ml-2">{row.primary}</span>
              {row.secondary && <span className="text-gray-400 shrink-0 ml-2 text-[10px]">{row.secondary}</span>}
              {row.delta && <span className="text-gray-400 shrink-0 ml-2 text-[10px]">{row.delta}</span>}
            </div>
          ))}
        </div>
      )}

      {/* Evidence bullets */}
      {stepData.evidence.length > 0 && (
        <ul className="space-y-1">
          {stepData.evidence.map((e, i) => (
            <li key={i} className="text-[11px] text-gray-500 flex items-start gap-1.5">
              <span className="text-teal-400 shrink-0 mt-0.5">•</span>{e}
            </li>
          ))}
        </ul>
      )}

      {/* Actions (Step 3 Recommend) */}
      {stepData.actions.length > 0 && (
        <div className="space-y-2">
          {stepData.actions.map((a, i) => (
            <div key={i} className="bg-teal-50 border border-teal-100 rounded-xl p-3 flex items-start justify-between gap-2">
              <div className="flex-1">
                <p className="text-xs font-medium text-gray-800">{a.action}</p>
                {a.impact && <p className="text-[11px] text-teal-600 mt-0.5">{a.impact}</p>}
              </div>
              {a.href && (
                <button onClick={() => router.push(a.href)}
                  className="shrink-0 text-[10px] font-semibold text-teal-700 bg-white px-2 py-1 rounded-lg border border-teal-200 flex items-center gap-1">
                  {a.module || "Open"} <ExternalLink size={9} />
                </button>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

// ─── Interactive Path Card (Phase 3) ────────────────────────────────────────

function PathCard({
  path,
  sessionId,
  rangeDays,
}: {
  path: InvestigationPath;
  sessionId: string;
  rangeDays: number;
}) {
  const [activeStep, setActiveStep] = useState(0);
  const [stepResult, setStepResult] = useState<StepResult | null>(null);
  const [loading, setLoading] = useState(false);
  const [expanded, setExpanded] = useState(true);

  async function runStep(step: number) {
    if (loading) return;
    setLoading(true);
    try {
      const res = await api.post("/analytics/ask/step", {
        session_id: sessionId,
        path_id: path.id,
        step,
        range_days: rangeDays,
      });
      setStepResult(res.data);
      setActiveStep(step);
      setExpanded(true);
    } catch (e) {
      console.error("Step failed", e);
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="bg-white border border-gray-100 rounded-2xl p-4">
      {/* Header */}
      <div className="flex items-center justify-between mb-3">
        <div className="flex items-center gap-2">
          <span className="text-base">{path.icon}</span>
          <h3 className="text-sm font-semibold text-gray-800">{path.name}</h3>
          {activeStep > 0 && (
            <span className="text-[10px] font-medium text-teal-600 bg-teal-50 px-1.5 py-0.5 rounded-full border border-teal-100">
              Step {activeStep} done
            </span>
          )}
        </div>
        {stepResult && (
          <button onClick={() => setExpanded(e => !e)}
            className="text-gray-300 hover:text-gray-500">
            <ChevronDown size={14} className={cn("transition-transform", expanded ? "" : "-rotate-90")} />
          </button>
        )}
      </div>

      {/* Snapshot */}
      {Object.keys(path.snapshot).length > 0 && activeStep === 0 && (
        <div className="flex flex-wrap gap-3 mb-3">
          {Object.entries(path.snapshot).slice(0, 3).map(([k, v]) => (
            <div key={k} className="text-[10px] text-gray-400">
              <span className="text-gray-600 font-medium capitalize">{k.replace(/_/g, " ")}: </span>
              <span>{typeof v === "number" && v > 1000 ? fmt_inr(v) : String(v ?? "—")}</span>
            </div>
          ))}
        </div>
      )}

      {/* Step buttons */}
      <div className="flex gap-1">
        {path.steps.map((step) => (
          <button
            key={step.step}
            onClick={() => runStep(step.step)}
            disabled={loading}
            className={cn(
              "flex-1 py-2 px-1 rounded-xl text-[11px] font-medium text-center transition-all border",
              loading && activeStep + 1 === step.step
                ? "bg-teal-100 text-teal-600 border-teal-200 animate-pulse"
                : activeStep >= step.step
                  ? "bg-teal-500 text-white border-teal-500 shadow-sm"
                  : "bg-gray-50 text-gray-500 border-gray-100 hover:border-teal-200 hover:text-teal-600",
            )}
          >
            {loading && activeStep + 1 === step.step
              ? <Loader2 size={10} className="animate-spin mx-auto" />
              : activeStep >= step.step
                ? <CheckCircle2 size={10} className="mx-auto mb-0.5" />
                : <span className="text-[10px] block opacity-60 mb-0.5">{step.step}</span>
            }
            {step.label}
          </button>
        ))}
      </div>

      <p className="text-[10px] text-gray-400 mt-1.5">
        {path.steps[Math.max(activeStep - 1, 0)]?.description ?? path.steps[0]?.description}
      </p>

      {/* Cumulative step results */}
      {stepResult && expanded && stepResult.cumulative.map((sd, i) => (
        <div key={i}>
          <div className="flex items-center gap-2 mt-3 mb-1">
            <span className="text-[9px] font-semibold uppercase tracking-wide text-teal-500 bg-teal-50 px-2 py-0.5 rounded-full border border-teal-100">
              Step {sd.step} — {sd.label}
            </span>
          </div>
          <StepResultPanel stepData={sd} />
        </div>
      ))}
    </div>
  );
}

// ─── Agent Panel ────────────────────────────────────────────────────────────

const SEVERITY_KPI: Record<string, string> = {
  critical: "text-red-600 bg-red-50 border-red-100",
  warning:  "text-amber-600 bg-amber-50 border-amber-100",
  good:     "text-green-600 bg-green-50 border-green-100",
  normal:   "text-gray-700 bg-gray-50 border-gray-100",
};

const DOMAIN_LABELS: Record<string, string> = {
  revenue: "Revenue", occupancy: "Occupancy", inquiry: "Inquiries",
  guest: "Guests", channel: "Channels", campaign: "Campaigns",
  property: "Properties", objection: "Objections",
  intent: "Intent", attribution: "Attribution",
};

function AgentPanel({ agents }: { agents: Record<string, AgentOutput> }) {
  const agentList = Object.values(agents).filter(a => a.status === "ok");
  if (agentList.length === 0) return null;

  return (
    <div>
      <p className="text-[10px] font-semibold text-gray-400 uppercase tracking-wide mb-2">
        Agent Intelligence ({agentList.length} agents)
      </p>
      <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
        {agentList.map(agent => (
          <div key={agent.agent} className="bg-white border border-gray-100 rounded-2xl p-4">
            <div className="flex items-center justify-between mb-3">
              <p className="text-xs font-semibold text-gray-800">
                {DOMAIN_LABELS[agent.domain] ?? agent.domain}
              </p>
              {agent.top_concern && (
                <span className="text-[9px] font-medium text-red-600 bg-red-50 px-1.5 py-0.5 rounded-full border border-red-100">
                  ⚠ concern
                </span>
              )}
              {!agent.top_concern && agent.top_positive && (
                <span className="text-[9px] font-medium text-green-600 bg-green-50 px-1.5 py-0.5 rounded-full border border-green-100">
                  ✓ good
                </span>
              )}
            </div>

            {/* KPIs */}
            <div className="grid grid-cols-2 gap-1.5 mb-3">
              {agent.kpis.slice(0, 4).map((kpi, i) => (
                <div key={i}
                  className={cn("rounded-xl px-2.5 py-1.5 border text-[10px]",
                    SEVERITY_KPI[kpi.severity ?? "normal"])}>
                  <p className="font-bold text-sm leading-none mb-0.5">{kpi.value}</p>
                  <p className="opacity-70 leading-none">{kpi.label}</p>
                  {kpi.delta_pct != null && (
                    <p className={cn("text-[9px] mt-0.5 font-medium",
                      kpi.delta_pct > 0 ? "text-green-600" : "text-red-600")}>
                      {kpi.delta_pct > 0 ? "+" : ""}{kpi.delta_pct?.toFixed(1)}%
                    </p>
                  )}
                </div>
              ))}
            </div>

            {/* Top signal */}
            {(agent.top_concern || agent.top_positive) && (
              <p className="text-[10px] text-gray-500 leading-relaxed">
                {agent.top_concern || agent.top_positive}
              </p>
            )}
          </div>
        ))}
      </div>
    </div>
  );
}

// ─── Phase 4: Signal Panel ───────────────────────────────────────────────────

const SIGNAL_CFG: Record<string, { icon: string; bg: string; text: string; border: string }> = {
  critical: { icon: "🔴", bg: "bg-red-50",    text: "text-red-800",    border: "border-red-200" },
  warning:  { icon: "🟡", bg: "bg-amber-50",  text: "text-amber-800",  border: "border-amber-200" },
  info:     { icon: "🔵", bg: "bg-blue-50",   text: "text-blue-800",   border: "border-blue-100" },
  positive: { icon: "🟢", bg: "bg-green-50",  text: "text-green-800",  border: "border-green-200" },
};

function SignalPanel({ signals }: { signals: Signal[] }) {
  if (signals.length === 0) return null;
  const critical = signals.filter(s => s.severity === "critical");
  const warnings = signals.filter(s => s.severity === "warning");
  const positives= signals.filter(s => s.severity === "positive");

  return (
    <div className="bg-white border border-gray-100 rounded-2xl p-5 space-y-3">
      <div className="flex items-center justify-between">
        <p className="text-xs font-semibold text-gray-800">Cross-Agent Signals</p>
        <div className="flex gap-2 text-[10px]">
          {critical.length > 0  && <span className="text-red-600 font-semibold">{critical.length} critical</span>}
          {warnings.length > 0  && <span className="text-amber-600 font-semibold">{warnings.length} warning</span>}
          {positives.length > 0 && <span className="text-green-600 font-semibold">{positives.length} positive</span>}
        </div>
      </div>
      <div className="space-y-1.5">
        {signals.map((sig, i) => {
          const cfg = SIGNAL_CFG[sig.severity] ?? SIGNAL_CFG.info;
          return (
            <div key={i} className={cn("flex items-start gap-2 px-3 py-2 rounded-xl border text-xs", cfg.bg, cfg.border)}>
              <span className="shrink-0 text-[12px]">{cfg.icon}</span>
              <span className={cfg.text}>{sig.message}</span>
              {sig.domains.length > 0 && (
                <div className="ml-auto flex gap-1 shrink-0">
                  {sig.domains.slice(0,2).map(d => (
                    <span key={d} className="text-[9px] text-gray-400 bg-white px-1.5 py-0.5 rounded-full border border-gray-100 capitalize">{d}</span>
                  ))}
                </div>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}

// ─── Phase 4: Confidence Badge ───────────────────────────────────────────────

function ConfidenceBadge({ score, label, missing }: { score: number; label: string; missing: string[] }) {
  const color = label === "high" ? "text-green-600 bg-green-50 border-green-200"
              : label === "medium" ? "text-amber-600 bg-amber-50 border-amber-200"
              : "text-red-600 bg-red-50 border-red-200";
  return (
    <div className={cn("flex items-center gap-1.5 text-[10px] font-semibold px-2 py-1 rounded-full border", color)}>
      <span className="w-1.5 h-1.5 rounded-full bg-current opacity-80" />
      {(score * 100).toFixed(0)}% confidence
      {missing.length > 0 && (
        <span className="font-normal opacity-70">· {missing.length} domain{missing.length>1?"s":""} missing</span>
      )}
    </div>
  );
}

// ─── Phase 4: Root Cause Chain ───────────────────────────────────────────────

function RootCauseChain({ chain }: { chain: string }) {
  if (!chain) return null;
  // "Signal: X → Cause: Y → Impact: ₹Z → Action: W"
  const parts = chain.split("→").map(p => p.trim());
  return (
    <div className="bg-gray-50 border border-gray-100 rounded-2xl p-4">
      <p className="text-[10px] font-semibold text-gray-400 uppercase tracking-wide mb-2">Root Cause Chain</p>
      <div className="flex flex-wrap items-center gap-1">
        {parts.map((part, i) => (
          <span key={i} className="flex items-center gap-1">
            <span className="text-xs text-gray-700 bg-white border border-gray-200 rounded-lg px-2 py-1">{part}</span>
            {i < parts.length - 1 && <span className="text-gray-300 text-sm">→</span>}
          </span>
        ))}
      </div>
    </div>
  );
}

// ─── Phase 4: History Panel ──────────────────────────────────────────────────

function HistoryPanel({ onSelect }: { onSelect: (q: string) => void }) {
  const { data, isLoading } = useQuery<{ history: HistoryItem[] }>({
    queryKey: ["ask-history"],
    queryFn: () => api.get("/analytics/ask/history", { params: { limit: 8 } }).then(r => r.data),
    staleTime: 60_000,
  });

  if (isLoading || !data?.history.length) return null;

  return (
    <div>
      <p className="text-[10px] font-semibold text-gray-400 uppercase tracking-wide mb-2">Recent Analyses</p>
      <div className="space-y-1.5">
        {data.history.map(item => (
          <div key={item.id}
            className="bg-white border border-gray-100 rounded-xl px-4 py-2.5 hover:border-teal-200 cursor-pointer group transition-all"
            onClick={() => onSelect(item.summary)}>
            <div className="flex items-center justify-between">
              <p className="text-xs text-gray-700 group-hover:text-teal-700 truncate flex-1">{item.summary}</p>
              <div className="flex items-center gap-2 ml-2 shrink-0">
                <span className={cn("text-[9px] font-medium px-1.5 py-0.5 rounded-full",
                  item.confidence_label === "high" ? "bg-green-50 text-green-600" :
                  item.confidence_label === "medium" ? "bg-amber-50 text-amber-600" :
                  "bg-gray-50 text-gray-400")}>
                  {(item.confidence * 100).toFixed(0)}%
                </span>
                <span className="text-[9px] text-gray-400">
                  {item.created_at ? new Date(item.created_at).toLocaleDateString() : ""}
                </span>
              </div>
            </div>
            {item.top_finding && (
              <p className="text-[10px] text-gray-400 mt-0.5 truncate">{item.top_finding}</p>
            )}
          </div>
        ))}
      </div>
    </div>
  );
}

function FindingCard({ finding }: { finding: Finding }) {
  const router = useRouter();
  const sev = finding.impact?.severity ?? "medium";
  const cfg = SEVERITY_CFG[sev as keyof typeof SEVERITY_CFG] ?? SEVERITY_CFG.medium;

  return (
    <div className={cn("border rounded-2xl p-5", cfg.bg, cfg.border)}>
      <div className="flex items-start gap-2 mb-3">
        {cfg.icon}
        <div className="flex-1">
          <div className="flex items-center gap-2 flex-wrap mb-1">
            <h3 className="text-sm font-semibold text-gray-900">{finding.title}</h3>
            {finding.impact?.revenue_loss > 0 && (
              <span className="text-[10px] font-semibold text-red-600 bg-red-50 px-2 py-0.5 rounded-full border border-red-200">
                {fmt_inr(finding.impact.revenue_loss)} impact
              </span>
            )}
          </div>
          {finding.root_cause && (
            <p className="text-xs text-gray-500 italic mb-3">{finding.root_cause}</p>
          )}
        </div>
      </div>

      {/* Evidence */}
      {finding.evidence.length > 0 && (
        <div className="mb-4">
          <p className="text-[10px] font-semibold text-gray-400 uppercase tracking-wide mb-2">Evidence</p>
          <ul className="space-y-1">
            {finding.evidence.map((e, i) => (
              <li key={i} className="flex items-start gap-2 text-xs text-gray-700">
                <span className="text-teal-500 shrink-0 mt-0.5">•</span>
                {e}
              </li>
            ))}
          </ul>
        </div>
      )}

      {/* Recommendations */}
      {finding.recommendations.length > 0 && (
        <div>
          <p className="text-[10px] font-semibold text-gray-400 uppercase tracking-wide mb-2">Actions</p>
          <div className="space-y-2">
            {finding.recommendations.map((rec, i) => (
              <div key={i} className="bg-white/70 rounded-xl p-3 border border-white">
                <div className="flex items-start justify-between gap-2">
                  <div className="flex-1">
                    <p className="text-xs font-medium text-gray-800">{rec.action}</p>
                    {rec.expected_impact && (
                      <p className="text-[11px] text-teal-600 mt-0.5">{rec.expected_impact}</p>
                    )}
                  </div>
                  {rec.href && (
                    <button
                      onClick={() => router.push(rec.href)}
                      className="shrink-0 text-[10px] font-semibold text-teal-600 bg-teal-50 px-2 py-1 rounded-lg border border-teal-100 hover:bg-teal-100 flex items-center gap-1"
                    >
                      {rec.module || "Open"} <ExternalLink size={9} />
                    </button>
                  )}
                </div>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

// ─── Main Page ──────────────────────────────────────────────────────────────

export default function AskHaipPage() {
  const [question, setQuestion] = useState("");
  const [result, setResult] = useState<AskHaipResponse | null>(null);
  const [runAllLoading, setRunAllLoading] = useState(false);
  const inputRef = useRef<HTMLTextAreaElement>(null);

  const mutation = useMutation({
    mutationFn: (q: string) =>
      api.post("/analytics/ask", { question: q, range_days: 30 }).then(r => r.data),
    onSuccess: (data: AskHaipResponse) => setResult(data),
  });

  function handleSubmit(q?: string) {
    const text = (q ?? question).trim();
    if (!text) return;
    setQuestion(text);
    setResult(null);
    mutation.mutate(text);
  }

  async function handleRunAll() {
    if (!result) return;
    setRunAllLoading(true);
    try {
      await api.post("/analytics/ask/run-all", {
        session_id: result.session_id,
        domains: result.intent?.domains ?? [],
        range_days: 30,
      });
    } catch (e) {
      console.error("Run all failed", e);
    } finally {
      setRunAllLoading(false);
    }
  }

  function handleReset() {
    setResult(null);
    setQuestion("");
    setTimeout(() => inputRef.current?.focus(), 100);
  }

  // Auto-focus on load
  useEffect(() => { inputRef.current?.focus(); }, []);

  return (
    <div className="min-h-screen bg-gray-50/50">
      <div className="max-w-4xl mx-auto px-4 py-8 space-y-6">

        {/* Header */}
        <div className="flex items-center gap-3">
          <div className="w-9 h-9 rounded-xl bg-gradient-to-br from-teal-400 to-teal-600 flex items-center justify-center">
            <Sparkles size={16} className="text-white" />
          </div>
          <div>
            <h1 className="text-xl font-semibold text-gray-900 tracking-tight">Ask HAIP</h1>
            <p className="text-[12px] text-gray-400 mt-0.5">Hospitality Intelligence Analyst</p>
          </div>
          {result && (
            <button
              onClick={handleReset}
              className="ml-auto text-xs text-gray-400 hover:text-gray-600 flex items-center gap-1"
            >
              <RotateCcw size={12} /> New question
            </button>
          )}
        </div>

        {/* Input */}
        {!result && (
          <>
            <div className="bg-white border border-gray-200 rounded-2xl p-4 shadow-sm">
              <textarea
                ref={inputRef}
                value={question}
                onChange={e => setQuestion(e.target.value)}
                onKeyDown={e => {
                  if (e.key === "Enter" && !e.shiftKey) {
                    e.preventDefault();
                    handleSubmit();
                  }
                }}
                placeholder="Ask anything about your hospitality business..."
                className="w-full resize-none text-sm text-gray-800 placeholder-gray-400 outline-none bg-transparent min-h-[72px]"
                rows={3}
              />
              <div className="flex items-center justify-between mt-3">
                <p className="text-[10px] text-gray-400">Press Enter to analyze · Shift+Enter for new line</p>
                <button
                  onClick={() => handleSubmit()}
                  disabled={!question.trim() || mutation.isPending}
                  className={cn(
                    "flex items-center gap-2 px-4 py-2 rounded-xl text-sm font-medium transition-all",
                    question.trim() && !mutation.isPending
                      ? "bg-teal-500 text-white hover:bg-teal-600"
                      : "bg-gray-100 text-gray-400 cursor-not-allowed",
                  )}
                >
                  {mutation.isPending ? <Loader2 size={14} className="animate-spin" /> : <Send size={14} />}
                  Analyze
                </button>
              </div>
            </div>

            {/* Phase 4: History panel */}
            <HistoryPanel onSelect={(summary) => { setQuestion(summary); }} />

            {/* Suggested questions */}
            <div>
              <p className="text-[10px] font-semibold text-gray-400 uppercase tracking-wide mb-2">Try asking</p>
              <div className="grid grid-cols-1 sm:grid-cols-2 gap-2">
                {SUGGESTED.map((q, i) => (
                  <button
                    key={i}
                    onClick={() => handleSubmit(q)}
                    disabled={mutation.isPending}
                    className="text-left text-xs text-gray-600 bg-white border border-gray-100 rounded-xl px-4 py-2.5 hover:border-teal-200 hover:text-teal-700 transition-all group flex items-center justify-between"
                  >
                    {q}
                    <ChevronRight size={12} className="text-gray-300 group-hover:text-teal-400" />
                  </button>
                ))}
              </div>
            </div>
          </>
        )}

        {/* Loading state */}
        {mutation.isPending && (
          <div className="bg-white border border-gray-100 rounded-2xl p-8 text-center">
            <Loader2 size={24} className="animate-spin text-teal-500 mx-auto mb-3" />
            <p className="text-sm font-medium text-gray-700">Analyzing your data...</p>
            <p className="text-xs text-gray-400 mt-1">Running intelligence agents across all modules</p>
          </div>
        )}

        {/* Error state */}
        {mutation.isError && (
          <div className="bg-red-50 border border-red-200 rounded-2xl p-5 text-center">
            <AlertCircle size={20} className="text-red-500 mx-auto mb-2" />
            <p className="text-sm font-medium text-red-700">Analysis failed</p>
            <p className="text-xs text-red-500 mt-1">Check that the backend is running and try again.</p>
            <button onClick={handleReset} className="mt-3 text-xs text-red-600 underline">Try again</button>
          </div>
        )}

        {/* Results */}
        {result && !mutation.isPending && (
          <div className="space-y-5">
            {/* Question echo + summary */}
            <div className="bg-white border border-gray-100 rounded-2xl p-5">
              <div className="flex items-start gap-3">
                <div className="w-6 h-6 rounded-lg bg-teal-50 flex items-center justify-center shrink-0 mt-0.5">
                  <Sparkles size={12} className="text-teal-500" />
                </div>
                <div className="flex-1">
                  <p className="text-xs text-gray-400 mb-1">{result.question}</p>
                  {result.summary && (
                    <p className="text-sm font-semibold text-gray-800">{result.summary}</p>
                  )}
                  {/* Phase 4: comparative mode badge */}
                  {result.compare_mode && (
                    <span className="inline-block mt-1.5 text-[10px] font-medium text-indigo-600 bg-indigo-50 px-2 py-0.5 rounded-full border border-indigo-100">
                      ↔ Comparative Analysis
                    </span>
                  )}
                  <div className="flex flex-wrap items-center gap-2 mt-2">
                    {result.intent?.domains?.map(d => (
                      <span key={d} className="text-[10px] font-medium text-teal-600 bg-teal-50 px-2 py-0.5 rounded-full border border-teal-100 capitalize">
                        {d}
                      </span>
                    ))}
                    {/* Phase 4: rich confidence badge */}
                    <ConfidenceBadge
                      score={result.confidence}
                      label={result.confidence_label || "low"}
                      missing={result.missing_domains || []}
                    />
                  </div>
                </div>
              </div>
            </div>

            {/* Phase 4: Root cause chain */}
            {result.root_cause_chain && <RootCauseChain chain={result.root_cause_chain} />}

            {/* Phase 4: Structured signal panel (replaces plain correlations) */}
            {result.structured_signals?.length > 0
              ? <SignalPanel signals={result.structured_signals} />
              : result.correlations.length > 0 && (
                <div className="bg-amber-50 border border-amber-200 rounded-2xl p-4">
                  <p className="text-[10px] font-semibold text-amber-600 uppercase tracking-wide mb-2">Signals</p>
                  <ul className="space-y-1">
                    {result.correlations.map((c, i) => (
                      <li key={i} className="text-xs text-amber-800 flex items-start gap-2">
                        <span className="shrink-0 mt-0.5">⚡</span> {c}
                      </li>
                    ))}
                  </ul>
                </div>
              )
            }

            {/* Phase 2: Agent Intelligence Panels */}
            {result.agents && Object.keys(result.agents).length > 0 && (
              <AgentPanel agents={result.agents} />
            )}

            {/* Investigation Paths */}
            {result.paths.length > 0 && (
              <div>
                <div className="flex items-center justify-between mb-2">
                  <p className="text-[10px] font-semibold text-gray-400 uppercase tracking-wide">
                    Investigation Paths ({result.paths.length})
                  </p>
                  <button
                    onClick={handleRunAll}
                    disabled={runAllLoading}
                    className={cn(
                      "flex items-center gap-1.5 text-xs font-medium px-3 py-1.5 rounded-xl border transition-all",
                      runAllLoading
                        ? "bg-gray-100 text-gray-400 border-gray-100"
                        : "bg-teal-500 text-white border-teal-500 hover:bg-teal-600",
                    )}
                  >
                    {runAllLoading
                      ? <><Loader2 size={11} className="animate-spin" /> Running…</>
                      : <><PlayCircle size={11} /> Run All Paths</>
                    }
                  </button>
                </div>
                <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
                  {result.paths.map(path => (
                    <PathCard
                      key={path.id}
                      path={path}
                      sessionId={result.session_id}
                      rangeDays={30}
                    />
                  ))}
                </div>
                <p className="text-[10px] text-gray-400 mt-2">
                  Click steps to investigate. Step 3 → Recommend shows actionable advice. "Run All" executes every path at once.
                </p>
              </div>
            )}

            {/* Findings */}
            {result.findings.length > 0 && (
              <div>
                <p className="text-[10px] font-semibold text-gray-400 uppercase tracking-wide mb-2">
                  Root Cause Findings ({result.findings.length})
                </p>
                <div className="space-y-3">
                  {result.findings.map((finding, i) => (
                    <FindingCard key={i} finding={finding} />
                  ))}
                </div>
              </div>
            )}

            {/* No findings fallback */}
            {result.findings.length === 0 && (
              <div className="bg-white border border-gray-100 rounded-2xl p-8 text-center">
                <Info size={24} className="text-gray-300 mx-auto mb-3" />
                <p className="text-sm font-medium text-gray-600">No findings generated</p>
                <p className="text-xs text-gray-400 mt-1">
                  This could mean your data is in good shape, or the AI service is not configured.
                  Check ANTHROPIC_API_KEY or GEMINI_API_KEY in your environment.
                </p>
              </div>
            )}

            {/* Follow-up input */}
            <div className="bg-white border border-gray-200 rounded-2xl p-4">
              <p className="text-[10px] text-gray-400 mb-2">Ask a follow-up question</p>
              <div className="flex gap-2">
                <textarea
                  value={question}
                  onChange={e => setQuestion(e.target.value)}
                  onKeyDown={e => {
                    if (e.key === "Enter" && !e.shiftKey) {
                      e.preventDefault();
                      handleSubmit();
                    }
                  }}
                  placeholder="Now show me only Villa Serenity... / Compare this month vs last..."
                  className="flex-1 resize-none text-xs text-gray-800 placeholder-gray-400 outline-none bg-gray-50 rounded-xl px-3 py-2"
                  rows={2}
                />
                <button
                  onClick={() => handleSubmit()}
                  disabled={!question.trim() || mutation.isPending}
                  className={cn(
                    "self-end px-4 py-2 rounded-xl text-xs font-medium",
                    question.trim() ? "bg-teal-500 text-white hover:bg-teal-600" : "bg-gray-100 text-gray-400 cursor-not-allowed",
                  )}
                >
                  Ask
                </button>
              </div>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
