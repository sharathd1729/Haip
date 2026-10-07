"use client";

/**
 * X6 — Command palette (Cmd+K / Ctrl+K)
 *
 * Built without cmdk dependency — lightweight custom implementation.
 * Searches: pages, guests, conversations, recent calls, actions.
 * Grouped results with keyboard navigation (↑↓ Enter Escape).
 *
 * Mount in dashboard/layout.tsx:
 *   <CommandPalette />
 */

import { useState, useEffect, useRef, useCallback } from "react";
import { useRouter } from "next/navigation";
import { useQuery } from "@tanstack/react-query";
import { Search, MessageSquare, Phone, Users, Settings, BarChart2, Shield, FileText, Inbox, ArrowRight, Clock, User, Building2, HelpCircle } from "@/lib/icons";
import { cn } from "@/lib/utils";
import api from "@/lib/api";

// ── Static page items ──────────────────────────────────────────────────────────

const PAGES = [
  // "dashboard" and "analytics" entries removed 2026-08-08 -- deactivated,
  // being rebuilt from scratch.
  { id: "inbox",        label: "Inbox",              href: "/dashboard/inbox",            icon: <Inbox size={14} />,            group: "Pages" },
  { id: "calls",        label: "Calls",              href: "/dashboard/calls",            icon: <Phone size={14} />,            group: "Pages" },
  { id: "leads",        label: "Leads",              href: "/dashboard/leads",            icon: <FileText size={14} />,         group: "Pages" },
  { id: "guests",       label: "Bookings",           href: "/dashboard/bookings",           icon: <Users size={14} />,            group: "Pages" },
  { id: "properties",   label: "Properties",         href: "/dashboard/properties",       icon: <Building2 size={14} />,        group: "Pages" },
  { id: "qa",           label: "QA Scores",          href: "/dashboard/qa",               icon: <BarChart2 size={14} />,        group: "Pages" },
  { id: "compliance",   label: "Compliance",         href: "/dashboard/compliance",       icon: <Shield size={14} />,           group: "Pages" },
  { id: "settings",     label: "Settings",           href: "/dashboard/settings",         icon: <Settings size={14} />,         group: "Pages" },
  { id: "integrations", label: "Integrations",       href: "/dashboard/settings/integrations", icon: <Settings size={14} />, group: "Pages" },
  { id: "team",         label: "Team members",       href: "/dashboard/settings/team",    icon: <Users size={14} />,            group: "Pages" },
  { id: "templates",    label: "Saved replies",      href: "/dashboard/settings/saved-replies", icon: <MessageSquare size={14} />, group: "Pages" },
  { id: "meta-quality", label: "Meta WABA quality",  href: "/dashboard/settings/integrations/meta-quality", icon: <Settings size={14} />, group: "Pages" },
  { id: "grievance",    label: "Grievance form",     href: "/grievance",                  icon: <HelpCircle size={14} />,       group: "Pages" },
];

const ACTIONS = [
  { id: "new-inquiry",  label: "New lead",           href: "/dashboard/leads",            icon: <FileText size={14} />,         group: "Actions" },
  { id: "invite-team",  label: "Invite teammate",    href: "/dashboard/settings/team",    icon: <Users size={14} />,            group: "Actions" },
  { id: "new-template", label: "New saved reply",    href: "/dashboard/settings/saved-replies", icon: <MessageSquare size={14} />, group: "Actions" },
  { id: "connect-wa",   label: "Connect WhatsApp",   href: "/dashboard/settings/integrations", icon: <MessageSquare size={14} />, group: "Actions" },
];

interface ResultItem {
  id: string;
  label: string;
  subtitle?: string;
  href: string;
  icon: React.ReactNode;
  group: string;
}

function fuzzyMatch(query: string, text: string): boolean {
  if (!query) return true;
  const q = query.toLowerCase();
  const t = text.toLowerCase();
  if (t.includes(q)) return true;
  // character-by-character fuzzy
  let qi = 0;
  for (let i = 0; i < t.length && qi < q.length; i++) {
    if (t[i] === q[qi]) qi++;
  }
  return qi === q.length;
}

export function CommandPalette() {
  const router = useRouter();
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState("");
  const [cursor, setCursor] = useState(0);
  const inputRef = useRef<HTMLInputElement>(null);

  // Backend search for guests + conversations
  const { data: backendResults = [] } = useQuery<ResultItem[]>({
    queryKey: ["cmd-search", query],
    queryFn: async () => {
      if (query.length < 2) return [];
      const [guests, convs] = await Promise.allSettled([
        api.get(`/guests?q=${encodeURIComponent(query)}&limit=4`).then(r => r.data),
        api.get(`/conversations/search?q=${encodeURIComponent(query)}&limit=4`).then(r => r.data),
      ]);
      const results: ResultItem[] = [];
      if (guests.status === "fulfilled") {
        for (const g of (guests.value as any[])) {
          results.push({
            id: `guest-${g.id}`,
            label: g.name || g.phone,
            subtitle: g.phone,
            href: `/dashboard/bookings?guest=${g.id}`,
            icon: <User size={14} />,
            group: "Guests",
          });
        }
      }
      if (convs.status === "fulfilled") {
        for (const c of (convs.value as any[])) {
          results.push({
            id: `conv-${c.conversation_id}`,
            label: c.guest_name || c.guest_phone,
            subtitle: c.snippet?.slice(0, 60),
            href: `/dashboard/inbox`,
            icon: <MessageSquare size={14} />,
            group: "Conversations",
          });
        }
      }
      return results;
    },
    enabled: open && query.length >= 2,
    staleTime: 5_000,
  });

  // Static filtered results
  const staticResults: ResultItem[] = query
    ? [
        ...PAGES.filter(p => fuzzyMatch(query, p.label)),
        ...ACTIONS.filter(a => fuzzyMatch(query, a.label)),
      ]
    : [...PAGES.slice(0, 6), ...ACTIONS];

  const allResults: ResultItem[] = [
    ...(query.length >= 2 ? backendResults : []),
    ...staticResults,
  ];

  // Group
  const grouped: Record<string, ResultItem[]> = {};
  for (const item of allResults) {
    if (!grouped[item.group]) grouped[item.group] = [];
    if (!grouped[item.group].find(r => r.id === item.id)) {
      grouped[item.group].push(item);
    }
  }
  const flat = Object.values(grouped).flat();

  // Keyboard listener
  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key === "k") {
        e.preventDefault();
        setOpen(v => !v);
        setQuery("");
        setCursor(0);
      }
      if (!open) return;
      if (e.key === "Escape") { setOpen(false); return; }
      if (e.key === "ArrowDown") { e.preventDefault(); setCursor(c => Math.min(c + 1, flat.length - 1)); }
      if (e.key === "ArrowUp") { e.preventDefault(); setCursor(c => Math.max(c - 1, 0)); }
      if (e.key === "Enter" && flat[cursor]) {
        router.push(flat[cursor].href);
        setOpen(false);
      }
    };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, [open, cursor, flat, router]);

  useEffect(() => {
    if (open) setTimeout(() => inputRef.current?.focus(), 50);
  }, [open]);

  useEffect(() => { setCursor(0); }, [query]);

  if (!open) return null;

  let flatIdx = 0;

  return (
    <>
      {/* Backdrop */}
      <div
        className="fixed inset-0 z-50 bg-black/50 backdrop-blur-sm"
        onClick={() => setOpen(false)}
      />

      {/* Palette */}
      <div className="fixed top-[20vh] left-1/2 -translate-x-1/2 z-50 w-full max-w-xl px-4">
        <div className="bg-white rounded-2xl shadow-2xl border border-gray-200 overflow-hidden">
          {/* Search input */}
          <div className="flex items-center gap-3 px-4 py-3.5 border-b border-gray-100">
            <Search size={16} className="text-gray-400 flex-shrink-0" />
            <input
              ref={inputRef}
              value={query}
              onChange={e => setQuery(e.target.value)}
              placeholder="Search pages, guests, conversations…"
              className="flex-1 text-sm text-gray-800 placeholder:text-gray-400 outline-none bg-transparent"
            />
            <kbd className="hidden sm:flex items-center gap-0.5 text-[10px] text-gray-400 bg-gray-100 rounded px-1.5 py-0.5 font-mono">
              Esc
            </kbd>
          </div>

          {/* Results */}
          <div className="max-h-80 overflow-y-auto py-2">
            {flat.length === 0 ? (
              <p className="text-sm text-gray-400 text-center py-8">No results for &quot;{query}&quot;</p>
            ) : (
              Object.entries(grouped).map(([group, items]) => (
                <div key={group}>
                  <p className="text-[10px] font-bold uppercase tracking-wider text-gray-400 px-4 py-1.5">{group}</p>
                  {items.map(item => {
                    const idx = flatIdx++;
                    const isActive = cursor === idx;
                    return (
                      <button
                        key={item.id}
                        onClick={() => { router.push(item.href); setOpen(false); }}
                        onMouseEnter={() => setCursor(idx)}
                        className={cn(
                          "w-full flex items-center gap-3 px-4 py-2.5 text-left transition-colors",
                          isActive ? "bg-teal-50" : "hover:bg-gray-50"
                        )}
                      >
                        <span className={cn("flex-shrink-0", isActive ? "text-teal-600" : "text-gray-400")}>
                          {item.icon}
                        </span>
                        <div className="flex-1 min-w-0">
                          <p className={cn("text-sm font-medium truncate", isActive ? "text-teal-700" : "text-gray-800")}>
                            {item.label}
                          </p>
                          {item.subtitle && (
                            <p className="text-xs text-gray-400 truncate">{item.subtitle}</p>
                          )}
                        </div>
                        {isActive && <ArrowRight size={13} className="text-teal-500 flex-shrink-0" />}
                      </button>
                    );
                  })}
                </div>
              ))
            )}
          </div>

          {/* Footer */}
          <div className="px-4 py-2.5 border-t border-gray-100 flex items-center gap-4 text-[10px] text-gray-400">
            <span className="flex items-center gap-1"><kbd className="bg-gray-100 rounded px-1 py-0.5 font-mono">↑↓</kbd> navigate</span>
            <span className="flex items-center gap-1"><kbd className="bg-gray-100 rounded px-1 py-0.5 font-mono">↵</kbd> open</span>
            <span className="flex items-center gap-1"><kbd className="bg-gray-100 rounded px-1 py-0.5 font-mono">Esc</kbd> close</span>
            <span className="ml-auto flex items-center gap-1">
              <Clock size={10} />
              {flat.length} result{flat.length !== 1 ? "s" : ""}
            </span>
          </div>
        </div>
      </div>
    </>
  );
}
