"use client";
import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Target, RefreshCw, Settings2 } from "lucide-react";
import api from "@/lib/api";
import { LeadCard, type LeadCard as LeadCardType } from "@/components/leads/LeadCard";
import { SkeletonCard } from "@/components/ui/SkeletonCard";
import { cn } from "@/lib/utils";
import { usePipelineStages, type PipelineStageRow } from "@/hooks/usePipelineStages";
import { PipelineSettingsModal } from "@/components/leads/PipelineSettingsModal";

const ALL_STAGES_ID = "__all__";

// ─── Fetch ────────────────────────────────────────────────────────────────────

async function fetchLeads(stage?: string, page = 1) {
  const params: Record<string, string | number> = { page, page_size: 50 };
  if (stage && stage !== ALL_STAGES_ID) params.stage = stage;
  const res = await api.get("/leads", { params });
  return res.data;
}

// ─── Stage column ─────────────────────────────────────────────────────────────

function StageColumn({
  stage,
  leads,
  meta,
  loading,
}: {
  stage: PipelineStageRow;
  leads: LeadCardType[];
  meta?: { count: number; potential_revenue: number };
  loading: boolean;
}) {
  const count = meta?.count ?? leads.length;
  const revenue = meta?.potential_revenue ?? 0;

  return (
    <div
      className="flex-shrink-0 w-[264px] flex flex-col rounded-xl"
      style={{ background: "var(--muted)", opacity: 1 }}
    >
      {/* Column header */}
      <div className="px-3 pt-3 pb-2.5 flex-shrink-0">
        <div className="flex items-center justify-between gap-2">
          <div className="flex items-center gap-1.5 min-w-0">
            <span
              className="w-2 h-2 rounded-full flex-shrink-0"
              style={{ background: stage.color }}
            />
            <span className="text-xs font-medium truncate" style={{ color: "var(--haip-fg)" }}>
              {stage.label}
            </span>
          </div>
          <span
            className="rounded-full px-2 py-0.5 text-[10px] font-medium tabular-nums flex-shrink-0"
            style={{ background: "var(--haip-border)", color: "var(--haip-fg-subtle)" }}
          >
            {count}
          </span>
        </div>
        {revenue > 0 && (
          <p className="text-[10px] mt-0.5" style={{ color: "var(--haip-fg-subtle)" }}>
            ₹{Number(revenue).toLocaleString("en-IN")} potential
          </p>
        )}
      </div>

      {/* Cards scroll area */}
      <div
        className="flex-1 overflow-y-auto px-2 pb-3 space-y-2 haip-scrollbar"
        style={{ maxHeight: "calc(100vh - 180px)" }}
      >
        {loading ? (
          <SkeletonCard />
        ) : leads.length === 0 ? (
          <div
            className="flex items-center justify-center py-10 text-[11px]"
            style={{ color: "var(--haip-fg-subtle)" }}
          >
            No leads here
          </div>
        ) : (
          leads.map(lead => <LeadCard key={lead.inquiry_id} lead={lead} />)
        )}
      </div>
    </div>
  );
}

// ─── Page ─────────────────────────────────────────────────────────────────────

export default function Leads360Page() {
  const [stageFilter, setStageFilter] = useState(ALL_STAGES_ID);
  const [settingsOpen, setSettingsOpen] = useState(false);

  const { data: pipelineStages = [] } = usePipelineStages();
  const visibleStages = pipelineStages;

  const { data, isLoading, refetch, isFetching } = useQuery({
    queryKey: ["leads", stageFilter],
    queryFn: () => fetchLeads(stageFilter),
    refetchInterval: 30_000,
  });

  const leads: LeadCardType[] = data?.leads ?? [];
  const stageMeta: Record<string, { count: number; potential_revenue: number }> = data?.stages ?? {};
  const total: number = data?.total ?? 0;

  // Group by stage — map legacy values
  const leadsByStage: Record<string, LeadCardType[]> = {};
  for (const s of visibleStages) leadsByStage[s.key] = [];
  for (const lead of leads) {
    const s = lead.inquiry_stage;
    if (leadsByStage[s] !== undefined) {
      leadsByStage[s].push(lead);
    } else {
      const mapped =
        s === "site_visit" ? "site_visit_scheduled"
        : s === "lost" || s === "ghosted" ? "closed"
        : s;
      if (leadsByStage[mapped] !== undefined) leadsByStage[mapped].push(lead);
    }
  }

  return (
    <div className="flex flex-col h-full overflow-hidden bg-background">

      {/* ── Page header ─────────────────────────────────────────────────── */}
      <div
        className="flex-shrink-0 flex items-center justify-between px-5 py-3.5"
        style={{ borderBottom: "1px solid var(--haip-border)" }}
      >
        {/* Title */}
        <div className="flex items-center gap-2.5">
          <Target size={16} style={{ color: "var(--primary)" }} />
          <div>
            <h1 className="text-xl font-semibold tracking-tight" style={{ color: "var(--haip-fg)" }}>
              Leads360
            </h1>
            <p className="text-xs" style={{ color: "var(--haip-fg-subtle)" }}>
              {total} active leads
            </p>
          </div>
        </div>

        {/* Controls */}
        <div className="flex items-center gap-2">
          {/* Stage filter pills — scrollable on mobile */}
          <div className="flex items-center gap-1 overflow-x-auto haip-scrollbar-x pb-0.5 max-w-xs sm:max-w-md">
            <button
              onClick={() => setStageFilter(ALL_STAGES_ID)}
              className={cn(
                "flex-shrink-0 text-[10px] font-medium px-2.5 py-1 rounded-full transition-colors duration-150",
                stageFilter === ALL_STAGES_ID
                  ? "text-primary-foreground"
                  : "border hover:border-border",
              )}
              style={
                stageFilter === ALL_STAGES_ID
                  ? { background: "var(--primary)", color: "var(--primary-foreground)" }
                  : { background: "transparent", borderColor: "var(--haip-border)", color: "var(--haip-fg-subtle)" }
              }
            >
              All
            </button>
            {visibleStages.map(s => {
              const active = stageFilter === s.key;
              const cnt = stageMeta[s.key]?.count;
              return (
                <button
                  key={s.key}
                  onClick={() => setStageFilter(s.key)}
                  className="flex-shrink-0 text-[10px] font-medium px-2.5 py-1 rounded-full border transition-colors duration-150"
                  style={
                    active
                      ? { background: "var(--primary)", color: "var(--primary-foreground)", borderColor: "var(--primary)" }
                      : { background: "transparent", borderColor: "var(--haip-border)", color: "var(--haip-fg-subtle)" }
                  }
                >
                  {s.label}{cnt ? ` · ${cnt}` : ""}
                </button>
              );
            })}
          </div>

          {/* Pipeline settings */}
          <button
            onClick={() => setSettingsOpen(true)}
            className="w-7 h-7 flex items-center justify-center rounded-lg border transition-colors duration-150"
            style={{ borderColor: "var(--haip-border)", color: "var(--haip-fg-subtle)" }}
            title="Configure pipeline stages"
          >
            <Settings2 size={12} />
          </button>

          {/* Refresh */}
          <button
            onClick={() => refetch()}
            className="w-7 h-7 flex items-center justify-center rounded-lg border transition-colors duration-150"
            style={{ borderColor: "var(--haip-border)", color: isFetching ? "var(--primary)" : "var(--haip-fg-subtle)" }}
            title="Refresh"
          >
            <RefreshCw size={12} className={isFetching ? "animate-spin" : ""} />
          </button>
        </div>
      </div>

      {/* ── Kanban board ─────────────────────────────────────────────────── */}
      <div className="flex-1 overflow-x-auto overflow-y-hidden">
        <div className="flex gap-3 p-4 h-full" style={{ minWidth: "max-content" }}>
          {visibleStages.map(stage => (
            <StageColumn
              key={stage.key}
              stage={stage}
              leads={leadsByStage[stage.key] ?? []}
              meta={stageMeta[stage.key]}
              loading={isLoading}
            />
          ))}
        </div>
      </div>

      {/* ── Pipeline settings modal ──────────────────────────────────────── */}
      {settingsOpen && (
        <PipelineSettingsModal
          stages={pipelineStages}
          onClose={() => setSettingsOpen(false)}
        />
      )}
    </div>
  );
}
