"use client";
// The call page's "QA Score" card: total, criteria (click to expand evidence), correction, strengths / growth areas.
import { useState } from "react";
import { ChevronDown, ChevronRight, CheckCircle2, AlertCircle, Copy } from "@/lib/icons";
import { cn } from "@/lib/utils";
import { ScoreRing } from "@/components/calls/ScoreRing";
import { CorrectScore } from "@/components/calls/CorrectScore";

export interface CriterionScore {
  criterion: string;
  id?: string;
  name?: string | null;
  method?: string | null;
  overridden?: boolean;
  score: number;
  max_score: number;
  evidence: string;
  evidence_spans?: { start: number; end: number; label?: string; sentiment?: "positive" | "negative" | "neutral" }[];
}

export interface QaScore {
  score_id?: string;
  is_overridden?: boolean;
  override_reason?: string | null;
  total_score: number;
  max_score: number;
  confidence: number;
  criteria: CriterionScore[];
  summary?: string;
  agent_strengths?: string[];
  agent_growth_areas?: string[];
  missed_revenue?: number;
  suggested_disposition?: string;
  next_action?: string;
  ai_summary?: string;
}

export function QaScoreCard({ score, canCorrect, onCorrected }: { score: QaScore; canCorrect: boolean; onCorrected: () => void }) {
  const [showAllCriteria, setShowAllCriteria] = useState(false);
  // Several criteria can be open at once
  const [expandedCriteria, setExpandedCriteria] = useState<Set<number>>(new Set());
  const criteria = score.criteria ?? [];
  const visibleCriteria = showAllCriteria ? criteria : criteria.slice(0, 5);
  const strengths = score.agent_strengths ?? [];
  const growth = score.agent_growth_areas ?? [];

  return (
  <div className="haip-card p-5">
  <div className="flex items-center gap-4 mb-5">
  <ScoreRing score={(score.total_score / score.max_score) * 100} size={72} />
  <div>
  <h2 className="text-sm font-semibold text-[var(--haip-fg)]">QA Score</h2>
  <p className="text-2xl font-black text-[var(--haip-fg)] mt-0.5">
  {score.total_score}
  <span className="text-base font-normal text-[var(--haip-fg-subtle)]">/{score.max_score}</span>
  </p>
  {score.confidence > 0 && (
  <p className="text-xs text-[var(--haip-fg-subtle)] mt-0.5">
  Confidence: {Math.round(score.confidence * 100)}%
  </p>
  )}
  </div>
  </div>

  {/* Criteria breakdown: click to expand evidence */}
  <div className="space-y-2">
  {visibleCriteria.map((c, i) => {
  const pct = Math.min(100, Math.round((c.score / c.max_score) * 100));
  const isExpanded = expandedCriteria.has(i);
  return (
  <div key={i} className="rounded-xl border border-[var(--haip-border)] overflow-hidden">
  <button
  className="w-full text-left px-3 py-2 flex items-center gap-2 hover:bg-[var(--haip-surface)] transition-colors"
  onClick={() => setExpandedCriteria(prev => {
  const next = new Set(prev);
  isExpanded ? next.delete(i) : next.add(i);
  return next;
  })}
  >
  {isExpanded
  ? <ChevronDown size={12} className="text-[var(--haip-fg-subtle)] flex-shrink-0" />
  : <ChevronRight size={12} className="text-[var(--haip-fg-subtle)] flex-shrink-0" />}
  <span className="text-xs text-[var(--haip-fg-2)] font-medium capitalize flex-1">{(c.name ?? c.criterion).replace(/_/g, " ")}{c.overridden ? " · corrected" : ""}</span>
  <span className="text-xs text-[var(--haip-fg-subtle)] font-mono flex-shrink-0">{c.score}/{c.max_score}</span>
  </button>
  <div className="px-3 pb-2">
  <div className="h-1.5 bg-[var(--haip-surface)] rounded-full overflow-hidden mb-1">
  <div
  className={cn("h-full rounded-full", pct >= 80 ? "bg-primary" : pct >= 50 ? "bg-[var(--haip-accent)]" : "bg-[var(--haip-status-danger-fg)]")}
  style={{ width: `${pct}%` }}
  />
  </div>
  {/* Collapsed: one-line preview */}
  {c.evidence && !isExpanded && (
  <p className="text-[11px] text-[var(--haip-fg-subtle)] italic line-clamp-1">{c.evidence}</p>
  )}
  </div>
  {/* Expanded: full evidence + copy */}
  {isExpanded && c.evidence && (
  <div className="px-3 pb-3 border-t border-[var(--haip-border)] pt-2">
  <div className="flex items-start justify-between gap-2">
  <p className="text-xs text-[var(--haip-fg-2)] leading-relaxed flex-1">{c.evidence}</p>
  <button
  onClick={() => navigator.clipboard.writeText(c.evidence)}
  title="Copy evidence"
  className="text-[var(--haip-fg-subtle)] hover:text-[var(--haip-fg)] transition-colors flex-shrink-0"
  >
  <Copy size={12} />
  </button>
  </div>
  </div>
  )}
  </div>
  );
  })}
  </div>

  {criteria.length > 5 && (
  <button
  onClick={() => setShowAllCriteria(v => !v)}
  className="mt-3 text-xs text-primary hover:text-primary font-medium flex items-center gap-1"
  >
  {showAllCriteria ? "Show less" : `+${criteria.length - 5} more criteria`}
  <ChevronDown size={12} className={cn("transition-transform", showAllCriteria && "rotate-180")} />
  </button>
  )}

  {score.is_overridden && (
  <p className="mt-3 text-[11px] text-[var(--haip-fg-subtle)]">Corrected by a person{score.override_reason ? `: ${score.override_reason}` : ""}</p>
  )}
  {score.score_id && canCorrect && (
  <CorrectScore scoreId={score.score_id} criteria={criteria} onDone={onCorrected} />
  )}

  {/* Strengths & growth areas */}
  {(strengths.length > 0 || growth.length > 0) && (
  <div className="mt-4 pt-4 border-t border-[var(--haip-border)] grid grid-cols-2 gap-3">
  {strengths.length > 0 && (
  <div>
  <p className="text-[11.5px] font-bold uppercase tracking-wider text-primary mb-1.5">Strengths</p>
  <ul className="space-y-1">
  {strengths.slice(0, 3).map((s, i) => (
  <li key={i} className="text-xs text-[var(--haip-fg-2)] flex items-start gap-1.5">
  <CheckCircle2 size={11} className="text-primary mt-0.5 flex-shrink-0" /> {s}
  </li>
  ))}
  </ul>
  </div>
  )}
  {growth.length > 0 && (
  <div>
  <p className="text-[11.5px] font-bold uppercase tracking-wider text-[var(--haip-status-warning-fg)] mb-1.5">Improve</p>
  <ul className="space-y-1">
  {growth.slice(0, 3).map((s, i) => (
  <li key={i} className="text-xs text-[var(--haip-fg-2)] flex items-start gap-1.5">
  <AlertCircle size={11} className="text-[var(--haip-accent-ink)] mt-0.5 flex-shrink-0" /> {s}
  </li>
  ))}
  </ul>
  </div>
  )}
  </div>
  )}
  </div>
  );
}
