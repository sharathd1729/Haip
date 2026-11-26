"use client";
// Recent calls made with one API key (last 100) and how many in the last 7 days (backend api_usage_service).
import { useQuery } from "@tanstack/react-query";
import api from "@/lib/api";
import { cn } from "@/lib/utils";
import { Skeleton } from "@/components/ui/skeleton";

interface Usage {
  calls_7d: number;
  recent: { method: string; path: string; status: number; duration_ms: number; at: string | null }[];
}

const tone = (status: number) =>
  status < 300 ? "text-[var(--haip-status-success-fg)]" : status < 500 ? "text-[var(--haip-status-warning-fg)]" : "text-[var(--haip-status-danger-fg)]";

export function ApiKeyUsage({ keyId }: { keyId: string }) {
  const { data, isLoading, isError, refetch } = useQuery<Usage>({
    queryKey: ["api-key-usage", keyId],
    queryFn: () => api.get(`/api-keys/${keyId}/usage`).then(r => r.data),
  });
  if (isLoading) return <Skeleton className="h-16 rounded-lg" />;
  if (isError || !data) {
    return (
      <p className="text-xs text-[var(--haip-status-danger-fg)]">
        Could not load the calls. <button type="button" onClick={() => refetch()} className="min-h-9 font-semibold underline">Try again</button>
      </p>
    );
  }
  return (
    <div className="space-y-2">
      <p className="text-xs text-[var(--haip-fg-2)]">
        <b>{data.calls_7d.toLocaleString("en-IN")}</b> call{data.calls_7d === 1 ? "" : "s"} in the last 7 days
        <span className="text-[var(--haip-fg-subtle)]"> · calls are kept for 30 days</span>
      </p>
      {data.recent.length === 0 ? (
        <p className="text-xs text-[var(--haip-fg-subtle)]">No calls with this key yet. They show here a few seconds after your software uses it.</p>
      ) : (
        <ul className="max-h-72 overflow-y-auto divide-y divide-[var(--haip-border)] text-xs">
          {data.recent.map((c, i) => (
            <li key={i} className="py-1.5 flex items-center gap-2 min-w-0">
              <span className="w-12 shrink-0 font-mono font-semibold text-[var(--haip-fg-2)]">{c.method}</span>
              <span className="min-w-0 flex-1 truncate font-mono text-[var(--haip-fg-2)]" title={c.path}>{c.path}</span>
              <span className={cn("shrink-0 font-semibold", tone(c.status))}>{c.status}</span>
              <span className="hidden sm:inline shrink-0 text-[var(--haip-fg-subtle)]">{c.duration_ms} ms</span>
              <span className="shrink-0 whitespace-nowrap text-[var(--haip-fg-subtle)]">
                {c.at ? new Date(c.at).toLocaleString("en-IN", { day: "numeric", month: "short", hour: "numeric", minute: "2-digit", timeZone: "Asia/Kolkata" }) : ""}
              </span>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
