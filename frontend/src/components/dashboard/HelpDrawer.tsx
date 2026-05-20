"use client";

import { useState } from "react";
import {
  HelpCircle, X, MessageSquare, PlayCircle,
  Search, ExternalLink, Phone, Mail, ChevronRight,
} from "lucide-react";
import { cn } from "@/lib/utils";

// ---------------------------------------------------------------------------
// Static video catalogue
// ---------------------------------------------------------------------------

interface Video {
  id: string;
  title: string;
  duration: string;
  category: string;
  href: string;
}

const VIDEOS: Video[] = [
  { id: "v1", title: "Getting started: brand setup & first property", duration: "3:12", category: "Onboarding", href: "https://www.loom.com/share/haip-onboarding" },
  { id: "v2", title: "Connecting your WhatsApp number", duration: "2:45", category: "Onboarding", href: "https://www.loom.com/share/haip-whatsapp" },
  { id: "v3", title: "Setting up IVR with Acefone", duration: "4:01", category: "Onboarding", href: "https://www.loom.com/share/haip-acefone" },
  { id: "v4", title: "How AI scoring works", duration: "5:30", category: "Calls & QA", href: "https://www.loom.com/share/haip-scoring" },
  { id: "v5", title: "Reviewing call transcripts & rubrics", duration: "3:55", category: "Calls & QA", href: "https://www.loom.com/share/haip-rubrics" },
  { id: "v6", title: "Using the Inbox: approve & send AI drafts", duration: "4:20", category: "Inbox", href: "https://www.loom.com/share/haip-inbox" },
  { id: "v7", title: "Managing the inquiry pipeline (Kanban)", duration: "3:40", category: "CRM", href: "https://www.loom.com/share/haip-kanban" },
  { id: "v8", title: "Guest 360: timeline, tags, and DPDP", duration: "2:58", category: "CRM", href: "https://www.loom.com/share/haip-guest360" },
  { id: "v9", title: "DPDP compliance: consents & deletion requests", duration: "5:10", category: "Compliance", href: "https://www.loom.com/share/haip-dpdp" },
  { id: "v10", title: "Analytics: reading the owner dashboard", duration: "4:45", category: "Analytics", href: "https://www.loom.com/share/haip-analytics" },
];

const CATEGORIES = ["All", ...Array.from(new Set(VIDEOS.map(v => v.category)))];

// ---------------------------------------------------------------------------
// Help button (exported for TopBar)
// ---------------------------------------------------------------------------

export function HelpButton({ onClick }: { onClick: () => void }) {
  return (
    <button
      onClick={onClick}
      title="Help & support"
      className="w-8 h-8 rounded-lg hover:bg-white/5 flex items-center justify-center text-white/40 hover:text-white/70 transition-colors"
    >
      <HelpCircle size={15} />
    </button>
  );
}

// ---------------------------------------------------------------------------
// Main drawer
// ---------------------------------------------------------------------------

export function HelpDrawer() {
  const [open, setOpen] = useState(false);
  const [tab, setTab] = useState<"videos" | "contact">("videos");
  const [query, setQuery] = useState("");
  const [filterCat, setFilterCat] = useState("All");

  const filtered = VIDEOS.filter(v => {
    const matchesQuery =
      query === "" ||
      v.title.toLowerCase().includes(query.toLowerCase()) ||
      v.category.toLowerCase().includes(query.toLowerCase());
    const matchesCat = filterCat === "All" || v.category === filterCat;
    return matchesQuery && matchesCat;
  });

  // WhatsApp deep link — opens a WA chat with the HAIP support number
  const WA_SUPPORT_NUMBER = "919876543210"; // replace with real number
  const WA_MESSAGE = encodeURIComponent("Hi HAIP team, I need help with:");
  const waHref = `https://wa.me/${WA_SUPPORT_NUMBER}?text=${WA_MESSAGE}`;

  return (
    <>
      <HelpButton onClick={() => setOpen(true)} />

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
            <div className="flex items-center gap-3 px-5 py-4 border-b border-white/6 flex-shrink-0">
              <div className="w-8 h-8 rounded-xl bg-blue-500/12 flex items-center justify-center">
                <HelpCircle size={14} className="text-blue-400" />
              </div>
              <div className="flex-1">
                <h2 className="text-sm font-bold text-white/90">Help & support</h2>
                <p className="text-[10px] text-white/35">Walkthroughs and direct support</p>
              </div>
              <button
                onClick={() => setOpen(false)}
                className="w-7 h-7 rounded-lg hover:bg-white/8 flex items-center justify-center text-white/30 hover:text-white/60 transition-colors"
              >
                <X size={14} />
              </button>
            </div>

            {/* Tabs */}
            <div className="flex border-b border-white/6 flex-shrink-0">
              {(["videos", "contact"] as const).map(t => (
                <button
                  key={t}
                  onClick={() => setTab(t)}
                  className={cn(
                    "flex-1 py-2.5 text-xs font-semibold transition-colors capitalize",
                    tab === t
                      ? "text-teal-400 border-b-2 border-teal-500"
                      : "text-white/35 hover:text-white/60"
                  )}
                >
                  {t === "videos" ? "Video walkthroughs" : "Talk to us"}
                </button>
              ))}
            </div>

            {/* Content */}
            <div className="flex-1 overflow-y-auto">
              {/* ── Videos tab ── */}
              {tab === "videos" && (
                <div className="p-4 space-y-3">
                  {/* Search */}
                  <div className="relative">
                    <Search size={12} className="absolute left-3 top-1/2 -translate-y-1/2 text-white/25" />
                    <input
                      value={query}
                      onChange={e => setQuery(e.target.value)}
                      placeholder="Search walkthroughs…"
                      className="w-full pl-8 pr-3 py-2 text-xs rounded-xl bg-white/5 border border-white/8 text-white/70 placeholder:text-white/20 focus:outline-none focus:border-white/20"
                    />
                  </div>

                  {/* Category filter pills */}
                  <div className="flex gap-1.5 flex-wrap">
                    {CATEGORIES.map(cat => (
                      <button
                        key={cat}
                        onClick={() => setFilterCat(cat)}
                        className={cn(
                          "text-[10px] font-semibold px-2 py-0.5 rounded-lg transition-colors",
                          filterCat === cat
                            ? "bg-teal-500/20 text-teal-300"
                            : "bg-white/5 text-white/30 hover:text-white/60"
                        )}
                      >
                        {cat}
                      </button>
                    ))}
                  </div>

                  {/* Video list */}
                  {filtered.length === 0 && (
                    <div className="py-10 text-center">
                      <PlayCircle size={24} className="mx-auto text-white/15 mb-2" />
                      <p className="text-xs text-white/30">No videos match your search</p>
                    </div>
                  )}

                  <div className="space-y-1.5">
                    {filtered.map(video => (
                      <a
                        key={video.id}
                        href={video.href}
                        target="_blank"
                        rel="noopener noreferrer"
                        className="flex items-center gap-3 px-3 py-2.5 rounded-xl bg-white/3 hover:bg-white/6 border border-white/4 hover:border-white/10 transition-all group"
                      >
                        <div className="w-7 h-7 rounded-lg bg-blue-500/10 flex items-center justify-center flex-shrink-0 group-hover:bg-blue-500/20 transition-colors">
                          <PlayCircle size={13} className="text-blue-400" />
                        </div>
                        <div className="flex-1 min-w-0">
                          <p className="text-xs text-white/70 font-medium leading-tight truncate group-hover:text-white/90 transition-colors">
                            {video.title}
                          </p>
                          <p className="text-[10px] text-white/25 mt-0.5">
                            {video.category} · {video.duration}
                          </p>
                        </div>
                        <ExternalLink size={11} className="text-white/20 flex-shrink-0 group-hover:text-white/50 transition-colors" />
                      </a>
                    ))}
                  </div>
                </div>
              )}

              {/* ── Contact tab ── */}
              {tab === "contact" && (
                <div className="p-4 space-y-3">
                  {/* WhatsApp — primary CTA */}
                  <a
                    href={waHref}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="flex items-center gap-3 p-4 rounded-2xl border border-green-500/25 bg-green-500/8 hover:bg-green-500/14 transition-colors group"
                  >
                    <div className="w-10 h-10 rounded-xl bg-green-500/15 flex items-center justify-center flex-shrink-0">
                      <MessageSquare size={18} className="text-green-400" />
                    </div>
                    <div className="flex-1">
                      <p className="text-sm font-semibold text-green-300">Chat on WhatsApp</p>
                      <p className="text-xs text-white/35 mt-0.5">Fastest response · Typically replies in minutes</p>
                    </div>
                    <ChevronRight size={14} className="text-green-400/50 group-hover:text-green-400 transition-colors" />
                  </a>

                  {/* Email */}
                  <a
                    href="mailto:support@haip.app"
                    className="flex items-center gap-3 p-4 rounded-2xl border border-white/8 bg-white/3 hover:bg-white/6 transition-colors group"
                  >
                    <div className="w-10 h-10 rounded-xl bg-white/5 flex items-center justify-center flex-shrink-0">
                      <Mail size={16} className="text-white/40" />
                    </div>
                    <div className="flex-1">
                      <p className="text-sm font-semibold text-white/70">Email support</p>
                      <p className="text-xs text-white/30 mt-0.5">support@haip.app · Reply within 24 hours</p>
                    </div>
                    <ChevronRight size={14} className="text-white/20 group-hover:text-white/50 transition-colors" />
                  </a>

                  {/* Schedule call */}
                  <a
                    href="https://cal.com/haip/onboarding"
                    target="_blank"
                    rel="noopener noreferrer"
                    className="flex items-center gap-3 p-4 rounded-2xl border border-white/8 bg-white/3 hover:bg-white/6 transition-colors group"
                  >
                    <div className="w-10 h-10 rounded-xl bg-white/5 flex items-center justify-center flex-shrink-0">
                      <Phone size={16} className="text-white/40" />
                    </div>
                    <div className="flex-1">
                      <p className="text-sm font-semibold text-white/70">Schedule a call</p>
                      <p className="text-xs text-white/30 mt-0.5">Free 30-min onboarding session with our team</p>
                    </div>
                    <ExternalLink size={13} className="text-white/20 group-hover:text-white/50 transition-colors" />
                  </a>

                  {/* Divider */}
                  <div className="h-px bg-white/6 my-2" />

                  {/* Docs link */}
                  <div className="space-y-1.5">
                    <p className="text-[10px] font-bold text-white/25 uppercase tracking-wider">Self-serve resources</p>
                    {[
                      { label: "Documentation", href: "https://docs.haip.app" },
                      { label: "API reference", href: "https://docs.haip.app/api" },
                      { label: "Status page", href: "https://status.haip.app" },
                      { label: "Changelog", href: "https://haip.app/changelog" },
                    ].map(link => (
                      <a
                        key={link.label}
                        href={link.href}
                        target="_blank"
                        rel="noopener noreferrer"
                        className="flex items-center justify-between px-3 py-2 rounded-xl text-xs text-white/45 hover:text-white/75 hover:bg-white/5 transition-colors"
                      >
                        {link.label}
                        <ExternalLink size={10} className="text-white/20" />
                      </a>
                    ))}
                  </div>
                </div>
              )}
            </div>

            {/* Footer */}
            <div className="px-5 py-3 border-t border-white/6 flex-shrink-0">
              <p className="text-[10px] text-white/20 text-center">
                HAIP Support · Mon–Sat 9am–6pm IST
              </p>
            </div>
          </div>
        </div>
      )}
    </>
  );
}
