"use client";

/**
 * O2 — Sample data banner.
 *
 * Shown across all dashboard pages when is_sample data is present.
 * Renders as a slim strip just below the status bar.
 * Provides one-click wipe.
 */

import { useState } from "react";
import { FlaskConical, X, ArrowRight } from "lucide-react";
import Link from "next/link";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import api from "@/lib/api";

interface SampleStatus {
  has_sample: boolean;
  counts: { guests?: number; conversations?: number; calls?: number };
}

export function SampleDataBanner() {
  const [dismissed, setDismissed] = useState(false);
  const queryClient = useQueryClient();

  const { data } = useQuery<SampleStatus>({
    queryKey: ["sample-data-status"],
    queryFn: () => api.get("/sample-data/status").then(r => r.data),
    staleTime: 60_000,
    refetchOnWindowFocus: false,
  });

  const wipeMutation = useMutation({
    mutationFn: () => api.post("/sample-data/wipe"),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["sample-data-status"] });
      queryClient.invalidateQueries({ queryKey: ["conversations"] });
      queryClient.invalidateQueries({ queryKey: ["calls"] });
      queryClient.invalidateQueries({ queryKey: ["guests"] });
    },
  });

  if (!data?.has_sample || dismissed) return null;

  return (
    <div className="flex items-center gap-3 px-4 py-2 flex-shrink-0 text-xs" style={{
      backgroundColor: "rgba(245,158,11,0.08)",
      borderBottom: "1px solid rgba(245,158,11,0.15)",
    }}>
      <FlaskConical size={13} className="text-amber-400 flex-shrink-0" />
      <p className="flex-1 text-amber-300/70">
        <span className="font-semibold text-amber-300">You&apos;re viewing sample data</span>
        {" "}—{" "}
        Connect WhatsApp to see real guest conversations
      </p>
      <div className="flex items-center gap-3 flex-shrink-0">
        <Link
          href="/dashboard/settings/integrations"
          className="flex items-center gap-1 text-amber-400 hover:text-amber-300 font-semibold transition-colors"
        >
          Connect <ArrowRight size={11} />
        </Link>
        <button
          onClick={() => wipeMutation.mutate()}
          disabled={wipeMutation.isPending}
          className="text-amber-400/50 hover:text-amber-300 transition-colors font-medium"
        >
          {wipeMutation.isPending ? "Wiping…" : "Wipe sample data"}
        </button>
        <button
          onClick={() => setDismissed(true)}
          className="text-amber-400/40 hover:text-amber-300 transition-colors"
          title="Dismiss"
        >
          <X size={12} />
        </button>
      </div>
    </div>
  );
}
