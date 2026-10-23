"use client";
import { useCallback, useEffect, useState } from "react";
import { ValidityBadge } from "@/components/leads/ValidityBadge";
import dynamic from "next/dynamic";
import { useRouter } from "next/navigation";
import { useSession } from "next-auth/react";
import { useInfiniteQuery, useIsFetching, useQueryClient } from "@tanstack/react-query";
import { RefreshCw, Settings2, ChevronDown, Plus } from "@/lib/icons";
import { UserCheck } from "lucide-react";
import api from "@/lib/api";
import { CAME_FROM_LABEL, LEAD_TYPE_LABEL, LeadCard, type LeadCard as LeadCardType } from "@/components/leads/LeadCard";
import { groupLeads, LEAD_GROUP_LABEL } from "@/components/leads/leadGroups";
import { SkeletonCard } from "@/components/ui/SkeletonCard";
import { cn, formatINR } from "@/lib/utils";
import { DataTable, PageHeader, StatusPill, type Column } from "@/components/ui/kit";
import { usePipelineStages, type PipelineStageRow } from "@/hooks/usePipelineStages";
import { LeadsFilterBar, type LeadsFilters } from "@/components/leads/LeadsFilterBar";
import { NeedsActionView } from "@/components/leads/NeedsActionView";

// B5: only needed once the user opens pipeline settings -- keep it out of
// this route's initial chunk.
const PipelineSettingsModal = dynamic(
  () => import("@/components/leads/PipelineSettingsModal").then(m => m.PipelineSettingsModal),
  { ssr: false }
);
const AddLeadModal = dynamic(
  () => import("@/components/leads/AddLeadModal").then(m => m.AddLeadModal),
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
  /** Whose leads: "team" (owner/manager) or "mine_and_unassigned" (every other role) -- the one visibility rule. */
  scope?: "team" | "mine_and_unassigned";
}

const SCOPE_LABEL = { team: "Showing: whole team", mine_and_unassigned: "Showing: your leads + unassigned" } as const;

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

function useStageLeads(stageKey: string, filters: LeadsFilters, onStagesMeta: (meta: Record<string, StageMetaEntry>, scope?: LeadsApiPage["scope"]) => void) {
  const query = useInfiniteQuery({
    queryKey: ["leads", "stage", stageKey, filters],
    queryFn: ({ pageParam }) => fetchStageLeads(stageKey, filters, pageParam),
    initialPageParam: 1,
    getNextPageParam: (lastPage) => {
      const loaded = lastPage.page * lastPage.page_size;
      return loaded < lastPage.total ? lastPage.page + 1 : undefined;
    },
    refetchInterval: 30_000,
    // Changes made on another device (a stage, an owner, a source) must show up when this one is picked up again: the app-wide
    // default turns these off, which left a phone showing an old board after returning to the tab.
    refetchOnWindowFocus: true,
    refetchOnReconnect: true,
    staleTime: 10_000,
  });

  const lastPage = query.data?.pages[query.data.pages.length - 1];

  // Bubble the stage summary up to the parent (header total, badge counts on
  // the other pills) in an effect, not during render -- calling a parent's
  // setState directly from a child's render body trips React's "Cannot
  // update a component while rendering a different component" warning.
  useEffect(() => {
    if (lastPage) onStagesMeta(lastPage.stages, lastPage.scope);
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
      className="lx-col flex-shrink-0 w-[264px] flex flex-col"
      style={{ background: "var(--haip-card)" }}
    >
      {/* Column header — stage-color bar + tinted count badge, driven by
          the tenant's own pipeline_stages.color, not a fixed dot. */}
      <div className="flex items-start gap-2.5 px-2.5 pt-2.5 pb-3 flex-shrink-0">
        <span className="lx-col-bar" style={{ background: stage.color }} />
        <div className="flex-1 min-w-0">
          <div className="flex items-center justify-between gap-2">
            <span
              className="text-[12px] font-bold uppercase tracking-[0.06em] truncate"
              style={{ color: "var(--haip-fg)" }}
            >
              {stage.label}
            </span>
            <span
              className="rounded-full px-2 py-0.5 text-[11px] font-bold tabular-nums flex-shrink-0"
              style={{
                background: `color-mix(in srgb, ${stage.color} 15%, transparent)`,
                color: stage.color,
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
      </div>

      {/* Cards scroll area */}
      <div
        className="flex-1 overflow-y-auto px-0.5 pb-1 space-y-2 haip-scrollbar"
        style={{ maxHeight: "calc(100dvh - 180px)" }}
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
      <div className="mb-3 flex items-center justify-between gap-2">
        <div className="flex min-w-0 items-center gap-2">
          {/* The stage's own colour is tenant data (pipeline settings), so it stays a runtime value. */}
          <span className="size-2.5 flex-shrink-0 rounded-full" style={{ background: stage.color }} />
          <span className="truncate font-[family-name:var(--font-display)] text-[17px] font-semibold text-[var(--haip-fg)]">{stage.label}</span>
          <span className="num flex-shrink-0 rounded-full bg-[var(--haip-status-neutral-bg)] px-2 py-0.5 text-[12px] font-semibold text-[var(--haip-fg-muted)]">{count}</span>
        </div>
        {revenue > 0 && (
          <p className="num flex-shrink-0 text-[12.5px] text-[var(--haip-fg-subtle)]">₹{Number(revenue).toLocaleString("en-IN")}</p>
        )}
      </div>
      {isLoading ? (
        <SkeletonCard />
      ) : leads.length === 0 ? (
        <div className="flex items-center justify-center rounded-2xl bg-[var(--haip-status-neutral-bg)] py-8 text-[13.5px] text-[var(--haip-fg-subtle)]">
          No leads in this stage
        </div>
      ) : (
        <div className="space-y-4">
          {/* Grouped by what to do next (Act now / Today / Later); within a group the server's order stands. */}
          {groupLeads(leads).map(group => (
            <section key={group.key} aria-label={`${LEAD_GROUP_LABEL[group.key]}, ${group.leads.length}`}>
              <h3 className={cn("mb-2 flex items-center gap-2 px-0.5 text-[13px] font-semibold",
                group.key === "now" ? "text-[var(--haip-status-danger-fg)]" : "text-[var(--haip-fg-muted)]")}>
                {group.key === "now" && <span className="size-2 rounded-full bg-[var(--haip-status-danger-fg)]" aria-hidden />}
                {LEAD_GROUP_LABEL[group.key]}
                <span className="num font-medium text-[var(--haip-fg-subtle)]">{group.leads.length}</span>
              </h3>
              <div className="space-y-2">{group.leads.map(lead => <LeadCard key={lead.inquiry_id} lead={lead} />)}</div>
            </section>
          ))}
          {hasNextPage && (
            <button
              onClick={() => fetchNextPage()}
              disabled={isFetchingNextPage}
              className="flex min-h-11 w-full items-center justify-center gap-1.5 rounded-xl border border-[var(--haip-border)] bg-[var(--haip-card)] text-[13.5px] font-semibold text-[var(--haip-fg-muted)] transition-colors duration-150 disabled:opacity-50"
            >
              <ChevronDown size={14} className={isFetchingNextPage ? "animate-spin" : ""} />
              {isFetchingNextPage ? "Loading…" : `Load more (${count - leads.length} left)`}
            </button>
          )}
        </div>
      )}
    </div>
  );
}

// ─── Triage strip ─────────────────────────────────────────────────────────────

function TriageStrip({
  stages, counts, activeKey, onOpen, onBack,
}: {
  stages: PipelineStageRow[];
  counts: Record<string, StageMetaEntry>;
  activeKey: string;
  onOpen: (key: string) => void;
  onBack: () => void;
}) {
  const viewing = stages.find(st => st.key === activeKey);
  return (
    <div
      className="flex-shrink-0 flex items-center gap-2 px-4 sm:px-5 py-2 overflow-x-auto haip-scrollbar-x"
      style={{ borderBottom: "1px solid var(--haip-border)" }}
    >
      <span className="text-xs font-bold flex-shrink-0" style={{ color: "var(--haip-fg)" }}>Triage</span>
      <span className="hidden sm:inline text-xs flex-shrink-0" style={{ color: "var(--haip-fg-subtle)" }}>
        {viewing ? `Reviewing ${viewing.label}` : "Not on the board"}
      </span>
      {stages.map(st => {
        const active = st.key === activeKey;
        const n = counts[st.key]?.count;
        return (
          <button
            key={st.key}
            onClick={() => onOpen(st.key)}
            className="flex-shrink-0 text-[11px] font-semibold px-2.5 py-1 rounded-full transition-colors"
            style={active
              ? { background: st.color, color: "#fff" }
              : { background: `color-mix(in srgb, ${st.color} 12%, transparent)`, color: st.color }}
          >
            {st.label}{n != null ? ` · ${n.toLocaleString("en-IN")}` : ""}
          </button>
        );
      })}
      {viewing && (
        <button
          onClick={onBack}
          className="flex-shrink-0 ml-auto text-xs font-semibold"
          style={{ color: "var(--primary)" }}
        >
          ← Back to board
        </button>
      )}
    </div>
  );
}

// ─── Table layout ─────────────────────────────────────────────────────────────
// Same per-stage queries as the board, shown as one table per stage. Rows open the lead.

function agoShort(iso?: string): string {
  if (!iso) return "—";
  const m = Math.round((Date.now() - new Date(iso).getTime()) / 60000);
  if (m < 60) return `${Math.max(1, m)}m ago`;
  const h = Math.floor(m / 60);
  return h < 24 ? `${h}h ago` : `${Math.floor(h / 24)}d ago`;
}

function fmtShortDate(iso?: string): string {
  if (!iso) return "—";
  return new Date(iso.length <= 10 ? `${iso}T00:00:00` : iso).toLocaleDateString("en-IN", { day: "numeric", month: "short" });
}

const LEAD_COLUMNS: Column<LeadCardType>[] = [
  {
    key: "lead", header: "Lead",
    cell: l => (
      <div className="min-w-0">
        <p className="truncate font-semibold text-[var(--haip-fg)]">{l.display_name}</p>
        <p className="truncate text-xs text-[var(--haip-fg-subtle)]">
          {[l.primary_channel, l.occasion].filter(Boolean).join(" · ") || "No details yet"}
        </p>
      </div>
    ),
  },
  { key: "checkin", header: "Check-in", hideBelow: "sm", cell: l => fmtShortDate(l.check_in) },
  {
    key: "budget", header: "Budget", align: "right", hideBelow: "md",
    cell: l => {
      const v = l.quoted_amount || l.budget_estimate;
      return v ? formatINR(v) : <span className="text-[var(--haip-fg-subtle)]">—</span>;
    },
  },
  { key: "owner", header: "Owner", hideBelow: "lg", cell: l => l.assigned_agent_name ?? <span className="text-[var(--haip-fg-subtle)]">Unassigned</span> },
  {
    key: "type", header: "Type", hideBelow: "md",
    cell: l => (
      <span className="grid text-xs">
        <span className="text-[var(--haip-fg)]">{LEAD_TYPE_LABEL[l.lead_type || "guest"] ?? l.lead_type}</span>
        <span className="text-[var(--haip-fg-subtle)]">{CAME_FROM_LABEL[l.came_from || "unknown"]}</span>
        <ValidityBadge validity={l.validity} />
      </span>
    ),
  },
  {
    key: "wait", header: "Reply", hideBelow: "sm",
    cell: l => l.sla_breached
      ? <StatusPill tone="danger">SLA breached</StatusPill>
      : l.response_time_status === "waiting"
        ? <StatusPill tone="warning">Waiting</StatusPill>
        : <span className="text-[var(--haip-fg-subtle)]">—</span>,
  },
  { key: "touch", header: "Last touch", align: "right", cell: l => <span className="text-[var(--haip-fg-subtle)]">{agoShort(l.last_touch_at)}</span> },
];

function StageTable({
  stage, filters, onStagesMeta,
}: {
  stage: PipelineStageRow; filters: LeadsFilters;
  onStagesMeta: (meta: Record<string, StageMetaEntry>) => void;
}) {
  const router = useRouter();
  const { leads, isLoading, isError, refetch, isFetchingNextPage, hasNextPage, fetchNextPage, data } =
    useStageLeads(stage.key, filters, onStagesMeta);
  const count = data?.pages[0]?.stages[stage.key]?.count ?? leads.length;

  return (
    <section className="space-y-2">
      <h2 className="flex items-center gap-2 text-[12px] font-bold uppercase tracking-[0.06em] text-[var(--haip-fg)]">
        <span className="size-2.5 rounded-full" style={{ background: stage.color }} aria-hidden />
        {stage.label}
        <span className="text-[11px] font-semibold tabular-nums text-[var(--haip-fg-subtle)]">{count}</span>
      </h2>
      <DataTable<LeadCardType>
        columns={LEAD_COLUMNS} rows={leads} rowKey={l => l.inquiry_id}
        loading={isLoading} error={isError ? "Could not load this stage." : null} onRetry={() => refetch()}
        empty={{ title: `Nothing in ${stage.label}`, hint: "Leads that reach this stage appear here." }}
        onRowClick={l => router.push(`/dashboard/leads/${l.inquiry_id}`)}
        maxHeightClass="max-h-[60vh]"
      />
      {hasNextPage && (
        <button onClick={() => fetchNextPage()} disabled={isFetchingNextPage}
          className="h-9 rounded-lg border border-[var(--haip-border)] bg-[var(--haip-card)] px-4 text-xs font-semibold text-[var(--haip-fg-2)] hover:bg-[var(--haip-surface)] disabled:opacity-50">
          {isFetchingNextPage ? "Loading…" : "Load more"}
        </button>
      )}
    </section>
  );
}

// ─── Page ─────────────────────────────────────────────────────────────────────

type LeadsView = "action" | "pipeline";

export default function Leads360Page() {
  // The pipeline is the default for every role ("Needs action" is one tab away). The last choice is remembered on this
  // device; it is read after mount so the first render matches the server.
  const [view, setViewState] = useState<LeadsView>("pipeline");
  useEffect(() => {
    try { if (localStorage.getItem("haip_leads_view") === "action") setViewState("action"); } catch { /* storage unavailable */ }
  }, []);
  const setView = (v: LeadsView) => {
    setViewState(v);
    try { localStorage.setItem("haip_leads_view", v); } catch { /* ignore */ }
  };
  const [stageFilter, setStageFilter] = useState(ALL_STAGES_ID);
  // Board (columns) or Table (rows grouped by stage). Remembered on this device.
  const [layout, setLayout] = useState<"board" | "table">("board");
  useEffect(() => {
    try { if (localStorage.getItem("haip_leads_layout") === "table") setLayout("table"); } catch { /* storage unavailable */ }
  }, []);
  const chooseLayout = (l: "board" | "table") => {
    setLayout(l);
    try { localStorage.setItem("haip_leads_layout", l); } catch { /* ignore */ }
  };
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [addLeadOpen, setAddLeadOpen] = useState(false);
  const [filters, setFilters] = useState<LeadsFilters>({});
  const [stageMeta, setStageMeta] = useState<Record<string, StageMetaEntry>>({});
  const [scope, setScope] = useState<LeadsApiPage["scope"]>(undefined);
  const queryClient = useQueryClient();
  const { data: session } = useSession();
  const currentUserId = session?.user?.id;
  const assignedToMe = !!currentUserId && filters.assigned_to === currentUserId;

  const { data: pipelineStages = [] } = usePipelineStages();

  // A specific stage pill narrows which column(s) render (and therefore
  // fetch) at all, on both desktop and mobile -- previously desktop always
  // rendered every column regardless of the pill (only mobile narrowed),
  // which meant picking a stage silently emptied every other desktop column
  // instead of hiding them.
  // Triage: stages the tenant itself marked as not-a-real-lead (category
  // "invalid" or "marketing" -- the same rule dashboards use for lead
  // counts) stay off the board. On Ratha that's Unqualified / RNR /
  // Collaboration, ~1,300 enquiries that buried the few dozen real leads.
  // Still one click away: a triage chip opens that stage as its own column.
  const isTriage = (s: PipelineStageRow) => s.category === "invalid" || s.category === "marketing";
  const boardStages = pipelineStages.filter(s => !isTriage(s));
  const triageStages = pipelineStages.filter(isTriage);

  const columnsToRender = stageFilter === ALL_STAGES_ID
    ? boardStages
    : pipelineStages.filter(s => s.key === stageFilter);

  // Every column's response carries the same full per-stage summary
  // (leads_service._build_stage_summary isn't scoped to the `stage` filter),
  // so any one of them keeps this accurate -- merged rather than replaced
  // since columns resolve at different times.
  const handleStagesMeta = useCallback((meta: Record<string, StageMetaEntry>, s?: LeadsApiPage["scope"]) => {
    if (s) setScope(s);
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
    ? boardStages.reduce((sum, st) => sum + (stageMeta[st.key]?.count ?? 0), 0)
    : stageMeta[stageFilter]?.count ?? 0;

  const isFetching = useIsFetching({ queryKey: ["leads"] }) > 0;
  const refetchAll = () => queryClient.invalidateQueries({ queryKey: ["leads"] });

  return (
    <div className="haip-leads-v2 flex flex-col h-full overflow-hidden">

      {/* ── Page header ─────────────────────────────────────────────────── */}
      {/* Title and controls (stage pills + Add Lead/Settings/Refresh) stack
          on mobile -- forced onto one row, the stage-pill scroller crowded
          the title with almost no breathing room at 375px. */}
      <div
        className="flex-shrink-0 flex flex-col gap-1.5 sm:gap-2.5 sm:flex-row sm:items-center sm:justify-between px-3 py-2 sm:px-5 sm:py-3.5"
        style={{
          background: "var(--haip-card)",
          borderBottom: "1px solid var(--haip-border)",
        }}
      >
        {/* Title */}
        {/* On a phone the top bar already names the page, so the title (and its description) only show from sm up */}
        <PageHeader className="hidden sm:flex" title="Leads360"
          subtitle={view === "action" ? "What to do next, most urgent first" : `${total} lead${total === 1 ? "" : "s"} on the board${stageFilter === ALL_STAGES_ID ? "" : " in this stage"}${scope ? ` · ${SCOPE_LABEL[scope]}` : ""}`} />

        {/* Controls: wrap on narrow screens instead of running off the edge */}
        <div className="flex flex-wrap items-center gap-2">
          <div role="tablist" aria-label="Leads view" className="order-1 sm:order-none flex flex-shrink-0 rounded-lg p-0.5" style={{ background: "var(--muted)" }}>
            {([["action", "Needs action"], ["pipeline", "Pipeline"]] as const).map(([key, label]) => (
              <button
                key={key}
                role="tab"
                aria-selected={view === key}
                onClick={() => setView(key)}
                className="text-xs font-semibold px-3 min-h-11 sm:min-h-0 sm:py-1.5 rounded-md transition-colors"
                style={view === key
                  ? { background: "var(--haip-card)", color: "var(--haip-fg)", boxShadow: "0 1px 2px rgb(0 0 0 / 0.06)" }
                  : { color: "var(--haip-fg-subtle)" }}
              >
                {label}
              </button>
            ))}
          </div>

          {view === "pipeline" && (<>
          <div role="group" aria-label="Layout" className={cn("order-5 sm:order-none flex-shrink-0 rounded-lg p-0.5", layout === "board" ? "hidden md:flex" : "flex")} style={{ background: "var(--muted)" }}>
            {(["board", "table"] as const).map(l => (
              <button key={l} type="button" aria-pressed={layout === l} onClick={() => chooseLayout(l)}
                className={cn("rounded-md px-3 min-h-11 sm:min-h-0 sm:py-1.5 text-xs font-semibold capitalize transition-colors",
                  layout === l ? "bg-[var(--haip-card)] text-[var(--haip-fg)] shadow-sm" : "text-[var(--haip-fg-subtle)]")}>
                {l}
              </button>
            ))}
          </div>
          {/* Stage filter pills — scrollable on mobile */}
          <div className="order-6 flex w-full items-center gap-1 overflow-x-auto haip-scrollbar-x pb-0.5 sm:order-none sm:w-auto sm:max-w-md">
            <button
              onClick={() => setStageFilter(ALL_STAGES_ID)}
              className="lx-stage-pill flex-shrink-0 text-xs px-3 min-h-11 lg:min-h-0 lg:py-1 lg:text-[10px] transition-colors duration-150"
              style={
                stageFilter === ALL_STAGES_ID
                  ? { background: "var(--lx-iris)", color: "#fff" }
                  : { background: "transparent", border: "1.5px solid var(--haip-border)", color: "var(--haip-fg-subtle)" }
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
                  className="lx-stage-pill flex-shrink-0 text-xs px-3 min-h-11 lg:min-h-0 lg:py-1 lg:text-[10px] transition-colors duration-150"
                  style={
                    active
                      ? { background: `color-mix(in srgb, ${s.color} 18%, transparent)`, color: s.color, border: `1.5px solid ${s.color}` }
                      : { background: "transparent", border: "1.5px solid var(--haip-border)", color: "var(--haip-fg-subtle)" }
                  }
                >
                  {s.label}{cnt ? ` · ${cnt}` : ""}
                </button>
              );
            })}
          {/* Assign-to-me visibility fix: one-click "mine" toggle, same
              quick-filter-chip idiom as ConversationList.tsx's "Assigned to
              Me" in the Inbox -- previously the only way to see your own
              leads here was LeadsFilterBar's full assigned_to dropdown,
              which requires finding your own name in the whole team list. */}
          {currentUserId && (
            <button
              onClick={() => setFilters(f => ({ ...f, assigned_to: assignedToMe ? undefined : currentUserId }))}
              className="lx-stage-pill flex-shrink-0 flex items-center gap-1 text-xs px-3 min-h-11 lg:min-h-0 lg:py-1 lg:text-[10px] transition-colors duration-150"
              style={
                assignedToMe
                  ? { background: "var(--lx-iris)", color: "#fff" }
                  : { background: "transparent", border: "1.5px solid var(--haip-border)", color: "var(--haip-fg-subtle)" }
              }
              title="Show only leads assigned to me"
            >
              <UserCheck size={11} />
              Assigned to me
            </button>
          )}
          </div>

          </>)}

          {/* Add lead manually */}
          <button
            onClick={() => setAddLeadOpen(true)}
            className="lx-btn-add order-2 sm:order-none flex items-center gap-1.5 text-xs font-semibold px-3 min-h-11 sm:min-h-0 sm:py-1.5 transition-colors duration-150"
            title="Add a lead manually"
          >
            <Plus size={12} />
            <span className="hidden sm:inline">Add Lead</span>
          </button>

          {/* Pipeline settings */}
          <button
            onClick={() => setSettingsOpen(true)}
            className="lx-icon-btn order-3 sm:order-none w-7 h-7 flex items-center justify-center border transition-colors duration-150"
            style={{ borderColor: "var(--haip-border)", color: "var(--haip-fg-subtle)" }}
            title="Configure pipeline stages"
          >
            <Settings2 size={12} />
          </button>

          {/* Refresh */}
          <button
            onClick={refetchAll}
            className="lx-icon-btn order-4 sm:order-none w-7 h-7 flex items-center justify-center border transition-colors duration-150"
            style={{ borderColor: "var(--haip-border)", color: isFetching ? "var(--lx-iris)" : "var(--haip-fg-subtle)" }}
            title="Refresh"
          >
            <RefreshCw size={12} className={isFetching ? "animate-spin" : ""} />
          </button>
        </div>
      </div>

      {view === "action" && (
        <NeedsActionView
          onOpenPipeline={f => { setFilters(f); setStageFilter(ALL_STAGES_ID); setView("pipeline"); }}
        />
      )}

      {view === "pipeline" && (<>
      <LeadsFilterBar filters={filters} onChange={setFilters} />

      {triageStages.length > 0 && (
        <TriageStrip
          stages={triageStages}
          counts={stageMeta}
          activeKey={stageFilter}
          onOpen={setStageFilter}
          onBack={() => setStageFilter(ALL_STAGES_ID)}
        />
      )}

      {/* ── Table layout ────────────────────────────────────────────────── */}
      {layout === "table" && (
        <div className="flex-1 space-y-6 overflow-y-auto p-4 sm:p-6">
          {columnsToRender.map(stage => (
            <StageTable key={stage.key} stage={stage} filters={filters} onStagesMeta={handleStagesMeta} />
          ))}
        </div>
      )}

      {/* ── Kanban board (desktop) ──────────────────────────────────────── */}
      <div className={cn("hidden flex-1 overflow-x-auto overflow-y-hidden", layout === "board" && "md:block")}>
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

      {/* ── Stage slider (mobile) — sideways-scrolling sub-300px Kanban
          columns are unusable on a phone, but stacking every stage
          vertically (the previous approach) meant scrolling through the
          entire pipeline just to see "Sold". This is a real swipeable
          slider instead: one stage fills the screen at a time, snap-
          scrolling horizontally between them. The stage-filter pills
          above still work exactly as before (narrow columnsToRender to
          one stage, which just makes this a single-slide view). ─────── */}
      <div className={cn("flex-1 flex overflow-x-auto overflow-y-hidden snap-x snap-mandatory haip-scrollbar-x md:hidden", layout === "table" && "!hidden")}>
        {columnsToRender.map(stage => (
          <div
            key={stage.key}
            className="w-full flex-shrink-0 snap-center overflow-y-auto haip-scrollbar px-3 py-3"
          >
            <MobileStageSection
              stage={stage}
              filters={filters}
              onStagesMeta={handleStagesMeta}
            />
          </div>
        ))}
      </div>

      </>)}

      {/* ── Pipeline settings modal ──────────────────────────────────────── */}
      {settingsOpen && (
        <PipelineSettingsModal
          stages={pipelineStages}
          onClose={() => setSettingsOpen(false)}
        />
      )}

      {/* ── Add lead modal ──────────────────────────────────────────────── */}
      {addLeadOpen && (
        <AddLeadModal
          onClose={() => setAddLeadOpen(false)}
          onCreated={() => setAddLeadOpen(false)}
        />
      )}
    </div>
  );
}
