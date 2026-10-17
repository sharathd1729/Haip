"use client";
import { useState, useEffect, useRef } from "react";
import { useQuery, useMutation } from "@tanstack/react-query";
import Fuse from "fuse.js";
import { cn } from "@/lib/utils";
import api from "@/lib/api";

interface SavedReply {
  id: string;
  title: string;
  body: string;
  usage_count: number;
  language: string;
}

interface MergeContext {
  guest_name?: string;
  property_name?: string;
  check_in?: string;
  check_out?: string;
  owner_name?: string;
}

/** Pure function: replace {{field}} with context values; unresolved fields stay highlighted via marker */
export function resolveMergeFields(body: string, ctx: MergeContext): string {
  return body
    .replace(/\{\{guest\.name\}\}/g,    ctx.guest_name    ?? "{{guest.name}}")
    .replace(/\{\{property\.name\}\}/g, ctx.property_name ?? "{{property.name}}")
    .replace(/\{\{check_in\}\}/g,       ctx.check_in      ?? "{{check_in}}")
    .replace(/\{\{check_out\}\}/g,      ctx.check_out     ?? "{{check_out}}")
    .replace(/\{\{owner\.name\}\}/g,    ctx.owner_name    ?? "{{owner.name}}");
}

interface SavedReplyMenuProps {
  query: string;
  context: MergeContext;
  onSelect: (resolved: string) => void;
  onClose: () => void;
  anchorRef: React.RefObject<HTMLElement | null>;
}

export function SavedReplyMenu({ query, context, onSelect, onClose, anchorRef }: SavedReplyMenuProps) {
  const [activeIdx, setActiveIdx] = useState(0);

  const { data: replies = [] } = useQuery<SavedReply[]>({
    queryKey: ["saved-replies"],
    queryFn: () => api.get("/saved-replies").then(r => r.data),
    staleTime: 60_000,
  });

  const useMutation_ = useMutation({
    mutationFn: (id: string) => api.post(`/saved-replies/${id}/use`, {}),
  });

  const fuse = new Fuse(replies, { keys: ["title", "body"], threshold: 0.4 });
  const results: SavedReply[] =
    query.length > 1
      ? fuse.search(query).map(r => r.item).slice(0, 8)
      : [...replies].sort((a, b) => b.usage_count - a.usage_count).slice(0, 8);

  useEffect(() => { setActiveIdx(0); }, [query]);

  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if (e.key === "ArrowDown") { e.preventDefault(); setActiveIdx(i => Math.min(i + 1, results.length - 1)); }
      if (e.key === "ArrowUp")   { e.preventDefault(); setActiveIdx(i => Math.max(i - 1, 0)); }
      if (e.key === "Enter")     { e.preventDefault(); if (results[activeIdx]) pick(results[activeIdx]); }
      if (e.key === "Escape")    { onClose(); }
    };
    document.addEventListener("keydown", handler);
    return () => document.removeEventListener("keydown", handler);
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [results, activeIdx]);

  function pick(reply: SavedReply) {
    useMutation_.mutate(reply.id);
    onSelect(resolveMergeFields(reply.body, context));
    onClose();
  }

  if (results.length === 0) return null;

  return (
    <div className="absolute bottom-full left-0 mb-1 w-80 haip-card shadow-xl overflow-hidden z-50">
      <div className="px-3 py-2 border-b border-[var(--haip-border)]">
        <span className="text-[10px] font-bold uppercase tracking-wider text-[var(--haip-fg-subtle)]">Saved replies</span>
      </div>
      <div className="max-h-56 overflow-y-auto">
        {results.map((r, i) => (
          <button
            key={r.id}
            onMouseDown={e => { e.preventDefault(); pick(r); }}
            className={cn(
              "w-full text-left px-3 py-2.5 transition-colors border-b border-[var(--haip-border)] last:border-0",
              i === activeIdx ? "bg-[var(--haip-primary-tint)]" : "hover:bg-[var(--haip-surface)]"
            )}
          >
            <p className="text-xs font-semibold text-[var(--haip-fg)] truncate">{r.title}</p>
            <p className="text-[11px] text-[var(--haip-fg-subtle)] truncate mt-0.5">{r.body}</p>
          </button>
        ))}
      </div>
      <div className="px-3 py-1.5 border-t border-[var(--haip-border)] bg-[var(--haip-surface)]">
        <span className="text-[10px] text-[var(--haip-fg-subtle)]">↑↓ navigate · Enter to insert · Esc to close</span>
      </div>
    </div>
  );
}
