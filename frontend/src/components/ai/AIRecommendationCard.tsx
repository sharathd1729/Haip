"use client";
import { useState } from "react";
import { Sparkles, Check, Loader2, AlertCircle } from "@/lib/icons";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import api from "@/lib/api";
import { useToast } from "@/components/ui/toast";

/**
 * One AI recommendation, with its suggested actions executable in a click.
 *
 * Shared by every surface that shows AI output — Leads360 cards, Calls
 * intelligence, Guest Journey, Ask HAIP findings — so a recommendation looks
 * and behaves the same everywhere instead of each page growing its own card.
 *
 * Every action posts to POST /automations/actions/execute, which runs it
 * through the same shared dispatcher automation rules and the Flow Builder
 * use, and writes an audit row naming the user who clicked.
 */

export interface EntityRefs {
  guest_id?: string;
  inquiry_id?: string;
  call_id?: string;
  property_id?: string;
}

export interface RecommendedAction {
  /** Must be in the backend's ONE_CLICK_ACTIONS allowlist. */
  action_type: string;
  label: string;
  action_config?: Record<string, unknown>;
  /** Outbound/irreversible actions ask for confirmation before firing. */
  confirm?: boolean;
}

interface Props {
  title: string;
  summary: string;
  entityRefs: EntityRefs;
  actions?: RecommendedAction[];
  /** Where this recommendation came from — recorded on the audit row. */
  source?: string;
  confidence?: number;
  /** Query keys to refetch after a successful action. */
  invalidateKeys?: string[][];
}

export function AIRecommendationCard({
  title,
  summary,
  entityRefs,
  actions = [],
  source,
  confidence,
  invalidateKeys = [],
}: Props) {
  const { toast } = useToast();
  const qc = useQueryClient();
  const [done, setDone] = useState<Record<string, boolean>>({});
  const [pending, setPending] = useState<string | null>(null);
  const [error, setError] = useState("");

  const execute = useMutation({
    mutationFn: async (action: RecommendedAction) => {
      const res = await api.post("/automations/actions/execute", {
        action_type: action.action_type,
        entity_refs: entityRefs,
        action_config: action.action_config ?? {},
        source,
      });
      return res.data;
    },
    onSuccess: (data, action) => {
      setDone((d) => ({ ...d, [action.action_type]: true }));
      setPending(null);
      toast({ title: action.label, description: data.detail ?? "Done" });
      invalidateKeys.forEach((key) => qc.invalidateQueries({ queryKey: key }));
    },
    onError: (err: unknown, action) => {
      setPending(null);
      const detail =
        (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail ??
        `Couldn't ${action.label.toLowerCase()}`;
      setError(detail);
      toast({ title: "Action failed", description: detail });
    },
  });

  function run(action: RecommendedAction) {
    setError("");
    if (action.confirm && !window.confirm(`${action.label}?\n\nThis will be sent right away.`)) {
      return;
    }
    setPending(action.action_type);
    execute.mutate(action);
  }

  return (
    <div className="rounded-xl border border-border bg-card p-4">
      <div className="flex items-start gap-2">
        <Sparkles className="mt-0.5 h-4 w-4 shrink-0 text-primary" aria-hidden />
        <div className="min-w-0 flex-1">
          <div className="flex items-baseline gap-2">
            <h3 className="text-sm font-semibold text-foreground">{title}</h3>
            {typeof confidence === "number" && (
              <span className="text-xs text-muted-foreground">
                {Math.round(confidence * 100)}% confidence
              </span>
            )}
          </div>
          <p className="mt-1 text-sm leading-relaxed text-muted-foreground">{summary}</p>

          {actions.length > 0 && (
            <div className="mt-3 flex flex-wrap gap-2">
              {actions.map((action) => {
                const isDone = done[action.action_type];
                const isPending = pending === action.action_type;
                return (
                  <button
                    key={action.action_type}
                    type="button"
                    onClick={() => run(action)}
                    disabled={isPending || isDone}
                    className="inline-flex items-center gap-1.5 rounded-lg border border-border px-3 py-1.5 text-xs font-medium text-foreground transition-colors hover:bg-accent disabled:opacity-60"
                  >
                    {isPending ? (
                      <Loader2 className="h-3.5 w-3.5 animate-spin" aria-hidden />
                    ) : isDone ? (
                      <Check className="h-3.5 w-3.5 text-primary" aria-hidden />
                    ) : null}
                    {isDone ? "Done" : action.label}
                  </button>
                );
              })}
            </div>
          )}

          {error && (
            <p className="mt-2 flex items-center gap-1.5 text-xs text-destructive">
              <AlertCircle className="h-3.5 w-3.5" aria-hidden />
              {error}
            </p>
          )}
        </div>
      </div>
    </div>
  );
}

export default AIRecommendationCard;
