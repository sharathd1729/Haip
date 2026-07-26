"use client";

import { useState, useCallback, useRef } from "react";
import { useParams, useRouter } from "next/navigation";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
// eslint-disable-next-line @typescript-eslint/no-require-imports
const ReactGridLayout = require("react-grid-layout").default ?? require("react-grid-layout");
import "react-grid-layout/css/styles.css";
import "react-resizable/css/styles.css";

type Layout = { i: string; x: number; y: number; w: number; h: number };
import api from "@/lib/api";
import { useWorkspace } from "@/components/providers/WorkspaceProvider";
import {
  ArrowLeft, Plus, Lock, AlertCircle, Loader2, X, GripVertical, Settings2,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import {
  Sheet, SheetContent, SheetHeader, SheetTitle,
} from "@/components/ui/sheet";
import { Badge } from "@/components/ui/badge";
import { WidgetContent } from "@/components/dashboard/WidgetShell";

// ── Types ─────────────────────────────────────────────────────────────────────

interface WidgetInstance {
  id: string;
  widget_key: string;
  widget_name: string;
  widget_type: string;
  category: string;
  title?: string;
  position: { lg?: { col: number; row: number; w: number; h: number } };
  state: "module_required" | "flag_disabled" | "early_signal" | "full_insight";
  required_modules: string[];
  cached_data?: unknown;
}

interface DashboardSnapshot {
  id: string;
  name: string;
  description?: string;
  layout_config: Record<string, Layout[]>;
  date_range_default: string;
  widgets: WidgetInstance[];
  active_modules: string[];
}

interface WidgetCatalogEntry {
  key: string;
  name: string;
  description?: string;
  category: string;
  widget_type: string;
  available: boolean;
  missing_modules: string[];
}

const COLS = { lg: 12, md: 8, sm: 4, xs: 2 };
const BREAKPOINTS = { lg: 1200, md: 1024, sm: 768, xs: 0 };

const STATE_BADGE: Record<string, { label: string; className: string }> = {
  module_required: { label: "Upgrade required", className: "bg-amber-50 text-amber-700 border-amber-200" },
  flag_disabled:   { label: "Feature disabled", className: "bg-gray-50 text-gray-500 border-gray-200" },
  early_signal:    { label: "Gathering data",   className: "bg-blue-50 text-blue-600 border-blue-200" },
  full_insight:    { label: "Live",             className: "bg-green-50 text-green-700 border-green-200" },
};

// ── Page ─────────────────────────────────────────────────────────────────────

export default function DashboardBuilderPage() {
  const { id } = useParams<{ id: string }>();
  const router = useRouter();
  const qc = useQueryClient();
  const workspace = useWorkspace();
  const [widgetLibraryOpen, setWidgetLibraryOpen] = useState(false);
  const [currentBp] = useState<"lg">("lg");
  const [selectedWidgets, setSelectedWidgets] = useState<Set<string>>(new Set());
  const addingRef = useRef(false);

  // Load snapshot
  const { data: snapshot, isLoading } = useQuery({
    queryKey: ["dashboard-snapshot", id],
    queryFn: () => api.get(`/dashboards/${id}/snapshot`).then((r) => r.data as DashboardSnapshot),
  });

  // Widget catalogue
  const { data: catalogData } = useQuery({
    queryKey: ["widget-registry"],
    queryFn: () => api.get("/widgets/registry").then((r) => r.data as { widgets: WidgetCatalogEntry[] }),
    enabled: widgetLibraryOpen,
  });

  // Save layout on drag/resize
  const saveLayout = useMutation({
    mutationFn: (layout: Layout[]) =>
      api.patch(`/dashboards/${id}`, {
        layout_config: {
          ...snapshot?.layout_config,
          [currentBp]: layout,
        },
      }),
  });

  // Add widget
  const addWidget = useMutation({
    mutationFn: (widget_key: string) =>
      api.post(`/dashboards/${id}/widgets`, {
        widget_key,
        position: { lg: { col: 0, row: 999, w: 4, h: 3 } },
      }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["dashboard-snapshot", id] });
    },
  });

  const addSelectedWidgets = useCallback(async () => {
    if (addingRef.current || selectedWidgets.size === 0) return;
    addingRef.current = true;
    for (const key of Array.from(selectedWidgets)) {
      await addWidget.mutateAsync(key);
    }
    addingRef.current = false;
    setSelectedWidgets(new Set());
    setWidgetLibraryOpen(false);
  }, [selectedWidgets, addWidget]);

  const toggleWidget = useCallback((key: string, available: boolean) => {
    if (!available) return;
    setSelectedWidgets((prev) => {
      const next = new Set(prev);
      if (next.has(key)) next.delete(key);
      else next.add(key);
      return next;
    });
  }, []);

  // Remove widget
  const removeWidget = useMutation({
    mutationFn: (widgetInstanceId: string) =>
      api.delete(`/dashboards/${id}/widgets/${widgetInstanceId}`),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["dashboard-snapshot", id] }),
  });

  const onLayoutChange = useCallback(
    (layout: Layout[]) => saveLayout.mutate(layout),
    [snapshot, saveLayout]
  );

  if (isLoading) {
    return (
      <div className="flex items-center justify-center h-64">
        <Loader2 className="w-6 h-6 animate-spin text-muted-foreground" />
      </div>
    );
  }

  if (!snapshot) {
    return (
      <div className="p-6 text-center">
        <p className="text-muted-foreground">Dashboard not found.</p>
        <Button variant="link" onClick={() => router.push("/dashboard/dashboards")}>
          Back to dashboards
        </Button>
      </div>
    );
  }

  // Convert widget positions to react-grid-layout format
  const layout: Layout[] = snapshot.widgets.map((w) => {
    const pos = w.position?.lg ?? { col: 0, row: 0, w: 4, h: 3 };
    return { i: w.id, x: pos.col ?? 0, y: pos.row ?? 0, w: pos.w ?? 4, h: pos.h ?? 3 };
  });

  const widgetMap = Object.fromEntries(snapshot.widgets.map((w) => [w.id, w]));

  const categories = Array.from(
    new Set((catalogData?.widgets ?? []).map((w) => w.category))
  ).filter(Boolean);

  return (
    <div className="flex flex-col h-full">
      {/* Toolbar */}
      <div className="flex items-center gap-3 px-6 py-3 border-b bg-background/80 backdrop-blur-sm sticky top-0 z-10">
        <button
          onClick={() => router.push("/dashboard/dashboards")}
          className="p-1.5 rounded hover:bg-muted transition-colors"
        >
          <ArrowLeft className="w-4 h-4" />
        </button>
        <h1 className="font-semibold flex-1 truncate">{snapshot.name}</h1>
        {snapshot.description && (
          <span className="text-sm text-muted-foreground hidden md:block truncate max-w-xs">
            {snapshot.description}
          </span>
        )}
        <Button size="sm" className="gap-1.5" onClick={() => setWidgetLibraryOpen(true)}>
          <Plus className="w-3.5 h-3.5" />
          Add Widget
        </Button>
      </div>

      {/* Grid */}
      <div className="flex-1 overflow-y-auto p-4">
        {snapshot.widgets.length === 0 ? (
          <div className="flex flex-col items-center justify-center h-64 border-2 border-dashed rounded-xl gap-3">
            <Settings2 className="w-10 h-10 text-muted-foreground" />
            <p className="font-medium text-muted-foreground">Empty dashboard</p>
            <p className="text-sm text-muted-foreground">Click Add Widget to get started</p>
            <Button onClick={() => setWidgetLibraryOpen(true)} className="gap-2">
              <Plus className="w-4 h-4" />
              Add Widget
            </Button>
          </div>
        ) : (
          <ReactGridLayout
            className="layout"
            layout={layout}
            cols={COLS.lg}
            rowHeight={80}
            width={1200}
            onLayoutChange={onLayoutChange}
            draggableHandle=".drag-handle"
            margin={[12, 12]}
          >
            {layout.map(({ i }: Layout) => {
              const widget = widgetMap[i];
              if (!widget) return null;
              const stateInfo = STATE_BADGE[widget.state] ?? STATE_BADGE.full_insight;
              return (
                <div key={i} className="border rounded-xl bg-card shadow-sm overflow-hidden flex flex-col">
                  {/* Widget header */}
                  <div className="flex items-center gap-2 px-3 py-2 border-b bg-muted/30">
                    <span className="drag-handle cursor-grab text-muted-foreground">
                      <GripVertical className="w-4 h-4" />
                    </span>
                    <span className="font-medium text-sm flex-1 truncate">
                      {widget.title || widget.widget_name}
                    </span>
                    <span className={`text-xs px-1.5 py-0.5 rounded border ${stateInfo.className}`}>
                      {stateInfo.label}
                    </span>
                    <button
                      onClick={() => removeWidget.mutate(widget.id)}
                      className="p-0.5 hover:text-destructive transition-colors"
                    >
                      <X className="w-3.5 h-3.5" />
                    </button>
                  </div>

                  {/* Widget body */}
                  <div className="flex-1 p-3 flex items-center justify-center">
                    <WidgetBody widget={widget} />
                  </div>
                </div>
              );
            })}
          </ReactGridLayout>
        )}
      </div>

      {/* Widget library sheet */}
      <Sheet open={widgetLibraryOpen} onOpenChange={(open) => {
        if (!open) setSelectedWidgets(new Set());
        setWidgetLibraryOpen(open);
      }}>
        <SheetContent side="right" className="w-96 flex flex-col p-0">
          <SheetHeader className="px-5 pt-5 pb-3 border-b">
            <SheetTitle>Widget Library</SheetTitle>
            <p className="text-xs text-muted-foreground">Select widgets to add to your dashboard</p>
          </SheetHeader>

          {/* Scrollable list */}
          <div className="flex-1 overflow-y-auto px-5 py-4 space-y-6">
            {categories.map((cat) => {
              const catWidgets = (catalogData?.widgets ?? []).filter((w) => w.category === cat);
              return (
                <div key={cat}>
                  <h3 className="text-xs font-semibold text-muted-foreground uppercase tracking-wider mb-2 capitalize">
                    {cat}
                  </h3>
                  <div className="space-y-2">
                    {catWidgets.map((w) => {
                      const selected = selectedWidgets.has(w.key);
                      return (
                        <button
                          key={w.key}
                          disabled={!w.available}
                          onClick={() => toggleWidget(w.key, w.available)}
                          className={[
                            "w-full flex items-start gap-3 p-3 border rounded-lg text-left transition-colors",
                            w.available
                              ? selected
                                ? "border-primary bg-primary/5 hover:bg-primary/10"
                                : "hover:bg-muted/50"
                              : "opacity-50 cursor-not-allowed",
                          ].join(" ")}
                        >
                          {/* Checkbox indicator */}
                          <span className={[
                            "mt-0.5 flex-shrink-0 w-4 h-4 rounded border flex items-center justify-center transition-colors",
                            selected ? "bg-primary border-primary" : "border-muted-foreground/40",
                          ].join(" ")}>
                            {selected && (
                              <svg className="w-2.5 h-2.5 text-primary-foreground" viewBox="0 0 10 8" fill="none">
                                <path d="M1 4l3 3 5-6" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />
                              </svg>
                            )}
                          </span>

                          <div className="flex-1 min-w-0">
                            <p className="text-sm font-medium">{w.name}</p>
                            {w.description && (
                              <p className="text-xs text-muted-foreground mt-0.5 line-clamp-2">{w.description}</p>
                            )}
                            {!w.available && w.missing_modules.length > 0 && (
                              <p className="text-xs text-amber-600 mt-1 flex items-center gap-1">
                                <Lock className="w-3 h-3" />
                                Requires: {w.missing_modules.join(", ")}
                              </p>
                            )}
                          </div>
                        </button>
                      );
                    })}
                  </div>
                </div>
              );
            })}
            {!catalogData && (
              <div className="flex justify-center py-8">
                <Loader2 className="w-5 h-5 animate-spin text-muted-foreground" />
              </div>
            )}
          </div>

          {/* Sticky footer */}
          <div className="border-t px-5 py-4 bg-background">
            <Button
              className="w-full gap-2"
              disabled={selectedWidgets.size === 0 || addWidget.isPending}
              onClick={addSelectedWidgets}
            >
              {addWidget.isPending ? (
                <Loader2 className="w-4 h-4 animate-spin" />
              ) : (
                <Plus className="w-4 h-4" />
              )}
              {selectedWidgets.size === 0
                ? "Select widgets above"
                : `Add ${selectedWidgets.size} widget${selectedWidgets.size > 1 ? "s" : ""}`}
            </Button>
          </div>
        </SheetContent>
      </Sheet>
    </div>
  );
}

// ── Widget body — renders state-appropriate content ───────────────────────────

function WidgetBody({ widget }: { widget: WidgetInstance }) {
  if (widget.state === "module_required") {
    return (
      <div className="text-center text-xs text-amber-600 space-y-1">
        <Lock className="w-5 h-5 mx-auto" />
        <p>Requires module upgrade</p>
        <p className="text-muted-foreground">{widget.required_modules.join(", ")}</p>
      </div>
    );
  }
  if (widget.state === "flag_disabled") {
    return (
      <div className="text-center text-xs text-muted-foreground space-y-1">
        <AlertCircle className="w-5 h-5 mx-auto" />
        <p>Feature not enabled</p>
      </div>
    );
  }
  if (widget.state === "early_signal") {
    return (
      <div className="text-center text-xs text-blue-600 space-y-1">
        <Loader2 className="w-5 h-5 mx-auto animate-spin" />
        <p>Gathering data…</p>
      </div>
    );
  }
  // full_insight — render the real chart, same component the main dashboard uses
  return (
    <WidgetContent
      widgetKey={widget.widget_key}
      data={(widget.cached_data as Record<string, unknown> | null) ?? null}
    />
  );
}
