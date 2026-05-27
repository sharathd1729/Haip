"use client";

import { useState, useEffect, useCallback } from "react";
import { Gift, X, Tag, Calendar, ChevronRight, Sparkles } from "lucide-react";
import { cn } from "@/lib/utils";
import { useQuery } from "@tanstack/react-query";
import api from "@/lib/api";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

interface ChangelogItem {
  title: string;
  detail: string;
}

interface ChangelogEntry {
  slug: string;
  date: string;
  title: string;
  summary: string;
  version: string;
  tags: string[];
  items: ChangelogItem[];
}

interface ChangelogResponse {
  entries: ChangelogEntry[];
  latest_version: string;
  count: number;
}

// ---------------------------------------------------------------------------
// localStorage helpers
// ---------------------------------------------------------------------------

const LS_KEY = "changelog_last_seen";

function getLastSeen(): string {
  if (typeof window === "undefined") return "";
  return localStorage.getItem(LS_KEY) ?? "";
}

function markSeen(version: string) {
  if (typeof window === "undefined") return;
  localStorage.setItem(LS_KEY, version);
}

// ---------------------------------------------------------------------------
// Tag colour map
// ---------------------------------------------------------------------------

const TAG_COLORS: Record<string, string> = {
  inbox: "bg-blue-500/15 text-blue-300",
  calls: "bg-violet-500/15 text-violet-300",
  workflow: "bg-teal-500/15 text-teal-300",
  compliance: "bg-amber-500/15 text-amber-300",
  dpdp: "bg-orange-500/15 text-orange-300",
  meta: "bg-blue-400/15 text-blue-300",
  onboarding: "bg-green-500/15 text-green-300",
  ux: "bg-pink-500/15 text-pink-300",
};

function TagBadge({ tag }: { tag: string }) {
  const cls = TAG_COLORS[tag] ?? "bg-white/8 text-white/40";
  return (
    <span className={cn("text-[9px] font-bold uppercase tracking-wider px-1.5 py-0.5 rounded-md", cls)}>
      {tag}
    </span>
  );
}

// ---------------------------------------------------------------------------
// Entry card
// ---------------------------------------------------------------------------

function EntryCard({ entry, isFirst }: { entry: ChangelogEntry; isFirst: boolean }) {
  const [expanded, setExpanded] = useState(isFirst);

  return (
    <div
      className={cn(
        "border rounded-2xl overflow-hidden transition-colors",
        isFirst
          ? "border-teal-500/25 bg-teal-500/5"
          : "border-white/6 bg-white/2 hover:bg-white/4"
      )}
    >
      <button
        onClick={() => setExpanded(e => !e)}
        className="w-full flex items-start gap-3 px-4 py-3 text-left"
      >
        {/* Version badge */}
        <span
          className={cn(
            "flex-shrink-0 mt-0.5 text-[10px] font-bold px-2 py-0.5 rounded-lg",
            isFirst
              ? "bg-teal-500/20 text-teal-300"
              : "bg-white/6 text-white/35"
          )}
        >
          v{entry.version}
        </span>

        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2 mb-0.5">
            <p className="text-sm font-semibold text-white/85 truncate">{entry.title}</p>
            {isFirst && (
              <span className="flex-shrink-0 text-[9px] font-bold bg-teal-500/25 text-teal-300 px-1.5 py-0.5 rounded-full uppercase tracking-wider">
                Latest
              </span>
            )}
          </div>
          <div className="flex items-center gap-2 text-[10px] text-white/30">
            <Calendar size={9} />
            <span>{entry.date}</span>
          </div>
        </div>

        <ChevronRight
          size={13}
          className={cn(
            "flex-shrink-0 mt-0.5 text-white/25 transition-transform",
            expanded && "rotate-90"
          )}
        />
      </button>

      {expanded && (
        <div className="px-4 pb-4 border-t border-white/5 pt-3 space-y-3">
          {/* Summary */}
          <p className="text-xs text-white/45 leading-relaxed">{entry.summary}</p>

          {/* Items */}
          {entry.items.length > 0 && (
            <ul className="space-y-2">
              {entry.items.map((item, i) => (
                <li key={i} className="flex gap-2">
                  <span className="w-1 h-1 rounded-full bg-teal-500/50 flex-shrink-0 mt-[5px]" />
                  <div>
                    <span className="text-xs font-semibold text-white/75">{item.title}</span>
                    {item.detail && (
                      <span className="text-xs text-white/35"> — {item.detail}</span>
                    )}
                  </div>
                </li>
              ))}
            </ul>
          )}

          {/* Tags */}
          {entry.tags.length > 0 && (
            <div className="flex items-center gap-1.5 flex-wrap pt-1">
              <Tag size={9} className="text-white/20" />
              {entry.tags.map(t => <TagBadge key={t} tag={t} />)}
            </div>
          )}
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Gift icon button (exported for TopBar)
// ---------------------------------------------------------------------------

export function ChangelogGiftButton({ onClick, hasUnread }: { onClick: () => void; hasUnread: boolean }) {
  return (
    <button
      onClick={onClick}
      title="What's new"
      className="relative w-8 h-8 rounded-lg hover:bg-white/5 flex items-center justify-center text-white/40 hover:text-white/70 transition-colors"
    >
      <Gift size={15} />
      {hasUnread && (
        <span className="absolute top-1 right-1 w-2 h-2 rounded-full bg-teal-400 ring-2 ring-white" />
      )}
    </button>
  );
}

// ---------------------------------------------------------------------------
// Main modal
// ---------------------------------------------------------------------------

export function ChangelogModal() {
  const [open, setOpen] = useState(false);
  const [hasUnread, setHasUnread] = useState(false);

  const { data, isLoading } = useQuery<ChangelogResponse>({
    queryKey: ["changelog"],
    queryFn: () => api.get("/changelog").then(r => r.data),
    staleTime: 5 * 60_000,
    refetchOnWindowFocus: false,
  });

  // Detect unread once data is available
  useEffect(() => {
    if (data?.latest_version) {
      const lastSeen = getLastSeen();
      if (data.latest_version !== lastSeen) {
        setHasUnread(true);
      }
    }
  }, [data?.latest_version]);

  const handleOpen = useCallback(() => {
    setOpen(true);
    setHasUnread(false);
    if (data?.latest_version) {
      markSeen(data.latest_version);
    }
  }, [data?.latest_version]);

  // Mark seen when data arrives with modal already open
  useEffect(() => {
    if (open && data?.latest_version) {
      markSeen(data.latest_version);
      setHasUnread(false);
    }
  }, [open, data?.latest_version]);

  return (
    <>
      <ChangelogGiftButton onClick={handleOpen} hasUnread={hasUnread} />

      {open && (
        <div className="fixed inset-0 z-50 flex items-start justify-end">
          {/* Backdrop */}
          <div
            className="absolute inset-0 bg-black/40 backdrop-blur-sm"
            onClick={() => setOpen(false)}
          />

          {/* Panel */}
          <div
            className="relative z-10 w-full max-w-sm h-full flex flex-col shadow-2xl shadow-black/60"
            style={{
              backgroundColor: "#0a1929",
              borderLeft: "1px solid rgba(255,255,255,0.07)",
            }}
          >
            {/* Header */}
            <div
              className="flex items-center gap-3 px-5 py-4 border-b border-white/6 flex-shrink-0"
              style={{ backgroundColor: "rgba(20,184,166,0.05)" }}
            >
              <div className="w-8 h-8 rounded-xl bg-teal-500/15 flex items-center justify-center">
                <Sparkles size={14} className="text-teal-400" />
              </div>
              <div className="flex-1">
                <h2 className="text-sm font-bold text-white/90">What&apos;s new</h2>
                <p className="text-[10px] text-white/35">Release notes &amp; feature updates</p>
              </div>
              <button
                onClick={() => setOpen(false)}
                className="w-7 h-7 rounded-lg hover:bg-white/8 flex items-center justify-center text-white/30 hover:text-white/60 transition-colors"
              >
                <X size={14} />
              </button>
            </div>

            {/* Content */}
            <div className="flex-1 overflow-y-auto px-4 py-4 space-y-3">
              {isLoading && (
                <div className="space-y-3">
                  {[1, 2, 3].map(i => (
                    <div key={i} className="h-16 rounded-2xl bg-white/4 animate-pulse" />
                  ))}
                </div>
              )}

              {!isLoading && (!data || data.entries.length === 0) && (
                <div className="flex flex-col items-center justify-center py-16 text-center">
                  <Gift size={28} className="text-white/15 mb-3" />
                  <p className="text-sm text-white/30">No updates yet</p>
                  <p className="text-xs text-white/20 mt-1">Check back soon for new features</p>
                </div>
              )}

              {!isLoading && data?.entries.map((entry, i) => (
                <EntryCard key={entry.slug} entry={entry} isFirst={i === 0} />
              ))}
            </div>

            {/* Footer */}
            <div className="px-5 py-3 border-t border-white/6 flex-shrink-0">
              <p className="text-[10px] text-white/20 text-center">
                {data?.count ?? 0} release{(data?.count ?? 0) !== 1 ? "s" : ""} · HAIP Platform
              </p>
            </div>
          </div>
        </div>
      )}
    </>
  );
}
