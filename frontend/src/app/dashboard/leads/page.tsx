"use client";
import { useCallback, useEffect, useState } from "react";
import dynamic from "next/dynamic";
import { useInfiniteQuery, useIsFetching, useQueryClient } from "@tanstack/react-query";
import { Target, RefreshCw, Settings2, ChevronDown } from "lucide-react";
import api from "@/lib/api";
import { LeadCard, type LeadCard as LeadCardType } from "@/components/leads/LeadCard";
import { SkeletonCard } from "@/components/ui/SkeletonCard";
import { cn } from "@/lib/utils";
import { usePipelineStages, type PipelineStageRow } from "@/hooks/usePipelineStages";
import { LeadsFilterBar, type LeadsFilters } from "@/components/leads/LeadsFilterBar";

// B5: only needed once the user opens pipeline settings -- keep it out of
// this route's initial chunk.
const PipelineSettingsModal = dynamic(
  () => import("@/components/leads/PipelineSettingsModal").then(m => m.PipelineSettingsModal),
  { ssr: false }
);

const ALL_STAGES_ID = "__all__";
const LEADS_PAGE_SIZE = 30;

interface StageMetaEntry {
  count: number;
  potential_revenue: number;
}

interface LeadsApiPage {
  total: number;
  page: number;
  page_size: number;
  stages: Record<string, StageMetaEntry>;
  leads: LeadCardType[];
}

// ─── Fetch ────────────────────────────────────────────────────────────────────
// One bounded query PER stage column, not one big fetch for the whole board.
// The Kanban needs every visible column populated at once (client-side
// bucketing by stage_key doesn't work with a single flat page), which is why
// this used to request page_size=1000 in a single call -- against Ratha's
// real 683 inquiries that made the endpoint take >30s (see B8/leads_service's
// N+1 fix). Fetching each column separately, bounded and independently
// paginated, keeps every request small regardless of total pipeline size.
//
// The `stages` field in the response is a full count+revenue summary across
// ALL stages (see leads_service._build_stage_summary), not just the one this
// call filtered to -- so any one column's response carries everything the
// header/badges need; no separate aggregate endpoint required.

async function fetchStageLeads(stageKey: string, filters: LeadsFilters, page: number) {
  const params: Record<string, string | number> = {
    page, page_size: LEADS_PAGE_SIZE, stage: stageKey, ...filters,
  };
  const res = await api.get("/leads", { params });
  return res.data as LeadsApiPage;
}

function useStageLeads(stageKey: string, filters: LeadsFilters, onStagesMeta: (meta: Record<string, StageMetaEntry>) => void) {
  const query = useInfiniteQuery({
    queryKey: ["leads", "stage", stageKey, filters],
    queryFn: ({ pageParam }) => fetchStageLeads(stageKey, filters, pageParam),
    initialPageParam: 1,
    getNextPageParam: (lastPage) => {
      const loaded = lastPage.page * lastPage.page_size;
      return loaded < lastPage.total ? lastPage.page + 1 : undefined;
    },
    refetchInterval: 30_000,
  });

  const lastPage = query.data?.pages[query.data.pages.length - 1];

  // Bubble the stage summary up to the parent (header total, badge counts on
  // the other pills) in an effect, not during render -- calling a parent's
  // setState directly from a child's render body trips React's "Cannot
  // update a component while rendering a different component" warning.
  useEffect(() => {
    if (lastPage) onStagesMeta(lastPage.stages);
  }, [lastPage, onStagesMeta]);

  const leads = query.data?.pages.flatMap(p => p.leads) ?? [];
  return { leads, ...query };
}

// ─── Stage column ─────────────────────────────────────────────────────────────

function StageColumn({
  stage,
  filters,
  onStagesMeta,
}: {
  stage: PipelineStageRow;
  filters: LeadsFilters;
  onStagesMeta: (meta: Record<string, StageMetaEntry>) => void;
}) {
  const { leads, isLoading, isFetchingNextPage, hasNextPage, fetchNextPage, data } =
    useStageLeads(stage.key, filters, onStagesMeta);

  const meta = data?.pages[0]?.stages[stage.key];
  const count = meta?.count ?? leads.length;
  const revenue = meta?.potential_revenue ?? 0;

  return (
    <div
      className="flex-shrink-0 w-[264px] flex flex-col rounded-lg p-2.5"
      style={{ background: "var(--haip-surface)" }}
    >
      {/* Column header — uppercase name + white count pill over a 2px rule,
          per the prototype's .k-col-head / .k-col-name / .k-col-count */}
      <div
        className="px-1.5 pt-1 pb-2 mb-1 flex-shrink-0"
        style={{ borderBottom: "2px solid var(--haip-border)" }}
      >
        <div className="flex items-center justify-between gap-2">
          <div className="flex items-center gap-1.5 min-w-0">
            <span
              className="w-2 h-2 rounded-full flex-shrink-0"
              style={{ background: stage.color }}
            />
            <span
              className="text-[12px] font-bold uppercase tracking-[0.06em] truncate"
              style={{ color: "var(--haip-fg)" }}
            >
              {stage.label}
            </span>
          </div>
          <span
            className="rounded-full px-[7px] py-px text-[11px] font-semibold tabular-nums flex-shrink-0 border"
            style={{
              background: "var(--haip-card)",
              borderColor: "var(--haip-border)",
              color: "var(--haip-fg-muted)",
            }}
          >
            {count}
          </span>
        </div>
        {revenue > 0 && (
          <p className="text-[10px] mt-1" style={{ color: "var(--haip-fg-subtle)" }}>
            ₹{Number(revenue).toLocaleString("en-IN")} potential
          </p>
        )}
      </div>

      {/* Cards scroll area */}
      <div
        className="flex-1 overflow-y-auto px-0.5 pb-1 space-y-2 haip-scrollbar"
        style={{ maxHeight: "calc(100vh - 180px)" }}
      >
        {isLoading ? (
          <SkeletonCard />
        ) : leads.length === 0 ? (
          <div
            className="flex items-center justify-center py-10 text-[11px]"
            style={{ color: "var(--haip-fg-subtle)" }}
          >
            No leads here
          </div>
        ) : (
          <>
            {leads.map(lead => <LeadCard key={lead.inquiry_id} lead={lead} />)}
            {hasNextPage && (
              <button
                onClick={() => fetchNextPage()}
                disabled={isFetchingNextPage}
                className="w-full flex items-center justify-center gap-1 text-[10px] font-medium py-2 rounded-lg border transition-colors duration-150 disabled:opacity-50"
                style={{ borderColor: "var(--haip-border)", color: "var(--haip-fg-subtle)" }}
              >
                <ChevronDown size={11} className={isFetchingNextPage ? "animate-spin" : ""} />
                {isFetchingNextPage ? "Loading…" : `Load more (${count - leads.length} left)`}
              </button>
            )}
          </>
        )}
      </div>
    </div>
  );
}

// ─── Mobile stage section ──────────────────────────────────────────────────────

function MobileStageSection({
  stage,
  filters,
  onStagesMeta,
}: {
  stage: PipelineStageRow;
  filters: LeadsFilters;
  onStagesMeta: (meta: Record<string, StageMetaEntry>) => void;
}) {
  const { leads, isLoading, isFetchingNextPage, hasNextPage, fetchNextPage, data } =
    useStageLeads(stage.key, filters, onStagesMeta);

  const meta = data?.pages[0]?.stages[stage.key];
  const count = meta?.count ?? leads.length;
  const revenue = meta?.potential_revenue ?? 0;

  return (
    <div>
      <div className="flex items-center justify-between gap-2 mb-2">
        <div className="flex items-center gap-1.5 min-w-0">
          <span className="w-2 h-2 rounded-full flex-shrink-0" style={{ background: stage.color }} />
          <span className="text-sm font-semibold truncate" style={{ color: "var(--haip-fg)" }}>
            {stage.label}
          </span>
          <span
            className="rounded-full px-2 py-0.5 text-[10px] font-medium tabular-nums flex-shrink-0"
            style={{ background: "var(--muted)", color: "var(--haip-fg-subtle)" }}
          >
            {count}
          </span>
        </div>
        {revenue > 0 && (
          <p className="text-[10px] flex-shrink-0" style={{ color: "var(--haip-fg-subtle)" }}>
            ₹{Number(revenue).toLocaleString("en-IN")}
          </p>
        )}
      </div>
      {isLoading ? (
        <SkeletonCard />
      ) : leads.length === 0 ? (
        <div className="flex items-center justify-center py-6 text-[11px] rounded-xl" style={{ background: "var(--muted)", color: "var(--haip-fg-subtle)" }}>
          No leads here
        </div>
      ) : (
        <div className="space-y-2">
          {leads.map(lead => <LeadCard key={lead.inquiry_id} lead={lead} />)}
          {hasNextPage && (
            <button
              onClick={() => fetchNextPage()}
              disabled={isFetchingNextPage}
              className="w-full flex items-center justify-center gap-1 text-[11px] font-medium py-2.5 rounded-xl border transition-colors duration-150 disabled:opacity-50"
              style={{ borderColor: "var(--haip-border)", color: "var(--haip-fg-subtle)" }}
            >
              <ChevronDown size={12} className={isFetchingNextPage ? "animate-spin" : ""} />
              {isFetchingNextPage ? "Loading…" : `Load more (${count - leads.length} left)`}
            </button>
          )}
        </div>
      )}
    </div>
  );
}

// ─── Page ─────────────────────────────────────────────────────────────────────

export default function Leads360Page() {
  const [stageFilter, setStageFilter] = useState(ALL_STAGES_ID);
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [filters, setFilters] = useState<LeadsFilters>({});
  const [stageMeta, setStageMeta] = useState<Record<string, StageMetaEntry>>({});
  const queryClient = useQueryClient();

  const { data: pipelineStages = [] } = usePipelineStages();

  // A specific stage pill narrows which column(s) render (and therefore
  // fetch) at all, on both desktop and mobile -- previously desktop always
  // rendered every column regardless of the pill (only mobile narrowed),
  // which meant picking a stage silently emptied every other desktop column
  // instead of hiding them.
  const columnsToRender = stageFilter === ALL_STAGES_ID
    ? pipelineStages
    : pipelineStages.filter(s => s.key === stageFilter);

  // Every column's response carries the same full per-stage summary
  // (leads_service._build_stage_summary isn't scoped to the `stage` filter),
  // so any one of them keeps this accurate -- merged rather than replaced
  // since columns resolve at different times.
  const handleStagesMeta = useCallback((meta: Record<string, StageMetaEntry>) => {
    setStageMeta(prev => {
      // Skip the update if nothing actually changed, to avoid a render loop
      // (this runs on every render of every column while its query is warm).
      const same = Object.keys(meta).every(k =>
        prev[k]?.count === meta[k].count && prev[k]?.potential_revenue === meta[k].potential_revenue
      ) && Object.keys(prev).length === Object.keys(meta).length;
      return same ? prev : { ...prev, ...meta };
    });
  }, []);

  const total = stageFilter === ALL_STAGES_ID
    ? Object.values(stageMeta).reduce((sum, m) => sum + m.count, 0)
    : stageMeta[stageFilter]?.count ?? 0;

  const isFetching = useIsFetching({ queryKey: ["leads"] }) > 0;
  const refetchAll = () => queryClient.invalidateQueries({ queryKey: ["leads"] });

  return (
    <div className="flex flex-col h-full overflow-hidden">

      {/* ── Page header ─────────────────────────────────────────────────── */}
      <div
        className="flex-shrink-0 flex items-center justify-between px-5 py-3.5"
        style={{
          background: "var(--haip-card)",
          borderBottom: "1px solid var(--haip-border)",
        }}
      >
        {/* Title */}
        <div className="flex items-center gap-2.5">
          <Target size={16} style={{ color: "var(--primary)" }} />
          <div>
            <h1
              className="text-[22px] font-bold tracking-tight"
              style={{ color: "var(--haip-fg)", fontFamily: "var(--font-display), sans-serif" }}
            >
              Leads360
            </h1>
            <p className="text-xs" style={{ color: "var(--haip-fg-muted)" }}>
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
            {pipelineStages.map(s => {
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
            onClick={refetchAll}
            className="w-7 h-7 flex items-center justify-center rounded-lg border transition-colors duration-150"
            style={{ borderColor: "var(--haip-border)", color: isFetching ? "var(--primary)" : "var(--haip-fg-subtle)" }}
            title="Refresh"
          >
            <RefreshCw size={12} className={isFetching ? "animate-spin" : ""} />
          </button>
        </div>
      </div>

      <LeadsFilterBar filters={filters} onChange={setFilters} />

      {/* ── Kanban board (desktop) ──────────────────────────────────────── */}
      <div className="hidden md:block flex-1 overflow-x-auto overflow-y-hidden">
        <div className="flex gap-3 p-4 h-full" style={{ minWidth: "max-content" }}>
          {columnsToRender.map(stage => (
            <StageColumn
              key={stage.key}
              stage={stage}
              filters={filters}
              onStagesMeta={handleStagesMeta}
            />
          ))}
        </div>
      </div>

      {/* ── Stacked stage list (mobile) — sideways-scrolling sub-300px
          Kanban columns are unusable on a phone; the stage filter pills
          above already let you narrow to one stage, so this just stacks
          whichever stage(s) are visible vertically instead. ─────────── */}
      <div className="md:hidden flex-1 overflow-y-auto haip-scrollbar px-3 py-3 space-y-4">
        {columnsToRender.map(stage => (
          <MobileStageSection
            key={stage.key}
            stage={stage}
            filters={filters}
            onStagesMeta={handleStagesMeta}
          />
        ))}
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
