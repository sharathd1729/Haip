"use client";
import { useState } from "react";
import { Lock, BarChart2, RefreshCw } from "@/lib/icons";
import { cn } from "@/lib/utils";
import type { WidgetSnapshot } from "@/hooks/useDashboardWidgets";
import api from "@/lib/api";

interface Props {
  snap: WidgetSnapshot;
  onRefresh?: (key: string, fresh: WidgetSnapshot) => void;
}

export function WidgetShell({ snap, onRefresh }: Props) {
  const [refreshing, setRefreshing] = useState(false);

  async function handleRefresh() {
    if (refreshing) return;
    setRefreshing(true);
    try {
      const res = await api.post("/dashboard/widgets/refresh", null, {
        params: { widget_key: snap.key },
      });
      onRefresh?.(snap.key, res.data);
    } catch {
      // silently ignore — rate limit or network
    } finally {
      setRefreshing(false);
    }
  }

  const genAt = snap.generated_at
    ? new Date(snap.generated_at).toLocaleTimeString("en-IN", {
        hour: "2-digit",
        minute: "2-digit",
      })
    : null;

  return (
    <div
      className="haip-card relative flex flex-col overflow-hidden"
      style={{ minHeight: 180, maxHeight: 280 }}
    >
      {/* Header */}
      <div
        className="flex items-center justify-between px-4 pt-3 pb-2 flex-shrink-0"
        style={{ borderBottom: "1px solid var(--haip-border)" }}
      >
        <div className="min-w-0">
          <p className="text-xs font-semibold truncate" style={{ color: "var(--haip-fg)" }}>
            {snap.title}
          </p>
          {snap.summary && snap.state === "full_insight" && (
            <p className="text-[10px] mt-0.5 truncate" style={{ color: "var(--haip-fg-subtle)" }}>
              {snap.summary}
            </p>
          )}
        </div>
        <div className="flex items-center gap-1.5 flex-shrink-0">
          {genAt && (
            <span className="text-[9px]" style={{ color: "var(--haip-fg-subtle)" }} title="Last updated">
              {genAt}
            </span>
          )}
          {snap.state !== "unavailable" && (
            <button
              onClick={handleRefresh}
              disabled={refreshing}
              className="w-5 h-5 flex items-center justify-center rounded"
              style={{ color: "var(--haip-fg-subtle)" }}
              title="Refresh widget"
            >
              <RefreshCw size={10} className={refreshing ? "animate-spin" : ""} />
            </button>
          )}
        </div>
      </div>

      {/* Body */}
      <div className="flex-1 overflow-hidden relative">
        {snap.state === "unavailable" && <UnavailableState />}
        {snap.state === "early_signal" && <EarlySignalState summary={snap.summary} />}
        {snap.state === "full_insight" && (
          <WidgetContent widgetKey={snap.key} data={snap.data} />
        )}
      </div>
    </div>
  );
}

function UnavailableState() {
  return (
    <div className="flex flex-col items-center justify-center h-full gap-2 px-4 py-6">
      <Lock size={18} style={{ color: "var(--haip-fg-subtle)" }} />
      <p className="text-[11px] text-center" style={{ color: "var(--haip-fg-subtle)" }}>
        Connect the required module to unlock this insight.
      </p>
    </div>
  );
}

function EarlySignalState({ summary }: { summary: string | null }) {
  return (
    <div className="flex flex-col items-center justify-center h-full gap-2 px-4 py-6">
      <BarChart2 size={18} style={{ color: "var(--haip-fg-subtle)", opacity: 0.5 }} />
      <p className="text-[11px] text-center" style={{ color: "var(--haip-fg-subtle)" }}>
        {summary ?? "Gathering data — check back soon."}
      </p>
    </div>
  );
}

// Lazy widget renderer — resolves key → component. Exported so other
// surfaces (e.g. the custom dashboard builder) can render the same real
// charts without dragging in this shell's own header/refresh chrome.
export function WidgetContent({
  widgetKey,
  data,
}: {
  widgetKey: string;
  data: Record<string, unknown> | null;
}) {
  const Component = WIDGET_COMPONENTS[widgetKey];
  if (!Component || !data) {
    return (
      <div className="flex items-center justify-center w-full h-full">
        <p className="text-[11px]" style={{ color: "var(--haip-fg-subtle)" }}>
          No data available.
        </p>
      </div>
    );
  }
  return (
    <div className="w-full h-full overflow-hidden px-3 py-2">
      {/* eslint-disable-next-line @typescript-eslint/no-explicit-any */}
      <Component data={data as any} />
    </div>
  );
}

// ─── Lazy widget map (imported below) ─────────────────────────────────────────

import { CallVolumeWidget }         from "./widgets/CallVolumeWidget";
import { SentimentWidget }          from "./widgets/SentimentWidget";
import { MissedRevenueWidget }      from "./widgets/MissedRevenueWidget";
import { ObjectionsWidget }         from "./widgets/ObjectionsWidget";
import { IntentMixWidget }          from "./widgets/IntentMixWidget";
import { ResponseTimeWidget }       from "./widgets/ResponseTimeWidget";
import { AgentLeaderboardWidget }   from "./widgets/AgentLeaderboardWidget";
import { InquiryFunnelWidget }      from "./widgets/InquiryFunnelWidget";
import { LeadVsConversationWidget } from "./widgets/LeadVsConversationWidget";
import { ChannelMixWidget }         from "./widgets/ChannelMixWidget";
import { AttributionWidget }        from "./widgets/AttributionWidget";
import { CampaignPerformanceWidget }from "./widgets/CampaignPerformanceWidget";
import { GuestLtvWidget }           from "./widgets/GuestLtvWidget";
import { OccupancyForecastWidget }  from "./widgets/OccupancyForecastWidget";
import { RevenueForecastWidget }    from "./widgets/RevenueForecastWidget";
import { PricingWidget }            from "./widgets/PricingWidget";
import { ChurnRiskWidget }          from "./widgets/ChurnRiskWidget";
import { CohortsWidget }            from "./widgets/CohortsWidget";
import { AiRecommendationsWidget }  from "./widgets/AiRecommendationsWidget";

// eslint-disable-next-line @typescript-eslint/no-explicit-any
const WIDGET_COMPONENTS: Record<string, React.ComponentType<{ data: any }>> = {
  call_volume:          CallVolumeWidget,
  sentiment:            SentimentWidget,
  missed_revenue:       MissedRevenueWidget,
  objections:           ObjectionsWidget,
  intent_mix:           IntentMixWidget,
  response_time:        ResponseTimeWidget,
  agent_leaderboard:    AgentLeaderboardWidget,
  inquiry_funnel:       InquiryFunnelWidget,
  lead_vs_conversation: LeadVsConversationWidget,
  channel_mix:          ChannelMixWidget,
  attribution:          AttributionWidget,
  campaign_performance: CampaignPerformanceWidget,
  guest_ltv:            GuestLtvWidget,
  occupancy_forecast:   OccupancyForecastWidget,
  revenue_forecast:     RevenueForecastWidget,
  pricing:              PricingWidget,
  churn_risk:           ChurnRiskWidget,
  cohorts:              CohortsWidget,
  ai_recommendations:   AiRecommendationsWidget,
};
