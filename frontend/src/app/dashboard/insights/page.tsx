"use client";

import { AIInsightsPanel } from "@/components/analytics/AIInsightsPanel";

// AI Insights feed reactivated 2026-08-15 as its own module ("ai_insights",
// migration 075) -- a standalone live feed of AI-generated recommendations
// and alerts, decoupled from the still-deactivated "analytics" module.
// AIInsightsPanel itself is unchanged (already fully self-contained: own
// react-query fetch + dismiss mutation) -- previously only mounted on the
// now-redirected /dashboard/analytics/* pages, so it existed but was
// unreachable in the live app.
export default function InsightsPage() {
  return (
    <div className="h-full flex flex-col">
      <div className="px-6 py-5 bg-white border-b border-gray-100 flex-shrink-0">
        <h1 className="haip-page-title">AI Insights</h1>
        <p className="text-sm text-gray-400 mt-0.5">
          Live recommendations and alerts, generated from what's happening across your leads, calls, and messages right now.
        </p>
      </div>
      <div className="flex-1 overflow-y-auto p-6">
        <div className="max-w-2xl">
          <AIInsightsPanel />
        </div>
      </div>
    </div>
  );
}
